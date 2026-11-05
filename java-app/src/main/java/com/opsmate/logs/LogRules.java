package com.opsmate.logs;

import java.util.*;
import java.util.regex.Pattern;

final class LogRules {
    private static final Pattern LEVEL = Pattern.compile("(?i)\\b(ERROR|FATAL|CRITICAL|WARN(?:ING)?|INFO|DEBUG|TRACE)\\b");
    private static final Pattern TIMESTAMP = Pattern.compile("\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?");
    private static final Pattern CONTINUATION = Pattern.compile("^(?:\\s+|at |Caused by:|\\.\\.\\.\\s*\\d+ more)");

    static String level(String text) {
        var match = LEVEL.matcher(text);
        if (!match.find()) return "";
        return switch (match.group(1).toUpperCase(Locale.ROOT)) {
            case "FATAL", "CRITICAL" -> "ERROR";
            case "WARNING" -> "WARN";
            case "TRACE" -> "DEBUG";
            default -> match.group(1).toUpperCase(Locale.ROOT);
        };
    }

    static String format(List<String> lines) {
        String sample = String.join("\n",lines.subList(0,Math.min(lines.size(),200)));
        String[][] patterns = {
            {"^\\S+ \\S+ \\S+ \\[.*\\] \"\\w+ .*\" \\d{3} ","nginx_access"},
            {" \\[(?:error|warn)\\] ","nginx_error"},
            {"^\\w{3} +\\d+ \\d{2}:\\d{2}:\\d{2} \\S+ ","syslog"},
            {" \\[main\\]|java\\.|Exception|ERROR","java_app"},
            {"zabbix_server|zabbix_agent","known_service"}
        };
        for (String[] pair : patterns)
            if (Pattern.compile(pair[0],Pattern.MULTILINE).matcher(sample).find()) return pair[1];
        return "unknown";
    }

    static String normalize(String text) {
        return text.replaceAll("\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b","<ip>")
            .replaceAll("(?U)/[\\w./-]+","\uE002")
            .replaceAll("\\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\\b","\uE000")
            .replaceAll("\\b(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{6,}\\b","\uE001")
            .replaceAll("\\d+(?:\\.\\d+)?","<num>")
            .replace("\uE001","<hex>").replace("\uE000","<id>")
            .replaceAll("'[^']*'|\"[^\"]*\"","<str>")
            .replace("\uE002","<path>").replaceAll("(?U)\\s+"," ").strip();
    }

    static final class Clusters {
        private final Map<String,Map<String,Object>> groups = new LinkedHashMap<>();
        private String currentLevel;
        private StringBuilder current;
        private int first;
        private int last;
        private String firstTimestamp;
        private String lastTimestamp;

        void accept(int number,String level,String text) {
            var time = TIMESTAMP.matcher(text);
            if (time.find()) {
                if (firstTimestamp==null) firstTimestamp=time.group();
                lastTimestamp=time.group();
            }
            if (current!=null && CONTINUATION.matcher(text).find()) {
                current.append('\n').append(text);
                last=number;
            } else {
                flush();
                currentLevel=level;
                current=new StringBuilder(text);
                first=last=number;
            }
        }

        private void flush() {
            if (current==null || !Set.of("ERROR","WARN").contains(currentLevel)) return;
            String text = current.toString();
            String normalized = normalize(text);
            var group = groups.computeIfAbsent(normalized,key -> {
                Map<String,Object> value = new LinkedHashMap<>();
                value.put("pattern",key.substring(0,Math.min(key.length(),80)));
                value.put("count",0);
                value.put("first_no",first);
                value.put("sample",text.substring(0,Math.min(text.length(),300)));
                value.put("level",currentLevel);
                return value;
            });
            group.put("count",(int)group.get("count")+1);
            group.put("last_no",last);
            if (currentLevel.equals("ERROR")) group.put("level","ERROR");
        }

        Map<String,Object> finish() {
            flush();
            var kept = groups.values().stream()
                .filter(g -> "ERROR".equals(g.get("level")) || (int)g.get("count")>=2)
                .sorted(Comparator.comparingInt((Map<String,Object> g) -> -(int)g.get("count"))
                    .thenComparingInt(g -> (int)g.get("first_no"))).limit(20)
                .map(g -> { var result = new LinkedHashMap<>(g); result.remove("level"); return result; }).toList();
            Map<String,Object> result = new LinkedHashMap<>();
            result.put("top_clusters",kept);
            if (firstTimestamp!=null) result.put("time_range",List.of(firstTimestamp,lastTimestamp));
            return result;
        }
    }
}
