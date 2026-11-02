"""我的配置工坊：user_configs 存取与多格式静态校验。

只做只读文本分析：永不解析执行、永不联网；除显式 shared=1 的记录外
内容不出现在任何 LLM 请求中。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import yaml

from app import config

MAX_CONTENT_BYTES = 2 * 1024 * 1024
FORMATS = ("yaml", "nginx", "keepalived", "properties", "json", "text")
LONG_LINE_CHARS = 1000
_MAX_TRAILING_HINTS = 20
_MAX_LONG_LINE_HINTS = 10


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """每次操作独立连接，用完关闭。"""
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_workbench() -> None:
    """按施工文档 §4.4 的 DDL 建 user_configs 表。"""
    config.ensure_dirs()
    with connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_configs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          format TEXT NOT NULL,
          content TEXT NOT NULL,
          shared INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        """)
        conn.commit()


def _check_fields(name: str, format_: str, content: str) -> None:
    """创建/更新共用的入参校验；超限抛 OverflowError 由路由转 413。"""
    if not name.strip():
        raise ValueError("配置名称不能为空")
    if len(name) > 80:
        raise ValueError("配置名称不能超过 80 字")
    if format_ not in FORMATS:
        raise ValueError("格式仅支持 " + "/".join(FORMATS))
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise OverflowError("配置内容超过 2MB 上限，请先拆分")


def list_configs() -> list[dict[str, Any]]:
    """倒序配置列表，只含摘要不回传正文。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id,name,format,shared,LENGTH(CAST(content AS BLOB)) AS size_bytes,updated_at "
            "FROM user_configs ORDER BY updated_at DESC,id DESC")
        return [dict(row) for row in rows]


def get_config(config_id: int) -> dict[str, Any] | None:
    """单条完整记录，供本地编辑回看。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id,name,format,content,shared,"
            "LENGTH(CAST(content AS BLOB)) AS size_bytes,created_at,updated_at "
            "FROM user_configs WHERE id=?", (config_id,)).fetchone()
        return dict(row) if row else None


def get_config_by_name(name: str) -> dict[str, Any] | None:
    """按名称取完整配置（@引用注入用，不要求开启共享——用户点名即授权）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id,name,format,content FROM user_configs WHERE name=? ORDER BY id DESC",
            (name,)).fetchone()
        return dict(row) if row else None


def create_config(name: str, format_: str, content: str) -> dict[str, Any]:
    _check_fields(name, format_, content)
    with connection() as conn:
        with conn:
            cursor = conn.execute(
                "INSERT INTO user_configs(name,format,content,shared) VALUES (?,?,?,0)",
                (name.strip(), format_, content))
            config_id = int(cursor.lastrowid)
    return {"id": config_id, "name": name.strip(), "format": format_}


def update_config(config_id: int, name: str, format_: str, content: str) -> bool:
    _check_fields(name, format_, content)
    with connection() as conn:
        with conn:
            cursor = conn.execute(
                "UPDATE user_configs SET name=?,format=?,content=?,"
                "updated_at=datetime('now','localtime') WHERE id=?",
                (name.strip(), format_, content, config_id))
            return cursor.rowcount > 0


def delete_config(config_id: int) -> bool:
    with connection() as conn:
        with conn:
            cursor = conn.execute("DELETE FROM user_configs WHERE id=?", (config_id,))
            return cursor.rowcount > 0


def set_shared(config_id: int, shared: bool) -> int | None:
    """显式白名单开关；只翻 shared，不动 updated_at，关闭立即生效。"""
    with connection() as conn:
        with conn:
            cursor = conn.execute(
                "UPDATE user_configs SET shared=? WHERE id=?",
                (1 if shared else 0, config_id))
            return (1 if shared else 0) if cursor.rowcount else None


def read_shared_config(name: str) -> dict[str, Any]:
    """智能体只读工具入口：仅返回 shared=1 的记录，内容截断约 4000 字符。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT content FROM user_configs WHERE shared=1 AND name=?", (name,)).fetchone()
    if row is None:
        return {"ok": False, "error": "配置不存在或未共享"}
    content = row["content"]
    return {"ok": True, "result": {
        "name": name, "content": content[:4000], "truncated": len(content) > 4000}}


# ---------------- 静态校验（全部只读分析，不落库） ----------------

def _line_of(content: str, position: int) -> int:
    return content.count("\n", 0, position) + 1


def _generic_checks(content: str, lines: list[str],
                    warnings: list[dict[str, Any]]) -> None:
    """通用检查：BOM、混合行尾、尾随空格、超长行——均为警告不阻断。"""
    if content.startswith("\ufeff"):
        warnings.append({"line": 1, "message": "文件含 UTF-8 BOM，部分解析器会报错"})
    ending_names = {"\r\n": "CRLF", "\r": "CR", "\n": "LF"}
    first_at: dict[str, int] = {}
    for match in re.finditer(r"\r\n|\r|\n", content):
        first_at.setdefault(match.group(0), match.start())
    if len(first_at) > 1:
        ordered = sorted(first_at.items(), key=lambda item: item[1])
        mixed = "、".join(ending_names.get(key, repr(key)) for key, _ in ordered)
        warnings.append({"line": _line_of(content, ordered[1][1]),
                         "message": f"混合行尾：同一文件混用 {mixed}"})
    trailing = [index + 1 for index, line in enumerate(lines) if line != line.rstrip()]
    for line_no in trailing[:_MAX_TRAILING_HINTS]:
        warnings.append({"line": line_no, "message": "行尾存在多余空白字符"})
    if len(trailing) > _MAX_TRAILING_HINTS:
        warnings.append({"line": trailing[_MAX_TRAILING_HINTS],
                         "message": f"共 {len(trailing)} 行存在尾随空格，仅显示前 {_MAX_TRAILING_HINTS} 处"})
    long_lines = [index + 1 for index, line in enumerate(lines) if len(line) > LONG_LINE_CHARS]
    for line_no in long_lines[:_MAX_LONG_LINE_HINTS]:
        warnings.append({"line": line_no, "message": f"行长度超过 {LONG_LINE_CHARS} 字符"})
    if len(long_lines) > _MAX_LONG_LINE_HINTS:
        warnings.append({"line": long_lines[_MAX_LONG_LINE_HINTS],
                         "message": f"共 {len(long_lines)} 行超长，仅显示前 {_MAX_LONG_LINE_HINTS} 处"})


def _scan_duplicate_keys_heuristic(content: str,
                                   warnings: list[dict[str, Any]]) -> None:
    """解析失败时的降级重复键扫描：同缩进层级同名键视为重复。

    近似规则：跳过注释/列表项 `- ` 行与块标量（| >）内部行；不能识别
    flow 风格与锚点等复杂结构，仅用于坏文件中仍能提示重复键。
    """
    context: list[tuple[int, set[str]]] = []
    block_indent = -1
    for line_no, raw in enumerate(content.splitlines(), 1):
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if block_indent >= 0:
            if not stripped or indent > block_indent:
                continue
            block_indent = -1
        if not stripped or stripped.startswith("#") or stripped.startswith("- "):
            continue
        match = re.match(r"^(\s*)([^\s#][^:]*?)\s*:(?:\s|$)", raw)
        if match is None:
            continue
        key = match.group(2).strip("\"'")
        if raw.rstrip().endswith(("|", ">")) or re.search(r":[|>][+-]?\s*$", raw):
            block_indent = indent
        while context and context[-1][0] > indent:
            context.pop()
        if context and context[-1][0] == indent:
            if key in context[-1][1]:
                warnings.append({"line": line_no, "message": f"重复键：{key}（后值覆盖前值）"})
            else:
                context[-1][1].add(key)
        else:
            context.append((indent, {key}))


def _validate_yaml(content: str, errors: list[dict[str, Any]],
                   warnings: list[dict[str, Any]]) -> None:
    """yaml.safe_load 全量解析取行号；自定 constructor 收集重复键为警告。

    解析失败时 constructor 不会执行，改用缩进栈启发式仍给出重复键提示。
    """
    duplicates: list[tuple[str, int]] = []

    class DuplicateTrackingLoader(yaml.SafeLoader):
        """保持 PyYAML 后值覆盖语义，仅记录重复键及其行号。"""

        def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
            mapping: dict[Any, Any] = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                try:
                    duplicate = key in mapping
                except TypeError:
                    raise yaml.ConstructorError(
                        "while constructing a mapping", node.start_mark,
                        "found unhashable key", key_node.start_mark) from None
                if duplicate:
                    duplicates.append((str(key), key_node.start_mark.line + 1))
                mapping[key] = self.construct_object(value_node, deep=deep)
            return mapping

    try:
        yaml.load(content, Loader=DuplicateTrackingLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        errors.append({"line": (mark.line + 1) if mark else 0,
                       "message": "YAML 解析错误：" + str(problem)})
        _scan_duplicate_keys_heuristic(content, warnings)
    for key, line_no in duplicates:
        warnings.append({"line": line_no, "message": f"重复键：{key}（后值覆盖前值）"})


def _code_text(line: str) -> tuple[str, bool]:
    """去掉 # 注释与引号内内容后的代码文本；引号不跨行，返回是否闭合。"""
    out: list[str] = []
    quote = ""
    for char in line:
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            continue
        if char == "#":
            break
        out.append(char)
    return "".join(out), not quote


def _validate_block_syntax(content: str, format_: str, errors: list[dict[str, Any]]) -> None:
    """nginx/keepalived：大括号配对栈 + 指令行缺分号（keepalived 语法无分号，只查括号）。"""
    stack: list[int] = []
    for line_no, raw in enumerate(content.splitlines(), 1):
        code, closed = _code_text(raw)
        if not closed:
            errors.append({"line": line_no, "message": "引号未闭合（引号不能跨行）"})
            continue
        stripped = code.strip()
        for _ in range(stripped.count("{")):
            stack.append(line_no)
        for _ in range(stripped.count("}")):
            if not stack:
                errors.append({"line": line_no, "message": "多余的 '}'，没有对应的开括号"})
            else:
                stack.pop()
        if (format_ == "nginx" and stripped
                and not stripped.endswith("{") and not stripped.endswith("}")
                and not stripped.endswith(";")):
            errors.append({"line": line_no, "message": "指令行末尾缺少分号 ';'"})
    for line_no in stack:
        errors.append({"line": line_no, "message": "块未闭合：'{' 缺少对应的 '}'"})


def _validate_properties(lines: list[str], errors: list[dict[str, Any]],
                         warnings: list[dict[str, Any]]) -> None:
    """properties：非法行报错；重复键警告（后值覆盖）。"""
    seen: dict[str, int] = {}
    for line_no, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped or stripped[0] in "#!":
            continue
        if "=" not in stripped:
            errors.append({"line": line_no, "message": "非法行：properties 应为 key=value 形式"})
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in seen:
            warnings.append({"line": line_no, "message": f"重复键：{key}（后值覆盖）"})
        seen[key] = line_no


def _validate_json(content: str, errors: list[dict[str, Any]]) -> None:
    """json.loads + JSONDecodeError 自带行列号。"""
    try:
        json.loads(content)
    except json.JSONDecodeError as exc:
        errors.append({"line": exc.lineno, "message": "JSON 解析错误：" + exc.msg})


def validate_config(format_: str, content: str) -> dict[str, Any]:
    """按格式静态校验，返回统一结构；errors 非空即 ok=false。"""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    lines = content.splitlines()
    _generic_checks(content, lines, warnings)
    if format_ == "yaml":
        _validate_yaml(content, errors, warnings)
    elif format_ in ("nginx", "keepalived"):
        _validate_block_syntax(content, format_, errors)
    elif format_ == "properties":
        _validate_properties(lines, errors, warnings)
    elif format_ == "json":
        _validate_json(content, errors)
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "stats": {"lines": len(lines), "bytes": len(content.encode("utf-8"))}}
