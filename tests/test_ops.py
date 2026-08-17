"""长期挂载运维相关的回归测试：线程池扩容、磁盘容量清理、清理任务鲁棒性。"""
from __future__ import annotations

import asyncio
import os
import time

import pytest

from app import config, main


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """把上传目录指向临时目录，避免污染真实 uploads。"""
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    main._preview_files.clear()
    yield
    main._preview_files.clear()


def _make(tmp_path, name: str, size: int, age_seconds: float) -> None:
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    t = time.time() - age_seconds
    os.utime(p, (t, t))
    main._register_preview_file(f"id-{name}", name)


# ---------- 磁盘容量上限 ----------

def test_quota_deletes_oldest_first(tmp_path, monkeypatch):
    """超过容量上限时应从最旧的文件开始删，直到降到上限以下。"""
    monkeypatch.setattr(config, "UPLOAD_MAX_TOTAL_MB", 1)
    for i in range(5):  # 5 x 400KB = 2MB，超过 1MB 上限
        _make(tmp_path, f"f{i}.pdf", 400_000, age_seconds=1000 * (5 - i))

    removed = main._enforce_upload_quota()

    left = {p.name for p in tmp_path.iterdir()}
    total = sum(p.stat().st_size for p in tmp_path.iterdir())
    assert removed > 0
    assert total <= 1 * 1024 * 1024, "清理后仍超过上限"
    assert "f0.pdf" not in left, "应优先删除最旧的文件"
    assert "f4.pdf" in left, "最新的文件不应被删除"


def test_quota_prunes_registry(tmp_path, monkeypatch):
    """被容量清理删掉的文件，必须同步从预览注册表移除，否则会残留死链接。"""
    monkeypatch.setattr(config, "UPLOAD_MAX_TOTAL_MB", 1)
    for i in range(5):
        _make(tmp_path, f"f{i}.pdf", 400_000, age_seconds=1000 * (5 - i))

    main._enforce_upload_quota()

    alive = {p.name for p in tmp_path.iterdir()}
    for name in main._preview_files.values():
        assert name in alive, "注册表残留了已删除的文件"


def test_quota_noop_when_under_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_MAX_TOTAL_MB", 100)
    _make(tmp_path, "small.pdf", 1000, age_seconds=10)
    assert main._enforce_upload_quota() == 0
    assert (tmp_path / "small.pdf").exists()


def test_quota_disabled_when_zero(tmp_path, monkeypatch):
    """上限设 0 表示不限制，即使超量也不该删。"""
    monkeypatch.setattr(config, "UPLOAD_MAX_TOTAL_MB", 0)
    for i in range(3):
        _make(tmp_path, f"f{i}.pdf", 500_000, age_seconds=100)
    assert main._enforce_upload_quota() == 0
    assert len(list(tmp_path.iterdir())) == 3


# ---------- 配置默认值 ----------

def test_upload_ttl_default_is_two_hours():
    """PDF 保留时长应与会话 TTL 一致（2 小时）：会话都过期了，PDF 留着也无人预览。

    注意校验的是代码默认值而非 config 当前值：本机 .env 可能有自定义覆盖，
    直接断言 config.UPLOAD_TTL_SECONDS 会让测试受环境影响。
    """
    import re
    from pathlib import Path

    src = (Path(main.__file__).parent / "config.py").read_text(encoding="utf-8")
    m = re.search(r'UPLOAD_TTL_SECONDS = int\(os\.getenv\([^,]+,\s*"(\d+)"\)\)', src)
    assert m, "未找到 UPLOAD_TTL_SECONDS 默认值定义"
    assert int(m.group(1)) == 7200


def test_env_example_matches_two_hour_ttl():
    """.env.example 不能再写 86400，否则会覆盖代码默认值。

    这个坑真实发生过：改了 config.py 默认值但忘了改 .env.example，
    导致部署后实际仍按 24 小时保留。
    """
    from pathlib import Path

    p = Path(main.__file__).parent.parent / ".env.example"
    if not p.exists():
        pytest.skip(".env.example 不存在")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("UPLOAD_TTL_SECONDS="):
            assert line.split("=", 1)[1].strip() == "7200"


def test_thread_pool_size_above_anyio_default():
    """默认 40 在 20 并发下会触顶（每人可能占 2~3 个线程），必须调高。"""
    assert config.THREAD_POOL_SIZE > 40


# ---------- 线程池实际生效 ----------

def test_lifespan_raises_thread_limiter(monkeypatch):
    """lifespan 必须真的把 anyio 线程池上限调上去，否则配置是摆设。"""
    import anyio.to_thread

    async def go():
        async with main.lifespan(main.app):
            return anyio.to_thread.current_default_thread_limiter().total_tokens

    got = asyncio.run(go())
    assert got == config.THREAD_POOL_SIZE


# ---------- 清理任务鲁棒性 ----------

def test_cleanup_loop_survives_exceptions(monkeypatch):
    """清理任务遇异常必须继续存活。

    这是长期挂载的关键：若任务静默退出，此后再无人清理磁盘，
    且没有任何报错提示，问题会在数天后才以「磁盘满」的形式爆出来。
    """
    monkeypatch.setattr(config, "SESSION_CLEANUP_INTERVAL", 0)
    calls: list[int] = []

    def boom():
        calls.append(1)
        raise RuntimeError("模拟磁盘故障")

    monkeypatch.setattr(main, "_sweep_expired_uploads", boom)

    async def go():
        async with main.lifespan(main.app):
            await asyncio.sleep(0.3)
            tasks = [
                t for t in asyncio.all_tasks()
                if "_cleanup_loop" in str(t.get_coro())
            ]
            return calls, any(not t.done() for t in tasks)

    fired, alive = asyncio.run(go())
    assert fired, "清理任务没有执行"
    assert alive, "清理任务在异常后退出了"


def test_cleanup_loop_cancels_cleanly(monkeypatch):
    """CancelledError 必须放行，否则关闭时会卡住。

    直接扫 all_tasks 会误伤测试自身的任务，改为校验 lifespan 能否
    在限时内完成退出（卡住则超时）。
    """
    monkeypatch.setattr(config, "SESSION_CLEANUP_INTERVAL", 0)

    async def go():
        async with main.lifespan(main.app):
            await asyncio.sleep(0.1)

    # 若 CancelledError 被吃掉导致无法取消，这里会超时报错
    async def bounded():
        await asyncio.wait_for(go(), timeout=5)

    asyncio.run(bounded())


def test_cleanup_loop_invokes_quota(monkeypatch):
    """清理循环必须调用容量清理，否则新加的配额逻辑永远不生效。"""
    monkeypatch.setattr(config, "SESSION_CLEANUP_INTERVAL", 0)
    seen: list[str] = []
    monkeypatch.setattr(main, "_sweep_expired_uploads", lambda: seen.append("ttl") or 0)
    monkeypatch.setattr(main, "_enforce_upload_quota", lambda: seen.append("quota") or 0)

    async def go():
        async with main.lifespan(main.app):
            await asyncio.sleep(0.3)

    asyncio.run(go())
    assert "ttl" in seen and "quota" in seen


# ---------- 日志可见性 ----------

def test_app_logger_has_handler():
    """没有 handler 时 logger.exception 会被静默丢弃，线上将无法排查故障。"""
    main._setup_logging()
    assert main.logger.handlers, "应用日志没有 handler，日志会被丢弃"
