package com.opsmate.llm;

import java.util.Map;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/settings")
class SettingsController {
    static class SettingsInput {
        @NotNull public String provider="zhipu";
        @NotNull @Size(max=2048) public String base_url;
        @NotNull @Size(max=256) public String model;
        @NotNull @Size(max=8192) public String api_key="";
        public Map<String,Object> values() {
            return new java.util.LinkedHashMap<>(Map.of("provider",provider,"base_url",base_url,"model",model,"api_key",api_key));
        }
    }
    static class ProfileInput extends SettingsInput {
        @NotNull @Size(min=1,max=80) public String name;
        @Override public Map<String,Object> values() {
            var result=super.values();
            result.put("name",name);
            return result;
        }
    }
    private final SettingsService settings;
    SettingsController(SettingsService settings) { this.settings=settings; }
    @GetMapping Map<String,Object> get() { return settings.publicSettings(settings.effective()); }
    @PutMapping Map<String,Object> save(@Valid @RequestBody SettingsInput body) {
        settings.save(body.values()); return Map.of("ok",true);
    }
    @GetMapping("/profiles") Map<String,Object> profiles() { return settings.listProfiles(); }
    @PostMapping("/profiles") Map<String,Object> create(@Valid @RequestBody ProfileInput body) {
        return Map.of("ok",true,"id",settings.createProfile(body.values()));
    }
    @PutMapping("/profiles/{id}") Map<String,Object> update(@PathVariable String id,@Valid @RequestBody ProfileInput body) {
        settings.updateProfile(id,body.values()); return Map.of("ok",true);
    }
    @PostMapping("/profiles/{id}/activate") Map<String,Object> activate(@PathVariable String id) {
        settings.activate(id); return Map.of("ok",true);
    }
}
