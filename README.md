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

> 若系统自带 Python 低于 3.10（如 macOS 自带 3.9，会报 `unsupported operand type(s) for |`），
> 可用 [uv](https://github.com/astral-sh/uv) 免 sudo 装一个独立 Python：
>
> ```bash
> curl -fsSL https://astral.sh/uv/install.sh | sh
> uv python install 3.12
> uv venv --python 3.12 .venv
> uv pip install --python .venv/bin/python -r requirements.txt
> ```

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

## 服务器部署（长期挂载）

### 一键安装（全新空机器）

```bash
curl -fsSL https://raw.githubusercontent.com/Pheobus610/doubaochat/main/install.sh | bash
```

或已克隆后：

```bash
./install.sh              # 自动选择 Docker / 裸机
./install.sh --docker     # 强制 Docker
./install.sh --bare       # 强制裸机 venv
./install.sh --yes        # 全默认，不交互（自动化场景）
```

脚本会依次处理：基础命令（curl/git）→ Python 环境 → 配置文件 → 启动 → 可选注册开机自启。

**Python 版本兼容**：代码使用 `X | None` 语法，需 3.10+。在只有 Python 3.9 的老系统
（CentOS 7、Ubuntu 20.04 等）上，脚本会自动用 `uv` 安装独立的 Python 3.12，
不需要 root，也不污染系统 Python。

### 日常运维

```bash
./server.sh start              # 后台启动
./server.sh stop               # 停止
./server.sh restart            # 重启
./server.sh status             # 状态 + 健康检查 + 内存/磁盘占用
./server.sh logs               # 跟踪日志
./server.sh update             # 拉取最新代码并重启
./server.sh install-service    # 注册开机自启（长期挂载建议开启）
```

脚本自动识别运行方式（Docker / systemd / nohup），无需关心底层差异。

### 长期挂载的鲁棒性设计

| 机制 | 说明 |
| --- | --- |
| 进程自动重启 | Docker `restart: always`；systemd `Restart=always` + `RestartSec=5` |
| 防重启风暴 | systemd `StartLimitBurst=10`（10 分钟内超 10 次则停下等人工介入） |
| 内存上限 | 512M。实测 500 会话仅约 13MB，余量充足 |
| 日志轮转 | 单文件 10MB × 3。**Docker 默认日志无上限**，长期挂载几个月后可能比数据还大 |
| 会话清理 | 2 小时无活动自动删除 + `MAX_SESSIONS` LRU 淘汰 |
| 磁盘清理 | PDF 按 `UPLOAD_TTL_SECONDS`（2h）过期清理，另有 `UPLOAD_MAX_TOTAL_MB` 容量兜底 |
| 清理任务容错 | 任何异常都不会让清理任务退出，并按失败次数退避，避免异常风暴刷爆日志 |
| 健康探针 | 每 30s 探活 `/api/health`，连续 3 次失败标记 unhealthy |

> `nohup` 方式（未注册 systemd）在崩溃后**不会**自动重启，长期挂载请务必执行
> `./server.sh install-service`。

### 关于 20 并发

实测可支撑（20 并发出题完全并行，期间 `/api/health` 响应 2.4ms）。关键配置是
`THREAD_POOL_SIZE=80`：

anyio 线程池默认上限 40，而每个活跃用户可能同时占用 2~3 个线程（出题预取 +
TTS 合成 + 偶发上传/判题）。实测 60 并发请求下，线程池 40 时峰值并发**卡死在 40**、
耗时 4.0s；调到 80 后峰值达 60、耗时 2.1s（**降低 49%**）。

**必须单 worker**：会话状态存在进程内存字典中，`--workers > 1` 会让同一用户的请求
随机命中不同进程，随机报「会话不存在」。本应用是 IO 密集（等 LLM）而非 CPU 密集，
单 worker + 大线程池已足够，多核用不上影响很小。

若将来需要多机/多 worker 横向扩展，需先把会话状态迁移到 Redis。

### 真实瓶颈提示

前端有自动生成与预取机制，**用户进入页面即消耗 API 调用**。20 并发下真正的天花板
通常是方舟侧的 QPS/TPM 限流，而不是本服务的处理能力。压测前建议先确认账号配额。

## Docker 部署

```bash
docker compose up -d --build        # 一键构建并后台运行
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

## 界面与体验

### 左栏 PDF 常驻预览

上传的 PDF 会保留在服务端 `uploads/`，并通过 `GET /api/file/{file_id}` 内嵌到左栏，
学习的每个阶段都能随时对照原文：

- 多个 PDF 时左栏顶部出现下拉框切换。
- 点击 `‹` 可收起左栏，偏好会记住；窄屏（≤900px）自动改为上下堆叠。
- 未上传 PDF 时左栏隐藏，界面与原来的单列布局一致。
- 文件超过 `UPLOAD_TTL_SECONDS`（默认 24 小时）后由后台任务清理，避免磁盘堆积。

### 自动生成与提前预生成

为减少等待，做了两件事：

1. **进入页面即自动生成**：讲解 / 出题 / 错题分析在首次进入对应页面时自动开始，
   不需要先点按钮。已有内容后按钮会变成「重新生成…」，作为换一批或失败重试的入口。
2. **跨阶段提前预生成**：讲解生成完成后，会立即在后台并行开始出题
   （出题只依赖讲解文本，与语音合成互不影响）。用户听讲解语音的这段时间
   题目已经算好，进入做题页几乎 0 等待。

> 注意：错题分析与变式题必须依据实际答题结果，无法提前生成，因此不做预取。

## 并发与多用户

服务可同时服务多个用户，但有几点需要了解：

- **不要用 `--reload` 跑生产**：它是给开发用的（改动即重启，会中断在途请求）。
  生产请用 `./server.sh start`，或直接：
  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
  ```
- **必须 `--workers 1`**：见下方「会话存在进程内存里」。切勿改成多 worker。
- **会话存在进程内存里**（`_sessions` 字典），因此：
  - 多 worker 下同一用户的请求可能落到不同进程，导致「会话不存在」。需要多 worker 时应先把会话改存 Redis。
  - 服务重启后所有会话丢失（前端已能自愈：收到 404 会引导重新开始）。
  - 会话数超过 `MAX_SESSIONS`（默认 500）时按 LRU 淘汰最久未活动的，防止内存被打满。
- **同步接口自动跑在线程池**，互不阻塞；`async` 接口内的阻塞调用已统一用
  `run_in_threadpool` 调度，避免一个用户的慢请求冻结整个服务。
  线程池上限由 `THREAD_POOL_SIZE`（默认 80）控制 —— anyio 原生默认 40，
  实测在 20 并发下会触顶（每人可能占 2~3 个线程）。
- **真正的并发瓶颈是方舟侧的限流（RPM/TPM）**，而不是本服务。多人同时出题若出现
  `请求过于频繁（限流）`，需要在方舟控制台提升配额。

## 生成速度调优（出题/判题变慢或超时）

出题、判题、错因分析属于「结构化 JSON」调用，**只依据讲解文本生成，不再重复上传 PDF**
（重传 PDF 会让模型每次都重新解析整份教辅，是出题极慢与超时的主因）。

相关 `.env` 参数：

| 变量 | 默认 | 说明 |
|------|------|------|
| `ARK_JSON_TIMEOUT` | 45 | 结构化调用超时（秒），比带 PDF 的调用更短，让失败更快暴露 |
| `ARK_JSON_MAX_RETRIES` | 1 | SDK 网络层重试次数；调大会成倍拉长最坏等待时间 |
| `ARK_JSON_MAX_TOKENS` | 2048 | 输出上限，防止模型「越写越长」而超时 |
| `ARK_DISABLE_THINKING` | 1 | 关闭深度思考；开启会让出题耗时成倍增加 |
| `QUIZ_LESSON_MAX_CHARS` | 1200 | 传给出题 prompt 的讲解文本上限 |

若仍偶发超时：

1. 优先确认接入点模型规格（深度思考类模型即使关闭 thinking 也偏慢）。
2. 适度下调 `ARK_JSON_MAX_TOKENS` 与 `QUIZ_LESSON_MAX_CHARS`。
3. 前端已对各接口设置超时上限（出题 90 秒），超时会提示重试而非无限等待。

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
