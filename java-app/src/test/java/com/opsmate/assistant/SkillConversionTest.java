package com.opsmate.assistant;

import com.opsmate.infrastructure.*;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class SkillConversionTest {
    @Test void skillMarkdownAndMissingTriggersConvertToLocalSchema() {
        var converted=SetupTools.normalize("---\nname: disk-check\ndescription: disk check\n---\n先检查磁盘，再分析。","",null);
        assertEquals("disk-check",converted.getKey());
        assertTrue(converted.getValue().contains("先检查磁盘，再分析。"));
        assertTrue(converted.getValue().contains("triggers:"));
        var yaml=SetupTools.normalize("name: custom\nmethodology: check disks\n","explicit",List.of("磁盘"));
        assertEquals("explicit",yaml.getKey());
        assertTrue(yaml.getValue().contains("磁盘"));
        assertThrows(ApiFailure.class,() -> SetupTools.normalize("not a skill","",null));
    }
    @Test void publicFetchRejectsIpv4Ipv6AndCredentialUrls() {
        for (String url:List.of("http://127.0.0.1/a","http://[::1]/a","http://10.0.0.1/a","http://169.254.169.254/a","http://100.64.0.1/a","file:///c:/x","http://user:pass@127.0.0.1/a"))
            assertThrows(ApiFailure.class,() -> PublicHttp.validate(url),url);
    }
}
