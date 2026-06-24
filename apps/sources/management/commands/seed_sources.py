from django.core.management.base import BaseCommand

from apps.sources.models import Source, SourceType

SEED_SOURCES = [
    {
        "name": "OpenAI",
        "homepage_url": "https://openai.com/blog",
        "rss_url": "https://openai.com/blog/rss.xml",
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "Google AI",
        "homepage_url": "https://blog.google/technology/ai/",
        "rss_url": "https://blog.google/technology/ai/rss/",
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "Anthropic",
        "homepage_url": "https://www.anthropic.com/news",
        "rss_url": None,
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "Meta AI",
        "homepage_url": "https://ai.meta.com/",
        "rss_url": None,
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "Mistral AI",
        "homepage_url": "https://mistral.ai/news",
        "rss_url": None,
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "xAI",
        "homepage_url": "https://x.ai/",
        "rss_url": None,
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "Microsoft AI Blog",
        "homepage_url": "https://blogs.microsoft.com/ai/",
        "rss_url": None,
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "Hugging Face Blog",
        "homepage_url": "https://huggingface.co/blog",
        "rss_url": "https://huggingface.co/blog/feed.xml",
        "source_type": SourceType.BLOG,
        "badge_label": "Blog",
    },
    {
        "name": "DeepMind",
        "homepage_url": "https://deepmind.google/blog/",
        "rss_url": "https://deepmind.google/blog/rss.xml",
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "NVIDIA AI Blog",
        "homepage_url": "https://blogs.nvidia.com/blog/category/deep-learning/",
        "rss_url": "https://blogs.nvidia.com/feed/",
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "TechCrunch AI",
        "homepage_url": "https://techcrunch.com/category/artificial-intelligence/",
        "rss_url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "source_type": SourceType.MEDIA,
        "badge_label": "Media",
    },
    {
        "name": "VentureBeat AI",
        "homepage_url": "https://venturebeat.com/category/ai/",
        "rss_url": "https://venturebeat.com/category/ai/feed/",
        "source_type": SourceType.MEDIA,
        "badge_label": "Media",
    },
    {
        "name": "The Verge AI",
        "homepage_url": "https://www.theverge.com/ai-artificial-intelligence",
        "rss_url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "source_type": SourceType.MEDIA,
        "badge_label": "Media",
    },
    {
        "name": "Ars Technica",
        "homepage_url": "https://arstechnica.com/ai/",
        "rss_url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "source_type": SourceType.MEDIA,
        "badge_label": "Media",
    },
    {
        "name": "MIT Technology Review",
        "homepage_url": "https://www.technologyreview.com/topic/artificial-intelligence/",
        "rss_url": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
        "source_type": SourceType.RESEARCH,
        "badge_label": "Research",
    },
    {
        "name": "AWS ML Blog",
        "homepage_url": "https://aws.amazon.com/blogs/machine-learning/",
        "rss_url": "https://aws.amazon.com/blogs/machine-learning/feed/",
        "source_type": SourceType.OFFICIAL,
        "badge_label": "Official",
    },
    {
        "name": "Papers With Code",
        "homepage_url": "https://paperswithcode.com/",
        "rss_url": None ,
        "source_type": SourceType.RESEARCH,
        "badge_label": "Research",
    },
    {
        "name": "r/MachineLearning",
        "homepage_url": "https://www.reddit.com/r/MachineLearning/",
        "rss_url": "https://www.reddit.com/r/MachineLearning/.rss",
        "source_type": SourceType.COMMUNITY,
        "badge_label": "Community",
    },
    {
        "name": "IEEE Spectrum AI",
        "homepage_url": "https://spectrum.ieee.org/topic/artificial-intelligence",
        "rss_url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
        "source_type": SourceType.RESEARCH,
        "badge_label": "Research",
    },
]


class Command(BaseCommand):
    help = "Seed the 19 background-fetch news sources."

    def handle(self, *args, **options):
        created_count = 0
        for entry in SEED_SOURCES:
            _, created = Source.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "homepage_url": entry["homepage_url"],
                    "rss_url": entry["rss_url"],
                    "source_type": entry["source_type"],
                    "badge_label": entry["badge_label"],
                    "is_active": True,
                    "fetch_interval_minutes": 240,
                },
            )
            if created:
                created_count += 1

        total = Source.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {created_count} created, {total} total sources."
            )
        )
