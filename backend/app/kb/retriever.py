"""分级 RAG 召回核心。

三级结构：
- L0 意图路由：规则关键词把 query 映射到「部门/主题」分类（category）+ 受众（audience），
  粗粒度缩小候选空间；未命中则全库召回（不丢召回）。
- L1 双路召回：BM25（关键词精确匹配）+ 向量（语义相似），各自归一化后加权融合。
- L2 精排：按融合分排序，去重，输出 top-k，附引用来源。

召回策略要点：
- 双路召回 + 分数融合（weighted normalization），对中文短问句友好；
- 元数据过滤（category/audience）即「分级」的第一级；
- 向量不可用时自动降级为纯 BM25，保证系统可用性。
"""
from __future__ import annotations

import logging
import math
import re
from typing import Dict, List, Optional

import numpy as np

from ..crawler.sites import PROCESS_KEYWORDS
from .embedder import embedder

logger = logging.getLogger("ginkgo.retriever")

CJK = re.compile(r"[\u4e00-\u9fff]+")
WORD = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str) -> List[str]:
    """中文按字二元组、英文按词切分（无需外部分词依赖）。"""
    tokens: List[str] = []
    for m in WORD.finditer(text.lower()):
        tokens.append(m.group())
    for m in CJK.finditer(text):
        seg = m.group()
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens


class BM25Index:
    def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.corpus = corpus
        self.N = len(corpus)
        self.k1, self.b = k1, b
        self.doc_len = np.array([len(d) for d in corpus], dtype=np.float32)
        self.avgdl = float(self.doc_len.mean()) if self.N else 1.0
        self.df: Dict[str, int] = {}
        for doc in corpus:
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def score(self, query_tokens: List[str]) -> np.ndarray:
        scores = np.zeros(self.N, dtype=np.float32)
        for term in query_tokens:
            idf = self.idf(term)
            if idf == 0.0:
                continue
            for i, doc in enumerate(self.corpus):
                tf = doc.count(term)
                if tf:
                    denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                    scores[i] += idf * tf * (self.k1 + 1) / denom
        return scores


def _norm(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return scores
    lo, hi = float(scores.min()), float(scores.max())
    if hi - lo < 1e-9:
        return np.zeros_like(scores)
    return (scores - lo) / (hi - lo)


class Retriever:
    def __init__(self, store):
        self.store = store
        self.chunks: List[Dict] = []
        self.bm25: Optional[BM25Index] = None
        self.vectors: Optional[np.ndarray] = None
        self.rebuild()

    # ------------------------------------------------------------ index
    def rebuild(self) -> None:
        self.chunks = self.store.iter_chunks()
        corpus = [tokenize(c["text"]) for c in self.chunks]
        self.bm25 = BM25Index(corpus) if corpus else None

        vecs = [c["embedding"] for c in self.chunks]
        if vecs and all(v for v in vecs):
            self.vectors = np.array(vecs, dtype=np.float32)
        else:
            self.vectors = None

    # ------------------------------------------------------ L0 路由
    def classify(self, query: str) -> str:
        """规则路由：返回最匹配的 category，未命中返回空串（全库召回）。

        以「关键词长度」作为权重（更长的词更具体，如“奖学金”应优先于泛化的“申请”），
        避免通用词（申请/办理/证明）抢占更具体的领域词。
        """
        best, best_score = "", 0
        for cat, kws in PROCESS_KEYWORDS.items():
            score = sum(len(kw) for kw in kws if kw in query)
            if score > best_score:
                best, best_score = cat, score
        return best if best_score > 0 else ""

    # ------------------------------------------------------ L1/L2 召回
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        category: str = "",
        audience: str = "",
    ) -> List[Dict]:
        if not self.chunks:
            return []

        q_tokens = tokenize(query)
        n = len(self.chunks)

        # 双路召回
        bm = self.bm25.score(q_tokens) if (self.bm25 and q_tokens) else np.zeros(n, dtype=np.float32)
        vec = np.zeros(n, dtype=np.float32)
        if self.vectors is not None:
            try:
                qv = embedder.embed([query])
                if qv:
                    q = np.asarray(qv[0], dtype=np.float32)
                    q = q / (np.linalg.norm(q) + 1e-9)
                    v = self.vectors / (np.linalg.norm(self.vectors, axis=1, keepdims=True) + 1e-9)
                    vec = (v @ q).astype(np.float32)
            except Exception as e:  # noqa: BLE001
                logger.warning("向量召回失败，降级 BM25: %s", e)

        # 融合（向量可用时 6:4 偏向语义，否则纯 BM25）
        if self.vectors is not None and vec.any():
            fused = 0.6 * _norm(vec) + 0.4 * _norm(bm)
        else:
            fused = _norm(bm)

        # L0 元数据过滤
        mask = np.ones(n, dtype=bool)
        if category:
            mask &= np.array([c["category"] == category for c in self.chunks])
        if audience:
            mask &= np.array([c["audience"] in ("all", audience) for c in self.chunks])
        if not mask.any():
            # 过滤后为空则退化为全库
            mask[:] = True

        fused[~mask] = -np.inf
        order = np.argsort(-fused)
        results: List[Dict] = []
        seen_docs = set()
        for idx in order:
            if len(results) >= top_k:
                break
            score = float(fused[idx])
            if not np.isfinite(score):
                continue  # 跳过被过滤（-inf）的项
            c = self.chunks[int(idx)]
            if c["doc_id"] in seen_docs:
                continue
            seen_docs.add(c["doc_id"])
            results.append({
                "title": c["title"],
                "url": c["url"],
                "category": c["category"],
                "audience": c["audience"],
                "date": c["date"],
                "source": c["source"],
                "text": c["text"],
                "score": round(score, 4),
            })
        return results
