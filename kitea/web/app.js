/* Kitea v2 public canvas: one map, lenses, provenance pins + the private
   tracking view. All user-sourced strings render via textContent, never
   innerHTML. Provenance model:
     official  = agency feeds + council-verified reports
     community = reports not (yet) verified
     mine      = reports whose reference codes live in this browser
   The reference code (WGN-…) is the reporter's credential and never
   appears on public surfaces; the map speaks public ids (K…) only. */

"use strict";

const $ = (id) => document.getElementById(id);

const CATEGORY_META = {
  "flooding":        { icon: "🌊", label: "Flooding" },
  "landslip":        { icon: "⛰️", label: "Slip / landslide" },
  "road-damage":     { icon: "🛣️", label: "Road damage" },
  "tree-down":       { icon: "🌲", label: "Tree down" },
  "power-lines":     { icon: "⚡", label: "Power lines" },
  "water-supply":    { icon: "🚰", label: "Water supply" },
  "building-damage": { icon: "🏠", label: "Building damage" },
  "blocked-drain":   { icon: "🕳️", label: "Blocked drain" },
  "welfare-need":    { icon: "🤝", label: "Someone needs help" },
  "other":           { icon: "📝", label: "Something else" },
};

const STATUS_COPY = {
  received:   { title: "Received",   blurb: "Your report has reached the council." },
  reviewing:  { title: "Reviewing",  blurb: "Someone is looking at your report." },
  responding: { title: "Responding", blurb: "The council is acting on it." },
  resolved:   { title: "Resolved",   blurb: "This has been dealt with." },
};
const LIFECYCLE = ["received", "reviewing", "responding", "resolved"];
const STATUS_COLOR = { received: "#5B6B7A", reviewing: "#B57A00",
                       responding: "#1D5FBF", resolved: "#1A7A3C" };

// type chips: one vocabulary across reports and agency feeds
const TYPES = [
  ["flood",   "🌊 Flooding & drains"],
  ["slips",   "⛰️ Slips"],
  ["roads",   "🛣️ Roads"],
  ["power",   "⚡ Power"],
  ["rivers",  "🌧️ Rivers & rain"],
  ["weather", "🌬️ Weather"],
  ["quakes",  "🌐 Quakes"],
  ["help",    "🤝 Help & hubs"],
  ["other",   "📝 Other"],
];
const CATEGORY_TYPE = {
  "flooding": "flood", "blocked-drain": "flood", "landslip": "slips",
  "road-damage": "roads", "tree-down": "roads", "power-lines": "power",
  "welfare-need": "help", "water-supply": "other", "building-damage": "other",
  "other": "other",
};

const nzTime = new Intl.DateTimeFormat("en-NZ", {
  timeZone: "Pacific/Auckland", weekday: "short",
  hour: "numeric", minute: "2-digit", day: "numeric", month: "short",
});
function fmtTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : nzTime.format(d);
}
function agoText(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}
async function getJSON(url) {
  const r = await fetch(url);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `request failed (${r.status})`);
  return body;
}
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `request failed (${r.status})`);
  return data;
}

const OSM_STYLE = {
  version: 8,
  sources: { osm: { type: "raster",
    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
    tileSize: 256, attribution: "© OpenStreetMap contributors" } },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

function myReports() {
  try { return JSON.parse(localStorage.getItem("kitea-mine") || "[]"); }
  catch { return []; }
}
function myPublicIds() {
  return new Set(myReports().map(m => m.public_id).filter(Boolean));
}

/* ================================================================ router */

// router runs at the end of the file: const declarations
// below would otherwise be in their temporal dead zone when it fires.
const params = new URLSearchParams(location.search);
const trackRef = (params.get("ref") || "").trim().toUpperCase();

/* ================================================================ canvas */

const state = {
  lens: "everything",            // everything | official | community | mine
  types: new Set(TYPES.map(t => t[0])),
  reports: [],
  feeds: {},
  selected: null,                // {kind:"report", public_id} | {kind:"feed", ...}
  placing: false,
};

let map, mapReady = false;
const pinById = new Map();       // public_id -> Marker
const feedMarkers = [];          // all agency markers, tagged with type

function initCanvas() {
  buildLenses();
  buildTypeChips();

  map = new maplibregl.Map({
    container: "canvas-map", style: OSM_STYLE,
    center: [174.82, -41.27], zoom: 10.6,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  map.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }));
  map.on("load", () => {
    mapReady = true;
    map.addSource("delays", { type: "geojson",
      data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "delays-line", type: "line", source: "delays",
      paint: { "line-color": "#C2410C", "line-width": 3.5, "line-opacity": 0.65 } });
    map.addSource("weather", { type: "geojson",
      data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "weather-fill", type: "fill", source: "weather",
      paint: { "fill-color": ["match", ["get", "severity"],
        "extreme", "#B3261E", "severe", "#C2410C", "#B57A00"],
        "fill-opacity": 0.13 } }, "delays-line");
    map.addLayer({ id: "weather-outline", type: "line", source: "weather",
      paint: { "line-color": ["match", ["get", "severity"],
        "extreme", "#B3261E", "severe", "#C2410C", "#B57A00"],
        "line-width": 1.5, "line-dasharray": [3, 2] } });
    map.on("click", "delays-line", (e) => {
      if (state.placing) return;
      const p = e.features[0].properties;
      selectFeedItem({ type: "roads", title: `${p.eventType}: ${p.location}`,
        sub: p.description || "", attribution: "NZ Transport Agency Waka Kotahi",
        when: p.updated });
    });
    applyVisibility();
  });
  map.on("click", (e) => {
    if (!state.placing) return;
    exitPlacing();
    openDrawer({ lat: e.lngLat.lat, lng: e.lngLat.lng });
  });

  buildDrawer();
  $("btn-report-fab").addEventListener("click", () => {
    state.placing = true;
    $("placing-banner").classList.remove("hidden");
    $("btn-report-fab").classList.add("hidden");
    map.getCanvas().style.cursor = "crosshair";
  });
  $("placing-banner").addEventListener("click", () => { exitPlacing(); openDrawer(null); });
  $("panel-back").addEventListener("click", () => { state.selected = null;
    history.replaceState(null, "", "/"); renderPanel(); });

  loadReports().then(() => {
    const deep = params.get("item");
    if (deep) selectReportItem(deep, false);
  });
  refreshFeeds();
  setInterval(refreshFeeds, 150_000);
  setInterval(renderPanel, 60_000);
  openCanvasStream();
}

function exitPlacing() {
  state.placing = false;
  $("placing-banner").classList.add("hidden");
  $("btn-report-fab").classList.remove("hidden");
  if (map) map.getCanvas().style.cursor = "";
}

/* ---- lenses & chips ---------------------------------------------------- */

const LENSES = [
  ["everything", "Everything"],
  ["official", "Official"],
  ["community", "Community"],
  ["mine", "Mine"],
];

function buildLenses() {
  const box = $("lenses");
  for (const [value, label] of LENSES) {
    const b = document.createElement("button");
    b.className = "lens";
    b.textContent = label;
    b.setAttribute("aria-pressed", String(value === state.lens));
    b.addEventListener("click", () => {
      state.lens = value;
      box.querySelectorAll(".lens").forEach(x => x.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      state.selected = null;
      applyVisibility();
      renderPanel();
    });
    box.append(b);
  }
}

function buildTypeChips() {
  const bar = $("chipsbar");
  for (const [value, label] of TYPES) {
    const b = document.createElement("button");
    b.className = "tchip";
    b.textContent = label;
    b.setAttribute("aria-pressed", "true");
    b.addEventListener("click", () => {
      if (state.types.has(value)) state.types.delete(value);
      else state.types.add(value);
      b.setAttribute("aria-pressed", String(state.types.has(value)));
      applyVisibility();
      renderPanel();
    });
    bar.append(b);
  }
}

/* ---- provenance -------------------------------------------------------- */

function provenanceOf(report) {
  if (myPublicIds().has(report.public_id)) return "mine";
  return report.verified ? "official" : "community";
}
function inLens(prov) {
  if (state.lens === "everything") return true;
  if (state.lens === "official") return prov === "official";
  if (state.lens === "community") return prov === "community" || prov === "mine";
  return prov === "mine";
}
function agencyVisible() {
  return state.lens === "everything" || state.lens === "official";
}

/* ---- data -------------------------------------------------------------- */

async function loadReports() {
  try {
    const data = await getJSON("/api/reports?limit=300");
    state.reports = data.reports;
  } catch { state.reports = []; }
  renderReportPins();
  renderPanel();
}

const FEED_IDS = ["gauges", "delays", "outages", "weather", "quakes", "hubs"];

async function refreshFeeds() {
  await Promise.allSettled(FEED_IDS.map(async (id) => {
    state.feeds[id] = await getJSON(`/api/feeds/${id}`);
  }));
  renderFeedMarkers();
  renderPanel();
}

/* ---- SSE --------------------------------------------------------------- */

function openCanvasStream() {
  const tag = $("live-tag"), text = $("live-tag-text");
  const es = new EventSource("/api/stream");
  es.onopen = () => { tag.classList.add("connected"); text.textContent = "live"; };
  es.onerror = () => { tag.classList.remove("connected"); text.textContent = "reconnecting…"; };
  es.addEventListener("report", (e) => {
    try { state.reports.unshift(JSON.parse(e.data)); } catch { return; }
    renderReportPins();
    renderPanel();
  });
  es.addEventListener("item-updated", (e) => {
    let up; try { up = JSON.parse(e.data); } catch { return; }
    const rep = state.reports.find(r => r.public_id === up.public_id);
    if (rep) {
      if (up.status) rep.status = up.status;
      if (up.verified) rep.verified = true;
    }
    renderReportPins();
    if (state.selected && state.selected.kind === "report" &&
        state.selected.public_id === up.public_id) {
      selectReportItem(up.public_id, false);
    } else {
      renderPanel();
    }
  });
}

/* ---- map pins ----------------------------------------------------------- */

function renderReportPins() {
  for (const m of pinById.values()) m.remove();
  pinById.clear();
  for (const r of state.reports) {
    if (r.lat == null || r.lng == null) continue;
    const prov = provenanceOf(r);
    const el = document.createElement("div");
    el.className = "cpin" + (r.verified ? " verified" : "") +
                   (prov === "mine" ? " mine" : "");
    el.style.background = STATUS_COLOR[r.status] || "#5B6B7A";
    const meta = CATEGORY_META[r.category] || { label: r.category };
    el.title = `${meta.label}${r.place_name ? " · " + r.place_name : ""}` +
               (r.verified ? " · council-verified" : " · community report");
    el.style.display = inLens(prov) &&
      state.types.has(CATEGORY_TYPE[r.category] || "other") ? "" : "none";
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.placing) return;
      selectReportItem(r.public_id, true);
    });
    pinById.set(r.public_id,
      new maplibregl.Marker({ element: el }).setLngLat([r.lng, r.lat]).addTo(map));
  }
}

function clearFeedMarkers() {
  for (const { marker } of feedMarkers) marker.remove();
  feedMarkers.length = 0;
}

function addFeedMarker(type, lat, lng, el, onClick) {
  if (lat == null || lng == null || !map) return;
  el.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!state.placing) onClick();
  });
  const marker = new maplibregl.Marker({ element: el })
    .setLngLat([lng, lat]).addTo(map);
  feedMarkers.push({ type, marker, el });
}

function renderFeedMarkers() {
  if (!map) return;
  clearFeedMarkers();

  for (const g of ((state.feeds.gauges || {}).items || [])) {
    if (g.error || g.lat == null) continue;
    const el = document.createElement("div");
    el.className = "cpin-gauge" + (g.trend === "rising" ? " rising" : "");
    const v = typeof g.value === "number"
      ? (g.value >= 100 ? Math.round(g.value) : g.value.toFixed(1)) : g.value;
    el.textContent = g.kind === "rain" ? `☔ ${g.recent_total ?? v}` :
      `${v}${g.trend === "rising" ? "▲" : g.trend === "falling" ? "▼" : ""}`;
    addFeedMarker("rivers", g.lat, g.lng, el, () => selectFeedItem({
      type: "rivers", title: g.site,
      sub: `${g.measurement}: ${g.value} ${g.units}` +
           (g.trend ? ` · ${g.trend}` : "") + (g.fresh ? "" : " · reading is old"),
      attribution: "Greater Wellington Regional Council", when: null }));
  }

  for (const hub of ((state.feeds.hubs || {}).items || [])) {
    const el = document.createElement("div");
    el.className = "cpin-hub";
    el.textContent = "🏫";
    el.title = hub.name || "Community Emergency Hub";
    addFeedMarker("help", hub.lat, hub.lng, el, () => selectFeedItem({
      type: "help", title: hub.name || "Community Emergency Hub",
      sub: (hub.address || "") + " · In a major emergency, hubs are where neighbours gather to help each other.",
      attribution: "WREMO", when: null }));
  }

  for (const o of ((state.feeds.outages || {}).items || [])) {
    const el = document.createElement("div");
    el.className = "cpin-outage";
    el.textContent = "⚡";
    addFeedMarker("power", o.lat, o.lng, el, () => selectFeedItem({
      type: "power", title: `Power outage: ${o.location || "unnamed"}`,
      sub: `${o.affected || "?"} customers · ${o.status || ""}`,
      attribution: "NEMA", when: o.start }));
  }

  for (const q of ((state.feeds.quakes || {}).items || [])) {
    const el = document.createElement("div");
    el.className = "cpin-quake";
    const size = Math.max(12, Math.min(36, q.magnitude * 7));
    el.style.width = el.style.height = `${size}px`;
    addFeedMarker("quakes", q.lat, q.lng, el, () => selectFeedItem({
      type: "quakes", title: `M${q.magnitude} ${q.locality}`,
      sub: `${q.depth_km} km deep · felt intensity ${q.mmi}`,
      attribution: "GeoNet (GNS Science)", when: q.time, link: q.link }));
  }

  if (mapReady) {
    const d = state.feeds.delays;
    if (d && d.geojson) map.getSource("delays").setData(d.geojson);
    const w = state.feeds.weather;
    if (w) map.getSource("weather").setData({
      type: "FeatureCollection",
      features: (w.items || []).filter(i => i.polygon).map(i => ({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: i.polygon },
        properties: { severity: i.severity, title: i.title },
      })),
    });
  }
  applyVisibility();
}

function applyVisibility() {
  const showAgency = agencyVisible();
  for (const { type, el } of feedMarkers) {
    el.style.display = showAgency && state.types.has(type) ? "" : "none";
  }
  for (const r of state.reports) {
    const marker = pinById.get(r.public_id);
    if (!marker) continue;
    const ok = inLens(provenanceOf(r)) &&
               state.types.has(CATEGORY_TYPE[r.category] || "other");
    marker.getElement().style.display = ok ? "" : "none";
  }
  if (mapReady) {
    const roads = showAgency && state.types.has("roads");
    map.setLayoutProperty("delays-line", "visibility", roads ? "visible" : "none");
    const wx = showAgency && state.types.has("weather");
    for (const id of ["weather-fill", "weather-outline"])
      map.setLayoutProperty(id, "visibility", wx ? "visible" : "none");
  }
}

/* ---- panel: list -------------------------------------------------------- */

function renderPanel() {
  if (state.selected) return;   // detail view owns the panel
  $("panel-back").classList.add("hidden");
  $("panel-title").textContent = {
    everything: "On the map now", official: "Official information",
    community: "What people are reporting", mine: "Your reports",
  }[state.lens];
  const box = $("panel-scroll");
  box.replaceChildren();

  const rows = [];
  for (const r of state.reports) {
    const prov = provenanceOf(r);
    if (!inLens(prov) || !state.types.has(CATEGORY_TYPE[r.category] || "other")) continue;
    rows.push({ time: r.created_at, el: reportRow(r, prov) });
  }
  if (agencyVisible()) {
    for (const w of ((state.feeds.weather || {}).items || [])) {
      if (!state.types.has("weather")) continue;
      rows.push({ time: w.published || new Date().toISOString(),
        el: feedRow("🌬️", w.title, w.area || "MetService warning", null,
          () => selectFeedItem({ type: "weather", title: w.title,
            sub: `${w.area || ""}${w.onset ? " · from " + fmtTime(w.onset) : ""}${w.expires ? " until " + fmtTime(w.expires) : ""}`,
            attribution: "MetService (CC BY 4.0)", when: w.published, link: w.link })) });
    }
    for (const q of ((state.feeds.quakes || {}).items || []).slice(0, 5)) {
      if (!state.types.has("quakes")) continue;
      rows.push({ time: q.time, el: feedRow("🌐", `M${q.magnitude} ${q.locality}`,
        `${q.depth_km} km deep`, q.time,
        () => selectFeedItem({ type: "quakes", title: `M${q.magnitude} ${q.locality}`,
          sub: `${q.depth_km} km deep · felt intensity ${q.mmi}`,
          attribution: "GeoNet (GNS Science)", when: q.time, link: q.link })) });
    }
    for (const o of ((state.feeds.outages || {}).items || [])) {
      if (!state.types.has("power")) continue;
      rows.push({ time: o.start || new Date().toISOString(),
        el: feedRow("⚡", `Outage: ${o.location || "unnamed"}`,
          `${o.affected || "?"} customers`, o.start, null) });
    }
    const delayFeats = (((state.feeds.delays || {}).geojson) || {}).features || [];
    for (const f of delayFeats.slice(0, 8)) {
      if (!state.types.has("roads")) continue;
      const p = f.properties;
      rows.push({ time: p.updated || "", el: feedRow("🛣️",
        `${p.eventType}: ${p.location}`, p.impact || "", null, null) });
    }
  }
  rows.sort((a, b) => String(b.time).localeCompare(String(a.time)));

  if (agencyVisible() && state.types.has("rivers")) {
    for (const g of ((state.feeds.gauges || {}).items || [])) {
      if (g.error || g.value == null) continue;
      const parts = g.site.split(" at ");
      const v = typeof g.value === "number"
        ? (g.value >= 100 ? Math.round(g.value) : g.value.toFixed(1)) : g.value;
      rows.push({ time: "", el: feedRow(g.kind === "rain" ? "☔" : "🌊",
        parts[1] || parts[0],
        g.kind === "rain" ? `${g.recent_total ?? v} mm recently`
          : `${v} ${g.units === "m³/sec" ? "m³/s" : g.units}${g.trend ? " · " + g.trend : ""}`,
        null, null) });
    }
  }

  if (!rows.length) {
    const d = document.createElement("div");
    d.className = "rows-empty";
    d.style.margin = "14px 4px";
    d.textContent = state.lens === "mine"
      ? "No reports from this device yet. Tap “Report something” and you'll see it here and on the map."
      : "Nothing matches the current filters.";
    box.append(d);
    return;
  }
  for (const r of rows) box.append(r.el);
}

function provBadge(prov) {
  const s = document.createElement("span");
  s.className = `prov ${prov}`;
  s.textContent = prov === "official" ? "✓ official"
    : prov === "mine" ? "yours" : "community";
  return s;
}

function reportRow(r, prov) {
  const meta = CATEGORY_META[r.category] || { icon: "📝", label: r.category };
  const b = document.createElement("button");
  b.className = "item-row";
  const ic = document.createElement("span");
  ic.className = "ic"; ic.textContent = meta.icon;
  const main = document.createElement("span");
  main.className = "main";
  const t = document.createElement("span");
  t.className = "t"; t.textContent = meta.label;
  const s = document.createElement("span");
  s.className = "s"; s.textContent = r.place_name || "";
  main.append(t, s);
  const right = document.createElement("span");
  right.className = "right";
  right.append(provBadge(prov));
  const pill = document.createElement("span");
  pill.className = `pill ${r.status}`;
  pill.textContent = (STATUS_COPY[r.status] || {}).title || r.status;
  right.append(pill);
  b.append(ic, main, right);
  b.addEventListener("click", () => selectReportItem(r.public_id, true));
  return b;
}

function feedRow(icon, title, sub, when, onClick) {
  const b = document.createElement("button");
  b.className = "item-row";
  const ic = document.createElement("span");
  ic.className = "ic"; ic.textContent = icon;
  const main = document.createElement("span");
  main.className = "main";
  const t = document.createElement("span");
  t.className = "t"; t.textContent = title;
  const s = document.createElement("span");
  s.className = "s"; s.textContent = sub || "";
  main.append(t, s);
  const right = document.createElement("span");
  right.className = "right";
  right.append(provBadge("official"));
  if (when) {
    const w = document.createElement("span");
    w.className = "s"; w.textContent = agoText(when);
    right.append(w);
  }
  b.append(ic, main, right);
  if (onClick) b.addEventListener("click", onClick);
  else b.style.cursor = "default";
  return b;
}

/* ---- panel: detail ------------------------------------------------------ */

async function selectReportItem(publicId, fly) {
  let item;
  try { item = await getJSON(`/api/items/${encodeURIComponent(publicId)}`); }
  catch { return; }
  state.selected = { kind: "report", public_id: publicId };
  history.replaceState(null, "", `/?item=${publicId}`);
  const mine = myReports().find(m => m.public_id === publicId);
  const prov = mine ? "mine" : item.verified ? "official" : "community";

  $("panel-back").classList.remove("hidden");
  $("panel-title").textContent = "Report";
  const box = $("panel-scroll");
  box.replaceChildren();
  const d = document.createElement("div");
  d.className = "item-detail";

  d.append(provBadge(prov));
  const provLine = document.createElement("div");
  provLine.className = "s";
  provLine.style.cssText = "color:var(--ink-mute);font-size:13px;margin-top:6px";
  provLine.textContent = item.verified
    ? "Verified by the council: a duty officer has confirmed this report."
    : "Community report: shared as received, not yet council-verified.";
  d.append(provLine);

  const meta = CATEGORY_META[item.category] || { icon: "📝", label: item.category };
  const h = document.createElement("h3");
  h.textContent = `${meta.icon} ${meta.label}`;
  d.append(h);
  if (item.place_name) {
    const place = document.createElement("div");
    place.className = "place"; place.textContent = item.place_name;
    d.append(place);
  }
  const kv = document.createElement("div");
  kv.className = "kv";
  const kvrow = document.createElement("div");
  const bb = document.createElement("b");
  bb.textContent = "Reported: ";
  kvrow.append(bb, document.createTextNode(
    `${fmtTime(item.created_at)} (${agoText(item.created_at)})`));
  kv.append(kvrow);
  d.append(kv);

  const tl = document.createElement("ol");
  tl.className = "pub-timeline";
  for (const ev of item.timeline) {
    const li = document.createElement("li");
    const what = document.createElement("span");
    if (ev.status === "verified") {
      what.className = "vmark";
      what.textContent = "✓ Council verified this report";
    } else {
      what.textContent = (STATUS_COPY[ev.status] || {}).title || ev.status;
      what.style.fontWeight = "700";
      what.style.color = STATUS_COLOR[ev.status] || "inherit";
    }
    const when = document.createElement("span");
    when.className = "when"; when.textContent = fmtTime(ev.created_at);
    li.append(what, when);
    tl.append(li);
  }
  d.append(tl);

  if (mine) {
    const a = document.createElement("a");
    a.className = "detail-cta";
    a.href = `/?ref=${encodeURIComponent(mine.ref)}`;
    a.textContent = "This is yours: open your tracking page";
    d.append(a);
  } else {
    const hint = document.createElement("p");
    hint.className = "privacy-note";
    hint.textContent = "Only the reporter (holding the reference code) and council staff can see the description, photo and contact details.";
    d.append(hint);
  }
  box.append(d);

  const rep = state.reports.find(r => r.public_id === publicId);
  if (fly && rep && rep.lat != null) map.flyTo({ center: [rep.lng, rep.lat], zoom: 14 });
}

function selectFeedItem(info) {
  state.selected = { kind: "feed" };
  $("panel-back").classList.remove("hidden");
  $("panel-title").textContent = "Official information";
  const box = $("panel-scroll");
  box.replaceChildren();
  const d = document.createElement("div");
  d.className = "item-detail";
  d.append(provBadge("official"));
  const h = document.createElement("h3");
  h.textContent = info.title;
  d.append(h);
  const sub = document.createElement("div");
  sub.className = "place"; sub.textContent = info.sub || "";
  d.append(sub);
  const kv = document.createElement("div");
  kv.className = "kv";
  const src = document.createElement("div");
  const b = document.createElement("b");
  b.textContent = "Source: ";
  src.append(b, document.createTextNode(info.attribution +
    (info.when ? ` · ${agoText(info.when)}` : "")));
  kv.append(src);
  d.append(kv);
  if (info.link) {
    const a = document.createElement("a");
    a.className = "detail-cta";
    a.href = info.link; a.target = "_blank"; a.rel = "noopener";
    a.textContent = "View at the source";
    d.append(a);
  }
  box.append(d);
}

/* ================================================================ drawer */

let pickedCategory = null;
let photoB64 = null;
let drawerLatLng = null;

function buildDrawer() {
  const chipBox = $("category-chips");
  for (const [value, meta] of Object.entries(CATEGORY_META)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.setAttribute("aria-pressed", "false");
    const icon = document.createElement("span");
    icon.className = "chip-icon";
    icon.textContent = meta.icon;
    icon.setAttribute("aria-hidden", "true");
    b.append(icon, document.createTextNode(meta.label));
    b.addEventListener("click", () => {
      chipBox.querySelectorAll(".chip").forEach(c => c.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      pickedCategory = value;
    });
    chipBox.append(b);
  }
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-wrap").addEventListener("click", (e) => {
    if (e.target === $("drawer-wrap")) closeDrawer();
  });
  $("photo").addEventListener("change", onPhotoPicked);
  $("report-form").addEventListener("submit", onSubmit);
}

function openDrawer(latLng) {
  drawerLatLng = latLng;
  const pinState = $("pin-state");
  if (latLng) {
    pinState.className = "pin-state";
    pinState.textContent = "📍 Pin set on the map.";
    showHazardHint(latLng.lat, latLng.lng);
  } else {
    pinState.className = "pin-state unset";
    pinState.textContent = "No map pin. Close this and tap the map, or just describe the place below.";
    $("hazard-hint").classList.add("hidden");
  }
  $("drawer-wrap").classList.remove("hidden");
  $("description").focus();
}

function closeDrawer() {
  $("drawer-wrap").classList.add("hidden");
}

async function showHazardHint(lat, lng) {
  const box = $("hazard-hint");
  box.classList.remove("hidden");
  box.textContent = "Checking what the council's hazard maps say about this spot…";
  try {
    const hz = await getJSON(`/api/hazard?lat=${lat.toFixed(5)}&lng=${lng.toFixed(5)}`);
    box.replaceChildren();
    const intro = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = "About this spot ";
    intro.append(strong, document.createTextNode("(from council hazard-planning maps; context, not a forecast):"));
    box.append(intro);
    const chips = document.createElement("div");
    chips.className = "hazard-chips";
    const add = (text, warn) => {
      const c = document.createElement("span");
      c.className = "hz-chip" + (warn ? " warn" : "");
      c.textContent = text;
      chips.append(c);
    };
    if (hz.tsunami_zone) add(`Tsunami evacuation zone: ${hz.tsunami_zone}`, true);
    if (hz.flood_hazard) add(`Flood hazard (1% AEP): ${hz.flood_hazard}`, true);
    if (hz.liquefaction_risk) add(`Liquefaction: ${hz.liquefaction_risk}`, false);
    if (hz.fault_zone && hz.fault_zone.name) add(`Near ${hz.fault_zone.name}`, false);
    if (hz.nearest_emergency_hub && hz.nearest_emergency_hub.name)
      add(`Nearest hub: ${hz.nearest_emergency_hub.name}`, false);
    if (hz.nearest_gauge && hz.nearest_gauge.value != null)
      add(`Nearest gauge: ${hz.nearest_gauge.site} ${hz.nearest_gauge.value} ${hz.nearest_gauge.units}${hz.nearest_gauge.trend ? ", " + hz.nearest_gauge.trend : ""}`, false);
    if (!chips.childElementCount) add("No mapped hazards at this exact spot", false);
    box.append(chips);
  } catch {
    box.textContent = "Couldn't reach the hazard maps just now. That won't affect your report.";
  }
}

function onPhotoPicked() {
  photoB64 = null;
  const file = $("photo").files && $("photo").files[0];
  if (!file) return;
  const img = new Image();
  img.onload = () => {
    const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    photoB64 = canvas.toDataURL("image/jpeg", 0.82).split(",")[1];
    URL.revokeObjectURL(img.src);
  };
  img.src = URL.createObjectURL(file);
}

async function onSubmit(e) {
  e.preventDefault();
  const err = $("form-error");
  err.classList.add("hidden");
  const problems = [];
  if (!pickedCategory) problems.push("pick what's happening (step 1)");
  if (!$("description").value.trim()) problems.push("describe what you can see");
  if (problems.length) {
    err.textContent = "Almost there. Please " + problems.join(" and ") + ".";
    err.classList.remove("hidden");
    return;
  }
  const btn = $("btn-submit");
  btn.disabled = true;
  btn.textContent = "Sending…";
  try {
    const body = {
      category: pickedCategory,
      description: $("description").value.trim(),
      place_name: $("place-name").value.trim() || null,
      reporter_role: $("reporter-role").value,
      contact: $("contact").value.trim() || null,
    };
    if (drawerLatLng) { body.lat = drawerLatLng.lat; body.lng = drawerLatLng.lng; }
    if (photoB64) body.photo_b64 = photoB64;
    const report = await postJSON("/api/reports", body);
    rememberRef(report);
    location.assign(`/?ref=${report.ref}&new=1`);
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove("hidden");
    btn.disabled = false;
    btn.textContent = "Send to the council";
  }
}

function rememberRef(report) {
  try {
    const mine = myReports();
    mine.unshift({ ref: report.ref, public_id: report.public_id,
      category: report.category, place: report.place_name,
      at: new Date().toISOString() });
    localStorage.setItem("kitea-mine", JSON.stringify(mine.slice(0, 30)));
  } catch { /* private browsing */ }
}

/* ============================================================== tracking */

let trackSource = null;

async function initTrackView(ref, justSubmitted) {
  $("track-ref").textContent = ref;
  if (!justSubmitted) $("track-heading").textContent = "Your report";
  $("btn-copy-link").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(`${location.origin}/?ref=${ref}`);
      $("btn-copy-link").textContent = "Copied ✓";
      setTimeout(() => { $("btn-copy-link").textContent = "Copy tracking link"; }, 1800);
    } catch {}
  });
  await refreshTrack(ref);
  openTrackStream(ref);
}

async function refreshTrack(ref) {
  try {
    const rep = await getJSON(`/api/reports/${encodeURIComponent(ref)}`);
    $("track-error").classList.add("hidden");
    const meta = CATEGORY_META[rep.category] || { icon: "📝", label: rep.category };
    $("track-summary").textContent =
      `${meta.icon} ${meta.label}` +
      (rep.place_name ? ` · ${rep.place_name}` : "") +
      ` · sent ${fmtTime(rep.created_at)}` +
      (rep.verified ? " · ✓ council-verified" : "");
    renderTrackTimeline(rep);
    renderHub(rep);
  } catch (ex) {
    $("track-error").textContent =
      ex.message.includes("no report")
        ? `No report found for code ${ref}. Check the code and try again.`
        : ex.message;
    $("track-error").classList.remove("hidden");
  }
}

function renderTrackTimeline(rep) {
  const lifecycle = rep.history.filter(ev => LIFECYCLE.includes(ev.status));
  const verifiedEv = rep.history.find(ev => ev.status === "verified");
  const seen = {};
  for (const ev of lifecycle) seen[ev.status] = ev;
  const reachedIdx = Math.max(...lifecycle.map(ev => LIFECYCLE.indexOf(ev.status)), 0);
  const ol = $("track-timeline");
  ol.replaceChildren();

  if (verifiedEv) {
    const li = document.createElement("li");
    li.className = "done";
    const dot = document.createElement("span");
    dot.className = "tl-dot";
    dot.setAttribute("aria-hidden", "true");
    const title = document.createElement("div");
    title.className = "tl-title";
    title.textContent = "Council verified your report";
    const note = document.createElement("div");
    note.className = "tl-note";
    note.textContent = verifiedEv.note || "A duty officer confirmed what you reported. It now shows as official on the public map.";
    const time = document.createElement("div");
    time.className = "tl-time";
    time.textContent = fmtTime(verifiedEv.created_at);
    li.append(dot, title, note, time);
    ol.append(li);
  }

  LIFECYCLE.forEach((status, i) => {
    const li = document.createElement("li");
    li.className = i < reachedIdx ? "done" : i === reachedIdx ? "current" : "future";
    if (i === reachedIdx && status === "resolved") li.className = "done";
    const dot = document.createElement("span");
    dot.className = "tl-dot";
    dot.setAttribute("aria-hidden", "true");
    const title = document.createElement("div");
    title.className = "tl-title";
    title.textContent = STATUS_COPY[status].title;
    li.append(dot, title);
    const ev = seen[status];
    if (ev) {
      const note = document.createElement("div");
      note.className = "tl-note";
      note.textContent = ev.note || STATUS_COPY[status].blurb;
      const time = document.createElement("div");
      time.className = "tl-time";
      time.textContent = fmtTime(ev.created_at);
      li.append(note, time);
    }
    ol.append(li);
  });
}

function renderHub(rep) {
  const hz = rep.hazard;
  const box = $("track-hub");
  if (!hz || !hz.nearest_emergency_hub || !hz.nearest_emergency_hub.name) return;
  box.classList.remove("hidden");
  box.replaceChildren();
  const strong = document.createElement("strong");
  strong.textContent = "Good to know: ";
  box.append(strong, document.createTextNode(
    `your nearest Community Emergency Hub is ${hz.nearest_emergency_hub.name}` +
    (hz.nearest_emergency_hub.address ? ` (${hz.nearest_emergency_hub.address})` : "") +
    ". In a major emergency, hubs are where neighbours gather to help each other."));
}

function openTrackStream(ref) {
  const tag = $("track-live"), text = $("track-live-text");
  if (trackSource) trackSource.close();
  trackSource = new EventSource(`/api/stream?ref=${encodeURIComponent(ref)}`);
  trackSource.onopen = () => { tag.classList.add("connected"); text.textContent = "live: updates by itself"; };
  trackSource.onerror = () => { tag.classList.remove("connected"); text.textContent = "reconnecting…"; };
  trackSource.addEventListener("status", () => refreshTrack(ref));
  trackSource.addEventListener("verified", () => refreshTrack(ref));
  trackSource.addEventListener("report-updated", () => refreshTrack(ref));
}

/* ================================================================ boot */

if (trackRef) {
  $("view-canvas").classList.add("hidden");
  document.body.classList.remove("canvas");
  $("view-track").classList.remove("hidden");
  initTrackView(trackRef, params.get("new") === "1");
} else {
  initCanvas();
}
