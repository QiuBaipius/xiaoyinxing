#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

echo "==> 升级 pip"
python -m pip install --upgrade pip

echo "==> 安装后端依赖"
pip install -r backend/requirements.txt

echo "==> 完成。若需 AI 回答，请在 Codespaces Secrets 中配置 GLM_API_KEY"
