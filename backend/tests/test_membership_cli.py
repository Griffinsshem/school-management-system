import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Membership


def _run(app, email="ada@example.com", school_code="greenfield-academy", role="teacher"):
    runner = app.test_cli_runner()
    return runner.invoke(
        args=["add-membership", "--email", email, "--school-code", school_code, "--role", role]
    )


def _memberships(app) -> list[tuple[str, bool]]:
    with app.app_context():
        rows = db.session.execute(select(Membership.role, Membership.is_active)).all()
        return sorted((role, active) for role, active in rows)


@pytest.fixture
def user_and_school(make_user, make_school):
    return make_user(), make_school()


def test_adds_a_membership(db_app, user_and_school):
    result = _run(db_app, email=" ADA@example.com", school_code="Greenfield-Academy")

    assert result.exit_code == 0, result.output
    assert "is now teacher at Greenfield Academy" in result.output
    assert _memberships(db_app) == [("teacher", True)]


def test_a_second_role_can_be_added(db_app, user_and_school):
    _run(db_app, role="teacher")
    result = _run(db_app, role="guardian")

    assert result.exit_code == 0, result.output
    assert _memberships(db_app) == [("guardian", True), ("teacher", True)]


def test_refuses_an_existing_active_role(db_app, user_and_school):
    _run(db_app)
    result = _run(db_app)

    assert result.exit_code != 0
    assert "already has that role" in result.output
    assert _memberships(db_app) == [("teacher", True)]


def test_reactivates_a_deactivated_role(db_app, user_and_school, add_member):
    user_id, school_id = user_and_school
    add_member(user_id, school_id, "teacher", is_active=False)

    result = _run(db_app)

    assert result.exit_code == 0, result.output
    assert _memberships(db_app) == [("teacher", True)]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"email": "nobody@example.com"}, "No user with that email"),
        ({"school_code": "no-such-school"}, "No school with that code"),
        ({"role": "platform_admin"}, "Invalid value for '--role'"),
    ],
)
def test_refuses_bad_input(db_app, user_and_school, changes, message):
    result = _run(db_app, **changes)

    assert result.exit_code != 0
    assert message in result.output
    assert _memberships(db_app) == []
