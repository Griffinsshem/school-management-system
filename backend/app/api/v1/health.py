"""Health checks.

/health        liveness: the API process is running. Never touches the database.
/health/ready  readiness: the API can also reach the database.

Both are deliberately minimal: no version, hostnames, database or config details.
"""

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@health_bp.get("/health/ready")
def ready():
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Details go to the server log only, never to the client.
        current_app.logger.exception("Readiness check failed: database unreachable")
        db.session.rollback()
        return jsonify({"status": "unavailable"}), 503
    return jsonify({"status": "ok"}), 200
