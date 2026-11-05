package com.opsmate.assistant;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsmate.agent.*;
import com.opsmate.infrastructure.*;
import com.opsmate.kb.WorkbenchService;
import com.opsmate.llm.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/assistant")
class AssistantChatController {
    private final AssistantStore store;
    private final AssistantAgent agent;
    private final SkillsService skills;
    private final SettingsService settings;
    private final SseTasks tasks;
    private final ObjectMapper json;
    private final AgentJson prompts;
    private final WorkbenchService configs;
    AssistantChatController(AssistantStore store,AssistantAgent agent,SkillsService skills,SettingsService settings,SseTasks tasks,ObjectMapper json,AgentJson prompts,WorkbenchService configs) {
        this.store=store; this.agent=agent; this.skills=skills; this.settings=settings; this.tasks=tasks; this.json=json; this.prompts=prompts; this.configs=configs;
    }
    static class Chat {
        @NotNull @Size(min=1,max=8000) public String message;
        public Long session_id;
        @NotNull public List<Long> attachments=new ArrayList<>();
        @NotNull @Pattern(regexp="(low|medium|high|max)?") public String effort="";
        @NotNull @Size(max=400) public String workspace="";
        public boolean tools=true;
        @NotNull @Size(max=5) public List<String> config_refs=new ArrayList<>();
    }
    @PostMapping(value="/chat",produces="text/event-stream")
    SseEmitter chat(@Valid @RequestBody Chat body) {
        var config=settings.effective();
        String key=Objects.toString(config.get("api_key"),"");
        return tasks.start(300,key,events -> {
            if (key.isBlank()) { events.send(Map.of("error","未配置模型密钥，请先前往设置页保存并启用")); return; }
            List<Map<String,Object>> history;
            try { history=body.session_id==null?new ArrayList<>():store.history(body.session_id); }
            catch (ApiFailure missing) { events.send(Map.of("error","会话不存在或已删除，请点击新建对话")); return; }
            List<Long> attachments=body.attachments.stream().limit(5).distinct().toList();
            StringBuilder message=new StringBuilder(body.message);
            List<String> images=new ArrayList<>();
            int index=0;
            for (long id:attachments) {
                Map<String,Object> item;
                try { item=store.attachment(id); }
                catch (ApiFailure missing) { events.send(Map.of("error","附件不存在或已使用，请重新添加")); return; }
                if (item.get("message_id")!=null) { events.send(Map.of("error","附件不存在或已使用，请重新添加")); return; }
                index++;
                message.append("\n\n[附件 ").append(index).append("：").append(item.get("name")).append("（").append(item.get("mime")).append("，");
                if (item.get("kind").equals("image")) {
                    images.add("data:"+item.get("mime")+";base64,"+Base64.getEncoder().encodeToString(Files.readAllBytes(store.attachmentPath(item))));
                    message.append("图片，已随消息提供给你）]");
                } else message.append(item.get("size_bytes")).append(" 字节）]\n").append(AssistantStore.clip(Files.readString(store.attachmentPath(item),StandardCharsets.UTF_8),15000));
            }
            for (String name:body.config_refs) {
                var item=configs.referenced(AssistantStore.clip(name,120));
                if (item.isEmpty()) message.append("\n\n[引用配置：").append(name).append("（不存在或已删除）]");
                else message.append("\n\n[引用配置：").append(item.get("name")).append("（").append(item.get("format")).append("，用户在消息中 @ 引用，可直接基于它分析）]\n").append(AssistantStore.clip(item.get("content").toString(),15000));
            }
            try (var client=new LlmClient(config,json)) {
                events.register(client);
                if (history.size()>=14&&body.session_id!=null) {
                    int count=history.size()-6;
                    var old=store.summary(body.session_id);
                    String summary=Objects.toString(old.get("summary"),"");
                    int compressed=old.isEmpty()?0:((Number)old.get("compressed_until")).intValue();
                    if (count>compressed) {
                        try {
                            events.send(Map.of("thinking","正在压缩较早的对话历史…"));
                            StringBuilder material=new StringBuilder(summary);
                            for (var row:history.subList(Math.min(compressed,count),count)) material.append('\n').append(row.get("role")).append(": ").append(AssistantStore.clip(row.get("content").toString(),2000));
                            summary=AssistantStore.clip(client.chat(List.of(Map.of("role","system","content","你是对话压缩器。将历史压成不超过500字摘要，只保留问题、结论、主机/路径/版本和未决事项，直接输出正文。"),Map.of("role","user","content",material.toString())),0.2,60,4096,"low"),4000);
                            store.saveSummary(body.session_id,count,summary);
                        } catch (IllegalStateException compressionFailed) { summary=""; }
                    }
                    if (!summary.isBlank()) {
                        history=new ArrayList<>(history.subList(count,history.size()));
                        history.addFirst(Map.of("role","user","content","[历史对话摘要（原文可在会话记录中回看）]\n"+summary));
                    }
                }
                history.add(Map.of("role","user","content",message.toString()));
                String system=prompts.prompt(body.tools?"assistant":"assistant-direct")+(body.tools?skills.methodology(body.message):"");
                var answer=agent.run(client,system,history,images,body.effort,body.tools,new ToolScope(null,body.session_id,body.workspace),events);
                if (events.cancelled()) return;
                long id=store.saveTurn(body.session_id,body.message,answer.steps(),answer.text(),attachments,body.workspace);
                events.send(Map.of("done",true,"session_id",id));
            }
        });
    }
}
