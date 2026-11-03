"""生成 dist 用的启动器批处理（ASCII + CRLF，规避 cmd 解析坑）。"""
from pathlib import Path

LINES = [
    "@echo off",
    "rem OpsMate launcher: program folder contains non-ASCII path chars,",
    "rem so use system robocopy to make an ASCII runtime copy, then start from there.",
    "rem User data stays in this folder (OPSMATE_DATA_DIR points back).",
    "setlocal",
    'set "SRC=%~dp0"',
    'set "DST=%LOCALAPPDATA%\\OpsMate\\launch"',
    "echo OpsMate: preparing runtime (first run about 1 minute, instant afterwards)...",
    'robocopy "%SRC%" "%DST%" /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /XF start_OpsMate.bat >nul',
    "if errorlevel 8 (",
    "  echo Copy failed. Move the whole OpsMate folder to an ASCII-only path",
    "  echo such as D:\\OpsMate and run OpsMate.exe directly.",
    "  pause",
    "  exit /b 1",
    ")",
    'set "OPSMATE_DATA_DIR=%SRC%data"',
    'start "" "%DST%\\OpsMate.exe"',
    "endlocal",
    "",  # 末尾换行
]


def main() -> None:
    for target in (Path("tools/start_OpsMate.bat"),
                   Path("dist/OpsMate/start_OpsMate.bat")):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes("\r\n".join(LINES).encode("ascii"))
        print("written", target)


if __name__ == "__main__":
    main()
