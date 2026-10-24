"""The production web server: gunicorn settings, the WSGI entry point, and a
real gunicorn run that shows no request line carries a query string."""

import os
import runpy
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
RENDER_BLUEPRINT = BACKEND_DIR.parent / "render.yaml"
# What Render puts in every Python service's environment (its documented default).
RENDER_GUNICORN_CMD_ARGS = "--preload --access-logfile - --bind=0.0.0.0:10000"
PRODUCTION_ENV = {
    "APP_ENV": "production",
    "SECRET_KEY": "x" * 48,
    # Never connected to: the health check does not touch the database.
    "DATABASE_URL": "postgresql+psycopg://user:pass@127.0.0.1:1/unused",
    "FRONTEND_ORIGIN": "https://app.example.com",
}
APP_VARIABLES = (
    "APP_ENV",
    "SECRET_KEY",
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "FRONTEND_ORIGIN",
    "TRUSTED_PROXY_COUNT",
)


@pytest.fixture
def clean_env(monkeypatch):
    for name in APP_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_gunicorn_settings(monkeypatch):
    monkeypatch.setenv("PORT", "12345")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    settings = runpy.run_path(str(BACKEND_DIR / "gunicorn.conf.py"))

    assert settings["bind"] == "0.0.0.0:12345"
    assert settings["workers"] == 2
    # Off on purpose: gunicorn's access log would record query strings and IPs.
    assert settings["accesslog"] is None
    assert settings["control_socket_disable"] is True


def test_gunicorn_refuses_to_start_with_an_access_log():
    on_starting = runpy.run_path(str(BACKEND_DIR / "gunicorn.conf.py"))["on_starting"]

    on_starting(SimpleNamespace(cfg=SimpleNamespace(accesslog=None)))
    with pytest.raises(RuntimeError, match="access log is on"):
        on_starting(SimpleNamespace(cfg=SimpleNamespace(accesslog="-")))


def test_wsgi_refuses_to_start_without_settings(clean_env):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        runpy.run_path(str(BACKEND_DIR / "wsgi.py"))


def test_wsgi_starts_in_production_mode(clean_env):
    for name, value in PRODUCTION_ENV.items():
        clean_env.setenv(name, value)

    app = runpy.run_path(str(BACKEND_DIR / "wsgi.py"))["app"]

    assert not app.config["TESTING"]
    assert app.config["AUTH_COOKIE_SECURE"] is True
    assert app.config["LOG_FORMAT"] == "json"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def render_start_command() -> list[str]:
    """render.yaml's start command, run with this test's Python."""
    lines = [line.strip() for line in RENDER_BLUEPRINT.read_text().splitlines()]
    command = next(line for line in lines if line.startswith("startCommand:"))
    words = shlex.split(command.removeprefix("startCommand:"))
    index = words.index("gunicorn")
    return [*words[:index], sys.executable, "-m", *words[index:]]


def run_gunicorn(command: list[str], extra_env: dict[str, str]):
    """Start gunicorn, request the health check with a query string, stop it.

    Returns (response body or None if it never answered, everything it printed).
    """
    port = _free_port()
    env = (
        {key: value for key, value in os.environ.items() if key not in APP_VARIABLES}
        | PRODUCTION_ENV
        | {"PORT": str(port), "WEB_CONCURRENCY": "1"}
        | extra_env
    )
    # Listen on this computer only, whatever the settings say.
    command = [*command[:-1], "--bind", f"127.0.0.1:{port}", command[-1]]
    server = subprocess.Popen(  # noqa: S603 (fixed command, no shell)
        command,
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    body = None
    try:
        url = f"http://127.0.0.1:{port}/api/v1/health?q=Secret-Child-Name"
        for _ in range(50):
            if server.poll() is not None:
                break
            try:
                with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                    body = response.read().decode()
                break
            except OSError:
                time.sleep(0.2)
    finally:
        server.terminate()
        output, _ = server.communicate(timeout=20)
    return body, output


def test_render_start_command_serves_without_logging_query_strings():
    command = render_start_command()
    assert command[:3] == ["env", "-u", "GUNICORN_CMD_ARGS"]

    # Render's own GUNICORN_CMD_ARGS is in the environment, as on Render.
    body, output = run_gunicorn(command, {"GUNICORN_CMD_ARGS": RENDER_GUNICORN_CMD_ARGS})

    assert body is not None, output
    assert '"status": "ok"' in body or '"status":"ok"' in body
    assert '"path": "/api/v1/health"' in output
    assert "Secret-Child-Name" not in output
    assert "Control socket" not in output


def test_gunicorn_will_not_serve_if_render_settings_reach_it():
    command = [sys.executable, "-m", "gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]

    body, output = run_gunicorn(command, {"GUNICORN_CMD_ARGS": RENDER_GUNICORN_CMD_ARGS})

    assert body is None
    assert "access log is on" in output
    assert "Secret-Child-Name" not in output
