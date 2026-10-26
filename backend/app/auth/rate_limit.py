"""Failed-login rate limiting, stored in PostgreSQL (no Redis on the free tier).

Counters are keyed by an HMAC of the normalized email or the client IP, so
neither is stored. Accounts are never locked permanently: once failures fall
out of the sliding window, logins are allowed again.
"""

import hashlib
import hmac
import math
from datetime import datetime

from flask import current_app
from sqlalchemy import delete, func, select

from app.extensions import db
from app.frontend_proxy import client_ip
from app.models import LoginAttempt


def _key_hash(key_type: str, value: str) -> str:
    secret = current_app.config["SECRET_KEY"].encode()
    message = f"login-rate-limit:{key_type}:{value}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _client_ip() -> str:
    # The frontend's client-IP header is trusted only on requests that carry
    # the shared proxy secret (see app.frontend_proxy).
    return client_ip()


def _keys(email: str) -> list[tuple[str, str, int]]:
    config = current_app.config
    return [
        ("account", _key_hash("account", email), config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]),
        ("ip", _key_hash("ip", _client_ip()), config["LOGIN_MAX_FAILURES_PER_IP"]),
    ]


def retry_after_seconds(email: str, now: datetime) -> int | None:
    """Seconds until a login may be tried again, or None if it is allowed now."""
    window = current_app.config["LOGIN_WINDOW"]
    since = now - window
    longest_wait = None

    for key_type, key_hash, limit in _keys(email):
        recent = (
            LoginAttempt.key_type == key_type,
            LoginAttempt.key_hash == key_hash,
            LoginAttempt.attempted_at > since,
        )
        failures = db.session.scalar(select(func.count()).select_from(LoginAttempt).where(*recent))
        if failures >= limit:
            # Blocked until enough of the oldest failures leave the window.
            oldest_counted = db.session.scalars(
                select(LoginAttempt.attempted_at)
                .where(*recent)
                .order_by(LoginAttempt.attempted_at.desc())
                .offset(limit - 1)
                .limit(1)
            ).one()
            wait = max(1, math.ceil((oldest_counted + window - now).total_seconds()))
            longest_wait = max(longest_wait or 0, wait)

    return longest_wait


def record_failure(email: str, now: datetime) -> None:
    """Count one failed attempt against the account and the IP. The caller commits."""
    for key_type, key_hash, _limit in _keys(email):
        db.session.add(LoginAttempt(key_type=key_type, key_hash=key_hash, attempted_at=now))


def clear_account_failures(email: str) -> None:
    """After a successful login, forget the account's failures. The caller commits."""
    db.session.execute(
        delete(LoginAttempt).where(
            LoginAttempt.key_type == "account",
            LoginAttempt.key_hash == _key_hash("account", email),
        )
    )


def prune(now: datetime) -> int:
    """Delete attempts that have left the window. Returns how many. The caller commits."""
    since = now - current_app.config["LOGIN_WINDOW"]
    result = db.session.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at <= since))
    return result.rowcount
