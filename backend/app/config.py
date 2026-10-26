"""Application settings.

Secrets are never hard-coded here. Real values are read from environment
variables when the app is created: from `backend/.env` during local
development, or from the host's settings in production.
"""

import os
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

MIN_SECRET_KEY_LENGTH = 32
TEST_DATABASE_SUFFIX = "_test"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
MAX_TRUSTED_PROXY_COUNT = 5
MIN_PROXY_SECRET_LENGTH = 32


class BaseConfig:
    TESTING = False
    SECRET_KEY: str | None = None
    # Runtime connection (sms_app: reads and writes rows only).
    SQLALCHEMY_DATABASE_URI: str | None = None
    # Migration connection (sms_migrator: owns the schema). Used only by `flask db`.
    MIGRATION_DATABASE_URI: str | None = None
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Check a pooled connection is alive before using it.
        "pool_pre_ping": True,
        # Fail fast (seconds) instead of hanging when the database is unreachable.
        "connect_args": {"connect_timeout": 5},
    }
    # Reject request bodies larger than 1 MB (responds with 413).
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024
    LOG_LEVEL = "INFO"
    # "json" (one object per line, for log collectors) or "text" (for people).
    LOG_FORMAT = "json"

    # The only origin allowed to send state-changing requests (CSRF protection).
    FRONTEND_ORIGIN: str | None = None
    # Number of reverse proxies in front of the API whose X-Forwarded-For header
    # is trusted. 0 means the header is ignored, so clients cannot fake their IP.
    TRUSTED_PROXY_COUNT = 0
    # TEMPORARY (B10): /api/v1/diagnostics/client-ip, for measuring which
    # addresses reach the API on staging. Off unless CLIENT_IP_DIAGNOSTICS=1.
    CLIENT_IP_DIAGNOSTICS = False
    # Shared by the frontend's host and the API's host: API requests without
    # it are refused (see app.frontend_proxy). Required in production.
    PROXY_SHARED_SECRET: str | None = None
    REQUIRE_PROXY_SHARED_SECRET = False

    # Login session cookie. Secure cookies are named with the __Host- prefix,
    # which makes browsers enforce Secure, Path=/ and no Domain.
    AUTH_COOKIE_SECURE = True
    SESSION_IDLE_TIMEOUT = timedelta(minutes=30)
    SESSION_ABSOLUTE_TIMEOUT = timedelta(hours=8)
    # Activity extends the idle timer, written to the database at most this often.
    SESSION_TOUCH_INTERVAL = timedelta(minutes=1)

    # Failed-login limits within a sliding window.
    LOGIN_WINDOW = timedelta(minutes=15)
    LOGIN_MAX_FAILURES_PER_ACCOUNT = 10
    LOGIN_MAX_FAILURES_PER_IP = 50

    # How long an invitation link stays usable.
    INVITATION_LIFETIME = timedelta(days=7)


class DevelopmentConfig(BaseConfig):
    LOG_FORMAT = "text"
    # Local development runs on plain http, where Secure cookies are not sent.
    AUTH_COOKIE_SECURE = False
    FRONTEND_ORIGIN = "http://127.0.0.1:3000"


class ProductionConfig(BaseConfig):
    REQUIRE_PROXY_SHARED_SECRET = True


class TestingConfig(BaseConfig):
    TESTING = True
    # A fixed, clearly fake key used only by the automated tests.
    SECRET_KEY = "testing-only-key-never-use-outside-tests"  # noqa: S105
    AUTH_COOKIE_SECURE = False
    FRONTEND_ORIGIN = "http://localhost:3000"


CONFIGS: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str) -> type[BaseConfig]:
    try:
        return CONFIGS[name]
    except KeyError:
        valid = ", ".join(sorted(CONFIGS))
        raise RuntimeError(f"Unknown APP_ENV '{name}'. Use one of: {valid}.") from None


def load_from_environment(config: dict) -> None:
    """Read secrets and connection strings from environment variables."""
    if config.get("TESTING"):
        config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("TEST_DATABASE_URL")
        config["MIGRATION_DATABASE_URI"] = os.environ.get("TEST_MIGRATION_DATABASE_URL")
        return
    config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
    config["MIGRATION_DATABASE_URI"] = os.environ.get("MIGRATION_DATABASE_URL")
    config["LOG_LEVEL"] = os.environ.get("LOG_LEVEL", config["LOG_LEVEL"]).upper()
    config["FRONTEND_ORIGIN"] = os.environ.get("FRONTEND_ORIGIN", config["FRONTEND_ORIGIN"])
    config["CLIENT_IP_DIAGNOSTICS"] = os.environ.get("CLIENT_IP_DIAGNOSTICS") == "1"
    config["PROXY_SHARED_SECRET"] = os.environ.get("PROXY_SHARED_SECRET") or None
    proxy_count = os.environ.get("TRUSTED_PROXY_COUNT")
    if proxy_count is not None:
        try:
            config["TRUSTED_PROXY_COUNT"] = int(proxy_count)
        except ValueError:
            raise RuntimeError("TRUSTED_PROXY_COUNT must be a whole number.") from None


def validate_config(config: dict) -> None:
    """Stop the app from starting with missing or unsafe settings."""
    if config.get("LOG_LEVEL") not in LOG_LEVELS:
        raise RuntimeError(f"LOG_LEVEL must be one of: {', '.join(LOG_LEVELS)}.")

    if config.get("TESTING"):
        _validate_test_databases(config)
    else:
        secret_key = config.get("SECRET_KEY")
        if not secret_key or len(secret_key) < MIN_SECRET_KEY_LENGTH:
            raise RuntimeError(
                f"SECRET_KEY must be set and at least {MIN_SECRET_KEY_LENGTH} characters long. "
                "See backend/.env.example."
            )
        if not config.get("SQLALCHEMY_DATABASE_URI"):
            raise RuntimeError("DATABASE_URL must be set. See backend/.env.example.")

    proxy_count = config.get("TRUSTED_PROXY_COUNT")
    if not isinstance(proxy_count, int) or not 0 <= proxy_count <= MAX_TRUSTED_PROXY_COUNT:
        raise RuntimeError(f"TRUSTED_PROXY_COUNT must be between 0 and {MAX_TRUSTED_PROXY_COUNT}.")

    _validate_frontend_origin(config)
    _validate_proxy_secret(config)


def _validate_proxy_secret(config: dict) -> None:
    secret = config.get("PROXY_SHARED_SECRET")
    if secret is None:
        if config.get("REQUIRE_PROXY_SHARED_SECRET"):
            raise RuntimeError(
                "PROXY_SHARED_SECRET must be set in production (the same value as the "
                "frontend's). See docs/deployment.md."
            )
        return
    if len(secret) < MIN_PROXY_SECRET_LENGTH:
        raise RuntimeError(
            f"PROXY_SHARED_SECRET must be at least {MIN_PROXY_SECRET_LENGTH} characters long."
        )


def _validate_test_databases(config: dict) -> None:
    """Tests may only ever touch a database whose name ends in `_test`."""
    if not config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("TEST_DATABASE_URL must be set to run tests. See backend/.env.example.")

    for setting in ("SQLALCHEMY_DATABASE_URI", "MIGRATION_DATABASE_URI"):
        url = config.get(setting)
        if url and not (make_url(url).database or "").endswith(TEST_DATABASE_SUFFIX):
            raise RuntimeError(
                f"Refusing to run tests: the database for {setting} must have a name "
                f"ending in '{TEST_DATABASE_SUFFIX}'."
            )


def _validate_frontend_origin(config: dict) -> None:
    """FRONTEND_ORIGIN must be a bare origin such as https://app.example.com."""
    origin = config.get("FRONTEND_ORIGIN")
    if not origin:
        raise RuntimeError("FRONTEND_ORIGIN must be set. See backend/.env.example.")

    parts = urlsplit(origin)
    is_bare_origin = (
        parts.scheme in ("http", "https")
        and parts.netloc
        and not parts.path
        and not parts.query
        and not parts.fragment
    )
    if not is_bare_origin:
        raise RuntimeError(
            "FRONTEND_ORIGIN must look like https://app.example.com (no path or trailing slash)."
        )
    if config.get("AUTH_COOKIE_SECURE") and parts.scheme != "https":
        raise RuntimeError("FRONTEND_ORIGIN must use https when secure cookies are enabled.")
