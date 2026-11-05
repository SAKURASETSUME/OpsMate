package com.opsmate;

import com.opsmate.infrastructure.RuntimePaths;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.junit.jupiter.api.Assertions.*;

class KnowledgeLandingTest {
    @TempDir Path temporary;
    @Test void packagedEmptyDirectoriesLandKnowledgeAndUserEditsSurvive() throws Exception {
        String previous=System.getProperty("jpackage.app-path");
        try {
            System.setProperty("jpackage.app-path",temporary.resolve("中文 空格/OpsMate.exe").toString());
            Path data=temporary.resolve("中文 空格/data");
            Files.createDirectories(data.resolve("commands")); Files.createDirectories(data.resolve("kb"));
            RuntimePaths first=new RuntimePaths("","");
            assertEquals(data.toAbsolutePath(),first.data());
            try (var files=Files.list(data.resolve("commands"))) { assertEquals(621,files.count()); }
            try (var files=Files.list(data.resolve("kb"))) { assertEquals(15,files.count()); }
            try (var files=Files.list(data.resolve("skills"))) { assertEquals(6,files.count()); }
            Path nginx=data.resolve("kb/nginx.yaml");
            Files.writeString(nginx,"user changed",StandardCharsets.UTF_8);
            Path skill;
            try (var files=Files.list(data.resolve("skills"))) { skill=files.findFirst().orElseThrow(); }
            Files.writeString(data.resolve("skills/.initialized"),"1",StandardCharsets.UTF_8); Files.delete(skill);
            new RuntimePaths("","");
            assertEquals("user changed",Files.readString(nginx,StandardCharsets.UTF_8));
            assertFalse(Files.exists(skill));
        } finally {
            if (previous==null) System.clearProperty("jpackage.app-path"); else System.setProperty("jpackage.app-path",previous);
        }
    }
}
