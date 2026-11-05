package com.opsmate.kb;

import com.opsmate.infrastructure.ApiFailure;
import com.opsmate.infrastructure.RuntimePaths;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import org.springframework.stereotype.Service;
import org.yaml.snakeyaml.LoaderOptions;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.constructor.SafeConstructor;

@Service
public class KnowledgeService {
    private final Map<String,Map<String,Object>> softwares = new TreeMap<>();

    @SuppressWarnings("unchecked")
    KnowledgeService(RuntimePaths paths) throws java.io.IOException {
        Path directory = paths.knowledge().resolve("kb");
        if (!Files.isDirectory(directory)) return;
        try (var files = Files.list(directory)) {
            for (Path file : files.filter(p -> p.toString().endsWith(".yaml")).sorted().toList()) {
                try {
                    Object parsed = new Yaml(new SafeConstructor(new LoaderOptions()))
                        .load(Files.readString(file,StandardCharsets.UTF_8));
                    if (parsed instanceof Map<?,?> value && value.get("software") instanceof String id
                            && value.get("categories") instanceof List<?>) {
                        softwares.put(id,(Map<String,Object>)value);
                    }
                } catch (RuntimeException failure) {
                    // A damaged knowledge file must not disable the other software entries.
                }
            }
        }
    }

    @SuppressWarnings("unchecked")
    private List<Map<String,Object>> categories(Map<String,Object> software) {
        return (List<Map<String,Object>>)software.get("categories");
    }

    @SuppressWarnings("unchecked")
    private List<Map<String,Object>> entries(Map<String,Object> category) {
        return (List<Map<String,Object>>)category.getOrDefault("entries",List.of());
    }

    public List<Map<String,Object>> summary() {
        List<Map<String,Object>> result = new ArrayList<>();
        for (var item : softwares.values()) {
            int cli = 0;
            int conf = 0;
            for (var category : categories(item)) {
                if ("cli".equals(category.get("id"))) cli += entries(category).size();
                else conf += entries(category).size();
            }
            result.add(Map.of("software",item.get("software"),"label",item.getOrDefault("label",item.get("software")),
                "cli_count",cli,"conf_count",conf));
        }
        return result;
    }

    public Map<String,Object> get(String id) {
        var item = softwares.get(id);
        if (item == null) throw new ApiFailure(404,"软件不存在");
        return item;
    }

    public List<Map<String,Object>> search(String query, String software) {
        String term = query.strip().toLowerCase(Locale.ROOT);
        if (term.isEmpty()) return List.of();
        List<Map<String,Object>> result = new ArrayList<>();
        for (var item : softwares.values()) {
            if (software != null && !software.isEmpty() && !software.equals(item.get("software"))) continue;
            for (var category : categories(item)) {
                for (var entry : entries(category)) {
                    String text = entry.get("name") + " " + entry.get("syntax") + " " + entry.get("desc");
                    if (text.toLowerCase(Locale.ROOT).contains(term)) {
                        result.add(Map.of("software",item.get("software"),"category",category.get("id"),
                            "name",entry.getOrDefault("name",""),"desc",entry.getOrDefault("desc",""),
                            "danger",entry.getOrDefault("danger",false)));
                    }
                }
            }
        }
        return result;
    }
}
