"""核心编排：知识库入库、检索器实例、内置知识初始化。"""
from __future__ import annotations

import logging
from typing import Dict, List

from .kb.chunker import chunk_text
from .kb.embedder import embedder
from .kb.retriever import Retriever
from .kb.store import store

logger = logging.getLogger("ginkgo.service")

retriever = Retriever(store)


def ingest_documents(docs: List[Dict]) -> int:
    """文档入库：去重 -> 分块 -> 向量化 -> 落库，返回新增/更新数量。"""
    changed = 0
    for doc in docs:
        res = store.upsert_document(doc)
        action = res["action"]
        if action in ("created", "updated"):
            doc_id = int(res["doc_id"])
            chunks = chunk_text(doc.get("text", ""))
            embeddings = embedder.embed(chunks) if embedder.available() else []
            store.add_chunks(doc_id, chunks, embeddings)
            changed += 1
    if changed:
        retriever.rebuild()
    return changed


def ingest_files(files: List[Dict]) -> int:
    """可下载文件入库，返回新增数量。"""
    n = 0
    for f in files:
        if store.add_file(
            f.get("name", ""), f.get("url", ""), f.get("category", "file"),
            f.get("source", ""), f.get("description", ""),
        ) == "created":
            n += 1
    return n


def ingest_all(docs: List[Dict]) -> int:
    """采集入库（文档 + 可下载文件），返回新增/更新总数。"""
    n = ingest_documents(docs)
    try:
        from .crawler.base import crawl_files

        n += ingest_files(crawl_files())
    except Exception as e:  # noqa: BLE001
        logger.warning("文件采集失败: %s", e)
    return n


def seed_if_empty() -> None:
    """首次启动时写入内置参考知识，保证系统离线可用。"""
    if store.stats()["total_documents"] > 0:
        return
    from .seed import SEED_DOCUMENTS

    n = ingest_documents(SEED_DOCUMENTS)
    logger.info("内置参考知识初始化完成，共 %s 篇", n)


def seed_files_if_empty() -> None:
    """首次启动时写入内置可下载文件（校历等）。"""
    if store.count_files() > 0:
        return
    from .seed import SEED_FILES

    ingest_files(SEED_FILES)
    logger.info("内置可下载文件初始化完成，共 %s 个", len(SEED_FILES))
