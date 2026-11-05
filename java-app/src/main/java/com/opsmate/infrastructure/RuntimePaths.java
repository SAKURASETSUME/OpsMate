package com.opsmate.infrastructure;

import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Central definition of writable storage and read-only knowledge locations. */
@Component
public class RuntimePaths {
    private final Path data;
    private final Path knowledge;

    public RuntimePaths(@Value("${opsmate.data:target/local-data}") String data,
                        @Value("${opsmate.knowledge:../data}") String knowledge) throws java.io.IOException {
        this.data = Path.of(data).toAbsolutePath().normalize();
        this.knowledge = Path.of(knowledge).toAbsolutePath().normalize();
        Files.createDirectories(this.data);
    }

    public Path data() { return data; }
    public Path knowledge() { return knowledge; }
}
