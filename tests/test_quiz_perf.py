"""出题（第 4 步）性能与容错回归测试。

背景：此前 /api/quiz/generate 会把 PDF 的 file_ids 一起发给模型，
导致模型每次出题都重新解析整份教辅，出现"生成很久 / 超时 / 报错"。
本文件锁定修复后的关键行为，防止回退。
"""

import json

import pytest

from app import ark_service, config
from app.main import _dump_question, _friendly_llm_error, _is_timeout_error, _normalize_question


# ---------- JSON 解析鲁棒性 ----------
@pytest.mark.parametrize(
    "raw",
    [
        '{"questions":[1]}',
        '```json\n{"questions":[1]}\n```',
        '```\n{"questions":[1]}\n```',
        "好的，题目如下：\n{\"questions\":[1]}\n希望有帮助",
    ],
)
def test_parse_json_object_handles_wrappers_and_prose(raw):
    """模型可能返回代码块包裹或夹带解说文字，都应能解析出 JSON。"""
    assert ark_service._parse_json_object(raw) == {"questions": [1]}


def test_parse_json_object_tolerates_trailing_commas():
    """模型偶发输出尾随逗号，应自动修正而不是直接失败。"""
    assert ark_service._parse_json_object('{"questions":[1,2,],}') == {"questions": [1, 2]}


def test_parse_json_object_rejects_non_object():
    with pytest.raises(ValueError):
        ark_service._parse_json_object("这里完全没有 JSON")


# ---------- 提速参数 ----------
def test_json_call_kwargs_limits_output_tokens():
    """必须限制输出长度，避免模型越写越长导致超时。"""
    kwargs = ark_service._json_call_kwargs()
    assert kwargs["max_output_tokens"] == config.ARK_JSON_MAX_TOKENS


def test_json_call_kwargs_disables_thinking_by_default():
    """默认关闭深度思考：这是出题耗时成倍增加的主因之一。"""
    kwargs = ark_service._json_call_kwargs()
    assert kwargs.get("thinking") == {"type": "disabled"}


def test_thinking_disabled_is_a_valid_sdk_value():
    """校验传给 SDK 的 thinking 取值合法，避免线上 400。"""
    from volcenginesdkarkruntime.types.shared.thinking import Thinking

    assert Thinking(type="disabled").type == "disabled"


# ---------- 不支持参数时自动降级 ----------
class _FakeResponses:
    def __init__(self, unsupported):
        self.unsupported = set(unsupported)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(set(kwargs))
        for key in self.unsupported:
            if key in kwargs:
                raise RuntimeError(f"Error code: 400 unsupported parameter: {key}")
        return "ok"


class _FakeClient:
    def __init__(self, unsupported=()):
        self.responses = _FakeResponses(unsupported)


def test_create_response_strips_unsupported_optional_params():
    """接入点不支持 thinking/max_output_tokens 时应剥离后重试，而非报错。"""
    client = _FakeClient(unsupported=["thinking", "max_output_tokens"])
    result = ark_service._create_response(
        client, model="m", input=[], **ark_service._json_call_kwargs()
    )
    assert result == "ok"
    # 最后一次尝试应只剩必要参数
    assert client.responses.calls[-1] == {"model", "input"}


def test_create_response_keeps_supported_params():
    """接入点支持时不应无谓剥离参数。"""
    client = _FakeClient()
    ark_service._create_response(client, model="m", input=[], **ark_service._json_call_kwargs())
    assert len(client.responses.calls) == 1
    assert "thinking" in client.responses.calls[0]


def test_create_response_reraises_unrelated_errors():
    """非参数类错误应原样上抛，不能被降级逻辑吞掉。"""

    class _Boom:
        class responses:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("Error code: 500 internal")

    with pytest.raises(RuntimeError, match="500"):
        ark_service._create_response(_Boom(), model="m", input=[])


# ---------- 重试策略 ----------
def test_timeout_is_not_retried_at_app_level():
    """超时重试会让总耗时翻倍并超出前端等待上限，必须不重试。"""
    assert ark_service._should_retry_json(RuntimeError("Request timed out")) is False


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("模型未返回 JSON: xxx"),
        json.JSONDecodeError("bad", "{", 0),
        RuntimeError("Error code: 429 rate limit"),
    ],
)
def test_fast_failures_are_retried(exc):
    """格式错误/限流属于快速失败，重试一次能显著提升成功率。"""
    assert ark_service._should_retry_json(exc) is True


def test_config_error_is_not_retried():
    assert ark_service._should_retry_json(ark_service.ArkConfigError("no key")) is False


def test_ask_json_text_only_stops_after_timeout(monkeypatch):
    """超时场景下只应调用模型一次。"""
    calls = []

    def _fake_create(client, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("Request timed out")

    monkeypatch.setattr(ark_service, "_create_response", _fake_create)
    monkeypatch.setattr(ark_service, "_make_client", lambda *a, **k: object())
    monkeypatch.setattr(ark_service, "_resolve_credentials", lambda a, m: ("k", "ep"))

    with pytest.raises(RuntimeError, match="timed out"):
        ark_service.ask_json_text_only("prompt", attempts=2)
    assert len(calls) == 1


def test_ask_json_text_only_retries_bad_json_then_succeeds(monkeypatch):
    """首次返回非 JSON 时自动重问一次，用户无需看到报错。"""
    outputs = ["这不是 JSON", '{"questions":[1]}']

    def _fake_create(client, **kwargs):
        return outputs.pop(0)

    monkeypatch.setattr(ark_service, "_create_response", _fake_create)
    monkeypatch.setattr(ark_service, "_extract_text_from_response", lambda r: r)
    monkeypatch.setattr(ark_service, "_make_client", lambda *a, **k: object())
    monkeypatch.setattr(ark_service, "_resolve_credentials", lambda a, m: ("k", "ep"))

    assert ark_service.ask_json_text_only("prompt", attempts=2) == {"questions": [1]}


def test_json_client_uses_shorter_timeout_than_pdf_calls():
    """结构化调用超时应短于带 PDF 的调用，让失败更快暴露。"""
    assert config.ARK_JSON_TIMEOUT <= config.ARK_LLM_TIMEOUT
    assert config.ARK_JSON_MAX_RETRIES <= config.ARK_LLM_MAX_RETRIES


# ---------- 出题不再重传 PDF（核心修复） ----------
def _quiz_generate_source() -> str:
    from pathlib import Path

    src = Path(ark_service.__file__).with_name("main.py").read_text(encoding="utf-8")
    body = src.split("def api_quiz_generate")[1].split("@app.post")[0]
    # 排除注释行，避免注释中的关键词造成误判
    return "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))


def test_quiz_generate_does_not_resend_pdf():
    """核心回归：出题只依赖讲解文本，绝不能再把 PDF 发给模型。"""
    body = _quiz_generate_source()
    assert "ask_json_text_only" in body
    assert "ask_json_with_files" not in body
    assert "file_ids" not in body


def test_quiz_generate_truncates_lesson_text():
    """讲解过长时截断，进一步压缩输入。"""
    assert "QUIZ_LESSON_MAX_CHARS" in _quiz_generate_source()


def test_quiz_prompt_is_compact_and_demands_raw_json():
    """精简后的 prompt 应更短并明确要求直接输出 JSON。"""
    from app.prompts import quiz_generate_prompt

    prompt = quiz_generate_prompt("初一", "数学", "讲解内容", 5)
    assert len(prompt) < 700
    assert "JSON" in prompt


# ---------- 错误提示与序列化 ----------
def test_timeout_detection():
    assert _is_timeout_error(RuntimeError("read operation timed out")) is True
    assert _is_timeout_error(RuntimeError("something else")) is False


@pytest.mark.parametrize(
    ("exc", "keyword"),
    [
        (RuntimeError("Request timed out"), "超时"),
        (RuntimeError("Error code: 429"), "限流"),
        (RuntimeError("invalid api key"), "API Key"),
        (ValueError("模型未返回 JSON: abc"), "格式"),
    ],
)
def test_friendly_error_messages_are_actionable(exc, keyword):
    """错误提示必须是用户能看懂并知道怎么做的中文。"""
    assert keyword in _friendly_llm_error(exc, "生成题目")


def test_dump_question_works_on_pydantic_v2():
    """替换已弃用的 .dict()，兼容 Pydantic v1/v2。"""
    q = _normalize_question({"type": "choice", "answer": "A"}, 1, "q")
    dumped = _dump_question(q)
    assert dumped["id"] == "q1"
    assert dumped["answer"] == "A"
    assert dumped["type"] == "choice"
