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

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
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

# Ops roles. duty acts on reports (status + verify); comms publishes council
# updates; admin does both and manages people. Only a human holding an admin
# key can create keys: there is deliberately NO automated path to issuing
# access (the prep kit's hard rule about automation and cards, kept).
OPS_ROLES = ("duty", "comms", "admin")

COMMS_TYPES = ("flood", "slips", "roads", "power", "rivers", "weather",
               "quakes", "help", "other")

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
                public_id      TEXT UNIQUE,
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
                current_status TEXT NOT NULL DEFAULT 'received',
                verified       INTEGER NOT NULL DEFAULT 0
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
            CREATE TABLE IF NOT EXISTS comms (
                public_id    TEXT PRIMARY KEY,
                created_at   TEXT NOT NULL,
                title        TEXT NOT NULL,
                body         TEXT NOT NULL,
                comms_type   TEXT NOT NULL DEFAULT 'other',
                lat          REAL,
                lng          REAL,
                place_name   TEXT,
                expires_at   TEXT,
                author       TEXT NOT NULL,
                withdrawn_at TEXT,
                withdrawn_by TEXT
            );
            CREATE TABLE IF NOT EXISTS ops_users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                role       TEXT NOT NULL,
                key_hash   TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                revoked_at TEXT,
                revoked_by TEXT
            );
            """
        )
        # v1 -> v2 migration for databases created before public_id/verified.
        cols = {r["name"] for r in db.execute("PRAGMA table_info(reports)")}
        if "public_id" not in cols:
            db.execute("ALTER TABLE reports ADD COLUMN public_id TEXT")
        if "verified" not in cols:
            db.execute("ALTER TABLE reports ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
        for row in db.execute("SELECT ref FROM reports WHERE public_id IS NULL").fetchall():
            db.execute("UPDATE reports SET public_id=? WHERE ref=?",
                       (_new_public_id(db), row["ref"]))
    init_offers()
    init_settings()


def _conn() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("store.init(db_path) has not been called")
    db = sqlite3.connect(_db_path, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_public_id(db: sqlite3.Connection) -> str:
    """Public map identifier. Deliberately a DIFFERENT namespace from the
    reference code: the ref is the reporter's credential and never appears
    on public surfaces; the public id carries no access at all.
    """
    for _ in range(50):
        pid = "K" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if db.execute("SELECT 1 FROM reports WHERE public_id=?", (pid,)).fetchone() is None:
            return pid
    raise RuntimeError("could not allocate a public id")


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
        public_id = _new_public_id(db)
        db.execute(
            "INSERT INTO reports (ref, public_id, created_at, category, description,"
            " lat, lng, place_name, reporter_role, contact, photo, current_status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?, 'received')",
            (ref, public_id, now, category, description, lat, lng, place_name,
             reporter_role, contact, photo),
        )
        db.execute(
            "INSERT INTO status_events (ref, status, note, actor, created_at)"
            " VALUES (?, 'received', 'Your report has reached the council.', 'system', ?)",
            (ref, now),
        )
    created = get_report(ref, private=True)
    if created is None:  # just inserted; only a torn DB could do this
        raise RuntimeError("row vanished after insert")
    return created


def add_status(ref: str, status: str, note: str = "", actor: str = "ops") -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    note = (note or "").strip()[:_NOTE_MAX]
    now = _now()
    with _write_lock, _conn() as db:
        row = db.execute("SELECT public_id FROM reports WHERE ref=?", (ref,)).fetchone()
        if row is None:
            raise KeyError(ref)
        db.execute(
            "INSERT INTO status_events (ref, status, note, actor, created_at)"
            " VALUES (?,?,?,?,?)",
            (ref, status, note, actor, now),
        )
        db.execute("UPDATE reports SET current_status=? WHERE ref=?", (status, ref))
    return {"ref": ref, "public_id": row["public_id"], "status": status,
            "note": note, "actor": actor, "created_at": now}


def verify_report(ref: str, note: str = "", actor: str = "ops") -> dict:
    """Mark a report council-verified. A verification is an append-only
    event like everything else: it records who and when, and it is what
    promotes the report's pin to 'official' on the public map. It does not
    touch the response status lifecycle.
    """
    note = (note or "").strip()[:_NOTE_MAX]
    now = _now()
    with _write_lock, _conn() as db:
        row = db.execute("SELECT public_id FROM reports WHERE ref=?", (ref,)).fetchone()
        if row is None:
            raise KeyError(ref)
        db.execute(
            "INSERT INTO status_events (ref, status, note, actor, created_at)"
            " VALUES (?, 'verified', ?, ?, ?)",
            (ref, note, actor, now),
        )
        db.execute("UPDATE reports SET verified=1 WHERE ref=?", (ref,))
    return {"ref": ref, "public_id": row["public_id"], "status": "verified",
            "note": note, "actor": actor, "created_at": now}


def set_hazard(ref: str, hazard: dict) -> None:
    with _write_lock, _conn() as db:
        db.execute("UPDATE reports SET hazard=? WHERE ref=?", (json.dumps(hazard), ref))


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def _row_to_report(row: sqlite3.Row, private: bool) -> dict:
    rep = {
        "public_id": row["public_id"],
        "created_at": row["created_at"],
        "category": row["category"],
        "lat": row["lat"],
        "lng": row["lng"],
        "place_name": row["place_name"],
        "reporter_role": row["reporter_role"],
        "status": row["current_status"],
        "verified": bool(row["verified"]),
    }
    if private:
        # The ref is the reporter's credential: it appears ONLY in private
        # views. Description, photo, contact and hazard context are
        # ops/reporter detail. The public view stays at category + place +
        # status so a reporter never accidentally publishes a phone number
        # they typed into the description.
        rep["ref"] = row["ref"]
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


def get_public_item(public_id: str) -> dict | None:
    """The public item page: what anyone may see about a report from its
    public id. Status/verified timeline with times only; ops notes are for
    the reporter, not the world.
    """
    with _conn() as db:
        row = db.execute("SELECT * FROM reports WHERE public_id=?", (public_id,)).fetchone()
        if row is None:
            return None
        item = _row_to_report(row, private=False)
        item["offer_count"] = offer_count(public_id)
        item["timeline"] = [
            {"status": r["status"], "created_at": r["created_at"]}
            for r in db.execute(
                "SELECT status, created_at FROM status_events"
                " WHERE ref=? ORDER BY id", (row["ref"],),
            )
        ]
    return item


def reporter_view(ref: str) -> dict | None:
    """What possession of the reference code entitles you to see: your own
    report in full (minus contact echo) and its complete status history.
    """
    rep = get_report(ref, private=True)
    if rep:
        rep.pop("contact", None)
        rep["offers"] = offers_for_item(rep["public_id"], include_contact=False)
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


# ---------------------------------------------------------------------------
# comms: council updates, first-class official items on the public canvas
# ---------------------------------------------------------------------------

_TITLE_MAX = 200
_BODY_MAX = 2000


def create_comms(*, title: str, body: str, comms_type: str = "other",
                 lat: float | None = None, lng: float | None = None,
                 place_name: str | None = None, expires_at: str | None = None,
                 author: str = "council") -> dict:
    title = (title or "").strip()
    body = (body or "").strip()
    if not 3 <= len(title) <= _TITLE_MAX:
        raise ValueError("title must be 3 to 200 characters")
    if not 3 <= len(body) <= _BODY_MAX:
        raise ValueError("body must be 3 to 2000 characters")
    if comms_type not in COMMS_TYPES:
        raise ValueError(f"comms_type must be one of {COMMS_TYPES}")
    if lat is not None:
        lat = float(lat)
        if not -90 <= lat <= 90:
            raise ValueError("lat out of range")
    if lng is not None:
        lng = float(lng)
        if not -180 <= lng <= 180:
            raise ValueError("lng out of range")
    place_name = (place_name or "").strip()[:_PLACE_MAX] or None
    now = _now()
    with _write_lock, _conn() as db:
        for _ in range(50):
            pid = "C" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
            if db.execute("SELECT 1 FROM comms WHERE public_id=?", (pid,)).fetchone() is None:
                break
        else:
            raise RuntimeError("could not allocate a comms id")
        db.execute(
            "INSERT INTO comms (public_id, created_at, title, body, comms_type,"
            " lat, lng, place_name, expires_at, author)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, now, title, body, comms_type, lat, lng, place_name,
             expires_at, author),
        )
    created = get_comms(pid)
    if created is None:  # just inserted; only a torn DB could do this
        raise RuntimeError("row vanished after insert")
    return created


def get_comms(public_id: str) -> dict | None:
    with _conn() as db:
        row = db.execute("SELECT * FROM comms WHERE public_id=?", (public_id,)).fetchone()
    return dict(row) if row else None


def list_comms(include_inactive: bool = False, limit: int = 200) -> list[dict]:
    """Public callers get active updates only; ops sees the full history
    (withdrawn posts stay on the record, never deleted).
    """
    q = "SELECT * FROM comms"
    args: list = []
    if not include_inactive:
        q += (" WHERE withdrawn_at IS NULL"
              " AND (expires_at IS NULL OR expires_at > ?)")
        args.append(_now())
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(min(int(limit), 1000))
    with _conn() as db:
        return [dict(r) for r in db.execute(q, args)]


def withdraw_comms(public_id: str, actor: str) -> dict:
    now = _now()
    with _write_lock, _conn() as db:
        row = db.execute("SELECT withdrawn_at FROM comms WHERE public_id=?",
                         (public_id,)).fetchone()
        if row is None:
            raise KeyError(public_id)
        if row["withdrawn_at"] is None:
            db.execute("UPDATE comms SET withdrawn_at=?, withdrawn_by=?"
                       " WHERE public_id=?", (now, actor, public_id))
    post = get_comms(public_id)
    if post is None:  # existence checked in this transaction
        raise RuntimeError("row vanished after update")
    return post


# ---------------------------------------------------------------------------
# ops users: named keys with roles (the Access tab)
# ---------------------------------------------------------------------------


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_ops_user(*, name: str, role: str, created_by: str) -> tuple[dict, str]:
    """Create a named ops user. Returns (user, key). The key is shown ONCE
    and only its hash is stored, same discipline as the prep kit's card
    codes: secrets are never persisted in the clear.
    """
    name = (name or "").strip()[:100]
    if len(name) < 2:
        raise ValueError("name must be at least 2 characters")
    if role not in OPS_ROLES:
        raise ValueError(f"role must be one of {OPS_ROLES}")
    key = "KOPS-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(16))
    now = _now()
    with _write_lock, _conn() as db:
        cur = db.execute(
            "INSERT INTO ops_users (name, role, key_hash, created_at, created_by)"
            " VALUES (?,?,?,?,?)",
            (name, role, _hash_key(key), now, created_by),
        )
        user_id = cur.lastrowid
    return ({"id": user_id, "name": name, "role": role, "created_at": now,
             "created_by": created_by, "revoked_at": None}, key)


def list_ops_users() -> list[dict]:
    with _conn() as db:
        return [
            {k: r[k] for k in ("id", "name", "role", "created_at",
                               "created_by", "revoked_at", "revoked_by")}
            for r in db.execute("SELECT * FROM ops_users ORDER BY id")
        ]


def revoke_ops_user(user_id: int, actor: str) -> dict:
    now = _now()
    with _write_lock, _conn() as db:
        row = db.execute("SELECT id, revoked_at FROM ops_users WHERE id=?",
                         (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        if row["revoked_at"] is None:
            db.execute("UPDATE ops_users SET revoked_at=?, revoked_by=? WHERE id=?",
                       (now, actor, user_id))
        user = db.execute("SELECT * FROM ops_users WHERE id=?", (user_id,)).fetchone()
    return {k: user[k] for k in ("id", "name", "role", "created_at",
                                 "created_by", "revoked_at", "revoked_by")}


def resolve_ops_key(key: str) -> dict | None:
    """Map a presented key to an active named user, or None."""
    if not key:
        return None
    with _conn() as db:
        row = db.execute(
            "SELECT id, name, role FROM ops_users"
            " WHERE key_hash=? AND revoked_at IS NULL",
            (_hash_key(key),),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# offers: neighbours responding to an item with help or skills.
# Council-mediated on purpose: content goes to ops and the reporter, the
# public sees only a count. Participation without an open board.
# ---------------------------------------------------------------------------

OFFER_KINDS = ("hands", "equipment", "transport", "shelter", "food-water",
               "check-in", "skills", "other")

_OFFER_MAX = 500


def init_offers() -> None:
    with _conn() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS offers (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                item_public_id TEXT NOT NULL,
                created_at     TEXT NOT NULL,
                kind           TEXT NOT NULL,
                text           TEXT NOT NULL,
                contact        TEXT,
                status         TEXT NOT NULL DEFAULT 'new'
            );
            CREATE INDEX IF NOT EXISTS idx_offers_item ON offers(item_public_id, id);
            """
        )


def create_offer(*, item_public_id: str, kind: str, text: str,
                 contact: str | None = None) -> dict:
    if kind not in OFFER_KINDS:
        raise ValueError(f"kind must be one of {OFFER_KINDS}")
    text = (text or "").strip()
    if not 3 <= len(text) <= _OFFER_MAX:
        raise ValueError("offer text must be 3 to 500 characters")
    contact = (contact or "").strip()[:_CONTACT_MAX] or None
    now = _now()
    with _write_lock, _conn() as db:
        row = db.execute("SELECT ref FROM reports WHERE public_id=?",
                         (item_public_id,)).fetchone()
        if row is None:
            raise KeyError(item_public_id)
        cur = db.execute(
            "INSERT INTO offers (item_public_id, created_at, kind, text, contact)"
            " VALUES (?,?,?,?,?)",
            (item_public_id, now, kind, text, contact),
        )
    return {"id": cur.lastrowid, "item_public_id": item_public_id,
            "created_at": now, "kind": kind, "text": text}


def offers_for_item(item_public_id: str, include_contact: bool) -> list[dict]:
    """Ops sees contact details; the reporter sees the offer without them."""
    fields = ("id", "created_at", "kind", "text", "status") + \
             (("contact",) if include_contact else ())
    with _conn() as db:
        return [{k: r[k] for k in fields}
                for r in db.execute(
                    "SELECT * FROM offers WHERE item_public_id=? ORDER BY id",
                    (item_public_id,))]


def offer_count(item_public_id: str) -> int:
    with _conn() as db:
        return db.execute("SELECT COUNT(*) AS n FROM offers WHERE item_public_id=?",
                          (item_public_id,)).fetchone()["n"]


# ---------------------------------------------------------------------------
# platform mode: normal or emergency. The switch is council's alone; in
# emergency the public canvas states plainly that council is coordinating.
# ---------------------------------------------------------------------------


def init_settings() -> None:
    with _conn() as db:
        db.execute("CREATE TABLE IF NOT EXISTS settings ("
                   "key TEXT PRIMARY KEY, value TEXT NOT NULL,"
                   "updated_at TEXT, updated_by TEXT)")


def get_mode() -> str:
    with _conn() as db:
        row = db.execute("SELECT value FROM settings WHERE key='mode'").fetchone()
    return row["value"] if row else "normal"


def set_mode(mode: str, actor: str) -> str:
    if mode not in ("normal", "emergency"):
        raise ValueError("mode must be normal or emergency")
    with _write_lock, _conn() as db:
        db.execute("INSERT INTO settings (key, value, updated_at, updated_by)"
                   " VALUES ('mode', ?, ?, ?)"
                   " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                   " updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                   (mode, _now(), actor))
    return mode


# ---------------------------------------------------------------------------
# retention: the privacy review's schedule, enforced (IPP9)
# ---------------------------------------------------------------------------


def apply_retention(*, contact_days: int = 90, photo_days: int = 365,
                    uploads_dir: Path | None = None) -> dict:
    """Purge what the privacy review says must not live forever: contact
    details 90 days after a report resolves (offers age from creation),
    photos after 12 months. Anonymised report rows stay for planning.
    Returns counts so the run is observable.
    """
    now = datetime.now(timezone.utc)
    contact_cutoff = (now - timedelta(days=contact_days)).isoformat(timespec="seconds")
    photo_cutoff = (now - timedelta(days=photo_days)).isoformat(timespec="seconds")
    removed = {"contacts": 0, "offer_contacts": 0, "photos": 0}
    with _write_lock, _conn() as db:
        cur = db.execute(
            "UPDATE reports SET contact=NULL WHERE contact IS NOT NULL AND ref IN ("
            " SELECT ref FROM status_events WHERE status='resolved'"
            " GROUP BY ref HAVING MAX(created_at) < ?)",
            (contact_cutoff,))
        removed["contacts"] = cur.rowcount
        cur = db.execute(
            "UPDATE offers SET contact=NULL"
            " WHERE contact IS NOT NULL AND created_at < ?",
            (contact_cutoff,))
        removed["offer_contacts"] = cur.rowcount
        rows = db.execute(
            "SELECT ref, photo FROM reports"
            " WHERE photo IS NOT NULL AND created_at < ?",
            (photo_cutoff,)).fetchall()
        for r in rows:
            if uploads_dir is not None:
                try:
                    (Path(uploads_dir) / r["photo"]).unlink(missing_ok=True)
                except OSError:
                    pass  # file already gone; still clear the reference
            db.execute("UPDATE reports SET photo=NULL WHERE ref=?", (r["ref"],))
            removed["photos"] += 1
    return removed
