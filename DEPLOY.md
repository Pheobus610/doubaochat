# 部署指南

本文档介绍如何将 doubaochat 部署到服务器，支持 Docker（推荐）和原生两种方式。

## 服务器要求

| 项目 | 最低要求 | 推荐 |
|------|----------|------|
| CPU / 内存 | 1 核 1G | 2 核 2G |
| 操作系统 | Ubuntu 20.04+ / Debian 11+ / CentOS 8+ | Ubuntu 22.04 LTS |
| 网络 | 需访问 `ark.cn-beijing.volces.com`（火山方舟）和 `openspeech.bytedance.com`（语音） | 北京地域延迟最低 |
| 端口 | 放行 TCP 8000 | — |

> 地域建议：火山方舟与 OpenSpeech 服务均部署在北京，服务器选北京地域可获得最低延迟。

---

## 方式一：Docker 部署（推荐）

### 一键部署

SSH 登录服务器后，运行：

```bash
curl -fsSL https://raw.githubusercontent.com/Pheobus610/doubaochat/main/deploy.sh | bash
```

脚本会自动完成：安装 Docker → 克隆代码 → 创建 `.env` → 构建镜像 → 启动容器。

首次运行会提示编辑 `.env` 填入密钥，编辑后再次运行 `./deploy.sh` 即可启动。

### 手动步骤

如果想手动操作：

```bash
# 1. 安装 Docker
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker

# 2. 拉取代码
git clone https://github.com/Pheobus610/doubaochat.git
cd doubaochat

# 3. 配置环境变量
cp .env.example .env
nano .env   # 填入 API Key、模型 ID 等

# 4. 构建并启动
docker compose up -d --build
```

### 验证

```bash
curl http://127.0.0.1:8000/api/health
# 返回 {"ok": true, "configured": true, ...} 即正常
```

---

## 方式二：原生部署

适用于无法安装 Docker 的环境。

```bash
# 1. 安装 Python 3.10+
sudo apt update && sudo apt install -y python3 python3-venv git   # Ubuntu/Debian

# 2. 克隆并安装
git clone https://github.com/Pheobus610/doubaochat.git
cd doubaochat
./setup.sh    # 自动创建 venv、安装依赖、生成 .env

# 3. 配置密钥
nano .env

# 4. 启动（前台，用于测试）
./start.sh
```

### 生产常驻（systemd）

创建 `/etc/systemd/system/doubaochat.service`：

```ini
[Unit]
Description=doubaochat
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/doubaochat
ExecStart=/path/to/doubaochat/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now doubaochat
sudo systemctl status doubaochat     # 查看状态
journalctl -u doubaochat -f          # 查看日志
```

> 注意：原生生产模式**不要用 `--reload`**（`start.sh` 带 `--reload` 是开发用的）。

---

## 配置说明（.env）

| 变量 | 必填 | 说明 |
|------|------|------|
| `ARK_API_KEY` | ✅ | 火山方舟 API Key |
| `ARK_MODEL` | ✅ | 文本大模型 ID（如 `doubao-seed-2-1-turbo-260628`） |
| `ARK_BASE_URL` | — | 方舟 API 地址，默认 `https://ark.cn-beijing.volces.com/api/v3` |
| `SPEECH_PROVIDER` | — | 语音模式：`auto`（默认）/ `openspeech` / `ark` |
| `SPEECH_APPID` | — | OpenSpeech AppID（TTS 用，`auto` 模式下没配则回退走 Ark） |
| `SPEECH_TOKEN` | — | OpenSpeech Token |
| `TTS_VOICE` | — | 语音音色 ID，默认 `zh_female_cancan_mars_bigtts` |
| `TTS_RATE` | — | 语速，默认 `1.0` |
| `ACCESS_TOKEN` | — | 访问口令，公网暴露强烈建议设置 |
| `ARK_LLM_TIMEOUT` | — | LLM 调用超时（秒），默认 `60` |
| `ARK_LLM_MAX_RETRIES` | — | LLM 重试次数，默认 `2` |
| `SESSION_TTL_SECONDS` | — | 会话过期清理（秒），默认 `7200`（2小时） |
| `SESSION_CLEANUP_INTERVAL` | — | 清理扫描间隔（秒），默认 `600`（10分钟） |

---

## 防火墙 / 端口放行

### 腾讯云轻量应用服务器

控制台 → 实例详情 → **防火墙** → 添加规则：
- 协议：TCP
- 端口：8000
- 来源：0.0.0.0/0（或限制为你的 IP）

### 阿里云 ECS

安全组规则 → 入方向 → 添加：
- 协议：TCP
- 端口范围：8000/8000
- 授权对象：0.0.0.0/0

### 系统防火墙（如启用了 ufw）

```bash
sudo ufw allow 8000/tcp
sudo ufw reload
```

放行后访问 `http://服务器公网IP:8000`。

---

## HTTPS / 域名（可选，正式对外建议配置）

### 用 Caddy 自动 HTTPS（推荐）

创建 `docker-compose.https.yml`：

```yaml
services:
  web:
    build: .
    image: doubaochat
    container_name: doubaochat
    env_file: .env
    volumes:
      - ./uploads:/app/uploads
    restart: unless-stopped

  caddy:
    image: caddy:2
    container_name: caddy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
    restart: unless-stopped

volumes:
  caddy_data:
```

创建 `Caddyfile`（将 `your-domain.com` 换成你的域名）：

```
your-domain.com {
    reverse_proxy web:8000
}
```

启动：

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

> Caddy 会自动申请 Let's Encrypt 免费 SSL 证书，无需手动配置。
> 使用 HTTPS 后，防火墙放行 80 + 443 端口（而非 8000）。

---

## 访问控制

在 `.env` 中设置 `ACCESS_TOKEN`：

```env
ACCESS_TOKEN=你的随机口令
```

设置后，除首页、静态资源、健康检查外的所有接口都需要在请求头中携带口令：
- `Authorization: Bearer 你的随机口令`
- 或 `X-Access-Token: 你的随机口令`

前端用户在「设置 → 访问口令」中填写即可自动携带。

---

## 运维命令

### Docker

```bash
docker compose logs -f              # 查看实时日志
docker compose restart              # 重启服务
docker compose down                 # 停止并移除容器
docker compose up -d --build        # 重新构建并启动（更新代码后）

# 更新到最新版本
git pull && docker compose up -d --build
```

### 原生（systemd）

```bash
sudo systemctl restart doubaochat   # 重启
sudo systemctl stop doubaochat      # 停止
sudo systemctl status doubaochat    # 状态
journalctl -u doubaochat -f         # 实时日志
```

---

## 故障排查

| 症状 | 排查方法 |
|------|----------|
| 访问超时 / 无法打开 | 检查防火墙是否放行 8000 端口；`curl http://127.0.0.1:8000/api/health` 确认服务在跑 |
| 502 生成讲解失败 | 检查 `.env` 中 `ARK_API_KEY` / `ARK_MODEL` 是否正确；查看日志 `docker compose logs` |
| TTS 无声音 | 检查 `SPEECH_APPID` / `SPEECH_TOKEN` 是否填写；或设 `SPEECH_PROVIDER=ark` 走方舟 TTS |
| 401 需要访问口令 | 设置了 `ACCESS_TOKEN` 但前端没填；在「设置 → 访问口令」中填写 |
| 容器反复重启 | `docker compose logs` 查看错误；常见原因：`.env` 配置缺失、端口被占用 |
| 内存不足 (OOM) | 服务器内存 < 1G 时可能发生；升级配置或减少并发 |
| 会话丢失 | 进程/容器重启会清空内存会话（正常行为），用户需重新上传 PDF |

---

## 架构限制

- **单进程**：会话状态存储在进程内存中，不支持多 worker / 多实例水平扩展。
- **重启丢会话**：进程重启后，正在进行的讲解/题目/讲题状态会丢失（用户需重新上传 PDF）。已上传的 PDF 文件不丢（持久化到 `uploads/` 卷）。
- **并发上限 ≈ 40**：单进程 + 40 线程池。实际瓶颈通常是火山引擎账号的 QPS 限额。
