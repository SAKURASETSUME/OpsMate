package com.opsmate.assistant;

import com.opsmate.agent.*;
import java.io.*;
import java.nio.charset.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import org.springframework.context.annotation.*;

@Configuration(proxyBeanMethods=false)
class WorkspaceTools {
    @Bean AgentTool listDirectory(WorkspaceService workspace) { return tool("list_dir","浏览授权工作目录，args={path:路径}，最多300项",workspace); }
    @Bean AgentTool readWorkspaceFile(WorkspaceService workspace) { return tool("read_workspace_file","读取授权目录内UTF-8文件，args={path:路径}，最多200KB",workspace); }
    @Bean AgentTool writeWorkspaceFile(WorkspaceService workspace) { return tool("write_workspace_file","写入授权目录内文件，args={path:路径,content:文本}，子目录自动创建",workspace); }
    @Bean AgentTool runWorkspaceCommand(WorkspaceService workspace) { return tool("run_command","执行工作目录命令，args={command:命令,cwd:授权目录,timeout:5到120秒}",workspace); }
    private AgentTool tool(String name,String description,WorkspaceService workspace) {
        return new AgentTool() {
            @Override public String name() { return name; }
            @Override public String description() { return description; }
            @Override public Map<String,Object> execute(Map<String,Object> args,ToolScope scope) throws Exception {
                try { return Map.of("ok",true,"result",executeWorkspace(name,args,workspace)); }
                catch (com.opsmate.infrastructure.ApiFailure expected) { return Map.of("ok",false,"error",expected.getMessage()); }
            }
        };
    }
    private Map<String,Object> executeWorkspace(String name,Map<String,Object> args,WorkspaceService workspace) throws Exception {
        String value=Objects.toString(args.get("path"),"");
        if (name.equals("run_command")) return command(args,workspace);
        Path target=workspace.resolve(value,!name.equals("write_workspace_file"));
        if (name.equals("list_dir")) {
            if (!Files.isDirectory(target)) throw new IllegalArgumentException();
            List<Map<String,Object>> entries=new ArrayList<>();
            try (var stream=Files.list(target)) {
                for (Path child:stream.sorted(Comparator.comparing((Path p) -> !Files.isDirectory(p)).thenComparing(p -> p.getFileName().toString().toLowerCase(Locale.ROOT))).limit(300).toList()) {
                    var item=new LinkedHashMap<String,Object>();
                    item.put("name",child.getFileName().toString()); item.put("type",Files.isDirectory(child)?"dir":"file");
                    item.put("size",Files.isRegularFile(child)?Files.size(child):null); entries.add(item);
                }
            }
            return Map.of("path",target.toString(),"entries",entries);
        }
        if (name.equals("read_workspace_file")) {
            if (!Files.isRegularFile(target)||Files.size(target)>200_000) throw new com.opsmate.infrastructure.ApiFailure(400,"文件不存在或超过200KB读取上限");
            String content=StandardCharsets.UTF_8.decode(java.nio.ByteBuffer.wrap(Files.readAllBytes(target))).toString();
            return Map.of("path",target.toString(),"content",content);
        }
        String content=Objects.toString(args.get("content"),"");
        if (content.isEmpty()||content.length()>1_000_000) throw new IllegalArgumentException();
        Files.createDirectories(target.getParent());
        // Resolve again after mkdir, before opening any destination.
        target=workspace.resolve(target.toString(),false);
        Path temporary=Files.createTempFile(target.getParent(),"opsmate-",".tmp");
        try {
            Files.writeString(temporary,content,StandardCharsets.UTF_8);
            Files.move(temporary,target,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
        } finally { Files.deleteIfExists(temporary); }
        return Map.of("path",target.toString(),"bytes",content.getBytes(StandardCharsets.UTF_8).length);
    }
    private static String readOutput(InputStream input,int limit) throws IOException {
        ByteArrayOutputStream kept=new ByteArrayOutputStream();
        byte[] buffer=new byte[8192]; int size;
        while ((size=input.read(buffer))!=-1) if (kept.size()<limit*4) kept.write(buffer,0,Math.min(size,limit*4-kept.size()));
        byte[] bytes=kept.toByteArray(); String text;
        try { text=StandardCharsets.UTF_8.newDecoder().decode(java.nio.ByteBuffer.wrap(bytes)).toString(); }
        catch (CharacterCodingException legacy) { text=new String(bytes,Charset.forName("GBK")); }
        return AssistantStore.clip(text,limit);
    }
    private Map<String,Object> command(Map<String,Object> args,WorkspaceService workspace) throws Exception {
        String command=Objects.toString(args.get("command"),"").strip();
        if (command.isEmpty()||command.length()>2000) throw new IllegalArgumentException();
        int timeout=30;
        try { timeout=Math.clamp(Integer.parseInt(Objects.toString(args.get("timeout"),"30")),5,120); }
        catch (NumberFormatException ignored) { }
        Path cwd=workspace.resolve(Objects.toString(args.get("cwd"),""),true);
        if (!Files.isDirectory(cwd)) throw new IllegalArgumentException();
        Process process=new ProcessBuilder("cmd.exe","/d","/s","/c",command).directory(cwd.toFile()).start();
        try (var readers=Executors.newVirtualThreadPerTaskExecutor()) {
            Future<String> stdout=readers.submit(() -> readOutput(process.getInputStream(),4000));
            Future<String> stderr=readers.submit(() -> readOutput(process.getErrorStream(),2000));
            try {
                if (!process.waitFor(timeout,TimeUnit.SECONDS)) throw new com.opsmate.infrastructure.ApiFailure(400,"命令超时，已终止");
                return Map.of("command",command,"cwd",cwd.toString(),"returncode",process.exitValue(),"stdout",stdout.get(3,TimeUnit.SECONDS),"stderr",stderr.get(3,TimeUnit.SECONDS));
            } finally {
                process.descendants().forEach(child -> child.destroyForcibly());
                process.destroyForcibly();
                process.getInputStream().close(); process.getErrorStream().close();
                stdout.cancel(true); stderr.cancel(true);
            }
        }
    }
}
