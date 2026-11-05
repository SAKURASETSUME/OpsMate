"""隔离原生窗口启动基线，页面 loaded 后确认 Vue 挂载并自动退出。"""
from __future__ import annotations
import json
import tempfile
import threading
import time
from pathlib import Path
import webview
from verify_java_baseline import start, stop, working_set


def main() -> None:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="opsmate-window-") as folder:
        root = Path(folder)
        proc,client,backend_start = start(root)
        samples = []
        window = webview.create_window("OpsMate J0 isolated baseline",str(client.base_url),width=1280,height=860)
        def loaded() -> None:
            try:
                deadline = time.monotonic()+15
                text = ""
                while time.monotonic()<deadline:
                    text = window.evaluate_js('document.getElementById("app").innerText') or ""
                    if "OpsMate" in text and len(text)>50:
                        break
                    time.sleep(0.1)
                assert "OpsMate" in text and len(text)>50, "Vue did not mount"
                samples.append({"process_entry_to_vue_seconds":time.perf_counter()-started,
                                "backend_start_seconds":backend_start,
                                "backend_working_set_bytes":working_set(json.loads((root/"ready.json").read_text(encoding="utf-8"))["pid"]),
                                "vue_mounted":True})
            finally:
                window.destroy()
        window.events.loaded += loaded
        timer = threading.Timer(30,window.destroy)
        timer.start()
        try:
            webview.start()
            assert samples, "native window did not reach loaded/Vue mounted"
        finally:
            timer.cancel()
            stop(proc,client)
        target = Path(__file__).resolve().parents[1]/"migration"/"j0"/"desktop-baseline.json"
        target.write_text(json.dumps({"samples":samples,"scope":"Python source process entry to native Vue mounted; excludes Python interpreter boot; not packaged exe"},indent=2),encoding="utf-8")
        print("PASS: isolated native window loaded, Vue mounted, auto closed and backend exited")


if __name__ == "__main__":
    main()
