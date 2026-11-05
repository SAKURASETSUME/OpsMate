package com.opsmate.logs;

import com.opsmate.agent.*;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
class LogContextTool implements AgentTool {
    private final LogService logs;
    LogContextTool(LogService logs) { this.logs=logs; }
    public String name() { return "get_context"; }
    public String description() { return "只读当前日志行附近上下文，args={log_id,line_no,around:0到10}"; }
    public Map<String,Object> execute(Map<String,Object> args,ToolScope scope) {
        if (scope.logId()==null||scope.logId()!=Long.parseLong(Objects.toString(args.get("log_id"),"-1")))
            return Map.of("ok",false,"error","未授权读取该日志，仅允许当前日志");
        int line=Math.max(1,Integer.parseInt(args.getOrDefault("line_no",1).toString()));
        int around=Math.max(0,Math.min(Integer.parseInt(args.getOrDefault("around",10).toString()),10));
        return Map.of("ok",true,"result",LogFilterTool.bounded(logs.query(scope.logId(),"","","",Math.max(0,line-around-1),around*2+1,"asc")));
    }
}
