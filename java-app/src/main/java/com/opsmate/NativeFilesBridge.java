package com.opsmate;

import java.io.File;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.util.Base64;
import javax.imageio.ImageIO;
import javafx.stage.DirectoryChooser;
import javafx.stage.FileChooser;
import javafx.stage.Window;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsmate.assistant.AssistantStore;

/** All file destinations are selected by the user through native dialogs. */
public final class NativeFilesBridge {
    private final Window owner;
    private final AssistantStore store;
    private final ObjectMapper json;

    public NativeFilesBridge(Window owner, AssistantStore store, ObjectMapper json) {
        this.owner = owner;
        this.store = store;
        this.json = json;
    }

    public String pickAssistantFiles() {
        FileChooser chooser = new FileChooser();
        chooser.setTitle("添加运维助手附件");
        var images = new FileChooser.ExtensionFilter("常见图片", "*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.bmp");
        chooser.getExtensionFilters().addAll(images, new FileChooser.ExtensionFilter("所有文件（含文本）", "*.*"));
        chooser.setSelectedExtensionFilter(images);
        var selected = chooser.showOpenMultipleDialog(owner);
        return selected == null ? "" : NativeAssistantDrop.upload(selected, store, json);
    }

    public String assistantThumbnail(String id) {
        var item = store.attachment(Long.parseLong(id));
        if (!"image".equals(item.get("kind"))) return "";
        try (var input = ImageIO.createImageInputStream(store.attachmentPath(item).toFile());
             var output = new ByteArrayOutputStream()) {
            if (input == null) return "";
            var readers = ImageIO.getImageReaders(input);
            if (!readers.hasNext()) return "";
            var reader = readers.next();
            try {
                reader.setInput(input, true, true);
                int stride = Math.max(1, Math.max(reader.getWidth(0), reader.getHeight(0)) / 128);
                var options = reader.getDefaultReadParam();
                options.setSourceSubsampling(stride, stride, 0, 0);
                if (!ImageIO.write(reader.read(0, options), "png", output)) return "";
                return "data:image/png;base64," + Base64.getEncoder().encodeToString(output.toByteArray());
            } finally {
                reader.dispose();
            }
        } catch (java.io.IOException failure) {
            return "";
        }
    }

    public String pickFolder() {
        DirectoryChooser chooser = new DirectoryChooser();
        chooser.setTitle("选择工作目录");
        File chosen = chooser.showDialog(owner);
        return chosen == null ? "" : chosen.getAbsolutePath();
    }

    public void download(String filename, String encoded) {
        if (encoded.length() > 75_000_000) {
            throw new IllegalArgumentException("下载内容超过桌面保存上限");
        }
        byte[] bytes = Base64.getDecoder().decode(encoded);
        FileChooser chooser = new FileChooser();
        chooser.setTitle("保存文件");
        chooser.setInitialFileName(filename.replaceAll("[\\\\/:*?\"<>|]", "_"));
        File chosen = chooser.showSaveDialog(owner);
        if (chosen != null) {
            try {
                Files.write(chosen.toPath(), bytes);
            } catch (java.io.IOException failure) {
                throw new IllegalStateException("无法保存文件", failure);
            }
        }
    }
}
