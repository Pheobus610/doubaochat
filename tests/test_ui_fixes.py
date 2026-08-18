"""前端交互修复的回归测试。

这些用例直接读 static/*.js 与 index.html 源码做断言，不复刻逻辑。
原因：本机没有 node，tests/test_prefetch.js 无法在 pytest 中执行；
而「完成答题」这类 bug 的本质是源码里存在死逻辑，用源码断言即可稳定拦住回归。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"
APP_JS = STATIC / "app.js"
VOICE_JS = STATIC / "voice.js"
INDEX_HTML = STATIC / "index.html"
PROMPTS = Path(__file__).resolve().parent.parent / "app" / "prompts.py"
MAIN_PY = Path(__file__).resolve().parent.parent / "app" / "main.py"
CONFIG_PY = Path(__file__).resolve().parent.parent / "app" / "config.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    """截取 `function name(...) { ... }` 的函数体（按大括号配平）。"""
    m = re.search(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*{{", src)
    assert m, f"未找到函数 {name}"
    i = m.end() - 1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    raise AssertionError(f"{name} 大括号不配平")


# ---------- 1. 完成答题 ----------


@pytest.mark.parametrize("fn", ["goNextQuestion", "goNextVariant"])
def test_last_question_delegates_to_finish(fn: str) -> None:
    """最后一题必须走 finishQuestions，而不是重渲染当前题。

    修复前 else 分支只调 renderCurrentQuestion()，视觉上无变化，
    表现为「点击完成答题没有任何反应」。
    """
    body = _func_body(_read(APP_JS), fn)
    assert "finishQuestions(" in body, f"{fn} 未委托给 finishQuestions"


def test_finish_prompts_when_unanswered() -> None:
    """未答完时要提示且不跳转。"""
    body = _func_body(_read(APP_JS), "finishQuestions")
    assert "getUnansweredIndexes" in body
    # 提示用户还剩几题
    assert "未作答" in body
    # 提示后必须 return，不能继续往下跳转
    idx_banner = body.index("showBanner")
    assert "return;" in body[idx_banner:], "提示后未 return，会继续跳转"


def test_finish_delegates_to_gonext_when_complete() -> None:
    """答完后应复用 goNext()，以免绕过「全对跳过错题分析」等既有逻辑。"""
    body = _func_body(_read(APP_JS), "finishQuestions")
    assert "goNext()" in body


def test_unanswered_uses_answer_results_not_count() -> None:
    """必须按题目 id 判定，而非比较已答数量。

    用数量比较时，重复提交同一题会让计数虚高，从而把未答完误判为已完成。
    """
    body = _func_body(_read(APP_JS), "getUnansweredIndexes")
    assert "state.answerResults[q.id]" in body
    assert "undefined" in body


# ---------- 2. 录音竞态 ----------


def test_recording_click_blocked_while_stop_not_ready() -> None:
    """授权对话框期间再次点击不能启动第二路录音。

    修复前条件是 `current?.recording && current.stop`，
    stop 尚为 null 时判断为假，会继续往下走再开一路录音，导致流泄漏。
    """
    body = _func_body(_read(VOICE_JS), "startSpeechCapture")
    assert "current?.recording && current.stop" not in body, "竞态条件回归"
    assert "pendingStop" in body, "缺少待停止标记"


def test_pending_stop_is_honored_after_start() -> None:
    """recorder.start() 之后要检查 pendingStop 并立即收尾。"""
    body = _func_body(_read(VOICE_JS), "startSpeechCapture")
    start_idx = body.index("recorder.start()")
    assert "pendingStop" in body[start_idx:], "start() 之后未处理 pendingStop"


# ---------- 3. 录制与播放 UI ----------


def test_teach_page_has_explicit_record_button() -> None:
    html = _read(INDEX_HTML)
    for el in ["teachRecordBtn", "teachRecordLabel", "recordingStatus", "recordingDot"]:
        assert f'id="{el}"' in html, f"缺少元素 {el}"


def test_record_label_toggles_start_and_stop() -> None:
    body = _func_body(_read(VOICE_JS), "syncTeachRecordUi")
    assert "开始录制" in body
    assert "结束录制" in body


def test_record_state_syncs_ui() -> None:
    """setRecordingState 必须联动显式按钮，否则按钮文字不会变。"""
    body = _func_body(_read(VOICE_JS), "setRecordingState")
    assert "syncTeachRecordUi" in body


def test_teach_page_has_play_pause_controls() -> None:
    html = _read(INDEX_HTML)
    for el in ["teachPlayBtn", "teachPauseBtn"]:
        assert f'id="{el}"' in html, f"缺少元素 {el}"


def test_play_pause_are_mutually_exclusive() -> None:
    """播放与暂停按钮互斥显示，保证状态一眼可辨。"""
    body = _func_body(_read(VOICE_JS), "syncTeachAudioUi")
    assert 'classList.toggle("hidden", playing)' in body
    assert 'classList.toggle("hidden", !playing)' in body


def test_teach_reply_recorded_for_replay() -> None:
    """AI 回复要存下来，否则自动播报一次后无法重听。"""
    app = _read(APP_JS)
    assert app.count("window.setTeachReplyText?.(") >= 2, "邀请与评估两处都要记录回复"


# ---------- 4. 命名 ----------


def test_renamed_to_peertalk() -> None:
    html = _read(INDEX_HTML)
    assert "<title>Peertalk</title>" in html
    assert "<h1>Peertalk</h1>" in html
    assert "语音学习" not in html
    assert 'title="Peertalk"' in _read(MAIN_PY)


def test_no_ai_teacher_left() -> None:
    """「AI老师」与「AI 老师」两种写法都不应残留。"""
    for p in (APP_JS, INDEX_HTML, MAIN_PY):
        text = _read(p)
        assert "AI老师" not in text, f"{p.name} 残留 AI老师"
        assert "AI 老师" not in text, f"{p.name} 残留 AI 老师"


def test_ai_classmate_present() -> None:
    assert "AI 同学" in _read(APP_JS)
    assert "AI同学" in _read(MAIN_PY)


def test_teach_prompts_use_peer_persona() -> None:
    """互讲环节的人设应为同学而非老师，否则口吻与「AI 同学」不一致。"""
    src = _read(PROMPTS)
    invite = src[src.index("def teach_invite_prompt") : src.index("def teach_eval_prompt")]
    assert "同学" in invite
    assert "老师" not in invite


def test_no_teacher_wording_in_frontend() -> None:
    """前端不应再出现「老师」，包括空状态提示这类容易漏改的文案。"""
    for p in (APP_JS, INDEX_HTML, VOICE_JS):
        assert "老师" not in _read(p), f"{p.name} 残留「老师」"


def test_no_press_and_hold_wording() -> None:
    """录制已改为点击开始/结束，文案不能再写「按住」，否则与实际交互矛盾。"""
    for p in (APP_JS, INDEX_HTML):
        assert "按住" not in _read(p), f"{p.name} 仍写着「按住」"


def test_session_storage_keys_unchanged() -> None:
    """改名不应动 sessionStorage 键前缀，否则老用户已保存的设置全部失效。"""
    assert "doubaochat_auto_speak" in _read(VOICE_JS)


# ---------- 5. 讲解长度 ----------


def test_explain_prompt_has_hard_char_limit() -> None:
    """讲解 prompt 必须给出可量化的字数上限。

    修复前只在第 3 条末尾夹了一句「说话尽可能简短」，无数字、位置隐蔽，
    模型遵循度低，导致首次讲解很长、用户等待久。
    """
    src = _read(PROMPTS)
    body = src[src.index("def explain_prompt") : src.index("def quiz_generate_prompt")]
    assert "350" in body, "缺少字数上限"
    assert "尽可能简短" not in body, "仍在用无法量化的措辞"


def test_explain_prompt_drops_boilerplate_tail() -> None:
    """结尾套话已由界面按钮承担，不该再让模型生成。"""
    src = _read(PROMPTS)
    body = src[src.index("def explain_prompt") : src.index("def quiz_generate_prompt")]
    assert "接下来开始做题巩固" not in body


def test_lesson_is_not_truncated_server_side() -> None:
    """讲解不做服务端截断：长度只由 prompt 约束，超了就超了。

    截断会砍掉模型的完整表达（可能正好切掉结尾总结），因此按产品决策移除。
    这里守住，避免以后又把截断加回来。
    """
    assert "_truncate_lesson" not in _read(MAIN_PY)
    assert "LESSON_MAX_CHARS" not in _read(CONFIG_PY).replace("QUIZ_LESSON_MAX_CHARS", "")


# ---------- 6. 导航栏位置 ----------


def _page_nav_rule() -> str:
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    i = css.index(".page-nav {")
    rule = css[i : css.index("}", i)]
    # 去掉注释，否则注释里提到的属性名会被误判为实际声明
    return re.sub(r"/\*.*?\*/", "", rule, flags=re.S)


def test_page_nav_spans_all_columns() -> None:
    """.page-nav 是两列网格的第三个子项，不跨列会被排到 PDF 左栏正下方。

    实测（1400px 两栏）：修复前 nav 的 left/right 与 pdfPane 完全一致（16/536），
    「下一步」被挤在 PDF 框右下角而非页面右下角。
    """
    assert "grid-column: 1 / -1" in _page_nav_rule()


def test_page_nav_buttons_grouped_right() -> None:
    """全宽后按钮成组靠右；space-between 会把两个按钮甩到屏幕两端。"""
    rule = _page_nav_rule()
    assert "justify-content: flex-end" in rule
    assert "space-between" not in rule
