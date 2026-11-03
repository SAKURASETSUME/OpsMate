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
ASSISTANT_FILES_DIR = DATA_DIR / "assistant_files"   # 会话附件原始文件
AGENT_FILES_DIR = DATA_DIR / "agent_files"           # 智能体经确认生成/修改的文件
DB_PATH = DATA_DIR / "opsmate.db"
CONFIG_JSON = DATA_DIR / "config.json"
PROFILES_JSON = DATA_DIR / "model_profiles.json"


def ensure_dirs() -> None:
    """确保运行期可写目录存在（frozen 首启动在 exe 旁创建 data/ 并落地知识数据）。"""
    for directory in (DATA_DIR, COMMANDS_DIR, KB_DIR, LOGS_DIR,
                      ASSISTANT_FILES_DIR, AGENT_FILES_DIR):
        Path(directory).mkdir(parents=True, exist_ok=True)
    land_bundled_knowledge()


def land_bundled_knowledge() -> None:
    """frozen 首启动把包内知识数据（commands/kb/skills）落地到 exe 旁 data/，仅一次。

    目标目录已存在即视为已落地，绝不覆盖用户侧数据；开发态直接跳过。
    """
    if not getattr(sys, "frozen", False):
        return
    bundled_root = APP_DIR.parent / "data"
    targets = {"commands": COMMANDS_DIR, "kb": KB_DIR, "skills": DATA_DIR / "skills"}
    for name, target in targets.items():
        source = bundled_root / name
        if not source.is_dir():
            continue
        # ensure_dirs 可能已把目标建成空目录：存在但为空仍视为未落地
        if target.exists() and any(target.iterdir()):
            continue
        try:
            import shutil
            shutil.copytree(source, target, dirs_exist_ok=True)
        except OSError:
            continue  # 落地失败不阻断启动：对应模块显示为空，可手动拷贝


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
    temporary = CONFIG_JSON.with_name(CONFIG_JSON.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
    temporary.replace(CONFIG_JSON)


def load_model_profiles() -> dict:
    """读取本机命名配置，不向调用方以外输出内容。"""
    if not PROFILES_JSON.exists():
        return {"active_id": "current", "items": []}
    with open(PROFILES_JSON, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError("本机配置文件格式无效")
    return value


def save_model_profiles(profiles: dict) -> None:
    """原子写入本机配置，所有临时文件同样必须忽略与排除打包。"""
    ensure_dirs()
    temporary = PROFILES_JSON.with_name(PROFILES_JSON.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(profiles, handle, ensure_ascii=False, indent=2)
    temporary.replace(PROFILES_JSON)
