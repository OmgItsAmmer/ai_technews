"""Query understanding: question -> QueryPlan (intent, filters, search queries, time range)."""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from antix_ai import prompts
from antix_ai.core.cache import stable_hash
from antix_ai.ingestion.enricher import extract_candidate_entities
from antix_ai.ingestion.entities import resolve_query_entities
from antix_ai.ingestion.loader import table
from antix_ai.providers.base import Message, ProviderError
from antix_ai.providers.offline import OfflineChat
from antix_ai.providers.structured import complete_structured
from antix_ai.query.timeparse import TimeRange, default_window, implies_recency, parse_time_range
from antix_ai.runtime import Runtime

logger = logging.getLogger(__name__)

Intent = Literal[
    "latest", "briefing", "fact_lookup", "entity_overview", "compare", "timeline",
    "explain_concept", "analysis", "out_of_scope", "chit_chat",
]
AnswerShape = Literal["bullets", "paragraph", "table", "timeline"]
INTENTS: tuple[str, ...] = Intent.__args__  # type: ignore[attr-defined]

# Bump when planning logic changes so cached plans from older code are never served
PLANNER_VERSION = 2

# Words that are never useful as entities on an AI/tech news site
GENERIC_ENTITIES = frozenset(
    "ai ml tech technology news today yesterday tomorrow artificial intelligence machine learning "
    "latest update updates".split()
)

# Default look-back when the question implies recency but names no period
DEFAULT_WINDOWS = {"latest": 7, "briefing": 2, "entity_overview": 30, "timeline": 180}


class LLMPlan(BaseModel):
    intent: str = "fact_lookup"
    search_queries: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    compare_targets: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    time_expression: str | None = None
    answer_shape: str = "paragraph"

    @field_validator("search_queries", "entities", "compare_targets", "sources", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v if x]


class QueryPlan(BaseModel):
    query: str
    standalone_query: str
    intent: Intent
    search_queries: list[str]
    entities: list[str] = Field(default_factory=list)
    entity_ids: list[int] = Field(default_factory=list)
    compare_targets: list[str] = Field(default_factory=list)
    source_ids: list[int] = Field(default_factory=list)
    source_names: list[str] = Field(default_factory=list)
    time_range: dict | None = None
    answer_shape: AnswerShape = "paragraph"
    needs_freshness: bool = False
    planner: str = "heuristic"
    today: str = ""
    timezone: str = "UTC"

    def window(self) -> TimeRange | None:
        if not self.time_range:
            return None
        tr = self.time_range
        return TimeRange(
            datetime.fromisoformat(tr["from"]), datetime.fromisoformat(tr["to"]),
            tr.get("label", ""), tr.get("source", "explicit"),
        )


# ------------------------------------------------------------------ sources

_SOURCES_CACHE: dict[str, tuple[float, list[dict]]] = {}


async def known_sources(rt: Runtime) -> list[dict]:
    hit = _SOURCES_CACHE.get("all")
    if hit and time.monotonic() - hit[0] < 300:
        return hit[1]
    try:
        rows = await rt.db.fetch(
            f"SELECT id, name FROM {table(rt.settings.sources_table)} WHERE is_active ORDER BY name"
        )
    except Exception as exc:
        logger.warning("could not load sources: %s", exc)
        rows = []
    _SOURCES_CACHE["all"] = (time.monotonic(), rows)
    return rows


def match_sources(text: str, names: list[str], sources: list[dict]) -> list[dict]:
    lowered = text.lower()
    wanted = {n.lower().strip() for n in names}
    out = []
    for s in sources:
        n = s["name"].lower()
        if n in wanted or re.search(rf"\b{re.escape(n)}\b", lowered):
            out.append(s)
    return out


# --------------------------------------------------------------- heuristics

_CHIT = re.compile(
    r"^\s*(hi|hello|hey|yo|thanks|thank you|thx|good (morning|evening|night)|who are you|"
    r"what can you do|help|ok|okay|cool|great|bye)\b[\s!?.]*$",
    re.I,
)
_COMPARE = re.compile(r"\b(vs\.?|versus|compare[ds]?|comparison|difference between|better than)\b", re.I)
_TIMELINE = re.compile(r"\b(timeline|history of|evolv|over time|so far|chronolog|how did .* develop)", re.I)
_BRIEFING = re.compile(
    r"\b(brief(ing)?|recap|round-?up|digest|top (stories|news|headlines)|summar(y|ise|ize) "
    r"(of )?(the |today|this|last|yesterday)|what happened (today|yesterday|this week|last week))",
    re.I,
)
_EXPLAIN = re.compile(r"^\s*(what (is|are)|explain|define|how does|how do|meaning of)\b", re.I)
_ANALYSIS = re.compile(r"\b(why|impact|implication|mean for|consequence|should i|opinion|analy[sz])", re.I)
_LATEST = re.compile(r"\b(latest|recent|new|news|happening|updates?|headlines?|trending)\b", re.I)


def heuristic_intent(q: str, has_entities: bool, has_time: bool) -> str:
    if _CHIT.match(q):
        return "chit_chat"
    if _COMPARE.search(q):
        return "compare"
    if _BRIEFING.search(q):
        return "briefing"
    if _TIMELINE.search(q):
        return "timeline"
    if _EXPLAIN.match(q) and not has_time and not _LATEST.search(q):
        return "explain_concept"
    if _ANALYSIS.search(q):
        return "analysis"
    if _LATEST.search(q) or has_time:
        return "entity_overview" if has_entities else "latest"
    return "fact_lookup"


def _split_compare(q: str) -> list[str]:
    m = re.search(r"(?:compare\s+)?(.+?)\s+(?:vs\.?|versus|and|or|with)\s+(.+?)(?:[?.]|$)", q, re.I)
    if not m:
        return []
    clean = lambda s: re.sub(r"^(compare|between|the)\s+", "", s.strip(), flags=re.I)  # noqa: E731
    return [clean(m[1])[-60:], clean(m[2])[:60]]


# --------------------------------------------------------------- main entry


async def understand(
    rt: Runtime,
    query: str,
    standalone: str,
    *,
    tz: str | None = None,
    now: datetime | None = None,
    usage_cb=None,
) -> QueryPlan:
    tz = tz or rt.settings.default_timezone
    now = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        local = now.astimezone(ZoneInfo(tz))
    except Exception:
        tz, local = "UTC", now
    sources = await known_sources(rt)

    cache_key = stable_hash(
        "plan", PLANNER_VERSION, prompts.prompt_id("understand"), standalone, local.date(), tz
    )
    if cached := await rt.cache.get_json("plan", cache_key):
        return QueryPlan.model_validate(cached)

    llm_plan: LLMPlan | None = None
    if not isinstance(rt.providers.fast, OfflineChat):
        try:
            system = prompts.load("understand").format(
                today=local.date().isoformat(),
                weekday=local.strftime("%A"),
                sources=", ".join(s["name"] for s in sources[:60]) or "unknown",
            )
            llm_plan = await complete_structured(
                rt.providers.fast,
                [Message("system", system), Message("user", standalone)],
                LLMPlan,
                max_tokens=400,
                usage_cb=usage_cb,
            )
        except ProviderError as exc:
            logger.info("planner LLM unavailable, using heuristics: %s", exc)

    plan = await _build_plan(rt, query, standalone, llm_plan, sources, now, tz, local)
    await rt.cache.set_json("plan", cache_key, plan.model_dump(), rt.settings.cache_plan_ttl)
    return plan


async def _build_plan(
    rt: Runtime,
    query: str,
    standalone: str,
    llm: LLMPlan | None,
    sources: list[dict],
    now: datetime,
    tz: str,
    local: datetime,
) -> QueryPlan:
    # Time: always resolved deterministically (LLM only points at the phrase)
    window = None
    if llm and llm.time_expression:
        window = parse_time_range(llm.time_expression, now, tz)
    window = window or parse_time_range(standalone, now, tz)

    # Entities: known entities from the index + LLM / heuristic mentions
    hint_names = list(llm.entities) if llm else extract_candidate_entities(standalone, 5)
    hint_names = [h for h in hint_names if h.strip().lower() not in GENERIC_ENTITIES]
    resolved = [
        r for r in await resolve_query_entities(rt.db, standalone, hint_names)
        if r["norm_name"] not in GENERIC_ENTITIES
    ]
    entity_names = list(dict.fromkeys([r["name"] for r in resolved] + hint_names))[:6]

    matched_sources = match_sources(standalone, llm.sources if llm else [], sources)

    intent = (llm.intent.strip().lower() if llm else "") or ""
    if intent not in INTENTS:
        intent = heuristic_intent(standalone, bool(entity_names), window is not None)

    needs_fresh = intent in ("latest", "briefing") or implies_recency(standalone)
    if window is None and intent in DEFAULT_WINDOWS and needs_fresh:
        window = default_window(now, DEFAULT_WINDOWS[intent], f"last {DEFAULT_WINDOWS[intent]} days")

    compare_targets = (llm.compare_targets if llm else []) or (
        _split_compare(standalone) if intent == "compare" else []
    )
    queries = [q for q in (llm.search_queries if llm else []) if q.strip()][:3] or [standalone]
    if intent == "compare" and compare_targets:
        queries = list(dict.fromkeys(queries[:1] + [f"{t} {standalone}" for t in compare_targets[:4]]))

    shape = (llm.answer_shape if llm else "") or ""
    if shape not in ("bullets", "paragraph", "table", "timeline"):
        shape = {"briefing": "bullets", "latest": "bullets", "timeline": "timeline",
                 "compare": "table"}.get(intent, "paragraph")

    return QueryPlan(
        query=query,
        standalone_query=standalone,
        intent=intent,  # type: ignore[arg-type]
        search_queries=queries,
        entities=entity_names,
        entity_ids=[r["id"] for r in resolved],
        compare_targets=compare_targets[:4],
        source_ids=[s["id"] for s in matched_sources],
        source_names=[s["name"] for s in matched_sources],
        time_range=window.as_dict() if window else None,
        answer_shape=shape,  # type: ignore[arg-type]
        needs_freshness=needs_fresh,
        planner="llm" if llm else "heuristic",
        today=local.date().isoformat(),
        timezone=tz,
    )
