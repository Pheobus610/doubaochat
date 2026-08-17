#!/usr/bin/env bash
# doubaochat 一键安装脚本（全新空机器可用）
#
# 用法：
#   ./install.sh                自动选择部署方式
#   ./install.sh --docker       强制 Docker 模式
#   ./install.sh --bare         强制裸机模式（venv）
#   ./install.sh --yes          全部使用默认值，不交互（适合自动化）
#
# 一行安装（未克隆仓库时）：
#   curl -fsSL https://raw.githubusercontent.com/Pheobus610/doubaochat/main/install.sh | bash
#
# 可重复执行：已有环境不会被破坏。
set -euo pipefail

REPO_URL="https://github.com/Pheobus610/doubaochat.git"
MODE="auto"
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --docker) MODE="docker" ;;
    --bare)   MODE="bare" ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 1 ;;
  esac
done

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }
step() { echo -e "\n${CYAN}→${NC} $*"; }

ask() {  # ask "问题" -> 0=是
  [ "$ASSUME_YES" = "1" ] && return 0
  [ -t 0 ] || return 1          # 管道执行（curl | bash）时不交互，走默认
  read -r -p "$1 [Y/n] " a
  case "$a" in [nN]*) return 1 ;; *) return 0 ;; esac
}

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

# ── 包管理器识别（用于提示缺失依赖的安装命令）──────
PKG=""
for p in apt-get dnf yum apk brew; do
  command -v "$p" >/dev/null 2>&1 && { PKG="$p"; break; }
done
pkg_install() {
  case "$PKG" in
    apt-get) $SUDO apt-get update -qq && $SUDO apt-get install -y "$@" ;;
    dnf)     $SUDO dnf install -y "$@" ;;
    yum)     $SUDO yum install -y "$@" ;;
    apk)     $SUDO apk add --no-cache "$@" ;;
    brew)    brew install "$@" ;;
    *) return 1 ;;
  esac
}

echo "=============================================="
echo "     doubaochat 一键安装"
echo "=============================================="

# ── 1. 基础命令 ────────────────────────────────────
step "检查基础命令"
for c in curl git; do
  if ! command -v "$c" >/dev/null 2>&1; then
    warn "缺少 $c，尝试自动安装"
    pkg_install "$c" || { err "请先手动安装 $c 后重试"; exit 1; }
  fi
done
info "curl / git 就绪"

# ── 2. 定位项目 ────────────────────────────────────
step "定位项目目录"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "$PWD")"
if [ -f "$SCRIPT_DIR/requirements.txt" ] && [ -d "$SCRIPT_DIR/app" ]; then
  PROJECT_DIR="$SCRIPT_DIR"
  info "已在项目目录：$PROJECT_DIR"
else
  PROJECT_DIR="${PWD}/doubaochat"
  if [ -d "$PROJECT_DIR/.git" ]; then
    info "复用已有克隆：$PROJECT_DIR"
    git -C "$PROJECT_DIR" pull --ff-only || warn "git pull 失败，使用当前代码"
  else
    step "克隆仓库到 $PROJECT_DIR"
    git clone --depth 1 "$REPO_URL" "$PROJECT_DIR"
  fi
fi
cd "$PROJECT_DIR"

# ── 3. 选择部署方式 ────────────────────────────────
step "选择部署方式"
docker_ready() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }

if [ "$MODE" = "auto" ]; then
  if docker_ready; then
    MODE="docker"; info "检测到可用的 Docker，使用容器部署（隔离性更好）"
  elif [ -n "$PKG" ] && ask "未检测到 Docker。是否安装 Docker？（否则使用裸机 venv 部署）"; then
    MODE="docker"
  else
    MODE="bare"; info "使用裸机 venv 部署"
  fi
fi

# ── 4. 执行安装 ────────────────────────────────────
if [ "$MODE" = "docker" ]; then
  if ! docker_ready; then
    step "安装 Docker"
    if command -v docker >/dev/null 2>&1; then
      # 已装但 daemon 没跑
      $SUDO systemctl enable --now docker 2>/dev/null || {
        err "Docker 已安装但守护进程未运行，请手动启动后重试（macOS 请打开 Docker Desktop）"; exit 1; }
    else
      curl -fsSL https://get.docker.com | $SUDO sh || { err "Docker 安装失败，可改用：./install.sh --bare"; exit 1; }
      $SUDO systemctl enable --now docker 2>/dev/null || true
    fi
    docker_ready || { err "Docker 仍不可用。若当前用户不在 docker 组，请执行：$SUDO usermod -aG docker $(id -un) 后重新登录"; exit 1; }
  fi
  info "Docker 就绪：$(docker --version)"
else
  step "准备 Python 环境（自动处理 Python < 3.10 的机器）"
  # setup.sh 里已包含版本检测 + uv 兜底逻辑
  bash ./setup.sh
fi

# ── 5. 配置 .env ───────────────────────────────────
step "检查配置文件"
if [ ! -f .env ]; then
  cp .env.example .env
  info "已生成 .env"
fi
if ! grep -qE '^ARK_API_KEY=.+' .env 2>/dev/null; then
  warn "ARK_API_KEY 尚未填写，服务可以启动但接口会提示未配置"
  echo "    请编辑 $PROJECT_DIR/.env 填入火山方舟的 ARK_API_KEY 与 ARK_MODEL"
fi

# ── 6. 启动 ────────────────────────────────────────
chmod +x server.sh 2>/dev/null || true
step "启动服务"
./server.sh start || { err "启动失败，请查看：./server.sh logs"; exit 1; }

# ── 7. 开机自启 ────────────────────────────────────
if ask "是否注册开机自启（长期挂载建议开启）？"; then
  ./server.sh install-service || warn "注册开机自启失败，可稍后手动执行 ./server.sh install-service"
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -z "$IP" ] && IP="$(ipconfig getifaddr en0 2>/dev/null || echo '<本机IP>')"
cat <<EOF

==============================================
  安装完成
==============================================
  本机访问   : http://127.0.0.1:${PORT:-8000}
  局域网访问 : http://${IP}:${PORT:-8000}

  常用命令（在 $PROJECT_DIR 下）：
    ./server.sh status    查看状态与资源占用
    ./server.sh logs      查看日志
    ./server.sh restart   重启
    ./server.sh update    更新代码并重启
==============================================
EOF
