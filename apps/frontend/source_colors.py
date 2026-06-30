"""Deterministic per-source accent colors for the feed UI."""

SOURCE_PALETTE = (
    "#E50914",  # red
    "#3B82F6",  # blue
    "#10B981",  # emerald
    "#F59E0B",  # amber
    "#8B5CF6",  # violet
    "#EC4899",  # pink
    "#06B6D4",  # cyan
    "#84CC16",  # lime
    "#F97316",  # orange
    "#6366F1",  # indigo
    "#14B8A6",  # teal
    "#A855F7",  # purple
    "#22D3EE",  # sky
    "#F43F5E",  # rose
    "#EAB308",  # yellow
    "#2DD4BF",  # mint
)


def source_color(source):
    """Return a stable hex color for a Source instance, id, or name string."""
    if source is None:
        return None

    if hasattr(source, "id"):
        key = source.id
    elif isinstance(source, int):
        key = source
    else:
        key = sum(ord(c) for c in str(source))

    return SOURCE_PALETTE[key % len(SOURCE_PALETTE)]
