"""知识库管理接口。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..kb.embedder import embedder
from ..schemas import DocumentList, DocumentItem, KBStats
from ..service import retriever, store

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])


@router.get("/stats", response_model=KBStats)
def kb_stats():
    s = store.stats()
    from ..crawler.scheduler import status

    return KBStats(
        **s,
        last_crawl_at=status().get("last_run_at", ""),
        embedding_enabled=embedder.available(),
    )


@router.get("/categories")
def kb_categories():
    cats = store.category_distinct()
    from ..crawler.sites import CATEGORY_CN

    return {
        "categories": [
            {"key": c, "name": CATEGORY_CN.get(c, c)} for c in cats
        ]
    }


@router.get("/documents", response_model=DocumentList)
def kb_documents(
    category: str = "",
    query: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total, rows = store.list_documents(category, query, limit, offset)
    items = [
        DocumentItem(
            id=r["id"], content_id=r["content_id"], title=r["title"],
            url=r["url"], category=r["category"], audience=r["audience"],
            source=r["source"], date=r["date"], crawled_at=r["crawled_at"],
        )
        for r in rows
    ]
    return DocumentList(total=total, items=items)


@router.post("/rebuild")
def kb_rebuild():
    retriever.rebuild()
    return {"ok": True, "chunks": len(retriever.chunks)}
