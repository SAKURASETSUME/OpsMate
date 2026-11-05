package com.opsmate.notes;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/notes")
class NotesController {
    record Note(@NotBlank @Size(max=500) String content) {}
    record Done(@NotNull Boolean done) {}
    private final NotesService notes;
    NotesController(NotesService notes) { this.notes = notes; }
    @GetMapping Map<String,Object> list() { return Map.of("items",notes.list()); }
    @PostMapping Map<String,Object> create(@Valid @RequestBody Note body) {
        return Map.of("id",notes.create(body.content()));
    }
    @PutMapping("/{id}/done") Map<String,Object> done(@PathVariable long id,@Valid @RequestBody Done body) {
        return Map.of("ok",true,"done",notes.done(id,body.done()));
    }
    @DeleteMapping("/{id}") Map<String,Object> delete(@PathVariable long id) {
        notes.delete(id);
        return Map.of("ok",true);
    }
}
