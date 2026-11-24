"""小银杏 AI 助手后端应用入口。"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import BASE_DIR, settings
from .crawler.agent import agent as collect_agent
from .routes import chat, crawl, kb
from .service import retriever, seed_files_if_empty, seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ginkgo")

app = FastAPI(
    title="小银杏 · 东北财经大学 AI 校园助手",
    description="面向 AI 高校建设场景的对话式助手：校园政策、课程安排、业务流程、材料审批查询。",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(kb.router)
app.include_router(crawl.router)


@app.on_event("startup")
def on_startup():
    seed_if_empty()
    seed_files_if_empty()
    if settings.auto_crawl:
        from .crawler import scheduler

        scheduler.start(collect_agent.run)
        logger.info("采集 Agent 已启动，上班时段每天两次自动采集")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": "小银杏",
        "model": settings.glm_model,
        "api_key_configured": settings.has_api_key,
        "chunks": len(retriever.chunks),
    }


@app.get("/api/suggestions")
def suggestions():
    return {
        "items": [
            "如何办理成绩证明？",
            "补考和缓考怎么申请？",
            "怎么办理休学复学？",
            "奖学金怎么申请？",
            "图书馆研讨间如何预约？",
            "四六级考试怎么报名？",
        ]
    }


@app.get("/api/meta")
def meta():
    return {
        "app": "小银杏",
        "school": "东北财经大学",
        "model": settings.glm_model,
        "theme": {
            "primary": "#FFC53D",
            "deep": "#F5A623",
            "green": "#3E9A5B",
            "bg": "#FFF9E8",
        },
    }


# 托管前端（电脑版 / 手机版响应式页面）
# 用显式路由而非根路径挂载 StaticFiles，避免静态挂载拦截 /api/* 的 POST 请求（导致 405）。
_web_dir = BASE_DIR.parent / "web"
if _web_dir.exists():
    @app.get("/", include_in_schema=False)
    def _index():
        return FileResponse(_web_dir / "index.html")

    @app.get("/mascot.jpg", include_in_schema=False)
    def _mascot():
        return FileResponse(_web_dir / "mascot.jpg")
