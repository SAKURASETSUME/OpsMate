package com.opsmate;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import javafx.application.Application;
import javafx.application.Platform;
import javafx.concurrent.Worker;
import javafx.scene.Scene;
import javafx.scene.web.WebView;
import javafx.stage.Stage;
import netscape.javascript.JSObject;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.web.servlet.context.ServletWebServerApplicationContext;

/** Desktop owns the embedded server lifecycle, with no separate backend process. */
public class DesktopShell extends Application {
    private ServletWebServerApplicationContext context;
    private static volatile ServletWebServerApplicationContext activeContext;
    private boolean browserMode;
    private final ClipboardBridge clipboard = new ClipboardBridge();
    private NativeFilesBridge files;

    @Override
    public void init() {
        SpringApplication app = new SpringApplication(OpsMateApplication.class);
        if (Boolean.getBoolean("opsmate.verifypage")) {
            app.setAdditionalProfiles("desktop-verification");
        }
        context = (ServletWebServerApplicationContext) app.run(getParameters().getRaw().toArray(String[]::new));
        activeContext=context;
    }

    @Override
    public void start(Stage stage) {
        try { startEmbedded(stage); }
        catch (RuntimeException|LinkageError unavailable) {
            browserMode=true;
            BrowserFallback.open(getParameters().getRaw().toArray(String[]::new),context);
            Platform.exit();
        }
    }

    static ServletWebServerApplicationContext activeContext() { return activeContext; }

    private void startEmbedded(Stage stage) {
        WebView view = new WebView();
        files = new NativeFilesBridge(stage);
        stage.setTitle("OpsMate Java");
        stage.setScene(new Scene(view, 1280, 860));
        stage.setOnCloseRequest(event -> Platform.exit());
        view.getEngine().getLoadWorker().stateProperty().addListener((observable, previous, state) -> {
            if (state != Worker.State.SUCCEEDED) {
                return;
            }
            java.net.URI location = java.net.URI.create(view.getEngine().getLocation());
            if (!"127.0.0.1".equals(location.getHost())
                    || location.getPort() != context.getWebServer().getPort()) {
                return;
            }
            JSObject browser = (JSObject) view.getEngine().executeScript("window");
            browser.setMember("opsmateClipboard", clipboard);
            browser.setMember("opsmateFiles", files);
            try (var script = DesktopShell.class.getResourceAsStream("/desktop-bridge.js")) {
                view.getEngine().executeScript(new String(script.readAllBytes(), StandardCharsets.UTF_8));
            } catch (java.io.IOException failure) {
                throw new IllegalStateException("Cannot initialize desktop integration", failure);
            }
            if (Boolean.getBoolean("opsmate.smoke")) {
                String capabilities = String.valueOf(view.getEngine().executeScript(
                    "JSON.stringify({fetch:typeof fetch,stream:typeof ReadableStream,"
                    + "worker:typeof Worker,clipboard:typeof navigator.clipboard,"
                    + "blob:typeof Blob,app:!!document.getElementById('app')})"));
                try {
                    Files.writeString(Path.of(System.getProperty("opsmate.smoke.report")),
                        capabilities, StandardCharsets.UTF_8);
                } catch (Exception failure) {
                    throw new IllegalStateException("Cannot save desktop smoke evidence", failure);
                } finally {
                    Platform.exit();
                }
            }
        });
        String page = Boolean.getBoolean("opsmate.verifypage") ? "/__verify" : "/index.html";
        view.getEngine().load("http://127.0.0.1:" + context.getWebServer().getPort() + page);
        stage.show();
    }

    @Override
    public void stop() {
        if (context != null&&!browserMode) {
            context.close();
        }
    }
}
