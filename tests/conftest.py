import pytest

import app.config as config


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """测试环境不启用访问口令，且不读取本机 .env 中的真实凭证。"""
    monkeypatch.setattr(config, "ACCESS_TOKEN", "")
    monkeypatch.setattr(config, "ARK_API_KEY", "")
    monkeypatch.setattr(config, "ARK_MODEL", "")
