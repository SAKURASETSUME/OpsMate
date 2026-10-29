"""OpsMate 入口：选空闲端口 → 同进程 uvicorn 线程 → pywebview 原生窗口（降级默认浏览器）。"""
from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

# --noconsole 打包态 sys.stdout/stderr 为 None：reconfigure 与 print 前必须判空
if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr is not None:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def pick_free_port() -> int:
    """绑定 127.0.0.1:0 取空闲端口（禁止写死端口）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _log(message: str) -> None:
    """向 stdout 打日志（noconsole 打包态静默）。"""
    if sys.stdout is not None:
        print(message, flush=True)


def _file_sha256(path: Path) -> str:
    """计算二进制文件 SHA-256，供冻结态运行时副本校验。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _select_ascii_runtime_root(source_hash: str) -> Path:
    """选择纯 ASCII 且可写的用户级目录保存冻结应用运行缓存。"""
    candidates: list[Path] = []
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x001C, None, 0, buffer)
        if result == 0 and buffer.value:
            candidates.append(Path(buffer.value))
    local_app_data = os.environ.get("LOCALAPPDATA")
    public_dir = os.environ.get("PUBLIC")
    if local_app_data:
        candidates.append(Path(local_app_data))
    if public_dir:
        candidates.append(Path(public_dir))
    candidates.append(Path(tempfile.gettempdir()))

    failures: list[str] = []
    for base_dir in dict.fromkeys(candidates):
        runtime_root = base_dir / "OpsMate" / "runtime" / source_hash[:16]
        if not str(runtime_root).isascii():
            failures.append(f"{base_dir}: 路径含非 ASCII 字符")
            continue
        try:
            runtime_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            failures.append(f"{base_dir}: {exc}")
            continue
        return runtime_root
    detail = "；".join(failures) if failures else "没有可用候选目录"
    raise RuntimeError(f"未找到纯 ASCII 且可写的冻结应用运行目录：{detail}")


def _relaunch_frozen_from_ascii_shadow() -> bool:
    """中文目录下将冻结程序复制到英文用户缓存并自动重启。"""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False

    source_exe = Path(sys.executable)
    source_root = source_exe.parent
    if str(source_root).isascii() or os.environ.get("OPSMATE_SHADOW_STARTED") == "1":
        return False

    source_internal = source_root / "_internal"
    if not source_internal.is_dir():
        raise RuntimeError("冻结应用缺少 _internal 目录，无法建立英文运行缓存")

    executable_hash = _file_sha256(source_exe)
    shadow_root = _select_ascii_runtime_root(executable_hash)
    shadow_exe = shadow_root / source_exe.name
    shadow_internal = shadow_root / source_internal.name
    ready_marker = shadow_root / ".ready"

    ready = False
    try:
        ready = (
            ready_marker.read_text(encoding="utf-8").strip() == executable_hash
            and shadow_exe.is_file()
            and _file_sha256(shadow_exe) == executable_hash
            and shadow_internal.is_dir()
        )
    except OSError:
        ready = False

    if not ready:
        shutil.copytree(source_internal, shadow_internal, dirs_exist_ok=True)
        shutil.copy2(source_exe, shadow_exe)
        if _file_sha256(shadow_exe) != executable_hash:
            raise RuntimeError("英文运行缓存中的 OpsMate.exe 校验失败")
        ready_marker.write_text(executable_hash, encoding="utf-8")

    child_env = os.environ.copy()
    child_env["OPSMATE_SHADOW_STARTED"] = "1"
    child_env["OPSMATE_DATA_DIR"] = str(source_root / "data")
    subprocess.Popen(
        [str(shadow_exe)],
        cwd=str(shadow_root),
        env=child_env,
        close_fds=True,
    )
    return True


def main() -> None:
    try:
        if _relaunch_frozen_from_ascii_shadow():
            return
    except Exception as exc:  # noqa: BLE001 —— 缓存失败时继续走原路径与浏览器降级
        _log(f"英文运行缓存准备失败（{exc}），继续从原路径启动。")

    # FastAPI 以库形式内嵌同进程，监听随机空闲端口
    import uvicorn

    from app.server import create_app

    port = pick_free_port()
    url = f"http://127.0.0.1:{port}"
    app = create_app()
    # --noconsole 下 stdout/stderr 为 None；禁用 uvicorn 默认日志格式器，
    # 避免其初始化时调用 sys.stdout.isatty() 导致启动失败。
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _log(f"OpsMate 后端已启动：{url}")

    try:
        import webview

        webview.create_window("OpsMate", url, width=1280, height=860)
        webview.start()
        # 窗口关闭后 uvicorn 线程不会随窗口自动终止：显式结束进程
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 —— GUI 链路任何异常都降级为默认浏览器
        _log(f"原生窗口启动失败（{exc}），已降级为默认浏览器打开。")
        _log("如需原生窗口，请安装 Microsoft Edge WebView2 运行时。")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
