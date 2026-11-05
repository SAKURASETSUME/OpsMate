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
        } else {
            Application.launch(DesktopShell.class, args);
        }
    }
}
