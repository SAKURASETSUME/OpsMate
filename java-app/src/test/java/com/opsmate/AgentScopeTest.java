package com.opsmate;

import com.opsmate.agent.*;
import com.opsmate.logs.LogService;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class AgentScopeTest {
    @Autowired ToolRegistry tools;
    @Autowired LogService logs;

    @Test
    void toolCannotReadUnrelatedLogsOrEscapeSceneScope() {
        long first=((Number)logs.importLog("scope first","ERROR first".getBytes(StandardCharsets.UTF_8),null).get("id")).longValue();
        long second=((Number)logs.importLog("scope second","ERROR private unrelated".getBytes(StandardCharsets.UTF_8),null).get("id")).longValue();
        try {
            assertEquals(false,tools.execute("get_stats",Map.of("log_id",first),ToolScope.readOnly()).get("ok"));
            assertEquals(false,tools.execute("get_stats",Map.of("log_id",second),new ToolScope(first,null,"")).get("ok"));
            assertEquals(true,tools.execute("get_context",Map.of("log_id",first,"around",999),new ToolScope(first,null,"")).get("ok"));
        } finally {
            logs.delete(first); logs.delete(second);
        }
    }
}
