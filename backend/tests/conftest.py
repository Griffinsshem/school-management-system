import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app import create_app
from app.extensions import db

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
TEST_ENV_KEYS = ("TEST_DATABASE_URL", "TEST_MIGRATION_DATABASE_URL")


def pytest_configure(config):
    """Use test connection strings from the environment, or else from backend/.env.

    Only the TEST_* keys are read from .env. Development secrets and the
    development database URL are never loaded into the test process.
    """
    if not ENV_FILE.exists():
        return
    values = dotenv_values(ENV_FILE)
    for key in TEST_ENV_KEYS:
        if key not in os.environ and values.get(key):
            os.environ[key] = values[key]


@pytest.fixture
def app():
    app = create_app("testing")
    yield app
    # Close this app's pooled database connections.
    with app.app_context():
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()
