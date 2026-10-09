"""Command line: migrate, serve, worker, backfill, reconcile, ask, evals."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys

from antix_ai.config import get_settings
from antix_ai.core.logging import configure_logging


def _run(coro):
    return asyncio.run(coro)


async def _backfill(days: int, force: bool) -> None:
    from antix_ai.ingestion.indexer import reconcile
    from antix_ai.runtime import create_runtime

    rt = await create_runtime()
    try:
        report = await reconcile(rt, days, force=force)
        print(json.dumps(report.__dict__, indent=2))
    finally:
        await rt.close()


async def _ask(query: str, session: str | None) -> None:
    from antix_ai.pipeline import AskRequest, ask_stream
    from antix_ai.runtime import create_runtime

    rt = await create_runtime()
    try:
        async for ev in ask_stream(rt, AskRequest(query=query, session_id=session)):
            if ev["type"] == "token":
                print(ev["text"], end="", flush=True)
            elif ev["type"] == "final":
                print("\n\n--- citations ---")
                for c in ev["citations"]:
                    print(f"[{c['sid']}] {c['title']} ({c['source_name']}, {c['date']}) {c['url']}")
                print(f"grounding={ev['grounding']} intent={ev['intent']} trace={ev['trace_id']}")
            elif ev["type"] == "error":
                print("\nERROR:", ev["message"])
    finally:
        await rt.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="antix-ai")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    p = sub.add_parser("serve")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--reload", action="store_true")
    sub.add_parser("worker")
    p = sub.add_parser("backfill")
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("ask")
    p.add_argument("query")
    p.add_argument("--session", default=None)
    p = sub.add_parser("eval")
    p.add_argument("--dataset", default="evals/datasets/golden.jsonl")
    p.add_argument("--backend", choices=["antix", "scrutinize"], default="antix")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", default="evals/reports")
    p = sub.add_parser("gen-evals")
    p.add_argument("--out", default="evals/datasets/golden.jsonl")
    p.add_argument("--n", type=int, default=150)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    if args.cmd == "migrate":
        sys.exit(subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"]))
    elif args.cmd == "serve":
        import uvicorn

        # On Windows uvicorn forces the Proactor loop, which psycopg async cannot use; "none" makes
        # asyncio.run fall back to the selector policy set in antix_ai/__init__.py.
        uvicorn.run("antix_ai.api.app:create_app", factory=True, host=args.host, port=args.port,
                    reload=args.reload, log_config=None,
                    loop="none" if sys.platform == "win32" else "auto")
    elif args.cmd == "worker":
        from arq.worker import run_worker

        from antix_ai.workers.tasks import WorkerSettings

        run_worker(WorkerSettings)
    elif args.cmd == "backfill":
        _run(_backfill(args.days or settings.backfill_days, args.force))
    elif args.cmd == "ask":
        _run(_ask(args.query, args.session))
    elif args.cmd == "eval":
        from antix_ai.evals.runner import run_cli

        _run(run_cli(args.dataset, args.backend, args.limit, args.out))
    elif args.cmd == "gen-evals":
        from antix_ai.evals.generate import generate_cli

        _run(generate_cli(args.out, args.n))


if __name__ == "__main__":
    main()
