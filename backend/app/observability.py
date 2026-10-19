"""Request IDs, one summary log line per request, and log formatting.

Every request gets an ID: a safe incoming X-Request-ID header is reused,
anything else is replaced with a new random ID. The ID is returned in the
response header, included in error bodies and stamped on every log line.

Privacy: the summary line records method, path (never the query string),
status and duration only. Bodies, headers, cookies, query strings and IP
addresses are never logged.
"""

import json
import logging
import re
import sys
import time
import uuid
from datetime import UTC, datetime

from flask import Flask, g, has_request_context, request

REQUEST_ID_HEADER = "X-Request-ID"

# Letters, digits, '-' and '_' only, 8 to 64 characters. Anything else could
# be used to forge log lines or tamper with response headers.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")

# Control characters (such as a newline sent as %0A in a URL) are escaped
# before logging, so a crafted path cannot start a fake log line.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")

_SUMMARY_FIELDS = ("method", "path", "status", "duration_ms")
_TEXT_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


def _escape_control_characters(text: str) -> str:
    return _CONTROL_CHARACTERS.sub(lambda match: f"\\x{ord(match.group()):02x}", text)


def get_request_id() -> str | None:
    """The current request's ID, or None outside a request."""
    if has_request_context():
        return g.get("request_id")
    return None


class RequestIdFilter(logging.Filter):
    """Adds the current request ID ("-" outside a request) to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log collectors in production."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for field in _SUMMARY_FIELDS:
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(app: Flask) -> None:
    """Send the app's logs to standard output in the configured format."""
    handler = logging.StreamHandler(sys.stdout)
    if app.config["LOG_FORMAT"] == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))
    handler.addFilter(RequestIdFilter())

    logger = app.logger
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
    logger.addHandler(handler)
    logger.setLevel(app.config["LOG_LEVEL"])
    logger.propagate = False


def register_request_hooks(app: Flask) -> None:
    summary_logger = logging.getLogger(f"{app.logger.name}.request")

    @app.before_request
    def assign_request_id():
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        g.request_id = incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def finish_request(response):
        request_id = g.get("request_id")
        if request_id:
            response.headers[REQUEST_ID_HEADER] = request_id

        started = g.get("request_started")
        duration_ms = round((time.perf_counter() - started) * 1000, 1) if started else None
        path = _escape_control_characters(request.path)
        summary_logger.info(
            "%s %s %s %sms",
            request.method,
            path,
            response.status_code,
            duration_ms,
            extra={
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
