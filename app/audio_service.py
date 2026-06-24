from __future__ import annotations

import base64
import re
import uuid
from typing import Any

import httpx

from app.config import (
    ARK_BASE_URL,
    SPEECH_APPID,
    SPEECH_BASE_URL,
    SPEECH_CLUSTER,
    SPEECH_PROVIDER,
    SPEECH_TOKEN,
    TTS_RATE,
    TTS_MAX_TEXT_BYTES,
    TTS_VOICE,
)


class ArkAudioError(Exception):
    pass


def _utf8_byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _clip_utf8_bytes(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    clipped = raw[:max_bytes]
    while clipped and (clipped[-1] & 0b1100_0000) == 0b1000_0000:
        clipped = clipped[:-1]
    return clipped.decode("utf-8", errors="ignore")


def _hard_split_text_by_bytes(text: str, max_bytes: int) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if _utf8_byte_len(remaining) <= max_bytes:
            chunks.append(remaining)
            break
        piece = _clip_utf8_bytes(remaining, max_bytes)
        if not piece:
            break
        chunks.append(piece)
        remaining = remaining[len(piece) :].strip()
    return [c for c in chunks if c]


def split_text_for_tts(text: str, max_bytes: int | None = None) -> list[str]:
    """Split long text into TTS-safe chunks at sentence boundaries."""
    limit = max_bytes if max_bytes is not None else TTS_MAX_TEXT_BYTES
    clean = (text or "").strip()
    if not clean:
        return []
    if _utf8_byte_len(clean) <= limit:
        return [clean]

    parts = re.split(r"(?<=[。！？；\n])", clean)
    chunks: list[str] = []
    current = ""
    for part in parts:
        if not part:
            continue
        candidate = current + part
        if _utf8_byte_len(candidate) <= limit:
            current = candidate
            continue
        if current.strip():
            chunks.append(current.strip())
        if _utf8_byte_len(part) > limit:
            chunks.extend(_hard_split_text_by_bytes(part, limit))
            current = ""
        else:
            current = part
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


def _ark_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
    }


def _openspeech_headers(token: str) -> dict[str, str]:
    # Doc 6561 examples use "Bearer;{token}" format.
    return {
        "Authorization": f"Bearer;{token}",
        "Content-Type": "application/json",
    }


def _parse_transcription(data: dict[str, Any]) -> str:
    if "text" in data and isinstance(data["text"], str):
        return data["text"].strip()
    if "transcript" in data and isinstance(data["transcript"], str):
        return data["transcript"].strip()
    result = data.get("result")
    if isinstance(result, dict) and isinstance(result.get("text"), str):
        return result["text"].strip()
    if isinstance(result, str):
        return result.strip()
    raise ArkAudioError(f"无法解析 ASR 响应: {data}")


def transcribe_audio(api_key: str, file_bytes: bytes, filename: str) -> str:
    url = f"{ARK_BASE_URL}/audio/transcriptions"
    content_type = "audio/webm"
    lower = filename.lower()
    if lower.endswith(".wav"):
        content_type = "audio/wav"
    elif lower.endswith(".mp3"):
        content_type = "audio/mpeg"
    elif lower.endswith(".m4a"):
        content_type = "audio/mp4"

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            url,
            headers=_ark_headers(api_key),
            files={"file": (filename, file_bytes, content_type)},
        )
        if response.status_code >= 400:
            detail = response.text[:500]
            raise ArkAudioError(
                f"ASR 请求失败 ({response.status_code}): {detail}"
            )
        if "application/json" in response.headers.get("content-type", ""):
            return _parse_transcription(response.json())
        text = response.text.strip()
        if text:
            return text
        raise ArkAudioError("ASR 返回空内容")


def _parse_tts_response(response: httpx.Response) -> dict[str, str | None]:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        data = response.json()
        for key in ("audio", "audio_url", "url"):
            val = data.get(key)
            if isinstance(val, str) and val:
                if val.startswith("http") or val.startswith("data:"):
                    return {"audio_url": val, "audio_base64": None}
                return {"audio_url": None, "audio_base64": val}
        if "data" in data and isinstance(data["data"], str):
            return {"audio_url": None, "audio_base64": data["data"]}
        raise ArkAudioError(f"无法解析 TTS 响应: {data}")
    if content_type.startswith("audio/"):
        encoded = base64.b64encode(response.content).decode("ascii")
        mime = content_type.split(";")[0].strip() or "audio/mpeg"
        return {
            "audio_url": f"data:{mime};base64,{encoded}",
            "audio_base64": encoded,
        }
    raise ArkAudioError(f"TTS 返回未知类型: {content_type}")


def _synthesize_via_ark(
    client: httpx.Client,
    api_key: str,
    text: str,
    voice: str,
    rate: float,
) -> dict[str, str | None]:
    url = f"{ARK_BASE_URL}/audio/synthesize"
    payload = {
        "text": text,
        "voice": voice,
        "rate": rate,
    }
    response = client.post(
        url,
        headers={**_ark_headers(api_key), "Content-Type": "application/json"},
        json=payload,
    )
    if response.status_code >= 400:
        detail = response.text[:500]
        raise ArkAudioError(
            f"Ark TTS 失败 ({response.status_code}): {detail}"
        )
    return _parse_tts_response(response)


def _synthesize_via_openspeech(
    client: httpx.Client,
    api_key: str,
    text: str,
    voice: str,
    rate: float,
) -> dict[str, str | None]:
    token = SPEECH_TOKEN or api_key
    appid = SPEECH_APPID
    if not token:
        raise ArkAudioError("openspeech TTS 缺少 token（SPEECH_TOKEN 或 API Key）")
    if not appid:
        raise ArkAudioError("openspeech TTS 缺少 SPEECH_APPID")

    # Caller must pass chunks already within TTS_MAX_TEXT_BYTES.
    if _utf8_byte_len(text) > TTS_MAX_TEXT_BYTES:
        text = _clip_utf8_bytes(text, TTS_MAX_TEXT_BYTES)

    # speed_ratio generally accepts 0.2~3.0; keep sane fallback.
    speed_ratio = max(0.2, min(rate, 3.0))
    payload = {
        "app": {
            "appid": appid,
            "token": "access_token",
            "cluster": SPEECH_CLUSTER,
        },
        "user": {"uid": "doubaochat"},
        "audio": {
            "voice_type": voice,
            "encoding": "mp3",
            "speed_ratio": speed_ratio,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
        },
        "request": {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "text_type": "plain",
            "operation": "query",
        },
    }
    url = f"{SPEECH_BASE_URL}/api/v1/tts"
    response = client.post(url, headers=_openspeech_headers(token), json=payload)
    if response.status_code >= 400:
        detail = response.text[:500]
        raise ArkAudioError(
            f"OpenSpeech TTS 失败 ({response.status_code}): {detail}"
        )
    parsed = _parse_tts_response(response)
    # OpenSpeech JSON often returns base64 audio data.
    if not parsed.get("audio_url") and parsed.get("audio_base64"):
        parsed["audio_url"] = f"data:audio/mpeg;base64,{parsed['audio_base64']}"
    return parsed


def _synthesize_single_chunk(
    client: httpx.Client,
    api_key: str,
    text: str,
    voice: str,
    rate: float,
) -> dict[str, str | None]:
    errors: list[str] = []
    provider = SPEECH_PROVIDER if SPEECH_PROVIDER in {"ark", "openspeech", "auto"} else "auto"
    order: list[str]
    if provider == "ark":
        order = ["ark"]
    elif provider == "openspeech":
        order = ["openspeech"]
    else:
        order = ["openspeech", "ark"] if SPEECH_APPID else ["ark", "openspeech"]

    for mode in order:
        try:
            if mode == "openspeech":
                return _synthesize_via_openspeech(
                    client, api_key, text, voice, rate
                )
            return _synthesize_via_ark(client, api_key, text, voice, rate)
        except ArkAudioError as exc:
            errors.append(str(exc))
    raise ArkAudioError(" | ".join(errors) or "TTS 请求失败")


def synthesize_speech(
    api_key: str,
    text: str,
    voice: str | None = None,
    rate: float | None = None,
) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("播报文本不能为空")
    clean_text = text.strip()
    selected_voice = voice or TTS_VOICE
    selected_rate = rate if rate is not None else TTS_RATE
    chunks = split_text_for_tts(clean_text, TTS_MAX_TEXT_BYTES)

    segments: list[dict[str, Any]] = []
    with httpx.Client(timeout=120.0) as client:
        for index, chunk in enumerate(chunks):
            result = _synthesize_single_chunk(
                client, api_key, chunk, selected_voice, selected_rate
            )
            segments.append(
                {
                    "index": index,
                    "audio_url": result.get("audio_url"),
                    "audio_base64": result.get("audio_base64"),
                }
            )

    first = segments[0] if segments else {}
    return {
        "segments": segments,
        "chunk_count": len(segments),
        "audio_url": first.get("audio_url"),
        "audio_base64": first.get("audio_base64"),
    }
