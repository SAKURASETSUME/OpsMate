package com.opsmate;

import javafx.scene.input.Clipboard;
import javafx.scene.input.ClipboardContent;

/** Exposes text copying only. No file, process or network access is exposed to JavaScript. */
public final class ClipboardBridge {
    public void writeText(String text) {
        ClipboardContent content = new ClipboardContent();
        content.putString(text);
        if (!Clipboard.getSystemClipboard().setContent(content)) {
            throw new IllegalStateException("Clipboard write failed");
        }
    }
}
