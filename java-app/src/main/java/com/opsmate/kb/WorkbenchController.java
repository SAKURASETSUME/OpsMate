package com.opsmate.kb;

import com.opsmate.infrastructure.ApiFailure;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/kb/workbench")
class WorkbenchController {
    record Config(@NotBlank @Size(max=80) String name,@NotNull String format,
                  @NotNull @Size(max=3000000) String content) {}
    record Validation(@NotNull String format,@NotNull @Size(max=3000000) String content) {}
    record Share(@NotNull Boolean shared) {}
    private final WorkbenchService configs;
    private final ConfigValidator validator;
    WorkbenchController(WorkbenchService configs,ConfigValidator validator) {
        this.configs = configs;
        this.validator = validator;
    }
    @GetMapping("/configs")
    Map<String,Object> list() { return Map.of("items",configs.list()); }
    @GetMapping("/configs/{id}")
    Map<String,Object> get(@PathVariable long id) { return configs.get(id); }
    @PostMapping("/configs")
    Map<String,Object> create(@Valid @RequestBody Config body) {
        return configs.create(body.name(),body.format(),body.content());
    }
    @PutMapping("/configs/{id}")
    Map<String,Object> update(@PathVariable long id,@Valid @RequestBody Config body) {
        configs.update(id,body.name(),body.format(),body.content());
        return Map.of("ok",true);
    }
    @DeleteMapping("/configs/{id}")
    Map<String,Object> delete(@PathVariable long id) {
        configs.delete(id);
        return Map.of("ok",true);
    }
    @PutMapping("/configs/{id}/share")
    Map<String,Object> share(@PathVariable long id,@Valid @RequestBody Share body) {
        return Map.of("ok",true,"shared",configs.share(id,body.shared()));
    }
    @PostMapping("/validate")
    Map<String,Object> validate(@Valid @RequestBody Validation body) {
        if (!WorkbenchService.FORMATS.contains(body.format())) throw new ApiFailure(422,"配置格式无效");
        return validator.validate(body.format(),body.content());
    }
}
