"""文本分块：按段落/句子边界切分，保证语义完整性与召回粒度。"""
from __future__ import annotations

import re
from typing import List


def split_sentences(text: str) -> List[str]:
    # 按中文句末标点、换行切句
    parts = re.split(r"(?<=[。！？；!?;\n])", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, max_len: int = 480, overlap: int = 80) -> List[str]:
    """把长文本切成带重叠的语义块。"""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    sentences = split_sentences(text)
    chunks: List[str] = []
    buf = ""
    for s in sentences:
        if len(buf) + len(s) <= max_len:
            buf += s
        else:
            if buf:
                chunks.append(buf.strip())
            # 保留重叠尾，衔接上下文
            if s:
                tail = buf[-overlap:] if len(buf) > overlap else buf
                buf = tail + s
            else:
                buf = ""
    if buf.strip():
        chunks.append(buf.strip())

    # 兜底：若某句超长，硬切
    final: List[str] = []
    for c in chunks:
        if len(c) <= max_len:
            final.append(c)
        else:
            for i in range(0, len(c), max_len - overlap):
                final.append(c[i:i + max_len])
    return [c for c in final if c]
