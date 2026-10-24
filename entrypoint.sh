#!/bin/bash
set -e

# ========================================================
# 个人轻量级 ASO 监控工具 - 容器统一启动入口 (entrypoint.sh)
# 职责：
# 1. 后台启动 ASO 爬虫定时守护进程 (拉取 App 状态与排名)
# 2. 前台启动 Streamlit Web 看板
# 3. 优雅捕获退出信号，保障多进程平稳停止与数据安全
# ========================================================

TRACKER_PID=""
WEB_PID=""

cleanup() {
    echo ""
    echo "🛑 接收到退出信号，正在平稳停止所有容器子进程..."
    if [ -n "$TRACKER_PID" ]; then
        kill -TERM "$TRACKER_PID" 2>/dev/null || true
    fi
    if [ -n "$WEB_PID" ]; then
        kill -TERM "$WEB_PID" 2>/dev/null || true
    fi
    wait
    echo "✅ 容器服务已安全退出。"
    exit 0
}

trap cleanup SIGTERM SIGINT

echo "========================================================"
echo "🚀 启动 ASO Toolkit 容器环境..."
echo "🕒 当前容器时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "========================================================"

# 1. 启动后台 ASO 监控守护进程 (默认开启，如需关闭可在环境变量配置 ENABLE_DAEMON=false)
if [ "${ENABLE_DAEMON:-true}" != "false" ]; then
    echo "⏰ [1/2] 正在启动后台 ASO 自动巡检守护进程 (每日定时更新 App 状态与排名)..."
    python3 cron_tracker.py --daemon &
    TRACKER_PID=$!
    echo "✅ 后台巡检守护进程已启动，PID: $TRACKER_PID"
else
    echo "ℹ️ 后台巡检守护进程已通过 ENABLE_DAEMON=false 禁用。"
fi

# 2. 启动前台 Streamlit Web 服务
echo "🌐 [2/2] 正在启动 Streamlit Web 看板 (端口 ${STREAMLIT_SERVER_PORT:-8501})..."
streamlit run app.py \
    --server.port="${STREAMLIT_SERVER_PORT:-8501}" \
    --server.address="${STREAMLIT_SERVER_ADDRESS:-0.0.0.0}" \
    --server.headless=true &
WEB_PID=$!
echo "✅ Streamlit 看板已启动，PID: $WEB_PID"

echo "========================================================"
echo "🎉 ASO Toolkit 服务已就绪，正在持续监控中..."
echo "========================================================"

wait "$WEB_PID"
