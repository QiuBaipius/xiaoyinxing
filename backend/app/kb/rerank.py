"""检索结果相关性边界判定（LLM 精排）：只保留与用户问题「直接相关」的资料。

对应分级 RAG 的 L2 精排层——召回是「宁可多召」，精排是「精确把关」。
对文档切片与可下载文件统一适用。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List

from ..llm import client

logger = logging.getLogger("ginkgo.rerank")

SYSTEM = (
    "你是检索结果的相关性裁判。判断每条候选资料是否与用户问题【直接相关】。\n"
    "直接相关：该资料能直接回答或帮助解决用户的具体问题。\n"
    "不相关：仅主题相近或形近、但无法回答用户问题。务必严格区分形近术语，例如：\n"
    "- 问「成绩证明/成绩单」时，「成绩评定」「评分办法」「考试评定单」是不同主题，判为不相关；\n"
    "- 问「休学/复学」「转专业」「在读证明」时，互相都不是同一件事，不能混入。\n"
    "原则：宁可少给、不要多给，拿不准的一律判为不相关。\n"
    "示例：\n"
    "用户问题：如何办理成绩证明？\n"
    "候选：[1] 成绩证明办理流程 [2] 本科生成绩评定相关说明 [3] 休学与复学办理流程\n"
    '正确输出：{"relevant": [1], "irrelevant": [2, 3]}（「成绩评定」是评分规则，不是「成绩证明」办理，判为不相关）\n'
    '只输出 JSON（不要代码块、不要解释）：{"relevant": [相关项编号...], "irrelevant": [不相关项编号...]}\n'
    "编号为候选资料前缀的 [数字]。"
)

FALLBACK_THRESHOLD = 0.5


def _parse(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def rerank(query: str, items: List[Dict], on_fail: str = "score") -> List[int]:
    """返回「应保留」的 items 索引列表（保持原顺序）。

    items 每项需含 title / text（用于判断），可含 score（用于降级阈值过滤）。
    on_fail: LLM 判定失败时的策略 —— "score" 按召回分数阈值过滤；"none" 全部不显示。
    """
    if not items:
        return []
    if len(items) == 1:
        return [0]

    lines = []
    for i, it in enumerate(items, 1):
        snippet = ((it.get("text") or "") or (it.get("title") or ""))[:200].replace("\n", " ")
        lines.append(f"[{i}] {it.get('title', '')}：{snippet}")
    prompt = f"用户问题：{query}\n\n候选资料：\n" + "\n".join(lines) + "\n\n请判断并输出 JSON。"

    try:
        raw = client.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0, max_tokens=300,
        )
        data = _parse(raw)
        if data and "relevant" in data:
            kept = []
            for x in data.get("relevant", []):
                try:
                    idx = int(x)
                except (ValueError, TypeError):
                    continue
                if 1 <= idx <= len(items):
                    kept.append(idx - 1)
            # 信任 LLM 判定：relevant 为空表示「全部不相关」，也返回空列表
            return kept
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 精排失败，降级为分数过滤：%s", e)

    # 降级：LLM 不可用时的策略
    if on_fail == "none":
        return []
    # 按 score 阈值过滤（score 为召回融合分，越高越相关）
    scored = [it.get("score") for it in items]
    if all(isinstance(s, (int, float)) for s in scored):
        kept = [i for i, s in enumerate(scored) if s >= FALLBACK_THRESHOLD]
        if kept:
            return kept
        # 全部低于阈值时，至少保留最高分一项，避免空结果
        return [max(range(len(scored)), key=lambda i: scored[i])]
    return list(range(len(items)))
