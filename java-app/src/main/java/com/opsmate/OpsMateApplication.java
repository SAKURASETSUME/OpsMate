package com.opsmate;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import javafx.application.Application;
import java.util.Arrays;

@SpringBootApplication
public class OpsMateApplication {
    public static void main(String[] args) {
        if (Arrays.asList(args).contains("--headless")) {
            SpringApplication.run(OpsMateApplication.class, args);
        } else if (Arrays.asList(args).contains("--browser")) {
            BrowserFallback.open(args,null);
        } else {
            try { Application.launch(DesktopShell.class, args); }
            catch (RuntimeException|LinkageError unavailable) { BrowserFallback.open(args,DesktopShell.activeContext()); }
        }
    }
}
