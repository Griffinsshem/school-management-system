"""Cross-site request forgery (CSRF) protection for cookie-based sessions.

Three layers, as described in OWASP's guidance:
1. The session cookie is SameSite=Lax (see app.auth.sessions).
2. State-changing requests with a body must be JSON. A plain HTML form on
   another site cannot send JSON to this API.
3. If the browser sends an Origin header on a state-changing request, it
   must be our frontend's origin.
"""

from flask import Flask, current_app, request

from app.errors import ApiError

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def register_csrf_protection(app: Flask) -> None:
    @app.before_request
    def check_request_origin_and_type():
        if request.method not in _UNSAFE_METHODS:
            return None

        origin = request.headers.get("Origin")
        if origin is not None and origin != current_app.config["FRONTEND_ORIGIN"]:
            raise ApiError(403, "forbidden_origin", "This request is not allowed from this site.")

        has_body = bool(request.content_length) or "chunked" in request.headers.get(
            "Transfer-Encoding", ""
        )
        if has_body and request.mimetype != "application/json":
            raise ApiError(415, "unsupported_media_type", "Request bodies must be JSON.")
        return None
