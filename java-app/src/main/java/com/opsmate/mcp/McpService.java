package com.opsmate.mcp;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsmate.agent.DynamicTools;
import com.opsmate.infrastructure.*;
import jakarta.annotation.PreDestroy;
import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class McpService implements DynamicTools {
    private final Path file;
    private final JsonFiles files;
    private final ObjectMapper json;
    private final int timeout;
    private final Map<String,Stdio> sessions=new HashMap<>();
    private final ScheduledExecutorService deadlines=Executors.newSingleThreadScheduledExecutor(r -> { Thread thread=new Thread(r,"opsmate-mcp-deadlines"); thread.setDaemon(true); return thread; });
    private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).followRedirects(HttpClient.Redirect.NEVER).build();
    private static final Map<String,Object> INITIALIZE=Map.of("protocolVersion","2024-11-05","capabilities",Map.of(),"clientInfo",Map.of("name","OpsMate","version","1.0.0"));
    public McpService(RuntimePaths paths,JsonFiles files,ObjectMapper json,@Value("${opsmate.mcp-timeout-seconds:30}") int timeout) {
        this.file=paths.data().resolve("mcp_servers.json"); this.files=files; this.json=json; this.timeout=timeout;
    }
    public synchronized List<Map<String,Object>> servers() {
        try { return json.readValue(Files.readString(file,StandardCharsets.UTF_8),new TypeReference<ArrayList<Map<String,Object>>>(){}); }
        catch (Exception absent) { return new ArrayList<>(); }
    }
    public synchronized void save(List<Map<String,Object>> records) {
        files.write(file,records);
        for (String id:new ArrayList<>(sessions.keySet())) {
            var server=records.stream().filter(s -> id.equals(s.get("id"))&&Boolean.TRUE.equals(s.getOrDefault("enabled",true))).findFirst();
            Stdio session=sessions.get(id);
            if (server.isEmpty()||!Objects.equals(server.get().get("command"),session.command)||!"stdio".equals(server.get().get("transport"))) { sessions.remove(id); session.close(); }
        }
    }
    public static void validate(Map<String,Object> server) {
        String name=Objects.toString(server.get("name"),"");
        if (name.isBlank()||name.length()>40) throw new ApiFailure(422,"服务器名称必填且不超过40字");
        if ("stdio".equals(server.get("transport"))) {
            if (!(server.get("command") instanceof List<?> command)||command.isEmpty()||command.size()>20||command.stream().anyMatch(v -> !(v instanceof String s)||s.isBlank())) throw new ApiFailure(400,"stdio 服务器需提供 command 命令行数组");
        } else if ("http".equals(server.get("transport"))) {
            String url=Objects.toString(server.get("url"),"");
            if (!(url.startsWith("http://")||url.startsWith("https://"))) throw new ApiFailure(400,"http 服务器需提供 http(s) url");
        } else throw new ApiFailure(422,"传输类型无效");
    }
    public synchronized String add(Map<String,Object> record) {
        validate(record);
        var records=servers();
        if (records.stream().anyMatch(s -> Objects.equals(s.get("name"),record.get("name")))) throw new ApiFailure(400,"服务器 "+record.get("name")+" 已存在");
        String id=UUID.randomUUID().toString().replace("-","").substring(0,12);
        var server=new LinkedHashMap<>(record); server.put("id",id); records.add(server); save(records);
        return id;
    }
    public synchronized void update(String id,Map<String,Object> body) {
        validate(body);
        var records=servers();
        var record=records.stream().filter(s -> id.equals(s.get("id"))).findFirst().orElseThrow(() -> new ApiFailure(404,"服务器不存在"));
        record.putAll(body); save(records);
    }
    public synchronized void delete(String id) {
        var records=servers();
        if (!records.removeIf(s -> id.equals(s.get("id")))) throw new ApiFailure(404,"服务器不存在");
        save(records);
    }
    public Map<String,Object> server(String id) { return servers().stream().filter(s -> id.equals(s.get("id"))).findFirst().orElseThrow(() -> new ApiFailure(404,"服务器不存在")); }
    private final class Stdio implements AutoCloseable {
        private final Process process;
        private final List<String> command;
        private final BufferedWriter writer;
        private final BlockingQueue<String> queue=new LinkedBlockingQueue<>(256);
        private long id;
        Stdio(List<String> command) throws IOException {
            this.command=List.copyOf(command);
            process=new ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.DISCARD).start();
            writer=new BufferedWriter(new OutputStreamWriter(process.getOutputStream(),StandardCharsets.UTF_8));
            Thread.startVirtualThread(() -> {
                try (var reader=new BufferedReader(new InputStreamReader(process.getInputStream(),StandardCharsets.UTF_8))) {
                    String line;
                    while ((line=reader.readLine())!=null) {
                        if (line.length()>2_000_000||!queue.offer(line)) { close(); break; }
                    }
                } catch (IOException ignored) { }
                finally { queue.offer(""); }
            });
        }
        synchronized void notifyInitialized() throws Exception {
            writer.write(json.writeValueAsString(Map.of("jsonrpc","2.0","method","notifications/initialized"))+"\n"); writer.flush();
        }
        synchronized Map<String,Object> request(String method,Map<String,Object> params) throws Exception {
            long requestId=++id;
            writer.write(json.writeValueAsString(Map.of("jsonrpc","2.0","id",requestId,"method",method,"params",params))+"\n"); writer.flush();
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(timeout);
            while (true) {
                long remaining=deadline-System.nanoTime();
                if (remaining<=0) throw new IllegalStateException("MCP 请求超时："+method);
                String line=queue.poll(remaining,TimeUnit.NANOSECONDS);
                if (line==null) throw new IllegalStateException("MCP 请求超时："+method);
                if (line.isEmpty()) throw new IllegalStateException("MCP 进程已退出");
                var reply=json.readValue(line,new TypeReference<Map<String,Object>>(){});
                if (!(reply.get("id") instanceof Number number)||number.longValue()!=requestId) continue;
                return result(reply);
            }
        }
        @Override public void close() {
            process.descendants().forEach(child -> child.destroyForcibly());
            process.destroyForcibly();
            try { process.getInputStream().close(); } catch (IOException ignored) { }
            try { process.getOutputStream().close(); } catch (IOException ignored) { }
        }
    }
    @SuppressWarnings("unchecked")
    private Map<String,Object> result(Map<String,Object> reply) {
        if (reply.containsKey("error")) throw new IllegalStateException("MCP 服务返回协议错误");
        return reply.get("result") instanceof Map<?,?> value?(Map<String,Object>)value:Map.of();
    }
    @SuppressWarnings("unchecked")
    private synchronized Stdio stdio(Map<String,Object> server) throws Exception {
        String id=server.get("id").toString();
        Stdio session=sessions.get(id);
        if (session!=null&&session.process.isAlive()) return session;
        if (session!=null) session.close();
        session=new Stdio((List<String>)server.get("command"));
        try { session.request("initialize",INITIALIZE); session.notifyInitialized(); }
        catch (Exception failed) { session.close(); throw failed; }
        sessions.put(id,session); return session;
    }
    private record HttpReply(Map<String,Object> result,String session) { }
    private HttpReply http(Map<String,Object> server,String method,Map<String,Object> params,String session) throws Exception {
        var request=HttpRequest.newBuilder(URI.create(server.get("url").toString())).timeout(Duration.ofSeconds(timeout))
            .header("Content-Type","application/json").header("Accept","application/json, text/event-stream");
        if (session!=null) request.header("Mcp-Session-Id",session);
        request.POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(Map.of("jsonrpc","2.0","id",1,"method",method,"params",params))));
        var response=http.send(request.build(),HttpResponse.BodyHandlers.ofInputStream());
        var deadline=deadlines.schedule(() -> { try { response.body().close(); } catch (IOException ignored) { } },timeout,TimeUnit.SECONDS);
        try (var body=response.body()) {
            if (response.statusCode()>=300) throw new IllegalStateException("MCP HTTP "+response.statusCode());
            byte[] bytes=body.readNBytes(2_000_001);
            if (bytes.length>2_000_000) throw new IllegalStateException("MCP 响应超过上限");
            String text=new String(bytes,StandardCharsets.UTF_8);
            if (response.headers().firstValue("Content-Type").orElse("").contains("text/event-stream")) {
                text=text.lines().filter(line -> line.startsWith("data:")).map(line -> line.substring(5).strip()).filter(s -> !s.isEmpty()).findFirst().orElseThrow();
            }
            return new HttpReply(result(json.readValue(text,new TypeReference<Map<String,Object>>(){})),response.headers().firstValue("Mcp-Session-Id").orElse(session));
        } finally { deadline.cancel(false); }
    }
    private Map<String,Object> rpc(Map<String,Object> server,String method,Map<String,Object> params) {
        try {
            if ("http".equals(server.get("transport"))) {
                var init=http(server,"initialize",INITIALIZE,null);
                return http(server,method,params,init.session()).result();
            }
            return stdio(server).request(method,params);
        } catch (Exception failure) {
            synchronized (this) { Stdio session=sessions.remove(Objects.toString(server.get("id"),"")); if (session!=null) session.close(); }
            if (failure instanceof InterruptedException) Thread.currentThread().interrupt();
            String message=failure instanceof IllegalStateException?failure.getMessage():"MCP 连接失败，请检查命令、网络与服务配置";
            throw new IllegalStateException(message);
        }
    }
    @SuppressWarnings("unchecked")
    public List<Map<String,Object>> tools(Map<String,Object> server) {
        Object value=rpc(server,"tools/list",Map.of()).get("tools");
        return value instanceof List<?> list?(List<Map<String,Object>>)list:List.of();
    }
    private static String slug(String name) { return AssistantName.clip(name.replaceAll("[^a-zA-Z0-9_]","-"),24); }
    // Local helper keeps MCP independent from assistant persistence.
    private static final class AssistantName { static String clip(String s,int n) { return s.isEmpty()?"srv":s.substring(0,Math.min(s.length(),n)); } }
    @Override public Map<String,String> descriptions() {
        Map<String,String> result=new LinkedHashMap<>();
        for (var server:servers()) if (Boolean.TRUE.equals(server.getOrDefault("enabled",true))) {
            try { for (var tool:tools(server)) if (tool.get("name") instanceof String name&&!name.isBlank()) result.put("mcp__"+slug(server.get("name").toString())+"__"+name,"[MCP:"+server.get("name")+"] "+Objects.toString(tool.get("description"),name)); }
            catch (IllegalStateException unavailable) { }
        }
        return result;
    }
    @Override public boolean accepts(String name) { return name.startsWith("mcp__"); }
    @Override public Map<String,Object> execute(String name,Map<String,Object> args) {
        String[] parts=name.split("__",3);
        if (parts.length!=3) return Map.of("ok",false,"error","非法 MCP 工具名");
        var server=servers().stream().filter(s -> Boolean.TRUE.equals(s.getOrDefault("enabled",true))&&slug(Objects.toString(s.get("name"),"")).equals(parts[1])).findFirst();
        if (server.isEmpty()) return Map.of("ok",false,"error","MCP 服务器不存在或已停用");
        try {
            var response=rpc(server.get(),"tools/call",Map.of("name",parts[2],"arguments",args));
            StringBuilder text=new StringBuilder();
            if (response.get("content") instanceof List<?> content) for (Object item:content) if (item instanceof Map<?,?> map&&map.get("text") instanceof String value) text.append(value).append('\n');
            String value=text.isEmpty()?"(空结果)":text.substring(0,Math.min(text.length(),8000)).stripTrailing();
            return Boolean.TRUE.equals(response.get("isError"))?Map.of("ok",false,"error",value):Map.of("ok",true,"result",value);
        } catch (IllegalStateException failure) { return Map.of("ok",false,"error",failure.getMessage()); }
    }
    @PreDestroy public synchronized void close() { sessions.values().forEach(Stdio::close); sessions.clear(); http.shutdownNow(); deadlines.shutdownNow(); }
}
