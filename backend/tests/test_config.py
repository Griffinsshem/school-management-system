import pytest

from app import create_app

VALID_KEY = "x" * 48
VALID_DB_URL = "postgresql+psycopg://user:pass@localhost:5432/example"


@pytest.fixture
def env(monkeypatch):
    """Start each test with none of the app's variables set."""
    for name in ("SECRET_KEY", "DATABASE_URL", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_production_refuses_to_start_without_secret_key(env):
    env.setenv("DATABASE_URL", VALID_DB_URL)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")


def test_short_secret_key_is_rejected(env):
    env.setenv("SECRET_KEY", "change-me")
    env.setenv("DATABASE_URL", VALID_DB_URL)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("development")


def test_missing_database_url_is_rejected(env):
    env.setenv("SECRET_KEY", VALID_KEY)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app("production")


def test_app_env_defaults_to_production_checks(env):
    # With nothing configured, the strict checks must still apply.
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()


def test_unknown_app_env_is_rejected(env):
    with pytest.raises(RuntimeError, match="Unknown APP_ENV"):
        create_app("staging")


def test_valid_configuration_starts(env):
    env.setenv("SECRET_KEY", VALID_KEY)
    env.setenv("DATABASE_URL", VALID_DB_URL)

    app = create_app("production")

    assert app.config["TESTING"] is False
    assert app.config["SECRET_KEY"] == VALID_KEY
