"""scripts/staging_database.py: connection-string checks, the files it writes,
and the least-privilege checks (run here against the migrated test database,
which is set up the same way as staging)."""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "staging_database.py"
spec = importlib.util.spec_from_file_location("staging_database", SCRIPT)
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)

DIRECT = (
    "postgresql://neondb_owner:owner-secret@ep-calm-sun-123.eu-central-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)


def test_accepts_neon_direct_connection_string():
    url = staging.parse_owner_url(DIRECT + "\n")
    assert url.host == "ep-calm-sun-123.eu-central-1.aws.neon.tech"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (DIRECT.replace("-123.", "-123-pooler."), "pooled"),
        (DIRECT.split("?")[0], "sslmode"),
        (DIRECT.replace("sslmode=require", "sslmode=prefer"), "sslmode"),
        (DIRECT.replace(":owner-secret", ""), "Expected a connection string"),
        ("mysql://user:pass@example.com/db?sslmode=require", "Expected a connection string"),
        ("not a url", "does not look like"),
    ],
)
def test_rejects_unsafe_or_wrong_connection_strings(raw, message):
    with pytest.raises(staging.SetupError, match=message):
        staging.parse_owner_url(raw)


def test_app_urls_keep_host_and_tls_but_change_user_and_database():
    owner = staging.parse_owner_url(DIRECT)
    urls = staging.build_urls(owner, "app-pass", "migrator-pass")

    assert urls["DATABASE_URL"].startswith(
        "postgresql+psycopg://sms_app:app-pass@ep-calm-sun-123.eu-central-1.aws.neon.tech/sms_staging?"
    )
    assert urls["MIGRATION_DATABASE_URL"].startswith(
        "postgresql+psycopg://sms_migrator:migrator-pass@"
    )
    for url in urls.values():
        assert "sslmode=require" in url
        assert "channel_binding=require" in url
        assert "owner-secret" not in url


def test_env_file_loads_safely_in_a_shell(tmp_path):
    owner = staging.parse_owner_url(DIRECT)
    text = staging.env_file_text(staging.build_urls(owner, "app-pass", "migrator-pass"))
    env_file = tmp_path / ".env.staging"
    env_file.write_text(text)

    # The '&' in the URLs must not be treated as a shell command separator.
    result = subprocess.run(  # noqa: S603 (fixed command, no user input)
        ["/bin/sh", "-c", 'set -a; . "$1"; printf %s "$DATABASE_URL"', "sh", str(env_file)],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": os.environ.get("PATH", "")},
    )
    assert result.stdout.endswith("sslmode=require")
    assert "channel_binding=require" in result.stdout
    assert "APP_ENV='production'" in text
    assert f"FRONTEND_ORIGIN='{staging.PLACEHOLDER_ORIGIN}'" in text


def test_env_file_is_private_and_never_overwritten(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.staging"
    monkeypatch.setattr(staging, "ENV_FILE", env_file)

    staging.write_env_file("A='1'\n")
    assert env_file.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        staging.write_env_file("A='2'\n")
    assert env_file.read_text() == "A='1'\n"


def test_checks_pass_for_the_least_privilege_api_user(migrated_database, capsys):
    passed = staging.run_checks(os.environ["TEST_DATABASE_URL"], require_tls=False)

    output = capsys.readouterr().out
    assert passed, output
    assert "FAIL" not in output
    assert "Row-Level Security is on for students" in output


def test_checks_fail_for_the_schema_owner(migrated_database, capsys):
    passed = staging.run_checks(os.environ["TEST_MIGRATION_DATABASE_URL"], require_tls=False)

    assert not passed
    assert "FAIL  connected as sms_migrator" in capsys.readouterr().out
