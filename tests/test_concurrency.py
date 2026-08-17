"""并发安全回归测试。

背景：多用户同时调用接口时曾有两个缺陷：
1. /api/asr 与 /api/upload 声明为 async def，但内部调用同步阻塞的 httpx/SDK，
   会阻塞事件循环 —— 一个用户上传 PDF 时，所有其他用户的请求（含健康检查）全部冻结。
2. _sessions 无容量上限且无锁，并发用户增多时内存单调增长、读改写存在竞态。
"""

import ast
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.main import _create_session, _evict_if_over_capacity, _sessions, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_sessions():
    _sessions.clear()
    yield
    _sessions.clear()


# ---------- 缺陷 1：async def 内不得直接调用阻塞函数 ----------
def _async_endpoints_with_blocking_calls() -> list[str]:
    """静态分析：找出 async def 接口里直接调用已知阻塞函数的地方。

    这些函数内部使用同步 httpx.Client / SDK 轮询，必须经 run_in_threadpool 调度。
    """
    blocking = {"transcribe_audio", "synthesize_speech", "upload_pdf", "write_bytes", "unlink"}
    tree = ast.parse(Path(main.__file__).read_text(encoding="utf-8"))
    offenders = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            # 只关心裸调用；run_in_threadpool(...) 包装过的不算
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name not in blocking:
                continue
            # 判断该调用是否被 await run_in_threadpool(...) 包裹
            wrapped = any(
                isinstance(p, ast.Call)
                and (getattr(p.func, "id", None) == "run_in_threadpool")
                for p in ast.walk(node)
                if isinstance(p, ast.Call)
                and getattr(p.func, "id", None) == "run_in_threadpool"
                and any(inner is a or name in ast.dump(a) for a in p.args)
            )
            if not wrapped:
                offenders.append(f"{node.name} -> {name}")
    return offenders


def test_async_endpoints_do_not_block_event_loop():
    """async 接口不得直接调用阻塞函数，否则会卡死所有并发用户。"""
    assert _async_endpoints_with_blocking_calls() == []


def test_blocking_calls_are_dispatched_to_threadpool():
    """/api/asr 与 /api/upload 必须通过 run_in_threadpool 调度阻塞调用。"""
    src = Path(main.__file__).read_text(encoding="utf-8")
    for endpoint in ("async def api_asr", "async def api_upload"):
        body = src.split(endpoint)[1].split("\n@app.")[0]
        assert "run_in_threadpool" in body, f"{endpoint} 仍在阻塞事件循环"


def test_health_stays_responsive_while_blocking_endpoint_runs(monkeypatch):
    """实测：上传 PDF 期间健康检查仍需快速返回。"""
    monkeypatch.setattr(config, "ARK_API_KEY", "k")
    monkeypatch.setattr(config, "ARK_MODEL", "ep")

    def _slow_upload(local_path, api_key=None):
        time.sleep(1.0)
        return {"file_id": "f1", "filename": "a.pdf"}

    monkeypatch.setattr(main, "upload_pdf", _slow_upload)

    ping_latency: list[float] = []

    def _ping_during_upload():
        time.sleep(0.3)  # 等上传进入阻塞段
        t0 = time.perf_counter()
        client.get("/api/health")
        ping_latency.append(time.perf_counter() - t0)

    t = threading.Thread(target=_ping_during_upload)
    t.start()
    res = client.post("/api/upload", files={"file": ("a.pdf", b"%PDF-1.4 data", "application/pdf")})
    t.join()

    assert res.status_code == 200
    # 修复前该值会接近 1 秒（被阻塞）；修复后应远低于此
    assert ping_latency and ping_latency[0] < 0.5, (
        f"健康检查被阻塞 {ping_latency[0]:.2f}s，事件循环仍未释放"
    )


# ---------- 缺陷 2：会话容量与并发安全 ----------
def test_sessions_are_capped_by_max_sessions(monkeypatch):
    """会话数不得无上限增长，否则并发用户多时内存被打满。"""
    monkeypatch.setattr(config, "MAX_SESSIONS", 10)
    for i in range(25):
        _create_session(f"c{i}")
    assert len(_sessions) <= 10


def test_eviction_removes_least_recently_active(monkeypatch):
    """淘汰应遵循 LRU：保留最近活跃的会话。"""
    monkeypatch.setattr(config, "MAX_SESSIONS", 2)
    for name, ts in (("old", 100.0), ("mid", 200.0), ("new", 300.0)):
        _sessions[name] = {"last_active": ts}
    _evict_if_over_capacity()
    assert "old" not in _sessions
    assert "new" in _sessions


def test_eviction_disabled_when_limit_non_positive(monkeypatch):
    """上限设为 0 表示不限制，便于特殊部署场景。"""
    monkeypatch.setattr(config, "MAX_SESSIONS", 0)
    for i in range(30):
        _sessions[f"c{i}"] = {"last_active": float(i)}
    assert _evict_if_over_capacity() == 0
    assert len(_sessions) == 30


def test_concurrent_session_creation_is_race_free(monkeypatch):
    """多线程并发创建同一会话应只产生一个对象，且不丢数据。"""
    monkeypatch.setattr(config, "MAX_SESSIONS", 1000)
    seen: list[int] = []
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()  # 尽量让所有线程同时冲进去
        seen.append(id(_create_session("same-client")))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(_sessions) == 1
    assert len(set(seen)) == 1, "并发创建产生了多个会话对象"


def test_concurrent_distinct_sessions_all_survive(monkeypatch):
    """并发创建不同会话不应互相覆盖或丢失。"""
    monkeypatch.setattr(config, "MAX_SESSIONS", 1000)
    barrier = threading.Barrier(30)

    def worker(i):
        barrier.wait()
        _create_session(f"client-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(_sessions) == 30


def test_sweep_is_lock_protected():
    """TTL 清理与会话创建共享同一把锁，避免并发下字典被改坏。"""
    src = Path(main.__file__).read_text(encoding="utf-8")
    sweep = src.split("def _sweep_expired_sessions")[1].split("\n@")[0]
    assert "_sessions_lock" in sweep
