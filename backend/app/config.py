"""Application settings.

Secrets are never hard-coded here. Real values are read from environment
variables when the app is created: from `backend/.env` during local
development, or from the host's settings in production.
"""

import os

from sqlalchemy.engine import make_url

MIN_SECRET_KEY_LENGTH = 32
TEST_DATABASE_SUFFIX = "_test"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


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


class DevelopmentConfig(BaseConfig):
    LOG_FORMAT = "text"


class ProductionConfig(BaseConfig):
    pass


class TestingConfig(BaseConfig):
    TESTING = True
    # A fixed, clearly fake key used only by the automated tests.
    SECRET_KEY = "testing-only-key-never-use-outside-tests"  # noqa: S105


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


def validate_config(config: dict) -> None:
    """Stop the app from starting with missing or unsafe settings."""
    if config.get("LOG_LEVEL") not in LOG_LEVELS:
        raise RuntimeError(f"LOG_LEVEL must be one of: {', '.join(LOG_LEVELS)}.")

    if config.get("TESTING"):
        _validate_test_databases(config)
        return

    secret_key = config.get("SECRET_KEY")
    if not secret_key or len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            f"SECRET_KEY must be set and at least {MIN_SECRET_KEY_LENGTH} characters long. "
            "See backend/.env.example."
        )

    if not config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL must be set. See backend/.env.example.")


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
