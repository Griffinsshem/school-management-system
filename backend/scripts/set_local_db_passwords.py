"""Set new passwords for the local database users.

Generates a random password for sms_app and sms_migrator, writes the four
connection strings into backend/.env, and prints SQL that stores the passwords
in PostgreSQL as SCRAM-SHA-256 hashes. No password is ever displayed.

Run from the backend/ folder, piping the output straight into psql:

    python scripts/set_local_db_passwords.py | sudo -u postgres psql -v ON_ERROR_STOP=1

Safe to re-run: each run replaces both passwords (useful for rotation).
"""

import base64
import hashlib
import hmac
import os
import secrets
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
HOST = "127.0.0.1:5432"
SCRAM_ITERATIONS = 4096


def scram_sha256_verifier(password: str) -> str:
    """Build the hash PostgreSQL stores for a SCRAM-SHA-256 password."""
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, SCRAM_ITERATIONS)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    def b64(data: bytes) -> str:
        return base64.b64encode(data).decode()

    return f"SCRAM-SHA-256${SCRAM_ITERATIONS}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def update_env_file(values: dict[str, str]) -> None:
    """Replace or append the given keys in .env, leaving other lines untouched."""
    if not ENV_FILE.exists():
        sys.exit(f"{ENV_FILE} not found. Create it first: cp .env.example .env")

    lines = ENV_FILE.read_text().splitlines()
    remaining = dict(values)
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            lines[index] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())

    ENV_FILE.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)


def main() -> None:
    if sys.stdout.isatty():
        sys.exit(
            "Refusing to print to the screen. Pipe the output into psql:\n"
            "  python scripts/set_local_db_passwords.py | sudo -u postgres psql -v ON_ERROR_STOP=1"
        )

    # token_urlsafe uses only A-Z, a-z, 0-9, '-' and '_', so no URL escaping is needed.
    app_password = secrets.token_urlsafe(32)
    migrator_password = secrets.token_urlsafe(32)

    def url(user: str, password: str, database: str) -> str:
        return f"postgresql+psycopg://{user}:{password}@{HOST}/{database}"

    update_env_file(
        {
            "DATABASE_URL": url("sms_app", app_password, "sms_dev"),
            "MIGRATION_DATABASE_URL": url("sms_migrator", migrator_password, "sms_dev"),
            "TEST_DATABASE_URL": url("sms_app", app_password, "sms_test"),
            "TEST_MIGRATION_DATABASE_URL": url("sms_migrator", migrator_password, "sms_test"),
        }
    )

    print(f"ALTER ROLE sms_app PASSWORD '{scram_sha256_verifier(app_password)}';")
    print(f"ALTER ROLE sms_migrator PASSWORD '{scram_sha256_verifier(migrator_password)}';")
    print("Updated .env with new connection strings.", file=sys.stderr)


if __name__ == "__main__":
    main()
