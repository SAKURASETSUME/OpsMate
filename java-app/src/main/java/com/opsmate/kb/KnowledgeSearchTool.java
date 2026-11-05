package com.opsmate.kb;

import com.opsmate.agent.*;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
class KnowledgeSearchTool implements AgentTool {
    private final KnowledgeService knowledge;
    KnowledgeSearchTool(KnowledgeService knowledge) { this.knowledge=knowledge; }
    public String name() { return "search_kb"; }
    public String description() { return "检索本地配置知识，args={q:字符串,software:可选软件名,limit:1到5}"; }
    public Map<String,Object> execute(Map<String,Object> args,ToolScope scope) {
        String q=Objects.toString(args.get("q"),"").strip();
        if (q.isEmpty()||q.length()>500) return Map.of("ok",false,"error","q 必须是 1–500 字文本");
        int limit=Math.max(1,Math.min(Integer.parseInt(args.getOrDefault("limit",5).toString()),5));
        return Map.of("ok",true,"result",knowledge.search(q,Objects.toString(args.get("software"),"")).stream().limit(limit).toList());
    }
}
