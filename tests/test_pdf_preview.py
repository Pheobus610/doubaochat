"""PDF 预览接口与上传保留策略的回归测试。

背景：左栏常驻 PDF 预览需要后端保留上传的文件副本（此前上传成功即删除），
因此必须同时保证：
1. 预览接口只能读到注册过的、且位于 UPLOAD_DIR 内的文件（防路径穿越）。
2. 上传成功后文件保留、失败后清理，且有 TTL 回收避免磁盘被撑满。
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """把上传目录指向临时目录，避免污染真实 uploads/。"""
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    main._preview_files.clear()
    monkeypatch.setattr(config, "ARK_API_KEY", "k")
    monkeypatch.setattr(config, "ARK_MODEL", "ep")
    yield
    main._preview_files.clear()


# ---------- 安全：路径穿越 ----------
@pytest.mark.parametrize(
    "evil",
    [
        "../config.py",
        "../../etc/passwd",
        "....//config.py",
        "%2e%2e%2fconfig.py",
    ],
)
def test_preview_rejects_path_traversal(evil):
    """未注册的 file_id 一律 404，不得读取任意文件。"""
    res = client.get(f"/api/file/{evil}")
    assert res.status_code == 404


def test_preview_rejects_absolute_path_in_registry():
    """即使注册表被写入绝对路径，也必须被挡在 UPLOAD_DIR 之外。"""
    main._preview_files["bad"] = "/etc/passwd"
    assert client.get("/api/file/bad").status_code == 404


def test_preview_rejects_relative_escape_in_registry():
    """注册表被写入 ../ 时同样必须拒绝。"""
    main._preview_files["bad"] = "../app/config.py"
    assert client.get("/api/file/bad").status_code == 404


def test_preview_unregistered_id_is_404():
    assert client.get("/api/file/never-registered").status_code == 404


# ---------- 正常预览 ----------
def test_preview_returns_pdf_inline(tmp_path):
    """注册过的文件应以 inline 方式返回，便于 iframe 内嵌渲染。"""
    p = tmp_path / "abc_lesson.pdf"
    p.write_bytes(b"%PDF-1.4 content")
    main._register_preview_file("fid1", p.name)

    res = client.get("/api/file/fid1")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert "inline" in res.headers["content-disposition"]
    assert res.content == b"%PDF-1.4 content"


def test_preview_404_after_file_cleaned(tmp_path):
    """文件被 TTL 清理后，预览应返回可读的 404 而不是 500。"""
    p = tmp_path / "gone.pdf"
    p.write_bytes(b"%PDF-1.4")
    main._register_preview_file("fid2", p.name)
    p.unlink()

    res = client.get("/api/file/fid2")
    assert res.status_code == 404
    # 失效条目应被顺手剔除，避免注册表堆积
    assert "fid2" not in main._preview_files


# ---------- 上传保留 / 清理 ----------
def test_upload_keeps_file_and_returns_preview_url(monkeypatch, tmp_path):
    """上传成功后必须保留本地副本，否则左栏无法预览。"""
    monkeypatch.setattr(
        main, "upload_pdf", lambda p, api_key=None: {"file_id": "F1", "filename": "a.pdf"}
    )
    res = client.post(
        "/api/upload", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["preview_url"] == "/api/file/F1"
    # 文件仍在磁盘上，且可通过预览接口读到
    assert list(tmp_path.glob("*.pdf")), "上传成功后不应删除本地副本"
    assert client.get("/api/file/F1").status_code == 200


def test_upload_cleans_up_on_failure(monkeypatch, tmp_path):
    """上传失败必须清理临时文件，避免垃圾堆积。"""

    def _boom(p, api_key=None):
        raise RuntimeError("方舟拒绝")

    monkeypatch.setattr(main, "upload_pdf", _boom)
    res = client.post(
        "/api/upload", files={"file": ("b.pdf", b"%PDF-1.4 y", "application/pdf")}
    )
    assert res.status_code == 502
    assert not list(tmp_path.glob("*.pdf")), "失败后应删除临时文件"


def test_sweep_removes_expired_uploads(monkeypatch, tmp_path):
    """超过 TTL 的上传文件应被清理，并同步剔除注册表条目。"""
    monkeypatch.setattr(config, "UPLOAD_TTL_SECONDS", 60)
    old = tmp_path / "old.pdf"
    old.write_bytes(b"%PDF")
    fresh = tmp_path / "fresh.pdf"
    fresh.write_bytes(b"%PDF")
    # 把 old 的 mtime 调到 10 分钟前
    past = time.time() - 600
    import os

    os.utime(old, (past, past))

    main._register_preview_file("old-id", "old.pdf")
    main._register_preview_file("fresh-id", "fresh.pdf")

    removed = main._sweep_expired_uploads()
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
    assert "old-id" not in main._preview_files
    assert "fresh-id" in main._preview_files


def test_sweep_disabled_when_ttl_non_positive(monkeypatch, tmp_path):
    """TTL 设为 0 表示永不清理（便于需要长期留存的部署）。"""
    monkeypatch.setattr(config, "UPLOAD_TTL_SECONDS", 0)
    p = tmp_path / "keep.pdf"
    p.write_bytes(b"%PDF")
    import os

    past = time.time() - 999999
    os.utime(p, (past, past))
    assert main._sweep_expired_uploads() == 0
    assert p.exists()


def test_upload_endpoint_still_uses_threadpool():
    """保留文件的改动不应破坏之前的并发修复。"""
    src = Path(main.__file__).read_text(encoding="utf-8")
    body = src.split("async def api_upload")[1].split("\n@app.")[0]
    assert "run_in_threadpool" in body
