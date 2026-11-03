"""OpsMate 入口：选空闲端口 → 同进程 uvicorn 线程 → pywebview 原生窗口（降级默认浏览器）。"""
from __future__ import annotations

import hashlib
import os
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
    """向 stdout 打日志（noconsole 打包态静默）；打包态同时落 data/opsmate-startup.log 便于排障。"""
    if sys.stdout is not None:
        print(message, flush=True)
    if getattr(sys, "frozen", False):
        try:
            log_path = Path(os.environ.get("OPSMATE_DATA_DIR") or Path(sys.executable).parent) / "data" / "opsmate-startup.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            if log_path.exists() and log_path.stat().st_size > 100_000:
                log_path.unlink()
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
            pass


def _file_sha256(path: Path) -> str:
    """计算二进制文件 SHA-256，供冻结态运行时副本校验。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_runtime_bases() -> list[Path]:
    """英文运行目录候选，按优先级：用户 Profile → 非系统固定盘根 → Public → TEMP。

    未签名 exe 写用户 Profile 可能被 Defender 可控文件夹访问拦截（实测本机如此），
    非系统数据盘根目录不受该保护，作为关键降级路径。
    """
    candidates: list[Path] = []
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x001C, None, 0, buffer)
        if result == 0 and buffer.value:
            candidates.append(Path(buffer.value))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data))
    if sys.platform == "win32":
        import ctypes

        drives_mask = ctypes.windll.kernel32.GetLogicalDrives()
        system_drive = (os.environ.get("SystemDrive") or "C:").upper()
        for index in range(26):
            if not (drives_mask >> index) & 1:
                continue
            drive = f"{chr(65 + index)}:\\"
            if drive.upper() == system_drive:
                continue  # 系统盘根通常不可写
            if ctypes.windll.kernel32.GetDriveTypeW(drive) == 3:  # DRIVE_FIXED
                candidates.append(Path(drive))
    public_dir = os.environ.get("PUBLIC")
    if public_dir:
        candidates.append(Path(public_dir))
    candidates.append(Path(tempfile.gettempdir()))
    return candidates


def _select_ascii_runtime_root(source_hash: str) -> Path:
    """选择纯 ASCII 且可写的用户级目录保存冻结应用运行缓存。"""
    failures: list[str] = []
    for base_dir in dict.fromkeys(_candidate_runtime_bases()):
        runtime_root = base_dir / "OpsMate" / "runtime" / source_hash[:16]
        if not str(runtime_root).isascii():
            failures.append(f"{base_dir}: 路径含非 ASCII 字符")
            continue
        try:
            runtime_root.mkdir(parents=True, exist_ok=True)
            probe = runtime_root / ".writable"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            failures.append(f"{base_dir}: {exc}")
            continue
        return runtime_root
    detail = "；".join(failures) if failures else "没有可用候选目录"
    raise RuntimeError(f"未找到纯 ASCII 且可写的冻结应用运行目录：{detail}")


def _notify_box(message: str, title: str = "OpsMate", style: int = 0x40) -> None:
    """无依赖的 Win32 信息框（pythonnet 在中文路径下不可用，ctypes 不受限）。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, style)
    except Exception:  # noqa: BLE001 —— 提示失败不影响主流程
        pass


def _relaunch_frozen_from_ascii_shadow() -> bool:
    """中文目录下将冻结程序复制到英文用户缓存并自动重启。

    pythonnet/WebView2 无法从非 ASCII 路径加载（进程会解析联接/符号链接的真实路径，
    因此只能真实拷贝）。首次拷贝体积较大：先弹提示框说明，再执行；已有缓存则瞬时重启。
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False

    source_exe = Path(sys.executable)
    source_root = source_exe.parent
    if str(source_root).isascii() or os.environ.get("OPSMATE_SHADOW_STARTED") == "1":
        return False

    import shutil

    source_internal = source_root / "_internal"
    if not source_internal.is_dir():
        raise RuntimeError("冻结应用缺少 _internal 目录，无法建立英文运行缓存")

    executable_hash = _file_sha256(source_exe)
    shadow_root = _select_ascii_runtime_root(executable_hash)
    shadow_exe = shadow_root / source_exe.name
    shadow_internal = shadow_root / "_internal"
    ready_marker = shadow_root / ".ready"

    ready = False
    try:
        ready = (
            ready_marker.read_text(encoding="utf-8").strip() == executable_hash
            and shadow_exe.is_file()
            and shadow_internal.is_dir()
        )
    except OSError:
        ready = False

    if not ready:
        _log("首次启动：正在准备英文运行环境（拷贝一次，之后秒开）…")
        _notify_box(
            "检测到程序位于含中文的目录，首次启动需要准备运行环境（约 1-2 分钟，仅此一次）。\n"
            "点击确定后开始，窗口稍后自动打开，请勿重复启动。\n\n"
            "也可以把整个 OpsMate 文件夹移动到纯英文路径（如 D:\\OpsMate）后运行，无需此步骤。",
            "OpsMate 首次启动")
        if shadow_internal.exists():
            shutil.rmtree(shadow_internal, ignore_errors=True)
        shutil.copytree(source_internal, shadow_internal)
        shutil.copy2(source_exe, shadow_exe)
        if _file_sha256(shadow_exe) != executable_hash:
            raise RuntimeError("英文运行缓存中的 OpsMate.exe 校验失败")
        ready_marker.write_text(executable_hash, encoding="utf-8")
        _log("英文运行环境准备完成。")

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


class NativeApi:
    """注入到前端 window.pywebview.api 的原生能力（浏览器降级态不可用）。"""

    def pick_folder(self) -> str:
        """打开系统文件夹选择对话框；返回所选绝对路径，取消返回空串。"""
        import webview

        try:
            result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:  # noqa: BLE001 —— 对话框任何异常都按取消处理
            return ""
        if isinstance(result, (list, tuple)) and result:
            return str(result[0])
        return str(result or "")


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

        webview.create_window("OpsMate", url, width=1280, height=860, js_api=NativeApi())
        webview.start()
        # 窗口关闭后 uvicorn 线程不会随窗口自动终止：显式结束进程
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 —— GUI 链路任何异常都降级为默认浏览器
        _log(f"原生窗口启动失败（{exc}），已降级为默认浏览器打开。")
        _notify_box(
            f"原生窗口启动失败：{exc}\n\n已改用默认浏览器打开（若浏览器未弹出，请手动访问 {url} ）。\n"
            "程序位于中文目录时容易出现此问题：把整个 OpsMate 文件夹移动到纯英文路径"
            "（如 D:\\OpsMate）后重新运行即可恢复原生窗口。",
            "OpsMate", 0x30)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
