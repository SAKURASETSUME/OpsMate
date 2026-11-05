package com.opsmate.codegen;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsmate.agent.*;
import com.opsmate.infrastructure.SseTasks;
import com.opsmate.llm.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import java.util.regex.Pattern;
import org.springframework.web.bind.annotation.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/codegen")
class CodegenController {
    record Generate(@NotNull @Size(min=1,max=60000) String requirement,
                    @Size(max=100) String distro,@Size(max=60000) String notes) {}
    private final SettingsService settings;
    private final ObjectMapper json;
    private final AgentJson protocol;
    private final CodegenAgent agent;
    private final ScriptValidator quality;
    private final CodegenHistory history;
    private final SseTasks tasks;
    private final int budget;
    CodegenController(SettingsService settings,ObjectMapper json,AgentJson protocol,CodegenAgent agent,
            ScriptValidator quality,CodegenHistory history,SseTasks tasks,
            @Value("${opsmate.generation-budget-seconds:300}") int budget) {
        this.settings=settings; this.json=json; this.protocol=protocol; this.agent=agent;
        this.quality=quality; this.history=history; this.tasks=tasks;
        this.budget=budget;
    }

    @PostMapping(value="/generate",produces="text/event-stream")
    SseEmitter generate(@Valid @RequestBody Generate body) {
        var snapshot=settings.effective();
        String key=Objects.toString(snapshot.get("api_key"),"");
        return tasks.start(budget,key,events -> {
            if (body.requirement().isBlank()) { events.send(Map.of("error","请填写脚本需求")); return; }
            if (key.isEmpty()) { events.send(Map.of("error","未配置模型密钥，请先前往设置页保存并启用")); return; }
            String distro=body.distro()==null ? "" : body.distro();
            String notes=body.notes()==null ? "" : body.notes();
            String user="需求："+body.requirement()+"\n发行版："+(distro.isEmpty() ? "未指定" : distro)+"\n补充："+(notes.isEmpty() ? "无" : notes);
            if (Pattern.compile("(?:[两三2-3]|几)\\s*[个份].{0,8}脚本|脚本.{0,24}(?:和|以及|加|、).{0,24}脚本|多个脚本|分别(?:写|生成)").matcher(body.requirement()).find())
                user+="\n本需求包含多个脚本，必须全部输出 scripts 数组，每项含唯一 name，一次最多3个。";
            LlmClient model=new LlmClient(snapshot,json);
            events.register(model);
            String lastError="";
            for (int attempt=0;attempt<2;attempt++) {
                CodegenAgent.Result generated=agent.run(model,protocol.prompt("codegen"),
                    user+(attempt==0 ? "" : "\n上次未通过："+lastError+"。修复后按原需求输出完整业务 JSON。"),events);
                Map<String,Object> result;
                try {
                    result=quality.validate(generated.payload());
                    if (!Boolean.TRUE.equals(result.get("need_clarification")) &&
                            Pattern.compile("凌晨|每天").matcher(body.requirement()).find()) {
                        var items=result.get("scripts") instanceof List<?> values ? values : List.of(result);
                        StringBuilder guidance=new StringBuilder();
                        for (Object value:items) {
                            var item=(Map<?,?>)value;
                            guidance.append(item.get("usage")).append(item.get("warnings"));
                        }
                        if (!guidance.toString().toLowerCase(Locale.ROOT).contains("cron"))
                            throw new IllegalStateException("定时需求必须给出 cron 安装指引及风险");
                    }
                } catch (IllegalStateException invalid) {
                    lastError=invalid.getMessage();
                    if (attempt==1) throw invalid;
                    events.send(Map.of("phase","retry"));
                    continue;
                }
                var complete=new LinkedHashMap<>(result);
                if (!Boolean.TRUE.equals(result.get("need_clarification"))) complete.put("steps",generated.steps());
                if (events.cancelled()) return;
                if (!Boolean.TRUE.equals(result.get("need_clarification")))
                    history.save(body.requirement(),distro,notes,complete,Objects.toString(snapshot.get("model"),""));
                events.send(Map.of("result",complete));
                events.send(Map.of("done",true));
                return;
            }
        });
    }
    @GetMapping("/history") Map<String,Object> history(@RequestParam(defaultValue="50") int limit) {
        return Map.of("items",history.list(limit));
    }
    @GetMapping("/history/{id}") Map<String,Object> detail(@PathVariable long id) { return history.detail(id); }
}
