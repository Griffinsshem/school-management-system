import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.extensions import db
from app.models import AuditEvent

INSUFFICIENT_PRIVILEGE = "42501"
CHECK_VIOLATION = "23514"


def _event(**fields) -> AuditEvent:
    values = {
        "actor_user_id": uuid.uuid4(),
        "school_id": uuid.uuid4(),
        "action": "membership.deactivated",
        "target_type": "membership",
        "target_id": uuid.uuid4(),
        "outcome": "success",
        "request_id": "a" * 32,
    } | fields
    return AuditEvent(**values)


def test_the_api_user_can_add_and_read_events(db_app):
    with db_app.app_context():
        event = _event()
        db.session.add(event)
        db.session.commit()

        assert event.occurred_at.tzinfo is not None
        assert db.session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_terminal_actions_have_no_actor_or_request(db_app):
    with db_app.app_context():
        db.session.add(_event(actor_user_id=None, request_id=None, school_id=None))
        db.session.commit()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET outcome = 'denied'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
def test_the_api_user_cannot_change_or_erase_events(db_app, statement):
    with db_app.app_context():
        db.session.add(_event())
        db.session.commit()

        with db.engine.connect() as connection:
            with pytest.raises(ProgrammingError) as excinfo:
                connection.execute(text(statement))

        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE
        assert db.session.scalar(select(AuditEvent.outcome)) == "success"


@pytest.mark.parametrize(
    "fields",
    [
        {"action": "deactivated"},
        {"action": "Membership.Deactivated"},
        {"action": "membership.deactivated; drop"},
        {"outcome": "maybe"},
    ],
)
def test_database_rejects_malformed_events(db_app, fields):
    with db_app.app_context():
        db.session.add(_event(**fields))
        with pytest.raises(IntegrityError) as excinfo:
            db.session.commit()
        db.session.rollback()

    assert excinfo.value.orig.sqlstate == CHECK_VIOLATION


def test_repr_shows_only_the_id_and_action():
    event = _event()
    event.id = uuid.uuid4()

    assert repr(event) == f"<AuditEvent {event.id} membership.deactivated>"
