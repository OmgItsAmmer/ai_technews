from .development import *  # noqa: F403

# Tests use the same Neon database from DATABASE_URL when integration DB tests run.
# Unit tests for dedup/rss/scraper do not require database tables.
