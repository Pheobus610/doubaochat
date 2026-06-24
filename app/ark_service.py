from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from volcenginesdkarkruntime import Ark

from app.config import ARK_API_KEY, ARK_BASE_URL, ARK_MODEL


class ArkConfigError(Exception):
    pass


def _resolve_credentials(
    api_key: str | None, model: str | None
) -> tuple[str, str]:
    key = (api_key or "").strip() or ARK_API_KEY
    mdl = (model or "").strip() or ARK_MODEL
    if not key or not mdl:
        raise ArkConfigError(
            "请在前端设置中填写 API Key 和模型 ID，或在 .env 中配置 ARK_API_KEY 和 ARK_MODEL"
        )
    return key, mdl


def _client(api_key: str | None = None) -> Ark:
    key, _ = _resolve_credentials(api_key, None)
    return Ark(api_key=key, base_url=ARK_BASE_URL)


def upload_pdf(local_path: Path, api_key: str | None = None) -> dict[str, str]:
    client = _client(api_key)
    with open(local_path, "rb") as f:
        file_obj = client.files.create(file=f, purpose="user_data")
    processed = client.files.wait_for_processing(id=file_obj.id)
    if processed.status != "active":
        raise RuntimeError(
            f"PDF 处理失败，状态: {processed.status}（file_id={processed.id}）"
        )
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
    client = Ark(api_key=key, base_url=ARK_BASE_URL)
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

    response = client.responses.create(**kwargs)
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
    client = Ark(api_key=key, base_url=ARK_BASE_URL)
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt.strip()}]
    for fid in file_ids:
        content.append({"type": "input_file", "file_id": fid})
    response = client.responses.create(
        model=mdl,
        input=[{"role": "user", "content": content}],
    )
    return _extract_text_from_response(response)


def _extract_json_string(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        raise ValueError(f"模型未返回 JSON: {text[:300]}")
    return match.group(0)


def ask_json_with_files(
    prompt: str,
    file_ids: list[str],
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    raw = ask_text(prompt=prompt, file_ids=file_ids, api_key=api_key, model=model)
    json_text = _extract_json_string(raw)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        fixed = json_text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(fixed)
    if not isinstance(parsed, dict):
        raise ValueError("模型 JSON 输出不是对象")
    return parsed


def ask_json_text_only(
    prompt: str,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    key, mdl = _resolve_credentials(api_key, model)
    client = Ark(api_key=key, base_url=ARK_BASE_URL)
    response = client.responses.create(
        model=mdl,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt.strip()}]}],
    )
    raw = _extract_text_from_response(response)
    json_text = _extract_json_string(raw)
    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("模型 JSON 输出不是对象")
    return parsed
