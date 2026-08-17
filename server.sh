#!/usr/bin/env bash
# doubaochat 服务运维脚本（适合长期挂载的服务器）
#
# 用法：
#   ./server.sh start            后台启动
#   ./server.sh stop             停止
#   ./server.sh restart          重启
#   ./server.sh status           状态 + 健康检查 + 资源占用
#   ./server.sh logs [行数]      查看/跟踪日志
#   ./server.sh update           拉取最新代码并重启
#   ./server.sh install-service  注册开机自启
#   ./server.sh uninstall-service 取消开机自启
#
# 自动识别运行方式：有 docker compose 用容器，否则裸机 + nohup/systemd。
set -euo pipefail
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
PID_FILE="$PROJECT_DIR/.server.pid"
LOG_FILE="$PROJECT_DIR/logs/server.log"
SERVICE_NAME="doubaochat"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }
step() { echo -e "${CYAN}→${NC} $*"; }

# ── 运行模式判定 ───────────────────────────────────
DOCKER_CMD=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  DOCKER_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_CMD="docker-compose"
fi
# 只有存在 compose 文件且 docker 真的能用（daemon 在跑）才走容器模式
USE_DOCKER=0
if [ -n "$DOCKER_CMD" ] && [ -f docker-compose.yml ] && docker info >/dev/null 2>&1; then
  USE_DOCKER=1
fi

have_systemd() { command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; }

SUDO=""
[ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

check_env() {
  if [ ! -f .env ]; then
    if [ -f .env.example ]; then
      warn "未找到 .env，已从 .env.example 复制，请填写 ARK_API_KEY 后重新启动"
      cp .env.example .env
    else
      err "缺少 .env 配置文件"; exit 1
    fi
  fi
  # 提前拦住最常见的部署失败原因，避免起来后才报 503
  if ! grep -qE '^ARK_API_KEY=.+' .env 2>/dev/null; then
    warn ".env 中 ARK_API_KEY 似乎为空，服务能启动但接口会返回未配置"
  fi
}

wait_healthy() {
  step "等待服务就绪…"
  for i in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      info "服务已就绪：http://127.0.0.1:$PORT"
      return 0
    fi
    sleep 1
  done
  err "等待 60s 仍未就绪，请查看日志：./server.sh logs"
  return 1
}

bare_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null
}

do_start() {
  check_env
  if [ "$USE_DOCKER" = "1" ]; then
    step "Docker 模式启动…"
    $DOCKER_CMD up -d --build
    wait_healthy
    return
  fi
  # 裸机模式
  if have_systemd && $SUDO systemctl is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then
    step "systemd 模式启动…"
    $SUDO systemctl start "$SERVICE_NAME"
    wait_healthy
    return
  fi
  if bare_running; then
    warn "服务已在运行（PID $(cat "$PID_FILE")）"; return
  fi
  [ -x .venv/bin/uvicorn ] || { err "未找到 .venv，请先运行 ./install.sh"; exit 1; }
  mkdir -p "$(dirname "$LOG_FILE")"
  step "裸机模式后台启动…"
  # --workers 1：会话在进程内存，多 worker 会导致会话丢失
  nohup .venv/bin/uvicorn app.main:app \
    --host "$HOST" --port "$PORT" --workers 1 --timeout-keep-alive 65 \
    >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  wait_healthy || true
  warn "裸机 nohup 方式在崩溃后不会自动重启。长期挂载建议执行："
  echo "    ./server.sh install-service"
}

do_stop() {
  if [ "$USE_DOCKER" = "1" ]; then
    step "停止容器…"; $DOCKER_CMD down; info "已停止"; return
  fi
  if have_systemd && $SUDO systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then
    step "停止 systemd 服务…"; $SUDO systemctl stop "$SERVICE_NAME"; info "已停止"; return
  fi
  if bare_running; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    for _ in $(seq 1 20); do bare_running || break; sleep 0.5; done
    bare_running && kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"; info "已停止"
  else
    warn "服务未在运行"
  fi
}

do_status() {
  echo "运行模式：$([ "$USE_DOCKER" = 1 ] && echo Docker || echo 裸机)"
  echo "------------------------------------------"
  if [ "$USE_DOCKER" = "1" ]; then
    $DOCKER_CMD ps 2>/dev/null || true
    echo ""
    docker stats --no-stream --format \
      "内存 {{.MemUsage}}   CPU {{.CPUPerc}}   进程 {{.PIDs}}" doubaochat 2>/dev/null || true
  elif have_systemd && $SUDO systemctl is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then
    $SUDO systemctl status "$SERVICE_NAME" --no-pager -l | head -12 || true
  elif bare_running; then
    pid="$(cat "$PID_FILE")"
    info "运行中，PID $pid"
    ps -o pid,rss,%cpu,etime -p "$pid" 2>/dev/null | tail -n +1 || true
  else
    warn "未运行"
  fi
  echo "------------------------------------------"
  if h="$(curl -sf --max-time 5 "http://127.0.0.1:$PORT/api/health" 2>/dev/null)"; then
    info "健康检查通过：$h"
  else
    err "健康检查失败（端口 $PORT 无响应）"
  fi
  # 磁盘占用是长期挂载最容易被忽略的指标
  if [ -d uploads ]; then
    echo "uploads 占用：$(du -sh uploads 2>/dev/null | cut -f1)（$(find uploads -type f 2>/dev/null | wc -l | tr -d ' ') 个文件）"
  fi
  echo "磁盘剩余：$(df -h . | awk 'NR==2{print $4" / "$2" (已用 "$5")"}')"
}

do_logs() {
  n="${1:-200}"
  if [ "$USE_DOCKER" = "1" ]; then
    $DOCKER_CMD logs -f --tail "$n"
  elif have_systemd && $SUDO systemctl is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then
    $SUDO journalctl -u "$SERVICE_NAME" -n "$n" -f
  elif [ -f "$LOG_FILE" ]; then
    tail -n "$n" -f "$LOG_FILE"
  else
    err "未找到日志"
  fi
}

do_update() {
  if [ -d .git ]; then
    step "拉取最新代码…"
    git pull --ff-only || warn "git pull 失败，继续用当前代码"
  else
    warn "非 git 仓库，跳过代码更新"
  fi
  if [ "$USE_DOCKER" = "1" ]; then
    step "重建并重启容器…"; $DOCKER_CMD up -d --build; wait_healthy
  else
    # uv 创建的虚拟环境没有 pip，需分别处理
    if [ -x .venv/bin/python ]; then
      step "更新依赖…"
      if .venv/bin/python -m pip --version >/dev/null 2>&1; then
        .venv/bin/python -m pip install -q -r requirements.txt
      elif command -v uv >/dev/null 2>&1; then
        uv pip install -q --python .venv/bin/python -r requirements.txt
      else
        warn "无法更新依赖（缺 pip 与 uv），继续用现有依赖启动"
      fi
    fi
    do_stop || true; do_start
  fi
}

install_service() {
  if [ "$USE_DOCKER" = "1" ]; then
    # Docker 的 restart: always 本身已实现开机自启，只需确保 docker 自启
    step "Docker 模式：restart=always 已覆盖开机自启"
    have_systemd && $SUDO systemctl enable docker >/dev/null 2>&1 && info "已确保 docker 开机自启" || true
    info "无需额外配置"
    return
  fi
  have_systemd || { err "当前系统无 systemd，无法注册服务（macOS 请用 Docker 模式）"; exit 1; }
  [ -x .venv/bin/uvicorn ] || { err "未找到 .venv，请先运行 ./install.sh"; exit 1; }
  step "写入 systemd 服务…"
  $SUDO tee "/etc/systemd/system/$SERVICE_NAME.service" >/dev/null <<EOF
[Unit]
Description=doubaochat AI learning service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
# --workers 1：会话状态在进程内存，多 worker 会导致会话随机丢失
ExecStart=$PROJECT_DIR/.venv/bin/uvicorn app.main:app --host $HOST --port $PORT --workers 1 --timeout-keep-alive 65
# 崩溃自动恢复
Restart=always
RestartSec=5
# 防频繁重启风暴：10 分钟内最多重启 10 次，超过则停下等人工介入
StartLimitBurst=10
StartLimitIntervalSec=600
# 内存超限时由内核回收，避免拖垮整机
MemoryMax=512M
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable "$SERVICE_NAME"
  # 已有 nohup 实例会占端口，先清掉
  bare_running && { step "停止已有 nohup 实例…"; kill "$(cat "$PID_FILE")" 2>/dev/null || true; rm -f "$PID_FILE"; }
  $SUDO systemctl restart "$SERVICE_NAME"
  wait_healthy
  info "已注册开机自启（崩溃后 5s 自动重启）"
}

uninstall_service() {
  have_systemd || { warn "无 systemd，无需卸载"; exit 0; }
  $SUDO systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
  $SUDO rm -f "/etc/systemd/system/$SERVICE_NAME.service"
  $SUDO systemctl daemon-reload
  info "已取消开机自启"
}

case "${1:-}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop || true; do_start ;;
  status)  do_status ;;
  logs)    do_logs "${2:-200}" ;;
  update)  do_update ;;
  install-service)   install_service ;;
  uninstall-service) uninstall_service ;;
  *)
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    exit 1 ;;
esac
