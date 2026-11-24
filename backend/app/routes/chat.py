"""对话接口：分级 RAG + GLM（含模型降级、多模态图片、文件问答、可下载文件）。"""
from __future__ import annotations

import json
import time
from typing import Dict, List

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..config import settings
from ..crawler.sites import CATEGORY_CN
from ..fileparse import extract_text
from ..kb.store import store
from ..llm import GLMError, client
from ..schemas import ChatRequest, ChatResponse, FileRef, SourceRef
from ..service import retriever

router = APIRouter(prefix="/api", tags=["chat"])

SYSTEM_PROMPT = (
    "你是「小银杏」，东北财经大学的官方 AI 校园助手。你的形象是一枚金黄色的银杏叶，"
    "亲切、温暖、靠谱，寓意“坚韧沉着”。\n"
    "你的职责是帮助师生解答：校园政策制度、课程安排与选课、办事流程与材料审批查询、"
    "考试安排、奖助贷、毕业学位等校园问题。\n"
    "回答要求：\n"
    "1. 优先依据给定的【参考资料】回答，不要编造政策或流程细节；\n"
    "2. 回答简洁清晰，条理分明，适当使用要点列表；\n"
    "3. 引用资料时在句末标注来源编号，如 [1][2]；\n"
    "4. 若资料不足以回答，如实说明，并给出到哪个部门/网站查询的建议；\n"
    "5. 如果用户索要文件/附件（如校历、表格、模板），请从【可下载文件】中找到对应文件，"
    "给出链接并说明“点击链接即可下载/查看”；若没有对应文件，如实告知并建议到哪个栏目下载；\n"
    "6. 与校园无关的问题可正常友好回答，但不要偏离“校园助手”定位。"
)


def _extract_attachments(attachments) -> str:
    parts = []
    for f in attachments:
        try:
            txt = extract_text(f.name, f.data, f.mime)
        except Exception:  # noqa: BLE001
            txt = None
        if txt:
            parts.append(f"【用户上传文件：{f.name}】\n{txt}")
    return "\n\n".join(parts)


def _find_files(query: str) -> List[FileRef]:
    return [
        FileRef(name=f["name"], url=f["url"], description=f.get("description", ""))
        for f in store.find_files(query, limit=5)
    ]


def _build_context(query: str, category: str, audience: str, found_files: List[FileRef]):
    """分级 RAG：L0 路由 + L1/L2 召回，返回上下文与来源。"""
    route_cat = category or retriever.classify(query)
    hits = retriever.retrieve(
        query,
        top_k=settings.top_k,
        category=route_cat,
        audience=audience or "",
    )
    if not hits and route_cat:
        # 分级过滤无结果时，退回全库召回
        hits = retriever.retrieve(query, top_k=settings.top_k)

    context_blocks = []
    sources: List[SourceRef] = []
    for i, h in enumerate(hits, start=1):
        context_blocks.append(
            f"[{i}] {h['title']}\n来源：{h['source']}（{CATEGORY_CN.get(h['category'], h['category'])}）\n"
            f"内容：{h['text']}\n"
        )
        sources.append(SourceRef(
            title=h["title"], url=h["url"], category=h["category"],
            audience=h["audience"], date=h["date"], score=round(h["score"], 4),
        ))

    if found_files:
        blocks = "\n".join(
            f"- {f.name}：{f.url}" + (f"（{f.description}）" if f.description else "")
            for f in found_files
        )
        context_blocks.append("【可下载文件】\n" + blocks + "\n")

    context = "\n".join(context_blocks)
    return route_cat, context, sources


def _build_messages(req: ChatRequest, user_message: str, found_files: List[FileRef]):
    messages: List[Dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if req.use_rag:
        route_cat, context, sources = _build_context(user_message, req.category or "", req.audience or "", found_files)
        if context:
            messages.append({
                "role": "system",
                "content": "【参考资料】（来自东北财经大学官方渠道，请优先据此作答）：\n" + context,
            })
    else:
        route_cat, sources = "", []

    for m in req.history[-10:]:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": user_message})
    return messages, route_cat, sources


@router.post("/chat")
async def chat(req: ChatRequest):
    t0 = time.time()

    # 1) 用户上传文件的文本提取，拼入提问
    user_message = req.message
    extra = _extract_attachments(req.files)
    if extra:
        user_message = req.message + "\n\n" + extra

    # 2) 可下载文件检索（校历等）
    found_files = _find_files(req.message) if req.use_rag else []

    # 3) 组装消息与 RAG 上下文
    messages, route_cat, sources = _build_messages(req, user_message, found_files)
    images = req.images or []

    def _resp(answer, model):
        return ChatResponse(
            answer=answer, sources=sources, files=found_files, category=route_cat,
            latency_ms=int((time.time() - t0) * 1000), model=model,
        )

    if not req.stream:
        try:
            answer = client.chat(messages, images=images)
        except GLMError as e:
            return _resp(f"抱歉，暂时无法回答：{e}", client.last_model)
        except Exception as e:  # noqa: BLE001
            return _resp(f"抱歉，服务出现异常：{e}", client.last_model)
        return _resp(answer, client.last_model)

    def gen():
        meta = json.dumps({
            "type": "meta", "category": route_cat,
            "sources": [s.model_dump() for s in sources],
            "files": [f.model_dump() for f in found_files],
            "model": client.models[0] if client.models else "",
        }, ensure_ascii=False)
        yield f"data: {meta}\n\n"
        try:
            for delta in client.chat_stream(messages, images=images):
                yield f"data: {json.dumps({'type': 'delta', 'content': delta}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")
