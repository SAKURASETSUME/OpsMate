package com.opsmate;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
class HttpEntryTest {
    @Autowired MockMvc http;

    @Test
    void healthKeepsPythonContract() throws Exception {
        http.perform(get("/api/health")).andExpect(status().isOk())
            .andExpect(jsonPath("$.ok").value(true))
            .andExpect(jsonPath("$.version").value("1.0.0"));
    }

    @Test
    void existingFrontendIsIncluded() throws Exception {
        http.perform(get("/index.html")).andExpect(status().isOk());
        http.perform(get("/app.js")).andExpect(status().isOk());
    }
}
