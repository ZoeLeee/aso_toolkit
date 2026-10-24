FROM python:3.11-slim

WORKDIR /app

# 设置环境变量：免缓冲、默认时区、配置 Streamlit 生产运行参数
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# 安装运行时基础依赖（包含证书、健康检查与时区数据）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 先安装依赖，利用 Docker 构建缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制工程代码与预设数据库
COPY . .

# 确保脚本有可执行权限并创建持久化数据目录
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/data

# 暴露服务端口
EXPOSE 8501

# 容器健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# 通过统一入口启动后台巡检守护与前台看板
CMD ["/app/entrypoint.sh"]
