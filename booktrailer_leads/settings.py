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
    "rest_framework_simplejwt.token_blacklist",
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
        # 30s busy timeout so background pipeline threads and web requests
        # wait for each other's writes instead of failing with "database is locked".
        # BEGIN IMMEDIATE makes atomic() blocks take the write lock up front;
        # deferred transactions would otherwise fail instantly on WAL snapshot
        # conflicts (SQLITE_BUSY_SNAPSHOT), which busy_timeout cannot wait out.
        "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},
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
APP_MAX_AUTHOR_DISCOVERY_QUERIES = int(os.getenv("APP_MAX_AUTHOR_DISCOVERY_QUERIES", "9"))
APP_MAX_DEEP_CONTACT_QUERIES = int(os.getenv("APP_MAX_DEEP_CONTACT_QUERIES", "9"))
APP_MAX_AUTHOR_PAGES_TO_CRAWL = int(os.getenv("APP_MAX_AUTHOR_PAGES_TO_CRAWL", "6"))
# Second crawl hop: contact-intent links discovered on the author's own pages
# (custom slugs like /visit-me) are followed this many pages deep per site.
APP_MAX_SECOND_HOP_PAGES = int(os.getenv("APP_MAX_SECOND_HOP_PAGES", "4"))
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
APP_GROQ_CACHE_SECONDS = int(os.getenv("APP_GROQ_CACHE_SECONDS", str(24 * 60 * 60)))
APP_PIPELINE_WORKERS = min(max(int(os.getenv("APP_PIPELINE_WORKERS", "3")), 1), 8)
APP_STAGE_WORKERS = min(max(int(os.getenv("APP_STAGE_WORKERS", "4")), 1), 8)
# Concurrent network workers for the instant ISBN keyword lookup stream.
APP_ISBN_LOOKUP_WORKERS = min(max(int(os.getenv("APP_ISBN_LOOKUP_WORKERS", "8")), 1), 16)
# Extra free, no-key harvest layers (Crossref + Internet Archive keyword search).
APP_ISBN_LOOKUP_EXTRA_CATALOGS = env_bool("APP_ISBN_LOOKUP_EXTRA_CATALOGS", True)
APP_WIKIDATA_AUTHOR_LOOKUP = env_bool("APP_WIKIDATA_AUTHOR_LOOKUP", True)
DDGS_VERIFY_SSL = env_bool("DDGS_VERIFY_SSL", True)
DDGS_BACKEND = os.getenv("DDGS_BACKEND", "yahoo,startpage,mojeek,yandex")
# Ordered free search layers used when SEARCH_PROVIDER=enrichment provider is "fallback"
SEARCH_FALLBACK_PROVIDERS = os.getenv("SEARCH_FALLBACK_PROVIDERS", "ddgs,ddgs_html,bing_html")

# --- Lead-scraping feature toggles (all default to safe/off) ---
# Headless JS rendering fallback for thin pages (requires playwright + chromium).
APP_JS_RENDER_ENABLED = env_bool("APP_JS_RENDER_ENABLED", False)
APP_JS_RENDER_MIN_TEXT_CHARS = int(os.getenv("APP_JS_RENDER_MIN_TEXT_CHARS", "200"))
# Direct Amazon scraping toggle (default off for offline/tests, enable in env)
AMAZON_DIRECT_SCRAPE_ENABLED = env_bool("AMAZON_DIRECT_SCRAPE_ENABLED", False)

# Comma-separated egress proxies for crawl traffic ("" = direct connections).
APP_PROXY_LIST = os.getenv("APP_PROXY_LIST", "")
# Hosted email verification: "hunter" | "zerobounce" | "neverbounce" | "" (off).
APP_EMAIL_VERIFY_PROVIDER = os.getenv("APP_EMAIL_VERIFY_PROVIDER", "")
# Contacts older than this many days are flagged stale and re-verified.
APP_CONTACT_STALE_DAYS = int(os.getenv("APP_CONTACT_STALE_DAYS", "90"))
# Same contact value on this many leads = shared agency/publicist channel.
APP_SHARED_CONTACT_THRESHOLD = int(os.getenv("APP_SHARED_CONTACT_THRESHOLD", "3"))
# Slack/Discord/generic webhook for run-completion and hot-lead notifications.
APP_WEBHOOK_URL = os.getenv("APP_WEBHOOK_URL", "")
APP_HOT_LEAD_NOTIFY_SCORE = int(os.getenv("APP_HOT_LEAD_NOTIFY_SCORE", "90"))

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
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "SIGNING_KEY": hashlib.sha256(SECRET_KEY.encode("utf-8")).hexdigest(),
}
