package com.opsmate.assistant;

import com.opsmate.agent.*;
import com.opsmate.infrastructure.*;
import com.opsmate.kb.KnowledgeService;
import java.io.*;
import java.nio.charset.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.regex.*;
import java.util.zip.*;
import org.springframework.context.annotation.*;

@Configuration(proxyBeanMethods=false)
class SystemTools {
    @Bean AgentTool systemInfo() { return SetupTools.tool("system_info","读取系统、CPU、磁盘信息，args={}",args -> {
        List<Map<String,Object>> drives=new ArrayList<>();
        for (File root:File.listRoots()) drives.add(Map.of("drive",root.toString(),"total_gb",Math.round(root.getTotalSpace()/107374182.4)/10.0,"free_gb",Math.round(root.getUsableSpace()/107374182.4)/10.0));
        return Map.of("ok",true,"result",Map.of("os",System.getProperty("os.name")+" "+System.getProperty("os.version")+" ("+System.getProperty("os.arch")+")","java",System.getProperty("java.version"),"cpu_count",Runtime.getRuntime().availableProcessors(),"drives",drives,"cwd",Path.of("").toAbsolutePath().toString()));
    }); }
    @Bean AgentTool manageWorkspace(WorkspaceService workspace) { return SetupTools.tool("manage_workspace","用户明确要求时添加/移除授权目录，args={action:add|remove,path:绝对目录}",args -> {
        String action=Objects.toString(args.get("action"),""),value=Objects.toString(args.get("path"),"");
        List<String> directories=new ArrayList<>(workspace.directories());
        if (action.equals("add")) directories.add(value);
        else if (action.equals("remove")) directories.remove(Path.of(value).toAbsolutePath().normalize().toString());
        else throw new ApiFailure(400,"action必须为add或remove");
        return Map.of("ok",true,"result",Map.of("directories",workspace.save(directories)));
    }); }
    @Bean AgentTool installKnowledge(KnowledgeService knowledge) { return SetupTools.tool("install_kb","安装本机知识YAML，args={filename:小写英文短横线,content:YAML}；cli/conf必须分开",args -> Map.of("ok",true,"result",knowledge.install(Objects.toString(args.get("filename"),""),Objects.toString(args.get("content"),"")))); }
    @Bean AgentTool listProcesses() { return SetupTools.tool("list_processes","读取Windows进程，args={name:可选名称过滤,limit:1到100}",args -> {
        int limit=40; try { limit=Math.clamp(Integer.parseInt(Objects.toString(args.get("limit"),"40")),1,100); } catch (NumberFormatException ignored) { }
        String filter=Objects.toString(args.get("name"),"").toLowerCase(Locale.ROOT);
        List<Map<String,Object>> processes=new ArrayList<>();
        for (String line:process(List.of("tasklist.exe","/FO","CSV","/NH")).output().split("\\R")) {
            String[] fields=line.replaceFirst("^\"","").replaceFirst("\"$","").split("\",\"");
            if (fields.length>=5&&fields[0].toLowerCase(Locale.ROOT).contains(filter)) processes.add(Map.of("name",fields[0],"pid",fields[1],"mem",fields[4]));
            if (processes.size()>=limit) break;
        }
        return Map.of("ok",true,"result",Map.of("count",processes.size(),"processes",processes));
    }); }
    @Bean AgentTool stopProcess() { return SetupTools.tool("stop_process","仅用户明确要求时结束指定进程，args={pid:数字或name:精确进程名}；不得结束OpsMate自己",args -> {
        String pid=Objects.toString(args.get("pid"),""),name=Objects.toString(args.get("name"),"");
        List<String> command;
        if (pid.matches("[0-9]+")&&!pid.equals(Long.toString(ProcessHandle.current().pid()))) command=List.of("taskkill.exe","/PID",pid,"/F");
        else if (!name.isBlank()&&name.matches("[\\p{L}\\p{N}_.\\- ]{1,60}")&&!name.equalsIgnoreCase("OpsMate.exe")&&!name.equalsIgnoreCase("java.exe")) command=List.of("taskkill.exe","/IM",name,"/F");
        else throw new ApiFailure(400,"需提供有效pid或精确进程名，不能结束自身");
        var done=process(command);
        var result=new LinkedHashMap<String,Object>(); result.put("ok",done.code()==0); result.put("error",done.code()==0?null:AssistantStore.clip(done.output(),200)); return result;
    }); }
    @Bean AgentTool openPath(WorkspaceService workspace,RuntimePaths paths) { return SetupTools.tool("open_path","用户明确要求时打开授权工作目录或agent_downloads内文件，args={path}",args -> {
        String value=Objects.toString(args.get("path"),"");
        Path target;
        try { target=workspace.resolve(value,true); }
        catch (ApiFailure outside) {
            Path downloads=paths.data().resolve("agent_downloads").toAbsolutePath().normalize();
            target=(Path.of(value).isAbsolute()?Path.of(value):downloads.resolve(value)).toRealPath();
            if (!target.startsWith(downloads.toRealPath())) throw new ApiFailure(400,"路径不在授权目录或下载目录内");
        }
        new ProcessBuilder("explorer.exe",target.toString()).start();
        return Map.of("ok",true,"result",Map.of("opened",target.toString()));
    }); }
    @Bean AgentTool archiveFiles(WorkspaceService workspace) { return SetupTools.tool("archive_files","授权目录内zip/unzip，args={action,source,target}，拒绝路径穿越与链接越界",args -> {
        Path source=workspace.resolve(Objects.toString(args.get("source"),""),true),target=workspace.resolve(Objects.toString(args.get("target"),""),false);
        String action=Objects.toString(args.get("action"),"");
        if (action.equals("zip")) {
            Files.createDirectories(target.getParent());
            target=workspace.resolve(target.toString(),false);
            if (source.equals(target)) throw new ApiFailure(400,"归档源与目标不能相同");
            Path temporary=Files.createTempFile(target.getParent(),"archive-",".tmp");
            try {
                try (var zip=new ZipOutputStream(Files.newOutputStream(temporary),StandardCharsets.UTF_8)) {
                    List<Path> candidates;
                    if (Files.isRegularFile(source)) candidates=List.of(source);
                    else try (var walk=Files.walk(source)) { candidates=walk.filter(Files::isRegularFile).limit(10001).toList(); }
                    if (candidates.size()>10000) throw new ApiFailure(400,"归档超过10000文件上限");
                    for (Path child:candidates) {
                        if (child.equals(target)||child.equals(temporary)) continue;
                        workspace.resolve(child.toString(),true);
                        zip.putNextEntry(new ZipEntry((Files.isDirectory(source)?source.relativize(child):child.getFileName()).toString().replace('\\','/')));
                        Files.copy(child,zip); zip.closeEntry();
                    }
                }
                Files.move(temporary,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            } finally { Files.deleteIfExists(temporary); }
            return Map.of("ok",true,"result",Map.of("zip",target.toString(),"size_bytes",Files.size(target)));
        }
        if (!action.equals("unzip")) throw new ApiFailure(400,"action必须是zip或unzip");
        int count=0; long total=0;
        // Preflight every entry before writing any files; reject zip-slip and junction destinations.
        try (var zip=new ZipFile(source.toFile(),StandardCharsets.UTF_8)) {
            var entries=zip.entries();
            while (entries.hasMoreElements()) {
                var entry=entries.nextElement(); count++;
                Path destination=target.resolve(entry.getName().replace('\\','/')).normalize();
                if (!destination.startsWith(target)||entry.getName().contains(":")) throw new ApiFailure(400,"压缩包包含越界路径");
                workspace.resolve(destination.toString(),false);
                total+=Math.max(0,entry.getSize());
                if (count>10000||total>300L*1024*1024) throw new ApiFailure(400,"解压超过数量或300MB上限");
            }
            Files.createDirectories(target); entries=zip.entries(); total=0;
            while (entries.hasMoreElements()) {
                var entry=entries.nextElement(); Path destination=workspace.resolve(target.resolve(entry.getName().replace('\\','/')).toString(),false);
                if (entry.isDirectory()) { Files.createDirectories(destination); continue; }
                Files.createDirectories(destination.getParent()); destination=workspace.resolve(destination.toString(),false);
                Path temporary=Files.createTempFile(destination.getParent(),"unzip-",".tmp");
                try {
                    try (var input=zip.getInputStream(entry);var output=Files.newOutputStream(temporary)) {
                        byte[] buffer=new byte[8192]; int size;
                        while ((size=input.read(buffer))!=-1) { total+=size; if (total>300L*1024*1024) throw new ApiFailure(400,"解压超过300MB上限"); output.write(buffer,0,size); }
                    }
                    Files.move(temporary,destination,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
                } finally { Files.deleteIfExists(temporary); }
            }
        }
        return Map.of("ok",true,"result",Map.of("unpacked_to",target.toString(),"files",count));
    }); }
    @Bean AgentTool scheduleTask() { return SetupTools.tool("schedule_task","仅用户明确要求时管理OpsMate_前缀计划任务，args={action:create|delete|list,name,schedule:daily HH:mm,command}",args -> {
        String action=Objects.toString(args.get("action"),"");
        String name="OpsMate_"+AssistantStore.clip(Objects.toString(args.get("name"),"").replaceAll("[^\\p{L}\\p{N}_-]","-"),40);
        if (action.equals("list")) return Map.of("ok",true,"result",Map.of("tasks",process(List.of("schtasks.exe","/Query","/FO","CSV","/NH")).output().lines().filter(s -> s.contains("OpsMate_")).limit(20).toList()));
        List<String> command;
        String schedule=Objects.toString(args.get("schedule"),""),taskCommand=Objects.toString(args.get("command"),"");
        if (action.equals("create")) {
            var time=Pattern.compile("daily\\s+([0-9]{1,2}):([0-9]{2})",Pattern.CASE_INSENSITIVE).matcher(schedule);
            if (!time.matches()||Integer.parseInt(time.group(1))>23||Integer.parseInt(time.group(2))>59||taskCommand.isBlank()||taskCommand.length()>1000) throw new ApiFailure(400,"schedule形如daily 09:00，command必填≤1000字");
            command=List.of("schtasks.exe","/Create","/F","/SC","DAILY","/TN",name,"/TR",taskCommand,"/ST",String.format("%02d:%02d",Integer.parseInt(time.group(1)),Integer.parseInt(time.group(2))));
        } else if (action.equals("delete")&&name.length()>8) command=List.of("schtasks.exe","/Delete","/F","/TN",name);
        else throw new ApiFailure(400,"action必须是create/delete/list，name必填");
        var done=process(command);
        return done.code()==0?Map.of("ok",true,"result",Map.of(action.equals("create")?"created":"deleted",name)):Map.of("ok",false,"error",AssistantStore.clip(done.output(),200));
    }); }
    private record ProcessResult(int code,String output) { }
    private static ProcessResult process(List<String> command) throws Exception {
        Process process=new ProcessBuilder(command).redirectErrorStream(true).start();
        var executor=Executors.newVirtualThreadPerTaskExecutor();
        var output=executor.submit(() -> {
            ByteArrayOutputStream kept=new ByteArrayOutputStream(); byte[] buffer=new byte[8192]; int size;
            try (InputStream input=process.getInputStream()) { while ((size=input.read(buffer))!=-1) if (kept.size()<100_000) kept.write(buffer,0,Math.min(size,100_000-kept.size())); }
            return new String(kept.toByteArray(),Charset.forName("GBK"));
        });
        try {
            if (!process.waitFor(30,TimeUnit.SECONDS)) throw new ApiFailure(400,"系统命令超时");
            return new ProcessResult(process.exitValue(),output.get(3,TimeUnit.SECONDS));
        } finally { process.descendants().forEach(child -> child.destroyForcibly()); process.destroyForcibly(); process.getInputStream().close(); output.cancel(true); executor.shutdownNow(); }
    }
}
