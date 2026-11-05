package com.opsmate.logs;

import com.opsmate.agent.*;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
class LogStatsTool implements AgentTool {
    private final LogService logs;
    LogStatsTool(LogService logs) { this.logs=logs; }
    public String name() { return "get_stats"; }
    public String description() { return "只读当前日志级别及聚类统计，args={log_id}"; }
    public Map<String,Object> execute(Map<String,Object> args,ToolScope scope) {
        if (scope.logId()==null||scope.logId()!=Long.parseLong(Objects.toString(args.get("log_id"),"-1")))
            return Map.of("ok",false,"error","未授权读取该日志，仅允许当前日志");
        return Map.of("ok",true,"result",logs.stats(scope.logId()));
    }
}
