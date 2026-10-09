from datetime import UTC, datetime

import pytest

from antix_ai.providers.offline import OfflineChat
from antix_ai.retrieval.models import EvidenceArticle
from antix_ai.verification.checks import (
    find_uncited,
    number_support,
    strip_unknown_citations,
    temporal_issues,
    verify_answer,
)


def art(sid, text, day=8):
    return EvidenceArticle(
        post_id=int(sid[1:]), title="OpenAI releases GPT-5", source_name="TechCrunch", url="u",
        published_at=datetime(2026, 10, day, tzinfo=UTC), story_id=None, story_sources=1,
        summary_short=text, key_facts=[], content_type="news", passages=[text], sid=sid,
    )


A = [art("S1", "OpenAI announced GPT-5 with a 1 million token context window priced at $5 per million input tokens.")]


def test_unknown_citations_are_stripped():
    out, unknown = strip_unknown_citations("GPT-5 launched [S1]. Also true [S9].", {"S1"})
    assert unknown == ["S9"] and "[S9]" not in out and "[S1]" in out


def test_uncited_claims_detected_but_meta_sentences_ignored():
    text = ("OpenAI released GPT-5 in 2026. I couldn't find pricing details in the articles. "
            "Background: transformers use attention.")
    assert find_uncited(text) == ["OpenAI released GPT-5 in 2026."]


def test_number_support():
    src = "priced at $5 per million input tokens, 1 million token context window"
    assert number_support("It costs $5 per million tokens [S1].", src)
    assert not number_support("It costs $50 per million tokens [S1].", src)


def test_temporal_flag_for_date_after_publication():
    by = {"S1": art("S1", "x", day=8)}
    assert temporal_issues("It shipped on Oct 20 [S1].", ["S1"], by)
    assert not temporal_issues("It was announced on Oct 7 [S1].", ["S1"], by)


@pytest.mark.asyncio
async def test_unsupported_number_is_removed_and_lowers_grounding():
    ans = ("OpenAI priced GPT-5 at $5 per million input tokens [S1].\n"
           "It also costs $99 per million output tokens [S1].")
    v = await verify_answer(ans, A, fast=OfflineChat(), use_llm=False)
    assert "$99" not in v.answer and "$5" in v.answer
    assert 0 < v.grounding < 1 and v.removed


@pytest.mark.asyncio
async def test_clean_answer_scores_full_grounding():
    v = await verify_answer("OpenAI announced GPT-5 with a 1 million token context window [S1].", A,
                            fast=OfflineChat(), use_llm=False)
    assert v.grounding == 1.0 and v.used_sids == ["S1"]


@pytest.mark.asyncio
async def test_uncited_claim_penalizes_grounding():
    v = await verify_answer("OpenAI launched GPT-5 and raised $10 billion.", A, fast=OfflineChat(), use_llm=False)
    assert v.grounding == 0.0 and v.uncited


@pytest.mark.asyncio
async def test_dates_from_metadata_are_not_flagged_as_unsupported_numbers():
    # The article body never mentions 2026 or the day; the date is metadata.
    ans = "OpenAI announced GPT-5 on October 8, 2026 [S1]."
    v = await verify_answer(ans, A, fast=OfflineChat(), use_llm=False)
    assert v.removed == [] and v.grounding == 1.0


def test_number_check_still_catches_wrong_figures_next_to_dates():
    assert not number_support("On Oct 8 the model cost $50 per million tokens [S1].",
                              "priced at $5 per million input tokens")
