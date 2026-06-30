"""Composition root — DI wiring, /health, and webhook signature enforcement."""

from fastapi.testclient import TestClient

from lorekeeper.app import create_app
from lorekeeper.config import Settings


def _mock_settings(**overrides) -> Settings:
    base = dict(
        source="line",
        sinks=["markdown"],
        llm_provider="mock",
        line_channel_secret="secret",
        markdown_output_dir="./_test_out",
    )
    base.update(overrides)
    # _env_file=None keeps tests from reading a developer's local .env
    return Settings(_env_file=None, **base)


def test_health_reports_active_adapters():
    client = TestClient(create_app(_mock_settings()))
    body = client.get("/health").json()
    assert body["service"] == "lorekeeper"
    assert body["llm"] == "mock"
    assert body["sinks"] == ["markdown"]


def test_webhook_rejects_bad_signature():
    client = TestClient(create_app(_mock_settings()))
    resp = client.post(
        "/webhook",
        content=b'{"events":[]}',
        headers={"X-Line-Signature": "deadbeef"},
    )
    assert resp.status_code == 400


def test_unknown_sink_falls_back_to_markdown():
    client = TestClient(create_app(_mock_settings(sinks=["does-not-exist"])))
    assert client.get("/health").json()["sinks"] == ["markdown"]
