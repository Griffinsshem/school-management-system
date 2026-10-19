from alembic.script import ScriptDirectory
from flask import current_app
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, inspect, text


def _applied_revisions(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                return set()
            rows = connection.execute(text("SELECT version_num FROM alembic_version"))
            return {row[0] for row in rows}
    finally:
        engine.dispose()


def test_migrations_upgrade_and_downgrade_cleanly(app):
    url = app.config["MIGRATION_DATABASE_URI"]
    assert url, "TEST_MIGRATION_DATABASE_URL must be set to run migration tests."

    with app.app_context():
        alembic_config = current_app.extensions["migrate"].migrate.get_config()
        heads = set(ScriptDirectory.from_config(alembic_config).get_heads())
        assert heads, "No migrations found."

        upgrade()
        assert _applied_revisions(url) == heads

        downgrade(revision="base")
        assert _applied_revisions(url) == set()

        # Leave the test database fully migrated for other tests.
        upgrade()
        assert _applied_revisions(url) == heads
