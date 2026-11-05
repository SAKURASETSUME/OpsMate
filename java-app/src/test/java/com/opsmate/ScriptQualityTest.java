package com.opsmate;

import com.opsmate.codegen.ScriptValidator;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ScriptQualityTest {
    private final ScriptValidator quality=new ScriptValidator();

    @Test
    void legitimateBashCasesFromUserIncidentStayAccepted() {
        for (String script:List.of("PRIO=$1","DIR=/opt/$X",
                "mkdir -p \"$(dirname \"${X}\")\"",
                "cat <<EOF\nrole=${ROLE}\nEOF","echo 'literal $VALUE'",
                "cat <<'EOF'\nrole=$ROLE\nEOF")) {
            assertEquals("",quality.unsafeExpansion(script),script);
        }
        assertFalse(quality.unsafeExpansion("rm $X").isEmpty());
        assertDoesNotThrow(() -> quality.requireEcho("echo \"即将 systemctl restart nginx\"\nsystemctl restart nginx"));
        assertThrows(IllegalStateException.class,() -> quality.requireEcho("systemctl stop nginx"));
    }

    @Test
    void namesAndArrayBoundsPreserveOutputContract() {
        Map<String,Object> item=valid();
        assertDoesNotThrow(() -> quality.validate(item));
        var named=new LinkedHashMap<>(item);
        named.put("name","synthetic");
        assertThrows(IllegalStateException.class,() -> quality.validate(Map.of("scripts",List.of(named,named))));
        assertThrows(IllegalStateException.class,() -> quality.validate(Map.of("scripts",List.of(named,named,named,named))));
        var bad=new LinkedHashMap<>(item);
        bad.put("script",item.get("script")+"\nrm $PATH");
        assertThrows(IllegalStateException.class,() -> quality.validate(bad));
    }

    static Map<String,Object> valid() {
        return Map.of("need_clarification",false,"script","#!/usr/bin/env bash\n# 用途 用法 参数 依赖 适用 AI生成请审阅\nset -euo pipefail\necho \"synthetic\"",
            "explanation",List.of(Map.of("lines","1","title","a","detail","a"),Map.of("lines","2","title","b","detail","b"),
                Map.of("lines","3","title","c","detail","c")),"warnings",List.of(),"usage","synthetic");
    }
}
