#!/usr/bin/env bash
# 公网隧道脚本：把本地服务暴露到公网，供非局域网用户访问。
# 前置：先在另一终端运行 ./start.sh 启动服务。
# 推荐 cloudflared（免费、无需账号）；也支持 ngrok。
set -euo pipefail

PORT=${PORT:-8000}
TARGET="http://localhost:$PORT"

echo "→ 将本地 $TARGET 暴露到公网"
echo "   启动后找到形如 https://xxxx.trycloudflare.com 的地址，分享给他人即可"
echo "   按 Ctrl-C 关闭隧道（本地服务不受影响）"
echo ""

if command -v cloudflared >/dev/null 2>&1; then
  exec cloudflared tunnel --url "$TARGET"
elif command -v ngrok >/dev/null 2>&1; then
  exec ngrok http "$PORT"
else
  echo "❌ 未检测到 cloudflared 或 ngrok，请先安装其一："
  echo ""
  echo "   推荐 cloudflared（免费、无需账号）："
  echo "     brew install cloudflared"
  echo ""
  echo "   或 ngrok（需注册获取 authtoken）："
  echo "     brew install ngrok/ngrok/ngrok"
  echo "     ngrok config add-authtoken <你的Token>"
  echo ""
  exit 1
fi
