"""OpenAI 兼容客户端；错误摘要统一脱敏，429 最多重试一次。"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

import httpx

PRESETS = {
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen3-8B"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "custom": {"base_url": "", "model": ""},
}


class LLMError(Exception):
    """可安全展示给用户的模型调用错误。"""


class LLMClient:
    """异步 HTTP 客户端，供后续生成与流式分析复用。"""

    def __init__(self, settings: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = str(settings.get("base_url", "")).rstrip("/")
        self.model = str(settings.get("model", ""))
        self._key = str(settings.get("api_key", ""))
        self._transport = transport

    def _safe_error(self, text: str) -> str:
        if self._key:
            text = text.replace(self._key, "[密钥已隐藏]")
        return text[:500] + "；请检查网络/密钥/模型名"

    def _adapt_request(self, body: dict[str, Any]) -> dict[str, Any]:
        """官方 GLM-5.3 始终思考，使用轻量推理并保留正文预算。"""
        if (urlsplit(self.base_url).hostname == "open.bigmodel.cn"
                and self.model.casefold().startswith("glm-5.3")):
            body.update(thinking={"type": "enabled"}, reasoning_effort="low")
            body["max_tokens"] = max(int(body.get("max_tokens", 4096)), 4096)
        return body

    def _client(self, timeout: float) -> httpx.AsyncClient:
        if not self._key:
            raise LLMError("尚未配置 API key，请前往设置页保存密钥")
        if not self.base_url.startswith(("http://", "https://")) or not self.model:
            raise LLMError("请在设置页填写有效的 base_url 与模型名")
        return httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=httpx.Timeout(timeout), transport=self._transport,
        )

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.2,
                   timeout: float = 120, max_tokens: int | None = None) -> dict[str, Any]:
        """返回 content/model；失败返回 ok=false 的脱敏错误对象。"""
        body: dict[str, Any] = {"model": self.model, "messages": messages,
                                "temperature": temperature, "stream": False}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        self._adapt_request(body)
        try:
            async with self._client(timeout) as client:
                for attempt in range(2):
                    response = await client.post(f"{self.base_url}/chat/completions", json=body)
                    if response.status_code == 429 and attempt == 0:
                        await asyncio.sleep(2)
                        continue
                    if response.is_error:
                        raise LLMError(self._safe_error(f"HTTP {response.status_code}：{response.text}"))
                    payload = response.json()
                    content = payload["choices"][0]["message"]["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("content 不是文本")
                    return {"content": content, "model": payload.get("model", self.model)}
        except LLMError as exc:
            return {"ok": False, "error": str(exc)}
        except httpx.TimeoutException:
            return {"ok": False, "error": "请求超时；请检查网络/密钥/模型名"}
        except httpx.HTTPError:
            return {"ok": False, "error": "连接模型服务失败；请检查网络/密钥/模型名"}
        except (ValueError, KeyError, IndexError, TypeError):
            return {"ok": False, "error": "模型响应格式无效；请检查模型名与兼容协议"}
        return {"ok": False, "error": "模型服务未返回结果"}

    async def chat_stream(self, messages: list[dict[str, str]], temperature: float = 0.3,
                          timeout: float = 300, on_reasoning=None) -> AsyncIterator[str]:
        """逐段返回文本，失败抛出可脱敏的 LLMError（供 SSE 层捕获）。

        on_reasoning：可选同步回调；思考型模型（如 GLM-5.3）的 reasoning_content
        分片经它实时转交，不混入正文。
        """
        body = {"model": self.model, "messages": messages, "temperature": temperature, "stream": True}
        self._adapt_request(body)
        try:
            async with self._client(timeout) as client:
                for attempt in range(2):
                    async with client.stream("POST", f"{self.base_url}/chat/completions", json=body) as response:
                        if response.status_code == 429 and attempt == 0:
                            await response.aread()
                        else:
                            if response.is_error:
                                raw = (await response.aread()).decode("utf-8", errors="replace")
                                raise LLMError(self._safe_error(f"HTTP {response.status_code}：{raw}"))
                            async for line in response.aiter_lines():
                                if not line.startswith("data:"):
                                    continue
                                value = line[5:].strip()
                                if value == "[DONE]":
                                    return
                                if not value:
                                    continue
                                payload = json.loads(value)
                                choices = payload.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                                    if isinstance(reasoning, str) and reasoning and on_reasoning:
                                        on_reasoning(reasoning)
                                    content = delta.get("content")
                                    if isinstance(content, str) and content:
                                        yield content
                            return
                    await asyncio.sleep(2)
        except httpx.TimeoutException as exc:
            raise LLMError("请求超时；请检查网络/密钥/模型名") from None
        except httpx.HTTPError:
            raise LLMError("连接模型服务失败；请检查网络/密钥/模型名") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("流式响应格式无效；请检查兼容协议") from None


async def stream_with_reasoning(client: LLMClient, messages: list[dict[str, str]], *,
                                temperature: float, timeout: float) -> AsyncIterator[tuple[str, str]]:
    """把 chat_stream 的正文与思考分片统一为 ("delta"|"thinking", text) 事件流。

    思考分片经任务泵与正文交错产出，保证长思考阶段 UI 仍有实时输出；消费者
    提前退出时泵任务在 finally 中取消。错误以原异常抛出（LLMError 等）。
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for chunk in client.chat_stream(messages, temperature=temperature, timeout=timeout,
                                                  on_reasoning=lambda piece: queue.put_nowait(("thinking", piece))):
                queue.put_nowait(("delta", chunk))
        except BaseException as exc:  # 转交消费者后由其决定错误事件形态
            queue.put_nowait(("error", exc))
        else:
            queue.put_nowait(("done", None))

    task = asyncio.create_task(pump())
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "done":
                return
            if kind == "error":
                raise payload
            yield kind, payload
    finally:
        if not task.done():
            task.cancel()
