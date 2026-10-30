"""运维问答智能体：SSE 对话流与会话管理。"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.engine import run_assistant
from app.assistant import service
from app.llm.provider import LLMClient, LLMError
from app.llm.routes import effective_settings

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

ASSISTANT_SYSTEM_PROMPT = """你是 OpsMate 内置的运维问答助手，服务一名在 Windows 工作机上管理 Linux 服务器的运维工程师。

【回答纪律】
1. 涉及具体命令用法或软件配置参数时，先用工具检索本地知识库核实再回答，不要凭记忆编造参数。
   检索词 q 必须是单个简短关键词（如 reload、nginx、磁盘、压缩），带空格的整句会检索不到；
   一个词不够就分多次检索不同的关键词。
2. 只依据工具检索结果与对话上下文回答；本地资料没有的内容，明确说明"本地知识库未收录"，并建议查阅官方文档，不要编造。
   声称"未收录"之前必须先实际检索过该关键词；列举或对比多个命令时，每个都应检索并逐一加来源标记。
3. 来源标记（重要）：凡引用本地知识命中的内容，必须在对应内容后紧跟来源标记，前端会渲染为可点击链接：
   - 命令文档来源（search_commands 返回的条目，如 tar、df）：【命令：tar】
   - 配置速查来源（search_kb 返回的条目，无论启停命令还是配置参数，都必须用这种）：
     【配置：软件/条目名】，例：【配置：nginx/nginx -s reload】【配置：nginx/worker_processes】
   - 标记中的名称必须与检索结果里的 name 字段完全一致；配置速查条目绝不能用【命令：】标记。
4. 用户追问时结合上下文回答，不要让用户重复背景；闲聊或无需检索的问题可直接回答。
5. 全文中文，直接输出 markdown 正文（可用代码块、列表、小节标题），不要输出 JSON 或协议包装，不要输出开场白与结尾客套。"""


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: int | None = None


def _event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/sessions")
def sessions() -> dict[str, Any]:
    """倒序会话列表。"""
    service.init_assistant()
    return {"items": service.list_sessions()}


@router.get("/sessions/{session_id}")
def session_detail(session_id: int) -> dict[str, Any]:
    """回看会话全部消息；tool 行 content 为 JSON 轨迹字符串。"""
    service.init_assistant()
    try:
        return {"messages": service.get_messages(session_id)}
    except service.SessionNotFound:
        raise HTTPException(status_code=404, detail="会话不存在") from None


@router.delete("/sessions/{session_id}")
def session_delete(session_id: int) -> dict[str, Any]:
    """删除会话及全部消息。"""
    service.init_assistant()
    if not service.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.post("/chat")
async def chat(body: ChatBody) -> StreamingResponse:
    """SSE：过程事件 → delta 逐段 → done（含 session_id）；失败不落半份。"""
    service.init_assistant()
    settings = effective_settings()

    async def error_stream(message: str) -> AsyncIterator[str]:
        yield _event({"error": message})

    if not settings.get("api_key"):
        return StreamingResponse(error_stream("未配置模型密钥，请先前往设置页保存并启用"),
                                 media_type="text/event-stream")
    try:
        history = service.conversation_history(body.session_id) if body.session_id else []
    except service.SessionNotFound:
        return StreamingResponse(error_stream("会话不存在或已删除，请点击新建对话"),
                                 media_type="text/event-stream")
    conversation = [*history, {"role": "user", "content": body.message}]

    async def stream() -> AsyncIterator[str]:
        steps: list[dict[str, Any]] = []
        answer = ""
        try:
            async for event in run_assistant(LLMClient(settings), ASSISTANT_SYSTEM_PROMPT, conversation):
                if "final" in event:
                    answer = event["final"]
                    continue
                if "tool" in event:
                    steps.append({"tool": event["tool"], "args": event["args"],
                                  "result": event["result"]})
                yield _event(event)
            if not answer:
                raise LLMError("模型未返回回答")
            session_id = await asyncio.to_thread(
                service.save_turn, body.session_id, body.message, steps, answer, settings["model"])
            yield _event({"done": True, "session_id": session_id})
        except LLMError as exc:
            yield _event({"error": str(exc)})
        except Exception as exc:  # 意外中断也不打断 SSE，转成明确错误事件
            yield _event({"error": "回答生成失败：" + str(exc)[:200]})

    return StreamingResponse(stream(), media_type="text/event-stream")
