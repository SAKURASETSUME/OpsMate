"""脚本生成、历史持久化及 FTS5 同步。"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import closing
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import config
from app.agent.engine import AgentFormatError, run_agent
from app.codegen.prompts import CODEGEN_SYSTEM_PROMPT
from app.llm.provider import LLMClient, LLMError
from app.llm.routes import effective_settings

router = APIRouter(prefix="/api/codegen", tags=["codegen"])


def _sse(payload: dict[str, Any]) -> str:
    """统一 SSE 事件行。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class GenerateInput(BaseModel):
    requirement: str = Field(min_length=1, max_length=60000)
    distro: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=60000)


def ensure_history() -> None:
    """建表与兼容早期 steps 列，DDL 统一通过代码执行。"""
    config.ensure_dirs()
    with closing(sqlite3.connect(config.DB_PATH, check_same_thread=False)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""CREATE TABLE IF NOT EXISTS codegen_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, requirement TEXT NOT NULL,
            params TEXT, script TEXT NOT NULL, explanation TEXT, warnings TEXT, usage TEXT,
            model TEXT, steps TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(codegen_history)")}
        if "steps" not in columns:
            connection.execute("ALTER TABLE codegen_history ADD COLUMN steps TEXT")
        if "scripts" not in columns:
            connection.execute("ALTER TABLE codegen_history ADD COLUMN scripts TEXT")
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='codegen_history_fts'").fetchone()
        connection.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS codegen_history_fts USING fts5(
            requirement, script, content='codegen_history', content_rowid='id', tokenize='unicode61')""")
        if not exists:
            connection.execute("INSERT INTO codegen_history_fts(codegen_history_fts) VALUES ('rebuild')")
        connection.commit()


_ASSIGNMENT_PREFIX = re.compile(r"^\s*(?:export\s+|local\s+|declare\s+)?[A-Za-z_][A-Za-z0-9_]*=[^\s'\"|;&]*$")
_NUMERIC_TEST = re.compile(r"\[\s+\$([A-Za-z_][A-Za-z0-9_]*|[0-9]+)\s+(-(?:eq|ne|lt|le|gt|ge)\s+\d+\s*)\]")


_HEREDOC_START = re.compile(r"<<-?\s*('?)([A-Za-z_][A-Za-z0-9_]*)\1")


def find_unsafe_expansion(script: str) -> str:
    """定位首个未引用且处于危险位置的变量展开；无则返回空串。

    引号用栈建模：$(...) 内部是独立引号上下文（合法写法 "$(dirname "${X}")"），
    单引号内一切字面。豁免：注释、引号/命令替换内部、赋值语句右侧（不发生分词）、
    heredoc 正文（数据段，变量展开不发生分词）。
    """
    heredoc_delim = ""  # 非空表示当前行处于 heredoc 正文
    for line_no, line in enumerate(script.splitlines(), 1):
        if heredoc_delim:
            if line.strip() == heredoc_delim:
                heredoc_delim = ""  # 结束定界行
            continue  # heredoc 正文不扫描
        stack: list[str] = []  # 元素：'"'、"'" 或 'S'（$( 命令替换上下文）
        escaped = False
        index = 0
        while index < len(line):
            char = line[index]
            top = stack[-1] if stack else ""
            if escaped:
                escaped = False
            elif char == "\\" and top != "'":
                escaped = True
            elif char == "#" and not stack:
                break  # 行内注释（引号外的 # 之后是字面量）
            elif char == "'" and top != '"':
                if top == "'":
                    stack.pop()
                else:
                    stack.append("'")
            elif char == '"':
                if top == '"':
                    stack.pop()
                else:
                    stack.append('"')
            elif char == "(" and index > 0 and line[index - 1] == "$" and top != "'":
                stack.append("S")
            elif char == ")" and top == "S":
                stack.pop()
            elif char == "<" and not stack and line[index:index + 2] in ("<<",):
                match = _HEREDOC_START.search(line, index)
                if match:
                    heredoc_delim = match.group(2)  # 正文从下一行开始
                    break
            elif char == "$" and not stack and index + 1 < len(line) \
                    and re.match(r"\$(?:[A-Za-z_]|\{|[0-9@*])", line[index:]):
                if not _ASSIGNMENT_PREFIX.match(line[:index]):
                    return f"第{line_no}行: {line.strip()[:120]}"
            index += 1
    return ""


def _has_unsafe_expansion(script: str) -> bool:
    return bool(find_unsafe_expansion(script))


_DANGEROUS_OP = re.compile(r"(?:^|[;|&\s])(?:rm|kill|iptables)\s|systemctl\s+(?:stop|restart)\b|\s-delete\b")


def ensure_echo_prompts(script: str, context: str) -> None:
    """影响业务的命令前 3 行内必须有中文 echo 提示。

    echo 语句行本身（提示文案常提到要执行的操作）与 heredoc 正文（数据段）
    不参与危险操作检测，但仍计入 previous 供后续行匹配。
    """
    heredoc_delim = ""
    previous: list[str] = []
    for line in script.splitlines():
        code = line.strip()
        if heredoc_delim:
            if code == heredoc_delim:
                heredoc_delim = ""
            continue
        if not code or code.startswith("#"):
            continue
        started = _HEREDOC_START.search(code)
        if started:
            heredoc_delim = started.group(2)
        first_token = code.split(None, 1)[0]
        if first_token != "echo" and re.search(_DANGEROUS_OP, code):
            if not any("echo " in earlier for earlier in previous[-3:]):
                raise AgentFormatError(f"{context}影响业务操作前缺少中文 echo 提示：" + code)
        previous.append(code)


def _validate_script_item(script: Any, explanation: Any, warnings: Any, usage: Any,
                          context: str) -> dict:
    """单个脚本的硬性校验（多脚本数组元素与单脚本共用同一套规则）；失败信息精确到条目。"""
    if isinstance(script, str):
        # 数值测试自动补引号（bash 内建测试对整数比较安全等价）：[ $EUID -eq 0 ] / [ $1 -lt 1 ]
        script = _NUMERIC_TEST.sub(r'[ "$\1" \2]', script)
    checks: list[tuple[str, bool]] = [
        ("script 必须是文本", isinstance(script, str)),
        ("首行须为 #!/usr/bin/env bash", isinstance(script, str) and script.startswith("#!/usr/bin/env bash")),
        ("须含 set -euo pipefail", isinstance(script, str) and "set -euo pipefail" in script),
        ("脚本至少 3 行", isinstance(script, str) and len(script.splitlines()) >= 3),
        ("变量展开必须双引号包裹", isinstance(script, str) and not _has_unsafe_expansion(script)),
        ("script 内不得出现『解读/分析』字样", isinstance(script, str) and "解读" not in script and "分析" not in script),
        ("explanation 须为 ≥3 段的数组", isinstance(explanation, list) and len(explanation) >= 3),
        ("explanation 每段须含 lines/title/detail 非空文本", isinstance(explanation, list) and all(
            isinstance(item, dict) and all(isinstance(item.get(k), str) and item[k].strip()
            for k in ("lines", "title", "detail")) for item in explanation)),
        ("warnings 须为字符串数组", isinstance(warnings, list) and all(isinstance(w, str) for w in warnings)),
        ("usage 须为字符串", isinstance(usage, str)),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        located = find_unsafe_expansion(script) if isinstance(script, str) else ""
        raise AgentFormatError(
            f"{context}脚本结构不满足约定（未通过：{'；'.join(failed)}"
            + (f"；违规位置 → {located}" if located else "")
            + "）：" + json.dumps(
                {"script": str(script)[:300], "usage": usage}, ensure_ascii=False)[:400])
    header = "\n".join(script.splitlines()[:20])
    if not all(marker in header for marker in ("用途", "用法", "参数", "依赖", "适用")) or "AI" not in header:
        raise AgentFormatError(f"{context}缺少用途/用法/参数/依赖/AI审阅/适用发行版注释块：" + script[:300])
    ensure_echo_prompts(script, context)
    return {"script": script, "explanation": explanation, "warnings": warnings, "usage": usage}


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """拒绝畸形或不满足脚本/解读分离约定的模型输出。"""
    if payload.get("need_clarification") is True:
        questions = payload.get("questions")
        if isinstance(questions, list):
            questions = [
                q["question"] + (f"（建议：{q['default']}）" if q.get("default") is not None else "")
                if isinstance(q, dict) and isinstance(q.get("question"), str) else q
                for q in questions]
            # 一轮最多三个问题；其余信息可在用户补答后的下一轮继续澄清。
            questions = questions[:3]
        if not isinstance(questions, list) or not 1 <= len(questions) <= 3 or not all(isinstance(q, str) and q.strip() for q in questions):
            raise AgentFormatError(json.dumps(payload, ensure_ascii=False))
        return {"need_clarification": True, "questions": questions}
    # 多脚本：需求要几个就全部生成，每个元素独立过硬校验；name 仅用于界面标识，不写入脚本内容
    if isinstance(payload.get("scripts"), list) and payload["scripts"]:
        if len(payload["scripts"]) > 3:
            raise AgentFormatError(
                f"一次最多生成 3 个脚本（当前 {len(payload['scripts'])} 个）：请只保留最关键的 3 个，"
                "或返回 need_clarification 建议用户分批生成")
        names: list[str] = []
        items: list[dict[str, Any]] = []
        for index, item in enumerate(payload["scripts"], 1):
            if not isinstance(item, dict):
                raise AgentFormatError(f"scripts[{index}] 不是对象：" + json.dumps(item, ensure_ascii=False)[:200])
            name = str(item.get("name", "")).strip()[:60]
            if not name or "/" in name or "\\" in name or name in names:
                raise AgentFormatError(f"scripts[{index}] 名称无效或重复（需非空、唯一、不含路径分隔符）：{name!r}")
            names.append(name)
            checked = _validate_script_item(item.get("script"), item.get("explanation"),
                                            item.get("warnings"), item.get("usage"), f"[{name}] ")
            items.append({"name": name, **checked})
        return {"need_clarification": False, "scripts": items}
    script = payload.get("script")
    if isinstance(script, str):
        # 数值测试自动补引号（bash 内建测试对整数比较安全等价）：[ $EUID -eq 0 ] / [ $1 -lt 1 ]
        script = _NUMERIC_TEST.sub(r'[ "$\1" \2]', script)
    explanation = payload.get("explanation")
    warnings = payload.get("warnings")
    # 拒绝明显未引用的变量展开；不把注释和单引号字面量当作变量。
    unsafe_expansion = _has_unsafe_expansion(script) if isinstance(script, str) else False
    if (payload.get("need_clarification") is not False or not isinstance(script, str)
        or not script.startswith("#!/usr/bin/env bash") or "set -euo pipefail" not in script
        or len(script.splitlines()) < 3 or unsafe_expansion
        or "解读" in script or "分析" in script
        or not isinstance(explanation, list) or len(explanation) < 3
        or not all(isinstance(item, dict) and all(isinstance(item.get(k), str) and item[k].strip()
                   for k in ("lines", "title", "detail")) for item in explanation)
        or not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings)
        or not isinstance(payload.get("usage"), str)):
        raise AgentFormatError(json.dumps(payload, ensure_ascii=False))
    header = "\n".join(script.splitlines()[:20])
    if not all(marker in header for marker in ("用途", "用法", "参数", "依赖", "适用")) or "AI" not in header:
        raise AgentFormatError("缺少用途/用法/参数/依赖/AI审阅/适用发行版注释块：" + json.dumps(payload, ensure_ascii=False))
    ensure_echo_prompts(script, "")
    return {"need_clarification": False, "script": script, "explanation": explanation,
            "warnings": warnings, "usage": payload["usage"]}


def save_result(body: GenerateInput, payload: dict[str, Any], model: str) -> None:
    """历史与 FTS 行在同一事务写入；多脚本时 script 列存全部拼接（供 FTS 命中），完整数组入 scripts 列。"""
    scripts_json = (json.dumps(payload["scripts"], ensure_ascii=False)
                    if isinstance(payload.get("scripts"), list) else None)
    script_column = ("\n\n".join(item["script"] for item in payload["scripts"])
                     if scripts_json else payload["script"])
    first = payload["scripts"][0] if scripts_json else payload
    with closing(sqlite3.connect(config.DB_PATH, check_same_thread=False)) as connection:
        with connection:
            cursor = connection.execute(
                "INSERT INTO codegen_history(requirement,params,script,explanation,warnings,usage,model,steps,scripts) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (body.requirement, json.dumps({"distro": body.distro, "notes": body.notes}, ensure_ascii=False),
                 script_column, json.dumps(first["explanation"], ensure_ascii=False),
                 json.dumps(first["warnings"], ensure_ascii=False), first["usage"], model,
                 json.dumps(payload["steps"], ensure_ascii=False), scripts_json))
            connection.execute("INSERT INTO codegen_history_fts(rowid,requirement,script) VALUES (?,?,?)",
                               (cursor.lastrowid, body.requirement, script_column))


MULTI_SCRIPT_HINT_RE = re.compile(
    r"(?:[两三2-3]|几)\s*[个份].{0,8}脚本|脚本.{0,24}(?:和|以及|加|、).{0,24}脚本|多个脚本|分别(?:写|生成)")


@router.post("/generate")
async def generate(body: GenerateInput) -> StreamingResponse:
    """SSE 流式生成：过程事件（工具轨迹/阶段）实时推送 → result → done。

    成功成稿才入库；失败/超时发 error 事件，不写历史。
    """
    settings = effective_settings()

    async def error_stream(message: str) -> AsyncIterator[str]:
        yield _sse({"error": message})

    if not body.requirement.strip():
        return StreamingResponse(error_stream("请填写脚本需求"), media_type="text/event-stream")
    if not settings.get("api_key"):
        return StreamingResponse(error_stream("未配置模型密钥，请先前往设置页保存并启用"),
                                 media_type="text/event-stream")
    ensure_history()
    user = f"需求：{body.requirement}\n发行版：{body.distro or '未指定'}\n补充：{body.notes or '无'}"
    if MULTI_SCRIPT_HINT_RE.search(body.requirement):
        user += ("\n（本需求包含多个脚本：必须输出 scripts 数组，每个元素含唯一 name 与完整的 "
                 "script/explanation/warnings/usage；一次最多 3 个）")
    events: asyncio.Queue = asyncio.Queue()

    async def produce() -> dict[str, Any]:
        for attempt in range(2):
            raw, steps = await run_agent(LLMClient(settings), CODEGEN_SYSTEM_PROMPT, user + (
                "\n上次业务输出未通过校验。必须是业务 JSON；所有变量展开必须双引号包裹；脚本不含解读/分析字样；至少三段解读。顶部注释必须写全用途/用法/参数/依赖命令/AI生成请审阅/适用发行版，删除前必须 echo 中文提示。若需求是日志归档备份，应 tar -czf 归档，保留策略只针对归档文件，禁止删除源日志，定时任务提供 cron 安装指引。需求包含多个脚本时必须输出 scripts 数组且一个不少，每项含唯一的 name。" if attempt else ""),
                on_event=lambda event: events.put_nowait(event))
            try:
                result = validate_payload(raw)
                if not result["need_clarification"]:
                    if isinstance(result.get("scripts"), list):
                        combined = " ".join(item["usage"] + " ".join(item["warnings"])
                                            for item in result["scripts"])
                    else:
                        combined = result["usage"] + " ".join(result["warnings"])
                    if ("每天" in body.requirement or "凌晨" in body.requirement) and "cron" not in combined.lower():
                        raise AgentFormatError("定时需求缺少 cron 用法与风险指引：" + json.dumps(raw, ensure_ascii=False))
                    result["steps"] = steps
                    save_result(body, result, settings["model"])
                return result
            except AgentFormatError:
                if attempt:
                    raise
        raise AgentFormatError("未生成结果")

    async def produce_bounded() -> dict[str, Any]:
        # 长需求出稿慢（校验失败还有一次重试），超时上限与前端 320s 超时错开
        return await asyncio.wait_for(produce(), timeout=300)

    async def stream() -> AsyncIterator[str]:
        task = asyncio.create_task(produce_bounded())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(events.get(), timeout=0.25)
                    yield _sse(event)
                except asyncio.TimeoutError:
                    pass
                if task.done():
                    while not events.empty():
                        yield _sse(events.get_nowait())
                    break
        finally:
            if not task.done():
                task.cancel()  # 客户端断开时不留后台生成任务
        try:
            result = task.result()
        except asyncio.TimeoutError:
            yield _sse({"error": "生成超时，请缩短需求后重试"})
            return
        except LLMError as exc:
            yield _sse({"error": str(exc)})
            return
        except AgentFormatError as exc:
            summary = str(exc)
            key = str(settings.get("api_key", ""))
            if key:
                summary = summary.replace(key, "[密钥已隐藏]")
            yield _sse({"error": "模型输出格式无效：" + summary[:500]})
            return
        yield _sse({"result": result})
        yield _sse({"done": True})

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/history")
def history(limit: int = Query(default=50, ge=1, le=2000)) -> dict[str, Any]:
    """倒序列出脚本历史。"""
    ensure_history()
    with closing(sqlite3.connect(config.DB_PATH, check_same_thread=False)) as connection:
        connection.row_factory = sqlite3.Row
        return {"items": [dict(row) for row in connection.execute(
            "SELECT id,requirement,created_at,model FROM codegen_history ORDER BY id DESC LIMIT ?", (limit,))]}


@router.get("/history/{id}")
def history_detail(id: int) -> dict[str, Any]:
    """返回可回看的完整记录，JSON 列还原成对象。"""
    ensure_history()
    with closing(sqlite3.connect(config.DB_PATH, check_same_thread=False)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM codegen_history WHERE id=?", (id,)).fetchone()
    if row is None:
        raise HTTPException(404, "脚本记录不存在")
    result = dict(row)
    for field, default in (("params", {}), ("explanation", []), ("warnings", []), ("steps", []), ("scripts", [])):
        result[field] = json.loads(result[field]) if result[field] else default
    result["need_clarification"] = False
    return result
