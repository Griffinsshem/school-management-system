"""Version 1 of the API. Every v1 endpoint is registered under /api/v1."""

from flask import Blueprint

from app.api.v1.auth import auth_bp
from app.api.v1.health import health_bp
from app.api.v1.invitations import invitations_bp, school_invitations_bp
from app.api.v1.platform import platform_bp
from app.api.v1.school import school_bp
from app.api.v1.students import students_bp

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")
api_v1.register_blueprint(health_bp)
api_v1.register_blueprint(auth_bp)
api_v1.register_blueprint(platform_bp)
api_v1.register_blueprint(school_bp)
api_v1.register_blueprint(students_bp)
api_v1.register_blueprint(school_invitations_bp)
api_v1.register_blueprint(invitations_bp)
