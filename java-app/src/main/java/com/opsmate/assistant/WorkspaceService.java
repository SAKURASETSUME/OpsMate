package com.opsmate.assistant;

import com.opsmate.infrastructure.*;
import java.nio.file.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class WorkspaceService {
    private final JsonFiles json;
    private final Path file;
    private final JdbcTemplate db;
    public WorkspaceService(JsonFiles json,RuntimePaths paths,JdbcTemplate db,AssistantStore initialized) {
        this.json=json; this.file=paths.data().resolve("agent_workspace.json"); this.db=db;
    }
    public synchronized List<String> directories() {
        try {
            Object values=json.read(file).get("directories");
            if (values instanceof List<?> items) return items.stream().filter(String.class::isInstance).map(Object::toString).toList();
        } catch (ApiFailure ignored) { }
        return List.of();
    }
    public synchronized List<String> save(List<String> values) {
        List<String> clean=new ArrayList<>();
        for (String value:values) {
            try {
                Path path=Path.of(value.strip());
                if (!path.isAbsolute()||!Files.isDirectory(path)) throw new java.io.IOException();
                String resolved=path.toRealPath().toString();
                if (!clean.contains(resolved)) clean.add(resolved);
            } catch (Exception invalid) { throw new ApiFailure(400,"目录不存在或不是绝对路径："+value); }
        }
        List<String> old=directories();
        json.write(file,Map.of("directories",clean));
        for (String removed:old) if (!clean.contains(removed)) db.update("UPDATE assistant_sessions SET workspace=NULL WHERE workspace=?",removed);
        return clean;
    }
    /** Resolve every existing ancestor, so junctions are checked even for a new nested target. */
    public Path resolve(String value,boolean mustExist) {
        Path raw;
        try { raw=Path.of(value.strip()); } catch (Exception invalid) { throw new ApiFailure(400,"路径无效"); }
        for (String directory:directories()) {
            try {
                Path root=Path.of(directory).toRealPath();
                Path target=(raw.isAbsolute()?raw:root.resolve(raw)).normalize();
                Path existing=target;
                while (existing!=null&&!Files.exists(existing,LinkOption.NOFOLLOW_LINKS)) existing=existing.getParent();
                if (existing==null) continue;
                Path resolved=existing.toRealPath().resolve(existing.relativize(target)).normalize();
                if (resolved.startsWith(root)&&(!mustExist||Files.exists(resolved))) return resolved;
            } catch (java.io.IOException ignored) { }
        }
        throw new ApiFailure(400,"路径不存在或不在已授权工作目录范围内");
    }
}
