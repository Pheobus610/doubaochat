from fastapi.testclient import TestClient

from app.main import (
    _norm_text,
    _normalize_question,
    _update_stats,
    app,
)

client = TestClient(app)


# ---------- 纯函数：_norm_text ----------
def test_norm_text_strips_and_lowercases():
    assert _norm_text("  A.B。C ") == "abc"


def test_norm_text_handles_none_and_empty():
    assert _norm_text(None) == ""
    assert _norm_text("") == ""


def test_norm_text_removes_spaces_and_punctuation():
    assert _norm_text("a b.c。D") == "abcd"


# ---------- 纯函数：_normalize_question ----------
def test_normalize_question_defaults_for_empty_dict():
    q = _normalize_question({}, 1)
    assert q.type == "fill"
    assert q.type_label == "填空题"
    assert q.id == "q1"


def test_normalize_question_clamps_options_to_four():
    q = _normalize_question({"options": ["a", "b", "c", "d", "e"]}, 0)
    assert q.options == ["a", "b", "c", "d"]


def test_normalize_question_unknown_type_falls_back_to_fill():
    q = _normalize_question({"type": "whoops"}, 2, "v")
    assert q.type == "fill"
    assert q.id == "v2"


def test_normalize_question_preserves_valid_fields():
    q = _normalize_question(
        {
            "type": "choice",
            "question_text": "1+1=?",
            "answer": "2",
            "options": ["1", "2", "3"],
        },
        1,
    )
    assert q.type == "choice"
    assert q.type_label == "选择题"
    assert q.answer == "2"
    assert q.options == ["1", "2", "3"]


# ---------- 纯函数：_update_stats ----------
def test_update_stats_counts_and_unlocks_at_three():
    learning = {
        "answer_results": {
            "q1": {"correct": True},
            "q2": {"correct": False},
            "q3": {"correct": True},
            "q4": {"correct": True},
        }
    }
    _update_stats(learning)
    assert learning["correct_count"] == 3
    assert learning["wrong_count"] == 1
    assert learning["teach_unlocked"] is True


def test_update_stats_not_unlocked_below_three():
    learning = {"answer_results": {"q1": {"correct": True}, "q2": {"correct": True}}}
    _update_stats(learning)
    assert learning["correct_count"] == 2
    assert learning["wrong_count"] == 0
    assert learning["teach_unlocked"] is False


def test_update_stats_handles_empty_results():
    learning = {}
    _update_stats(learning)
    assert learning["correct_count"] == 0
    assert learning["wrong_count"] == 0
    assert learning["teach_unlocked"] is False


# ---------- 接口：/api/health ----------
def test_health_endpoint_returns_ok():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "configured" in data
    assert "message" in data
    assert data["voice_supported"] is True


# ---------- 数据校验：年级 / 科目 ----------
_DUMMY_HEADERS = {"X-Ark-Api-Key": "dummy-key", "X-Ark-Model": "ep-dummy"}


def test_session_start_rejects_invalid_grade():
    res = client.post(
        "/api/session/start",
        json={"grade": "高一", "subject": "数学", "file_ids": ["f1"]},
        headers=_DUMMY_HEADERS,
    )
    assert res.status_code == 400
    assert "初一" in res.json()["detail"]


def test_session_start_rejects_invalid_subject():
    res = client.post(
        "/api/session/start",
        json={"grade": "初一", "subject": "物理", "file_ids": ["f1"]},
        headers=_DUMMY_HEADERS,
    )
    assert res.status_code == 400
    assert "数学" in res.json()["detail"]


def test_session_start_requires_files():
    res = client.post(
        "/api/session/start",
        json={"grade": "初一", "subject": "数学", "file_ids": []},
        headers=_DUMMY_HEADERS,
    )
    assert res.status_code == 400


def test_session_start_requires_credentials():
    res = client.post(
        "/api/session/start",
        json={"grade": "初一", "subject": "数学", "file_ids": ["f1"]},
    )
    assert res.status_code == 401


# ---------- TTS 分段：segment.text 契约 ----------
def test_synthesize_speech_segments_include_text(monkeypatch):
    """每段音频必须携带其对应文本，供前端段级高亮对齐。"""
    import app.audio_service as asr

    # 让短文本也能触发多段分组（默认 900 字节）
    monkeypatch.setattr(asr, "TTS_MAX_TEXT_BYTES", 30)

    # 绕过真实网络：合成单段返回 dummy 音频
    monkeypatch.setattr(
        asr,
        "_synthesize_single_chunk",
        lambda client, api_key, text, voice, rate: {
            "audio_url": None,
            "audio_base64": "AAAA",
        },
    )

    # 绕过 httpx.Client 真实建连
    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(asr.httpx, "Client", lambda **k: _FakeClient())

    text = "第一句话内容。第二句话内容。第三句话内容。第四句话内容。"
    out = asr.synthesize_speech("key", text, "voice", 1.0)

    assert out["chunk_count"] == len(out["segments"])
    assert out["chunk_count"] > 1
    assert [s["index"] for s in out["segments"]] == list(range(out["chunk_count"]))
    assert all(s.get("text") for s in out["segments"])
    joined = "".join(s["text"] for s in out["segments"])
    assert joined.replace(" ", "") == text.replace(" ", "")
