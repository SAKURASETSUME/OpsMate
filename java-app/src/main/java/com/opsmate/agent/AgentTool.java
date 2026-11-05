package com.opsmate.agent;

import java.util.Map;

/** Implemented by business modules; the engine depends only on this contract. */
public interface AgentTool {
    String name();
    String description();
    Map<String,Object> execute(Map<String,Object> args,ToolScope scope) throws Exception;
}
