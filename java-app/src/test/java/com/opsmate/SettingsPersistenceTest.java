package com.opsmate;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsmate.infrastructure.*;
import com.opsmate.llm.SettingsService;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.junit.jupiter.api.Assertions.*;

class SettingsPersistenceTest {
    @TempDir Path temporary;

    @Test
    void profilesKeepKeysLocalAndRequireExplicitActivation() throws Exception {
        ObjectMapper json=new ObjectMapper();
        var settings=new SettingsService(new RuntimePaths(temporary.toString(),temporary.toString()),new JsonFiles(json));
        Map<String,Object> initial=Map.of("provider","custom","base_url","https://example.invalid/v1///",
            "model","synthetic","api_key","first-synthetic-secret");
        settings.save(initial);
        settings.save(Map.of("provider","custom","base_url","https://example.invalid/v1",
            "model","synthetic","api_key",""));
        assertEquals("first-synthetic-secret",settings.effective().get("api_key"));
        assertEquals("https://example.invalid/v1",settings.effective().get("base_url"));
        String id=settings.createProfile(Map.of("name","second","provider","custom",
            "base_url","https://example.invalid/v1","model","second","api_key",""));
        assertEquals("synthetic",settings.effective().get("model"));
        assertEquals(400,assertThrows(ApiFailure.class,() -> settings.activate(id)).status());
        settings.updateProfile(id,Map.of("name","second","provider","custom",
            "base_url","https://example.invalid/v1","model","second","api_key","second-synthetic-secret"));
        settings.activate(id);
        var restarted=new SettingsService(new RuntimePaths(temporary.toString(),temporary.toString()),new JsonFiles(json));
        assertEquals("second",restarted.effective().get("model"));
        String response=json.writeValueAsString(restarted.listProfiles())+
            json.writeValueAsString(restarted.publicSettings(restarted.effective()));
        assertFalse(response.contains("first-synthetic-secret"));
        assertFalse(response.contains("second-synthetic-secret"));
        assertFalse(restarted.publicSettings(restarted.effective()).containsKey("api_key"));
        try (var files=Files.list(temporary)) {
            assertFalse(files.anyMatch(path -> path.toString().endsWith(".tmp")));
        }
    }
}
