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
# 会话过期清理：超过该时长无活动的会话自动删除（秒），防止内存无限增长
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "7200"))
# 清理任务执行间隔（秒）
SESSION_CLEANUP_INTERVAL = int(os.getenv("SESSION_CLEANUP_INTERVAL", "600"))

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
