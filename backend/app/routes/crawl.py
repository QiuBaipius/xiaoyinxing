"""采集管理接口：手动触发 + 状态查询。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from ..crawler import scheduler
from ..crawler.agent import agent as collect_agent
from ..schemas import CrawlStatus

router = APIRouter(prefix="/api/crawl", tags=["crawler"])


@router.get("/status", response_model=CrawlStatus)
def crawl_status():
    s = scheduler.status()
    return CrawlStatus(
        running=s.get("running", False),
        last_run_at=s.get("last_run_at", ""),
        last_result=s.get("last_result", {}),
        next_run_at=s.get("next_run_at", ""),
    )


@router.post("/run")
def crawl_run(background: BackgroundTasks):
    """后台触发一次全量采集并自动入库。"""
    background.add_task(scheduler.trigger, collect_agent.run)
    return {"ok": True, "message": "采集 Agent 已启动，请稍后查询状态"}


@router.get("/sites")
def crawl_sites():
    from ..crawler.sites import SITES

    return {
        "sites": [
            {
                "key": s.key, "name": s.name, "base_url": s.base_url,
                "columns": [
                    {"name": c.name, "url": c.url, "category": c.category, "audience": c.audience}
                    for c in s.columns
                ],
            }
            for s in SITES
        ]
    }
