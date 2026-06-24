import secrets
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.ark_service import (
    ArkConfigError,
    ask_json_text_only,
    ask_json_with_files,
    ask_text,
    ask_with_files,
    upload_pdf,
)
from app.audio_service import ArkAudioError, synthesize_speech, transcribe_audio
from app.prompts import (
    explain_prompt,
    quiz_generate_prompt,
    quiz_judge_prompt,
    teach_eval_prompt,
    teach_invite_prompt,
    variant_prompt,
    wrong_analysis_prompt,
)

app = FastAPI(title="数学语音学习")

_sessions: dict[str, dict] = {}
ALLOWED_GRADES = {"初一", "初二", "初三"}
ALLOWED_SUBJECTS = {"数学", "语文", "英语"}


class ChatRequest(BaseModel):
    message: str
    file_ids: list[str] = Field(default_factory=list)
    previous_response_id: str | None = None
    client_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    response_id: str
    client_id: str


class TtsRequest(BaseModel):
    text: str
    voice: str | None = None
    rate: float | None = None


class SessionStartRequest(BaseModel):
    grade: str
    subject: str
    file_ids: list[str] = Field(default_factory=list)
    client_id: str | None = None


class SessionStartResponse(BaseModel):
    client_id: str
    grade: str
    subject: str
    file_ids: list[str]
    message: str


class ClientOnlyRequest(BaseModel):
    client_id: str


class LessonResponse(BaseModel):
    lesson_text: str
    knowledge_points: list[str]


class QuizGenerateRequest(BaseModel):
    client_id: str
    count: int = 5


class QuizQuestion(BaseModel):
    id: str
    type: str
    type_label: str
    knowledge_point: str
    question_text: str
    options: list[str] = Field(default_factory=list)
    answer: str
    explanation: str


class QuizGenerateResponse(BaseModel):
    questions: list[QuizQuestion]


class QuizAnswerRequest(BaseModel):
    client_id: str
    question_id: str
    answer_text: str


class TeachEvaluateRequest(BaseModel):
    client_id: str
    explanation_text: str


MAX_TEACH_STUDENT_ROUNDS = 2


def _new_learning_state(grade: str, subject: str, file_ids: list[str]) -> dict[str, Any]:
    return {
        "grade": grade,
        "subject": subject,
        "file_ids": file_ids,
        "lesson_text": "",
        "knowledge_points": [],
        "questions": [],
        "answer_results": {},
        "correct_count": 0,
        "wrong_count": 0,
        "teach_unlocked": False,
        "variant_questions": [],
        "variant_answer_results": {},
        "teach_turns": [],
        "teach_student_rounds": 0,
        "learning_completed": False,
    }


def _format_teach_history(turns: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in turns:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        rnd = item.get("round")
        if role == "student":
            label = f"学生（第 {rnd} 轮）" if rnd else "学生"
        else:
            label = "AI老师"
        lines.append(f"{label}：{content}")
    return "\n".join(lines)


def _build_ai_turn_content(parsed: dict[str, Any], is_final_round: bool) -> str:
    feedback = str(parsed.get("feedback") or "你的思路不错，继续加油。")
    follow_up = str(parsed.get("follow_up_question") or "").strip()
    closing = str(parsed.get("closing_message") or "").strip()
    parts = [feedback]
    if follow_up and not is_final_round:
        parts.append(f"追问：{follow_up}")
    if closing and is_final_round:
        parts.append(closing)
    return "\n".join(parts)


_TYPE_LABELS = {"choice": "选择题", "judge": "判断题", "fill": "填空题"}


def _normalize_question(item: Any, idx: int, id_prefix: str = "q") -> QuizQuestion:
    q = item if isinstance(item, dict) else {}
    q_type = str(q.get("type") or "fill").strip().lower()
    if q_type not in {"choice", "judge", "fill"}:
        q_type = "fill"
    return QuizQuestion(
        id=str(q.get("id") or f"{id_prefix}{idx}"),
        type=q_type,
        type_label=str(q.get("type_label") or _TYPE_LABELS[q_type]),
        knowledge_point=str(q.get("knowledge_point") or "基础计算"),
        question_text=str(q.get("question_text") or "请根据讲解内容作答。"),
        options=[str(opt) for opt in (q.get("options") or [])][:4],
        answer=str(q.get("answer") or ""),
        explanation=str(q.get("explanation") or "请回顾课堂讲解。"),
    )


def _require_credentials(
    x_ark_api_key: str | None,
    x_ark_model: str | None,
) -> tuple[str, str]:
    api_key = config.resolve_api_key(x_ark_api_key)
    model = config.resolve_model(x_ark_model)
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="未配置 API Key：请在前端设置中填写，或在 .env 设置 ARK_API_KEY",
        )
    if not model:
        raise HTTPException(
            status_code=401,
            detail="未配置模型 ID：请在前端设置中填写，或在 .env 设置 ARK_MODEL",
        )
    return api_key, model


def _get_session_or_404(client_id: str) -> dict[str, Any]:
    session = _sessions.get(client_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在，请重新开始学习")
    return session


def _get_learning_or_400(session: dict[str, Any]) -> dict[str, Any]:
    learning = session.get("learning")
    if not isinstance(learning, dict):
        raise HTTPException(status_code=400, detail="学习会话未初始化，请先点击“开始学习”")
    return learning


def _norm_text(text: str) -> str:
    return (
        (text or "")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("。", "")
        .replace(".", "")
    )


def _update_stats(learning: dict[str, Any]) -> None:
    answer_results = learning.get("answer_results", {})
    correct_count = sum(1 for item in answer_results.values() if item.get("correct"))
    wrong_count = sum(1 for item in answer_results.values() if not item.get("correct"))
    learning["correct_count"] = correct_count
    learning["wrong_count"] = wrong_count
    learning["teach_unlocked"] = correct_count >= 3


@app.get("/api/health")
def health():
    env_ok = config.is_configured()
    return {
        "ok": env_ok,
        "configured": env_ok,
        "model": config.ARK_MODEL if config.ARK_MODEL else None,
        "voice_supported": True,
        "tts_voice": config.TTS_VOICE,
        "message": (
            "服务端 .env 已配置，可直接使用"
            if env_ok
            else "可在网页「设置」中填写 API Key 与模型 ID，或配置 .env"
        ),
    }


@app.post("/api/asr")
async def api_asr(
    audio: UploadFile = File(...),
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
):
    api_key, _ = _require_credentials(x_ark_api_key, None)
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="音频为空")
    if len(data) > config.MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"音频过大，最大 {config.MAX_AUDIO_MB} MB",
        )
    filename = audio.filename or "recording.webm"
    try:
        text = transcribe_audio(api_key, data, filename)
        return {"text": text}
    except ArkAudioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/tts")
def api_tts(
    body: TtsRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
):
    api_key, _ = _require_credentials(x_ark_api_key, None)
    try:
        result = synthesize_speech(
            api_key, body.text, voice=body.voice, rate=body.rate
        )
        return {
            "audio_url": result.get("audio_url"),
            "audio_base64": result.get("audio_base64"),
            "segments": result.get("segments") or [],
            "chunk_count": result.get("chunk_count", 1),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ArkAudioError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/session/start", response_model=SessionStartResponse)
def api_session_start(
    body: SessionStartRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    _require_credentials(x_ark_api_key, x_ark_model)
    grade = body.grade.strip()
    subject = body.subject.strip()
    if grade not in ALLOWED_GRADES:
        raise HTTPException(status_code=400, detail="年级仅支持：初一/初二/初三")
    if subject not in ALLOWED_SUBJECTS:
        raise HTTPException(status_code=400, detail="科目仅支持：数学/语文/英语")
    if not body.file_ids:
        raise HTTPException(status_code=400, detail="请先上传至少一个 PDF")

    client_id = body.client_id or secrets.token_hex(16)
    session = _sessions.setdefault(
        client_id,
        {"file_ids": [], "previous_response_id": None},
    )
    file_ids = list(dict.fromkeys(body.file_ids))
    session["file_ids"] = file_ids
    session["learning"] = _new_learning_state(grade=grade, subject=subject, file_ids=file_ids)
    return SessionStartResponse(
        client_id=client_id,
        grade=grade,
        subject=subject,
        file_ids=file_ids,
        message="学习会话已创建",
    )


@app.post("/api/lesson/explain", response_model=LessonResponse)
def api_lesson_explain(
    body: ClientOnlyRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)
    session = _get_session_or_404(body.client_id)
    learning = _get_learning_or_400(session)
    prompt = explain_prompt(learning["grade"], learning["subject"])
    try:
        lesson_text = ask_text(
            prompt=prompt,
            file_ids=learning["file_ids"],
            api_key=api_key,
            model=model,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"生成讲解失败: {e}") from e
    knowledge_points = []
    for idx, line in enumerate(lesson_text.splitlines()):
        clean = line.strip(" -：:.")
        if clean and len(clean) >= 4:
            knowledge_points.append(clean)
        if idx >= 4:
            break
    learning["lesson_text"] = lesson_text
    learning["knowledge_points"] = knowledge_points
    return LessonResponse(lesson_text=lesson_text, knowledge_points=knowledge_points)


@app.post("/api/quiz/generate", response_model=QuizGenerateResponse)
def api_quiz_generate(
    body: QuizGenerateRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)
    session = _get_session_or_404(body.client_id)
    learning = _get_learning_or_400(session)
    lesson_text = (learning.get("lesson_text") or "").strip()
    if not lesson_text:
        raise HTTPException(status_code=400, detail="请先完成 AI 讲解")

    count = max(3, min(5, body.count))
    prompt = quiz_generate_prompt(
        learning["grade"], learning["subject"], lesson_text, count
    )
    try:
        parsed = ask_json_with_files(
            prompt=prompt,
            file_ids=learning["file_ids"],
            api_key=api_key,
            model=model,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"生成题目失败: {e}") from e
    raw_questions = parsed.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise HTTPException(status_code=502, detail="模型未返回有效题目列表")

    questions: list[QuizQuestion] = []
    for idx, item in enumerate(raw_questions[:5], start=1):
        questions.append(_normalize_question(item, idx, "q"))
    learning["questions"] = [q.dict() for q in questions]
    learning["variant_questions"] = []
    learning["variant_answer_results"] = {}
    learning["answer_results"] = {}
    learning["correct_count"] = 0
    learning["wrong_count"] = 0
    learning["teach_unlocked"] = False
    return QuizGenerateResponse(questions=questions)


@app.post("/api/quiz/answer")
def api_quiz_answer(
    body: QuizAnswerRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)
    session = _get_session_or_404(body.client_id)
    learning = _get_learning_or_400(session)
    questions = learning.get("questions") or []
    target = next((q for q in questions if q.get("id") == body.question_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="题目不存在")
    if not body.answer_text.strip():
        raise HTTPException(status_code=400, detail="答案不能为空")

    prompt = quiz_judge_prompt(
        subject=learning["subject"],
        question_text=str(target.get("question_text") or ""),
        answer=str(target.get("answer") or ""),
        user_answer=body.answer_text,
        question_type=str(target.get("type") or "fill"),
    )
    try:
        judge = ask_json_text_only(prompt=prompt, api_key=api_key, model=model)
        correct = bool(judge.get("correct"))
        feedback = str(judge.get("feedback") or "")
    except Exception:
        correct = _norm_text(body.answer_text) == _norm_text(str(target.get("answer") or ""))
        feedback = "判题服务暂时不稳定，已使用标准答案进行判定。"

    learning["answer_results"][body.question_id] = {
        "question_id": body.question_id,
        "user_answer": body.answer_text.strip(),
        "correct": correct,
        "feedback": feedback,
        "question": target,
    }
    _update_stats(learning)
    return {
        "question_id": body.question_id,
        "correct": correct,
        "feedback": feedback or ("回答正确，继续保持。" if correct else "回答不正确，建议复习相关知识点。"),
        "stats": {
            "correct_count": learning["correct_count"],
            "wrong_count": learning["wrong_count"],
        },
        "teach_unlocked": learning["teach_unlocked"],
    }


@app.post("/api/analysis/wrong")
def api_analysis_wrong(
    body: ClientOnlyRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)
    session = _get_session_or_404(body.client_id)
    learning = _get_learning_or_400(session)
    answer_results = learning.get("answer_results") or {}
    wrong_items = [
        {
            "question_id": item.get("question_id"),
            "question_text": item.get("question", {}).get("question_text"),
            "knowledge_point": item.get("question", {}).get("knowledge_point"),
            "standard_answer": item.get("question", {}).get("answer"),
            "user_answer": item.get("user_answer"),
        }
        for item in answer_results.values()
        if not item.get("correct")
    ]
    if not wrong_items:
        learning["variant_questions"] = []
        learning["variant_answer_results"] = {}
        return {
            "skipped": True,
            "summary": "本轮没有错题，继续保持。可以直接进入向 AI 讲题环节。",
            "reasons": [],
            "variants": [],
        }

    try:
        analysis = ask_json_text_only(
            prompt=wrong_analysis_prompt(
                learning["grade"], learning["subject"], wrong_items
            ),
            api_key=api_key,
            model=model,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"错因分析失败: {e}") from e
    try:
        variants_raw = ask_json_text_only(
            prompt=variant_prompt(learning["grade"], learning["subject"], wrong_items),
            api_key=api_key,
            model=model,
        )
    except Exception:
        variants_raw = {"variants": []}

    raw_variants = variants_raw.get("variants")
    if not isinstance(raw_variants, list):
        raw_variants = []

    variant_questions: list[QuizQuestion] = []
    for idx, item in enumerate(raw_variants[:3], start=1):
        variant_questions.append(_normalize_question(item, idx, "v"))

    learning["variant_questions"] = [q.dict() for q in variant_questions]
    learning["variant_answer_results"] = {}

    return {
        "skipped": False,
        "summary": str(analysis.get("summary") or "已完成错题分析。"),
        "reasons": analysis.get("reasons") if isinstance(analysis.get("reasons"), list) else [],
        "variants": variant_questions,
    }


@app.post("/api/variants/answer")
def api_variants_answer(
    body: QuizAnswerRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)
    session = _get_session_or_404(body.client_id)
    learning = _get_learning_or_400(session)
    questions = learning.get("variant_questions") or []
    target = next((q for q in questions if q.get("id") == body.question_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="变式题不存在")
    if not body.answer_text.strip():
        raise HTTPException(status_code=400, detail="答案不能为空")

    prompt = quiz_judge_prompt(
        subject=learning["subject"],
        question_text=str(target.get("question_text") or ""),
        answer=str(target.get("answer") or ""),
        user_answer=body.answer_text,
        question_type=str(target.get("type") or "fill"),
    )
    try:
        judge = ask_json_text_only(prompt=prompt, api_key=api_key, model=model)
        correct = bool(judge.get("correct"))
        feedback = str(judge.get("feedback") or "")
    except Exception:
        correct = _norm_text(body.answer_text) == _norm_text(str(target.get("answer") or ""))
        feedback = "判题服务暂时不稳定，已使用标准答案进行判定。"

    variant_results = learning.setdefault("variant_answer_results", {})
    variant_results[body.question_id] = {
        "question_id": body.question_id,
        "user_answer": body.answer_text.strip(),
        "correct": correct,
        "feedback": feedback,
        "question": target,
    }
    variant_correct = sum(1 for item in variant_results.values() if item.get("correct"))
    variant_wrong = sum(1 for item in variant_results.values() if not item.get("correct"))
    return {
        "question_id": body.question_id,
        "correct": correct,
        "feedback": feedback or ("回答正确，继续保持。" if correct else "回答不正确，建议复习相关知识点。"),
        "stats": {
            "correct_count": variant_correct,
            "wrong_count": variant_wrong,
        },
    }


@app.post("/api/teach/invite")
def api_teach_invite(
    body: ClientOnlyRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)
    session = _get_session_or_404(body.client_id)
    learning = _get_learning_or_400(session)
    _update_stats(learning)
    if not learning["teach_unlocked"]:
        return {
            "teach_unlocked": False,
            "invite_text": "继续答题，累计答对 3 题后可解锁“向 AI 讲题”。",
        }
    lesson_text = learning.get("lesson_text") or "请回顾本次讲解内容。"
    try:
        invite_text = ask_text(
            prompt=teach_invite_prompt(
                learning["grade"], learning["subject"], lesson_text
            ),
            file_ids=learning["file_ids"],
            api_key=api_key,
            model=model,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"生成邀请失败: {e}") from e

    turns: list[dict[str, Any]] = list(learning.get("teach_turns") or [])
    if not any(t.get("role") == "ai" and t.get("content") == invite_text for t in turns):
        turns.append({"role": "ai", "content": invite_text, "round": None})
    learning["teach_turns"] = turns

    return {
        "teach_unlocked": True,
        "invite_text": invite_text,
        "turns": turns,
        "teach_student_rounds": learning.get("teach_student_rounds", 0),
        "max_rounds": MAX_TEACH_STUDENT_ROUNDS,
        "learning_completed": bool(learning.get("learning_completed")),
    }


@app.post("/api/teach/evaluate")
def api_teach_evaluate(
    body: TeachEvaluateRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)
    session = _get_session_or_404(body.client_id)
    learning = _get_learning_or_400(session)
    if not body.explanation_text.strip():
        raise HTTPException(status_code=400, detail="讲解内容不能为空")

    student_rounds = int(learning.get("teach_student_rounds") or 0)
    if learning.get("learning_completed"):
        raise HTTPException(status_code=400, detail="本次学习互讲已结束")
    if student_rounds >= MAX_TEACH_STUDENT_ROUNDS:
        raise HTTPException(
            status_code=400,
            detail=f"互讲已满 {MAX_TEACH_STUDENT_ROUNDS} 轮",
        )

    current_round = student_rounds + 1
    is_final_round = current_round >= MAX_TEACH_STUDENT_ROUNDS
    turns: list[dict[str, Any]] = list(learning.get("teach_turns") or [])
    student_text = body.explanation_text.strip()
    turns.append({"role": "student", "content": student_text, "round": current_round})

    lesson_text = learning.get("lesson_text") or "请结合你刚才学习的内容。"
    history = _format_teach_history(turns[:-1])
    prompt = teach_eval_prompt(
        grade=learning["grade"],
        subject=learning["subject"],
        lesson_text=lesson_text,
        explanation_text=student_text,
        history=history,
        round_num=current_round,
        is_final_round=is_final_round,
    )
    try:
        parsed = ask_json_text_only(prompt=prompt, api_key=api_key, model=model)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"评估讲解失败: {e}") from e

    result = str(parsed.get("result") or "partial")
    ai_content = _build_ai_turn_content(parsed, is_final_round)
    turns.append({"role": "ai", "content": ai_content, "round": current_round})

    learning["teach_turns"] = turns
    learning["teach_student_rounds"] = current_round
    completed = current_round >= MAX_TEACH_STUDENT_ROUNDS
    if completed:
        learning["learning_completed"] = True

    return {
        "result": result,
        "feedback": ai_content,
        "round": current_round,
        "max_rounds": MAX_TEACH_STUDENT_ROUNDS,
        "completed": completed,
        "turns": turns,
        "teach_student_rounds": current_round,
        "learning_completed": completed,
    }


@app.post("/api/upload")
async def api_upload(
    file: UploadFile = File(...),
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, _ = _require_credentials(x_ark_api_key, x_ark_model)

    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大，最大 {config.MAX_UPLOAD_MB} MB",
        )
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")

    safe_name = Path(filename).name
    local_path = config.UPLOAD_DIR / f"{uuid.uuid4().hex}_{safe_name}"
    local_path.write_bytes(data)

    try:
        result = upload_pdf(local_path, api_key=api_key)
        return {
            "file_id": result["file_id"],
            "filename": result["filename"],
            "size": len(data),
        }
    except ArkConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"上传到方舟失败: {e}") from e
    finally:
        local_path.unlink(missing_ok=True)


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(
    body: ChatRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)

    client_id = body.client_id or secrets.token_hex(16)
    session = _sessions.setdefault(
        client_id, {"file_ids": [], "previous_response_id": None}
    )

    file_ids = body.file_ids or session.get("file_ids", [])
    prev_id = body.previous_response_id or session.get("previous_response_id")

    try:
        result = ask_with_files(
            message=body.message,
            file_ids=file_ids if not prev_id else [],
            previous_response_id=prev_id,
            api_key=api_key,
            model=model,
        )
    except ArkConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"调用豆包 API 失败: {e}") from e

    session["previous_response_id"] = result["response_id"]
    if body.file_ids:
        session["file_ids"] = list(
            dict.fromkeys(session.get("file_ids", []) + body.file_ids)
        )

    return ChatResponse(
        reply=result["reply"],
        response_id=result["response_id"],
        client_id=client_id,
    )


@app.get("/")
def index():
    index_path = config.STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_path)


if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
