#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "========================================================"
echo "  Doctor Agent 医疗多 Agent 系统 一键启动 (Bash)"
echo "========================================================"

if [ ! -d "frontend/node_modules" ]; then
    echo "[提示] 安装前端依赖中..."
    cd frontend && npm install && cd ..
fi

mkdir -p .cache
PID_FILE=".cache/services.pids"
> "$PID_FILE"

echo "[1/3] 启动后端服务 (FastAPI / 端口 8000)..."
python -m uvicorn doctor_agent.api:app --host 127.0.0.1 --port 8000 --workers 1 >/dev/null 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID,backend" >> "$PID_FILE"

echo "[2/3] 启动前端服务 (Vite / 端口 5173)..."
cd frontend
npm run dev >/dev/null 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID,frontend" >> "../$PID_FILE"
cd ..

echo "[3/3] 等待服务初始化就绪..."
sleep 3

echo "========================================================"
echo "  服务启动完成！"
echo "  前端地址: http://localhost:5173"
echo "  后端 API: http://127.0.0.1:8000/docs"
echo "  停止服务请运行: ./stop.sh"
echo "========================================================"
