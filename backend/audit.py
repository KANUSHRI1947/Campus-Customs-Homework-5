"""Append-only audit trail for the Campus Customs agent team.

Every event is added to output/audit_trail.json while the agents run, so you
can open the file later and see exactly who did what, in order. The file is a
JSON list; each run ADDS to it and never replaces earlier runs.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = PROJECT_ROOT / "output" / "audit_trail.json"

# Keep very long tool results from bloating the file (the full numbers are
# still in the database; this only trims oversized text).
MAX_FIELD_CHARS = 4000


def _trim(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + f"... [trimmed {len(value) - MAX_FIELD_CHARS} chars]"
    if isinstance(value, dict):
        return {k: _trim(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_trim(v) for v in value]
    return value


def _load() -> list:
    if not AUDIT_PATH.exists():
        return []
    try:
        data = json.loads(AUDIT_PATH.read_text() or "[]")
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # Never silently throw old history away: keep the unreadable file aside.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    AUDIT_PATH.rename(AUDIT_PATH.with_name(f"audit_trail.unreadable-{stamp}.json"))
    return []


def log_event(run_id: str, agent: str, event: str, **details: Any) -> None:
    """Append one event to output/audit_trail.json right away."""
    entries = _load()
    entries.append({
        "seq": len(entries) + 1,
        "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "agent": agent,
        "event": event,
        **_trim(json.loads(json.dumps(details, default=str))),
    })
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUDIT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2))
    os.replace(tmp, AUDIT_PATH)  # atomic: the file is never left half-written


def read_events(*, limit: int = 50, run_id: str | None = None, agent: str | None = None,
                event: str | None = None, after_seq: int | None = None) -> list[dict]:
    """Read events back from the same append-only file (read-only; never rewrites it).

    Filters are optional. Returns the most recent `limit` matching events, oldest first.
    """
    if not AUDIT_PATH.exists():
        return []
    try:
        entries = json.loads(AUDIT_PATH.read_text() or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{AUDIT_PATH.name} is not valid JSON: {exc}") from exc
    if not isinstance(entries, list):
        raise ValueError(f"{AUDIT_PATH.name} does not contain a JSON list.")
    matches = [
        e for e in entries
        if (run_id is None or e.get("run_id") == run_id)
        and (agent is None or e.get("agent") == agent)
        and (event is None or e.get("event") == event)
        and (after_seq is None or e.get("seq", 0) > after_seq)
    ]
    return matches[-limit:] if limit > 0 else []
