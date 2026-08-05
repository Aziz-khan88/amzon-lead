from __future__ import annotations

import os
import hashlib
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
if not DEBUG and (SECRET_KEY == "change-me" or len(SECRET_KEY) < 32):
    raise RuntimeError("Production requires a random SECRET_KEY with at least 32 characters.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "leadfinder",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "leadfinder.middleware.LoginAndRoleRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "booktrailer_leads.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "leadfinder" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "leadfinder.context_processors.role_context",
            ],
        },
    }
]

WSGI_APPLICATION = "booktrailer_leads.wsgi.application"


def database_config() -> dict:
    url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
        }
    path = parsed.path
    if path == "/db.sqlite3" or path == "db.sqlite3":
        path = BASE_DIR / "db.sqlite3"
    elif os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]

    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": path if parsed.scheme == "sqlite" else BASE_DIR / "db.sqlite3",
    }


DATABASES = {"default": database_config()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "leadfinder" / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "leadfinder:login"
LOGIN_REDIRECT_URL = "leadfinder:dashboard"
LOGOUT_REDIRECT_URL = "leadfinder:login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "ddgs")
APP_MAX_BOOKS_PER_RUN = int(os.getenv("APP_MAX_BOOKS_PER_RUN", "10"))
APP_MAX_SEARCH_RESULTS_PER_QUERY = int(os.getenv("APP_MAX_SEARCH_RESULTS_PER_QUERY", "8"))
APP_MAX_DISCOVERY_QUERIES = int(os.getenv("APP_MAX_DISCOVERY_QUERIES", "12"))
APP_MAX_AUTHOR_DISCOVERY_QUERIES = int(os.getenv("APP_MAX_AUTHOR_DISCOVERY_QUERIES", "8"))
APP_MAX_DEEP_CONTACT_QUERIES = int(os.getenv("APP_MAX_DEEP_CONTACT_QUERIES", "5"))
APP_MAX_AUTHOR_PAGES_TO_CRAWL = int(os.getenv("APP_MAX_AUTHOR_PAGES_TO_CRAWL", "4"))
APP_REQUEST_TIMEOUT_SECONDS = int(os.getenv("APP_REQUEST_TIMEOUT_SECONDS", "15"))
APP_REQUEST_DELAY_SECONDS = float(os.getenv("APP_REQUEST_DELAY_SECONDS", "0.4"))
APP_SEARCH_DELAY_SECONDS = float(os.getenv("APP_SEARCH_DELAY_SECONDS", str(APP_REQUEST_DELAY_SECONDS)))
APP_CRAWL_DELAY_SECONDS = float(os.getenv("APP_CRAWL_DELAY_SECONDS", str(APP_REQUEST_DELAY_SECONDS)))
APP_SOCIAL_CRAWL_DELAY_SECONDS = float(os.getenv("APP_SOCIAL_CRAWL_DELAY_SECONDS", "0.5"))
APP_MAX_SOCIAL_CONTACT_PAGES = int(os.getenv("APP_MAX_SOCIAL_CONTACT_PAGES", "5"))
APP_DNS_TIMEOUT_SECONDS = float(os.getenv("APP_DNS_TIMEOUT_SECONDS", "1.0"))
APP_SCHEDULED_TASK_LEASE_SECONDS = int(os.getenv("APP_SCHEDULED_TASK_LEASE_SECONDS", str(6 * 60 * 60)))
APP_SEARCH_CACHE_SECONDS = int(os.getenv("APP_SEARCH_CACHE_SECONDS", str(6 * 60 * 60)))
APP_MAX_GROQ_INPUT_CHARS = int(os.getenv("APP_MAX_GROQ_INPUT_CHARS", "12000"))
DDGS_VERIFY_SSL = env_bool("DDGS_VERIFY_SSL", True)
DDGS_BACKEND = os.getenv("DDGS_BACKEND", "yahoo,startpage,mojeek,yandex")

DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {"anon": "10/min", "user": "120/min"},
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
    "SIGNING_KEY": hashlib.sha256(SECRET_KEY.encode("utf-8")).hexdigest(),
}
