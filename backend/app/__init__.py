"""Application factory."""

import os
from pathlib import Path

from flask import Flask

from app.config import get_config, load_from_environment, validate_config
from app.errors import register_error_handlers
from app.extensions import db, migrate
from app.observability import configure_logging, register_request_hooks

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def create_app(config_name: str | None = None, overrides: dict | None = None) -> Flask:
    """Build and configure a new Flask app.

    The environment is chosen by the `config_name` argument or the APP_ENV
    variable. If neither is set it defaults to "production", the strictest
    settings, so a misconfigured server fails safely instead of running loosely.

    `overrides` replaces individual settings after they are loaded. Tests use
    it; overridden values still pass through validation.
    """
    app = Flask(__name__)

    name = config_name or os.environ.get("APP_ENV", "production")
    app.config.from_object(get_config(name))
    load_from_environment(app.config)
    if overrides:
        app.config.update(overrides)
    validate_config(app.config)

    configure_logging(app)
    register_request_hooks(app)

    db.init_app(app)
    migrate.init_app(app, db, directory=str(MIGRATIONS_DIR))

    from app.api.v1 import api_v1

    app.register_blueprint(api_v1)
    register_error_handlers(app)

    return app
