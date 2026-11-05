package com.opsmate.commands;

import com.opsmate.agent.*;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
class CommandSearchTool implements AgentTool {
    private final CommandsController commands;
    CommandSearchTool(CommandsController commands) { this.commands=commands; }
    public String name() { return "search_commands"; }
    public String description() { return "检索本地命令文档，args={q:字符串,limit:1到5}，返回简介及正文摘录"; }
    public Map<String,Object> execute(Map<String,Object> args,ToolScope scope) throws Exception {
        String q=Objects.toString(args.get("q"),"").strip();
        if (q.isEmpty()||q.length()>500) return Map.of("ok",false,"error","q 必须是 1–500 字文本");
        int limit=Math.max(1,Math.min(Integer.parseInt(args.getOrDefault("limit",5).toString()),5));
        var matches=(List<?>)commands.search(q,limit).get("items");
        List<Map<String,Object>> result=new ArrayList<>();
        for (Object item:matches) {
            Map<?,?> summary=(Map<?,?>)item;
            var detail=commands.detail(summary.get("name").toString());
            result.add(Map.of("name",summary.get("name"),"title",summary.get("title"),
                "markdown",detail.get("markdown").substring(0,Math.min(detail.get("markdown").length(),2500))));
        }
        return Map.of("ok",true,"result",result);
    }
}
