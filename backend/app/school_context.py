"""Telling PostgreSQL which school the current transaction belongs to.

Row-Level Security policies on school-owned tables (such as `students`)
compare each row's `school_id` with the `app.current_school_id` setting.
That setting is transaction-local (`set_config(..., true)`): it disappears
when the transaction ends, so a pooled connection reused by another request
never carries a previous school's context.

It is applied in two places:
- when a request's active school is established (`current_school()`), for
  the transaction already in progress;
- at the start of every later transaction in the same request, by the
  `after_begin` listener below.

Without a school (no request, no login, no active school), the setting is
empty and the policies return no rows: the database fails closed.
"""

import uuid

from flask import g, has_request_context
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.extensions import db

SETTING = "app.current_school_id"
_SET_SCHOOL = text(f"SELECT set_config('{SETTING}', :school_id, true)")


def _value(school_id: uuid.UUID | None) -> str:
    return str(school_id) if school_id else ""


def set_database_school(school_id: uuid.UUID | None) -> None:
    """Make `school_id` the request's database school, starting now.

    The ID is kept as a plain value on `g` (not a database object, which
    could need reloading while a connection is being set up).
    """
    if has_request_context():
        g.current_school_id = school_id
    db.session.execute(_SET_SCHOOL, {"school_id": _value(school_id)})


def _request_school_id() -> uuid.UUID | None:
    return g.get("current_school_id") if has_request_context() else None


def _apply_on_begin(session, transaction, connection) -> None:
    connection.execute(_SET_SCHOOL, {"school_id": _value(_request_school_id())})


def register_school_context() -> None:
    """Install the listener once per process (create_app may run many times)."""
    if not event.contains(Session, "after_begin", _apply_on_begin):
        event.listen(Session, "after_begin", _apply_on_begin)
