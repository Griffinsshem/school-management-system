import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.auth.passwords import hash_password
from app.extensions import db
from app.models import User
from app.models.user import EmailFormatError, normalize_email, validate_email

INSUFFICIENT_PRIVILEGE = "42501"
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"


def _user(email: str = "ada@example.com") -> User:
    return User(email=email, full_name="Ada Example", password_hash=hash_password("x" * 12))


def test_email_is_normalized():
    assert normalize_email("  Ada@Example.COM ") == "ada@example.com"


@pytest.mark.parametrize(
    "email",
    ["", "ada", "ada@", "@example.com", "ada@example", "a da@example.com", "a" * 250 + "@x.io"],
)
def test_invalid_emails_are_rejected(email):
    with pytest.raises(EmailFormatError):
        validate_email(email)


def test_new_user_gets_safe_defaults(db_app):
    with db_app.app_context():
        user = _user()
        db.session.add(user)
        db.session.commit()

        assert isinstance(user.id, uuid.UUID)
        assert user.is_active is True
        assert user.is_platform_admin is False
        assert user.created_at.tzinfo is not None


def test_database_rejects_an_unnormalized_email(db_app):
    with db_app.app_context():
        db.session.add(_user("Ada@Example.com"))
        with pytest.raises(IntegrityError) as excinfo:
            db.session.commit()
        db.session.rollback()

    assert excinfo.value.orig.sqlstate == CHECK_VIOLATION


def test_database_rejects_a_duplicate_email(db_app):
    with db_app.app_context():
        db.session.add(_user())
        db.session.commit()
        db.session.add(_user())
        with pytest.raises(IntegrityError) as excinfo:
            db.session.commit()
        db.session.rollback()

    assert excinfo.value.orig.sqlstate == UNIQUE_VIOLATION


def test_runtime_user_cannot_alter_the_users_table(db_app):
    with db_app.app_context(), db.engine.connect() as connection:
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text("ALTER TABLE users ADD COLUMN probe integer"))

    assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_repr_does_not_reveal_personal_data():
    user = _user()
    user.id = uuid.uuid4()

    assert "ada" not in repr(user).lower()
    assert str(user.id) in repr(user)
