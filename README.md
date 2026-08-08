# 数学语音学习 Demo（基于豆包 API）

[![CI](https://github.com/Pheobus610/doubaochat/actions/workflows/ci.yml/badge.svg)](https://github.com/Pheobus610/doubaochat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

一个基于 Python FastAPI 的单页应用，支持「初中」结构化学习流程：

1. 选择年级和科目（初一/初二/初三；数学/语文/英语）
2. 上传教辅 PDF
3. AI 讲解知识点（可语音播报）
4. 做题巩固（选择/判断/填空）
5. 错题分析与变式生成
6. 互讲互议（用户向 AI 讲题，AI 鼓励 + 修正 + 追问）

## 功能亮点

- 固定流程界面，不依赖自由聊天输入
- 后端分接口实现讲解、出题、判题、分析、互讲评估
- 语音输入（ASR + Web Speech 降级）和语音输出（TTS）
- Prompt 在后端集中管理，提升输出稳定性
- API Key / 模型支持前端设置（sessionStorage）或 `.env`
- 自带一键启动脚本与公网隧道脚本，便于向非局域网用户演示

## 前置条件

1. [火山方舟控制台](https://console.volcengine.com/ark) 注册并创建 API Key
2. 创建支持文档/PDF 理解的接入点（`ep-xxxx` 或模型名）
3. 开通语音识别（ASR）与语音合成（TTS）权限
4. Python **3.10+**（项目使用 `X | None` 语法）

## 快速开始

```bash
git clone https://github.com/Pheobus610/doubaochat.git
cd doubaochat
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

或直接使用一键启动脚本（自动创建虚拟环境并安装依赖）：

```bash
./start.sh
```

可选配置 `.env`（网页「设置」会覆盖）：

```bash
ARK_API_KEY=你的方舟_API_Key
ARK_MODEL=ep-xxxxxxxx

SPEECH_PROVIDER=auto
SPEECH_BASE_URL=https://openspeech.bytedance.com
SPEECH_APPID=你的语音应用AppID
SPEECH_TOKEN=你的语音Token
SPEECH_CLUSTER=volcano_tts
```

启动服务：

```bash
./start.sh
# 或手动：uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问地址：

- 本机：<http://127.0.0.1:8000>
- 局域网：`http://<本机IP>:8000`

## 远程访问指南（非局域网）

让非局域网用户访问的最简方式是**内网穿透**：本地启动服务后，用隧道工具把它暴露成一个公网 HTTPS 地址。

### 1. 启动本地服务

```bash
./start.sh          # 终端 1：启动后端
```

### 2. 建立公网隧道

```bash
./tunnel.sh         # 终端 2：建立隧道
```

首次使用需安装隧道工具（任选其一）：

```bash
brew install cloudflared          # 推荐：免费、无需账号
# 或
brew install ngrok/ngrok/ngrok    # 需注册并执行 ngrok config add-authtoken <Token>
```

`cloudflared` 会输出形如 `https://xxxx.trycloudflare.com` 的临时公网地址，分享给他人即可访问。

> 也支持一步到位：`TUNNEL=1 ./start.sh` 会在同一终端同时启动后端与隧道，Ctrl-C 一并退出。

### 3. 开启访问口令（强烈建议）

公网暴露后，建议在 `.env` 设置访问口令，防止接口被未授权调用、避免他人消耗你的方舟配额：

```bash
ACCESS_TOKEN=请使用一段足够随机的字符串
```

启用后，访问者首次操作时会被提示输入口令（在页面右上角「设置 → 访问口令」中填写）。

### 4. 安全注意事项

- 隧道地址默认走 HTTPS，浏览器才会允许使用麦克风（ASR）；纯 HTTP 公网地址会导致语音功能不可用。
- 切勿将 `.env` 或真实 API Key 提交到 Git。
- 临时隧道地址每次启动都会变；如需固定域名/证书，请改用云服务器 + 域名 + [Let's Encrypt](https://letsencrypt.org/) 方案，或 cloudflared 命名隧道。

### 5. 常见排查

| 现象 | 排查 |
|------|------|
| 隧道脚本提示未检测到工具 | 安装 `cloudflared` 或 `ngrok` 后重试 |
| 访问者打开页面是空白 | 确认 `./start.sh` 已就绪，且 `./tunnel.sh` 输出的地址正确 |
| 访问者提示「需要访问口令」 | 在 `.env` 设置了 `ACCESS_TOKEN`，访问者需在「设置」中填写 |
| 麦克风/语音不可用 | 确认使用 `https://` 地址，且浏览器已授权麦克风 |
| 端口被占用 | `PORT=8010 ./start.sh` 指定其他端口（隧道脚本同步 `PORT=8010 ./tunnel.sh`） |

## Docker 部署

```bash
docker compose up --build        # 一键构建并运行
```

访问 <http://localhost:8000>。配置通过 `.env` 注入，上传文件持久化到宿主机 `./uploads`。

## 使用流程

应用采用 **分步页面 + Hash 路由**，一次只显示一个步骤，可用浏览器前进/后退：

| 步骤 | 地址示例 |
|------|----------|
| 1 选年级 | `http://127.0.0.1:8000/#/grade` |
| 2 上传 PDF | `/#/upload` |
| 3 听讲解 | `/#/lesson` |
| 4 做题 | `/#/quiz` |
| 5 错题分析 | `/#/analysis` |
| 6 向 AI 讲题 | `/#/teach` |

操作顺序：

1. 打开页面，点击右上角「设置」填入 API Key 和模型
2. 在步骤 1 选择年级与科目（按钮会高亮并显示「已选：XX · 语文」等），再点「下一步」
3. 上传至少一个 PDF，点击「上传完成后，开始学习」（自动进入讲解页）
4. 点击「生成讲解」，可播报讲解内容
5. 点击「生成练习题」，按 A/B/C/D、对/错 或语音填空作答
6. 点击「生成错题分析」，查看错因与变式题
7. 答对 3 题后解锁「向 AI 讲题」，提交语音/文字讲解

进度保存在浏览器 `sessionStorage`，刷新后可恢复年级与当前步骤（服务端重启后需重新「开始学习」）。

## 核心接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/upload` | 上传 PDF |
| POST | `/api/session/start` | 创建学习会话（年级/科目/file_ids） |
| POST | `/api/lesson/explain` | 生成知识点讲解 |
| POST | `/api/quiz/generate` | 生成练习题 |
| POST | `/api/quiz/answer` | 提交单题答案并判定 |
| POST | `/api/analysis/wrong` | 生成错题分析与变式题 |
| POST | `/api/teach/invite` | 获取「向 AI 讲题」邀请语 |
| POST | `/api/teach/evaluate` | 评估用户讲题内容 |
| POST | `/api/asr` | 语音转文字 |
| POST | `/api/tts` | 文字转语音 |

> 开启 `ACCESS_TOKEN` 后，除 `/`、`/static/*`、`/api/health` 外的接口均需在请求头携带
> `Authorization: Bearer <ACCESS_TOKEN>` 或 `X-Access-Token: <ACCESS_TOKEN>`。

## 访问控制

- 在 `.env` 设置 `ACCESS_TOKEN` 即可启用服务端访问口令（留空则不启用，向后兼容）。
- 放行路径：首页 `/`、静态资源 `/static/*`、健康检查 `/api/health`。
- 前端用户在「设置 → 访问口令」中填入，后续所有接口调用会自动携带。

## 语音排查

若 ASR/TTS 异常：

1. 确认账号已开通语音能力
2. 核对 `ARK_BASE_URL` 和语音配置
3. 检查 `SPEECH_APPID`、`SPEECH_TOKEN`
4. 必要时按控制台最新文档调整 `app/audio_service.py`

ASR 失败时会尝试降级 Web Speech（推荐 Chrome/Edge）。

长文本播报：讲解内容超过 TTS 单次长度限制时，后端会按句号自动分块合成（默认每块约 900 字节），前端连续播放全部片段。可通过 `.env` 调整 `TTS_MAX_TEXT_BYTES`。

## 开发与测试

```bash
pip install -r requirements-dev.txt   # 含 ruff / pytest
ruff check .                          # 代码检查
pytest                                # 单元测试
```

可选 pre-commit 钩子（代码风格 + 密钥扫描）：

```bash
pip install pre-commit
pre-commit install
```

## 项目结构

```text
doubaochat/
  app/
    main.py            FastAPI 路由与访问控制中间件
    ark_service.py     方舟大模型调用
    audio_service.py   语音识别 / 合成
    prompts.py         Prompt 集中管理
    config.py          配置加载（含 ACCESS_TOKEN）
  static/              前端单页应用
  tests/               单元测试
  scripts/             pre-commit 密钥扫描脚本
  start.sh             本地一键启动
  tunnel.sh            公网隧道（cloudflared / ngrok）
  Dockerfile           容器镜像
  docker-compose.yml   一键容器部署
  requirements.txt     运行时依赖（已锁定版本）
  requirements-dev.txt 开发/测试依赖
  ruff.toml            代码检查配置
```

## 贡献

欢迎提 Issue 或 Pull Request。参与流程、代码风格与测试规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全

- 不要把 API Key 提交到 Git 仓库（`.env` 已在 `.gitignore` 中排除）。
- 公网部署请启用 `ACCESS_TOKEN` 并使用 HTTPS。
- 安全漏洞上报渠道见 [SECURITY.md](SECURITY.md)。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。模型与语音调用按火山方舟官方计费。
