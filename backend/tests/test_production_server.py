"""The production web server: gunicorn settings, the WSGI entry point, and a
real gunicorn run that shows no request line carries a query string."""

import os
import runpy
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
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


def test_gunicorn_serves_without_logging_query_strings():
    port = _free_port()
    env = (
        {key: value for key, value in os.environ.items() if key not in APP_VARIABLES}
        | PRODUCTION_ENV
        | {"PORT": str(port), "WEB_CONCURRENCY": "1"}
    )
    server = subprocess.Popen(  # noqa: S603 (fixed command, no shell)
        [
            sys.executable,
            "-m",
            "gunicorn",
            "-c",
            "gunicorn.conf.py",
            "--bind",
            f"127.0.0.1:{port}",
            "wsgi:app",
        ],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        url = f"http://127.0.0.1:{port}/api/v1/health?q=Secret-Child-Name"
        for _ in range(50):
            try:
                with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                    body = response.read().decode()
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("gunicorn did not start")
    finally:
        server.terminate()
        output, _ = server.communicate(timeout=20)

    assert '"status": "ok"' in body or '"status":"ok"' in body
    assert '"path": "/api/v1/health"' in output
    assert "Secret-Child-Name" not in output
    assert "Control socket" not in output
