package com.opsmate.llm;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.function.BiConsumer;

/** OpenAI-compatible wire client. Reasoning and answer text stay separate. */
public final class LlmClient implements AutoCloseable {
    private final ObjectMapper json;
    private final Map<String,Object> settings;
    private final HttpClient http;
    private volatile InputStream body;
    private volatile boolean closed;

    public LlmClient(Map<String,Object> settings,ObjectMapper json) {
        this.settings=new LinkedHashMap<>(settings);
        this.json=json;
        http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(20))
            .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    private String key() { return Objects.toString(settings.get("api_key"),""); }

    public String safe(String error) {
        String text=key().isEmpty() ? error : error.replace(key(),"[密钥已隐藏]");
        return text.substring(0,Math.min(text.length(),500));
    }

    public Map<String,Object> requestBody(List<Map<String,Object>> messages,boolean stream,
            double temperature,int tokens,String effort) {
        Map<String,Object> request=new LinkedHashMap<>();
        request.put("model",settings.get("model"));
        request.put("messages",messages);
        request.put("temperature",temperature);
        if (stream) request.put("stream",true);
        if (tokens>0) request.put("max_tokens",tokens);
        URI uri=URI.create(Objects.toString(settings.get("base_url"),""));
        // Coding-plan models may spend the first tokens on reasoning before emitting content.
        if ("ark.cn-beijing.volces.com".equals(uri.getHost())&&!stream&&tokens>0)
            request.put("max_tokens",Math.max(tokens,4096));
        if ("open.bigmodel.cn".equals(uri.getHost()) &&
                Objects.toString(settings.get("model"),"").toLowerCase(Locale.ROOT).startsWith("glm-5.3")) {
            request.put("thinking",Map.of("type","enabled"));
            request.put("reasoning_effort",effort==null||effort.isBlank() ? "low" : effort);
            if (!stream) request.put("max_tokens",Math.max(tokens,4096));
        }
        return request;
    }

    private HttpResponse<InputStream> send(Map<String,Object> request,int timeout) throws Exception {
        if (key().isEmpty()) throw new IllegalStateException("尚未配置 API key，请前往设置页保存密钥");
        String base=Objects.toString(settings.get("base_url"),"").replaceAll("/+$","");
        if (!(base.startsWith("http://")||base.startsWith("https://")) || Objects.toString(settings.get("model"),"").isBlank())
            throw new IllegalStateException("请在设置页填写有效的 base_url 与模型名");
        for (int attempt=0; attempt<2; attempt++) {
            if (closed||Thread.currentThread().isInterrupted()) throw new java.util.concurrent.CancellationException();
            var message=HttpRequest.newBuilder(URI.create(base+"/chat/completions"))
                .header("Content-Type","application/json").header("Authorization","Bearer "+key())
                .timeout(Duration.ofSeconds(timeout)).POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(request))).build();
            HttpResponse<InputStream> response=http.send(message,HttpResponse.BodyHandlers.ofInputStream());
            body=response.body();
            if (response.statusCode()==429 && attempt==0) {
                body.close();
                Thread.sleep(2000);
                continue;
            }
            if (response.statusCode()>=400) {
                String code="";
                try {
                    byte[] errorBytes=body.readNBytes(16384);
                    var error=json.readTree(errorBytes).path("error").path("code");
                    String value=error.asText("");
                    if (value.matches("\\d{1,8}") ||
                            Set.of("rate_limit_exceeded","insufficient_quota").contains(value)) code="（平台代码 "+value+"）";
                } catch (Exception ignored) { /* Never expose an untrusted error body. */ }
                body.close();
                throw new IllegalStateException("HTTP "+response.statusCode()+code+"；请检查网络/密钥/模型名与平台权限");
            }
            return response;
        }
        throw new IllegalStateException("模型服务未返回结果");
    }

    @SuppressWarnings("unchecked")
    public String chat(List<Map<String,Object>> messages,double temperature,int timeout,int tokens,String effort) {
        try {
            var response=send(requestBody(messages,false,temperature,tokens,effort),timeout);
            try (InputStream input=response.body()) {
                Map<String,Object> payload=json.readValue(input,Map.class);
                var choices=(List<Map<String,Object>>)payload.get("choices");
                var message=(Map<String,Object>)choices.getFirst().get("message");
                if (!(message.get("content") instanceof String content)||content.isBlank())
                    throw new IllegalStateException("模型响应为空，请重试");
                return content;
            }
        } catch (InterruptedException cancelled) {
            Thread.currentThread().interrupt();
            throw new java.util.concurrent.CancellationException();
        } catch (java.net.http.HttpTimeoutException timeoutError) {
            throw new IllegalStateException("请求超时；请检查网络/密钥/模型名");
        } catch (IllegalStateException error) {
            throw new IllegalStateException(safe(error.getMessage()));
        } catch (Exception error) {
            throw new IllegalStateException("连接模型服务失败或响应格式无效；请检查网络/模型名");
        }
    }

    @SuppressWarnings("unchecked")
    public void stream(List<Map<String,Object>> messages,double temperature,int timeout,String effort,
                       BiConsumer<String,String> onDelta) {
        Map<String,StringBuilder> pending=new HashMap<>();
        BiConsumer<String,String> filtered=(kind,text) -> {
            String secret=key();
            if (secret.isEmpty()) { onDelta.accept(kind,text); return; }
            StringBuilder buffer=pending.computeIfAbsent(kind,ignored -> new StringBuilder());
            buffer.append(text);
            String value=buffer.toString().replace(secret,"[密钥已隐藏]");
            int retained=0;
            for (int size=1;size<secret.length()&&size<=value.length();size++) if (value.endsWith(secret.substring(0,size))) retained=size;
            int end=value.length()-retained;
            if (end>0) onDelta.accept(kind,value.substring(0,end));
            buffer.setLength(0); buffer.append(value.substring(end));
        };
        try {
            var response=send(requestBody(messages,true,temperature,0,effort),timeout);
            try (var reader=new BufferedReader(new InputStreamReader(response.body(),StandardCharsets.UTF_8))) {
                String line;
                while ((line=reader.readLine())!=null) {
                    if (closed||Thread.currentThread().isInterrupted()) throw new java.util.concurrent.CancellationException();
                    if (!line.startsWith("data:")) continue;
                    String value=line.substring(5).strip();
                    if (value.equals("[DONE]")) break;
                    if (value.isEmpty()) continue;
                    var payload=json.readValue(value,Map.class);
                    var choices=(List<Map<String,Object>>)payload.get("choices");
                    if (choices==null||choices.isEmpty()) continue;
                    var delta=(Map<String,Object>)choices.getFirst().get("delta");
                    if (delta==null) continue;
                    Object reasoning=delta.getOrDefault("reasoning_content",delta.get("reasoning"));
                    if (reasoning instanceof String text&&!text.isEmpty()) filtered.accept("thinking",text);
                    if (delta.get("content") instanceof String text&&!text.isEmpty()) filtered.accept("delta",text);
                }
                pending.forEach((kind,buffer) -> { if (!buffer.isEmpty()) onDelta.accept(kind,buffer.toString()); });
            }
        } catch (java.util.concurrent.CancellationException cancelled) {
            throw cancelled;
        } catch (InterruptedException cancelled) {
            Thread.currentThread().interrupt();
            throw new java.util.concurrent.CancellationException();
        } catch (IllegalStateException error) {
            throw new IllegalStateException(safe(error.getMessage()));
        } catch (Exception error) {
            if (closed) throw new java.util.concurrent.CancellationException();
            throw new IllegalStateException("连接模型服务失败或流式响应格式无效；请检查网络/兼容协议");
        }
    }

    @Override public void close() {
        closed=true;
        InputStream current=body;
        if (current!=null) {
            try { current.close(); } catch (IOException ignored) { }
        }
        http.shutdownNow();
    }
}
