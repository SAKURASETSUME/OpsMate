package com.opsmate.llm;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.*;
import java.util.concurrent.*;
import org.springframework.web.bind.annotation.*;

@RestController
class ModelTestController {
    private final SettingsService settings;
    private final ObjectMapper json;
    ModelTestController(SettingsService settings,ObjectMapper json) {
        this.settings=settings; this.json=json;
    }
    @PostMapping("/api/llm/test")
    Map<String,Object> test() {
        var snapshot=settings.effective();
        long started=System.nanoTime();
        Map<String,Object> result=new LinkedHashMap<>();
        result.put("model",snapshot.getOrDefault("model",""));
        LlmClient model=new LlmClient(snapshot,json);
        ExecutorService worker=Executors.newVirtualThreadPerTaskExecutor();
        try {
            worker.submit(() -> model.chat(List.of(Map.of("role","user","content","回复 pong")),0,20,8,null))
                .get(55,TimeUnit.SECONDS);
            result.put("ok",true);
        } catch (Exception failure) {
            result.put("ok",false);
            Throwable cause=failure.getCause()==null ? failure : failure.getCause();
            result.put("error",model.safe(cause.getMessage()==null ? "测试超时；请检查网络/密钥/模型名" : cause.getMessage()));
        } finally {
            model.close();
            worker.shutdownNow();
        }
        result.put("latency_ms",Math.round((System.nanoTime()-started)/1_000_000d));
        return result;
    }
}
