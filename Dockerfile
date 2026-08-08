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

# 生产环境不加 --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
