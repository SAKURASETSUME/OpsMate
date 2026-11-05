package com.opsmate.kb;

import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/kb")
class KnowledgeController {
    private final KnowledgeService knowledge;
    KnowledgeController(KnowledgeService knowledge) { this.knowledge = knowledge; }

    @GetMapping
    Map<String,Object> list() { return Map.of("items",knowledge.summary()); }

    @GetMapping("/search")
    Map<String,Object> search(@RequestParam(defaultValue="") String q,
                             @RequestParam(required=false) String software) {
        return Map.of("items",knowledge.search(q,software));
    }

    @GetMapping("/{software}")
    Map<String,Object> detail(@PathVariable String software) { return knowledge.get(software); }
}
