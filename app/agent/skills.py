"""通用排查技能（优化方案三）：data/skills/*.yaml 加载与关键词匹配。

技能不改变工具面，只把"方法论"注入规划与终答 system：命中触发词最长者优先；
未命中完全不影响既有行为。坏文件跳过（与 kb 同策略）。
"""
from __future__ import annotations

import threading

import yaml

from app import config

SKILLS_DIR = config.DATA_DIR / "skills"

_lock = threading.Lock()
_skills: list[dict] = []


def _load() -> list[dict]:
    items: list[dict] = []
    if not SKILLS_DIR.is_dir():
        return items
    for path in sorted(SKILLS_DIR.glob("*.yaml")):
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        if (not str(data.get("name", "")).strip()
                or not isinstance(data.get("triggers"), list) or not data.get("triggers")
                or not str(data.get("methodology", "")).strip()):
            continue
        items.append({
            "name": str(data["name"]).strip(),
            "label": str(data.get("label") or data["name"]).strip(),
            "triggers": [str(t).strip().casefold() for t in data["triggers"] if str(t).strip()],
            "methodology": str(data["methodology"]).strip(),
            "example_question": str(data.get("example_question", "")).strip(),
        })
    return items


def refresh() -> None:
    """重新扫描技能目录。"""
    global _skills
    with _lock:
        _skills = _load()


def list_skills() -> list[dict]:
    """技能清单（供 API 输出，不含 methodology 全文）。"""
    global _skills
    with _lock:
        if not _skills:
            _skills = _load()
        return [{"name": s["name"], "label": s["label"],
                 "example_question": s["example_question"]} for s in _skills]


def match_skill(text: str) -> dict | None:
    """按触发词匹配；多个命中取触发词最长者，无命中返回 None。"""
    global _skills
    haystack = str(text or "").casefold()
    if not haystack.strip():
        return None
    with _lock:
        if not _skills:
            _skills = _load()
        best: tuple[int, dict] | None = None
        for skill in _skills:
            for trigger in skill["triggers"]:
                if trigger in haystack and (best is None or len(trigger) > best[0]):
                    best = (len(trigger), skill)
        return best[1] if best else None


def methodology_block(skill: dict) -> str:
    """拼装注入 system 的方法论文本。"""
    return (f"\n\n【排查方法论参考（命中技能：{skill['label']}）】\n"
            "以下步骤供参考，按用户实际情况取舍，不要机械照抄：\n" + skill["methodology"] + "\n")
