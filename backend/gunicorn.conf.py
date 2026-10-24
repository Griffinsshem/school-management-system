"""Production web server settings (gunicorn), used on Render.

gunicorn -c gunicorn.conf.py wsgi:app
"""

import os

# Render tells the service which port to listen on.
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# Each worker is a separate process with its own database connections. Two
# fit in a 512 MB instance: a password check briefly uses about 19 MiB.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = 30
graceful_timeout = 20
keepalive = 5

# No access log: the app writes its own line per request without query
# strings or IP addresses, while gunicorn's access log would include both
# (and a student search carries part of a child's name in the query string).
# Settings in the GUNICORN_CMD_ARGS environment variable override this file;
# Render sets it to turn the access log on, so render.yaml's start command
# removes it, and on_starting() below refuses to run if anything turns it on.
accesslog = None
errorlog = "-"
loglevel = "info"

# gunicorn's local control socket (for stopping or reloading it by command)
# is not needed on Render and would be one more way in, so it is turned off.
control_socket_disable = True


def on_starting(server):
    """Stop before serving anything if the access log has been turned on."""
    if server.cfg.accesslog is not None:
        raise RuntimeError(
            "gunicorn's access log is on, and it would record query strings. "
            "Remove --access-logfile (check GUNICORN_CMD_ARGS and the start command)."
        )
