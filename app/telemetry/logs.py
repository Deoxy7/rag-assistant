"""Structured logging: one JSON object per line, so logs can be filtered and aggregated by field.

    {"ts": "2026-10-03T…Z", "level": "INFO", "logger": "rag.request", "event": "request",
     "request_id": "…", "endpoint": "/query", "status": 200, "timings_ms": {…}, …}

Fields passed with `extra={"fields": {...}}` are merged into the object. Question
text is never logged (it can contain personal data); a hash and length are.
"""

import datetime as dt
import json
import logging


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {"ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
               "level": record.levelname, "logger": record.name, "event": record.getMessage()}
        obj.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False, default=str)


def configure(fmt: str = "json", level: str = "INFO") -> None:
    """Route the app's loggers (rag.*) to stderr in the chosen format; idempotent."""
    root = logging.getLogger("rag")
    root.setLevel(level.upper())
    for h in list(root.handlers):
        if getattr(h, "_rag", False):
            root.removeHandler(h)
    h = logging.StreamHandler()
    h._rag = True
    h.setFormatter(JsonFormatter() if fmt == "json" else
                   logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(h)
    root.propagate = False
