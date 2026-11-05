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
    private final Path local;

    @SuppressWarnings("unchecked")
    KnowledgeService(RuntimePaths paths) throws java.io.IOException {
        local=paths.data().resolve("kb");
        Path directory = paths.knowledge().resolve("kb");
        load(directory);
        load(local);
    }

    @SuppressWarnings("unchecked")
    private void load(Path directory) throws java.io.IOException {
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

    public synchronized List<Map<String,Object>> summary() {
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

    public synchronized Map<String,Object> get(String id) {
        var item = softwares.get(id);
        if (item == null) throw new ApiFailure(404,"软件不存在");
        return item;
    }

    public synchronized List<Map<String,Object>> search(String query, String software) {
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

    @SuppressWarnings("unchecked")
    public synchronized Map<String,Object> install(String slug,String content) throws java.io.IOException {
        if (!slug.matches("[a-z0-9][a-z0-9-]{0,30}")||content.isEmpty()||content.length()>200_000) throw new ApiFailure(400,"filename须为小写英文短横线，content≤200KB");
        Object parsed;
        try { parsed=new Yaml(new SafeConstructor(new LoaderOptions())).load(content); }
        catch (RuntimeException invalid) { throw new ApiFailure(400,"YAML解析失败"); }
        if (!(parsed instanceof Map<?,?> data)||!(data.get("software") instanceof String)||data.get("label")==null||!(data.get("categories") instanceof List<?> categories)||categories.isEmpty()) throw new ApiFailure(400,"kb YAML必含software、label、categories");
        Set<String> names=new HashSet<>(),tabs=new HashSet<>();
        for (Object object:categories) {
            if (!(object instanceof Map<?,?> category)||!(category.get("id") instanceof String tab)||!Set.of("cli","conf").contains(tab)||!tabs.add(tab)||!(category.get("entries") instanceof List<?> entries)) throw new ApiFailure(400,"categories必须分别为cli与conf");
            for (Object entryObject:entries) {
                if (!(entryObject instanceof Map<?,?> entry)||entry.get("name")==null||!names.add(entry.get("name").toString())) throw new ApiFailure(400,"条目name必填且唯一");
                if (Objects.toString(entry.get(tab.equals("cli")?"example":"section"),"").isBlank()) throw new ApiFailure(400,"cli条目须有example，conf条目须有section");
                if (!Set.of("false","low","medium","high").contains(Objects.toString(entry.get("danger"),"false").toLowerCase(Locale.ROOT))) throw new ApiFailure(400,"danger必须为false/low/medium/high");
            }
        }
        if (!tabs.equals(Set.of("cli","conf"))) throw new ApiFailure(400,"cli与conf必须分为两个category");
        Files.createDirectories(local);
        Path target=local.resolve(slug+".yaml"),temporary=Files.createTempFile(local,"kb-",".tmp");
        try { Files.writeString(temporary,content,StandardCharsets.UTF_8); Files.move(temporary,target,java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING); }
        finally { Files.deleteIfExists(temporary); }
        softwares.put(data.get("software").toString(),(Map<String,Object>)data);
        return Map.of("installed",data.get("software"),"file","data/kb/"+slug+".yaml","software_total",softwares.size());
    }
}
