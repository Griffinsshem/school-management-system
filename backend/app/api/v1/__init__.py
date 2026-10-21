"""Version 1 of the API. Every v1 endpoint is registered under /api/v1."""

from flask import Blueprint

from app.api.v1.auth import auth_bp
from app.api.v1.health import health_bp
from app.api.v1.platform import platform_bp

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")
api_v1.register_blueprint(health_bp)
api_v1.register_blueprint(auth_bp)
api_v1.register_blueprint(platform_bp)
