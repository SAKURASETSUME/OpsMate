package com.opsmate.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class AgentJson {
    private final ObjectMapper json;
    public AgentJson(ObjectMapper json) { this.json=json; }

    @SuppressWarnings("unchecked")
    public Map<String,Object> parse(String text) {
        String cleaned=text.strip().replaceAll("(?i)```(?:json)?\\s*","");
        int first=cleaned.indexOf('{');
        int last=cleaned.lastIndexOf('}');
        if (first<0||last<first) throw new IllegalStateException("模型 JSON 结构无效");
        try { return json.readValue(cleaned.substring(first,last+1),Map.class); }
        catch (Exception invalid) { throw new IllegalStateException("模型 JSON 解析失败"); }
    }

    public String encode(Object value) {
        try { return json.writeValueAsString(value); }
        catch (Exception failure) { throw new IllegalStateException("结果序列化失败"); }
    }

    public String prompt(String name) {
        try (var resource=AgentJson.class.getResourceAsStream("/prompts/"+name+".txt")) {
            if (resource==null) throw new IllegalStateException("缺少内置提示词");
            return new String(resource.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
        } catch (java.io.IOException failure) { throw new IllegalStateException("内置提示词读取失败"); }
    }
}
