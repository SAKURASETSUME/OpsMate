"""指令速查服务层：扫描 data/commands/*.md 建立内存索引并搜索。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app import config

REHYPE_COMMENT_RE = re.compile(r"<!--rehype:[^>]*-->", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CommandRecord:
    """单个命令文档的索引记录。"""

    name: str
    title: str
    path: Path


class CommandIndex:
    """将命令文档常驻内存，提供稳定的搜索与详情读取。"""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self._records: list[CommandRecord] = []
        self._by_name: dict[str, CommandRecord] = {}
        self.refresh()

    @staticmethod
    def _extract_title(markdown: str) -> str:
        """提取标题下方第一行非空简介并截断为 120 字符。"""
        lines = markdown.lstrip("\ufeff").splitlines()
        start_index = 2 if len(lines) >= 2 and lines[1].strip() == "===" else 1
        for line in lines[start_index:]:
            candidate = line.strip()
            if candidate and not candidate.startswith("#"):
                return candidate[:120]
        return "暂无简介"

    def refresh(self) -> None:
        """重新扫描目录并按命令名排序。"""
        records: list[CommandRecord] = []
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob("*.md"):
            if not path.is_file():
                continue
            try:
                markdown = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            records.append(
                CommandRecord(
                    name=path.stem,
                    title=self._extract_title(markdown),
                    path=path,
                )
            )
        records.sort(key=lambda record: record.name.casefold())
        self._records = records
        self._by_name = {record.name.casefold(): record for record in records}

    def search(self, query: str, limit: int = 20) -> tuple[list[dict[str, str]], int]:
        """按名称前缀、名称包含、简介包含的优先级搜索。"""
        normalized = query.strip().casefold()
        if not normalized:
            matches = self._records
        else:
            ranked: list[tuple[int, str, CommandRecord]] = []
            for record in self._records:
                name = record.name.casefold()
                title = record.title.casefold()
                if name.startswith(normalized):
                    rank = 0
                elif normalized in name:
                    rank = 1
                elif normalized in title:
                    rank = 2
                else:
                    continue
                ranked.append((rank, name, record))
            ranked.sort(key=lambda item: (item[0], item[1]))
            matches = [item[2] for item in ranked]

        items = [
            {"name": record.name, "title": record.title}
            for record in matches[:limit]
        ]
        return items, len(matches)

    def get(self, name: str) -> dict[str, str] | None:
        """按命令名读取详情，返回剥离 rehype 注释后的 markdown。"""
        record = self._by_name.get(name.casefold())
        if record is None:
            return None
        try:
            markdown = record.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        cleaned = REHYPE_COMMENT_RE.sub("", markdown)
        return {"name": record.name, "title": record.title, "markdown": cleaned}


_COMMAND_INDEX: CommandIndex | None = None


def get_command_index() -> CommandIndex:
    """惰性创建进程级命令索引。"""
    global _COMMAND_INDEX
    if _COMMAND_INDEX is None:
        _COMMAND_INDEX = CommandIndex(config.COMMANDS_DIR)
    return _COMMAND_INDEX
