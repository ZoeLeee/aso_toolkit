FROM python:3.11-slim

WORKDIR /app

# 设置环境变量：免缓冲、配置 Streamlit 生产运行参数
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# 安装运行时基础依赖（包含证书与健康检查工具）
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

# 创建持久化数据目录
RUN mkdir -p /app/data

# 暴露服务端口
EXPOSE 8501

# 容器健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# 启动 Streamlit 服务
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
