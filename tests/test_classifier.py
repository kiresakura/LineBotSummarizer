"""Classifier — JSON handling and entry construction, driven by fake providers."""

from datetime import datetime

from lorekeeper.adapters.mock_llm import MockLLMProvider
from lorekeeper.models import Importance, InboundMessage, MessageType
from lorekeeper.pipeline.classifier import MessageClassifier


def _msg(text: str) -> InboundMessage:
    return InboundMessage(
        id="1",
        conversation_id="c",
        sender_id="u",
        type=MessageType.TEXT,
        text=text,
        timestamp=datetime(2026, 1, 1, 9, 0),
    )


class _FakeLLM:
    def __init__(self, response: str):
        self._response = response

    async def complete(self, prompt, **kwargs):
        return self._response

    async def complete_multimodal(self, *args, **kwargs):
        return self._response


async def test_classify_with_mock_provider():
    clf = MessageClassifier(MockLLMProvider(category="技術分享", importance="high"))
    entry = await clf.classify("conv-1", [_msg("hello world")])
    assert entry is not None
    assert entry.category == "技術分享"
    assert entry.importance == Importance.HIGH
    assert entry.knowledge
    assert entry.conversation_label == "conv-1"


async def test_classify_parses_fenced_json():
    llm = _FakeLLM(
        '```json\n{"category":"其他","importance":"low","knowledge_points":"x"}\n```'
    )
    entry = await MessageClassifier(llm).classify("c", [_msg("hi")])
    assert entry is not None
    assert entry.category == "其他"
    assert entry.knowledge == "x"


async def test_classify_invalid_json_returns_none():
    entry = await MessageClassifier(_FakeLLM("not json at all")).classify(
        "c", [_msg("hi")]
    )
    assert entry is None


async def test_importance_falls_back_to_low():
    llm = _FakeLLM('{"importance":"bogus","knowledge_points":"k"}')
    entry = await MessageClassifier(llm).classify("c", [_msg("hi")])
    assert entry is not None
    assert entry.importance == Importance.LOW


async def test_urls_extracted_from_messages():
    llm = _FakeLLM('{"category":"工具推薦","importance":"low","knowledge_points":"k"}')
    entry = await MessageClassifier(llm).classify(
        "c", [_msg("check https://example.com/foo out")]
    )
    assert entry is not None
    assert "https://example.com/foo" in entry.urls
