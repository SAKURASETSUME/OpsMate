package com.opsmate.agent;

public record ToolScope(Long logId,Long sessionId,String workspace) {
    public static ToolScope readOnly() { return new ToolScope(null,null,""); }
}
