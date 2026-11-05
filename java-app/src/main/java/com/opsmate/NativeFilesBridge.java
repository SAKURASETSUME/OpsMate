package com.opsmate;

import java.io.File;
import java.nio.file.Files;
import java.util.Base64;
import javafx.stage.DirectoryChooser;
import javafx.stage.FileChooser;
import javafx.stage.Window;

/** All file destinations are selected by the user through native dialogs. */
public final class NativeFilesBridge {
    private final Window owner;

    public NativeFilesBridge(Window owner) {
        this.owner = owner;
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
