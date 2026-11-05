package com.opsmate.infrastructure;

import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PublicHttpTest {
    @Test void textLimitsRedirectRejectionAndBodyDeadlineUseRealHttp() throws Exception {
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.setExecutor(java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor());
        server.createContext("/text",exchange -> {
            byte[] bytes="中文技能".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type","text/plain"); exchange.sendResponseHeaders(200,bytes.length);
            try (var body=exchange.getResponseBody()) { body.write(bytes); }
        });
        server.createContext("/redirect",exchange -> { exchange.getResponseHeaders().add("Location","/text"); exchange.sendResponseHeaders(302,-1); exchange.close(); });
        server.createContext("/big",exchange -> { exchange.sendResponseHeaders(200,64001); try (var body=exchange.getResponseBody()) { body.write(new byte[64001]); } catch (java.io.IOException ignored) { } });
        server.createContext("/slow",exchange -> {
            exchange.sendResponseHeaders(200,0);
            try (var body=exchange.getResponseBody()) { body.write('a'); body.flush(); Thread.sleep(4000); body.write('b'); }
            catch (Exception ignored) { }
        });
        server.start();
        try {
            // Package-private policy injection is only used here; production always resolves public addresses.
            var client=new PublicHttp(URI::create);
            String base="http://127.0.0.1:"+server.getAddress().getPort();
            assertEquals("中文技能",new String(client.get(base+"/text",64000,false,3).bytes(),StandardCharsets.UTF_8));
            assertThrows(ApiFailure.class,() -> client.get(base+"/redirect",64000,false,3));
            assertEquals("中文技能",new String(client.get(base+"/redirect",64000,true,3).bytes(),StandardCharsets.UTF_8));
            assertThrows(ApiFailure.class,() -> client.get(base+"/big",64000,false,3));
            long started=System.nanoTime();
            assertThrows(ApiFailure.class,() -> client.get(base+"/slow",64000,false,1));
            assertTrue((System.nanoTime()-started)/1_000_000<3000,"body timeout must close upstream");
        } finally { server.stop(0); }
    }
}
