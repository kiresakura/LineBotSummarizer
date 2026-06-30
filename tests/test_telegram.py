"""Telegram source adapter — webhook auth + Update normalization."""

from fastapi.testclient import TestClient

from lorekeeper.adapters.telegram import TelegramClient, TelegramSource
from lorekeeper.app import create_app
from lorekeeper.config import Settings
from lorekeeper.models import MediaPayload, MessageType


async def _noop(_msg):
    return None


def test_verify_secret_token():
    c = TelegramClient("tok", webhook_secret="s3cr3t")
    assert c.verify("s3cr3t")
    assert not c.verify("wrong")
    assert not c.verify("")
    # fail-closed when no secret is configured
    assert not TelegramClient("tok", webhook_secret="").verify("anything")


async def test_to_inbound_text():
    src = TelegramSource(TelegramClient("tok", "s"), on_message=_noop)
    msg = await src._to_inbound(
        {
            "message_id": 5,
            "date": 1767200400,
            "chat": {"id": -100, "type": "supergroup"},
            "from": {"id": 42, "first_name": "Alice", "last_name": "W"},
            "text": "hello world",
        }
    )
    assert msg is not None
    assert msg.type == MessageType.TEXT
    assert msg.text == "hello world"
    assert msg.conversation_id == "-100"
    assert msg.sender_id == "42"
    assert msg.sender_name == "Alice W"


async def test_to_inbound_photo_downloads_largest(monkeypatch):
    client = TelegramClient("tok", "s")

    async def fake_download(file_id):
        assert file_id == "big"  # the largest size is chosen
        return MediaPayload(data=b"\x89PNG", mime_type="image/png")

    monkeypatch.setattr(client, "download_file", fake_download)
    src = TelegramSource(client, on_message=_noop)
    msg = await src._to_inbound(
        {
            "message_id": 1,
            "date": 1767200400,
            "chat": {"id": 1, "type": "group"},
            "from": {"id": 1, "first_name": "Bob"},
            "photo": [{"file_id": "small"}, {"file_id": "big"}],
            "caption": "a chart",
        }
    )
    assert msg is not None
    assert msg.type == MessageType.IMAGE
    assert msg.has_media
    assert msg.text == "a chart"


async def test_to_inbound_sticker_and_unsupported():
    src = TelegramSource(TelegramClient("tok", "s"), on_message=_noop)
    sticker = await src._to_inbound(
        {
            "message_id": 2,
            "date": 1767200400,
            "chat": {"id": 1, "type": "group"},
            "from": {"id": 1, "first_name": "Bob"},
            "sticker": {"file_id": "x"},
        }
    )
    assert sticker is not None
    assert sticker.type == MessageType.STICKER
    assert sticker.text == "[貼圖]"

    unsupported = await src._to_inbound(
        {
            "message_id": 3,
            "date": 1,
            "chat": {"id": 1, "type": "group"},
            "from": {},
            "location": {"latitude": 0, "longitude": 0},
        }
    )
    assert unsupported is None


def test_app_telegram_source_health_and_auth():
    settings = Settings(
        _env_file=None,
        source="telegram",
        sinks=["markdown"],
        llm_provider="mock",
        telegram_webhook_secret="sek",
        markdown_output_dir="./_test_out",
    )
    client = TestClient(create_app(settings))
    assert client.get("/health").json()["source"] == "telegram"
    resp = client.post(
        "/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert resp.status_code == 403
