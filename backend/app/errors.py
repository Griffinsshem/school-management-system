"""JSON error responses that never expose stack traces or internal details.

Every error body includes the request ID, so a user can quote it and the
matching server log lines can be found.
"""

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app.observability import get_request_id


def _error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": get_request_id()}}


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        # Start from Werkzeug's response so headers such as `Allow` (on 405) are kept.
        response = error.get_response()
        code = (error.name or "error").lower().replace(" ", "_")
        response.set_data(jsonify(_error_body(code, error.description or "")).get_data())
        response.content_type = "application/json"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error: Exception):
        # Full details go to the server log only, never to the client.
        app.logger.exception("Unhandled exception")
        body = _error_body("internal_server_error", "An unexpected error occurred.")
        return jsonify(body), 500
