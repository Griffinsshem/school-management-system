import pytest
from sqlalchemy import func, select

from app import create_app
from app.extensions import db
from app.models import School

LOGIN = "/api/v1/auth/login"
SCHOOLS = "/api/v1/platform/schools"
PASSWORD = "correct horse battery"
NEW_SCHOOL = {"name": "Greenfield Academy", "code": "greenfield-academy", "county_code": 32}


def _logged_in_client(app, email):
    client = app.test_client()
    response = client.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


@pytest.fixture
def admin_client(db_app, make_user):
    make_user(email="root@example.com", is_platform_admin=True)
    return _logged_in_client(db_app, "root@example.com")


def _school_count(app) -> int:
    with app.app_context():
        return db.session.scalar(select(func.count()).select_from(School))


def test_platform_admin_creates_a_school(db_app, admin_client):
    body = {"name": "  Greenfield Academy ", "code": " Greenfield-Academy ", "county_code": 32}

    response = admin_client.post(SCHOOLS, json=body)
    school = response.get_json()["school"]

    assert response.status_code == 201
    assert school["name"] == "Greenfield Academy"
    assert school["code"] == "greenfield-academy"
    assert (school["county_code"], school["county_name"]) == (32, "Nakuru")
    assert school["is_active"] is True
    assert _school_count(db_app) == 1


def test_creating_a_school_does_not_make_the_admin_a_member(admin_client):
    admin_client.post(SCHOOLS, json=NEW_SCHOOL)

    me = admin_client.get("/api/v1/auth/me").get_json()

    assert me["memberships"] == []
    assert me["active_school"] is None


def test_platform_admin_lists_all_schools_by_name(admin_client, make_school):
    make_school(code="zawadi-school", name="Zawadi School")
    make_school(code="amani-school", name="Amani School", is_active=False)

    response = admin_client.get(SCHOOLS)

    assert response.status_code == 200
    schools = response.get_json()["schools"]
    assert [s["name"] for s in schools] == ["Amani School", "Zawadi School"]
    assert [s["is_active"] for s in schools] == [False, True]


def test_duplicate_code_is_refused(db_app, admin_client):
    admin_client.post(SCHOOLS, json=NEW_SCHOOL)

    response = admin_client.post(SCHOOLS, json=NEW_SCHOOL | {"code": "GREENFIELD-academy"})

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "school_code_taken"
    assert _school_count(db_app) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"name": "x" * 201},
        {"code": "ab"},
        {"code": "green field"},
        {"code": "green--field"},
        {"county_code": 0},
        {"county_code": 48},
        {"county_code": "32"},
        {"county_code": True},
        {"county_code": 32.5},
        {"is_active": False},
    ],
)
def test_invalid_schools_are_rejected(db_app, admin_client, changes):
    response = admin_client.post(SCHOOLS, json=NEW_SCHOOL | changes)

    assert response.status_code == 422
    assert response.get_json()["error"]["details"]
    assert _school_count(db_app) == 0


@pytest.mark.parametrize("missing", ["name", "code", "county_code"])
def test_every_field_is_required(admin_client, missing):
    body = {key: value for key, value in NEW_SCHOOL.items() if key != missing}

    assert admin_client.post(SCHOOLS, json=body).status_code == 422


@pytest.mark.parametrize(("method", "body"), [("post", NEW_SCHOOL), ("get", None)])
def test_platform_endpoints_need_a_login(db_app, method, body):
    response = getattr(db_app.test_client(), method)(SCHOOLS, json=body)

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "body"), [("post", NEW_SCHOOL), ("get", None)])
def test_ordinary_users_are_refused(db_app, make_user, method, body):
    make_user()
    client = _logged_in_client(db_app, "ada@example.com")

    response = getattr(client, method)(SCHOOLS, json=body)

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"
    assert _school_count(db_app) == 0


def test_school_creation_logs_ids_but_no_names(migrated_database, db_app, make_user, capsys):
    make_user(email="root@example.com", is_platform_admin=True)
    client = _logged_in_client(create_app("testing"), "root@example.com")
    capsys.readouterr()

    response = client.post(SCHOOLS, json=NEW_SCHOOL)
    output = capsys.readouterr().out

    assert f"School created: school_id={response.get_json()['school']['id']}" in output
    assert "Greenfield" not in output
