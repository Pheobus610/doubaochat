# 构建 doubaochat 镜像
# 用法：docker build -t doubaochat . && docker run -p 8000:8000 --env-file .env doubaochat
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先安装依赖（利用层缓存）
COPY requirements.txt .
RUN pip install -r requirements.txt

# 拷贝应用代码与静态资源
COPY app/ ./app/
COPY static/ ./static/

RUN mkdir -p uploads

EXPOSE 8000

# 健康探针：每 30s 探活 /api/health，连续 3 次失败标记 unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

# 生产环境不加 --reload。
# 必须 --workers 1：会话状态存在进程内存字典里，多 worker 会让同一用户的
# 请求随机命中不同进程，随机报「会话不存在」。20 并发靠线程池即可支撑
# （已实测 20 并发出题完全并行），无需多 worker。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-keep-alive", "65"]
