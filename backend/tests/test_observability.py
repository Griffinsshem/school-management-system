import json
import re

import pytest

from app import create_app

GENERATED_ID = re.compile(r"[0-9a-f]{32}")


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _summary_lines(text: str) -> list[dict]:
    return [entry for entry in _json_lines(text) if entry["logger"] == "app.request"]


def test_every_response_gets_a_generated_request_id(client):
    first = client.get("/api/v1/health")
    second = client.get("/api/v1/health")

    assert GENERATED_ID.fullmatch(first.headers["X-Request-ID"])
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_safe_incoming_request_id_is_reused(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "frontend-abc_12345"})

    assert response.headers["X-Request-ID"] == "frontend-abc_12345"


@pytest.mark.parametrize(
    "unsafe_id",
    [
        "short",  # too short
        "x" * 65,  # too long
        "abc12345\tforged-log-entry",  # control character
        "abc12345 forged",  # space
        "abc12345<script>",  # markup
    ],
)
def test_unsafe_incoming_request_id_is_replaced(client, unsafe_id):
    response = client.get("/api/v1/health", headers={"X-Request-ID": unsafe_id})

    assert response.headers["X-Request-ID"] != unsafe_id
    assert GENERATED_ID.fullmatch(response.headers["X-Request-ID"])


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [("GET", "/api/v1/nope", 404), ("POST", "/api/v1/health", 405)],
)
def test_error_bodies_include_the_request_id(client, method, path, status):
    response = client.open(path, method=method)

    assert response.status_code == status
    assert response.get_json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_summary_line_is_json_and_omits_the_query_string(capsys):
    app = create_app("testing")

    response = app.test_client().get("/api/v1/health?token=secret123&email=a@example.com")
    output = capsys.readouterr().out
    summaries = _summary_lines(output)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["request_id"] == response.headers["X-Request-ID"]
    assert summary["method"] == "GET"
    assert summary["path"] == "/api/v1/health"
    assert summary["status"] == 200
    assert isinstance(summary["duration_ms"], float)
    assert summary["level"] == "INFO"
    for leaked in ("secret123", "token=", "a@example.com"):
        assert leaked not in output


def test_request_body_and_headers_are_not_logged(capsys):
    app = create_app("testing")

    app.test_client().post(
        "/api/v1/health",
        data="password=hunter2-secret",
        headers={"Authorization": "Bearer top-secret-token", "Cookie": "session=abc"},
    )
    output = capsys.readouterr().out

    assert _summary_lines(output)
    for leaked in ("hunter2-secret", "top-secret-token", "session=abc"):
        assert leaked not in output


def test_unhandled_error_is_logged_with_its_request_id(capsys):
    app = create_app("testing")

    @app.get("/boom")
    def boom():
        raise ValueError("internal detail for the log only")

    response = app.test_client().get("/boom")
    entries = _json_lines(capsys.readouterr().out)
    errors = [entry for entry in entries if entry["level"] == "ERROR"]

    assert len(errors) == 1
    assert errors[0]["request_id"] == response.headers["X-Request-ID"]
    assert "internal detail for the log only" in errors[0]["exception"]


def test_development_uses_readable_text_logs(capsys):
    app = create_app("testing", overrides={"LOG_FORMAT": "text"})

    response = app.test_client().get("/api/v1/health")
    output = capsys.readouterr().out

    assert f"[{response.headers['X-Request-ID']}] app.request: GET /api/v1/health 200" in output


def test_control_characters_in_the_path_cannot_forge_log_lines(capsys):
    app = create_app("testing", overrides={"LOG_FORMAT": "text"})

    app.test_client().get("/api/v1/nope%0A2026-01-01 INFO [forged] app.request: fake")
    lines = capsys.readouterr().out.splitlines()

    assert len(lines) == 1
    assert "\\x0a" in lines[0]


def test_log_level_hides_lower_levels(capsys):
    app = create_app("testing", overrides={"LOG_LEVEL": "WARNING"})

    app.test_client().get("/api/v1/health")

    assert capsys.readouterr().out == ""


def test_invalid_log_level_is_rejected():
    with pytest.raises(RuntimeError, match="LOG_LEVEL"):
        create_app("testing", overrides={"LOG_LEVEL": "LOUD"})


def test_log_level_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/example")
    monkeypatch.setenv("LOG_LEVEL", "warning")

    app = create_app("production")

    assert app.config["LOG_LEVEL"] == "WARNING"
