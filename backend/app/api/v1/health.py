"""Liveness check: reports only that the API process is running."""

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    # Deliberately minimal: no version, hostnames, database or config details.
    return jsonify({"status": "ok"}), 200
