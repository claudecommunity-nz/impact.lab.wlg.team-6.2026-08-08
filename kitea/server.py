"""HTTP server: routes, SSE push, uploads, and the ops boundary.

Stdlib only (http.server + threads). Two trust levels:

* Public — submit a report, view your own report by reference code,
  read the sanitised public report list, read proxied agency feeds.
* Ops — everything above plus full report detail (description, photo,
  contact, hazard context) and status changes. Gated by a single access
  key supplied via the X-Kitea-Key header (or ?key= for EventSource,
  which cannot set headers). The key comes from the KITEA_OPS_KEY env
  var; when unset a random one is generated and printed at startup so
  there is no hardcoded secret and no open-by-default ops surface.

Live updates are Server-Sent Events, not polling: the reporter's status
page and the ops dashboard each hold one long GET and receive events the
moment they happen — the "delivery tracker, not a support ticket" design.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import queue
import re
import secrets
import threading
import time
import urllib.parse
import uuid
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, feeds, store

WEB_DIR = Path(__file__).parent / "web"
DATA_DIR = Path(os.environ.get("KITEA_DATA_DIR", "data"))
UPLOAD_DIR = DATA_DIR / "uploads"

MAP_CENTER = {"lat": -41.2865, "lng": 174.7762, "zoom": 11.5}

_MAX_BODY = 8 * 1024 * 1024          # request body cap (photo travels base64)
_MAX_PHOTO = 5 * 1024 * 1024         # decoded photo cap
_RATE_LIMIT = 15                     # report submissions per IP per hour

# Magic-byte sniffing: the client's declared content type is hostile input.
_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"RIFF", ".webp"),  # RIFF....WEBP checked further below
)

_REF_RE = re.compile(r"^[A-Z]{2,5}-[A-Z2-9]{3,10}$")
_LOOKUP_MISS_LIMIT = 30              # failed ref lookups per IP per hour

OPS_KEY = os.environ.get("KITEA_OPS_KEY") or secrets.token_urlsafe(9)

_submits: dict[str, deque] = defaultdict(deque)
_submits_lock = threading.Lock()
_lookup_misses: dict[str, deque] = defaultdict(deque)
_misses_lock = threading.Lock()


def _miss_window(ip: str) -> deque:
    now = time.monotonic()
    window = _lookup_misses[ip]
    while window and now - window[0] > 3600:
        window.popleft()
    return window


# ---------------------------------------------------------------------------
# SSE hub
# ---------------------------------------------------------------------------


class Hub:
    """In-process pub/sub. Each SSE connection owns a queue; publishing
    fans out to every queue whose filter matches.
    """

    def __init__(self) -> None:
        self._subs: list[tuple[queue.Queue, str | None, bool]] = []
        self._lock = threading.Lock()

    def subscribe(self, ref: str | None, ops: bool) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subs.append((q, ref, ops))
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs = [s for s in self._subs if s[0] is not q]

    def publish(self, event_type: str, payload: dict, *,
                ref: str | None = None, ops_only: bool = False) -> None:
        with self._lock:
            subs = list(self._subs)
        for q, sub_ref, sub_ops in subs:
            if ops_only and not sub_ops:
                continue
            if sub_ref is not None and ref != sub_ref:
                continue
            try:
                q.put_nowait((event_type, payload))
            except queue.Full:
                pass  # slow consumer; it will resync on reconnect


HUB = Hub()


# ---------------------------------------------------------------------------
# background hazard enrichment
# ---------------------------------------------------------------------------


def _nearest_curated_gauge(lat: float, lng: float) -> dict | None:
    try:
        items = [i for i in feeds.gauges().get("items", [])
                 if i.get("lat") is not None and i.get("value") is not None]
    except Exception:
        return None
    if not items:
        return None
    best = min(items, key=lambda i: (i["lat"] - lat) ** 2 + (i["lng"] - lng) ** 2)
    return {k: best.get(k) for k in
            ("site", "measurement", "value", "units", "time", "trend", "fresh",
             "lat", "lng")}


def _enrich(ref: str, lat: float, lng: float) -> None:
    """Fill in the hazard context for a report after it is stored. Runs in
    a daemon thread: enrichment is several GIS round-trips and must never
    hold up the reporter's submit.
    """
    try:
        from enrichment.hazard_context import hazard_context
        ctx = hazard_context(lat, lng)
        # hazard_context scans every Hilltop site and tends to land on a
        # groundwater bore (observed live: "R27/7154"); the curated live
        # gauges we already poll are the meaningful neighbours.
        ctx["nearest_gauge"] = _nearest_curated_gauge(lat, lng)
    except Exception as exc:
        ctx = {"error": f"enrichment failed: {exc}"}
    try:
        store.set_hazard(ref, ctx)
    except Exception:
        return
    HUB.publish("report-updated", {"ref": ref}, ref=ref)
    HUB.publish("report-updated", {"ref": ref}, ops_only=True)


# ---------------------------------------------------------------------------
# grouping (ops view)
# ---------------------------------------------------------------------------


def _group_reports(reports: list[dict]) -> None:
    """Tag unresolved reports of the same category within ~400 m with a
    shared group id, so the ops queue reads "5 reports, 2 situations".
    Naive O(n²) pairing is fine at prototype scale.
    """
    located = [r for r in reports
               if r["lat"] is not None and r["lng"] is not None
               and r["status"] != "resolved"]
    group_of: dict[str, int] = {}
    next_group = 1
    for i, a in enumerate(located):
        for b in located[:i]:
            if a["category"] != b["category"]:
                continue
            dlat = (a["lat"] - b["lat"]) * 111_000
            dlng = (a["lng"] - b["lng"]) * 83_000  # cos(-41°) ≈ 0.75
            if dlat * dlat + dlng * dlng <= 400 ** 2:
                gid = group_of.get(b["ref"])
                if gid is None:
                    gid = next_group
                    next_group += 1
                    group_of[b["ref"]] = gid
                group_of[a["ref"]] = gid
                break
    for r in reports:
        r["group"] = group_of.get(r["ref"])


# ---------------------------------------------------------------------------
# request handler
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"Kitea/{__version__}"

    # -- helpers ------------------------------------------------------------

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self._common_headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _common_headers(self, ctype: str, length: int | None) -> None:
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https://tile.openstreetmap.org; "
            "worker-src blob:; frame-ancestors 'none'")

    def _error(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status)

    def _client_ip(self) -> str:
        return self.client_address[0]

    def _is_ops(self, query: dict) -> bool:
        header = self.headers.get("X-Kitea-Key", "")
        candidate = header or (query.get("key") or [""])[0]
        return secrets.compare_digest(candidate, OPS_KEY)

    def log_message(self, fmt, *args):  # quieter default log, no query strings
        path = self.path.split("?")[0]
        print(f"{self.log_date_time_string()} {self.command} {path} "
              f"{args[-1] if args else ''}")

    # -- routing ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler contract)
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path == "/":
                return self._send_file(WEB_DIR / "index.html")
            if path == "/ops":
                return self._send_file(WEB_DIR / "ops.html")
            if path.startswith("/static/"):
                return self._send_static(WEB_DIR, path[len("/static/"):])
            if path.startswith("/uploads/"):
                return self._send_static(UPLOAD_DIR, path[len("/uploads/"):])

            if path == "/api/meta":
                return self._send_json({
                    "version": __version__,
                    "categories": store.CATEGORIES,
                    "statuses": store.STATUSES,
                    "reporter_roles": store.REPORTER_ROLES,
                    "prefix": store.CODE_PREFIX,
                    "map_center": MAP_CENTER,
                })
            if path == "/api/reports":
                limit = int((query.get("limit") or ["500"])[0])
                return self._send_json(
                    {"reports": store.list_reports(limit=limit, private=False)})
            m = re.fullmatch(r"/api/reports/([A-Z0-9-]{4,16})", path)
            if m:
                # The ref code is the credential, so failed lookups are
                # guessing attempts: throttle them per client.
                ip = self._client_ip()
                with _misses_lock:
                    if len(_miss_window(ip)) >= _LOOKUP_MISS_LIMIT:
                        return self._error(429, "too many failed lookups; "
                                                "please wait before retrying")
                rep = store.reporter_view(m.group(1))
                if rep is None:
                    with _misses_lock:
                        _miss_window(ip).append(time.monotonic())
                    return self._error(404, "no report with that reference code")
                return self._send_json(rep)
            m = re.fullmatch(r"/api/feeds/(\w{1,32})", path)
            if m:
                envelope = feeds.get(m.group(1))
                if envelope is None:
                    return self._error(404, "unknown feed")
                return self._send_json(envelope)
            if path == "/api/hazard":
                return self._hazard(query)
            if path == "/api/stream":
                ref = (query.get("ref") or [None])[0]
                return self._stream(ref=ref, ops=False)

            if path == "/api/ops/reports":
                if not self._is_ops(query):
                    return self._error(401, "ops key required")
                reports = store.list_reports(limit=1000, private=True)
                _group_reports(reports)
                return self._send_json({"reports": reports, "stats": store.stats()})
            m = re.fullmatch(r"/api/ops/reports/([A-Z0-9-]{4,16})", path)
            if m:
                if not self._is_ops(query):
                    return self._error(401, "ops key required")
                rep = store.get_report(m.group(1), private=True)
                if rep is None:
                    return self._error(404, "no report with that reference code")
                return self._send_json(rep)
            if path == "/api/ops/stream":
                if not self._is_ops(query):
                    return self._error(401, "ops key required")
                return self._stream(ref=None, ops=True)

            return self._error(404, "not found")
        except BrokenPipeError:
            pass
        except Exception as exc:
            try:
                self._error(500, f"internal error: {type(exc).__name__}")
            except Exception:
                pass
            print(f"ERROR {self.path}: {exc!r}")

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            body = self._read_json_body()
            if body is None:
                return

            if path == "/api/reports":
                return self._create_report(body)
            m = re.fullmatch(r"/api/reports/([A-Z0-9-]{4,16})/status", path)
            if m:
                if not self._is_ops(query):
                    return self._error(401, "ops key required")
                return self._set_status(m.group(1), body)
            return self._error(404, "not found")
        except BrokenPipeError:
            pass
        except Exception as exc:
            try:
                self._error(500, f"internal error: {type(exc).__name__}")
            except Exception:
                pass
            print(f"ERROR {self.path}: {exc!r}")

    # -- endpoints ----------------------------------------------------------

    def _read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._error(400, "a JSON body is required")
            return None
        if length > _MAX_BODY:
            self._error(413, "request too large")
            return None
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._error(400, "body is not valid JSON")
            return None
        if not isinstance(body, dict):
            self._error(400, "body must be a JSON object")
            return None
        return body

    def _rate_limited(self) -> bool:
        ip = self._client_ip()
        now = time.monotonic()
        with _submits_lock:
            window = _submits[ip]
            while window and now - window[0] > 3600:
                window.popleft()
            if len(window) >= _RATE_LIMIT:
                return True
            window.append(now)
        return False

    def _create_report(self, body: dict) -> None:
        if self._rate_limited():
            return self._error(429, "too many reports from this connection; "
                                    "please wait before submitting more")
        photo_path = None
        photo_b64 = body.get("photo_b64")
        if photo_b64:
            photo_path = self._save_photo(photo_b64)
            if photo_path is None:
                return  # _save_photo already answered
        try:
            report = store.create_report(
                category=str(body.get("category", "")),
                description=str(body.get("description", "")),
                lat=body.get("lat"),
                lng=body.get("lng"),
                place_name=body.get("place_name"),
                reporter_role=str(body.get("reporter_role") or "resident"),
                contact=body.get("contact"),
                photo=photo_path,
            )
        except (ValueError, TypeError) as exc:
            return self._error(400, str(exc))

        if report["lat"] is not None and report["lng"] is not None:
            threading.Thread(
                target=_enrich,
                args=(report["ref"], report["lat"], report["lng"]),
                daemon=True,
            ).start()

        public = {k: report[k] for k in
                  ("ref", "created_at", "category", "lat", "lng",
                   "place_name", "reporter_role", "status")}
        HUB.publish("report", public)
        self._send_json(report, status=201)

    def _save_photo(self, photo_b64: str) -> str | None:
        try:
            blob = base64.b64decode(photo_b64, validate=True)
        except Exception:
            self._error(400, "photo_b64 is not valid base64")
            return None
        if len(blob) > _MAX_PHOTO:
            self._error(413, "photo larger than 5 MB")
            return None
        ext = None
        for magic, magic_ext in _IMAGE_MAGIC:
            if blob.startswith(magic):
                if magic == b"RIFF" and blob[8:12] != b"WEBP":
                    continue
                ext = magic_ext
                break
        if ext is None:
            self._error(400, "photo must be a JPEG, PNG or WebP image")
            return None
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / name).write_bytes(blob)
        return name

    def _set_status(self, ref: str, body: dict) -> None:
        try:
            event = store.add_status(
                ref,
                str(body.get("status", "")),
                note=str(body.get("note") or ""),
                actor="ops",
            )
        except KeyError:
            return self._error(404, "no report with that reference code")
        except ValueError as exc:
            return self._error(400, str(exc))
        HUB.publish("status", event, ref=ref)
        HUB.publish("status", event, ops_only=True)
        self._send_json(event, status=201)

    _hazard_cache: dict[tuple, tuple[float, dict]] = {}
    _hazard_lock = threading.Lock()

    def _hazard(self, query: dict) -> None:
        try:
            lat = float((query.get("lat") or [""])[0])
            lng = float((query.get("lng") or [""])[0])
        except ValueError:
            return self._error(400, "lat and lng are required numbers")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return self._error(400, "lat/lng out of range")
        key = (round(lat, 4), round(lng, 4))
        with self._hazard_lock:
            hit = self._hazard_cache.get(key)
            if hit and time.monotonic() - hit[0] < 600:
                return self._send_json(hit[1])
        try:
            from enrichment.hazard_context import hazard_context
            ctx = hazard_context(lat, lng)
            ctx["nearest_gauge"] = _nearest_curated_gauge(lat, lng)
        except Exception as exc:
            return self._error(502, f"hazard lookup failed: {type(exc).__name__}")
        with self._hazard_lock:
            self._hazard_cache[key] = (time.monotonic(), ctx)
        self._send_json(ctx)

    # -- SSE ----------------------------------------------------------------

    def _stream(self, ref: str | None, ops: bool) -> None:
        if ref is not None and not _REF_RE.fullmatch(ref):
            return self._error(400, "malformed reference code")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        q = HUB.subscribe(ref, ops)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event_type, payload = q.get(timeout=20)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                data = json.dumps(payload)
                self.wfile.write(
                    f"event: {event_type}\ndata: {data}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            HUB.unsubscribe(q)

    # -- static files ---------------------------------------------------------

    def _send_static(self, base: Path, rel: str) -> None:
        target = (base / rel).resolve()
        try:
            # relative_to enforces true containment; a string-prefix check
            # would also pass sibling dirs that share a name prefix.
            target.relative_to(base.resolve())
        except ValueError:
            return self._error(403, "forbidden")
        self._send_file(target)

    def _send_file(self, target: Path) -> None:
        if not target.is_file():
            return self._error(404, "not found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self._common_headers(ctype, len(body))
        if target.suffix in (".js", ".css", ".jpg", ".png", ".webp"):
            self.send_header("Cache-Control", "max-age=300")
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8146) -> None:
    store.init(DATA_DIR / "kitea.db")
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    if not os.environ.get("KITEA_OPS_KEY"):
        print(f"KITEA_OPS_KEY not set; generated ops key for this run: {OPS_KEY}")
    print(f"Kitea {__version__} — residents: http://{host}:{port}/   "
          f"ops: http://{host}:{port}/ops")
    server.serve_forever()
