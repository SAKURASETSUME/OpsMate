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
    requirement: str = Field(min_length=1, max_length=12000)
    distro: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=12000)


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


def _has_unsafe_expansion(script: str) -> bool:
    """拒绝明显未引用的变量展开；不把注释和单引号字面量当作变量。"""
    quote = ""
    for line in script.splitlines():
        escaped = False
        for char_index, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\" and quote != "'":
                escaped = True
            elif char == "#" and not quote:
                break
            elif char in ('"', "'"):
                if quote == char:
                    quote = ""
                elif not quote:
                    quote = char
            elif char == "$" and not quote and re.match(r"\$(?:[A-Za-z_]|\{|[0-9@*])", line[char_index:]):
                return True
    return False


def _validate_script_item(script: Any, explanation: Any, warnings: Any, usage: Any,
                          context: str) -> dict:
    """单个脚本的硬性校验（多脚本数组元素与单脚本共用同一套规则）。"""
    if isinstance(script, str):
        # EUID 为 bash 内建整数，仅对常见数值判断做等价引号补齐。
        script = re.sub(r'\[\s+\$EUID\s+(-(?:eq|ne|lt|le|gt|ge)\s+\d+\s*\])', r'[ "$EUID" \1', script)
    valid = (
        isinstance(script, str)
        and script.startswith("#!/usr/bin/env bash")
        and "set -euo pipefail" in script
        and len(script.splitlines()) >= 3
        and not _has_unsafe_expansion(script)
        and "解读" not in script and "分析" not in script
        and isinstance(explanation, list) and len(explanation) >= 3
        and all(isinstance(item, dict) and all(isinstance(item.get(k), str) and item[k].strip()
                for k in ("lines", "title", "detail")) for item in explanation)
        and isinstance(warnings, list) and all(isinstance(w, str) for w in warnings)
        and isinstance(usage, str))
    if not valid:
        raise AgentFormatError(f"{context}脚本结构不满足约定：" + json.dumps(
            {"script": str(script)[:200], "explanation": explanation, "usage": usage},
            ensure_ascii=False)[:400])
    header = "\n".join(script.splitlines()[:20])
    if not all(marker in header for marker in ("用途", "用法", "参数", "依赖", "适用")) or "AI" not in header:
        raise AgentFormatError(f"{context}缺少用途/用法/参数/依赖/AI审阅/适用发行版注释块：" + script[:300])
    previous: list[str] = []
    for line in script.splitlines():
        code = line.strip()
        if not code or code.startswith("#"):
            continue
        if re.search(r"(?:^|[;|&\s])(?:rm|kill|iptables)\s|systemctl\s+(?:stop|restart)\b|\s-delete\b", code):
            if not any("echo " in earlier for earlier in previous[-3:]):
                raise AgentFormatError(f"{context}影响业务操作前缺少中文 echo 提示：" + code)
        previous.append(code)
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
        # EUID 为 bash 内建整数，仅对常见数值判断做等价引号补齐。
        script = re.sub(r'\[\s+\$EUID\s+(-(?:eq|ne|lt|le|gt|ge)\s+\d+\s*\])', r'[ "$EUID" \1', script)
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
    previous: list[str] = []
    for line in script.splitlines():
        code = line.strip()
        if not code or code.startswith("#"):
            continue
        if re.search(r"(?:^|[;|&\s])(?:rm|kill|iptables)\s|systemctl\s+(?:stop|restart)\b|\s-delete\b", code):
            if not any("echo " in earlier for earlier in previous[-3:]):
                raise AgentFormatError("影响业务操作前缺少中文 echo 提示：" + json.dumps(payload, ensure_ascii=False))
        previous.append(code)
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
        return await asyncio.wait_for(produce(), timeout=120)

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
