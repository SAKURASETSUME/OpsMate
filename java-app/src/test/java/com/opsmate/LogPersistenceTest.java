package com.opsmate;

import com.opsmate.infrastructure.ApiFailure;
import com.opsmate.infrastructure.RuntimePaths;
import com.opsmate.logs.LogService;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class LogPersistenceTest {
    @Autowired LogService logs;
    @Autowired JdbcTemplate db;
    @Autowired RuntimePaths paths;

    @Test
    void failedLineBatchRollsBackWholeImport() {
        int before = db.queryForObject("SELECT count(*) FROM logs",Integer.class);
        int linesBefore = db.queryForObject("SELECT count(*) FROM log_lines",Integer.class);
        db.execute("""
            CREATE TRIGGER j3_fail BEFORE INSERT ON log_lines
            WHEN NEW.line_no=3 BEGIN SELECT RAISE(ABORT,'injected'); END
            """);
        try {
            assertThrows(DataAccessException.class,() ->
                logs.importLog("synthetic","INFO one\nINFO two\nERROR three".getBytes(StandardCharsets.UTF_8),"sample.log"));
            assertEquals(before,db.queryForObject("SELECT count(*) FROM logs",Integer.class));
            assertEquals(linesBefore,db.queryForObject("SELECT count(*) FROM log_lines",Integer.class));
        } finally {
            db.execute("DROP TRIGGER j3_fail");
        }
    }

    @Test
    void failedBackupDoesNotCommitRows() throws Exception {
        long next = db.queryForObject("SELECT coalesce((SELECT seq FROM sqlite_sequence WHERE name='logs'),0)+1",Long.class);
        var obstacle = paths.data().resolve("logs").resolve(next+".txt");
        Files.createDirectory(obstacle);
        int before = db.queryForObject("SELECT count(*) FROM logs",Integer.class);
        try {
            ApiFailure failure = assertThrows(ApiFailure.class,() ->
                logs.importLog("synthetic","ERROR failed".getBytes(StandardCharsets.UTF_8),"sample.log"));
            assertEquals(500,failure.status());
            assertEquals(before,db.queryForObject("SELECT count(*) FROM logs",Integer.class));
        } finally {
            Files.delete(obstacle);
        }
    }

    @Test
    void originalBytesAndCascadingDeleteStayConsistent() throws Exception {
        byte[] original = "\uFEFFERROR 示例\r\n    at Main.run(Main.java:42)\r\n".getBytes(StandardCharsets.UTF_8);
        long id = ((Number)logs.importLog("synthetic",original,"sample.log").get("id")).longValue();
        var backup = paths.data().resolve("logs").resolve(id+".txt");
        assertArrayEquals(original,Files.readAllBytes(backup));
        db.update("INSERT INTO reports(log_id,content) VALUES (?,?)",id,"synthetic report");
        assertEquals(2,((Number)logs.get(id).get("line_count")).intValue());
        logs.delete(id);
        assertFalse(Files.exists(backup));
        assertEquals(0,db.queryForObject("SELECT count(*) FROM reports WHERE log_id=?",Integer.class,id));
        assertEquals(0,db.queryForObject("SELECT count(*) FROM log_lines WHERE log_id=?",Integer.class,id));
        assertEquals(404,assertThrows(ApiFailure.class,() -> logs.get(id)).status());
    }
}
