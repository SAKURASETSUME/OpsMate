package com.opsmate.codegen;

import java.util.*;
import java.util.regex.*;
import org.springframework.stereotype.Component;

/** Quality gates preserve legitimate Bash assignments, command substitutions and heredocs. */
@Component
public class ScriptValidator {
    private static final Pattern ASSIGNMENT=Pattern.compile("^\\s*(?:export\\s+|local\\s+|declare\\s+)?[A-Za-z_][A-Za-z0-9_]*=[^\\s'\"|;&]*$");
    private static final Pattern HEREDOC=Pattern.compile("<<-?\\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\\1");
    private static final Pattern VARIABLE=Pattern.compile("\\$(?:[A-Za-z_]|\\{|[0-9@*])");
    private static final Pattern NUMERIC=Pattern.compile("\\[\\s+\\$([A-Za-z_][A-Za-z0-9_]*|[0-9]+)\\s+(-(?:eq|ne|lt|le|gt|ge)\\s+\\d+\\s*)\\]");
    private static final Pattern DANGER=Pattern.compile("(?:^|[;|&\\s])(?:rm|kill|iptables)\\s|systemctl\\s+(?:stop|restart)\\b|\\s-delete\\b");

    public String unsafeExpansion(String script) {
        String heredoc="";
        String[] lines=script.split("\\R");
        for (int number=0;number<lines.length;number++) {
            String line=lines[number];
            if (!heredoc.isEmpty()) {
                if (line.strip().equals(heredoc)) heredoc="";
                continue;
            }
            Deque<Character> stack=new ArrayDeque<>();
            boolean escaped=false;
            for (int i=0;i<line.length();i++) {
                char c=line.charAt(i);
                char top=stack.isEmpty() ? 0 : stack.peek();
                if (escaped) { escaped=false; continue; }
                if (top=='\'') { if (c=='\'') stack.pop(); continue; }
                if (c=='\\') { escaped=true; continue; }
                if (c=='#'&&stack.isEmpty()) break;
                if (c=='\''&&top!='"') { stack.push('\''); continue; }
                if (c=='"') {
                    if (top=='"') stack.pop();
                    else stack.push('"');
                    continue;
                }
                if (c=='('&&i>0&&line.charAt(i-1)=='$') { stack.push('S'); continue; }
                if (c==')'&&top=='S') { stack.pop(); continue; }
                if (c=='<'&&stack.isEmpty()&&line.startsWith("<<",i)) {
                    var match=HEREDOC.matcher(line);
                    if (match.find(i)) { heredoc=match.group(2); break; }
                }
                if (c=='$'&&stack.isEmpty()&&VARIABLE.matcher(line.substring(i)).lookingAt()
                        &&!ASSIGNMENT.matcher(line.substring(0,i)).matches()) {
                    String text=line.strip();
                    return "第"+(number+1)+"行: "+text.substring(0,Math.min(text.length(),120));
                }
            }
        }
        return "";
    }

    public void requireEcho(String script) {
        String heredoc="";
        List<String> previous=new ArrayList<>();
        for (String line:script.split("\\R")) {
            String code=line.strip();
            if (!heredoc.isEmpty()) { if (code.equals(heredoc)) heredoc=""; continue; }
            if (code.isEmpty()||code.startsWith("#")) continue;
            var start=HEREDOC.matcher(code);
            if (start.find()) heredoc=start.group(2);
            String token=code.split("\\s+",2)[0];
            if (!token.equals("echo")&&DANGER.matcher(code).find()&&previous.stream()
                    .skip(Math.max(0,previous.size()-3)).noneMatch(text -> text.contains("echo ")))
                throw new IllegalStateException("影响业务操作前缺少中文 echo 提示");
            previous.add(code);
        }
    }

    private Map<String,Object> item(Map<?,?> item) {
        if (!(item.get("script") instanceof String original))
            throw new IllegalStateException("script 必须是文本");
        String script=NUMERIC.matcher(original).replaceAll(match ->
            Matcher.quoteReplacement("[ \"$"+match.group(1)+"\" "+match.group(2)+"]"));
        List<String> failed=new ArrayList<>();
        if (!script.startsWith("#!/usr/bin/env bash")) failed.add("首行须为 #!/usr/bin/env bash");
        if (!script.contains("set -euo pipefail")) failed.add("须含 set -euo pipefail");
        if (script.split("\\R").length<3) failed.add("脚本至少3行");
        String unsafe=unsafeExpansion(script);
        if (!unsafe.isEmpty()) failed.add("变量展开必须双引号包裹："+unsafe);
        if (script.contains("解读")||script.contains("分析")) failed.add("script 内不得出现解读/分析字样");
        if (!(item.get("explanation") instanceof List<?> explanations)||explanations.size()<3
                ||explanations.stream().anyMatch(part -> !(part instanceof Map<?,?> values)
                    ||List.of("lines","title","detail").stream().anyMatch(key ->
                        !(values.get(key) instanceof String text)||text.isBlank())))
            failed.add("explanation 须为至少3段含 lines/title/detail 的文本数组");
        if (!(item.get("warnings") instanceof List<?> warnings)||warnings.stream().anyMatch(w -> !(w instanceof String)))
            failed.add("warnings 须为字符串数组");
        if (!(item.get("usage") instanceof String)) failed.add("usage 须为字符串");
        String header=String.join("\n",script.lines().limit(20).toList());
        if (List.of("用途","用法","参数","依赖","适用","AI").stream().anyMatch(marker -> !header.contains(marker)))
            failed.add("缺少用途/用法/参数/依赖/适用/AI审阅头注释");
        if (!failed.isEmpty()) throw new IllegalStateException("脚本未通过："+String.join("；",failed));
        requireEcho(script);
        return Map.of("script",script,"explanation",item.get("explanation"),"warnings",item.get("warnings"),"usage",item.get("usage"));
    }

    public Map<String,Object> validate(Map<String,Object> payload) {
        if (Boolean.TRUE.equals(payload.get("need_clarification"))) {
            if (!(payload.get("questions") instanceof List<?> raw)||raw.isEmpty())
                throw new IllegalStateException("追问必须包含 questions");
            List<String> questions=new ArrayList<>();
            for (Object value:raw) {
                if (value instanceof Map<?,?> question&&question.get("question") instanceof String text)
                    questions.add(text+(question.get("default")==null ? "" : "（建议："+question.get("default")+"）"));
                else if (value instanceof String text&&!text.isBlank()) questions.add(text);
                else throw new IllegalStateException("追问 questions 必须为非空文本");
            }
            return Map.of("need_clarification",true,"questions",questions);
        }
        if (payload.get("scripts") instanceof List<?> scripts&&!scripts.isEmpty()) {
            if (scripts.size()>3) throw new IllegalStateException("一次最多生成3个脚本，请分批生成");
            Set<String> names=new HashSet<>();
            List<Map<String,Object>> result=new ArrayList<>();
            for (Object value:scripts) {
                if (!(value instanceof Map<?,?> source)) throw new IllegalStateException("scripts 元素必须为对象");
                String name=Objects.toString(source.get("name"),"").strip();
                name=name.substring(0,Math.min(name.length(),60));
                if (name.isEmpty()||name.contains("/")||name.contains("\\")||!names.add(name))
                    throw new IllegalStateException("脚本名称无效或重复");
                var checked=new LinkedHashMap<>(item(source));
                checked.put("name",name);
                result.add(checked);
            }
            return Map.of("need_clarification",false,"scripts",result);
        }
        if (!Boolean.FALSE.equals(payload.get("need_clarification")))
            throw new IllegalStateException("单脚本 need_clarification 须为 false");
        var result=new LinkedHashMap<>(item(payload));
        result.put("need_clarification",false);
        return result;
    }
}
