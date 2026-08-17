from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from volcenginesdkarkruntime import Ark

from app.config import (
    ARK_API_KEY,
    ARK_BASE_URL,
    ARK_DISABLE_THINKING,
    ARK_JSON_MAX_RETRIES,
    ARK_JSON_MAX_TOKENS,
    ARK_JSON_TIMEOUT,
    ARK_LLM_MAX_RETRIES,
    ARK_LLM_TIMEOUT,
    ARK_MODEL,
)

logger = logging.getLogger("doubaochat.ark")


class ArkConfigError(Exception):
    pass


def _resolve_credentials(api_key: str | None, model: str | None) -> tuple[str, str]:
    key = (api_key or "").strip() or ARK_API_KEY
    mdl = (model or "").strip() or ARK_MODEL
    if not key or not mdl:
        raise ArkConfigError(
            "请在前端设置中填写 API Key 和模型 ID，或在 .env 中配置 ARK_API_KEY 和 ARK_MODEL"
        )
    return key, mdl


def _make_client(api_key: str, timeout: float | None = None, max_retries: int | None = None) -> Ark:
    """构造带超时与重试的 Ark 客户端（SDK 内置指数退避，覆盖 429/5xx/超时）。"""
    return Ark(
        api_key=api_key,
        base_url=ARK_BASE_URL,
        timeout=ARK_LLM_TIMEOUT if timeout is None else timeout,
        max_retries=ARK_LLM_MAX_RETRIES if max_retries is None else max_retries,
    )


def _create_response(client: Ark, **kwargs: Any) -> Any:
    """调用 responses.create，并对"不支持的参数"自动降级重试。

    不同接入点/模型对 thinking、max_output_tokens 的支持程度不一致，
    直接传参可能被服务端拒绝（400）。这里逐个剥离可选参数后重试，
    保证在任何接入点上都能跑通。
    """
    optional_keys = ["thinking", "max_output_tokens"]
    attempt_kwargs = dict(kwargs)
    while True:
        try:
            return client.responses.create(**attempt_kwargs)
        except Exception as exc:  # noqa: BLE001 - 需按错误内容判定是否降级
            message = str(exc).lower()
            dropped = None
            for key in optional_keys:
                if key in attempt_kwargs and key in message:
                    dropped = key
                    break
            # 参数不被支持时错误信息未必包含字段名，兜底：只要是 400 就逐个剥离
            if dropped is None and "400" in message:
                for key in optional_keys:
                    if key in attempt_kwargs:
                        dropped = key
                        break
            if dropped is None:
                raise
            attempt_kwargs.pop(dropped, None)
            logger.warning("接入点不支持参数 %s，已剥离后重试", dropped)


def _json_call_kwargs() -> dict[str, Any]:
    """结构化 JSON 调用的加速参数：关闭深度思考 + 限制输出长度。"""
    kwargs: dict[str, Any] = {"max_output_tokens": ARK_JSON_MAX_TOKENS}
    if ARK_DISABLE_THINKING:
        kwargs["thinking"] = {"type": "disabled"}
    return kwargs


def _client(api_key: str | None = None) -> Ark:
    key, _ = _resolve_credentials(api_key, None)
    return _make_client(key)


def upload_pdf(local_path: Path, api_key: str | None = None) -> dict[str, str]:
    client = _client(api_key)
    with open(local_path, "rb") as f:
        file_obj = client.files.create(file=f, purpose="user_data")
    processed = client.files.wait_for_processing(id=file_obj.id)
    if processed.status != "active":
        raise RuntimeError(f"PDF 处理失败，状态: {processed.status}（file_id={processed.id}）")
    return {"file_id": processed.id, "filename": local_path.name}


def _extract_text_from_response(response: Any) -> str:
    parts: list[str] = []
    output = getattr(response, "output", None) or []
    for item in output:
        item_type = getattr(item, "type", None) or (
            item.get("type") if isinstance(item, dict) else None
        )
        if item_type != "message":
            continue
        content = getattr(item, "content", None) or (
            item.get("content") if isinstance(item, dict) else []
        )
        if not content:
            continue
        for block in content:
            block_type = getattr(block, "type", None) or (
                block.get("type") if isinstance(block, dict) else None
            )
            if block_type in ("output_text", "text"):
                text = getattr(block, "text", None) or (
                    block.get("text") if isinstance(block, dict) else ""
                )
                if text:
                    parts.append(text)
    return "\n".join(parts).strip() or "（模型未返回文本内容）"


def ask_with_files(
    message: str,
    file_ids: list[str],
    previous_response_id: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    if not message.strip():
        raise ValueError("问题不能为空")
    if not file_ids and not previous_response_id:
        raise ValueError("请先上传 PDF 参考资料，或继续已有对话")

    key, mdl = _resolve_credentials(api_key, model)
    client = _make_client(key)
    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": message.strip()},
    ]
    for fid in file_ids:
        content.append({"type": "input_file", "file_id": fid})

    kwargs: dict[str, Any] = {
        "model": mdl,
        "input": [{"role": "user", "content": content}],
    }
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
        kwargs["input"] = [
            {"role": "user", "content": [{"type": "input_text", "text": message.strip()}]}
        ]

    response = _create_response(client, **kwargs)
    reply = _extract_text_from_response(response)
    return {
        "reply": reply,
        "response_id": response.id,
    }


def ask_text(
    prompt: str,
    file_ids: list[str],
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    if not prompt.strip():
        raise ValueError("prompt 不能为空")
    if not file_ids:
        raise ValueError("请先上传 PDF 参考资料")
    key, mdl = _resolve_credentials(api_key, model)
    client = _make_client(key)
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt.strip()}]
    for fid in file_ids:
        content.append({"type": "input_file", "file_id": fid})
    response = _create_response(
        client,
        model=mdl,
        input=[{"role": "user", "content": content}],
    )
    return _extract_text_from_response(response)


def _extract_json_string(text: str) -> str:
    stripped = text.strip()
    # 去掉常见的 ```json ... ``` 包裹
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        raise ValueError(f"模型未返回 JSON: {text[:300]}")
    return match.group(0)


def _parse_json_object(raw: str) -> dict[str, Any]:
    json_text = _extract_json_string(raw)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        fixed = json_text.replace("```json", "").replace("```", "").strip()
        # 容错：去掉对象/数组末尾多余的逗号
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        parsed = json.loads(fixed)
    if not isinstance(parsed, dict):
        raise ValueError("模型 JSON 输出不是对象")
    return parsed


def ask_json_with_files(
    prompt: str,
    file_ids: list[str],
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    raw = ask_text(prompt=prompt, file_ids=file_ids, api_key=api_key, model=model)
    return _parse_json_object(raw)


def _should_retry_json(exc: Exception) -> bool:
    """仅对"快速失败"的错误做应用层重试。

    超时类错误重试会让总耗时翻倍（可能超出前端等待上限），
    因此超时直接上抛，由用户手动重试；而 JSON 格式错误、限流
    这类失败返回很快，重试一次能显著提升成功率。
    """
    if isinstance(exc, ArkConfigError):
        return False
    text = f"{type(exc).__name__} {exc}".lower()
    if any(hint in text for hint in ("timeout", "timed out", "deadline")):
        return False
    if isinstance(exc, json.JSONDecodeError | ValueError):
        return True
    return "429" in text or "rate limit" in text


def ask_json_text_only(
    prompt: str,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    attempts: int = 2,
) -> dict[str, Any]:
    """纯文本 JSON 调用（不带 PDF），关闭深度思考并限制输出长度以提速。

    attempts 为"应用层"重试次数：模型偶发返回非 JSON 时再问一次，
    比让用户看到 502 更友好。网络层重试仍由 SDK 的 max_retries 负责。
    注意：超时不会触发应用层重试，避免总耗时翻倍。
    """
    key, mdl = _resolve_credentials(api_key, model)
    client = _make_client(
        key,
        timeout=ARK_JSON_TIMEOUT if timeout is None else timeout,
        max_retries=ARK_JSON_MAX_RETRIES if max_retries is None else max_retries,
    )
    total = max(1, attempts)
    last_error: Exception | None = None
    for attempt in range(1, total + 1):
        started = time.monotonic()
        try:
            response = _create_response(
                client,
                model=mdl,
                input=[
                    {"role": "user", "content": [{"type": "input_text", "text": prompt.strip()}]}
                ],
                **_json_call_kwargs(),
            )
            raw = _extract_text_from_response(response)
            parsed = _parse_json_object(raw)
            logger.info(
                "JSON 调用成功（第 %d 次尝试，耗时 %.1fs）", attempt, time.monotonic() - started
            )
            return parsed
        except Exception as exc:  # noqa: BLE001 - 需在所有尝试失败后统一抛出
            last_error = exc
            logger.warning(
                "JSON 调用失败（第 %d/%d 次，耗时 %.1fs）：%s",
                attempt,
                total,
                time.monotonic() - started,
                exc,
            )
            if attempt >= total or not _should_retry_json(exc):
                raise
    raise last_error if last_error else RuntimeError("JSON 调用失败")
