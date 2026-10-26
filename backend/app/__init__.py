"""Application factory."""

import os
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.auth.csrf import register_csrf_protection
from app.config import get_config, load_from_environment, validate_config
from app.errors import register_error_handlers
from app.extensions import db, migrate
from app.frontend_proxy import register_frontend_proxy_check
from app.observability import configure_logging, register_request_hooks
from app.school_context import register_school_context

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
    register_frontend_proxy_check(app)
    register_csrf_protection(app)

    proxy_count = app.config["TRUSTED_PROXY_COUNT"]
    if proxy_count:
        # Trust X-Forwarded-For from exactly this many proxies (for example Render's).
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count, x_proto=proxy_count)

    db.init_app(app)
    # Row-Level Security: every transaction is told its school (or none).
    register_school_context()
    migrate.init_app(app, db, directory=str(MIGRATIONS_DIR))

    # Importing the models registers their tables with SQLAlchemy and migrations.
    from app import models  # noqa: F401
    from app.api.v1 import api_v1
    from app.cli import register_cli

    app.register_blueprint(api_v1)
    register_error_handlers(app)
    register_cli(app)

    return app
