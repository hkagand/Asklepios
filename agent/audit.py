"""Append-only audit trail: every question, tool call, answer and error, one JSON object per line."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()

    def write(self, *, session: str, patient: str, event: str, **fields: object) -> None:
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "user": "demo-clinician",
            "session": session,
            "patient": patient,
            "event": event,
            **fields,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock, self._path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
