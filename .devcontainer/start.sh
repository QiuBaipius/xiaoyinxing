#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

# 用 Codespaces Secret 生成 backend/.env（如不存在）
if [ ! -f backend/.env ] && [ -n "${GLM_API_KEY:-}" ]; then
  printf 'GLM_API_KEY=%s\n' "${GLM_API_KEY}" > backend/.env
fi

cd backend
if ! curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  nohup python run.py > /tmp/xiaoyinxing.log 2>&1 &
fi

echo "小银杏已启动： http://localhost:8000"
echo "日志：/tmp/xiaoyinxing.log"
