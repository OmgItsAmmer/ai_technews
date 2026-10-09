"""Token counting. Uses tiktoken when its encoding is available, else a calibrated estimate."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # offline environments may not have the BPE file cached
        return None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        return len(enc.encode(text, disallowed_special=()))
    return max(1, len(text) // 4)


def truncate_tokens(text: str, max_tokens: int) -> str:
    if count_tokens(text) <= max_tokens:
        return text
    enc = _encoder()
    if enc is not None:
        return enc.decode(enc.encode(text, disallowed_special=())[:max_tokens])
    return text[: max_tokens * 4]
