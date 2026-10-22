"""Recording audit events: who did what, to what, and whether it was allowed.

`record()` adds the event to the current database transaction, so a change
and its audit event are saved together or not at all. For refused actions
there is no change to save, so callers commit straight away (see
`record_denied`).
"""

import uuid

from flask import g, has_request_context

from app.extensions import db
from app.models import AuditEvent
from app.observability import get_request_id


def _current_actor_id() -> uuid.UUID | None:
    if has_request_context():
        user = g.get("current_user")
        if user is not None:
            return user.id
    return None


def record(
    action: str,
    *,
    school_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    outcome: str = "success",
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Add an audit event to the session. The caller commits.

    The actor is the logged-in user, unless `actor_user_id` names someone
    else (for example a person whose account was created by this request).
    """
    db.session.add(
        AuditEvent(
            actor_user_id=actor_user_id or _current_actor_id(),
            school_id=school_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            request_id=get_request_id(),
        )
    )


def record_denied(
    action: str,
    *,
    school_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
) -> None:
    """Record a refused action and commit it immediately."""
    record(
        action,
        school_id=school_id,
        target_type=target_type,
        target_id=target_id,
        outcome="denied",
    )
    db.session.commit()
