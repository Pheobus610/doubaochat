#!/usr/bin/env bash
# 本地演示模式：用假数据替换所有 AI 调用，无需真实 API Key 即可完整走一遍流程。
#
# 用途：验证界面、PDF 左栏预览、自动生成、预取等改动，不消耗真实额度。
# 用法：
#   ./demo.sh            默认 8000 端口
#   PORT=8080 ./demo.sh  换端口
#
# 注意：这不是生产启动方式，仅用于本地验证。真实使用请配好 .env 后跑 ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

if [ ! -x .venv/bin/python ]; then
  echo "❌ 未找到虚拟环境，请先运行 ./setup.sh" >&2
  exit 1
fi

cat <<EOF

==============================================
  演示模式（假数据，不调用真实 AI）
==============================================
  访问     : http://127.0.0.1:$PORT
  讲解     : 约 1 秒返回固定文本
  出题     : 约 3 秒返回 5 道固定题目
  语音     : 静音占位（不真实合成）

  可验证：左栏 PDF 预览 / 进页面自动生成 /
          讲解完成后后台预取出题（进做题页几乎不等待）

  Ctrl-C 退出
==============================================

EOF

exec .venv/bin/python - "$PORT" <<'PYEOF'
import sys, time, base64, io
sys.path.insert(0, ".")

from app import config, main

# 绕过配置检查（演示模式不需要真 Key）
config.ARK_API_KEY = "demo-key"
config.ARK_MODEL = "demo-endpoint"

# ---- 假的上传：不真的传到方舟，但保留本地文件以便左栏预览 ----
_seq = {"n": 0}
def fake_upload_pdf(path, api_key=None):
    _seq["n"] += 1
    time.sleep(0.3)
    return {"file_id": f"demo-file-{_seq['n']}", "filename": path.name}
main.upload_pdf = fake_upload_pdf

# ---- 假的讲解 ----
def fake_ask_text(prompt, file_ids=None, api_key=None, model=None, **kw):
    time.sleep(1.0)
    return (
        "一、本节知识点\n"
        "分数的加减法：分母不同时必须先通分，化为同分母后再加减。\n\n"
        "二、解题步骤\n"
        "第一步，观察分母，求出最小公倍数；\n"
        "第二步，把各分数化为同分母；\n"
        "第三步，分子相加减，分母不变；\n"
        "第四步，检查结果能否约分。\n\n"
        "三、易错点\n"
        "最常见的错误是分子分母直接相加（如 1/2+1/3 错算成 2/5），"
        "以及算完忘记约分。\n\n"
        "（演示模式：以上为固定文本，未调用真实模型）"
    )
main.ask_text = fake_ask_text

# ---- 假的结构化输出（出题 / 判题 / 错因分析 / 变式题）----
_QUIZ = [
    {
        "id": f"q{i}",
        "type": "choice",
        "type_label": "选择题",
        "knowledge_point": "分数加减法与通分",
        "question_text": f"（演示第 {i} 题）计算 1/2 + 1/3 = ?",
        "options": ["A. 5/6", "B. 2/5", "C. 1/6", "D. 2/3"],
        "answer": "A",
        "explanation": "通分为 3/6 + 2/6 = 5/6，故选 A。",
    }
    for i in range(1, 6)
]

def fake_ask_json(prompt, api_key=None, model=None, **kw):
    p = str(prompt)
    # 出题：故意慢一点，方便观察"预取"带来的体感差异
    if "出题" in p or "题目" in p or "questions" in p:
        time.sleep(3.0)
        return {"questions": [dict(q) for q in _QUIZ]}
    # 变式题
    if "变式" in p or "variants" in p:
        time.sleep(1.5)
        return {
            "variants": [
                {**dict(q), "id": f"v{i}", "question_text": f"（演示变式 {i}）计算 2/3 + 1/4 = ?",
                 "options": ["A. 11/12", "B. 3/7", "C. 1/2", "D. 5/12"], "answer": "A",
                 "explanation": "通分为 8/12 + 3/12 = 11/12。"}
                for i, q in enumerate(_QUIZ[:3], start=1)
            ]
        }
    # 错因分析
    if "错因" in p or "分析" in p or "reasons" in p:
        time.sleep(1.5)
        return {
            "summary": "（演示）主要问题集中在通分环节，建议加强最小公倍数的练习。",
            "reasons": [
                {"knowledge_point": "通分", "reason": "未找到最小公倍数就直接相加",
                 "suggestion": "先列出两个分母的倍数，找到最小公倍数再计算"},
            ],
        }
    # 判题
    time.sleep(0.8)
    return {"correct": True, "feedback": "（演示）思路正确，通分这一步处理得很好。"}
main.ask_json_text_only = fake_ask_json

# ---- 假的语音合成：返回一段极短的静音 WAV，前端能正常走播放流程 ----
def _silent_wav(seconds=1):
    import struct
    rate, n = 8000, 8000 * seconds
    data = b"\x00\x00" * n
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
    hdr += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    hdr += b"data" + struct.pack("<I", len(data))
    return hdr + data

def fake_tts(api_key, text, voice=None, rate=None):
    time.sleep(0.5)
    return {
        "audio_url": None,
        "audio_base64": base64.b64encode(_silent_wav()).decode("ascii"),
        "mime_type": "audio/wav",
        "segments": [],
        "chunk_count": 1,
    }
main.synthesize_speech = fake_tts

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
import uvicorn
uvicorn.run(main.app, host="127.0.0.1", port=port, log_level="info")
PYEOF
