package com.opsmate;

import com.opsmate.codegen.CodegenHistory;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class CodegenTransactionTest {
    @Autowired CodegenHistory history;
    @Autowired JdbcTemplate db;

    @Test
    void failedFtsWriteRollsBackHistoryRecord() {
        int before=db.queryForObject("SELECT count(*) FROM codegen_history",Integer.class);
        db.execute("DROP TABLE codegen_history_fts");
        try {
            var result=new LinkedHashMap<>(ScriptQualityTest.valid());
            result.put("steps",List.of());
            assertThrows(DataAccessException.class,() -> history.save("synthetic","","",result,"synthetic"));
            assertEquals(before,db.queryForObject("SELECT count(*) FROM codegen_history",Integer.class));
        } finally {
            db.execute("CREATE VIRTUAL TABLE codegen_history_fts USING fts5(requirement,script,content='codegen_history',content_rowid='id')");
            db.execute("INSERT INTO codegen_history_fts(codegen_history_fts) VALUES ('rebuild')");
        }
    }
}
