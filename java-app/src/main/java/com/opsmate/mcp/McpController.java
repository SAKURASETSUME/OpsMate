package com.opsmate.mcp;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/mcp")
class McpController {
    private final McpService service;
    McpController(McpService service) { this.service=service; }
    static class Server {
        @NotBlank @Size(max=40) public String name;
        @NotNull @Pattern(regexp="stdio|http") public String transport;
        @NotNull @Size(max=20) public List<String> command=new ArrayList<>();
        @NotNull @Size(max=500) public String url="";
        public boolean enabled=true;
        Map<String,Object> map() { return new LinkedHashMap<>(Map.of("name",name,"transport",transport,"command",command,"url",url,"enabled",enabled)); }
    }
    @GetMapping Map<String,Object> list() { return Map.of("items",service.servers().stream().map(s -> { var result=new LinkedHashMap<String,Object>(); for (String key:List.of("id","name","transport","command","url","enabled")) result.put(key,s.get(key)); return result; }).toList()); }
    @PostMapping Map<String,Object> add(@Valid @RequestBody Server body) { return Map.of("ok",true,"id",service.add(body.map())); }
    @PutMapping("/{id}") Map<String,Object> update(@PathVariable String id,@Valid @RequestBody Server body) { service.update(id,body.map()); return Map.of("ok",true); }
    @DeleteMapping("/{id}") Map<String,Object> delete(@PathVariable String id) { service.delete(id); return Map.of("ok",true); }
    @PostMapping("/{id}/test") Map<String,Object> test(@PathVariable String id) {
        var server=service.server(id);
        try { return Map.of("ok",true,"tools",service.tools(server).stream().map(tool -> Map.of("name",Objects.toString(tool.get("name"),""),"description",Objects.toString(tool.get("description"),"").substring(0,Math.min(160,Objects.toString(tool.get("description"),"").length())))).toList()); }
        catch (IllegalStateException failed) { return Map.of("ok",false,"error",failed.getMessage()); }
    }
}
