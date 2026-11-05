package com.opsmate.infrastructure;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.*;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class JsonFiles {
    private final ObjectMapper json;
    public JsonFiles(ObjectMapper json) { this.json=json; }

    @SuppressWarnings("unchecked")
    public Map<String,Object> read(Path path) {
        if (!Files.exists(path)) return new java.util.LinkedHashMap<>();
        try { return json.readValue(path.toFile(),Map.class); }
        catch (Exception failure) { throw new ApiFailure(500,"本机配置读取失败，请检查本地文件"); }
    }

    public void write(Path path,Object value) {
        Path temporary=null;
        try {
            Files.createDirectories(path.getParent());
            temporary=Files.createTempFile(path.getParent(),path.getFileName()+".",".tmp");
            json.writerWithDefaultPrettyPrinter().writeValue(temporary.toFile(),value);
            try { Files.move(temporary,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING); }
            catch (AtomicMoveNotSupportedException unavailable) {
                Files.move(temporary,path,StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (Exception failure) {
            throw new ApiFailure(500,"本机配置保存失败，请检查目录权限");
        } finally {
            if (temporary!=null) {
                try { Files.deleteIfExists(temporary); }
                catch (java.io.IOException ignored) { /* Temporary configuration stays local. */ }
            }
        }
    }
}
