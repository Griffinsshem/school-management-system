import pytest

from app import create_app

VALID_KEY = "x" * 48
VALID_DB_URL = "postgresql+psycopg://user:pass@localhost:5432/example"
NON_TEST_DB_URL = "postgresql+psycopg://user:pass@localhost:5432/sms_dev"
VALID_ORIGIN = "https://app.example.com"
VALID_PROXY_SECRET = "p" * 40
APP_VARIABLES = (
    "SECRET_KEY",
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "APP_ENV",
    "FRONTEND_ORIGIN",
    "TRUSTED_PROXY_COUNT",
    "PROXY_SHARED_SECRET",
)


@pytest.fixture
def env(monkeypatch):
    """Start each test with none of the app's variables set."""
    for name in APP_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def production_env(env):
    """A complete, valid production environment."""
    env.setenv("SECRET_KEY", VALID_KEY)
    env.setenv("DATABASE_URL", VALID_DB_URL)
    env.setenv("FRONTEND_ORIGIN", VALID_ORIGIN)
    env.setenv("PROXY_SHARED_SECRET", VALID_PROXY_SECRET)
    return env


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


def test_valid_configuration_starts(production_env):
    app = create_app("production")

    assert app.config["TESTING"] is False
    assert app.config["SECRET_KEY"] == VALID_KEY
    assert app.config["FRONTEND_ORIGIN"] == VALID_ORIGIN
    assert app.config["AUTH_COOKIE_SECURE"] is True


def test_production_requires_a_frontend_origin(production_env):
    production_env.delenv("FRONTEND_ORIGIN")

    with pytest.raises(RuntimeError, match="FRONTEND_ORIGIN must be set"):
        create_app("production")


@pytest.mark.parametrize(
    "origin",
    ["http://app.example.com", "https://app.example.com/", "https://app.example.com/login", "app"],
)
def test_production_rejects_an_unsafe_or_malformed_origin(production_env, origin):
    production_env.setenv("FRONTEND_ORIGIN", origin)

    with pytest.raises(RuntimeError, match="FRONTEND_ORIGIN"):
        create_app("production")


@pytest.mark.parametrize("count", ["-1", "6", "two"])
def test_invalid_trusted_proxy_count_is_rejected(production_env, count):
    production_env.setenv("TRUSTED_PROXY_COUNT", count)

    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_COUNT"):
        create_app("production")


def test_tests_require_a_test_database_url(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        create_app("testing")


@pytest.mark.parametrize("setting", ["SQLALCHEMY_DATABASE_URI", "MIGRATION_DATABASE_URI"])
def test_tests_refuse_a_database_not_named_test(setting):
    with pytest.raises(RuntimeError, match="Refusing to run tests"):
        create_app("testing", overrides={setting: NON_TEST_DB_URL})


def test_production_requires_the_proxy_secret(production_env):
    production_env.delenv("PROXY_SHARED_SECRET")

    with pytest.raises(RuntimeError, match="PROXY_SHARED_SECRET must be set"):
        create_app("production")


def test_short_proxy_secret_is_rejected(production_env):
    production_env.setenv("PROXY_SHARED_SECRET", "too-short")

    with pytest.raises(RuntimeError, match="at least 32 characters"):
        create_app("production")


def test_development_runs_without_the_proxy_secret(env):
    env.setenv("SECRET_KEY", VALID_KEY)
    env.setenv("DATABASE_URL", VALID_DB_URL)

    app = create_app("development")

    assert app.config["PROXY_SHARED_SECRET"] is None
