"""知识库持久化（SQLite）与内存索引。

- documents：文档级元数据（content_id 去重，文本变化时更新）。
- chunks：文档切片 + 向量（JSON 存储）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional

from ..config import settings

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _bigrams(s: str) -> set:
    """中文按字二元组、英文按词切分，用于短文本重叠匹配。"""
    s = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", s.lower())
    if len(s) < 2:
        return {s} if s else set()
    out = {s[i:i + 2] for i in range(len(s) - 1)}
    for w in re.findall(r"[a-zA-Z0-9]+", s):
        out.add(w)
    return out


class DocumentStore:
    def __init__(self, db_path=None):
        self.db_path = str(db_path or settings.db_path)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_id TEXT UNIQUE NOT NULL,
                    title TEXT,
                    url TEXT,
                    source TEXT,
                    category TEXT,
                    audience TEXT,
                    date TEXT,
                    text TEXT,
                    text_hash TEXT,
                    crawled_at TEXT
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id INTEGER NOT NULL,
                    chunk_index INTEGER,
                    text TEXT,
                    embedding TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_docs_category ON documents(category);
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    url TEXT UNIQUE,
                    category TEXT,
                    source TEXT,
                    description TEXT
                );
                """
            )

    # ------------------------------------------------------------ ingest
    def upsert_document(self, doc: Dict) -> Dict[str, str]:
        """按 content_id 去重；文本未变化则跳过，变化则更新。返回 {doc_id, action}。"""
        text = (doc.get("text") or "").strip()
        if not text:
            return {"action": "skip", "doc_id": ""}
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()

        with _lock, self._conn() as conn:
            row = conn.execute(
                "SELECT id, text_hash FROM documents WHERE content_id=?",
                (doc["content_id"],),
            ).fetchone()
            if row:
                if row["text_hash"] == text_hash:
                    return {"action": "unchanged", "doc_id": str(row["id"])}
                conn.execute(
                    """UPDATE documents SET title=?, url=?, source=?, category=?,
                       audience=?, date=?, text=?, text_hash=?, crawled_at=? WHERE id=?""",
                    (doc.get("title", ""), doc.get("url", ""), doc.get("source", ""),
                     doc.get("category", "general"), doc.get("audience", "all"),
                     doc.get("date", ""), text, text_hash, _now(), row["id"]),
                )
                conn.execute("DELETE FROM chunks WHERE doc_id=?", (row["id"],))
                return {"action": "updated", "doc_id": str(row["id"])}

            cur = conn.execute(
                """INSERT INTO documents
                   (content_id, title, url, source, category, audience, date, text, text_hash, crawled_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (doc["content_id"], doc.get("title", ""), doc.get("url", ""),
                 doc.get("source", ""), doc.get("category", "general"),
                 doc.get("audience", "all"), doc.get("date", ""), text, text_hash, _now()),
            )
            return {"action": "created", "doc_id": str(cur.lastrowid)}

    def add_chunks(self, doc_id: int, chunks: List[str], embeddings: List[List[float]]) -> None:
        with _lock, self._conn() as conn:
            for i, ch in enumerate(chunks):
                emb = json.dumps(embeddings[i]) if i < len(embeddings) else "[]"
                conn.execute(
                    "INSERT INTO chunks (doc_id, chunk_index, text, embedding) VALUES (?,?,?,?)",
                    (doc_id, i, ch, emb),
                )

    def delete_all(self) -> None:
        with _lock, self._conn() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM documents")

    # ------------------------------------------------------------- query
    def iter_chunks(self):
        """返回 [(chunk_id, doc_id, text, embedding_list), ...]。"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT c.id AS cid, c.doc_id, c.text, c.embedding,
                          d.title, d.url, d.source, d.category, d.audience, d.date
                   FROM chunks c JOIN documents d ON d.id = c.doc_id"""
            ).fetchall()
            out = []
            for r in rows:
                emb = json.loads(r["embedding"] or "[]")
                out.append({
                    "chunk_id": r["cid"],
                    "doc_id": r["doc_id"],
                    "text": r["text"],
                    "embedding": emb,
                    "title": r["title"],
                    "url": r["url"],
                    "source": r["source"],
                    "category": r["category"],
                    "audience": r["audience"],
                    "date": r["date"],
                })
            return out

    def list_documents(self, category: str = "", query: str = "", limit: int = 100, offset: int = 0):
        sql = "SELECT * FROM documents"
        conds, args = [], []
        if category:
            conds.append("category=?")
            args.append(category)
        if query:
            conds.append("(title LIKE ? OR text LIKE ?)")
            args.extend([f"%{query}%", f"%{query}%"])
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM documents" + ((" WHERE " + " AND ".join(conds)) if conds else ""),
                args[:-2] if conds else [],
            ).fetchone()["c"]
        return total, [dict(r) for r in rows]

    def stats(self) -> Dict:
        with self._conn() as conn:
            doc_count = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
            chunk_count = conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
            cats = conn.execute(
                "SELECT category, COUNT(*) AS c FROM documents GROUP BY category"
            ).fetchall()
        return {
            "total_documents": doc_count,
            "total_chunks": chunk_count,
            "by_category": {r["category"]: r["c"] for r in cats},
        }

    def category_distinct(self) -> List[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT category FROM documents").fetchall()
        return [r["category"] for r in rows]

    def has_document(self, content_id: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM documents WHERE content_id=?", (content_id,)).fetchone() is not None

    def get_document_by_content_id(self, content_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM documents WHERE content_id=?", (content_id,)).fetchone()
        return dict(row) if row else None

    def is_new_or_changed(self, content_id: str, text: str) -> bool:
        """文档是否为新内容或内容有变化（用于 Agent 只对新内容做判别，避免重复调用）。"""
        text_hash = hashlib.md5((text or "").encode("utf-8")).hexdigest()
        with self._conn() as conn:
            row = conn.execute("SELECT text_hash FROM documents WHERE content_id=?", (content_id,)).fetchone()
        return row is None or row["text_hash"] != text_hash

    # ------------------------------------------------------------- 文件（可下载资源）
    def add_file(self, name: str, url: str, category: str = "file", source: str = "", description: str = "") -> str:
        with _lock, self._conn() as conn:
            row = conn.execute("SELECT id FROM files WHERE url=?", (url,)).fetchone()
            if row:
                return "unchanged"
            conn.execute(
                "INSERT INTO files (name, url, category, source, description) VALUES (?,?,?,?,?)",
                (name, url, category, source, description),
            )
            return "created"

    def find_files(self, query: str, limit: int = 5) -> List[Dict]:
        """按字词二元组重叠匹配可下载文件（校历、表格、模板等）。"""
        if not query:
            return []
        q = _bigrams(query)
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM files").fetchall()
        scored = []
        for r in rows:
            hay = _bigrams((r["name"] or "") + (r["description"] or ""))
            overlap = len(q & hay)
            if overlap:
                scored.append((overlap, dict(r)))
        scored.sort(key=lambda x: -x[0])
        return [d for _, d in scored[:limit]]

    def count_files(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]


store = DocumentStore()
