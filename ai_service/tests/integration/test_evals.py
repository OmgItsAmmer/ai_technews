"""The eval harness itself works end to end on the seeded corpus (offline providers)."""

from __future__ import annotations

import json

import pytest

from antix_ai.evals.metrics import aggregate
from antix_ai.evals.runner import AntixBackend, run_eval

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_harness_scores_a_mini_golden_set(rt, seeded):
    cases = [
        {"id": "f1", "kind": "fact_lookup", "question": "How much did Anthropic raise from Amazon?",
         "expected_post_ids": [3]},
        {"id": "u1", "kind": "unanswerable", "question": "What did Zorblax Dynamics say about the Quantum Frobnicator 9000?",
         "expected_post_ids": []},
        {"id": "c1", "kind": "chit_chat", "question": "hello", "expected_post_ids": []},
    ]
    results = await run_eval(rt, AntixBackend(rt), cases)
    agg = aggregate(results)
    assert agg["cases"] == 3 and agg["errors"] == 0
    by = {r.id: r for r in results}
    assert by["f1"].scores["recall"] == 1.0
    assert by["u1"].scores["correct_refusal"] == 1.0
    json.dumps(agg)
