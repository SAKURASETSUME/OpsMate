package com.opsmate.kb;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.springframework.stereotype.Service;
import org.yaml.snakeyaml.*;
import org.yaml.snakeyaml.constructor.SafeConstructor;
import org.yaml.snakeyaml.error.MarkedYAMLException;
import org.yaml.snakeyaml.nodes.*;

@Service
class ConfigValidator {
    private final ObjectMapper json;
    ConfigValidator(ObjectMapper json) { this.json = json; }

    private Map<String,Object> hint(int line,String text) { return Map.of("line",line,"message",text); }

    Map<String,Object> validate(String format,String content) {
        List<Map<String,Object>> errors = new ArrayList<>();
        List<Map<String,Object>> warnings = new ArrayList<>();
        String[] lines = content.isEmpty() ? new String[0] : content.split("\\R",-1);
        int count = lines.length;
        if (count>0 && lines[count-1].isEmpty()) count--;
        if (content.startsWith("\uFEFF")) warnings.add(hint(1,"文件含 UTF-8 BOM，部分解析器会报错"));
        Set<String> endings = new HashSet<>();
        var matcher = java.util.regex.Pattern.compile("\r\n|\r|\n").matcher(content);
        while (matcher.find()) {
            endings.add(matcher.group());
            if (endings.size()>1) {
                warnings.add(hint(content.substring(0,matcher.start()).split("\\R",-1).length,"混合行尾"));
                break;
            }
        }
        int trailing = 0;
        for (int i=0; i<count; i++) {
            if (!lines[i].equals(lines[i].stripTrailing()) && trailing++<20)
                warnings.add(hint(i+1,"行尾存在多余空白字符"));
            if (lines[i].length()>1000) warnings.add(hint(i+1,"超长行超过 1000 字符"));
        }
        switch (format) {
            case "yaml" -> yaml(content,errors,warnings);
            case "nginx", "keepalived" -> blocks(lines,format,errors);
            case "properties" -> properties(lines,errors,warnings);
            case "json" -> {
                try { json.reader().with(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(content); if (content.isBlank()) errors.add(hint(1,"JSON 解析错误：内容为空")); }
                catch (JsonProcessingException failure) {
                    errors.add(hint(failure.getLocation().getLineNr(),"JSON 解析错误："+failure.getOriginalMessage()));
                }
            }
            default -> { }
        }
        return Map.of("ok",errors.isEmpty(),"errors",errors,"warnings",warnings,
            "stats",Map.of("lines",count,"bytes",content.getBytes(StandardCharsets.UTF_8).length));
    }

    private void yaml(String content,List<Map<String,Object>> errors,List<Map<String,Object>> warnings) {
        LoaderOptions options = new LoaderOptions();
        options.setAllowDuplicateKeys(true);
        options.setCodePointLimit(3_000_000);
        try {
            Yaml yaml = new Yaml(new SafeConstructor(options));
            Node root = yaml.compose(new StringReader(content));
            duplicateNodes(root,warnings,Collections.newSetFromMap(new IdentityHashMap<>()));
            yaml.load(content);
        } catch (MarkedYAMLException failure) {
            errors.add(hint(failure.getProblemMark()==null ? 0 : failure.getProblemMark().getLine()+1,
                "YAML 解析错误："+failure.getProblem()));
            duplicateHeuristic(content,warnings);
        } catch (org.yaml.snakeyaml.error.YAMLException failure) {
            errors.add(hint(0,"YAML 解析错误："+failure.getMessage()));
        }
    }

    private void duplicateNodes(Node node,List<Map<String,Object>> warnings,Set<Node> visited) {
        if (node==null || !visited.add(node)) return;
        if (node instanceof MappingNode mapping) {
            Set<String> keys = new HashSet<>();
            for (NodeTuple tuple : mapping.getValue()) {
                if (tuple.getKeyNode() instanceof ScalarNode key && !keys.add(key.getValue()))
                    warnings.add(hint(key.getStartMark().getLine()+1,"重复键："+key.getValue()+"（后值覆盖）"));
                duplicateNodes(tuple.getValueNode(),warnings,visited);
            }
        } else if (node instanceof SequenceNode sequence) {
            for (Node child : sequence.getValue()) duplicateNodes(child,warnings,visited);
        }
    }

    private void duplicateHeuristic(String content,List<Map<String,Object>> warnings) {
        TreeMap<Integer,Set<String>> stack = new TreeMap<>();
        String[] lines = content.split("\\R");
        for (int i=0; i<lines.length; i++) {
            var match = java.util.regex.Pattern.compile("^(\\s*)([^#:'\\\"{}\\[\\]]+):(?:\\s|$)").matcher(lines[i]);
            if (!match.find()) continue;
            int indent = match.group(1).length();
            stack.tailMap(indent,false).clear();
            String key = match.group(2).strip();
            if (!stack.computeIfAbsent(indent,k -> new HashSet<>()).add(key))
                warnings.add(hint(i+1,"重复键："+key+"（后值覆盖）"));
        }
    }

    private void blocks(String[] lines,String format,List<Map<String,Object>> errors) {
        Deque<Integer> braces = new ArrayDeque<>();
        for (int i=0; i<lines.length; i++) {
            StringBuilder code = new StringBuilder();
            char quote = 0;
            for (char c : lines[i].toCharArray()) {
                if (quote!=0) { if (c==quote) quote=0; continue; }
                if (c=='\'' || c=='"') { quote=c; continue; }
                if (c=='#') break;
                code.append(c);
                if (c=='{') braces.push(i+1);
                if (c=='}') {
                    if (braces.isEmpty()) errors.add(hint(i+1,"多余的 '}'"));
                    else braces.pop();
                }
            }
            if (quote!=0) errors.add(hint(i+1,"引号未闭合"));
            String text = code.toString().strip();
            if (format.equals("nginx") && !text.isEmpty() && !text.endsWith("{") && !text.endsWith("}") && !text.endsWith(";"))
                errors.add(hint(i+1,"指令行末尾缺少分号 ';'"));
        }
        for (int line : braces) errors.add(hint(line,"块未闭合：'{' 缺少对应的 '}'"));
    }

    private void properties(String[] lines,List<Map<String,Object>> errors,List<Map<String,Object>> warnings) {
        Set<String> keys = new HashSet<>();
        for (int i=0; i<lines.length; i++) {
            String text = lines[i].strip();
            if (text.isEmpty() || text.startsWith("#") || text.startsWith("!")) continue;
            if (!text.contains("=")) { errors.add(hint(i+1,"非法行：properties 应为 key=value 形式")); continue; }
            String key = text.substring(0,text.indexOf('=')).strip();
            if (!keys.add(key)) warnings.add(hint(i+1,"重复键："+key+"（后值覆盖）"));
        }
    }
}
