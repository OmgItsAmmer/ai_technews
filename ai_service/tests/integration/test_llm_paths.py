"""LLM-dependent behaviour with a scripted model: planning, generation, verification, fallbacks."""

from __future__ import annotations

import dataclasses
import json

import pytest

from antix_ai.pipeline import AskRequest, ask_stream, ask_sync
from antix_ai.providers.registry import Providers
from antix_ai.providers.rerank import LLMReranker
from antix_ai.runtime import Runtime
from tests.fakes import ScriptedChat, answerer, planner, sids_in

pytestmark = pytest.mark.asyncio(loop_scope="session")


def with_models(rt: Runtime, fast: ScriptedChat, strong: ScriptedChat, rerank: bool = False) -> Runtime:
    p = rt.providers
    prov = Providers(fast=fast, strong=strong, embedder=p.embedder,
                     reranker=LLMReranker(fast) if rerank else p.reranker)
    return dataclasses.replace(rt, providers=prov)


async def test_grounded_answer_with_citations_and_verification(rt, seeded):
    seen = {}

    def gen(system, user):
        seen["system"], seen["user"] = system, user
        sid = next(s for s in sids_in(user) if True)  # first evidence block
        return f"Anthropic raised $4 billion from Amazon [{sid}]. Dario Amodei is the CEO [S99]."

    fast = ScriptedChat("fast", {
        "query planner": planner("fact_lookup", ["Anthropic Amazon funding"], ["Anthropic"]),
        "fact-checker": lambda s, u: json.dumps({"verdicts": [{"id": 0, "verdict": "supported", "reason": "ok"}]}),
    })
    strong = ScriptedChat("strong", {"GROUNDING RULES": gen})
    r2 = with_models(rt, fast, strong)

    out = await ask_sync(r2, AskRequest(query="How much did Anthropic raise from Amazon?", stream=False))
    assert "[S99]" not in out["answer"]                       # fabricated citation stripped
    assert out["citations"] and out["citations"][0]["post_id"] == 3
    assert out["grounding"] is not None and out["grounding"] > 0.7
    assert "Today is" in seen["system"]                       # clock injected
    assert "COVERAGE NOTES" in seen["user"] and "EVIDENCE" in seen["user"]


async def test_hallucinated_number_is_removed(rt, seeded):
    fast = ScriptedChat("fast", {"query planner": planner("fact_lookup", ["Nvidia Blackwell Ultra"], ["Nvidia"])})
    strong = ScriptedChat("strong", {"GROUNDING RULES": lambda s, u: (
        f"Nvidia unveiled Blackwell Ultra [{sids_in(u)[0]}].\n"
        f"The chip costs $40,000 each [{sids_in(u)[0]}].")})
    out = await ask_sync(with_models(rt, fast, strong),
                         AskRequest(query="What did Nvidia unveil?", stream=False))
    assert "$40,000" not in out["answer"] and "Blackwell Ultra" in out["answer"]


async def test_streaming_events_order_and_replacement_flag(rt, seeded):
    fast = ScriptedChat("fast", {"query planner": planner("latest", ["AI news"], time_expression="this week")})
    strong = ScriptedChat("strong", {"GROUNDING RULES": lambda s, u: f"- GPT-5 launched [{sids_in(u)[0]}]."})
    events = [e async for e in ask_stream(with_models(rt, fast, strong), AskRequest(query="latest AI news this week"))]
    types = [e["type"] for e in events]
    assert types[0] == "status" and "token" in types and types[-1] == "final"
    final = events[-1]
    assert final["citations"] and final["trace_id"] and final["replaced"] is False


async def test_planner_failure_falls_back_to_heuristics(rt, seeded):
    class Broken(ScriptedChat):
        async def complete(self, *a, **k):
            from antix_ai.providers.base import ProviderError
            raise ProviderError("down")

    out = await ask_sync(with_models(rt, Broken("fast"), ScriptedChat("strong", {"GROUNDING": answerer("ok [S1].")})),
                         AskRequest(query="What did Google release?", stream=False))
    assert out["intent"] and out["answer"]


async def test_strong_model_down_gives_extractive_answer(rt, seeded):
    from antix_ai.providers.base import ProviderError

    class Down(ScriptedChat):
        async def stream(self, *a, **k):
            raise ProviderError("overloaded")
            yield ""

    fast = ScriptedChat("fast", {"query planner": planner("fact_lookup", ["Gemini 2.5"], ["Google"])})
    out = await ask_sync(with_models(rt, fast, Down("strong")),
                         AskRequest(query="Tell me about Gemini 2.5", stream=False))
    assert "temporarily unavailable" in out["answer"] and out["citations"]
    assert out["grounding"] is None  # service-authored text is not "verified"


async def test_llm_reranker_reorders(rt, seeded):
    fast = ScriptedChat("fast", {
        "query planner": planner("fact_lookup", ["AI regulation Europe"], []),
        "rank news passages": lambda s, u: json.dumps({"ranking": [0, 1, 2]}),
    })
    strong = ScriptedChat("strong", {"GROUNDING": answerer("done")})
    r2 = with_models(rt, fast, strong, rerank=True)
    out = await ask_sync(r2, AskRequest(query="AI regulation in Europe", stream=False))
    assert out["answer"]
    assert any("rank news passages" in c[0] for c in fast.calls)


async def test_followup_is_rewritten_with_session_context(rt, seeded):
    sid = "followup-1"
    fast = ScriptedChat("fast", {
        "query planner": planner("fact_lookup", ["Nvidia Blackwell Ultra ship date"], ["Nvidia"]),
        "Rewrite the user": lambda s, u: json.dumps({"standalone": "When does Nvidia Blackwell Ultra ship?"}),
    })
    strong = ScriptedChat("strong", {"GROUNDING": lambda s, u: f"It ships in the second half of the year [{sids_in(u)[0]}]."})
    r2 = with_models(rt, fast, strong)
    await ask_sync(r2, AskRequest(query="What did Nvidia unveil?", session_id=sid, stream=False))
    await ask_sync(r2, AskRequest(query="when does it ship?", session_id=sid, stream=False))
    rewrite_calls = [c for c in fast.calls if "Rewrite the user" in c[0]]
    assert rewrite_calls and "Nvidia" in rewrite_calls[0][1]
    plan_user_inputs = [c[1] for c in fast.calls if "query planner" in c[0]]
    assert plan_user_inputs[-1] == "When does Nvidia Blackwell Ultra ship?"
