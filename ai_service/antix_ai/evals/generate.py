"""Build a golden eval set from the real approved corpus (no LLM required).

Case kinds
  fact_lookup      question whose answer is a key fact of one specific article
  entity_overview  "what's the news about <entity>" -> that entity's articles
  compare          two entities from different articles
  latest           recency question (window-checked)
  time_trap        asks about a window that contains NO articles (must refuse / cite nothing)
  unanswerable     invented entity or detail not in the corpus (must refuse)
  out_of_scope     unrelated to tech news (must decline)
  chit_chat        greetings (no citations)
  followup         multi-turn: second turn depends on the first

Review the generated file by hand before trusting it; add real user questions from 👎 traces.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from antix_ai.ingestion.loader import table
from antix_ai.runtime import create_runtime

INVENTED = [
    ("Zorblax Dynamics", "launched the Quantum Frobnicator 9000"),
    ("Nimbus Quillworks", "acquired a lunar mining startup"),
    ("Veldt Robotics", "released the Gryphon-7 humanoid"),
    ("Plexora AI", "raised $900 million at a $12 billion valuation"),
    ("Helios Photonic", "unveiled a 4-exaflop optical chip"),
]
OUT_OF_SCOPE = [
    "What's a good recipe for banana bread?",
    "Who won the football match last night?",
    "What is the capital of Australia?",
    "Can you give me medical advice about my back pain?",
]
CHIT = ["hello", "thanks!", "what can you do?"]


def _write_file(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


async def generate_cli(out: str, n: int) -> None:
    rt = await create_runtime()
    rng = random.Random(7)
    try:
        arts = await rt.db.fetch(
            f"""SELECT a.post_id, a.title, a.published_at, a.key_facts, a.story_id, a.summary_short
                FROM ai.article a JOIN {table(rt.settings.posts_table)} p ON p.id = a.post_id AND p.status='approved'
                WHERE a.published_at IS NOT NULL ORDER BY a.published_at DESC LIMIT 400"""
        )
        ents = await rt.db.fetch(
            """SELECT e.name, array_agg(ae.post_id ORDER BY ae.salience DESC) AS posts, count(*) AS n
               FROM ai.entity e JOIN ai.article_entity ae ON ae.entity_id = e.id
               WHERE e.type IN ('company','product','model','person','org') AND ae.salience >= 0.5
               GROUP BY e.id HAVING count(*) BETWEEN 2 AND 12 ORDER BY n DESC LIMIT 60"""
        )
        now = datetime.now(UTC)
        cases: list[dict] = []

        def add(kind: str, q: str, **kw):
            cases.append({"id": f"{kind}-{len(cases):03d}", "kind": kind, "question": q, **kw})

        # fact lookups: one question per sampled article using its title entities
        sample = rng.sample(arts, min(len(arts), int(n * 0.35)))
        for a in sample:
            facts = [f["fact"] for f in (a["key_facts"] or []) if re.search(r"\d", f["fact"])]
            if facts:
                add("fact_lookup", f"{a['title']}: what are the key details?",
                    expected_post_ids=[a["post_id"]], expected_keywords=[],
                    note=f"expects a fact like: {facts[0][:120]}")
            else:
                add("fact_lookup", f"What is the news about: {a['title']}?",
                    expected_post_ids=[a["post_id"]])

        for e in ents[: int(n * 0.15)]:
            add("entity_overview", f"What's the latest news about {e['name']}?",
                expected_post_ids=e["posts"][:5])

        for e1, e2 in zip(ents[::2], ents[1::2], strict=False):
            if len(cases) >= n * 0.65:
                break
            add("compare", f"Compare {e1['name']} and {e2['name']} based on recent news",
                expected_post_ids=e1["posts"][:2] + e2["posts"][:2])

        # latest / window questions
        for label, days in (("today", 1), ("this week", 7), ("yesterday", 1)):
            end = now + timedelta(minutes=1)
            start = now - timedelta(days=days)
            if label == "yesterday":
                d0 = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                start, end = d0, d0 + timedelta(days=1)
            in_window = [a["post_id"] for a in arts if start <= a["published_at"] < end]
            add("latest", f"What's the latest AI news {label}?", expected_post_ids=in_window[:8],
                window={"from": start.isoformat(), "to": end.isoformat()})

        # time traps: windows before the corpus begins
        oldest = min((a["published_at"] for a in arts), default=now)
        for yrs in (2, 3):
            ws, we = oldest - timedelta(days=365 * yrs), oldest - timedelta(days=365 * yrs - 30)
            add("time_trap", f"What AI news happened in {ws.strftime('%B %Y')}?",
                window={"from": ws.isoformat(), "to": we.isoformat()}, expected_post_ids=[])

        # unanswerable: invented entities
        for name, act in INVENTED * 2:
            add("unanswerable", f"What did {name} say after they {act}?", expected_post_ids=[])
        for q in OUT_OF_SCOPE:
            add("out_of_scope", q, expected_post_ids=[])
        for q in CHIT:
            add("chit_chat", q, expected_post_ids=[])

        # multi-turn
        for e in ents[:5]:
            add("followup", f"What's the news on {e['name']}?", expected_post_ids=e["posts"][:3],
                followup="And when did that happen?")

        cases = cases[:n] if len(cases) > n else cases
        path = Path(out)
        body = "\n".join(json.dumps(c, default=str) for c in cases) + "\n"
        await asyncio.to_thread(_write_file, path, body)
        kinds: dict[str, int] = {}
        for c in cases:
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        print(f"wrote {len(cases)} cases to {path}: {kinds}")
    finally:
        await rt.close()
