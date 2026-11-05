package com.opsmate;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsmate.llm.LlmClient;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class LlmWireTest {
    @Test
    void arkConnectivityHasRoomForReasoningWithoutChangingCustomServers() {
        for (String base:List.of("https://ark.cn-beijing.volces.com/api/plan/v3","http://127.0.0.1:1234")) {
            try (var model=new LlmClient(Map.of("base_url",base,"model","ark-code-latest","api_key","synthetic"),new ObjectMapper())) {
                var body=model.requestBody(List.of(),false,0,8,"low");
                assertEquals(base.contains("volces.com")?4096:8,body.get("max_tokens"));
                assertFalse(body.containsKey("thinking"));
                assertEquals(12000,model.requestBody(List.of(),false,0,12000,"low").get("max_tokens"));
                assertEquals(12000,model.requestBody(List.of(),true,0,12000,"low").get("max_tokens"));
            }
        }
    }
    @Test
    void requestAdapterPreservesOfficialGlmReasoningBudget() {
        try (var model=new LlmClient(Map.of("base_url","https://open.bigmodel.cn/api/paas/v4",
                "model","GLM-5.3","api_key","synthetic"),new ObjectMapper())) {
            var body=model.requestBody(List.of(),false,0,8,"high");
            assertEquals(4096,body.get("max_tokens"));
            assertEquals("high",body.get("reasoning_effort"));
        }
    }

    @Test
    void modelWireRetriesOnceSeparatesReasoningAndRedactsErrors() throws Exception {
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        AtomicInteger attempts=new AtomicInteger();
        server.createContext("/retry/chat/completions",exchange -> {
            exchange.getRequestBody().readAllBytes();
            byte[] body;
            int status;
            if (attempts.incrementAndGet()==1) {
                status=429; body="limited".getBytes(StandardCharsets.UTF_8);
            } else {
                status=200; body="{\"choices\":[{\"message\":{\"content\":\"pong\"}}]}".getBytes(StandardCharsets.UTF_8);
            }
            exchange.sendResponseHeaders(status,body.length);
            exchange.getResponseBody().write(body); exchange.close();
        });
        server.createContext("/stream/chat/completions",exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set("Content-Type","text/event-stream");
            byte[] bytes=("data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"思考\"}}]}\n\n"
                +"data: {\"choices\":[{\"delta\":{\"content\":\"中文正文\"}}]}\n\n"
                +"data: [DONE]\n\n").getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200,bytes.length);
            exchange.getResponseBody().write(bytes); exchange.close();
        });
        server.createContext("/bad/chat/completions",exchange -> {
            byte[] bytes="synthetic-secret invalid".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(401,bytes.length);
            exchange.getResponseBody().write(bytes); exchange.close();
        });
        server.start();
        String base="http://127.0.0.1:"+server.getAddress().getPort();
        try {
            try (var model=client(base+"/retry")) {
                assertEquals("pong",model.chat(List.of(),0,5,8,null));
                assertEquals(2,attempts.get());
            }
            try (var model=client(base+"/stream")) {
                List<String> events=new ArrayList<>();
                model.stream(List.of(),0.3,5,null,(kind,text) -> events.add(kind+":"+text));
                assertEquals(List.of("thinking:思考","delta:中文正文"),events);
            }
            try (var model=client(base+"/bad")) {
                var error=assertThrows(IllegalStateException.class,() -> model.chat(List.of(),0,5,8,null));
                assertTrue(error.getMessage().contains("401"));
                assertFalse(error.getMessage().contains("synthetic-secret"));
            }
        } finally { server.stop(0); }
    }

    private LlmClient client(String base) {
        return new LlmClient(Map.of("base_url",base,"model","synthetic","api_key","synthetic-secret"),new ObjectMapper());
    }
}
