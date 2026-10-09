from datetime import UTC, datetime

import pytest

from antix_ai.query.timeparse import implies_recency, parse_time_range

# Friday 2026-10-09 12:00 UTC
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def rng(text, tz="UTC"):
    r = parse_time_range(text, NOW, tz)
    return (r.start.date().isoformat(), r.end.date().isoformat()) if r else None


@pytest.mark.parametrize("text,expected", [
    ("what happened today", ("2026-10-09", "2026-10-10")),
    ("news from yesterday", ("2026-10-08", "2026-10-09")),
    ("the day before yesterday", ("2026-10-07", "2026-10-08")),
    ("this week", ("2026-10-05", "2026-10-10")),
    ("last week", ("2026-09-28", "2026-10-05")),
    ("this month", ("2026-10-01", "2026-10-10")),
    ("last month", ("2026-09-01", "2026-10-01")),
    ("since Monday", ("2026-10-05", "2026-10-10")),
    ("on Tuesday", ("2026-10-06", "2026-10-07")),
    ("in September", ("2026-09-01", "2026-10-01")),
    ("Oct 5", ("2026-10-05", "2026-10-06")),
    ("5th of october", ("2026-10-05", "2026-10-06")),
    ("2026-10-01", ("2026-10-01", "2026-10-02")),
    ("in 2025", ("2025-01-01", "2026-01-01")),
    ("last year", ("2025-01-01", "2026-01-01")),
    ("past 3 days", ("2026-10-06", "2026-10-09")),  # rolling window ending now
])
def test_ranges(text, expected):
    got = rng(text)
    assert got is not None, text
    assert got == expected


def test_no_time():
    assert parse_time_range("how does attention work", NOW) is None
    assert parse_time_range("tell me about OpenAI", NOW) is None


def test_may_the_verb_is_not_a_month():
    assert parse_time_range("which models may be released", NOW) is None


def test_timezone_shifts_day_boundary():
    late = datetime(2026, 10, 9, 23, 0, tzinfo=UTC)  # already Oct 10 in Karachi
    r = parse_time_range("today", late, "Asia/Karachi")
    assert r.start.isoformat().startswith("2026-10-09T19:00")
    assert r.end > late


def test_bad_timezone_falls_back():
    assert parse_time_range("today", NOW, "Not/AZone") is not None


def test_recency_detection():
    assert implies_recency("what's the latest on GPT-5")
    assert not implies_recency("explain transformers")
