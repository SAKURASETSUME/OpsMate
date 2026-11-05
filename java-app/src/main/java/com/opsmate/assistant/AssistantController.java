package com.opsmate.assistant;

import com.opsmate.infrastructure.ApiFailure;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/assistant")
class AssistantController {
    private final AssistantStore store;
    private final WorkspaceService workspace;
    private final SkillsService skills;
    AssistantController(AssistantStore store,WorkspaceService workspace,SkillsService skills) {
        this.store=store; this.workspace=workspace; this.skills=skills;
    }
    record Directories(@NotNull @Size(max=16) List<@NotNull String> directories) { }
    record OpenPath(@NotBlank @Size(max=400) String path) { }
    record Proposal(long session_id,@NotBlank @Size(max=200) String filename) { }
    record Skill(@NotBlank @Size(max=64) @Pattern(regexp="[A-Za-z0-9][A-Za-z0-9._-]*") String name,@NotNull @Size(min=10,max=64000) String content) { }
    @GetMapping("/workspace") Map<String,Object> directories() { return Map.of("directories",workspace.directories()); }
    @PutMapping("/workspace") Map<String,Object> directories(@Valid @RequestBody Directories body) { return Map.of("ok",true,"directories",workspace.save(body.directories())); }
    @PostMapping("/workspace/open") Map<String,Object> open(@Valid @RequestBody OpenPath body) {
        if (!workspace.directories().contains(body.path())) throw new ApiFailure(400,"该路径不在已授权的工作目录列表中");
        try { new ProcessBuilder("explorer.exe",body.path()).start(); }
        catch (java.io.IOException failure) { throw new ApiFailure(500,"打开目录失败"); }
        return Map.of("ok",true);
    }
    @GetMapping("/sessions") Map<String,Object> sessions(@RequestParam(required=false) String workspace) { return Map.of("items",store.sessions(workspace)); }
    @GetMapping("/sessions/{id}") Map<String,Object> messages(@PathVariable long id) { return Map.of("messages",store.messages(id)); }
    @DeleteMapping("/sessions/{id}") Map<String,Object> delete(@PathVariable long id) { store.delete(id); return Map.of("ok",true); }
    @PostMapping("/files") Map<String,Object> upload(@RequestParam MultipartFile file) throws java.io.IOException {
        return store.upload(Objects.requireNonNullElse(file.getOriginalFilename(),"未命名"),Objects.requireNonNullElse(file.getContentType(),""),file.getBytes());
    }
    @GetMapping("/files/{id}/content") ResponseEntity<FileSystemResource> content(@PathVariable long id) {
        var item=store.attachment(id);
        MediaType mime;
        try { mime=MediaType.parseMediaType(Objects.toString(item.get("mime"),"application/octet-stream")); }
        catch (Exception invalid) { mime=MediaType.APPLICATION_OCTET_STREAM; }
        return ResponseEntity.ok().contentType(mime).header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(item.get("name").toString(),java.nio.charset.StandardCharsets.UTF_8).build().toString()).body(new FileSystemResource(store.attachmentPath(item)));
    }
    @PostMapping("/files/apply") Map<String,Object> apply(@Valid @RequestBody Proposal body) { return Map.of("ok",true,"outcome",store.resolve(body.session_id(),body.filename(),true)); }
    @PostMapping("/files/cancel") Map<String,Object> cancel(@Valid @RequestBody Proposal body) { return Map.of("ok",true,"outcome",store.resolve(body.session_id(),body.filename(),false)); }
    @GetMapping("/skills") Map<String,Object> skills() { return Map.of("items",skills.list()); }
    @PostMapping("/skills") Map<String,Object> install(@Valid @RequestBody Skill body) { return skills.install(body.name(),body.content()); }
    @DeleteMapping("/skills/{slug}") Map<String,Object> remove(@PathVariable String slug) { return skills.delete(slug); }
}
