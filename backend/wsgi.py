"""Entry point for the production web server.

    gunicorn -c gunicorn.conf.py wsgi:app

Settings come from environment variables (APP_ENV, SECRET_KEY, DATABASE_URL,
FRONTEND_ORIGIN, TRUSTED_PROXY_COUNT, ...). APP_ENV defaults to production,
and missing or unsafe settings stop the server from starting.
"""

from app import create_app

app = create_app()
