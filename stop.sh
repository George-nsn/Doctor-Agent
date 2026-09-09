#!/usr/bin/env bash

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "========================================================"
echo "  Doctor Agent 医疗多 Agent 系统 一键停止 (Bash)"
echo "========================================================"

PID_FILE=".cache/services.pids"
if [ -f "$PID_FILE" ]; then
    while IFS=',' read -r pid role; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "终止 $role 进程 (PID: $pid)..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

for port in 8000 5173; do
    pid=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "清理端口 $port 占用进程 (PID: $pid)..."
        kill -9 $pid 2>/dev/null || true
    fi
done

echo "========================================================"
echo "  所有 Doctor Agent 前后端服务已停止！"
echo "========================================================"
