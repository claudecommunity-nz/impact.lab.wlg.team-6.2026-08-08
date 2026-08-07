"""Report-status loader — Problem 02 (community <-> WCC two-way channel).

Implements the design in reference/report-status-design.md: append-only
signal-chaining, a reference code instead of auth, and a fixed one-tap
status vocabulary (Scheme A) kept deliberately separate from track4's
triage vocabulary (action/verify/awareness + priority 1-5) — same
classify-with-Claude trick, different scope, own words.

Status vocabulary: received -> reviewing -> responding -> resolved

DRAFT — shape only, not final. wcc_impact isn't available until hackathon
day, so if it can't be imported this falls back to an in-memory stub with
the same function signatures (per reference/platform_cheatsheet.md), purely
so the acknowledge/status-resolve logic below can be exercised locally
tonight. The stub is a crutch, not a target — once the real wcc_impact
exists tomorrow, this file should just work against it unmodified (the
`try: import wcc_impact` succeeds and the whole `except` branch never
runs). Swap MODULE_ID for the assigned id first.

Location: sits at repo root for now. Move into modules/<team-id>/loader.py
once the platform's actual project structure is confirmed at 09:00 (see
the design doc's "load-bearing assumption" section) — the golden path in
platform_cheatsheet.md implies that's where it ultimately belongs.

Unverified assumption baked into submit_report(): that publish_signal()
returns the created signal (so its "id" can be handed to the reporter as
their reference code). Not confirmed anywhere in the docs — check this
alongside the other open questions at 09:00.

Platform contract: main(), sample(), tick().
"""

from __future__ import annotations

import itertools
import sys
import time
import types
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import wcc_impact  # noqa: F401 - imported for its side effect: registers itself in sys.modules
    USING_STUB = False
except ImportError:
    USING_STUB = True

    _stub = types.ModuleType("wcc_impact")
    _signals: list[dict] = []
    _id_counter = itertools.count(1)

    def _publish_signal(**fields) -> dict:
        sig = {"id": str(next(_id_counter)), **fields}
        _signals.append(sig)
        return sig

    def _fetch_signals(limit: int = 50, signal_type: str | None = None,
                        module_id: str | None = None) -> list[dict]:
        rows = _signals
        if signal_type:
            rows = [s for s in rows if s.get("signal_type") == signal_type]
        if module_id:
            rows = [s for s in rows if s.get("module_id") == module_id]
        return list(rows[-limit:])

    def _register_module(**kwargs) -> None:
        pass

    def _run_every(seconds: int, callback) -> None:
        raise RuntimeError("stub: call tick() directly instead of run_every() for local testing")

    def _on_new_signals(callback, signal_type: str | None = None):
        raise RuntimeError("stub: real-time push can't be simulated locally")

    def _ask_claude(prompt: str, system: str | None = None, max_tokens: int = 256) -> str:
        raise RuntimeError("stub: no live Claude access without the real wcc_impact")

    def _geocode(place_name: str):
        return None  # unresolved locally; real SDK would geocode

    def _heartbeat() -> None:
        pass

    def _upload_file(path: str, name: str | None = None) -> str:
        raise RuntimeError("stub: no file upload without the real wcc_impact")

    _stub.publish_signal = _publish_signal
    _stub.fetch_signals = _fetch_signals
    _stub.register_module = _register_module
    _stub.run_every = _run_every
    _stub.on_new_signals = _on_new_signals
    _stub.ask_claude = _ask_claude
    _stub.geocode = _geocode
    _stub.heartbeat = _heartbeat
    _stub.upload_file = _upload_file
    _stub.SEVERITIES = frozenset({"minor", "moderate", "severe", "extreme", "unknown"})
    _stub.SOURCE_TYPES = frozenset({"official", "community", "media", "sensor"})
    sys.modules["wcc_impact"] = _stub

from wcc_impact import publish_signal, register_module, run_every, fetch_signals  # noqa: E402
from enrichment.signal_helpers import make_signal  # noqa: E402
from enrichment.feed_poller import idempotency_key  # noqa: E402

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

MODULE_ID = "team-CHANGEME"

RECEIVED = "received"
REVIEWING = "reviewing"
RESPONDING = "responding"
RESOLVED = "resolved"
STATUSES = (RECEIVED, REVIEWING, RESPONDING, RESOLVED)

_seen_reports: set[str] = set()

# ---------------------------------------------------------------------------
# the three pieces from the design doc
# ---------------------------------------------------------------------------


def submit_report(*, title: str, description: str, lat: float | None = None,
                   lng: float | None = None, place_name: str | None = None,
                   issue_type: str = "community-report",
                   media_urls: list[str] | None = None) -> dict:
    """What the React form calls (via publishSignal) when a resident submits
    a report. Kept here too so it can be exercised from Python without the
    UI. The returned signal's id is the reference code shown to the
    reporter — see design doc, "reference code, not a login".
    """
    sig = make_signal(
        module_id=MODULE_ID,
        title=title,
        signal_type=issue_type,
        source_type="community",
        description=description,
        lat=lat,
        lng=lng,
        place_name=place_name,
        media_urls=media_urls,
        idempotency_key=idempotency_key("report", uuid.uuid4().hex),
    )
    return publish_signal(**sig)


def set_status(original_id: str, status: str, note: str = "") -> dict:
    """The one-tap button WCC/field staff press. Publishes a NEW
    report-status signal chained to the original via raw.original_signal_id
    — never edits the original (see "why append-only" in the design doc).
    """
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    return publish_signal(**make_signal(
        module_id=MODULE_ID,
        title=f"Status: {status}",
        signal_type="report-status",
        source_type="official",
        description=note,
        raw={"original_signal_id": original_id, "status": status},
        idempotency_key=idempotency_key(
            "report-status", f"{original_id}:{status}:{time.time()}"),
    ))


def latest_status(original_id: str) -> dict | None:
    """What the reporter's "check my report" view resolves to. Filters
    every report-status signal down to this one reference code and returns
    the most recent. Mirrors the client-side filtering useSignals() would
    do in the React plugin (design doc's open question about raw
    filterability applies here too).
    """
    updates = [
        s for s in fetch_signals(limit=500, signal_type="report-status", module_id=MODULE_ID)
        if (s.get("raw") or {}).get("original_signal_id") == original_id
    ]
    return updates[-1] if updates else None


def _acknowledge_new_reports() -> None:
    """Auto-fires RECEIVED the instant a new community report lands — no
    human needed for this first step. Everything after RECEIVED is a human
    tapping a button via set_status().
    """
    reports = fetch_signals(limit=100, signal_type="community-report", module_id=MODULE_ID)
    for report in reports:
        rid = report.get("id")
        if not rid or rid in _seen_reports:
            continue
        _seen_reports.add(rid)
        set_status(rid, RECEIVED, note="Auto-acknowledged on receipt.")


# ---------------------------------------------------------------------------
# platform contract
# ---------------------------------------------------------------------------


def tick() -> None:
    _acknowledge_new_reports()


def sample() -> dict:
    return make_signal(
        module_id=MODULE_ID,
        title=f"Status: {RECEIVED}",
        signal_type="report-status",
        source_type="official",
        description="Sample status update",
        raw={"original_signal_id": "sample-1", "status": RECEIVED},
    )


def main() -> None:
    register_module(
        id=MODULE_ID,
        name="Report Status",
        icon="\U0001F4EC",
        description="Community report intake and one-tap status acknowledgment",
    )
    run_every(15, tick)


# ---------------------------------------------------------------------------
# local smoke test against the stub
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not USING_STUB:
        raise SystemExit("Real wcc_impact detected -- run via main(), not this smoke test.")

    print("Running against the in-memory stub (wcc_impact not available yet).\n")

    report = submit_report(
        title="Water coming over the road on Hutt Rd near Petone",
        description="Water coming over the road, getting worse",
        lat=-41.2270, lng=174.8712, place_name="Petone",
    )
    ref = report["id"]
    print(f"1. Reporter submits -> reference code: {ref}")

    tick()
    print(f"2. tick() auto-acknowledges -> status: {latest_status(ref)['raw']['status']}")

    set_status(ref, REVIEWING, note="Field crew dispatched to check.")
    print(f"3. Staff taps REVIEWING  -> status: {latest_status(ref)['raw']['status']}")

    set_status(ref, RESOLVED, note="Confirmed clear, road reopened.")
    print(f"4. Staff taps RESOLVED   -> status: {latest_status(ref)['raw']['status']}")

    print(f"\nFull status history for {ref}:")
    for s in fetch_signals(limit=500, signal_type="report-status", module_id=MODULE_ID):
        if s["raw"]["original_signal_id"] == ref:
            print(f"  - {s['raw']['status']:<10} {s.get('description', '')}")
