"""Application factory."""

import os

from flask import Flask

from app.config import get_config, load_from_environment, validate_config
from app.errors import register_error_handlers
from app.extensions import db, migrate


def create_app(config_name: str | None = None) -> Flask:
    """Build and configure a new Flask app.

    The environment is chosen by the `config_name` argument or the APP_ENV
    variable. If neither is set it defaults to "production", the strictest
    settings, so a misconfigured server fails safely instead of running loosely.
    """
    app = Flask(__name__)

    name = config_name or os.environ.get("APP_ENV", "production")
    app.config.from_object(get_config(name))
    load_from_environment(app.config)
    validate_config(app.config)

    db.init_app(app)
    migrate.init_app(app, db)

    from app.api.v1 import api_v1

    app.register_blueprint(api_v1)
    register_error_handlers(app)

    return app
