from .base import *  # noqa: F403

if SECRET_KEY == "unsafe-development-secret-key":  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be set to a secure value in production.")

DEBUG = False
ALLOWED_HOSTS = [host for host in env("DJANGO_ALLOWED_HOSTS").split(",") if host]  # noqa: F405
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
