from antix_ai.query.understanding import QueryPlan
from antix_ai.retrieval.models import Candidate
from antix_ai.retrieval.relevance import filter_relevant, name_tokens


def plan(q, entities=()):
    return QueryPlan(query=q, standalone_query=q, intent="fact_lookup", search_queries=[q],
                     entities=list(entities))


def cand(post_id, title, text, sim=0.3, entity_hit=False):
    return Candidate(chunk_id=post_id, post_id=post_id, text=text, title=title, source_name="s",
                     source_id=1, url=None, published_at=None, story_id=None, summary_short="",
                     key_facts=[], importance=0.5, content_type="news", similarity=sim,
                     entity_hit=entity_hit)


NVIDIA = cand(1, "Nvidia unveils Blackwell Ultra", "Nvidia introduced the Blackwell Ultra GPU.")
GOOGLE = cand(2, "Gemini 2.5 tops leaderboards", "Google DeepMind released Gemini 2.5.")


def test_name_tokens_drop_generic_suffixes():
    assert name_tokens("Zorblax Dynamics") == ["zorblax"]
    assert name_tokens("OpenAI Inc.") == ["openai"]


def test_unknown_entity_yields_no_evidence():
    kept, dropped = filter_relevant(plan("What did Zorblax Dynamics announce?", ["Zorblax Dynamics"]),
                                    [NVIDIA, GOOGLE])
    assert kept == [] and dropped == 2


def test_known_entity_keeps_only_articles_that_mention_it():
    kept, dropped = filter_relevant(plan("What did Nvidia announce?", ["Nvidia"]), [NVIDIA, GOOGLE])
    assert [c.post_id for c in kept] == [1] and dropped == 1


def test_entity_hit_from_index_counts_even_if_text_uses_alias():
    c = cand(3, "Chipmaker news", "The Santa Clara firm showed a new GPU.", entity_hit=True)
    kept, _ = filter_relevant(plan("Nvidia GPU news", ["Nvidia"]), [c])
    assert kept == [c]


def test_term_gate_drops_unrelated_low_similarity_but_keeps_semantically_close():
    p = plan("quantum computing breakthroughs")
    unrelated = cand(4, "Apple on-device AI", "Apple announced writing tools.", sim=0.1)
    close = cand(5, "Qubit milestone", "Researchers demonstrated error correction.", sim=0.7)
    kept, _ = filter_relevant(p, [unrelated, close])
    assert [c.post_id for c in kept] == [5]


def test_no_constraints_keeps_everything():
    kept, dropped = filter_relevant(plan("what's new"), [NVIDIA, GOOGLE])
    assert len(kept) == 2 and dropped == 0


def test_time_and_domain_words_are_not_topical_terms():
    # "latest AI news yesterday" has no topical content -> nothing may be filtered out
    c = cand(9, "OpenAI releases GPT-5", "OpenAI announced GPT-5.", sim=0.0)
    kept, dropped = filter_relevant(plan("What's the latest AI news yesterday?"), [c])
    assert kept == [c] and dropped == 0
