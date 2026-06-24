import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ARK_API_KEY = os.getenv("ARK_API_KEY", "").strip()
ARK_MODEL = os.getenv("ARK_MODEL", "").strip()
ARK_BASE_URL = os.getenv(
    "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
).strip().rstrip("/")

# Speech service compatibility (Volcengine openspeech docs 6561)
SPEECH_PROVIDER = os.getenv("SPEECH_PROVIDER", "auto").strip().lower()
SPEECH_BASE_URL = os.getenv(
    "SPEECH_BASE_URL", "https://openspeech.bytedance.com"
).strip().rstrip("/")
SPEECH_APPID = os.getenv("SPEECH_APPID", "").strip()
SPEECH_TOKEN = os.getenv("SPEECH_TOKEN", "").strip()
SPEECH_CLUSTER = os.getenv("SPEECH_CLUSTER", "volcano_tts").strip()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "25"))
MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
TTS_VOICE = os.getenv("TTS_VOICE", "zh_female_cancan_mars_bigtts")
TTS_RATE = float(os.getenv("TTS_RATE", "1.0"))
TTS_MAX_TEXT_BYTES = int(os.getenv("TTS_MAX_TEXT_BYTES", "900"))
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
