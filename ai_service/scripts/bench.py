"""Latency benchmark against a running service.

  python scripts/bench.py --url http://localhost:8100 --key $AI_SERVICE_KEY --concurrency 8 --rounds 5

Measures time-to-first-token and total latency per query (SSE), prints p50/p95 and error rate,
and exits non-zero if the targets from architecture.md section 10 are missed (use in CI/staging).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

import httpx

QUERIES = [
    "What's the latest AI news this week?",
    "Recap today's top stories",
    "What did OpenAI announce recently?",
    "Compare Anthropic and OpenAI based on recent news",
    "How much funding did AI startups raise this month?",
    "What happened yesterday?",
    "Explain what a mixture-of-experts model is",
    "Which chips were announced recently?",
]


async def one(client: httpx.AsyncClient, url: str, query: str) -> tuple[float | None, float, bool]:
    t0 = time.perf_counter()
    first = None
    ok = False
    try:
        async with client.stream("POST", f"{url}/v1/ask", json={"query": query}) as r:
            r.raise_for_status()
            async for chunk in r.aiter_text():
                if first is None and "event: token" in chunk:
                    first = (time.perf_counter() - t0) * 1000
                if "event: final" in chunk:
                    ok = True
    except httpx.HTTPError:
        pass
    return first, (time.perf_counter() - t0) * 1000, ok


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8100")
    ap.add_argument("--key", required=True)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--ttft-p50-ms", type=float, default=1500)
    ap.add_argument("--total-p95-ms", type=float, default=6000)
    args = ap.parse_args()

    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(headers={"X-Service-Key": args.key}, timeout=60) as client:
        async def run(q: str):
            async with sem:
                return await one(client, args.url, q)

        results = await asyncio.gather(*(run(q) for _ in range(args.rounds) for q in QUERIES))

    firsts = sorted(r[0] for r in results if r[0] is not None)
    totals = sorted(r[1] for r in results if r[2])
    errors = sum(1 for r in results if not r[2])
    if not totals:
        print("no successful requests")
        return 2
    p = lambda xs, q: xs[min(len(xs) - 1, int(len(xs) * q))]  # noqa: E731
    report = {
        "requests": len(results), "errors": errors, "concurrency": args.concurrency,
        "ttft_p50_ms": round(p(firsts, 0.5), 1) if firsts else None,
        "total_p50_ms": round(statistics.median(totals), 1), "total_p95_ms": round(p(totals, 0.95), 1),
    }
    print(json.dumps(report, indent=2))
    bad = errors > 0 or (firsts and report["ttft_p50_ms"] > args.ttft_p50_ms) or report["total_p95_ms"] > args.total_p95_ms
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
