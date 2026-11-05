package com.opsmate.infrastructure;

import java.io.*;
import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.stereotype.Component;

/** Bounded public URL reads. Redirects are validated one hop at a time. */
@Component
public class PublicHttp {
    private final java.util.function.Function<String,URI> validator;
    public PublicHttp() { this(PublicHttp::validate); }
    PublicHttp(java.util.function.Function<String,URI> validator) { this.validator=validator; }
    public static URI validate(String value) {
        try {
            URI uri=URI.create(value);
            if (!("http".equals(uri.getScheme())||"https".equals(uri.getScheme()))||uri.getHost()==null||uri.getUserInfo()!=null) throw new Exception();
            for (InetAddress address:InetAddress.getAllByName(uri.getHost())) {
                byte[] bytes=address.getAddress();
                if (address.isAnyLocalAddress()||address.isLoopbackAddress()||address.isLinkLocalAddress()||address.isSiteLocalAddress()||address.isMulticastAddress()||((bytes[0]&0xfe)==0xfc)||((bytes.length==4)&&(bytes[0]&255)==100&&(bytes[1]&255)>=64&&(bytes[1]&255)<=127))
                    throw new ApiFailure(400,"禁止访问内网/本机地址");
            }
            return uri;
        } catch (ApiFailure denied) { throw denied; }
        catch (Exception invalid) { throw new ApiFailure(400,"URL无效或无法解析，仅支持公网http/https"); }
    }
    public record Result(byte[] bytes,String type,String url) { }
    public Result get(String value,int limit,boolean redirects,int seconds) {
        AtomicReference<InputStream> input=new AtomicReference<>();
        HttpClient client=HttpClient.newBuilder().followRedirects(HttpClient.Redirect.NEVER).connectTimeout(Duration.ofSeconds(10)).build();
        ExecutorService executor=Executors.newVirtualThreadPerTaskExecutor();
        Future<Result> task=executor.submit(() -> {
            URI uri=validator.apply(value);
            for (int hop=0;hop<6;hop++) {
                var request=HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(seconds)).header("User-Agent","OpsMate/1.0").GET().build();
                var response=client.send(request,HttpResponse.BodyHandlers.ofInputStream());
                input.set(response.body());
                try (InputStream body=response.body()) {
                    if (response.statusCode()>=300&&response.statusCode()<400) {
                        if (!redirects) throw new ApiFailure(400,"不接受重定向链接");
                        uri=validator.apply(uri.resolve(response.headers().firstValue("Location").orElseThrow()).toString()); continue;
                    }
                    if (response.statusCode()>=400) throw new ApiFailure(400,"HTTP "+response.statusCode());
                    if (response.headers().firstValueAsLong("Content-Length").orElse(0)>limit) throw new ApiFailure(400,"下载内容超过上限");
                    byte[] bytes=body.readNBytes(limit+1);
                    if (bytes.length>limit) throw new ApiFailure(400,"下载内容超过上限");
                    return new Result(bytes,response.headers().firstValue("Content-Type").orElse(""),uri.toString());
                }
            }
            throw new ApiFailure(400,"重定向次数超过上限");
        });
        try { return task.get(seconds,TimeUnit.SECONDS); }
        catch (ExecutionException failed) {
            if (failed.getCause() instanceof ApiFailure expected) throw expected;
            throw new ApiFailure(400,"下载失败，请检查网络与URL");
        } catch (InterruptedException cancelled) { Thread.currentThread().interrupt(); throw new CancellationException(); }
        catch (TimeoutException timeout) { throw new ApiFailure(400,"下载请求超时"); }
        finally {
            try { if (input.get()!=null) input.get().close(); } catch (IOException ignored) { }
            task.cancel(true); client.shutdownNow(); executor.shutdownNow();
        }
    }
}
