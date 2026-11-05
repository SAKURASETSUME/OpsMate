package com.opsmate.logs;

import com.opsmate.agent.*;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
class LogFilterTool implements AgentTool {
    private final LogService logs;
    LogFilterTool(LogService logs) { this.logs=logs; }
    public String name() { return "filter_log"; }
    public String description() { return "只读筛选当前日志，args={log_id,q可选,level可选,regex可选,limit:1到50}"; }
    public Map<String,Object> execute(Map<String,Object> args,ToolScope scope) {
        if (scope.logId()==null||scope.logId()!=Long.parseLong(Objects.toString(args.get("log_id"),"-1")))
            return Map.of("ok",false,"error","未授权读取该日志，仅允许当前日志");
        int limit=Math.max(1,Math.min(Integer.parseInt(args.getOrDefault("limit",50).toString()),50));
        var result=logs.query(scope.logId(),Objects.toString(args.get("level"),""),Objects.toString(args.get("q"),""),
            Objects.toString(args.get("regex"),""),0,limit,"asc");
        return Map.of("ok",true,"result",bounded(result));
    }
    @SuppressWarnings("unchecked")
    static Map<String,Object> bounded(Map<String,Object> result) {
        var rows=(List<Map<String,Object>>)result.get("lines");
        return Map.of("total",result.get("total"),"lines",rows.stream().map(row -> {
            var copy=new LinkedHashMap<>(row);
            String text=row.get("text").toString();
            copy.put("text",text.substring(0,Math.min(text.length(),600)));
            return copy;
        }).toList());
    }
}
