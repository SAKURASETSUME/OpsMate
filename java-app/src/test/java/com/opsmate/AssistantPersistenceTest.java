package com.opsmate;

import com.opsmate.assistant.*;
import com.opsmate.infrastructure.*;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class AssistantPersistenceTest {
    @Autowired AssistantStore store;
    @Autowired JdbcTemplate db;
    @Autowired RuntimePaths paths;
    @Autowired WorkspaceService workspace;

    @Test void proposalsDoNotWriteUntilConfirmedAndCannotReplay() throws Exception {
        String filename="提案-"+System.nanoTime()+".txt";
        long session=store.saveTurn(null,"测试文件",List.of(Map.of("tool","write_file","args",Map.of("filename",filename,"content","你好\n"),"result","等待用户确认")),"已提交",List.of(),"");
        Path target=paths.data().resolve("agent_files").resolve(filename);
        try {
            assertFalse(Files.exists(target));
            assertTrue(store.resolve(session,filename,true).contains("已写入"));
            assertEquals("你好\n",Files.readString(target,java.nio.charset.StandardCharsets.UTF_8));
            assertThrows(ApiFailure.class,() -> store.resolve(session,filename,true));
            assertThrows(ApiFailure.class,() -> store.resolve(session,"../outside.txt",true));
        } finally { store.delete(session); Files.deleteIfExists(target); }
    }
    @Test void attachmentOwnershipFailureRollsBackEntireTurnAndDeleteCleansFile() {
        long file=((Number)store.upload("中文.conf","text/plain","中文".getBytes(java.nio.charset.StandardCharsets.UTF_8)).get("id")).longValue();
        Path path=store.attachmentPath(store.attachment(file));
        long session=store.saveTurn(null,"附件轮",List.of(),"已读取",List.of(file),"");
        try {
            int count=store.messages(session).size();
            assertThrows(ApiFailure.class,() -> store.saveTurn(session,"不应保存",List.of(),"不应保存",List.of(file),""));
            assertEquals(count,store.messages(session).size());
            assertTrue(store.history(session).getFirst().get("content").toString().contains("中文"));
        } finally { store.delete(session); }
        assertFalse(Files.exists(path));
        assertEquals(0,db.queryForObject("SELECT count(*) FROM assistant_attachments WHERE id=?",Integer.class,file));
    }
    @Test void secretMaskingAndUtf8Boundary() {
        String secret="sk-"+"a".repeat(48);
        long id=store.saveTurn(null,"配置 "+secret,List.of(),"回复 "+secret,List.of(),"");
        try {
            assertFalse(store.messages(id).toString().contains(secret));
            assertFalse(store.sessions(null).toString().contains(secret));
            ApiFailure error=assertThrows(ApiFailure.class,() -> store.upload("bad.txt","text/plain",new byte[]{(byte)0xff}));
            assertEquals(415,error.status());
            assertEquals(413,assertThrows(ApiFailure.class,() -> store.upload("big.txt","text/plain",new byte[5*1024*1024+1])).status());
        } finally { store.delete(id); }
    }
    @Test void workspaceParentTraversalIsRejectedAndRevocationUngroups() throws Exception {
        var old=workspace.directories();
        Path root=Files.createTempDirectory(paths.data(),"workspace-");
        long id=store.saveTurn(null,"工作区",List.of(),"好",List.of(),root.toRealPath().toString());
        try {
            workspace.save(List.of(root.toString()));
            assertEquals(root.resolve("子目录/new.txt").toAbsolutePath(),workspace.resolve("子目录/new.txt",false));
            assertThrows(ApiFailure.class,() -> workspace.resolve("../outside.txt",false));
            workspace.save(List.of());
            assertTrue(store.sessions("__none__").stream().anyMatch(row -> ((Number)row.get("id")).longValue()==id));
        } finally { workspace.save(old); store.delete(id); Files.deleteIfExists(root); }
    }
}
