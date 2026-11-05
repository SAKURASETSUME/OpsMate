package com.opsmate.infrastructure;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Central definition of writable storage and read-only knowledge locations. */
@Component
public class RuntimePaths {
    private final Path data;
    private final Path knowledge;

    public RuntimePaths(@Value("${opsmate.data:}") String data,
                        @Value("${opsmate.knowledge:}") String knowledge) throws java.io.IOException {
        String launcher=System.getProperty("jpackage.app-path","");
        boolean packaged=!launcher.isBlank();
        Path home=packaged?Path.of(launcher).toAbsolutePath().getParent():Path.of("").toAbsolutePath();
        this.data = (data.isBlank()?home.resolve(packaged?"data":"target/local-data"):Path.of(data)).toAbsolutePath().normalize();
        this.knowledge = (knowledge.isBlank()?(packaged?this.data:home.resolve("../data")):Path.of(knowledge)).toAbsolutePath().normalize();
        Files.createDirectories(this.data);
        if (packaged&&knowledge.isBlank()) landKnowledge();
    }

    private void landKnowledge() throws java.io.IOException {
        try (var manifest=RuntimePaths.class.getResourceAsStream("/knowledge/manifest.txt")) {
            if (manifest==null) throw new java.io.IOException("发布包缺少知识清单");
            try (var lines=new BufferedReader(new InputStreamReader(manifest,StandardCharsets.UTF_8))) {
                for (String name:lines.lines().toList()) {
                    if (name.isBlank()) continue;
                    Path target=knowledge.resolve(name).normalize();
                    if (!target.startsWith(knowledge)||name.contains("..")||name.contains("\\")) throw new java.io.IOException("发布知识清单路径无效");
                    if (name.startsWith("skills/")&&Files.exists(knowledge.resolve("skills/.initialized"))) continue;
                    Files.createDirectories(target.getParent());
                    if (Files.exists(target)) continue;
                    try (var source=RuntimePaths.class.getResourceAsStream("/knowledge/"+name)) {
                        if (source==null) throw new java.io.IOException("发布包缺少内置资料："+name);
                        Files.copy(source,target);
                    }
                }
            }
        }
    }

    public Path data() { return data; }
    public Path knowledge() { return knowledge; }
}
