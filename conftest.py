import os

import django
from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://user:pass@localhost:5432/ainews_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CRON_SECRET", "test-cron-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

django.setup()
