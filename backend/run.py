"""小银杏 AI 助手后端启动入口：启动服务并自动打开浏览器。

用法：
  1. 双击项目根目录的「启动小银杏.bat」；
  2. 或在 backend 目录执行 `python run.py`。

启动后浏览器会自动打开 http://127.0.0.1:8000 ；
使用期间请保持本窗口开启，关闭本窗口即停止服务。
"""
from __future__ import annotations

import threading
import time
import urllib.request
import webbrowser

import uvicorn

from app.config import settings

URL = f"http://127.0.0.1:{settings.port}"


def _is_running() -> bool:
    """探测服务是否已在运行，避免重复启动报端口占用。"""
    try:
        urllib.request.urlopen(URL + "/api/health", timeout=1.5)
        return True
    except Exception:
        return False


def _open_browser() -> None:
    time.sleep(2.5)
    try:
        webbrowser.open(URL)
    except Exception:
        pass


if __name__ == "__main__":
    if _is_running():
        print("服务已在运行，正在打开浏览器...")
        webbrowser.open(URL)
    else:
        print(f"正在启动小银杏服务，浏览器将自动打开：{URL}")
        print("使用期间请勿关闭本窗口；关闭本窗口即停止服务。\n")
        threading.Thread(target=_open_browser, daemon=True).start()
        uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
