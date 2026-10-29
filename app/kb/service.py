"""配置速查服务层：load_kb() 读 data/kb/*.yaml；跨软件搜索。"""
from __future__ import annotations

from pathlib import Path

import yaml

from app import config

DANGER_LEVELS = ("false", "low", "medium", "high")


class KnowledgeBase:
    """加载全部 kb YAML 到内存，提供汇总、详情与跨软件搜索。"""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self._softwares: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self.refresh()

    def refresh(self) -> None:
        """重新扫描目录并按 software id 排序加载。"""
        softwares: list[dict] = []
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.directory.glob("*.yaml")):
            if not path.is_file():
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(data, dict) or not data.get("software"):
                continue
            if not isinstance(data.get("categories"), list):
                continue
            softwares.append(data)
        softwares.sort(key=lambda item: str(item["software"]))
        self._softwares = softwares
        self._by_id = {str(item["software"]): item for item in softwares}

    def summary(self) -> list[dict[str, object]]:
        """软件列表：id、显示名与 cli/conf 条目计数。"""
        items: list[dict[str, object]] = []
        for software in self._softwares:
            cli_count = 0
            conf_count = 0
            for category in software["categories"]:
                entries = category.get("entries") or []
                if category.get("id") == "cli":
                    cli_count += len(entries)
                else:
                    conf_count += len(entries)
            items.append(
                {
                    "software": software["software"],
                    "label": software.get("label") or software["software"],
                    "cli_count": cli_count,
                    "conf_count": conf_count,
                }
            )
        return items

    def get(self, software: str) -> dict | None:
        """按 software id 返回完整解析结果（原样）。"""
        return self._by_id.get(software)

    def search(self, query: str, software: str | None = None) -> list[dict[str, object]]:
        """跨软件（或指定软件内）大小写不敏感子串搜索条目。"""
        normalized = query.strip().casefold()
        if not normalized:
            return []
        results: list[dict[str, object]] = []
        for item in self._softwares:
            if software and str(item["software"]) != software:
                continue
            for category in item["categories"]:
                for entry in category.get("entries") or []:
                    haystack = " ".join(
                        str(entry.get(field) or "")
                        for field in ("name", "syntax", "desc")
                    ).casefold()
                    if normalized not in haystack:
                        continue
                    results.append(
                        {
                            "software": item["software"],
                            "category": category.get("id"),
                            "name": entry.get("name") or "",
                            "desc": entry.get("desc") or "",
                            "danger": entry.get("danger", False),
                        }
                    )
        return results


_KB: KnowledgeBase | None = None


def get_kb() -> KnowledgeBase:
    """惰性创建进程级知识库。"""
    global _KB
    if _KB is None:
        _KB = KnowledgeBase(config.KB_DIR)
    return _KB
