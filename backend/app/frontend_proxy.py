"""Only our own frontend may call the API (staging and production).

The frontend (Next.js `src/proxy.ts`) forwards every /api request with two
headers: a secret shared only by the frontend's host and the API's host, and
the visitor's IP address as the frontend's host reports it. Without the right
secret, requests are refused (health checks excepted, so the host can monitor
the API). Only with the right secret is the visitor's address trusted.

The secret is off unless PROXY_SHARED_SECRET is set; production requires it.
"""

import hmac
import ipaddress

from flask import Flask, current_app, g, request

from app.errors import ApiError

PROXY_SECRET_HEADER = "X-SMS-Proxy-Secret"  # noqa: S105 (a header name, not a secret)
CLIENT_IP_HEADER = "X-SMS-Client-IP"
# Called by the hosting platform itself, which does not know the secret.
EXEMPT_PATHS = frozenset({"/api/v1/health", "/api/v1/health/ready"})


def register_frontend_proxy_check(app: Flask) -> None:
    @app.before_request
    def require_frontend_proxy():
        g.via_frontend_proxy = False
        secret = current_app.config["PROXY_SHARED_SECRET"]
        if not secret:
            return None
        sent = request.headers.get(PROXY_SECRET_HEADER, "")
        # Constant-time comparison, so the secret cannot be guessed by timing.
        if hmac.compare_digest(sent.encode(), secret.encode()):
            g.via_frontend_proxy = True
            return None
        if request.path in EXEMPT_PATHS:
            return None
        raise ApiError(403, "forbidden", "Requests must come through the website.")


def client_ip() -> str:
    """The visitor's IP address, as far as it can be trusted.

    The frontend's header is used only on requests that carried the right
    secret, and only if it is a well-formed address. Otherwise this is the
    network peer (or, with TRUSTED_PROXY_COUNT set, what ProxyFix found).
    """
    if g.get("via_frontend_proxy"):
        forwarded = request.headers.get(CLIENT_IP_HEADER, "").strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            current_app.logger.warning("Frontend proxy sent no valid client IP")
    return request.remote_addr or "unknown"
