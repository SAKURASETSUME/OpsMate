package com.opsmate.versions;

import jakarta.validation.Valid;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/versions")
class VersionsController {
    record Version(@JsonProperty("package") @NotBlank @Size(max=100) String packageName,
                   @NotBlank @Size(max=50) String version,
                   @Size(max=500) String description,@JsonProperty("release_date") @Size(max=20) String releaseDate) {}
    private final VersionsService versions;
    VersionsController(VersionsService versions) { this.versions = versions; }
    @GetMapping Map<String,Object> list(@RequestParam(defaultValue="") String q,
        @RequestParam(name="package",defaultValue="") String pkg,
        @RequestParam(defaultValue="") String version,@RequestParam(defaultValue="") String description) {
        return Map.of("items",versions.list(q,pkg,version,description));
    }
    @PostMapping Map<String,Object> create(@Valid @RequestBody Version body) {
        return versions.create(body.packageName(),body.version(),text(body.description()),text(body.releaseDate()));
    }
    @PutMapping("/{id}") Map<String,Object> update(@PathVariable long id,@Valid @RequestBody Version body) {
        versions.update(id,body.packageName(),body.version(),text(body.description()),text(body.releaseDate()));
        return Map.of("ok",true);
    }
    @DeleteMapping("/{id}") Map<String,Object> delete(@PathVariable long id) {
        versions.delete(id);
        return Map.of("ok",true);
    }
    private String text(String value) { return value == null ? "" : value; }
}
