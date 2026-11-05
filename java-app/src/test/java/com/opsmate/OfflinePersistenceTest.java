package com.opsmate;

import com.opsmate.kb.WorkbenchService;
import com.opsmate.infrastructure.ApiFailure;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class OfflinePersistenceTest {
    @Autowired WorkbenchService configs;
    @Autowired JdbcTemplate db;

    @Test
    void sharingIsRevokedImmediatelyAndContentIsBounded() {
        String name = "shared-" + System.nanoTime();
        long id = ((Number)configs.create(name,"text","x".repeat(5000)).get("id")).longValue();
        try {
            assertEquals(false,configs.readShared(name).get("ok"));
            configs.share(id,true);
            var result = (java.util.Map<?,?>)configs.readShared(name).get("result");
            assertEquals(4000,result.get("content").toString().length());
            assertEquals(true,result.get("truncated"));
            configs.share(id,false);
            assertEquals(false,configs.readShared(name).get("ok"));
        } finally {
            configs.delete(id);
        }
    }

    @Test
    void utf8ByteLimitRejectsOnlyBeyondBoundary() {
        String name = "boundary-" + System.nanoTime();
        String content = "中".repeat(699050) + "ab";
        long id = ((Number)configs.create(name,"text",content).get("id")).longValue();
        try {
            assertEquals(2097152,((Number)configs.get(id).get("size_bytes")).intValue());
            ApiFailure failure = assertThrows(ApiFailure.class,() -> configs.create(name,"text",content+"x"));
            assertEquals(413,failure.status());
        } finally {
            configs.delete(id);
        }
    }

    @Test
    void deployedSQLiteDriverSupportsFts5() {
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS j2_fts_probe USING fts5(content)");
        try {
            db.update("INSERT INTO j2_fts_probe(content) VALUES (?)","磁盘 disk usage");
            assertTrue(db.queryForObject("SELECT count(*) FROM j2_fts_probe WHERE j2_fts_probe MATCH ?",
                Integer.class,"disk") > 0);
        } finally {
            db.execute("DROP TABLE j2_fts_probe");
        }
    }
}
