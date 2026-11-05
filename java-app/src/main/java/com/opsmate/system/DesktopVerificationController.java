package com.opsmate.system;

import java.util.Map;
import org.springframework.context.annotation.Profile;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/** Available only when explicitly enabling the desktop-verification profile. */
@Profile("desktop-verification")
@RestController
class DesktopVerificationController {
    @PostMapping("/__verify/upload")
    Map<String, Object> upload(@RequestParam("file") MultipartFile file) throws Exception {
        return Map.of("bytes", file.getSize(), "content",
            new String(file.getBytes(), java.nio.charset.StandardCharsets.UTF_8));
    }

    @PostMapping("/__verify/stream")
    SseEmitter stream() {
        SseEmitter emitter = new SseEmitter(10_000L);
        Thread.startVirtualThread(() -> {
            try {
                for (String chunk : new String[]{"中文", "分块", "完成"}) {
                    emitter.send(SseEmitter.event().data(chunk));
                    Thread.sleep(100);
                }
                emitter.complete();
            } catch (Exception failure) {
                emitter.completeWithError(failure);
            }
        });
        return emitter;
    }

    @GetMapping(value = "/__verify", produces = MediaType.TEXT_HTML_VALUE)
    String page() {
        return """
            <!doctype html><html lang="zh"><meta charset="utf-8">
            <title>OpsMate J1 桌面验收</title>
            <body style="font:20px sans-serif;background:#17171b;color:#dcdce1;padding:32px">
            <h1>OpsMate J1 桌面验收</h1>
            <button onclick="navigator.clipboard.writeText('J1剪贴板样例').then(()=>document.getElementById('status').textContent='复制完成')">复制测试</button>
            <input aria-label="粘贴验证" placeholder="粘贴验证">
            <button onclick="pywebview.api.pick_folder().then(p=>document.getElementById('result').textContent=p)">选择目录</button>
            <button onclick="var a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['J1中文文件\\n'],{type:'text/plain'}));a.download='J1下载.txt';a.click();URL.revokeObjectURL(a.href)">下载样例</button>
            <button onclick="probe()">流式、Worker、上传测试</button>
            <p id="status"></p><pre id="result"></pre>
            <script>
            async function probe(){
              try{
                const url=URL.createObjectURL(new Blob(['onmessage=()=>postMessage("worker通过")'],{type:'text/javascript'}));
                const result=await new Promise((ok,no)=>{const w=new Worker(url);w.onmessage=e=>{w.terminate();ok(e.data)};w.onerror=no;w.postMessage('go')});
                URL.revokeObjectURL(url);
                const form=new FormData();form.append('file',new Blob(['中文上传']),'synthetic.txt');
                const upload=await (await fetch('/__verify/upload',{method:'POST',body:form})).json();
                if(upload.content!=='中文上传'||upload.bytes!==12)throw new Error('上传不一致');
                const stream=await fetch('/__verify/stream',{method:'POST'});
                const reader=stream.body.getReader(),decoder=new TextDecoder();let text='',chunks=0;
                while(true){const r=await reader.read();if(r.done)break;text+=decoder.decode(r.value,{stream:true});chunks++;}
                if(!text.includes('中文')||!text.includes('完成')||chunks<2)throw new Error('流式未分块');
                document.getElementById('result').textContent=result+' 上传通过 分块数='+chunks+' '+text;
              }catch(error){document.getElementById('result').textContent='失败 '+error;}
            }
            </script></body></html>
            """;
    }
}
