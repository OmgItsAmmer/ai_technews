import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")

DEBUG = False

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_jinja",
    "apps.sources",
    "apps.posts",
    "apps.fetcher",
    "apps.extractor",
    "apps.extraction",
    "apps.frontend",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django_jinja.backend.Jinja2",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "match_extension": ".jinja",
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
            "filters": {
                "join_tags": "apps.frontend.templatetags.jinja_filters.join_tags",
            },
        },
    },
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required (Neon PostgreSQL connection string).")

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/admin/"
LOGOUT_REDIRECT_URL = "/admin/login/"

AUTHENTICATION_BACKENDS = [
    "config.backends.EmailBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Session Settings (60 minutes timeout)
SESSION_COOKIE_AGE = 3600  # 60 minutes in seconds
SESSION_SAVE_EVERY_REQUEST = True  # session expires 60 minutes after the last active request


LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

CRON_SECRET = os.environ.get("CRON_SECRET", "")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", None)
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "Qwen/Qwen3.5-4B")
OPENAI_FALLBACK_MODEL = os.environ.get("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")

FETCHER_DEDUP_REDIS_KEY = "fetcher:seen_urls"
FETCHER_DEDUP_TTL_SECONDS = 30 * 24 * 60 * 60
FETCHER_MAX_HOMEPAGE_LINKS = 30
FETCHER_MAX_ARTICLE_TEXT_CHARS = 3000

# Scrutinize API Config
SCRUTINIZE_API_BASE_URL = os.environ.get("SCRUTINIZE_API_BASE_URL", "http://localhost:8000")
SCRUTINIZE_ADMIN_API_KEY = os.environ.get("SCRUTINIZE_ADMIN_API_KEY", "scrutinize_sk_d5e6feae8ca4ff07557f29e8536f20f89b60f73f40270b9e")
SCRUTINIZE_PUBLIC_CLIENT_KEY = os.environ.get("SCRUTINIZE_PUBLIC_CLIENT_KEY", "scrutinize_pk_bad456b4ad1c215b093a78e12e33629074ee10f95e7e291b")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "apps.fetcher": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
