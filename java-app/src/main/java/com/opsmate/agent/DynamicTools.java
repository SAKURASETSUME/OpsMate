package com.opsmate.agent;

import java.util.Map;

/** Extension point for locally configured tool transports without module cycles. */
public interface DynamicTools {
    Map<String,String> descriptions();
    boolean accepts(String name);
    Map<String,Object> execute(String name,Map<String,Object> args);
}
