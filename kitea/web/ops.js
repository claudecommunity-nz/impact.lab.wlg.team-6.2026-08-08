/* Kitea ops dashboard. All user-sourced strings rendered via textContent. */

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
  "welfare-need":    { icon: "🤝", label: "Welfare need" },
  "other":           { icon: "📝", label: "Other" },
};

const STATUS_LABEL = { received: "Received", reviewing: "Reviewing",
                       responding: "Responding", resolved: "Resolved" };
const STATUS_COLOR = { received: "#9AA8B5", reviewing: "#E3A63A",
                       responding: "#6FA8FF", resolved: "#57C46F" };

const state = {
  key: sessionStorage.getItem("kitea-ops-key") || "",
  reports: [],
  stats: {},
  selectedRef: null,
  filter: "active",
  feeds: {},
};

const nzClock = new Intl.DateTimeFormat("en-NZ", {
  timeZone: "Pacific/Auckland", hour: "2-digit", minute: "2-digit", second: "2-digit",
});
const nzShort = new Intl.DateTimeFormat("en-NZ", {
  timeZone: "Pacific/Auckland", weekday: "short", hour: "numeric", minute: "2-digit",
});

function agoText(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  if (h < 48) return `${h}h ${mins % 60}m`;
  return `${Math.round(h / 24)}d`;
}

async function api(path, options = {}) {
  options.headers = Object.assign({ "X-Kitea-Key": state.key }, options.headers);
  const r = await fetch(path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(body.error || `request failed (${r.status})`); e.status = r.status; throw e; }
  return body;
}

/* ================================================================ lock */

$("lock-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  state.key = $("lock-key").value.trim();
  try {
    await api("/api/ops/reports");
    sessionStorage.setItem("kitea-ops-key", state.key);
    unlock();
  } catch (ex) {
    $("lock-error").textContent = ex.status === 401
      ? "That key wasn't accepted." : ex.message;
  }
});

(async function tryStoredKey() {
  if (!state.key) return;
  try { await api("/api/ops/reports"); unlock(); } catch { /* stay locked */ }
})();

function unlock() {
  $("lock").classList.add("hidden");
  $("topbar").classList.remove("hidden");
  $("workspace").classList.remove("hidden");
  $("feedbar").classList.remove("hidden");
  init();
}

/* ================================================================ init */

let map, mapReady = false;
const reportMarkers = new Map();     // ref -> Marker
const layerMarkers = { hubs: [], gauges: [], cameras: [], quakes: [], outages: [] };
const layerState = { reports: true, gauges: true, roads: true, hubs: true,
                     weather: true, outages: true, quakes: false, cameras: false };

function init() {
  setInterval(() => { $("clock").textContent = nzClock.format(new Date()); }, 1000);

  map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: { osm: { type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256, attribution: "© OpenStreetMap contributors" } },
      layers: [{ id: "osm", type: "raster", source: "osm",
                 paint: { "raster-saturation": -0.5, "raster-brightness-max": 0.85 } }],
    },
    center: [174.8, -41.26], zoom: 10.4,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.on("load", () => {
    mapReady = true;
    map.addSource("delays", { type: "geojson", data: emptyFC() });
    map.addLayer({ id: "delays-line", type: "line", source: "delays",
      paint: { "line-color": "#FF9950", "line-width": 3.5, "line-opacity": 0.75 } });
    map.addSource("weather", { type: "geojson", data: emptyFC() });
    map.addLayer({ id: "weather-fill", type: "fill", source: "weather",
      paint: { "fill-color": ["match", ["get", "severity"],
        "extreme", "#FF6B5E", "severe", "#FF9950", "#E3C441"], "fill-opacity": 0.14 } }, "delays-line");
    map.addLayer({ id: "weather-outline", type: "line", source: "weather",
      paint: { "line-color": ["match", ["get", "severity"],
        "extreme", "#FF6B5E", "severe", "#FF9950", "#E3C441"], "line-width": 1.5,
        "line-dasharray": [3, 2] } });
    map.on("click", "delays-line", (e) => {
      const p = e.features[0].properties;
      popupAt(e.lngLat, `${p.eventType}: ${p.location}`, p.description || "");
    });
    map.on("mouseenter", "delays-line", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "delays-line", () => { map.getCanvas().style.cursor = ""; });
    applyLayerVisibility();
  });

  buildLayerBar();
  buildFilters();
  $("detail-close").addEventListener("click", () => $("detail").classList.remove("open"));

  refreshReports();
  openStream();
  refreshFeeds();
  setInterval(refreshFeeds, 120_000);
  setInterval(renderQueue, 60_000);        // keep the "Xm ago" labels honest
}

function emptyFC() { return { type: "FeatureCollection", features: [] }; }

function popupAt(lngLat, title, sub) {
  const div = document.createElement("div");
  const t = document.createElement("div");
  t.className = "popup-title"; t.textContent = title;
  div.append(t);
  if (sub) {
    const s = document.createElement("div");
    s.className = "popup-sub"; s.textContent = sub;
    div.append(s);
  }
  new maplibregl.Popup({ closeButton: true }).setLngLat(lngLat).setDOMContent(div).addTo(map);
}

/* ============================================================== reports */

async function refreshReports() {
  try {
    const data = await api("/api/ops/reports");
    state.reports = data.reports;
    state.stats = data.stats;
    renderStats();
    renderQueue();
    renderReportMarkers();
    if (state.selectedRef) renderDetail(state.selectedRef, false);
  } catch (ex) {
    if (ex.status === 401) location.reload();
  }
}

function renderStats() {
  const box = $("stats");
  box.replaceChildren();
  const defs = [["total", "open + resolved"], ["received", "new"],
                ["reviewing", "reviewing"], ["responding", "responding"],
                ["resolved", "resolved"]];
  for (const [k, label] of defs) {
    const d = document.createElement("div");
    d.className = `stat s-${k}`;
    const b = document.createElement("b");
    b.textContent = state.stats[k] ?? 0;
    const s = document.createElement("span");
    s.textContent = label;
    d.append(b, s);
    box.append(d);
  }
}

function buildFilters() {
  const defs = [["active", "Active"], ["all", "All"], ["received", "New"],
                ["reviewing", "Reviewing"], ["responding", "Responding"],
                ["resolved", "Resolved"]];
  const box = $("filters");
  for (const [value, label] of defs) {
    const b = document.createElement("button");
    b.className = "filter"; b.textContent = label;
    b.setAttribute("aria-pressed", String(value === state.filter));
    b.addEventListener("click", () => {
      state.filter = value;
      box.querySelectorAll(".filter").forEach(f => f.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      renderQueue();
    });
    box.append(b);
  }
}

function visibleReports() {
  if (state.filter === "all") return state.reports;
  if (state.filter === "active") return state.reports.filter(r => r.status !== "resolved");
  return state.reports.filter(r => r.status === state.filter);
}

function renderQueue() {
  const box = $("queue-list");
  box.replaceChildren();
  const rows = visibleReports();
  if (!rows.length) {
    const d = document.createElement("div");
    d.className = "queue-empty";
    d.textContent = "Nothing here. When a community report arrives it appears instantly.";
    box.append(d);
    return;
  }
  for (const r of rows) {
    const card = document.createElement("button");
    card.className = "qcard" + (r.ref === state.selectedRef ? " selected" : "");
    card.addEventListener("click", () => selectReport(r.ref, true));

    const top = document.createElement("div");
    top.className = "qcard-top";
    const cat = document.createElement("span");
    const meta = CATEGORY_META[r.category] || { icon: "📝", label: r.category };
    cat.className = "cat";
    cat.textContent = `${meta.icon} ${meta.label}`;
    top.append(cat);
    if (r.group) {
      const g = document.createElement("span");
      g.className = "group-badge";
      g.textContent = `⧉ situation ${r.group}`;
      top.append(g);
    }
    const ref = document.createElement("span");
    ref.className = "ref"; ref.textContent = r.ref;
    top.append(ref);

    const mid = document.createElement("div");
    mid.className = "qcard-mid";
    mid.textContent = r.place_name || r.description || "";

    const bot = document.createElement("div");
    bot.className = "qcard-bot";
    const pill = document.createElement("span");
    pill.className = `pill ${r.status}`;
    pill.textContent = STATUS_LABEL[r.status] || r.status;
    const when = document.createElement("span");
    when.className = "when";
    when.textContent = agoText(r.created_at) + " ago";
    bot.append(pill, when);

    card.append(top, mid, bot);
    box.append(card);
  }
}

function renderReportMarkers() {
  for (const m of reportMarkers.values()) m.remove();
  reportMarkers.clear();
  if (!layerState.reports) return;
  for (const r of state.reports) {
    if (r.lat == null || r.lng == null) continue;
    const el = document.createElement("div");
    el.className = "report-pin" + (r.status !== "resolved" ? " big" : "");
    el.style.background = STATUS_COLOR[r.status] || "#9AA8B5";
    el.title = `${r.ref} ${r.category}`;
    el.addEventListener("click", (e) => { e.stopPropagation(); selectReport(r.ref, false); });
    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([r.lng, r.lat]).addTo(map);
    reportMarkers.set(r.ref, marker);
  }
}

function selectReport(ref, flyTo) {
  state.selectedRef = ref;
  renderQueue();
  renderDetail(ref, true);
  $("detail").classList.add("open");
  const r = state.reports.find(x => x.ref === ref);
  if (flyTo && r && r.lat != null) map.flyTo({ center: [r.lng, r.lat], zoom: 14.2 });
}

/* ============================================================== detail */

async function renderDetail(ref, scrollTop) {
  let rep;
  try { rep = await api(`/api/ops/reports/${encodeURIComponent(ref)}`); }
  catch { return; }
  $("detail-empty").classList.add("hidden");
  const box = $("detail-body");
  box.classList.remove("hidden");
  box.replaceChildren();

  const meta = CATEGORY_META[rep.category] || { icon: "📝", label: rep.category };
  const h2 = document.createElement("h2");
  h2.textContent = `${meta.icon} ${meta.label}`;
  const refLine = document.createElement("div");
  refLine.className = "ref-line";
  refLine.textContent = `${rep.ref} · reported ${nzShort.format(new Date(rep.created_at))} · ` +
    `as ${rep.reporter_role.replace("-", " ")}`;
  box.append(h2, refLine);

  const pill = document.createElement("span");
  pill.className = `pill ${rep.status}`;
  pill.textContent = STATUS_LABEL[rep.status];
  box.append(pill);

  const desc = document.createElement("div");
  desc.className = "detail-desc";
  desc.textContent = rep.description;
  desc.style.marginTop = "10px";
  box.append(desc);

  if (rep.photo) {
    const img = document.createElement("img");
    img.className = "detail-photo";
    img.src = `/uploads/${rep.photo}`;
    img.alt = "Photo attached to the report";
    box.append(img);
  }

  const rows = document.createElement("div");
  rows.className = "meta-rows";
  const addRow = (label, value) => {
    if (!value) return;
    const d = document.createElement("div");
    const b = document.createElement("b");
    b.textContent = label + ": ";
    d.append(b, document.createTextNode(value));
    rows.append(d);
  };
  addRow("Place", rep.place_name);
  addRow("Contact", rep.contact ? rep.contact + " (private)" : null);
  box.append(rows);

  box.append(hazardChips(rep.hazard));

  const actionsTitle = document.createElement("div");
  actionsTitle.style.cssText = "font-weight:700;margin-top:6px";
  actionsTitle.textContent = "One tap tells the reporter:";
  box.append(actionsTitle);

  const actions = document.createElement("div");
  actions.className = "status-actions";
  for (const status of ["reviewing", "responding", "resolved", "received"]) {
    if (status === "received") continue;   // fired automatically on arrival
    const b = document.createElement("button");
    b.className = "status-btn";
    b.dataset.status = status;
    b.textContent = STATUS_LABEL[status];
    b.disabled = rep.status === status;
    b.addEventListener("click", () => setStatus(rep.ref, status));
    actions.append(b);
  }
  box.append(actions);

  const note = document.createElement("input");
  note.className = "status-note";
  note.id = "status-note";
  note.maxLength = 1000;
  note.placeholder = "Optional note the reporter will see, e.g. Crew on the way";
  box.append(note);
  const hint = document.createElement("p");
  hint.className = "note-hint";
  hint.textContent = "The note is public to the reporter. Keep it plain and kind.";
  box.append(hint);

  const hist = document.createElement("ol");
  hist.className = "history";
  for (const ev of [...rep.history].reverse()) {
    const li = document.createElement("li");
    const time = document.createElement("span");
    time.className = "h-time";
    time.textContent = nzShort.format(new Date(ev.created_at));
    const what = document.createElement("span");
    what.textContent = STATUS_LABEL[ev.status] || ev.status;
    what.style.fontWeight = "700";
    const noteEl = document.createElement("span");
    noteEl.className = "h-note";
    noteEl.textContent = ev.note || "";
    li.append(time, what, noteEl);
    hist.append(li);
  }
  box.append(hist);

  if (scrollTop) $("detail-scroll").scrollTop = 0;
}

function hazardChips(hz) {
  const wrap = document.createElement("div");
  wrap.className = "hz-chips";
  if (!hz) {
    const c = document.createElement("span");
    c.className = "hz-chip";
    c.textContent = "hazard context: pending…";
    wrap.append(c);
    return wrap;
  }
  const add = (text, warn) => {
    const c = document.createElement("span");
    c.className = "hz-chip" + (warn ? " warn" : "");
    c.textContent = text;
    wrap.append(c);
  };
  if (hz.error) { add("hazard lookup failed", true); return wrap; }
  if (hz.tsunami_zone) add(`tsunami: ${hz.tsunami_zone}`, /red/i.test(hz.tsunami_zone));
  if (hz.flood_hazard) add(`ponding: ${hz.flood_hazard}`, true);
  if (hz.liquefaction_risk) add(`liquefaction: ${hz.liquefaction_risk}`,
                                /high|very/i.test(hz.liquefaction_risk));
  if (hz.fault_zone && hz.fault_zone.name) add(`fault: ${hz.fault_zone.name}`, false);
  if (hz.deprivation_decile) add(`NZDep decile ${hz.deprivation_decile}`,
                                 hz.deprivation_decile >= 8);
  if (hz.eq_prone_building_count) add(`${hz.eq_prone_building_count} EQ-prone buildings near`, false);
  if (hz.nearest_emergency_hub && hz.nearest_emergency_hub.name)
    add(`hub: ${hz.nearest_emergency_hub.name}`, false);
  if (hz.nearest_gauge && hz.nearest_gauge.value != null)
    add(`gauge: ${hz.nearest_gauge.site.split(" at ")[0]} ${hz.nearest_gauge.value} ` +
        `${hz.nearest_gauge.units}${hz.nearest_gauge.trend ? " · " + hz.nearest_gauge.trend : ""}`,
        hz.nearest_gauge.trend === "rising");
  if (!wrap.childElementCount) add("no mapped hazards at this location", false);
  return wrap;
}

async function setStatus(ref, status) {
  const note = ($("status-note") && $("status-note").value.trim()) || "";
  try {
    await api(`/api/reports/${encodeURIComponent(ref)}/status`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note }) });
    // SSE echoes the change back and triggers the refresh.
  } catch (ex) {
    alert(ex.message);
  }
}

/* ================================================================= SSE */

function openStream() {
  const es = new EventSource(`/api/ops/stream?key=${encodeURIComponent(state.key)}`);
  es.onopen = () => { $("sse-state").textContent = "live"; };
  es.onerror = () => { $("sse-state").textContent = "reconnecting…"; };
  es.addEventListener("report", refreshReports);
  es.addEventListener("status", refreshReports);
  es.addEventListener("report-updated", refreshReports);
}

/* ============================================================== layers */

function buildLayerBar() {
  const defs = [
    ["reports", "Reports", "#F2B705"],
    ["gauges", "Gauges", "#2E8C7E"],
    ["roads", "Roads", "#FF9950"],
    ["weather", "Weather", "#E3C441"],
    ["outages", "Power", "#FF6B5E"],
    ["hubs", "Hubs", "#57C46F"],
    ["quakes", "Quakes", "#FF6B5E"],
    ["cameras", "Cameras", "#8FA6C8"],
  ];
  const bar = $("layerbar");
  for (const [key, label, colour] of defs) {
    const b = document.createElement("button");
    b.className = "layer-toggle";
    b.setAttribute("aria-pressed", String(layerState[key]));
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = colour;
    b.append(dot, document.createTextNode(label));
    b.addEventListener("click", () => {
      layerState[key] = !layerState[key];
      b.setAttribute("aria-pressed", String(layerState[key]));
      if (key === "reports") renderReportMarkers();
      else applyLayerVisibility();
    });
    bar.append(b);
  }
}

function applyLayerVisibility() {
  if (!mapReady) return;
  map.setLayoutProperty("delays-line", "visibility", layerState.roads ? "visible" : "none");
  for (const id of ["weather-fill", "weather-outline"])
    map.setLayoutProperty(id, "visibility", layerState.weather ? "visible" : "none");
  for (const [name, markers] of Object.entries(layerMarkers)) {
    const on = layerState[name];
    for (const m of markers) m.getElement().style.display = on ? "" : "none";
  }
}

/* =============================================================== feeds */

const FEED_IDS = ["gauges", "weather", "delays", "outages", "quakes", "hubs", "cameras"];

async function refreshFeeds() {
  await Promise.allSettled(FEED_IDS.map(async (id) => {
    state.feeds[id] = await fetch(`/api/feeds/${id}`).then(r => r.json());
  }));
  renderFeedCards();
  renderFeedMarkers();
}

function freshnessDot(feed) {
  const dot = document.createElement("span");
  dot.className = "feed-fresh" + ((feed && (feed.from_cache || feed.error)) ? " stale" : "");
  dot.title = feed && feed.fetched_at ? `fetched ${nzShort.format(new Date(feed.fetched_at))}` : "";
  return dot;
}

function sparkline(series, colour) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "56"); svg.setAttribute("height", "16");
  svg.classList.add("spark");
  const vals = series.map(p => p.v).filter(v => typeof v === "number");
  if (vals.length < 2) return svg;
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  const pts = vals.map((v, i) =>
    `${(i / (vals.length - 1)) * 54 + 1},${14 - ((v - min) / span) * 12 + 1}`).join(" ");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", pts);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", colour);
  line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-linecap", "round");
  svg.append(line);
  return svg;
}

function renderFeedCards() {
  const bar = $("feedbar");
  bar.replaceChildren();

  const card = (title, feed) => {
    const c = document.createElement("div");
    c.className = "feed-card";
    const h = document.createElement("h3");
    h.append(freshnessDot(feed), document.createTextNode(title));
    c.append(h);
    const body = document.createElement("div");
    body.className = "feed-body";
    c.append(body);
    bar.append(c);
    return body;
  };

  const g = state.feeds.gauges;
  if (g) {
    const body = card("Rivers & rain · GWRC", g);
    for (const item of (g.items || [])) {
      if (item.error) continue;
      const line = document.createElement("div");
      line.className = "feed-line";
      const name = document.createElement("span");
      // "Hutt River at Taita Gorge" and "... at Birchville" must not both
      // render as "Hutt River" — the locality is the distinguishing part.
      const parts = item.site.split(" at ");
      name.textContent = parts[1] || parts[0];
      name.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:90px";
      line.append(name);
      if (item.series) line.append(sparkline(item.series, item.trend === "rising" ? "#FF9950" : "#2E8C7E"));
      const val = document.createElement("span");
      val.className = "val";
      const v = typeof item.value === "number" ?
        (item.value >= 100 ? Math.round(item.value) : item.value.toFixed(1)) : item.value;
      val.textContent = item.kind === "rain"
        ? `${item.recent_total ?? v} mm`
        : `${v} ${item.units === "m³/sec" ? "m³/s" : item.units}${item.trend === "rising" ? " ▲" : item.trend === "falling" ? " ▼" : ""}`;
      if (!item.fresh) { val.textContent += " (old)"; }
      line.append(val);
      body.append(line);
    }
  }

  const w = state.feeds.weather;
  if (w) {
    const body = card("Weather · MetService", w);
    if (!(w.items || []).length) {
      body.textContent = `No watches or warnings for the Wellington region right now` +
        (w.national_count ? ` (${w.national_count} elsewhere in NZ).` : ".");
    }
    for (const item of (w.items || []).slice(0, 3)) {
      const line = document.createElement("div");
      const sev = document.createElement("span");
      sev.className = `sev sev-${item.severity}`;
      sev.textContent = item.severity !== "unknown" ? item.severity.toUpperCase() + " " : "";
      line.append(sev, document.createTextNode(item.title));
      body.append(line);
    }
  }

  const d = state.feeds.delays;
  if (d) {
    const body = card("Roads · Waka Kotahi", d);
    const feats = ((d.geojson || {}).features || []);
    const closures = feats.filter(f => /closure/i.test(f.properties.eventType || ""));
    const b = document.createElement("b");
    b.textContent = `${feats.length}`;
    body.append(b, document.createTextNode(
      ` event${feats.length === 1 ? "" : "s"} · ${closures.length} closure${closures.length === 1 ? "" : "s"}`));
    for (const f of feats.slice(0, 2)) {
      const line = document.createElement("div");
      line.textContent = `${f.properties.eventType}: ${f.properties.location}`;
      line.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
      body.append(line);
    }
  }

  const o = state.feeds.outages;
  if (o) {
    const body = card("Power · NEMA", o);
    const items = o.items || [];
    const affected = items.reduce((sum, i) => sum + (i.affected || 0), 0);
    const b = document.createElement("b");
    b.textContent = `${items.length}`;
    body.append(b, document.createTextNode(
      ` outage${items.length === 1 ? "" : "s"} in the region` +
      (affected ? ` · ~${affected.toLocaleString()} customers` : "")));
  }

  const q = state.feeds.quakes;
  if (q) {
    const body = card("Quakes · GeoNet", q);
    const items = q.items || [];
    if (!items.length) body.textContent = "No felt quakes in the last 7 days.";
    else {
      const top = [...items].sort((a, b) => b.magnitude - a.magnitude)[0];
      const b = document.createElement("b");
      b.textContent = `M${top.magnitude}`;
      body.append(b, document.createTextNode(
        ` ${top.locality} (${agoText(top.time)} ago) · ${items.length} felt this week`));
    }
  }

  const hubsFeed = state.feeds.hubs;
  if (hubsFeed) {
    const body = card("Emergency hubs · WREMO", hubsFeed);
    const b = document.createElement("b");
    b.textContent = `${(hubsFeed.items || []).length}`;
    body.append(b, document.createTextNode(" Community Emergency Hubs on the map layer"));
  }
}

function clearLayer(name) {
  for (const m of layerMarkers[name]) m.remove();
  layerMarkers[name] = [];
}

function addMarker(name, lat, lng, el, popupBuilder) {
  if (lat == null || lng == null || !map) return;
  el.addEventListener("click", (e) => { e.stopPropagation(); popupBuilder && popupBuilder(); });
  const m = new maplibregl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map);
  if (!layerState[name]) el.style.display = "none";
  layerMarkers[name].push(m);
}

function renderFeedMarkers() {
  if (!map) return;

  clearLayer("gauges");
  for (const item of ((state.feeds.gauges || {}).items || [])) {
    if (item.error || item.lat == null) continue;
    const el = document.createElement("div");
    el.className = "gauge-pin" + (item.trend === "rising" ? " rising" : "") +
                   (item.fresh ? "" : " stale");
    const v = typeof item.value === "number"
      ? (item.value >= 100 ? Math.round(item.value) : item.value.toFixed(1)) : item.value;
    el.textContent = item.kind === "rain" ? `☔ ${item.recent_total ?? v}` :
      `${v}${item.trend === "rising" ? "▲" : item.trend === "falling" ? "▼" : ""}`;
    addMarker("gauges", item.lat, item.lng, el, () =>
      popupAt({ lng: item.lng, lat: item.lat }, item.site,
        `${item.measurement}: ${item.value} ${item.units}` +
        (item.trend ? ` · ${item.trend}` : "") + (item.fresh ? "" : " · READING IS OLD")));
  }

  clearLayer("hubs");
  for (const hub of ((state.feeds.hubs || {}).items || [])) {
    const el = document.createElement("div");
    el.className = "hub-pin";
    el.textContent = "🏫";
    addMarker("hubs", hub.lat, hub.lng, el, () =>
      popupAt({ lng: hub.lng, lat: hub.lat }, hub.name || "Community Emergency Hub", hub.address || ""));
  }

  clearLayer("quakes");
  for (const item of ((state.feeds.quakes || {}).items || [])) {
    const el = document.createElement("div");
    el.className = "quake-pin";
    const size = Math.max(12, Math.min(38, item.magnitude * 7));
    el.style.width = el.style.height = `${size}px`;
    addMarker("quakes", item.lat, item.lng, el, () =>
      popupAt({ lng: item.lng, lat: item.lat }, `M${item.magnitude} ${item.locality}`,
        `${agoText(item.time)} ago · ${item.depth_km} km deep`));
  }

  clearLayer("outages");
  for (const item of ((state.feeds.outages || {}).items || [])) {
    const el = document.createElement("div");
    el.className = "outage-pin";
    el.textContent = "⚡";
    addMarker("outages", item.lat, item.lng, el, () =>
      popupAt({ lng: item.lng, lat: item.lat }, item.location || "Outage",
        `${item.affected || "?"} customers · ${item.status || ""}`));
  }

  clearLayer("cameras");
  for (const cam of ((state.feeds.cameras || {}).items || [])) {
    if (cam.offline) continue;
    const el = document.createElement("div");
    el.className = "cam-pin";
    addMarker("cameras", cam.lat, cam.lng, el, () => {
      const div = document.createElement("div");
      const t = document.createElement("div");
      t.className = "popup-title";
      t.textContent = cam.name || "Camera";
      const img = document.createElement("img");
      img.className = "popup-img";
      img.src = cam.image;
      img.alt = cam.description || cam.name || "traffic camera";
      div.append(t, img);
      new maplibregl.Popup().setLngLat({ lng: cam.lng, lat: cam.lat }).setDOMContent(div).addTo(map);
    });
  }

  if (mapReady) {
    const d = state.feeds.delays;
    if (d && d.geojson) map.getSource("delays").setData(d.geojson);
    const w = state.feeds.weather;
    if (w) {
      map.getSource("weather").setData({
        type: "FeatureCollection",
        features: (w.items || []).filter(i => i.polygon).map(i => ({
          type: "Feature",
          geometry: { type: "Polygon", coordinates: i.polygon },
          properties: { severity: i.severity, title: i.title },
        })),
      });
    }
    applyLayerVisibility();
  }
}
