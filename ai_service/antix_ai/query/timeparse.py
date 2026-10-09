"""Deterministic resolution of relative/absolute time phrases.

Time is never left to the LLM: "yesterday", "this week", "since Monday", "in September",
"Oct 5", "past 3 days" are resolved here against the real clock in the user's timezone.
Ranges are half-open [start, end) in UTC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
WEEKDAYS = {
    d: i
    for i, names in enumerate(
        [("monday", "mon"), ("tuesday", "tue", "tues"), ("wednesday", "wed"),
         ("thursday", "thu", "thurs"), ("friday", "fri"), ("saturday", "sat"), ("sunday", "sun")]
    )
    for d in names
}
UNIT_DAYS = {"hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}
WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "few": 3, "couple of": 2, "couple": 2,
            "several": 5, "24": 24}

_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_WD_RE = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_NUM_RE = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|few|couple of|couple|several)"


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime
    label: str
    source: str = "explicit"  # explicit | implied | default

    def as_dict(self) -> dict:
        return {"from": self.start.isoformat(), "to": self.end.isoformat(),
                "label": self.label, "source": self.source}

    def contains(self, ts: datetime | None) -> bool:
        return ts is not None and self.start <= ts < self.end


def _tz(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _day_start(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time.min, tzinfo=tz).astimezone(UTC)


def _rng(start_d: date, end_d_excl: date, tz: ZoneInfo, label: str) -> TimeRange:
    return TimeRange(_day_start(start_d, tz), _day_start(end_d_excl, tz), label)


def _num(token: str) -> float:
    token = token.strip().lower()
    return float(token) if token.isdigit() else float(WORD_NUM.get(token, 1))


def _month_range(year: int, month: int, tz: ZoneInfo, label: str) -> TimeRange:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return _rng(start, end, tz, label)


def parse_time_range(text: str, now: datetime | None = None, tz: str | None = None) -> TimeRange | None:
    """Return the first time constraint found in ``text`` (or None)."""
    zone = _tz(tz)
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    local = now_utc.astimezone(zone)
    today = local.date()
    tomorrow = today + timedelta(days=1)
    q = " " + re.sub(r"\s+", " ", text.lower()) + " "

    # ISO date: 2026-10-05
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", q):
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
            return _rng(d, d + timedelta(days=1), zone, d.isoformat())
        except ValueError:
            pass

    # "past/last N days/hours/weeks/months"
    if m := re.search(rf"\b(?:past|last|previous|recent)\s+{_NUM_RE}?\s*(hour|day|week|month|year)s?\b", q):
        n = _num(m[1]) if m[1] else 1
        unit = m[2]
        if unit == "hour":
            return TimeRange(now_utc - timedelta(hours=n), now_utc + timedelta(minutes=1),
                             f"past {int(n)} hours")
        if m[1] is None and unit in ("week", "month", "year") and re.search(r"\blast\s+" + unit, q):
            pass  # "last week" = calendar period; handled below
        else:
            days = n * UNIT_DAYS[unit]
            return TimeRange(now_utc - timedelta(days=days), now_utc + timedelta(minutes=1),
                             f"past {int(n)} {unit}s")

    if re.search(r"\b(today|tonight|this morning|this afternoon|this evening)\b", q):
        return _rng(today, tomorrow, zone, "today")
    if re.search(r"\bday before yesterday\b", q):
        d = today - timedelta(days=2)
        return _rng(d, d + timedelta(days=1), zone, "day before yesterday")
    if re.search(r"\byesterday\b", q):
        return _rng(today - timedelta(days=1), today, zone, "yesterday")

    week_start = today - timedelta(days=today.weekday())
    if re.search(r"\bthis week(end)?\b", q):
        if "weekend" in q:
            sat = week_start + timedelta(days=5)
            return _rng(sat, sat + timedelta(days=2), zone, "this weekend")
        return _rng(week_start, tomorrow, zone, "this week")
    if re.search(r"\b(last|previous|past) weekend\b", q):
        sat = week_start - timedelta(days=2)
        return _rng(sat, sat + timedelta(days=2), zone, "last weekend")
    if re.search(r"\b(last|previous) week\b", q):
        return _rng(week_start - timedelta(days=7), week_start, zone, "last week")

    month_start = today.replace(day=1)
    if re.search(r"\bthis month\b", q):
        return _rng(month_start, tomorrow, zone, "this month")
    if re.search(r"\b(last|previous) month\b", q):
        prev = (month_start - timedelta(days=1)).replace(day=1)
        return _rng(prev, month_start, zone, "last month")
    if re.search(r"\bthis year\b", q):
        return _rng(date(today.year, 1, 1), tomorrow, zone, "this year")
    if re.search(r"\b(last|previous) year\b", q):
        return _rng(date(today.year - 1, 1, 1), date(today.year, 1, 1), zone, "last year")

    # "since monday" / "since oct 3"
    if m := re.search(rf"\bsince\s+(?:last\s+)?({_WD_RE})\b", q):
        back = (today.weekday() - WEEKDAYS[m[1]]) % 7 or 7
        d = today - timedelta(days=back)
        return _rng(d, tomorrow, zone, f"since {d.strftime('%A')}")
    # "on monday" / "last tuesday"
    if m := re.search(rf"\b(?:on|last|this past)\s+({_WD_RE})\b", q):
        back = (today.weekday() - WEEKDAYS[m[1]]) % 7 or 7
        d = today - timedelta(days=back)
        return _rng(d, d + timedelta(days=1), zone, d.strftime("%A %b %d"))

    # "oct 5", "october 5th", "5 october", optional year
    m = re.search(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", q) or None
    m2 = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b(?:,?\s+(\d{{4}}))?", q)
    if m or m2:
        if m:
            mon, day, yr = MONTHS[m[1]], int(m[2]), m[3]
        else:
            mon, day, yr = MONTHS[m2[2]], int(m2[1]), m2[3]
        year = int(yr) if yr else today.year
        try:
            d = date(year, mon, day)
            if not yr and d > today:
                d = date(year - 1, mon, day)
            return _rng(d, d + timedelta(days=1), zone, d.isoformat())
        except ValueError:
            pass

    # "since september", "in september", "september 2025"
    if m := re.search(rf"\bsince\s+({_MONTH_RE})\b(?:\s+(\d{{4}}))?", q):
        mon = MONTHS[m[1]]
        year = int(m[2]) if m[2] else (today.year if mon <= today.month else today.year - 1)
        return _rng(date(year, mon, 1), tomorrow, zone, f"since {m[1].title()} {year}")
    if m := re.search(rf"\b(?:in|during|of)\s+({_MONTH_RE})\b(?:\s+(\d{{4}}))?|\b({_MONTH_RE})\s+(\d{{4}})\b", q):
        name = m[1] or m[3]
        yr = m[2] or m[4]
        if name not in ("may", "mar", "jun") or yr or re.search(rf"\b(in|during)\s+{name}\b", q):
            mon = MONTHS[name]
            year = int(yr) if yr else (today.year if mon <= today.month else today.year - 1)
            return _month_range(year, mon, zone, f"{name.title()} {year}")

    if m := re.search(r"\b(?:in|during|of|since)\s+(20\d{2})\b", q):
        year = int(m[1])
        if "since" in m[0]:
            return _rng(date(year, 1, 1), tomorrow, zone, f"since {year}")
        return _rng(date(year, 1, 1), date(year + 1, 1, 1), zone, str(year))

    return None


_RECENCY = re.compile(
    r"\b(latest|recent(ly)?|lately|newest|current(ly)?|right now|breaking|new|this week|so far|"
    r"what('s| is) new|what('s| is) happening|updates?|trending|headlines?)\b",
    re.I,
)


def implies_recency(text: str) -> bool:
    return bool(_RECENCY.search(text))


def default_window(now: datetime | None, days: int, label: str) -> TimeRange:
    end = (now or datetime.now(UTC)).astimezone(UTC)
    return TimeRange(end - timedelta(days=days), end + timedelta(minutes=1), label, "default")
