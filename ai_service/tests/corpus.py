"""A small, realistic news corpus used by integration tests and offline evals."""

from __future__ import annotations

from datetime import datetime, timedelta

SOURCES = [
    (1, "TechCrunch", "media"),
    (2, "The Verge", "media"),
    (3, "OpenAI Blog", "official"),
    (4, "Hacker News", "community"),
]


def articles(now: datetime) -> list[dict]:
    """(source_id, days_ago, title, body, tags). Dates are relative to ``now``."""
    d = lambda n: now - timedelta(days=n, hours=1)  # noqa: E731
    return [
        dict(id=1, source=3, at=d(1), title="OpenAI releases GPT-5 with a 1 million token context window",
             tags=["OpenAI", "LLM"],
             body="OpenAI announced GPT-5 on Tuesday, its latest flagship language model. The model supports a "
                  "1 million token context window and costs $5 per million input tokens. OpenAI CEO Sam Altman said "
                  "the model is 40% better at coding benchmarks than GPT-4o. GPT-5 is available to ChatGPT Plus "
                  "subscribers starting today, and the API opens next week."),
        dict(id=2, source=1, at=d(1), title="GPT-5 launches: what OpenAI's new model can do",
             tags=["OpenAI", "LLM"],
             body="OpenAI unveiled GPT-5 this week, a new flagship model with a 1 million token context window. "
                  "According to OpenAI, input tokens are priced at $5 per million. TechCrunch reports that the model "
                  "improves coding performance by 40% on internal benchmarks. The rollout starts with ChatGPT Plus."),
        dict(id=3, source=2, at=d(2), title="Anthropic raises $4 billion from Amazon to expand Claude",
             tags=["Anthropic", "Funding"],
             body="Anthropic has raised $4 billion in new funding from Amazon, the company said on Monday. The money "
                  "will be used to train larger Claude models and expand compute capacity on AWS. Anthropic CEO Dario "
                  "Amodei said the partnership deepens the companies' existing relationship. Anthropic is now valued "
                  "at roughly $60 billion."),
        dict(id=4, source=1, at=d(3), title="Nvidia unveils Blackwell Ultra chips for AI data centers",
             tags=["Nvidia", "Hardware"],
             body="Nvidia introduced the Blackwell Ultra GPU at its annual conference. The chip delivers 1.5x the AI "
                  "inference performance of the original Blackwell and ships in the second half of the year. Nvidia "
                  "CEO Jensen Huang said demand from cloud providers remains far above supply. Prices were not disclosed."),
        dict(id=5, source=2, at=d(5), title="Google DeepMind's Gemini 2.5 tops reasoning leaderboards",
             tags=["Google", "LLM"],
             body="Google DeepMind released Gemini 2.5, which now ranks first on several public reasoning "
                  "leaderboards. The model scores 86% on the GPQA benchmark. Google said Gemini 2.5 will roll out to "
                  "developers through Vertex AI over the coming weeks."),
        dict(id=6, source=4, at=d(9), title="Meta open-sources Llama 4 with mixture-of-experts design",
             tags=["Meta", "Open Source"],
             body="Meta released Llama 4 as open weights on Saturday. The family uses a mixture-of-experts "
                  "architecture and comes in three sizes. Meta says the largest model has 400 billion total "
                  "parameters. The license permits commercial use for companies under 700 million monthly users."),
        dict(id=7, source=1, at=d(20), title="EU AI Act enforcement begins for general-purpose models",
             tags=["Regulation", "EU"],
             body="The European Union began enforcing the AI Act's rules for general-purpose AI models this month. "
                  "Providers must publish training data summaries and document copyright compliance. Fines can reach "
                  "7% of global annual revenue for the most serious violations."),
        dict(id=8, source=2, at=d(40), title="Apple announces on-device AI features for iPhone",
             tags=["Apple", "Mobile"],
             body="Apple announced a suite of on-device AI features for the iPhone, including writing tools and "
                  "improved Siri. The features run on the A18 chip and require iOS 19. Apple said the company will "
                  "not use private user data to train its models."),
    ]
