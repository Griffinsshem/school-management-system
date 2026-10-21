"""Server-side login sessions carried by an HttpOnly cookie.

The browser holds a random token; the database holds only its SHA-256 hash,
so a leaked database cannot be turned into working cookies. A token has
enough randomness (256 bits) that a fast hash is safe here, unlike passwords.
"""

import hashlib
import secrets
from datetime import UTC, datetime
from functools import wraps

from flask import Response, current_app, g, request
from sqlalchemy import delete, select

from app.errors import ApiError
from app.extensions import db
from app.models import User, UserSession

# Real tokens are 43 characters; anything far longer is refused unread.
_MAX_TOKEN_LENGTH = 128


def utcnow() -> datetime:
    """The current time. Tests replace this to move the clock."""
    return datetime.now(UTC)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def cookie_name() -> str:
    # The __Host- prefix makes browsers require Secure, Path=/ and no Domain.
    return "__Host-sms_session" if current_app.config["AUTH_COOKIE_SECURE"] else "sms_session"


def start_session(user: User) -> str:
    """Create a brand-new session for `user` and return its token.

    A new token on every login defeats session fixation. The caller commits.
    """
    token = new_token()
    now = utcnow()
    db.session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            last_seen_at=now,
            expires_at=now + current_app.config["SESSION_ABSOLUTE_TIMEOUT"],
        )
    )
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        cookie_name(),
        token,
        max_age=int(current_app.config["SESSION_ABSOLUTE_TIMEOUT"].total_seconds()),
        path="/",
        secure=current_app.config["AUTH_COOKIE_SECURE"],
        httponly=True,
        samesite="Lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        cookie_name(),
        path="/",
        secure=current_app.config["AUTH_COOKIE_SECURE"],
        httponly=True,
        samesite="Lax",
    )


def _find_session() -> UserSession | None:
    token = request.cookies.get(cookie_name())
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    return db.session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))


def current_user() -> User | None:
    """The logged-in user for this request, or None.

    Expired sessions and sessions of deactivated users are deleted on sight.
    The result is cached on `g` for the rest of the request.
    """
    if "current_user" in g:
        return g.current_user

    g.current_user = None
    user_session = _find_session()
    if user_session is None:
        return None

    now = utcnow()
    idle_limit = user_session.last_seen_at + current_app.config["SESSION_IDLE_TIMEOUT"]
    user = db.session.get(User, user_session.user_id)
    if now >= user_session.expires_at or now >= idle_limit or user is None or not user.is_active:
        db.session.delete(user_session)
        db.session.commit()
        return None

    if now - user_session.last_seen_at >= current_app.config["SESSION_TOUCH_INTERVAL"]:
        user_session.last_seen_at = now
        db.session.commit()

    g.current_session = user_session
    g.current_user = user
    return user


def end_current_session() -> None:
    """Delete this request's session, if there is one. The caller commits."""
    user_session = _find_session()
    if user_session is not None:
        db.session.delete(user_session)


def end_all_sessions(user: User) -> None:
    """Delete every session of `user` (for example on deactivation). The caller commits."""
    db.session.execute(delete(UserSession).where(UserSession.user_id == user.id))


def login_required(view):
    """Reject the request with 401 unless a valid session is present."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            raise ApiError(401, "unauthorized", "You need to log in to do that.")
        return view(*args, **kwargs)

    return wrapped
