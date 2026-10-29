"""路径常量与 settings 读写；frozen/开发双态基准切换（全项目唯一判断处）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # 打包态：只读资源在 sys._MEIPASS；可写数据目录以 exe 所在目录为基准
    APP_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "app"
    _DATA_DIR_OVERRIDE = os.environ.get("OPSMATE_DATA_DIR")
    DATA_DIR = (
        Path(_DATA_DIR_OVERRIDE)
        if _DATA_DIR_OVERRIDE
        else Path(sys.executable).parent / "data"
    )
else:
    # 开发态：以项目根为基准
    _ROOT_DIR = Path(__file__).resolve().parent.parent
    APP_DIR = _ROOT_DIR / "app"
    DATA_DIR = _ROOT_DIR / "data"

WEB_DIR = APP_DIR / "web"
COMMANDS_DIR = DATA_DIR / "commands"
KB_DIR = DATA_DIR / "kb"
LOGS_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "opsmate.db"
CONFIG_JSON = DATA_DIR / "config.json"


def ensure_dirs() -> None:
    """确保运行期可写目录存在（frozen 首启动在 exe 旁创建 data/）。"""
    for directory in (DATA_DIR, COMMANDS_DIR, KB_DIR, LOGS_DIR):
        Path(directory).mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    """读取 data/config.json；缺失或损坏时返回空对象。"""
    if not CONFIG_JSON.exists():
        return {}
    try:
        with open(CONFIG_JSON, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    """写入 data/config.json（utf-8，缩进 2，ensure_ascii=False）。"""
    with open(CONFIG_JSON, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
