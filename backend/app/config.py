"""Application settings.

Secrets are never hard-coded here. Real values are read from environment
variables when the app is created: from `backend/.env` during local
development, or from the host's settings in production.
"""

import os

MIN_SECRET_KEY_LENGTH = 32


class BaseConfig:
    TESTING = False
    SECRET_KEY: str | None = None
    SQLALCHEMY_DATABASE_URI: str | None = None
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Reject request bodies larger than 1 MB (responds with 413).
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024


class DevelopmentConfig(BaseConfig):
    pass


class ProductionConfig(BaseConfig):
    pass


class TestingConfig(BaseConfig):
    TESTING = True
    # A fixed, clearly fake key used only by the automated tests.
    SECRET_KEY = "testing-only-key-never-use-outside-tests"  # noqa: S105
    # Placeholder: no current test opens a database connection. Database-backed
    # tests will use an isolated PostgreSQL test database in a later feature.
    SQLALCHEMY_DATABASE_URI = "sqlite://"


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
    """Read secrets from environment variables (skipped for tests)."""
    if config.get("TESTING"):
        return
    config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")


def validate_config(config: dict) -> None:
    """Stop the app from starting with missing or unsafe settings."""
    if config.get("TESTING"):
        return

    secret_key = config.get("SECRET_KEY")
    if not secret_key or len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            f"SECRET_KEY must be set and at least {MIN_SECRET_KEY_LENGTH} characters long. "
            "See backend/.env.example."
        )

    if not config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL must be set. See backend/.env.example.")
