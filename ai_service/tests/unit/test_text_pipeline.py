from antix_ai.core.tokens import count_tokens
from antix_ai.ingestion.chunker import chunk_text, split_sentences
from antix_ai.ingestion.cleaner import clean_text
from antix_ai.ingestion.enricher import extract_candidate_entities
from antix_ai.ingestion.entities import normalize_entity
from antix_ai.providers.base import ThinkStreamFilter, strip_think
from antix_ai.providers.structured import extract_json


def test_clean_text_strips_html_boilerplate_and_dupes():
    dup = "The same long paragraph repeated here for scrapers."
    raw = f"<p>Hello &amp; welcome</p>\nAdvertisement\n\n\nSubscribe now\n{dup}\n{dup}\nShare this article"
    out = clean_text(raw)
    assert "Hello & welcome" in out
    assert "Advertisement" not in out and "Subscribe" not in out and "Share this" not in out
    assert out.count("same long paragraph") == 1


def test_short_article_is_single_chunk():
    chunks = chunk_text("Short article about AI. " * 20)
    assert len(chunks) == 1 and chunks[0].ord == 0


def test_long_article_chunks_respect_target_and_overlap():
    para = " ".join(f"Sentence number {i} talks about GPUs and models." for i in range(12))
    text = "\n".join(para for _ in range(12))
    chunks = chunk_text(text, target_tokens=200, overlap_tokens=40)
    assert len(chunks) > 3
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    assert all(c.token_count <= 200 * 1.6 for c in chunks)


def test_sentence_split_keeps_abbreviations():
    s = split_sentences("Dr. Smith of U.S. Steel spoke. Then Apple Inc. replied. It worked!")
    assert s[0].startswith("Dr. Smith") and len(s) == 3


def test_entity_normalization():
    assert normalize_entity("OpenAI, Inc.") == "openai"
    assert normalize_entity("The Verge") == "verge"
    assert normalize_entity("GPT-5") == "gpt-5"


def test_candidate_entities():
    names = extract_candidate_entities("OpenAI released GPT-5 today. Sam Altman said OpenAI is excited.")
    assert "OpenAI" in names and "GPT-5" in names


def test_strip_think():
    assert strip_think("<think>hmm\nsecret</think>\nAnswer") == "Answer"
    assert strip_think("Answer <think>unterminated") == "Answer"


def test_think_stream_filter_across_chunks():
    f = ThinkStreamFilter()
    out = "".join(f.feed(c) for c in ["Hel", "lo <thi", "nk>secret ", "stuff</th", "ink> world"]) + f.flush()
    assert "secret" not in out and out.startswith("Hello") and out.endswith("world")


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here: {"a": [1, 2,], "b": "x}y"} done') == {"a": [1, 2], "b": "x}y"}
    assert extract_json("<think>x</think>[1, 2]") == [1, 2]


def test_token_counter_monotonic():
    assert count_tokens("a b c d e f") < count_tokens("a b c d e f " * 10)


def test_refusal_detector():
    from antix_ai.evals.metrics import refused

    assert refused("I couldn't find articles on this in our database.")
    assert not refused("OpenAI released GPT-5 on Tuesday [S1].")
