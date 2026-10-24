"""TEMPORARY (B10 staging check): which addresses reach the API.

Shows the caller the address headers of their own request, so that
TRUSTED_PROXY_COUNT can be chosen from measurements behind Vercel and Render
instead of guesses. It is off unless CLIENT_IP_DIAGNOSTICS=1, answers 404
otherwise, and is removed again before B10 is finished.
"""

from flask import Blueprint, abort, current_app, jsonify, request

from app.auth.rate_limit import _client_ip

diagnostics_bp = Blueprint("diagnostics", __name__)

# Headers that proxies and CDNs commonly use to pass on the visitor's address.
ADDRESS_HEADERS = (
    "X-Forwarded-For",
    "X-Real-IP",
    "X-Vercel-Forwarded-For",
    "X-Vercel-Proxied-For",
    "CF-Connecting-IP",
    "True-Client-IP",
    "Forwarded",
    "X-Forwarded-Proto",
)


@diagnostics_bp.get("/diagnostics/client-ip")
def client_ip():
    if not current_app.config["CLIENT_IP_DIAGNOSTICS"]:
        abort(404)
    # ProxyFix (when TRUSTED_PROXY_COUNT > 0) keeps the untouched values here.
    original = request.environ.get("werkzeug.proxy_fix.orig", {})
    response = jsonify(
        {
            "trusted_proxy_count": current_app.config["TRUSTED_PROXY_COUNT"],
            "rate_limit_ip": _client_ip(),
            "socket_peer": original.get("REMOTE_ADDR") or request.environ.get("REMOTE_ADDR"),
            "headers": {name: request.headers.get(name) for name in ADDRESS_HEADERS},
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response
