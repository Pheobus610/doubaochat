import asyncio
import logging
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote

import anyio.to_thread
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.ark_service import (
    ArkConfigError,
    ask_json_text_only,
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

logger = logging.getLogger("doubaochat")

# 应用日志默认没有 handler，logger.info/exception 会被丢弃，导致线上排查时
# 「清理任务异常」「预览路径非法」等关键信息完全看不到。这里挂到 uvicorn 的
# handler 上，与访问日志一起输出；独立运行（如测试）时退化为 basicConfig。
def _setup_logging() -> None:
    if logger.handlers:
        return
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger.handlers:
        for h in uvicorn_logger.handlers:
            logger.addHandler(h)
    else:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
        logger.addHandler(h)
    logger.setLevel(level)
    logger.propagate = False


_sessions: dict[str, dict] = {}
# 同步接口跑在线程池中（多线程），会话字典的"读改写"需要加锁。
# 单个 dict 的原子操作本身是安全的，但 setdefault + 逐项赋值的组合不是。
_sessions_lock = threading.Lock()


def _touch_session(session: dict[str, Any]) -> None:
    """记录会话最近活动时间，供 TTL 清理判定。"""
    session["last_active"] = time.time()


def _evict_if_over_capacity() -> int:
    """会话数超过上限时，淘汰最久未活动的会话（LRU），返回淘汰数量。

    没有上限时，并发用户增多会让内存在 TTL(默认2小时) 内单调增长。
    """
    limit = config.MAX_SESSIONS
    if limit <= 0 or len(_sessions) <= limit:
        return 0
    victims = sorted(_sessions.items(), key=lambda kv: kv[1].get("last_active", 0.0))
    drop = len(_sessions) - limit
    for cid, _ in victims[:drop]:
        _sessions.pop(cid, None)
    logger.warning("会话数超过上限 %d，已淘汰最久未活动的 %d 个", limit, drop)
    return drop


def _create_session(client_id: str) -> dict[str, Any]:
    """线程安全地获取或创建会话，并在超限时淘汰旧会话。"""
    with _sessions_lock:
        session = _sessions.setdefault(
            client_id,
            {"file_ids": [], "previous_response_id": None},
        )
        _touch_session(session)
        _evict_if_over_capacity()
        return session


def _sweep_expired_sessions() -> int:
    """删除超过 SESSION_TTL_SECONDS 无活动的会话，返回清理数量。"""
    now = time.time()
    ttl = config.SESSION_TTL_SECONDS
    with _sessions_lock:
        expired = [
            cid
            for cid, s in list(_sessions.items())
            if now - s.get("last_active", now) > ttl
        ]
        for cid in expired:
            _sessions.pop(cid, None)
        return len(expired)


# file_id -> 本地文件名（只存文件名，不存绝对路径），供左栏 PDF 预览
_preview_files: dict[str, str] = {}
_preview_lock = threading.Lock()


def _register_preview_file(file_id: str, filename: str) -> None:
    with _preview_lock:
        _preview_files[file_id] = filename


def _sweep_expired_uploads() -> int:
    """删除超过 UPLOAD_TTL_SECONDS 的本地 PDF 副本，返回清理数量。

    预览功能需要保留上传的 PDF，因此必须配套清理，否则磁盘会被撑满。
    """
    ttl = config.UPLOAD_TTL_SECONDS
    if ttl <= 0:
        return 0
    now = time.time()
    removed = 0
    upload_root = config.UPLOAD_DIR
    if not upload_root.is_dir():
        return 0
    alive: set[str] = set()
    for path in list(upload_root.iterdir()):
        try:
            if not path.is_file():
                continue
            if now - path.stat().st_mtime > ttl:
                path.unlink(missing_ok=True)
                removed += 1
            else:
                alive.add(path.name)
        except OSError:
            logger.warning("清理上传文件失败: %s", path.name)
    # 同步剔除注册表中已不存在的条目，避免字典无限增长
    with _preview_lock:
        for fid in [f for f, n in _preview_files.items() if n not in alive]:
            _preview_files.pop(fid, None)
    return removed


def _enforce_upload_quota() -> int:
    """uploads 目录总量超过上限时，从最旧的文件开始删，返回删除数量。

    TTL 只管"放得久"，管不了"来得猛"。若短时间内大量用户各传一个大文件，
    磁盘会在 TTL 到期前就被打满，因此需要按总容量兜底。
    """
    limit_mb = config.UPLOAD_MAX_TOTAL_MB
    if limit_mb <= 0:
        return 0
    upload_root = config.UPLOAD_DIR
    if not upload_root.is_dir():
        return 0
    limit = limit_mb * 1024 * 1024
    files: list[tuple[float, int, Path]] = []
    total = 0
    for path in list(upload_root.iterdir()):
        try:
            if not path.is_file():
                continue
            st = path.stat()
            files.append((st.st_mtime, st.st_size, path))
            total += st.st_size
        except OSError:
            continue
    if total <= limit:
        return 0
    files.sort(key=lambda x: x[0])  # 最旧在前
    removed = 0
    dropped: set[str] = set()
    for _mtime, size, path in files:
        if total <= limit:
            break
        try:
            path.unlink(missing_ok=True)
            total -= size
            removed += 1
            dropped.add(path.name)
        except OSError:
            logger.warning("清理超额上传文件失败: %s", path.name)
    if dropped:
        with _preview_lock:
            for fid in [f for f, n in _preview_files.items() if n in dropped]:
                _preview_files.pop(fid, None)
        logger.warning(
            "uploads 超过 %d MB 上限，已删除最旧的 %d 个文件", limit_mb, removed,
        )
    return removed


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动后台会话清理任务，关闭时取消。"""
    _setup_logging()
    # 扩大 anyio 线程池：所有同步接口与 run_in_threadpool 调用共用它，
    # 默认 40 在 20 并发（每人可能占 2~3 个）时会排队。
    try:
        anyio.to_thread.current_default_thread_limiter().total_tokens = (
            config.THREAD_POOL_SIZE
        )
        logger.info("线程池上限设为 %d", config.THREAD_POOL_SIZE)
    except Exception:
        # 调不动就用默认值，不该因此拖垮启动
        logger.exception("设置线程池上限失败，沿用默认值")

    async def _cleanup_loop():
        fails = 0
        while True:
            try:
                await asyncio.sleep(config.SESSION_CLEANUP_INTERVAL)
                n = _sweep_expired_sessions()
                if n:
                    logger.info("清理过期会话 %d 个，剩余 %d 个", n, len(_sessions))
                # 文件 IO 放线程池，避免阻塞事件循环
                f = await run_in_threadpool(_sweep_expired_uploads)
                if f:
                    logger.info("清理过期上传文件 %d 个", f)
                q = await run_in_threadpool(_enforce_upload_quota)
                if q:
                    logger.info("清理超额上传文件 %d 个", q)
                fails = 0
            except asyncio.CancelledError:
                raise  # 关闭流程，必须放行
            except Exception:
                # 长期挂载的关键：任何异常都不能让清理任务退出，
                # 否则此后再无人清理，磁盘会缓慢涨满且无人察觉。
                fails += 1
                logger.exception("清理任务异常（连续第 %d 次），将继续重试", fails)
                # 连续失败时退避，避免异常风暴刷爆日志
                if fails > 1:
                    await asyncio.sleep(min(60 * fails, 600))

    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Peertalk", lifespan=lifespan)
ALLOWED_GRADES = {"初一", "初二", "初三"}
ALLOWED_SUBJECTS = {"数学", "语文", "英语"}

# 访问口令放行的路径：首页、静态资源、健康检查。其余接口在开启 ACCESS_TOKEN 后需鉴权。
_PUBLIC_PATHS = {"/", "/api/health"}


@app.middleware("http")
async def access_token_gate(request: Request, call_next):
    # 访问口令校验（仅在配置 ACCESS_TOKEN 时生效）
    token = config.ACCESS_TOKEN
    if token:
        path = request.url.path
        if path not in _PUBLIC_PATHS and not path.startswith("/static"):
            provided = request.headers.get("x-access-token", "").strip()
            if not provided:
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    provided = auth[len("bearer "):].strip()
            if provided != token:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "需要访问口令：请在「设置」中填写访问口令后重试"},
                )
    # 全局异常兜底：未捕获异常返回结构化中文错误（不泄漏堆栈），服务端记录完整 traceback
    try:
        return await call_next(request)
    except Exception:
        logger.exception("未捕获异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误，请稍后重试"},
        )


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
            label = "AI同学"
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
    _touch_session(session)
    return session


def _get_learning_or_400(session: dict[str, Any]) -> dict[str, Any]:
    learning = session.get("learning")
    if not isinstance(learning, dict):
        raise HTTPException(status_code=400, detail="学习会话未初始化，请先点击“开始学习”")
    return learning


def _norm_text(text: str) -> str:
    return (text or "").strip().lower().replace(" ", "").replace("。", "").replace(".", "")


def _dump_question(q: QuizQuestion) -> dict[str, Any]:
    """兼容 Pydantic v1/v2 的模型序列化。"""
    if hasattr(q, "model_dump"):
        return q.model_dump()
    return q.dict()


_TIMEOUT_HINTS = ("timeout", "timed out", "read operation", "deadline")


def _is_timeout_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(hint in text for hint in _TIMEOUT_HINTS)


def _friendly_llm_error(exc: Exception, action: str) -> str:
    """把底层异常翻译成用户能看懂的中文提示。"""
    text = str(exc).lower()
    if _is_timeout_error(exc):
        return f"{action}超时：模型响应较慢，请点击按钮重试一次"
    if "429" in text or "rate" in text and "limit" in text:
        return f"{action}失败：请求过于频繁（限流），请稍等几秒后重试"
    if "401" in text or "invalid api key" in text or "authentication" in text:
        return f"{action}失败：API Key 无效，请在「设置」中检查"
    if "json" in text:
        return f"{action}失败：模型返回格式异常，请重试一次"
    return f"{action}失败：{exc}"


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
        # transcribe_audio 内部是同步 httpx 请求：必须放到线程池，
        # 否则会阻塞事件循环，导致其他所有用户的请求一起卡住。
        text = await run_in_threadpool(transcribe_audio, api_key, data, filename)
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
        result = synthesize_speech(api_key, body.text, voice=body.voice, rate=body.rate)
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
    session = _create_session(client_id)
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
    # 出题只依赖讲解文本，不需要重新解析 PDF：
    # 重传 file_ids 会让模型再读一遍几十页教辅，是此前"出题极慢/超时"的主因。
    # 讲解过长时截断，进一步压缩输入。
    lesson_for_prompt = lesson_text[: config.QUIZ_LESSON_MAX_CHARS]
    prompt = quiz_generate_prompt(
        learning["grade"], learning["subject"], lesson_for_prompt, count
    )
    started = time.monotonic()
    try:
        parsed = ask_json_text_only(
            prompt=prompt,
            api_key=api_key,
            model=model,
        )
    except Exception as e:
        logger.warning("生成题目失败（耗时 %.1fs）：%s", time.monotonic() - started, e)
        raise HTTPException(
            status_code=504 if _is_timeout_error(e) else 502,
            detail=_friendly_llm_error(e, "生成题目"),
        ) from e
    logger.info("生成题目完成，耗时 %.1fs", time.monotonic() - started)
    raw_questions = parsed.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise HTTPException(status_code=502, detail="模型未返回有效题目列表，请重试")

    questions: list[QuizQuestion] = []
    for idx, item in enumerate(raw_questions[:5], start=1):
        questions.append(_normalize_question(item, idx, "q"))
    learning["questions"] = [_dump_question(q) for q in questions]
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
        "feedback": feedback
        or ("回答正确，继续保持。" if correct else "回答不正确，建议复习相关知识点。"),
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
            prompt=wrong_analysis_prompt(learning["grade"], learning["subject"], wrong_items),
            api_key=api_key,
            model=model,
        )
    except Exception as e:
        raise HTTPException(
            status_code=504 if _is_timeout_error(e) else 502,
            detail=_friendly_llm_error(e, "错因分析"),
        ) from e
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

    learning["variant_questions"] = [_dump_question(q) for q in variant_questions]
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
        "feedback": feedback
        or ("回答正确，继续保持。" if correct else "回答不正确，建议复习相关知识点。"),
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
            prompt=teach_invite_prompt(learning["grade"], learning["subject"], lesson_text),
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

    ok = False
    try:
        # 写盘与 upload_pdf（含 wait_for_processing 轮询）都是阻塞操作，
        # 必须放到线程池，否则大文件上传期间整个服务无响应。
        await run_in_threadpool(local_path.write_bytes, data)
        result = await run_in_threadpool(partial(upload_pdf, local_path, api_key=api_key))
        file_id = result["file_id"]
        # 保留本地副本供前端左栏预览（方舟 file_id 无法直接给浏览器渲染）。
        # 只记录文件名，不暴露绝对路径，读取时统一在 UPLOAD_DIR 下解析。
        _register_preview_file(file_id, local_path.name)
        ok = True
        return {
            "file_id": file_id,
            "filename": result["filename"],
            "size": len(data),
            "preview_url": f"/api/file/{file_id}",
        }
    except ArkConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"上传到方舟失败: {e}") from e
    finally:
        # 仅在失败时清理；成功时保留副本用于预览，由 TTL 清理任务回收。
        if not ok:
            await run_in_threadpool(partial(local_path.unlink, missing_ok=True))


@app.get("/api/file/{file_id}")
def api_file_preview(file_id: str):
    """回传已上传的 PDF，供前端左栏常驻预览。

    安全要点：只接受注册过的 file_id，并把路径强制约束在 UPLOAD_DIR 内，
    避免通过 file_id 构造 ../ 实现路径穿越读取任意文件。
    """
    name = _preview_files.get(file_id)
    if not name:
        raise HTTPException(status_code=404, detail="文件不存在或已过期，请重新上传")

    upload_root = config.UPLOAD_DIR.resolve()
    try:
        target = (upload_root / name).resolve()
        # 双重保险：即使注册表被写入异常值，也不允许逃出上传目录
        target.relative_to(upload_root)
    except (ValueError, OSError) as e:
        logger.warning("预览路径非法: %s", name)
        raise HTTPException(status_code=404, detail="文件不存在") from e

    if not target.is_file():
        _preview_files.pop(file_id, None)
        raise HTTPException(status_code=404, detail="文件已被清理，请重新上传")

    # HTTP 头只能用 latin-1 编码，中文文件名会触发 UnicodeEncodeError。
    # 采用 RFC 5987：filename 给 ASCII 兜底，filename* 给非 ASCII 浏览器使用。
    ascii_name = target.name.encode("ascii", "ignore").decode("ascii") or "preview.pdf"
    quoted_name = quote(target.name, safe="")
    return FileResponse(
        target,
        media_type="application/pdf",
        # inline 让浏览器内嵌渲染而非下载
        headers={
            "Content-Disposition": (
                f'inline; filename="{ascii_name}"; '
                f"filename*=UTF-8''{quoted_name}"
            )
        },
    )


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(
    body: ChatRequest,
    x_ark_api_key: str | None = Header(default=None, alias="X-Ark-Api-Key"),
    x_ark_model: str | None = Header(default=None, alias="X-Ark-Model"),
):
    api_key, model = _require_credentials(x_ark_api_key, x_ark_model)

    client_id = body.client_id or secrets.token_hex(16)
    session = _create_session(client_id)

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
        session["file_ids"] = list(dict.fromkeys(session.get("file_ids", []) + body.file_ids))

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
