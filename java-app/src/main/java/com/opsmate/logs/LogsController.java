package com.opsmate.logs;

import com.opsmate.infrastructure.ApiFailure;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api/logs")
class LogsController {
    private final LogService logs;
    LogsController(LogService logs) { this.logs=logs; }

    @PostMapping(consumes="application/json")
    Map<String,Object> paste(@RequestBody Map<String,Object> body) {
        if (!(body.get("title") instanceof String title) || !(body.get("content") instanceof String content))
            throw new ApiFailure(400,"粘贴日志需提供 title 和 content 文本");
        return logs.importLog(title,content.getBytes(StandardCharsets.UTF_8),null);
    }

    @PostMapping(consumes="multipart/form-data")
    Map<String,Object> upload(@RequestParam(required=false) MultipartFile file,
                             @RequestParam(required=false) String title) throws java.io.IOException {
        if (file==null) throw new ApiFailure(400,"请选择日志文件");
        if (file.getSize()>LogService.MAX_BYTES) throw new ApiFailure(413,"单份日志不能超过 50MB，请先 split/grep 裁剪");
        String filename = file.getOriginalFilename()==null ? "log.txt" : file.getOriginalFilename().replace('\\','/');
        filename = filename.substring(filename.lastIndexOf('/')+1);
        filename = filename.substring(0,Math.min(filename.length(),255));
        return logs.importLog(title==null || title.isEmpty() ? filename : title,file.getBytes(),filename);
    }
    @GetMapping Map<String,Object> list() { return Map.of("items",logs.list()); }
    @GetMapping("/{id}") Map<String,Object> get(@PathVariable long id) { return logs.get(id); }
    @GetMapping("/{id}/stats") Map<String,Object> stats(@PathVariable long id) { return logs.stats(id); }
    @GetMapping("/{id}/lines")
    Map<String,Object> lines(@PathVariable long id,@RequestParam(defaultValue="") String level,
        @RequestParam(defaultValue="") String q,@RequestParam(defaultValue="") String regex,
        @RequestParam(defaultValue="0") int offset,@RequestParam(defaultValue="500") int limit,
        @RequestParam(defaultValue="asc") String order) {
        return logs.query(id,level,q,regex,offset,limit,order);
    }
    @GetMapping("/{id}/export")
    ResponseEntity<StreamingResponseBody> export(@PathVariable long id,@RequestParam(defaultValue="") String level,
        @RequestParam(defaultValue="") String q,@RequestParam(defaultValue="") String regex) {
        logs.get(id);
        var filter = logs.filters(id,level,q,regex);
        StreamingResponseBody body = output -> logs.export(filter,text -> {
            try { output.write(text.getBytes(StandardCharsets.UTF_8)); }
            catch (java.io.IOException failure) { throw new java.io.UncheckedIOException(failure); }
        });
        return ResponseEntity.ok().header("Content-Type","text/plain; charset=utf-8")
            .header("Content-Disposition","attachment; filename=\"opsmate-log-"+id+".txt\"").body(body);
    }
    @DeleteMapping("/{id}") Map<String,Object> delete(@PathVariable long id) {
        logs.delete(id);
        return Map.of("ok",true);
    }
}
