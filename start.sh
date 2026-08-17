#!/usr/bin/env bash
# 本地一键启动脚本：准备虚拟环境 → 安装依赖 → 启动 FastAPI 服务
# 用法：
#   ./start.sh            仅启动本地服务（本机 + 局域网可访问）
#   TUNNEL=1 ./start.sh   启动服务并自动建立公网隧道（需已安装 cloudflared 或 ngrok）
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}
VENV=".venv"

# 1. 虚拟环境（复用 setup.sh 的版本检测与 uv 兜底，避免装出 3.9 的坏环境）
if [ ! -d "$VENV" ] || ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
  echo "→ 准备 Python 环境（需 3.10+）"
  bash ./setup.sh
fi

# 2. 依赖（仅在 fastapi 未安装时安装，避免每次启动都等待）
# 注意：uv 创建的虚拟环境默认不含 pip，所以用 python -c 探测、用 uv/python -m pip 安装
if ! "$VENV/bin/python" -c "import fastapi" >/dev/null 2>&1; then
  echo "→ 安装依赖（requirements.txt）"
  if "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
    "$VENV/bin/python" -m pip install -r requirements.txt
  elif command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV/bin/python" -r requirements.txt
  else
    echo "❌ 虚拟环境内既无 pip 也未找到 uv，请运行 ./setup.sh 重建环境" >&2
    exit 1
  fi
fi

# 3. 提示 .env
if [ ! -f .env ] && [ -f .env.example ]; then
  echo "→ 未检测到 .env，已从 .env.example 复制一份（请按需填写）"
  cp .env.example .env
fi

echo ""
echo "=============================================="
echo "  本机访问    : http://127.0.0.1:$PORT"
echo "  局域网访问  : http://<本机IP>:$PORT"
if [ "${TUNNEL:-0}" = "1" ]; then
  echo "  公网隧道    : 启动后见下方输出的 https://... 地址"
fi
echo "  按 Ctrl-C 退出"
echo "=============================================="
echo ""

# 4. 启动
if [ "${TUNNEL:-0}" = "1" ]; then
  # 后台启动服务，前台启动隧道；退出时一并关闭服务
  SERVER_PID=""
  cleanup() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
      echo ""
      echo "→ 停止后端服务"
      kill "$SERVER_PID" 2>/dev/null || true
      wait "$SERVER_PID" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT INT TERM

  "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" --reload &
  SERVER_PID=$!

  # 等待服务就绪
  for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then break; fi
    sleep 0.5
  done

  echo "→ 后端已启动，正在建立公网隧道…"
  if command -v cloudflared >/dev/null 2>&1; then
    echo "   （使用 cloudflared，无需账号；Ctrl-C 同时关闭后端）"
    cloudflared tunnel --url "http://localhost:$PORT" || true
  elif command -v ngrok >/dev/null 2>&1; then
    echo "   （使用 ngrok；Ctrl-C 同时关闭后端）"
    ngrok http "$PORT" || true
  else
    echo "⚠️  未检测到 cloudflared 或 ngrok，无法建立公网隧道。"
    echo "    安装其一后重试："
    echo "      brew install cloudflared     # 推荐，免费且无需账号"
    echo "      brew install ngrok/ngrok/ngrok  # 需注册并配置 authtoken"
    echo "    当前仅本机/局域网可访问，等待 Ctrl-C 退出…"
    wait "$SERVER_PID" || true
  fi
else
  exec "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" --reload
fi
