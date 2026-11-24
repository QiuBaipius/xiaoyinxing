"""上传附件文本提取：支持 txt/md/csv/pdf/docx。"""
from __future__ import annotations

import base64
import binascii
import io
from typing import Optional

MAX_CHARS = 6000


def _decode(data: str) -> bytes:
    """data 为纯 base64 或带 data: 前缀的 data URL。"""
    if "," in data and data.lstrip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        return base64.b64decode(data)
    except (binascii.Error, ValueError):
        # 可能不是 base64（例如纯文本直传），按 utf-8 返回
        return data.encode("utf-8", "ignore")


def extract_text(name: str, data: str, mime: str = "") -> Optional[str]:
    """按文件名/类型提取文本，失败返回 None。"""
    ext = (name.rsplit(".", 1)[-1].lower() if "." in name else "")
    raw = _decode(data)
    text: Optional[str] = None

    try:
        if ext in ("txt", "md", "csv", "log", "json") or "text/" in mime:
            text = raw.decode("utf-8", "ignore")
        elif ext == "pdf" or "pdf" in mime:
            text = _extract_pdf(raw)
        elif ext in ("docx",) or "word" in mime:
            text = _extract_docx(raw)
        elif ext in ("doc", "ppt", "pptx", "xls", "xlsx", "zip", "png", "jpg", "jpeg", "gif"):
            return None  # 暂不支持的类型
        else:
            text = raw.decode("utf-8", "ignore")
    except Exception:
        return None

    if not text or not text.strip():
        return None
    return text[:MAX_CHARS]


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    parts = []
    for page in reader.pages[:30]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(parts)


def _extract_docx(raw: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(raw))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)
