"""Lorekeeper CLI.

    lorekeeper demo [-o DIR]   # run the pipeline on sample data — no credentials
    lorekeeper serve           # run the FastAPI app via uvicorn

`demo` wires the Mock LLM + Markdown sink, so anyone can see the full
enrich → classify → write flow end-to-end without LINE/Notion/OpenRouter keys.
"""

import argparse
import asyncio
import logging
from datetime import datetime

from lorekeeper import __version__
from lorekeeper.adapters.markdown_sink import MarkdownSink
from lorekeeper.adapters.mock_llm import MockLLMProvider
from lorekeeper.adapters.notifiers import NullNotifier
from lorekeeper.models import InboundMessage, MessageType
from lorekeeper.pipeline.classifier import MessageClassifier
from lorekeeper.pipeline.orchestrator import Orchestrator

_SAMPLE = [
    InboundMessage(
        id="m1",
        conversation_id="demo",
        sender_id="alice",
        sender_name="Alice",
        type=MessageType.TEXT,
        text="剛看到一篇講 ports & adapters 的好文，重點是讓核心邏輯不依賴框架。",
        timestamp=datetime(2026, 1, 1, 9, 0, 0),
    ),
    InboundMessage(
        id="m2",
        conversation_id="demo",
        sender_id="bob",
        sender_name="Bob",
        type=MessageType.TEXT,
        text="對，這樣換 Notion → Markdown 之類的就只是換 adapter，核心不用動。",
        timestamp=datetime(2026, 1, 1, 9, 1, 0),
    ),
]


async def _run_demo(out_dir: str) -> None:
    classifier = MessageClassifier(MockLLMProvider())
    sink = MarkdownSink(out_dir)
    orchestrator = Orchestrator(
        classifier, [sink], NullNotifier(), noise_filter_enabled=False
    )
    await orchestrator.process("demo-conversation", _SAMPLE)
    print(f"✅ Demo 完成 — 看看 {out_dir}/ 裡產生的知識條目（Markdown）")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lorekeeper", description="Lorekeeper CLI")
    parser.add_argument(
        "--version", action="version", version=f"lorekeeper {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    demo = sub.add_parser("demo", help="run the pipeline on sample data (no creds)")
    demo.add_argument("-o", "--out", default="./knowledge", help="output directory")

    serve = sub.add_parser("serve", help="run the FastAPI app via uvicorn")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.command == "demo":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        asyncio.run(_run_demo(args.out))
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("lorekeeper.app:app", host=args.host, port=args.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
