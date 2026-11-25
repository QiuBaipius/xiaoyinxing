"""全局配置：从 .env 加载，集中管理。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
load_dotenv(BASE_DIR / ".env")


def _bool(v: str, default: bool = False) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on") if v else default


def _resolve_dir(raw: str) -> Path:
    """相对路径一律相对 backend/ 解析，绝对路径原样返回。"""
    p = Path(raw)
    return p if p.is_absolute() else BASE_DIR / p


class Settings:
    # ---- 大模型 ----
    glm_api_key: str = os.getenv("GLM_API_KEY", "30da5e4c06fc47bcbe420399d096b024.JHpfCCWVvrcD6bO5")
    glm_model: str = os.getenv("GLM_MODEL", "glm-4.7-flash")
    # 模型降级链：按顺序尝试，遇到限流/404 自动切换下一个（401 视为密钥错误，不降级）
    glm_models: list = [m.strip() for m in os.getenv("GLM_MODELS", "glm-4.7-flash,glm-4-flash").split(",") if m.strip()]
    # 多模态（图片理解）模型
    glm_vision_model: str = os.getenv("GLM_VISION_MODEL", "glm-4.6v-flash")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "embedding-3")
    glm_base_url: str = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

    # ---- 知识库 ----
    data_dir: Path = _resolve_dir(os.getenv("DATA_DIR", "data"))
    db_path: Path = data_dir / "kb.db"

    # ---- 采集 ----
    crawl_interval_hours: float = float(os.getenv("CRAWL_INTERVAL_HOURS", "6"))
    # 上班时段定时采集（24 小时制，如 9、15 点各一次）；为空则按 crawl_interval_hours 间隔
    collect_hours: list = [int(h) for h in os.getenv("COLLECT_HOURS", "9,15").split(",") if h.strip().isdigit()]
    auto_crawl: bool = _bool(os.getenv("AUTO_CRAWL", "1"), True)

    # ---- 召回 ----
    top_k: int = int(os.getenv("TOP_K", "5"))
    candidate_k: int = int(os.getenv("CANDIDATE_K", "20"))
    enable_rerank: bool = _bool(os.getenv("ENABLE_RERANK", "0"), False)

    # ---- 服务 ----
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    @property
    def has_api_key(self) -> bool:
        return bool(self.glm_api_key)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
