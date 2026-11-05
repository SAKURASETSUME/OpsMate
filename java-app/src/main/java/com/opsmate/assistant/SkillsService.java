package com.opsmate.assistant;

import com.opsmate.infrastructure.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.LoaderOptions;
import org.yaml.snakeyaml.constructor.SafeConstructor;

@Service
public class SkillsService {
    private final Path directory;
    public SkillsService(RuntimePaths paths) throws java.io.IOException {
        directory=paths.data().resolve("skills");
        Files.createDirectories(directory);
        // Initial copy only. A marker preserves explicit deletions on subsequent starts.
        Path marker=directory.resolve(".initialized");
        if (!Files.exists(marker)&&Files.isDirectory(paths.knowledge().resolve("skills"))) {
            try (var stream=Files.list(paths.knowledge().resolve("skills"))) {
                for (Path source:stream.filter(p -> p.getFileName().toString().endsWith(".yaml")).toList()) {
                    Path target=directory.resolve(source.getFileName());
                    if (!Files.exists(target)) Files.copy(source,target);
                }
            }
            Files.writeString(marker,"1",StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
        }
    }
    private Map<String,Object> parse(String text) {
        Object parsed=new Yaml(new SafeConstructor(new LoaderOptions())).load(text);
        if (!(parsed instanceof Map<?,?> map)||Objects.toString(map.get("name"),"").isBlank()||Objects.toString(map.get("methodology"),"").isBlank()||!(map.get("triggers") instanceof List<?> triggers)||triggers.isEmpty())
            throw new ApiFailure(400,"技能 YAML 必含：name、methodology（方法论全文）、triggers（非空触发词列表）；建议附 label 与 example_question");
        Map<String,Object> result=new LinkedHashMap<>();
        result.put("name",map.get("name").toString().strip());
        result.put("label",Objects.toString(map.get("label"),map.get("name").toString()).strip());
        result.put("methodology",map.get("methodology").toString().strip());
        result.put("example_question",Objects.toString(map.get("example_question"),"").strip());
        result.put("triggers",triggers.stream().map(Object::toString).map(String::strip).map(s -> s.toLowerCase(Locale.ROOT)).filter(s -> !s.isBlank()).toList());
        return result;
    }
    private List<Map<String,Object>> load() {
        List<Map<String,Object>> result=new ArrayList<>();
        try (var stream=Files.list(directory)) {
            for (Path path:stream.filter(p -> p.getFileName().toString().endsWith(".yaml")).sorted().toList()) {
                try { result.add(parse(Files.readString(path,StandardCharsets.UTF_8))); }
                catch (Exception ignored) { }
            }
        } catch (java.io.IOException ignored) { }
        return result;
    }
    public synchronized List<Map<String,Object>> list() {
        return load().stream().map(s -> Map.of("name",s.get("name"),"label",s.get("label"),"example_question",s.get("example_question"))).toList();
    }
    public synchronized String methodology(String text) {
        String haystack=text.toLowerCase(Locale.ROOT),best="";
        int length=0;
        for (var skill:load()) {
            for (Object trigger:(List<?>)skill.get("triggers")) {
                String word=trigger.toString();
                if (haystack.contains(word)&&word.length()>length) {
                    length=word.length();
                    best="\n\n【排查方法论参考（命中技能："+skill.get("label")+"）】\n以下步骤供参考，按用户实际情况取舍，不要机械照抄：\n"+skill.get("methodology")+"\n";
                }
            }
        }
        return best;
    }
    private Path target(String slug) {
        if (!slug.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,63}")) throw new ApiFailure(400,"非法技能名");
        return directory.resolve(slug+".yaml");
    }
    public synchronized Map<String,Object> install(String slug,String content) {
        Path path=target(slug);
        Map<String,Object> skill;
        try { skill=parse(content); }
        catch (ApiFailure expected) { throw expected; }
        catch (Exception invalid) { throw new ApiFailure(400,"YAML 解析失败：请检查技能格式"); }
        if (load().stream().anyMatch(s -> s.get("name").equals(skill.get("name")))) throw new ApiFailure(400,"技能 "+skill.get("name")+" 已存在");
        try { Files.writeString(path,content,StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW); }
        catch (FileAlreadyExistsException exists) { throw new ApiFailure(400,"同名技能文件已存在"); }
        catch (java.io.IOException failed) { throw new ApiFailure(500,"技能保存失败"); }
        return Map.of("ok",true,"installed",skill.get("name"),"total",list().size());
    }
    public synchronized Map<String,Object> delete(String slug) {
        try { if (!Files.deleteIfExists(target(slug))) throw new ApiFailure(404,"技能不存在"); }
        catch (java.io.IOException failed) { throw new ApiFailure(500,"技能删除失败"); }
        return Map.of("ok",true,"total",list().size());
    }
}
