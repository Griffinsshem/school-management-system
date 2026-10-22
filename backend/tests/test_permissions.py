import pytest

from app.auth.permissions import (
    ALL_PERMISSIONS,
    MEMBERS_MANAGE,
    MEMBERS_READ,
    ROLE_PERMISSIONS,
    STUDENTS_MANAGE,
    STUDENTS_READ,
    permission_required,
)
from app.models.membership import ROLES

ME = "/api/v1/auth/me"
PASSWORD = "correct horse battery"


def _client_for(app, email="ada@example.com"):
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


def test_every_role_has_an_explicit_permission_list():
    assert set(ROLE_PERMISSIONS) == set(ROLES)


def test_roles_get_only_what_they_are_given():
    assert ROLE_PERMISSIONS["school_admin"] == {
        MEMBERS_READ,
        MEMBERS_MANAGE,
        STUDENTS_READ,
        STUDENTS_MANAGE,
    }
    assert ROLE_PERMISSIONS["principal"] == {MEMBERS_READ, STUDENTS_READ}
    assert ROLE_PERMISSIONS["registrar"] == {STUDENTS_READ, STUDENTS_MANAGE}
    # Teachers get no student access until classes exist.
    for role in ("teacher", "finance_officer", "guardian", "student"):
        assert ROLE_PERMISSIONS[role] == frozenset()
    assert ALL_PERMISSIONS == {MEMBERS_READ, MEMBERS_MANAGE, STUDENTS_READ, STUDENTS_MANAGE}


def test_an_unknown_permission_is_a_programming_error():
    with pytest.raises(ValueError, match="Unknown permission"):
        permission_required("members.delete_everything")


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["school_admin"], ["members.manage", "members.read", "students.manage", "students.read"]),
        (["principal"], ["members.read", "students.read"]),
        (["teacher"], []),
        (["teacher", "principal"], ["members.read", "students.read"]),
        (["principal", "registrar"], ["members.read", "students.manage", "students.read"]),
    ],
)
def test_me_lists_the_permissions_of_all_roles_combined(
    db_app, make_user, make_school, add_member, roles, expected
):
    user_id, school_id = make_user(), make_school()
    for role in roles:
        add_member(user_id, school_id, role)

    body = _client_for(db_app).get(ME).get_json()

    assert body["permissions"] == expected


def test_permissions_come_only_from_the_active_school(db_app, make_user, make_school, add_member):
    user_id = make_user()
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    add_member(user_id, school_a, "school_admin")
    add_member(user_id, school_b, "teacher")
    client = _client_for(db_app)

    client.post("/api/v1/auth/active-school", json={"school_id": str(school_b)})
    body = client.get(ME).get_json()

    assert body["active_school"]["code"] == "school-b"
    assert body["permissions"] == []
    assert client.get("/api/v1/school/members").status_code == 403


def test_no_active_school_means_no_permissions(db_app, make_user):
    make_user(is_platform_admin=True)

    assert _client_for(db_app).get(ME).get_json()["permissions"] == []
