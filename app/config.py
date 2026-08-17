import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ARK_API_KEY = os.getenv("ARK_API_KEY", "").strip()
ARK_MODEL = os.getenv("ARK_MODEL", "").strip()
ARK_BASE_URL = (
    os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip().rstrip("/")
)

# Speech service compatibility (Volcengine openspeech docs 6561)
SPEECH_PROVIDER = os.getenv("SPEECH_PROVIDER", "auto").strip().lower()
SPEECH_BASE_URL = (
    os.getenv("SPEECH_BASE_URL", "https://openspeech.bytedance.com").strip().rstrip("/")
)
SPEECH_APPID = os.getenv("SPEECH_APPID", "").strip()
SPEECH_TOKEN = os.getenv("SPEECH_TOKEN", "").strip()
SPEECH_CLUSTER = os.getenv("SPEECH_CLUSTER", "volcano_tts").strip()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "25"))
MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# 访问控制：留空则不启用；设置后除 /、/static、/api/health 外的接口均需鉴权
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "").strip()
TTS_VOICE = os.getenv("TTS_VOICE", "zh_female_cancan_mars_bigtts")
TTS_RATE = float(os.getenv("TTS_RATE", "1.0"))
TTS_MAX_TEXT_BYTES = int(os.getenv("TTS_MAX_TEXT_BYTES", "900"))

# LLM 调用容错：超时（秒）与重试次数（火山方舟 SDK 内置指数退避重试 429/5xx/超时）
ARK_LLM_TIMEOUT = float(os.getenv("ARK_LLM_TIMEOUT", "60"))
ARK_LLM_MAX_RETRIES = int(os.getenv("ARK_LLM_MAX_RETRIES", "2"))

# 出题/判题等"结构化 JSON"调用的专用参数。
# 这类调用只需依据讲解文本生成短 JSON，不需要重新解析 PDF，
# 因此给更短的超时 + 更少的重试，避免用户在前端长时间空等。
ARK_JSON_TIMEOUT = float(os.getenv("ARK_JSON_TIMEOUT", "45"))
ARK_JSON_MAX_RETRIES = int(os.getenv("ARK_JSON_MAX_RETRIES", "1"))
# 结构化输出的最大 token 数：出题 JSON 通常 1000 token 内足够，
# 限制上限可显著降低"模型越写越长"导致的超时概率。
ARK_JSON_MAX_TOKENS = int(os.getenv("ARK_JSON_MAX_TOKENS", "2048"))
# 是否对结构化调用关闭深度思考（thinking）。深度思考会让出题耗时成倍增加。
ARK_DISABLE_THINKING = os.getenv("ARK_DISABLE_THINKING", "1").strip() not in {"0", "false", ""}
# 传给出题 prompt 的讲解文本最大字符数，避免讲解过长拖慢出题
QUIZ_LESSON_MAX_CHARS = int(os.getenv("QUIZ_LESSON_MAX_CHARS", "1200"))
# 会话过期清理：超过该时长无活动的会话自动删除（秒），防止内存无限增长
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "7200"))
# 清理任务执行间隔（秒）
SESSION_CLEANUP_INTERVAL = int(os.getenv("SESSION_CLEANUP_INTERVAL", "600"))
# 会话数量上限：达到上限时淘汰最久未活动的会话，防止并发用户过多时内存被打满
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "500"))
# 上传的 PDF 需保留以支持左栏预览，超过该时长后清理（秒，设 0 表示不清理）
# 默认与会话 TTL 保持一致（2 小时）：会话都过期了，PDF 再留着也无人预览。
UPLOAD_TTL_SECONDS = int(os.getenv("UPLOAD_TTL_SECONDS", "7200"))
# uploads 目录总容量上限（MB，设 0 表示不限）。
# 仅靠 TTL 无法防瞬时流量：若 2 小时内大量用户各传 50MB，磁盘仍会被撑满，
# 因此额外按总量做 LRU（删最早的）兑底。
UPLOAD_MAX_TOTAL_MB = int(os.getenv("UPLOAD_MAX_TOTAL_MB", "4096"))
# anyio 线程池上限。同步 def 接口（含所有 run_in_threadpool 调用）都跑在这里，
# 默认 40 在 20 并发下会触顶（每人可能同时占用出题预取 + TTS 合成 + 上传/判题）。
THREAD_POOL_SIZE = int(os.getenv("THREAD_POOL_SIZE", "80"))
# 应用日志级别（DEBUG/INFO/WARNING/ERROR）
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def is_configured() -> bool:
    return bool(ARK_API_KEY and ARK_MODEL)


def resolve_api_key(header_key: str | None) -> str:
    key = (header_key or "").strip()
    if key:
        return key
    return ARK_API_KEY


def resolve_model(header_model: str | None) -> str:
    model = (header_model or "").strip()
    if model:
        return model
    return ARK_MODEL
