"""API 数据模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = "user"  # user / assistant / system
    content: str


class Attachment(BaseModel):
    """用户上传的文件（base64 + 类型）。"""
    name: str = ""
    data: str = ""  # base64（或纯文本）
    mime: str = ""


class FileRef(BaseModel):
    """可下载文件（校历、表格等）。"""
    name: str
    url: str
    description: str = ""


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = Field(default_factory=list)
    stream: bool = True
    session_id: Optional[str] = None
    use_rag: bool = True
    # 可选：指定分类路由（分级 RAG 的 L0 层），不传则自动识别
    category: Optional[str] = None
    audience: Optional[str] = None  # student / teacher
    # 多模态输入
    images: List[str] = Field(default_factory=list)  # 图片 data URL（data:image/...;base64,...）
    files: List[Attachment] = Field(default_factory=list)  # 上传的文件


class SourceRef(BaseModel):
    title: str
    url: str = ""
    category: str = ""
    audience: str = ""
    date: str = ""
    score: float = 0.0


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceRef] = Field(default_factory=list)
    files: List[FileRef] = Field(default_factory=list)
    category: str = ""
    latency_ms: int = 0
    model: str = ""


class KBStats(BaseModel):
    total_documents: int = 0
    total_chunks: int = 0
    by_category: Dict[str, int] = Field(default_factory=dict)
    last_crawl_at: str = ""
    embedding_enabled: bool = False


class CrawlStatus(BaseModel):
    running: bool = False
    last_run_at: str = ""
    last_result: Dict[str, Any] = Field(default_factory=dict)
    next_run_at: str = ""


class DocumentItem(BaseModel):
    id: int
    content_id: str
    title: str
    url: str
    category: str
    audience: str
    source: str
    date: str
    crawled_at: str


class DocumentList(BaseModel):
    total: int
    items: List[DocumentItem]
