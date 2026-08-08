#!/usr/bin/env bash
# 一键环境准备脚本：克隆仓库 → 创建虚拟环境 → 安装依赖 → 生成 .env
#
# 适用场景：
#   1) 全新机器（尚未克隆）：直接运行本脚本，会自动克隆到 ./doubaochat
#        curl -fsSL https://raw.githubusercontent.com/Pheobus610/doubaochat/main/setup.sh | bash
#        或下载后：bash setup.sh [目标目录]
#   2) 已克隆仓库：在仓库目录内运行 ./setup.sh，自动跳过克隆、就地配置
#
# 可重复执行：已存在的虚拟环境/依赖/.env 不会被破坏。
set -euo pipefail

REPO_URL="https://github.com/Pheobus610/doubaochat.git"

# ---------- 辅助 ----------
need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "❌ 缺少命令：$1，请先安装后再运行本脚本。" >&2
    exit 1
  }
}

print_help() {
  cat <<'EOF'
用法：setup.sh [目标目录]
  不带参数且当前已在仓库内 → 就地配置
  不带参数且当前不在仓库内 → 克隆到 ./doubaochat
  带目录参数                → 克隆/更新到该目录
选项：
  -h, --help   显示本帮助
EOF
}

# ---------- 参数 ----------
case "${1:-}" in
  -h|--help) print_help; exit 0 ;;
esac

# ---------- 前置检查 ----------
need_cmd git
need_cmd python3

py_major=$(python3 -c 'import sys; print(sys.version_info[0])')
py_minor=$(python3 -c 'import sys; print(sys.version_info[1])')
if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 10 ]; }; then
  echo "❌ 需要 Python 3.10+（项目使用 X | None 语法），当前为 $(python3 --version 2>&1)" >&2
  echo "   macOS 可用 brew install python@3.11 安装新版本。" >&2
  exit 1
fi
echo "✓ $(python3 --version 2>&1)"

# ---------- 确定工作目录 ----------
# 若当前目录已有 app/main.py + requirements.txt，视为“已在仓库内”，就地配置
if [ -f "app/main.py" ] && [ -f "requirements.txt" ]; then
  PROJECT_DIR="$PWD"
  echo "✓ 检测到已位于仓库内，就地配置：$PROJECT_DIR"
else
  PROJECT_DIR="${1:-$PWD/doubaochat}"
  if [ -d "$PROJECT_DIR/.git" ]; then
    echo "→ 仓库已存在，拉取最新代码：$PROJECT_DIR"
    git -C "$PROJECT_DIR" pull --ff-only
  else
    # 目标目录非空且非仓库 → 报错，避免误伤用户数据
    if [ -e "$PROJECT_DIR" ] && [ -n "$(ls -A "$PROJECT_DIR" 2>/dev/null)" ]; then
      echo "❌ 目标目录已存在且非空：$PROJECT_DIR" >&2
      echo "   请指定一个空目录，或先删除该目录。" >&2
      exit 1
    fi
    echo "→ 克隆仓库到：$PROJECT_DIR"
    # 首次用默认协议克隆；遇到 HTTP/2 报错时回退 HTTP/1.1 重试一次
    if ! git clone "$REPO_URL" "$PROJECT_DIR"; then
      echo "⚠️ 克隆失败，尝试切换 HTTP/1.1 重试…"
      rm -rf "$PROJECT_DIR"
      git -c http.version=HTTP/1.1 clone "$REPO_URL" "$PROJECT_DIR" || {
        echo "❌ 克隆失败，请检查网络后重试，或手动执行：" >&2
        echo "   git clone $REPO_URL \"$PROJECT_DIR\"" >&2
        exit 1
      }
    fi
  fi
fi

cd "$PROJECT_DIR"

# ---------- 虚拟环境 ----------
if [ ! -d ".venv" ]; then
  echo "→ 创建虚拟环境 .venv"
  python3 -m venv .venv
fi

# ---------- 依赖 ----------
echo "→ 安装依赖（requirements.txt）"
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt

# ---------- .env ----------
if [ ! -f ".env" ]; then
  echo "→ 从 .env.example 生成 .env（请按需填写方舟凭证）"
  cp .env.example .env
else
  echo "✓ .env 已存在，保持不变"
fi

# ---------- 可选：cloudflared（公网隧道用） ----------
install_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    echo "✓ cloudflared 已安装（支持公网隧道）"
    return 0
  fi
  if ! command -v brew >/dev/null 2>&1; then
    echo "ℹ️ 未检测到 Homebrew；公网隧道需要 cloudflared，可手动安装：brew install cloudflared"
    return 0
  fi
  if [ -t 0 ]; then
    printf "是否现在安装 cloudflared 以支持公网访问？[Y/n] "
    read -r ans </dev/tty || ans=""
    case "${ans:-Y}" in
      [nN]*) echo "→ 已跳过（日后可执行：brew install cloudflared）"; return 0 ;;
    esac
    echo "→ 通过 Homebrew 安装 cloudflared…"
    brew install cloudflared || echo "⚠️ 安装失败，可稍后手动：brew install cloudflared"
  else
    echo "ℹ️ 非交互模式，跳过 cloudflared 自动安装；如需公网访问请执行：brew install cloudflared"
  fi
}
install_cloudflared

# ---------- 完成 ----------
cat <<EOF

============================================================
✅ 环境准备完成！仓库目录：$PROJECT_DIR

下一步：
  1) 编辑 .env 填入你的方舟 API Key / 模型（或在网页「设置」中填写）
     公网部署建议设置 ACCESS_TOKEN 启用访问口令保护
  2) 启动服务：
       cd "$PROJECT_DIR"
       ./start.sh
     本机访问：http://127.0.0.1:8000  |  局域网：http://<本机IP>:8000
  3) 公网访问（需 cloudflared）：另开一个终端执行
       ./tunnel.sh
     将输出的 https://xxxx.trycloudflare.com 分享给他人即可
============================================================
EOF
