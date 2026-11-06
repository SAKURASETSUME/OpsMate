package com.opsmate;

import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsmate.assistant.AssistantStore;
import com.opsmate.infrastructure.ApiFailure;
import javafx.scene.input.DragEvent;
import javafx.scene.input.TransferMode;
import javafx.scene.web.WebView;
import netscape.javascript.JSObject;

/** Pass Explorer file drops to the assistant before WebView handles the dragboard. */
final class NativeAssistantDrop {
    private static final int MAX_BYTES = 5 * 1024 * 1024;
    private static final int MAX_FILES = 5;

    private NativeAssistantDrop() {}

    static void install(WebView view, int port, AssistantStore store, ObjectMapper json) {
        view.addEventFilter(DragEvent.DRAG_OVER, event -> {
            if (assistantTarget(view, event, port) != null) {
                event.acceptTransferModes(TransferMode.COPY);
                event.consume();
            }
        });
        view.addEventFilter(DragEvent.DRAG_DROPPED, event -> {
            JSObject bridge = assistantTarget(view, event, port);
            if (bridge == null) {
                return;
            }
            bridge.call("receive", upload(event.getDragboard().getFiles(), store, json));
            event.setDropCompleted(true);
            event.consume();
        });
    }

    static String upload(List<File> files, AssistantStore store, ObjectMapper json) {
        var entries = new ArrayList<Map<String, Object>>();
        int count = Math.min(MAX_FILES, files.size());
        for (int index = 0; index < count; index++) {
            File file = files.get(index);
            try {
                byte[] bytes = readBounded(file.toPath());
                String mime = java.util.Objects.requireNonNullElse(Files.probeContentType(file.toPath()), "application/octet-stream");
                entries.add(store.upload(file.getName(), mime, bytes));
            } catch (ApiFailure failure) {
                entries.add(Map.of("name", file.getName(), "error", failure.getMessage()));
            } catch (IOException failure) {
                entries.add(Map.of("name", file.getName(), "error", "无法读取文件"));
            }
        }
        try {
            return json.writeValueAsString(Map.of("entries", entries, "truncated", files.size() > MAX_FILES));
        } catch (com.fasterxml.jackson.core.JsonProcessingException failure) {
            throw new IllegalStateException("无法返回附件上传结果", failure);
        }
    }

    private static JSObject assistantTarget(WebView view, DragEvent event, int port) {
        if (!event.getDragboard().hasFiles()) {
            return null;
        }
        URI location = URI.create(view.getEngine().getLocation());
        if (!"http".equals(location.getScheme()) || !"127.0.0.1".equals(location.getHost())
                || location.getPort() != port || !"/index.html".equals(location.getPath())) {
            return null;
        }
        Object value = view.getEngine().executeScript("window.opsmateAssistantDrop");
        if (value instanceof JSObject bridge
                && Boolean.TRUE.equals(bridge.call("accepts", event.getX(), event.getY()))) {
            return bridge;
        }
        return null;
    }

    private static byte[] readBounded(Path path) throws IOException {
        if (!Files.isRegularFile(path)) {
            throw new IOException("Expected a regular file");
        }
        try (var input = Files.newInputStream(path)) {
            return input.readNBytes(MAX_BYTES + 1);
        }
    }
}
