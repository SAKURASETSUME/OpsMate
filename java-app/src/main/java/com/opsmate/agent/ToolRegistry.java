package com.opsmate.agent;

import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class ToolRegistry {
    private final Map<String,AgentTool> tools=new LinkedHashMap<>();
    private final List<DynamicTools> dynamic;
    public ToolRegistry(List<AgentTool> discovered,List<DynamicTools> dynamic) {
        this.dynamic=dynamic;
        for (AgentTool tool:discovered) {
            if (tools.put(tool.name(),tool)!=null) throw new IllegalStateException("工具名称重复");
        }
    }
    public Map<String,String> dynamicDescriptions() {
        Map<String,String> result=new LinkedHashMap<>();
        for (var provider:dynamic) result.putAll(provider.descriptions());
        return result;
    }
    public Map<String,String> descriptions(Set<String> allowed) {
        Map<String,String> result=new LinkedHashMap<>();
        tools.forEach((name,tool) -> { if (allowed.contains(name)) result.put(name,tool.description()); });
        return result;
    }
    public Map<String,Object> execute(String name,Map<String,Object> args,ToolScope scope) {
        AgentTool tool=tools.get(name);
        if (tool==null) {
            for (var provider:dynamic) if (provider.accepts(name)) return provider.execute(name,args);
            return Map.of("ok",false,"error","工具不存在或未开放");
        }
        try { return tool.execute(args,scope); }
        catch (Exception failure) { return Map.of("ok",false,"error","工具参数无效或知识数据暂不可用"); }
    }
}
