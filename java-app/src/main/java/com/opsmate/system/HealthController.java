package com.opsmate.system;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
class HealthController {
    @GetMapping("/api/health")
    Map<String, Object> health() {
        return Map.of("ok", true, "version", "1.0.0");
    }
}
