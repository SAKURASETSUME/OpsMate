package com.opsmate.codegen;

import com.opsmate.agent.*;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
class HistorySearchTool implements AgentTool {
    private final CodegenHistory history;
    HistorySearchTool(CodegenHistory history) { this.history=history; }
    public String name() { return "search_history"; }
    public String description() { return "FTS5 检索既往脚本，args={q:简短关键词,limit:1到5}；相似任务先查历史"; }
    public Map<String,Object> execute(Map<String,Object> args,ToolScope scope) {
        String q=Objects.toString(args.get("q"),"");
        if (q.isBlank()||q.length()>500) return Map.of("ok",false,"error","q 必须是 1–500 字文本");
        return Map.of("ok",true,"result",history.search(q,Integer.parseInt(args.getOrDefault("limit",5).toString())));
    }
}
