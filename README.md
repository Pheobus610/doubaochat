# 数学语音学习 Demo（基于豆包 API）

这是一个基于 Python FastAPI 的单页应用，支持“初中数学”结构化学习流程：

1. 选择年级和科目（初一/初二/初三；数学/语文/英语）
2. 上传教辅 PDF
3. AI 讲解知识点（可语音播报）
4. 做题巩固（选择/判断/填空）
5. 错题分析与变式生成
6. 互讲互议（用户向 AI 讲题，AI鼓励+修正+追问）

## 功能亮点

- 固定流程界面，不依赖自由聊天输入
- 后端分接口实现讲解、出题、判题、分析、互讲评估
- 语音输入（ASR + Web Speech 降级）和语音输出（TTS）
- Prompt 在后端集中管理，提升输出稳定性
- API Key / 模型支持前端设置（sessionStorage）或 `.env`

## 前置条件

1. [火山方舟控制台](https://console.volcengine.com/ark) 注册并创建 API Key
2. 创建支持文档/PDF理解的接入点（`ep-xxxx` 或模型名）
3. 开通语音识别（ASR）与语音合成（TTS）权限
4. Python 3.9+

## 快速开始

```bash
cd ~/Desktop/doubaochat
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

可选配置 `.env`（网页设置会覆盖）：

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问地址：

- 本机：<http://127.0.0.1:8000>
- 局域网：`http://<本机IP>:8000`

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

进度会保存在浏览器 `sessionStorage`，刷新后可恢复年级与当前步骤（服务端重启后需重新「开始学习」）。

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
| POST | `/api/teach/invite` | 获取“向 AI 讲题”邀请语 |
| POST | `/api/teach/evaluate` | 评估用户讲题内容 |
| POST | `/api/asr` | 语音转文字 |
| POST | `/api/tts` | 文字转语音 |

## 语音排查

若 ASR/TTS 异常：

1. 确认账号开通语音能力
2. 核对 `ARK_BASE_URL` 和语音配置
3. 检查 `SPEECH_APPID`、`SPEECH_TOKEN`
4. 必要时按控制台最新文档调整 `app/audio_service.py`

ASR 失败时会尝试降级 Web Speech（推荐 Chrome/Edge）。

长文本播报：讲解内容超过 TTS 单次长度限制时，后端会按句号自动分块合成（默认每块约 900 字节），前端连续播放全部片段。可通过 `.env` 调整 `TTS_MAX_TEXT_BYTES`。

## 项目结构

```text
doubaochat/
  app/
    main.py
    ark_service.py
    audio_service.py
    prompts.py
    config.py
  static/
    index.html
    app.js
    voice.js
    styles.css
```

## 说明

- 当前版本为单会话模式，不含数据库和账号系统
- 不要把 API Key 提交到 git 仓库
- 模型与语音调用按官方计费
