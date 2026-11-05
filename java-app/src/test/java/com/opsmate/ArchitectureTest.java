package com.opsmate;

import org.junit.jupiter.api.Test;
import org.springframework.modulith.core.ApplicationModules;

class ArchitectureTest {
    @Test
    void businessModulesRespectBoundaries() {
        ApplicationModules.of(OpsMateApplication.class).verify();
    }
}
