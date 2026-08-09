"""SQLite store for reports and their append-only status trail.

Preserves the prep-kit design (reference/report-status-design.md) on our
own storage: status changes are new rows in status_events chained to the
report, never edits — the full trail doubles as the audit record. The
report row carries a denormalised current_status purely for cheap listing;
status_events is the source of truth.

Reference codes stand in for authentication, exactly as designed:
possession of the code is the only credential a reporter needs, so there
is no account, no login and nothing to forget in an emergency.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

# No lookalike characters (0/O, 1/I/L) — codes get read over the phone
# and copied from paper forms at emergency hubs.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_PREFIX = "WGN"

STATUSES = ("received", "reviewing", "responding", "resolved")

CATEGORIES = (
    "flooding",
    "landslip",
    "road-damage",
    "tree-down",
    "power-lines",
    "water-supply",
    "building-damage",
    "blocked-drain",
    "welfare-need",
    "other",
)

REPORTER_ROLES = ("resident", "community-group", "emergency-hub", "on-behalf")

_DESC_MAX = 2000
_PLACE_MAX = 200
_CONTACT_MAX = 200
_NOTE_MAX = 1000

_db_path: Path | None = None
_write_lock = threading.Lock()


def init(db_path: str | Path) -> None:
    global _db_path
    _db_path = Path(db_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS reports (
                ref            TEXT PRIMARY KEY,
                created_at     TEXT NOT NULL,
                category       TEXT NOT NULL,
                description    TEXT NOT NULL,
                lat            REAL,
                lng            REAL,
                place_name     TEXT,
                reporter_role  TEXT NOT NULL DEFAULT 'resident',
                contact        TEXT,
                photo          TEXT,
                hazard         TEXT,
                current_status TEXT NOT NULL DEFAULT 'received'
            );
            CREATE TABLE IF NOT EXISTS status_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ref        TEXT NOT NULL REFERENCES reports(ref),
                status     TEXT NOT NULL,
                note       TEXT NOT NULL DEFAULT '',
                actor      TEXT NOT NULL DEFAULT 'ops',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_ref ON status_events(ref, id);
            """
        )


def _conn() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("store.init(db_path) has not been called")
    db = sqlite3.connect(_db_path, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_ref(db: sqlite3.Connection) -> str:
    # The code is the reporter's only credential, so it needs enough entropy
    # to resist enumeration: 8 chars over a 31-char alphabet is ~40 bits
    # (8.5e11 combinations) while staying readable over the phone. The
    # server additionally throttles failed lookups per client.
    for _ in range(50):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        ref = f"{CODE_PREFIX}-{code}"
        row = db.execute("SELECT 1 FROM reports WHERE ref=?", (ref,)).fetchone()
        if row is None:
            return ref
    raise RuntimeError("could not allocate a reference code")


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def create_report(
    *,
    category: str,
    description: str,
    lat: float | None = None,
    lng: float | None = None,
    place_name: str | None = None,
    reporter_role: str = "resident",
    contact: str | None = None,
    photo: str | None = None,
) -> dict:
    """Insert a report and its automatic 'received' acknowledgment in one
    transaction — the acknowledgment needs no human, it fires the instant
    the report lands (the design doc's first status).
    """
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    description = (description or "").strip()
    if not 3 <= len(description) <= _DESC_MAX:
        raise ValueError("description must be 3 to 2000 characters")
    if reporter_role not in REPORTER_ROLES:
        raise ValueError(f"reporter_role must be one of {REPORTER_ROLES}")
    if lat is not None:
        lat = float(lat)
        if not -90 <= lat <= 90:
            raise ValueError("lat out of range")
    if lng is not None:
        lng = float(lng)
        if not -180 <= lng <= 180:
            raise ValueError("lng out of range")
    place_name = (place_name or "").strip()[:_PLACE_MAX] or None
    contact = (contact or "").strip()[:_CONTACT_MAX] or None

    now = _now()
    with _write_lock, _conn() as db:
        ref = _new_ref(db)
        db.execute(
            "INSERT INTO reports (ref, created_at, category, description, lat, lng,"
            " place_name, reporter_role, contact, photo, current_status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?, 'received')",
            (ref, now, category, description, lat, lng, place_name,
             reporter_role, contact, photo),
        )
        db.execute(
            "INSERT INTO status_events (ref, status, note, actor, created_at)"
            " VALUES (?, 'received', 'Your report has reached the council.', 'system', ?)",
            (ref, now),
        )
    return get_report(ref, private=True)


def add_status(ref: str, status: str, note: str = "", actor: str = "ops") -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    note = (note or "").strip()[:_NOTE_MAX]
    now = _now()
    with _write_lock, _conn() as db:
        row = db.execute("SELECT ref FROM reports WHERE ref=?", (ref,)).fetchone()
        if row is None:
            raise KeyError(ref)
        db.execute(
            "INSERT INTO status_events (ref, status, note, actor, created_at)"
            " VALUES (?,?,?,?,?)",
            (ref, status, note, actor, now),
        )
        db.execute("UPDATE reports SET current_status=? WHERE ref=?", (status, ref))
    return {"ref": ref, "status": status, "note": note, "actor": actor, "created_at": now}


def set_hazard(ref: str, hazard: dict) -> None:
    with _write_lock, _conn() as db:
        db.execute("UPDATE reports SET hazard=? WHERE ref=?", (json.dumps(hazard), ref))


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def _row_to_report(row: sqlite3.Row, private: bool) -> dict:
    rep = {
        "ref": row["ref"],
        "created_at": row["created_at"],
        "category": row["category"],
        "lat": row["lat"],
        "lng": row["lng"],
        "place_name": row["place_name"],
        "reporter_role": row["reporter_role"],
        "status": row["current_status"],
    }
    if private:
        # Description, photo, contact and hazard context are ops/reporter
        # detail. The public view stays at category + place + status so a
        # reporter never accidentally publishes a phone number they typed
        # into the description.
        rep["description"] = row["description"]
        rep["contact"] = row["contact"]
        rep["photo"] = row["photo"]
        rep["hazard"] = json.loads(row["hazard"]) if row["hazard"] else None
    return rep


def get_report(ref: str, private: bool = False) -> dict | None:
    with _conn() as db:
        row = db.execute("SELECT * FROM reports WHERE ref=?", (ref,)).fetchone()
        if row is None:
            return None
        rep = _row_to_report(row, private)
        rep["history"] = [
            dict(r)
            for r in db.execute(
                "SELECT status, note, actor, created_at FROM status_events"
                " WHERE ref=? ORDER BY id", (ref,),
            )
        ]
    return rep


def reporter_view(ref: str) -> dict | None:
    """What possession of the reference code entitles you to see: your own
    report in full (minus contact echo) and its complete status history.
    """
    rep = get_report(ref, private=True)
    if rep:
        rep.pop("contact", None)
    return rep


def list_reports(limit: int = 500, private: bool = False,
                 status: str | None = None) -> list[dict]:
    q = "SELECT * FROM reports"
    args: list = []
    if status:
        q += " WHERE current_status=?"
        args.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(min(int(limit), 2000))
    with _conn() as db:
        return [_row_to_report(r, private) for r in db.execute(q, args)]


def stats() -> dict:
    with _conn() as db:
        rows = db.execute(
            "SELECT current_status AS s, COUNT(*) AS n FROM reports GROUP BY s"
        ).fetchall()
    counts = {s: 0 for s in STATUSES}
    counts.update({r["s"]: r["n"] for r in rows})
    counts["total"] = sum(counts[s] for s in STATUSES)
    return counts
