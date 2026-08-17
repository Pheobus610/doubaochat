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
# 注意：这里不再硬性要求系统 python3 >= 3.10。
# 老系统（macOS 自带 3.9、CentOS 7、Ubuntu 20.04）上系统 Python 版本低是常态，
# 下面「虚拟环境」一节会自动挑选合适的解释器，必要时用 uv 装独立的 3.12。

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
# 关键：项目代码使用 `X | None` 语法，必须 Python >= 3.10。
# 直接 `python3 -m venv` 在只有 3.9 的老系统（CentOS 7、Ubuntu 20.04 等）上
# 会装出一个能创建但跑不起来的环境，且报错信息晦涩难懂。这里显式检测并兜底。
PY_BIN=""
pick_python() {
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PY_BIN="$cand"
      return 0
    fi
  done
  return 1
}

if ! pick_python; then
  cur="$(python3 -V 2>&1 || echo '未安装')"
  echo "→ 未找到 Python >= 3.10（当前：${cur}），改用 uv 安装独立的 Python 3.12"
  if ! command -v uv >/dev/null 2>&1; then
    # uv 装到用户目录，不需要 root，也不污染系统 Python
    curl -fsSL https://astral.sh/uv/install.sh | sh
    for p in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
      [ -d "$p" ] && export PATH="$p:$PATH"
    done
  fi
  command -v uv >/dev/null 2>&1 || {
    echo "❌ uv 安装失败。请手动装 Python 3.10+ 后重试：" >&2
    echo "   Ubuntu/Debian: sudo apt install -y python3.12 python3.12-venv" >&2
    echo "   CentOS/RHEL:   sudo yum install -y python3.12" >&2
    echo "   macOS:         brew install python@3.12" >&2
    exit 1
  }
  uv python install 3.12
  PY_BIN="$(uv python find 3.12)"
fi
# 注意：变量后緊跟全角括号时必须用 ${} 包起来，
# 否则 bash 会把全角字符当成变量名的一部分，配合 set -u 会报 unbound variable。
echo "→ 使用 Python：$("$PY_BIN" -V 2>&1) （${PY_BIN}）"

if [ ! -d ".venv" ]; then
  echo "→ 创建虚拟环境 .venv"
  "$PY_BIN" -m venv .venv 2>/dev/null || {
    # 部分发行版把 venv 拆成单独包，缺失时用 uv 兜底
    echo "→ venv 模块不可用，改用 uv 创建虚拟环境"
    command -v uv >/dev/null 2>&1 || { curl -fsSL https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
    uv venv --python "$PY_BIN" .venv
  }
fi

# 校验虚拟环境确实是 3.10+，避免复用了历史遗留的旧环境
if ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
  echo "→ 检测到已有 .venv 版本过低（$(.venv/bin/python -V 2>&1)），重建"
  rm -rf .venv
  "$PY_BIN" -m venv .venv 2>/dev/null || uv venv --python "$PY_BIN" .venv
fi

# ---------- 依赖 ----------
echo "→ 安装依赖（requirements.txt）"
# uv 创建的虚拟环境默认不包含 pip，因此不能直接调 .venv/bin/pip
if .venv/bin/python -m pip --version >/dev/null 2>&1; then
  .venv/bin/python -m pip install --upgrade pip --quiet
  .venv/bin/python -m pip install -r requirements.txt
elif command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -r requirements.txt
else
  echo "❌ 虚拟环境内无 pip 且未找到 uv，无法安装依赖" >&2
  exit 1
fi

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
