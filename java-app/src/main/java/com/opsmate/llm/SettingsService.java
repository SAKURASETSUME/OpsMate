package com.opsmate.llm;

import com.opsmate.infrastructure.*;
import java.nio.file.*;
import java.util.*;
import org.springframework.stereotype.Service;

@Service
public class SettingsService {
    private final Path config;
    private final Path profiles;
    private final JsonFiles files;
    private static final Set<String> PROVIDERS=Set.of("zhipu","siliconflow","deepseek","custom");

    public SettingsService(RuntimePaths paths,JsonFiles files) {
        config=paths.data().resolve("config.json");
        profiles=paths.data().resolve("model_profiles.json");
        this.files=files;
    }

    public synchronized Map<String,Object> effective() {
        Map<String,Object> result=new LinkedHashMap<>(Map.of("provider","zhipu",
            "base_url","https://open.bigmodel.cn/api/paas/v4","model","glm-4-flash"));
        try {
            var stored=files.read(config);
            if (stored!=null) result.putAll(stored);
        } catch (ApiFailure invalidLocalConfig) {
            // Existing Python installations use defaults for an unreadable settings snapshot.
        }
        return result;
    }

    public Map<String,Object> publicSettings(Map<String,Object> settings) {
        Map<String,Object> result=new LinkedHashMap<>();
        for (String key:List.of("provider","base_url","model")) result.put(key,settings.getOrDefault(key,""));
        result.put("api_key_set",!Objects.toString(settings.get("api_key"),"").isEmpty());
        return result;
    }

    public synchronized Map<String,Object> readProfiles() {
        Map<String,Object> result=files.read(profiles);
        if (result.isEmpty()) result=new LinkedHashMap<>(Map.of("active_id","current","items",new ArrayList<>()));
        if (!(result.get("items") instanceof List<?>)) throw new ApiFailure(500,"本机命名配置读取失败");
        if (((List<?>)result.get("items")).isEmpty()) {
            Map<String,Object> current=new LinkedHashMap<>(effective());
            current.put("id","current");
            current.put("name","原有配置");
            result.put("items",new ArrayList<>(List.of(current)));
        }
        return result;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String,Object>> items(Map<String,Object> data) {
        return (List<Map<String,Object>>)data.get("items");
    }

    public synchronized Map<String,Object> listProfiles() {
        var data=readProfiles();
        return Map.of("active_id",data.get("active_id"),"items",items(data).stream().map(item -> {
            var clean=publicSettings(item);
            clean.put("id",item.getOrDefault("id",""));
            clean.put("name",item.getOrDefault("name",""));
            return clean;
        }).toList());
    }

    private Map<String,Object> validated(Map<String,Object> body,Map<String,Object> old) {
        for (String field:List.of("provider","base_url","model","api_key")) {
            boolean required=field.equals("base_url")||field.equals("model");
            if ((required&&!body.containsKey(field)) || (body.containsKey(field)&&!(body.get(field) instanceof String)))
                throw new ApiFailure(422,"模型配置字段必须为文本："+field);
        }
        String provider=Objects.toString(body.getOrDefault("provider","zhipu"),"");
        String base=Objects.toString(body.get("base_url"),"").strip().replaceAll("/+$","");
        String model=Objects.toString(body.get("model"),"").strip();
        String key=Objects.toString(body.getOrDefault("api_key",""),"").strip();
        if (!PROVIDERS.contains(provider) || !(base.startsWith("http://")||base.startsWith("https://")) || model.isEmpty())
            throw new ApiFailure(400,"请检查预设、base_url 与模型名");
        if (base.length()>2048 || model.length()>256 || key.length()>8192)
            throw new ApiFailure(422,"模型配置字段超出长度限制");
        return new LinkedHashMap<>(Map.of("provider",provider,"base_url",base,"model",model,
            "api_key",key.isEmpty() ? Objects.toString(old.get("api_key"),"") : key));
    }

    public synchronized void save(Map<String,Object> body) {
        var settings=validated(body,effective());
        var data=readProfiles();
        for (var item:items(data)) if (item.get("id").equals(data.get("active_id"))) item.putAll(settings);
        if (Files.exists(profiles)) files.write(profiles,data);
        files.write(config,settings);
    }

    public synchronized String createProfile(Map<String,Object> body) {
        var settings=validated(body,Map.of());
        String name=Objects.toString(body.get("name"),"").strip();
        if (name.length()>80) throw new ApiFailure(422,"配置名称不超过 80 字");
        if (name.isEmpty()) throw new ApiFailure(400,"请填写配置名称");
        var data=readProfiles();
        String id=UUID.randomUUID().toString().replace("-","");
        settings.put("id",id);
        settings.put("name",name);
        items(data).add(settings);
        files.write(profiles,data);
        return id;
    }

    public synchronized void updateProfile(String id,Map<String,Object> body) {
        var data=readProfiles();
        var profile=items(data).stream().filter(item -> id.equals(item.get("id"))).findFirst()
            .orElseThrow(() -> new ApiFailure(404,"本机配置不存在"));
        String name=Objects.toString(body.get("name"),"").strip();
        if (name.isEmpty()||name.length()>80) throw new ApiFailure(400,"请填写配置名称");
        var settings=validated(body,profile);
        profile.putAll(settings);
        profile.put("name",name);
        files.write(profiles,data);
        if (id.equals(data.get("active_id"))) files.write(config,settings);
    }

    public synchronized void activate(String id) {
        var data=readProfiles();
        var profile=items(data).stream().filter(item -> id.equals(item.get("id"))).findFirst()
            .orElseThrow(() -> new ApiFailure(404,"本机配置不存在"));
        if (Objects.toString(profile.get("api_key"),"").isEmpty()) throw new ApiFailure(400,"请先保存该配置的 API key");
        Map<String,Object> settings=new LinkedHashMap<>();
        for (String field:List.of("provider","base_url","model","api_key")) settings.put(field,profile.getOrDefault(field,""));
        files.write(config,settings);
        data.put("active_id",id);
        files.write(profiles,data);
    }
}
