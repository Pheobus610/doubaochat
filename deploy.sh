#!/usr/bin/env bash
# doubaochat 一键 Docker 部署脚本
# 适用于全新服务器（仅需联网 + root/sudo 权限）
#
# 用法：
#   方式一（还没克隆，一行拉起）：
#     curl -fsSL https://raw.githubusercontent.com/Pheobus610/doubaochat/main/deploy.sh | bash
#   方式二（已克隆）：
#     git clone https://github.com/Pheobus610/doubaochat.git && cd doubaochat && ./deploy.sh
#   指定克隆目录：
#     ./deploy.sh /opt/doubaochat
set -euo pipefail

REPO_URL="https://github.com/Pheobus610/doubaochat.git"
INSTALL_DIR="${1:-}"

# ── 颜色输出 ──────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*" >&2; }
step()  { echo -e "${CYAN}→${NC} $*"; }

# ── root/sudo 检测 ─────────────────────────────────
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    error "需要 root 权限或 sudo 来安装 Docker"
    exit 1
  fi
fi

# ── 1. 定位项目目录 ────────────────────────────────
step "定位项目目录..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/docker-compose.yml" ] && [ -f "$SCRIPT_DIR/Dockerfile" ]; then
  PROJECT_DIR="$SCRIPT_DIR"
  info "已在项目目录：$PROJECT_DIR"
  if [ -d "$PROJECT_DIR/.git" ]; then
    step "拉取最新代码..."
    git -C "$PROJECT_DIR" pull --ff-only || warn "git pull 失败，使用当前代码继续"
  fi
else
  PROJECT_DIR="${INSTALL_DIR:-doubaochat}"
  if [ -d "$PROJECT_DIR/.git" ]; then
    step "目录 $PROJECT_DIR 已存在，拉取最新代码..."
    git -C "$PROJECT_DIR" pull --ff-only || warn "git pull 失败，使用当前代码继续"
  else
    step "克隆仓库到 $PROJECT_DIR..."
    git clone "$REPO_URL" "$PROJECT_DIR"
  fi
  cd "$PROJECT_DIR"
fi
info "工作目录：$(pwd)"

# ── 2. 检查/安装 Docker ────────────────────────────
step "检查 Docker..."
if ! command -v docker >/dev/null 2>&1; then
  step "未检测到 Docker，开始安装（get.docker.com）..."
  curl -fsSL https://get.docker.com | $SUDO sh
  $SUDO systemctl enable --now docker
  info "Docker 安装完成：$(docker --version 2>/dev/null || echo '已安装')"
else
  info "Docker 已安装：$(docker --version)"
fi

# ── 3. 检查 docker compose ─────────────────────────
step "检查 docker compose..."
COMPOSE=""
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  error "未检测到 docker compose 插件，请安装 Docker 20.10+"
  exit 1
fi
# 非 root 用户若无 docker 权限，加 sudo 前缀
if [ -n "$SUDO" ] && ! docker info >/dev/null 2>&1; then
  COMPOSE="$SUDO $COMPOSE"
fi
info "使用：$COMPOSE"

# ── 4. 配置 .env ───────────────────────────────────
step "检查 .env 配置..."
if [ ! -f .env ]; then
  cp .env.example .env
  warn "已从 .env.example 创建 .env"
  echo ""
  echo "=============================================="
  echo "  请编辑 .env 填入以下配置后重新运行本脚本："
  echo ""
  echo "    ARK_API_KEY    = 你的方舟 API Key"
  echo "    ARK_MODEL      = 模型 ID（如 doubao-seed-2-1-turbo-260628）"
  echo "    SPEECH_APPID   = 语音 AppID（TTS 用，可选）"
  echo "    SPEECH_TOKEN   = 语音 Token（TTS 用，可选）"
  echo "    ACCESS_TOKEN   = 访问口令（公网暴露强烈建议设置）"
  echo ""
  echo "  编辑命令：nano .env  或  vim .env"
  echo "  编辑后重跑：./deploy.sh"
  echo "=============================================="
  exit 0
fi

# 检查关键配置是否仍为占位符
if grep -q "你的方舟_API_Key\|ep-xxxxxxxx" .env 2>/dev/null; then
  warn ".env 中仍有占位符，请编辑 .env 填入真实配置后重新运行"
  echo "  编辑命令：nano .env"
  exit 1
fi
info ".env 配置已就绪"

# ── 5. 构建并启动 ──────────────────────────────────
step "构建镜像并启动容器..."
$COMPOSE up -d --build
info "容器已启动"

# ── 6. 等待服务就绪 ────────────────────────────────
step "等待服务就绪..."
READY=0
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    info "服务已就绪"
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -eq 0 ]; then
  warn "服务未在 30s 内就绪，查看日志：$COMPOSE logs -f"
fi

# ── 7. 输出访问信息 ────────────────────────────────
PUBLIC_IP="$(curl -sf --max-time 3 https://ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "服务器IP")"
echo ""
echo "=============================================="
echo "  🎉 部署完成！"
echo ""
echo "  本机访问 : http://127.0.0.1:8000"
echo "  公网访问 : http://${PUBLIC_IP}:8000"
echo ""
echo "  ⚠️  请在云服务器控制台防火墙中放行 TCP 8000 端口"
echo ""
echo "  常用命令："
echo "    查看日志 : $COMPOSE logs -f"
echo "    重启服务 : $COMPOSE restart"
echo "    停止服务 : $COMPOSE down"
echo "    更新代码 : git pull && $COMPOSE up -d --build"
echo "=============================================="
