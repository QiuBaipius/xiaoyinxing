"""智谱 GLM 大模型客户端：文本对话、流式、多模态（图片）、文本向量化。

- 模型降级：主模型限流（429）/不可用（404/5xx）时，自动按 GLM_MODELS 顺序切换下一个；
  401（密钥错误）视为致命错误，不降级。
- 每个模型只尝试一次，快速失败并切换，避免长时间等待。
"""
from __future__ import annotations

import json
from typing import Dict, Iterator, List, Optional

import requests

from .config import settings

CHAT_PATH = "/chat/completions"
EMBED_PATH = "/embeddings"

# 可降级重试的状态码（不含 401，密钥错误不降级）
_FALLBACK_CODES = (404, 429, 500, 502, 503, 504)


class GLMError(Exception):
    pass


def _friendly_error(status: int, body: str) -> str:
    try:
        msg = json.loads(body).get("error", {}).get("message", "")
    except Exception:  # noqa: BLE001
        msg = ""
    if status == 429:
        return "模型当前访问量过大，请稍后重试" + (f"（{msg}）" if msg else "")
    if status == 401:
        return "API Key 无效或已过期，请检查 backend/.env 中的 GLM_API_KEY"
    if status == 404:
        return "模型不存在或不可用，请检查 GLM_MODELS 配置"
    return f"GLM 接口错误 {status}" + (f"：{msg}" if msg else "")


class GLMClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.glm_api_key
        self.base_url = (base_url or settings.glm_base_url).rstrip("/")
        self.models: List[str] = settings.glm_models or [settings.glm_model]
        self.vision_model = settings.glm_vision_model
        self.embed_model = settings.embedding_model
        self.last_model = self.models[0]  # 实际命中的模型

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, model, messages, temperature, max_tokens, stream):
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    def _post(self, payload, timeout, stream=False):
        return requests.post(
            self.base_url + CHAT_PATH, headers=self._headers(),
            json=payload, timeout=timeout, stream=stream,
        )

    @staticmethod
    def _net_err(e: Exception) -> GLMError:
        return GLMError(f"网络异常（{e.__class__.__name__}），已尝试切换模型")

    def _check_key(self):
        if not self.api_key:
            raise GLMError("未配置 GLM_API_KEY，请在 backend/.env 中填写")

    # ------------------------------------------------------------ 非流式
    def chat(self, messages, temperature=0.3, max_tokens=2048, images=None) -> str:
        self._check_key()
        if images:
            return self._chat_vision(messages, images, temperature, max_tokens)
        return self._chat_fallback(messages, temperature, max_tokens)

    def _chat_fallback(self, messages, temperature, max_tokens) -> str:
        last_err: Optional[GLMError] = None
        for model in self.models:
            try:
                resp = self._post(self._payload(model, messages, temperature, max_tokens, False), timeout=25)
            except requests.RequestException as e:
                last_err = self._net_err(e)
                continue  # 网络超时/连接失败 → 切换下一个模型
            if resp.status_code == 200:
                self.last_model = model
                return resp.json()["choices"][0]["message"]["content"]
            err = GLMError(_friendly_error(resp.status_code, resp.text[:400]))
            if resp.status_code in _FALLBACK_CODES:
                last_err = err
                continue
            raise err  # 401 等致命错误直接抛
        raise last_err or GLMError("所有模型均不可用")

    def _chat_vision(self, messages, images, temperature, max_tokens) -> str:
        msgs = self._with_images(messages, images)
        resp = self._post(self._payload(self.vision_model, msgs, temperature, max_tokens, False), timeout=90)
        if resp.status_code != 200:
            raise GLMError(_friendly_error(resp.status_code, resp.text[:400]))
        self.last_model = self.vision_model
        return resp.json()["choices"][0]["message"]["content"]

    # ------------------------------------------------------------ 流式
    def chat_stream(self, messages, temperature=0.3, max_tokens=2048, images=None) -> Iterator[str]:
        self._check_key()
        if images:
            msgs = self._with_images(messages, images)
            yield from self._stream_model(self.vision_model, msgs, temperature, max_tokens)
            return
        yield from self._stream_fallback(messages, temperature, max_tokens)

    def _stream_fallback(self, messages, temperature, max_tokens) -> Iterator[str]:
        last_err: Optional[GLMError] = None
        for model in self.models:
            try:
                resp = self._post(self._payload(model, messages, temperature, max_tokens, True), timeout=(10, 60), stream=True)
            except requests.RequestException as e:
                last_err = self._net_err(e)
                continue
            if resp.status_code != 200:
                err = GLMError(_friendly_error(resp.status_code, resp.text[:400]))
                if resp.status_code in _FALLBACK_CODES:
                    last_err = err
                    continue
                raise err
            self.last_model = model
            yield from self._iter_stream(resp)
            return
        raise last_err or GLMError("所有模型均不可用")

    def _stream_model(self, model, messages, temperature, max_tokens) -> Iterator[str]:
        resp = self._post(self._payload(model, messages, temperature, max_tokens, True), timeout=(10, 60), stream=True)
        if resp.status_code != 200:
            raise GLMError(_friendly_error(resp.status_code, resp.text[:400]))
        self.last_model = model
        yield from self._iter_stream(resp)

    def _iter_stream(self, resp) -> Iterator[str]:
        with resp:
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data:"):
                    continue
                data_str = raw[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content

    # ------------------------------------------------------------ 多模态消息
    @staticmethod
    def _with_images(messages, images) -> List[Dict]:
        """把最后一条 user 消息转成多模态 content 格式。"""
        msgs = [dict(m) for m in messages]
        last = msgs[-1]
        content = [{"type": "text", "text": last.get("content", "")}]
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": img}})
        msgs[-1] = {"role": last.get("role", "user"), "content": content}
        return msgs

    # ------------------------------------------------------------ embedding
    def embed(self, texts: List[str]) -> List[List[float]]:
        self._check_key()
        if not texts:
            return []
        payload = {"model": self.embed_model, "input": texts}
        resp = requests.post(
            self.base_url + EMBED_PATH, headers=self._headers(),
            json=payload, timeout=60,
        )
        if resp.status_code != 200:
            raise GLMError(_friendly_error(resp.status_code, resp.text[:300]))
        data = resp.json()
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        return [it["embedding"] for it in items]


client = GLMClient()
