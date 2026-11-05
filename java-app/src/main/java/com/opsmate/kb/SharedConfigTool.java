package com.opsmate.kb;

import com.opsmate.agent.*;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
class SharedConfigTool implements AgentTool {
    private final WorkbenchService workbench;
    SharedConfigTool(WorkbenchService workbench) { this.workbench=workbench; }
    public String name() { return "read_user_config"; }
    public String description() { return "只读用户显式共享的配置，args={name}，未共享/不存在返回 ok=false，最多4000字"; }
    public Map<String,Object> execute(Map<String,Object> args,ToolScope scope) {
        return workbench.readShared(Objects.toString(args.get("name"),""));
    }
}
