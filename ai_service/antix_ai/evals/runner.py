"""Eval runner. Same dataset + same metrics for any backend (new service or Scrutinize)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx

from antix_ai.evals.metrics import CaseResult, aggregate, score_case
from antix_ai.ingestion.loader import table
from antix_ai.pipeline import AskRequest, ask_stream
from antix_ai.runtime import Runtime, create_runtime


class Backend(Protocol):
    name: str

    async def ask(self, question: str, session_id: str | None) -> CaseResult: ...


class AntixBackend:
    name = "antix"

    def __init__(self, rt: Runtime):
        self.rt = rt

    async def ask(self, question: str, session_id: str | None) -> CaseResult:
        res = CaseResult(id="", kind="", question=question)
        t0 = time.perf_counter()
        async for ev in ask_stream(self.rt, AskRequest(query=question, session_id=session_id)):
            if ev["type"] == "token" and res.first_token_ms is None:
                res.first_token_ms = (time.perf_counter() - t0) * 1000
            elif ev["type"] == "final":
                res.answer = ev["answer"]
                res.cited_post_ids = [c["post_id"] for c in ev["citations"]]
                res.cited_dates = [datetime.fromisoformat(c["published_at"]) for c in ev["citations"] if c.get("published_at")]
                trace = await self.rt.db.fetchval(
                    "SELECT retrieved FROM ai.trace WHERE id = %s", (ev["trace_id"],)
                )
                res.retrieved_post_ids = [r["post_id"] for r in (trace or [])]
            elif ev["type"] == "error":
                res.error = ev["message"]
        res.latency_ms = (time.perf_counter() - t0) * 1000
        return res


class ScrutinizeBackend:
    """Calls the existing Scrutinize POST /v2/search exactly as the Django app does today."""

    name = "scrutinize"

    def __init__(self, rt: Runtime, base_url: str | None = None, client_key: str | None = None):
        self.rt = rt
        self.base = (base_url or os.environ.get("SCRUTINIZE_API_BASE_URL", "http://localhost:8000")).rstrip("/")
        key = client_key or os.environ.get("SCRUTINIZE_PUBLIC_CLIENT_KEY")
        if not key:
            raise SystemExit("set SCRUTINIZE_PUBLIC_CLIENT_KEY (and SCRUTINIZE_API_BASE_URL) to eval Scrutinize")
        self.http = httpx.AsyncClient(timeout=120, headers={"X-Client-Key": key})
        self.history: dict[str, list[dict]] = {}

    async def ask(self, question: str, session_id: str | None) -> CaseResult:
        res = CaseResult(id="", kind="", question=question)
        payload: dict = {"query": question}
        if session_id and self.history.get(session_id):
            payload["conversation"] = {"messages": self.history[session_id][-10:]}
        t0 = time.perf_counter()
        try:
            r = await self.http.post(f"{self.base}/v2/search", json=payload)
            r.raise_for_status()
            data = r.json()
            res.answer = data.get("answer", "")
            for src in data.get("sources", []):
                m = re.match(r"^post_(\d+)\.txt$", src.get("filename", ""))
                if m:
                    pid = int(m.group(1))
                    res.cited_post_ids.append(pid)
                    res.retrieved_post_ids.append(pid)
            res.cited_post_ids = list(dict.fromkeys(res.cited_post_ids))
            if session_id:
                h = self.history.setdefault(session_id, [])
                h += [{"role": "user", "content": question}, {"role": "assistant", "content": res.answer}]
            dates = await self.rt.db.fetch(
                f"SELECT COALESCE(published_at, fetched_at) AS d FROM {table(self.rt.settings.posts_table)} "
                "WHERE id = ANY(%s)", (res.cited_post_ids,))
            res.cited_dates = [d["d"] for d in dates if d["d"]]
        except Exception as exc:
            res.error = str(exc)[:300]
        res.latency_ms = (time.perf_counter() - t0) * 1000
        return res


async def _evidence_text(rt: Runtime, post_ids: list[int]) -> str:
    if not post_ids:
        return ""
    rows = await rt.db.fetch(
        f"SELECT title, summary, raw_content FROM {table(rt.settings.posts_table)} WHERE id = ANY(%s)",
        (post_ids,),
    )
    return "\n".join(f"{r['title']} {r['summary']} {r['raw_content']}" for r in rows)


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


async def run_eval(rt: Runtime, backend: Backend, cases: list[dict], concurrency: int = 1) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        sid = f"eval-{uuid.uuid4().hex[:8]}" if case.get("followup") else None
        res = await backend.ask(case["question"], sid)
        if case.get("followup"):
            res = await backend.ask(case["followup"], sid)
        res.id, res.kind = case["id"], case["kind"]
        evidence = await _evidence_text(rt, list(set(res.cited_post_ids)))
        score_case(case, res, evidence)
        results.append(res)
    return results


def format_report(backend: str, dataset: str, agg: dict, results: list[CaseResult]) -> str:
    lines = [f"# Eval report: {backend}", "", f"- dataset: `{dataset}`  - cases: {agg['cases']}  - errors: {agg['errors']}",
             f"- git: `{_git_sha()}`", "", "| metric | value |", "|---|---|"]
    for k, v in agg.items():
        if k not in ("cases", "errors", "by_kind"):
            lines.append(f"| {k} | {v} |")
    lines += ["", "## Worst cases", ""]
    bad = []
    for r in results:
        sc = [v for v in r.scores.values() if v is not None]
        if r.error or (sc and min(sc) < 0.5):
            bad.append(r)
    for r in bad[:25]:
        lines.append(f"- **{r.id}** `{r.kind}` — {r.question[:100]}\n  scores={r.scores} error={r.error}\n  answer: {r.answer[:240]!r}")
    return "\n".join(lines) + "\n"


def _write_report(out: Path, backend: str, dataset: str, agg: dict, results: list) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now():%Y%m%d-%H%M}-{backend}.md"
    path.write_text(format_report(backend, dataset, agg, results), encoding="utf-8")
    return path


async def run_cli(dataset: str, backend_name: str, limit: int | None, out_dir: str) -> None:
    rt = await create_runtime()
    try:
        text = await asyncio.to_thread(Path(dataset).read_text, encoding="utf-8")
        cases = [json.loads(line) for line in text.splitlines() if line.strip()]
        if limit:
            cases = cases[:limit]
        backend: Backend = AntixBackend(rt) if backend_name == "antix" else ScrutinizeBackend(rt)
        results = await run_eval(rt, backend, cases)
        agg = aggregate(results)
        git_sha = _git_sha()
        await rt.db.execute(
            "INSERT INTO ai.eval_run (backend, dataset, git_sha, metrics, cases) VALUES (%s, %s, %s, %s, %s)",
            (backend.name, dataset, git_sha, json.dumps(agg),
             json.dumps([{"id": r.id, "kind": r.kind, "scores": r.scores, "answer": r.answer[:500],
                          "cited": r.cited_post_ids, "error": r.error} for r in results])),
        )
        report = await asyncio.to_thread(
            _write_report, Path(out_dir), backend.name, dataset, agg, results
        )
        print(json.dumps(agg, indent=2))
        print(f"report: {report}")
    finally:
        await rt.close()
