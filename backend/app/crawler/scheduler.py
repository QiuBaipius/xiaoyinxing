"""定时采集调度：按上班时段（每天两次）触发采集 Agent 循环。"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from ..config import settings

_lock = threading.Lock()
_status: Dict[str, Any] = {
    "running": False,
    "last_run_at": "",
    "last_result": {},
    "next_run_at": "",
}


def _fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _next_run_at() -> datetime:
    """计算下次采集时间：优先按 COLLECT_HOURS（如 9、15 点），否则按间隔。"""
    now = datetime.now()
    if settings.collect_hours:
        today = now.date()
        for h in sorted(settings.collect_hours):
            target = datetime(today.year, today.month, today.day, h, 0, 0)
            if target > now:
                return target
        first = sorted(settings.collect_hours)[0]
        return datetime(today.year, today.month, today.day, first, 0, 0) + timedelta(days=1)
    return now + timedelta(hours=settings.crawl_interval_hours)


def _run_once(runner: Callable[[], Dict]) -> Dict[str, Any]:
    global _status
    with _lock:
        _status["running"] = True
    result: Dict[str, Any] = {"started_at": _fmt(datetime.now())}
    try:
        report = runner() if runner else {}
        result.update(report)
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)
    finally:
        with _lock:
            _status["running"] = False
            _status["last_run_at"] = _fmt(datetime.now())
            _status["last_result"] = result
    return result


def start(runner: Optional[Callable[[], Dict]] = None) -> threading.Thread:
    """启动后台定时采集线程。"""

    def loop():
        while True:
            _run_once(runner)
            nxt = _next_run_at()
            with _lock:
                _status["next_run_at"] = _fmt(nxt)
            time.sleep(max(1, (nxt - datetime.now()).total_seconds()))

    t = threading.Thread(target=loop, daemon=True, name="collect-agent")
    t.start()
    return t


def trigger(runner: Optional[Callable[[], Dict]] = None) -> Dict[str, Any]:
    """手动触发一次采集（同步执行）。"""
    if _status["running"]:
        return {"running": True, "message": "采集进行中"}
    return _run_once(runner)


def status() -> Dict[str, Any]:
    with _lock:
        return dict(_status)
