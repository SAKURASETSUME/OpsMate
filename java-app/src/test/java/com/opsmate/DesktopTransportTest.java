package com.opsmate;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = "spring.profiles.active=desktop-verification")
class DesktopTransportTest {
    @LocalServerPort int port;
    private final HttpClient client = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(3)).build();

    private HttpRequest.Builder request(String path) {
        return HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
            .timeout(Duration.ofSeconds(5));
    }

    @Test
    void multipartRetainsChineseBytes() throws Exception {
        String boundary = "OpsMateJ1Boundary";
        String body = "--" + boundary + "\r\n"
            + "Content-Disposition: form-data; name=\"file\"; filename=\"synthetic.txt\"\r\n"
            + "Content-Type: text/plain; charset=UTF-8\r\n\r\n中文上传\r\n--"
            + boundary + "--\r\n";
        var response = client.send(request("/__verify/upload")
            .header("Content-Type", "multipart/form-data; boundary=" + boundary)
            .POST(HttpRequest.BodyPublishers.ofString(body)).build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("中文上传"));
        assertTrue(response.body().contains("\"bytes\":12"));
    }

    @Test
    void postSseDeliversEventsBeforeCompletion() throws Exception {
        long started = System.nanoTime();
        var response = client.send(request("/__verify/stream")
            .POST(HttpRequest.BodyPublishers.noBody()).build(),
            HttpResponse.BodyHandlers.ofInputStream());
        assertEquals(200, response.statusCode());
        assertTrue(response.headers().firstValue("content-type").orElse("").contains("text/event-stream"));
        int events = 0;
        long first = 0;
        long last = 0;
        try (var reader = new BufferedReader(new InputStreamReader(response.body(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.startsWith("data:")) {
                    if (events == 0) first = System.nanoTime();
                    last = System.nanoTime();
                    events++;
                }
            }
        }
        assertEquals(3, events);
        assertTrue(first >= started);
        assertTrue(last - first >= 100_000_000L, "SSE was buffered until completion");
        assertEquals(200, client.send(request("/api/health").GET().build(),
            HttpResponse.BodyHandlers.discarding()).statusCode());
    }
}
