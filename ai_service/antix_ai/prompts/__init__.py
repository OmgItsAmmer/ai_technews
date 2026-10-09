"""Versioned prompt templates. Change a prompt => bump its version and run evals."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

VERSIONS = {
    "enrich": "v1",
    "understand": "v1",
    "rewrite": "v1",
    "summarize_history": "v1",
    "answer": "v1",
    "verify": "v1",
    "briefing": "v1",
}


@lru_cache
def load(name: str) -> str:
    return files(__package__).joinpath(f"{name}.{VERSIONS[name]}.md").read_text(encoding="utf-8")


def prompt_id(name: str) -> str:
    return f"{name}.{VERSIONS[name]}"
