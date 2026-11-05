package com.opsmate;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Runs only after the new executable jar exists; it never consumes the previous build. */
class MigrationAcceptanceIT {
    private void verify(String suite) throws Exception {
        Path root=Path.of("..").toAbsolutePath().normalize();
        Path log=root.resolve("java-app/target/acceptance-"+suite+".log");
        var builder=new ProcessBuilder(root.resolve(".venv/Scripts/python.exe").toString(),root.resolve("tools/verify_java_"+suite+".py").toString()).directory(root.toFile()).redirectErrorStream(true).redirectOutput(log.toFile());
        builder.environment().put("PATH",Path.of(System.getProperty("java.home"),"bin")+";"+builder.environment().getOrDefault("PATH",""));
        builder.environment().put("PYTHONIOENCODING","utf-8");
        Process process=builder.start();
        try {
            assertTrue(process.waitFor(180,TimeUnit.SECONDS),"acceptance timeout: "+suite);
            assertEquals(0,process.exitValue(),() -> {
                try { return Files.readString(log,StandardCharsets.UTF_8); }
                catch (Exception missing) { return "acceptance log unavailable: "+suite; }
            });
        } finally { process.descendants().forEach(child -> child.destroyForcibly()); process.destroyForcibly(); }
    }
    @Test void offlineContracts() throws Exception { verify("offline"); }
    @Test void logsAndLegacyDatabase() throws Exception { verify("logs"); }
    @Test void generationAndDiagnosis() throws Exception { verify("generation"); }
    @Test void modelProfiles() throws Exception { verify("settings"); }
    @Test void assistantAndMcp() throws Exception { verify("assistant"); }
    @Test void cutoverAndRollback() throws Exception { verify("cutover"); }
}
