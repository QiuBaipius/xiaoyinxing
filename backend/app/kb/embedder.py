"""文本向量化封装：优先走智谱 embedding-3，失败自动降级为 BM25-only。"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..llm import client

logger = logging.getLogger("ginkgo.embedder")


class Embedder:
    def __init__(self):
        self._available: Optional[bool] = None  # None=未探测

    def available(self) -> bool:
        if self._available is None:
            try:
                client.embed(["探针"])
                self._available = True
            except Exception as e:  # noqa: BLE001
                logger.warning("向量服务不可用，降级为 BM25 召回: %s", e)
                self._available = False
        return self._available

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not self.available():
            return []
        try:
            return client.embed(texts)
        except Exception as e:  # noqa: BLE001
            logger.warning("向量化失败，降级为 BM25: %s", e)
            self._available = False
            return []


embedder = Embedder()
