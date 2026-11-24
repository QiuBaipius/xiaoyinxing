@echo off
chcp 65001 >nul
cd /d "%~dp0backend"

echo.
echo  ==============================================
echo    小银杏 · 东北财经大学 AI 校园助手
echo  ==============================================
echo.

rem 检查依赖是否已安装，首次运行自动安装
python -c "import fastapi, uvicorn, requests, bs4, numpy, dotenv" 2>nul
if errorlevel 1 (
    echo  首次运行：正在安装依赖，请稍候...
    echo.
    python -m pip install -r requirements.txt
    echo.
)

python run.py

echo.
echo  服务已停止，按任意键关闭窗口...
pause >nul
