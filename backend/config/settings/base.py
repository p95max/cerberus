from __future__ import annotations

import os
from pathlib import Path

import dj_database_url

from config.logging import JsonFormatter

BASE_DIR = Path(__file__).resolve().parents[2]


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        raise RuntimeError(f"Required environment variable {name} is not configured.")
    return value


def env_bool(name: str, default: str) -> bool:
    value = env(name, default).lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Environment variable {name} must be a boolean.")


CERBERUS_ENV = env("CERBERUS_ENV", "development")
CERBERUS_VERSION = env("CERBERUS_VERSION", "0.1.0")
SECRET_KEY = env("DJANGO_SECRET_KEY", "unsafe-development-secret-key")
DJANGO_ADMIN_URL = env("DJANGO_ADMIN_URL", "admin").strip("/")
if not DJANGO_ADMIN_URL:
    raise RuntimeError("DJANGO_ADMIN_URL must contain a non-root path.")
DJANGO_ADMIN_URL = f"{DJANGO_ADMIN_URL}/"
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "accounts",
    "domain",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "domain.context_processors.operator_permissions",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", "postgresql://cerberus:cerberus@localhost:5432/cerberus"),
        conn_max_age=60,
        conn_health_checks=True,
    )
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", "redis://localhost:6379/0"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/operator/login/"
LOGIN_REDIRECT_URL = "/operator/"

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_TIME_LIMIT = 30
CELERY_TASK_SOFT_TIME_LIMIT = 25
RECOGNITION_IMAGE_METADATA_RETENTION_DAYS = int(
    env("RECOGNITION_IMAGE_METADATA_RETENTION_DAYS", "30")
)
RECOGNITION_EVENT_RETENTION_DAYS = int(env("RECOGNITION_EVENT_RETENTION_DAYS", "180"))
RECOGNITION_AGGREGATE_AUDIT_RETENTION_DAYS = int(
    env("RECOGNITION_AGGREGATE_AUDIT_RETENTION_DAYS", "730")
)
RECOGNITION_PURGE_BATCH_SIZE = int(env("RECOGNITION_PURGE_BATCH_SIZE", "500"))
RECOGNITION_PURGE_INTERVAL_SECONDS = int(env("RECOGNITION_PURGE_INTERVAL_SECONDS", "3600"))
BARRIER_AUTO_CLOSE_SECONDS = int(env("BARRIER_AUTO_CLOSE_SECONDS", "10"))
BARRIER_CLOSE_RECONCILIATION_SECONDS = int(env("BARRIER_CLOSE_RECONCILIATION_SECONDS", "5"))
BARRIER_CONTROLLER_TIMEOUT_SECONDS = int(env("BARRIER_CONTROLLER_TIMEOUT_SECONDS", "3"))
BARRIER_COMMAND_MAX_RETRIES = int(env("BARRIER_COMMAND_MAX_RETRIES", "3"))
BARRIER_COMMAND_RETRY_DELAY_SECONDS = int(env("BARRIER_COMMAND_RETRY_DELAY_SECONDS", "5"))
MOCK_BARRIER_AVAILABLE = env_bool("MOCK_BARRIER_AVAILABLE", "true")
MOCK_BARRIER_DELAY_SECONDS = int(env("MOCK_BARRIER_DELAY_SECONDS", "0"))
RECOGNITION_RETENTION_ENABLED = env_bool("RECOGNITION_RETENTION_ENABLED", "true")
RECOGNITION_IMAGE_METADATA_RETENTION_ENABLED = env_bool(
    "RECOGNITION_IMAGE_METADATA_RETENTION_ENABLED", "true"
)
RECOGNITION_EVENT_RETENTION_ENABLED = env_bool("RECOGNITION_EVENT_RETENTION_ENABLED", "true")
RECOGNITION_AGGREGATE_AUDIT_RETENTION_ENABLED = env_bool(
    "RECOGNITION_AGGREGATE_AUDIT_RETENTION_ENABLED", "true"
)
CELERY_BEAT_SCHEDULE = {
    "purge-expired-recognition-events": {
        "task": "domain.tasks.purge_expired_recognition_events",
        "schedule": RECOGNITION_PURGE_INTERVAL_SECONDS,
    },
    "close-due-barrier-commands": {
        "task": "domain.tasks.close_due_barrier_commands",
        "schedule": BARRIER_CLOSE_RECONCILIATION_SECONDS,
    },
}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "accounts.authentication.ServiceKeyAuthentication",
    ],
    "DEFAULT_THROTTLE_RATES": {"login": "5/min", "service": "60/min"},
}

LOGIN_MAX_FAILURES = int(env("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_SECONDS = int(env("LOGIN_LOCKOUT_SECONDS", "900"))
RECOGNITION_EVENT_MAX_BYTES = int(env("RECOGNITION_EVENT_MAX_BYTES", "16384"))

SPECTACULAR_SETTINGS = {
    "TITLE": "Cerberus Core API",
    "DESCRIPTION": "Deterministic parking and vehicle access-control API.",
    "VERSION": CERBERUS_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": JsonFormatter}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
