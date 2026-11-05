package com.opsmate.infrastructure;

import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/** Bounded background work with heartbeats and cancellation propagated to network streams. */
@Component
public class SseTasks {
    private final ExecutorService jobs=Executors.newVirtualThreadPerTaskExecutor();
    private final ScheduledExecutorService timers=Executors.newSingleThreadScheduledExecutor(r -> {
        Thread thread=new Thread(r,"opsmate-stream-deadlines");
        thread.setDaemon(true);
        return thread;
    });
    @FunctionalInterface public interface Work { void run(Events events) throws Exception; }

    public static final class Events {
        private final SseEmitter emitter;
        private final String secret;
        private final AtomicBoolean cancelled=new AtomicBoolean();
        private final List<AutoCloseable> resources=new CopyOnWriteArrayList<>();
        private volatile Future<?> future;
        Events(SseEmitter emitter,String secret) { this.emitter=emitter; this.secret=secret; }
        public boolean cancelled() { return cancelled.get()||Thread.currentThread().isInterrupted(); }
        public void register(AutoCloseable resource) {
            resources.add(resource);
            if (cancelled.get()) close(resource);
        }
        private void close(AutoCloseable resource) {
            try { resource.close(); } catch (Exception ignored) { }
        }
        public void send(Map<String,?> payload) {
            if (cancelled()) throw new CancellationException();
            try { emitter.send(SseEmitter.event().data(payload,MediaType.APPLICATION_JSON)); }
            catch (IOException|IllegalStateException disconnected) { cancel(); throw new CancellationException(); }
        }
        void cancel() {
            if (cancelled.compareAndSet(false,true)) {
                for (AutoCloseable resource:resources) close(resource);
                if (future!=null) future.cancel(true);
            }
        }
        String safe(String text) {
            return secret.isEmpty() ? text : text.replace(secret,"[密钥已隐藏]");
        }
    }

    public SseEmitter start(int seconds,String secret,Work work) {
        SseEmitter emitter=new SseEmitter((seconds+10L)*1000);
        Events events=new Events(emitter,secret);
        var deadline=timers.schedule(() -> {
            try { events.send(Map.of("error","请求超时，本轮未保存完整结果")); }
            catch (CancellationException ignored) { }
            finally { events.cancel(); emitter.complete(); }
        },seconds,TimeUnit.SECONDS);
        var heartbeat=timers.scheduleAtFixedRate(() -> {
            if (events.cancelled.get()) return;
            try { emitter.send(SseEmitter.event().comment("keepalive")); }
            catch (IOException|IllegalStateException disconnected) { events.cancel(); }
        },5,5,TimeUnit.SECONDS);
        Runnable cleanup=() -> { deadline.cancel(false); heartbeat.cancel(false); events.cancel(); };
        emitter.onCompletion(cleanup);
        emitter.onTimeout(cleanup);
        emitter.onError(error -> cleanup.run());
        events.future=jobs.submit(() -> {
            try { work.run(events); }
            catch (CancellationException ignored) { }
            catch (IllegalStateException|ApiFailure expected) {
                if (!events.cancelled()) {
                    String message=expected.getMessage()==null ? "请求失败，请重试" : expected.getMessage();
                    try { events.send(Map.of("error",events.safe(message))); } catch (CancellationException ignored) { }
                }
            } catch (Exception failure) {
                if (!events.cancelled()) {
                    try { events.send(Map.of("error","请求处理失败，请重试")); } catch (CancellationException ignored) { }
                }
            } finally {
                deadline.cancel(false);
                heartbeat.cancel(false);
                for (AutoCloseable resource:events.resources) events.close(resource);
                emitter.complete();
            }
        });
        return emitter;
    }

    @PreDestroy public void close() {
        timers.shutdownNow();
        jobs.shutdownNow();
    }
}
