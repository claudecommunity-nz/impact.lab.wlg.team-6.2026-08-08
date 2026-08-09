/* Kitea resident page: report form + live tracking view.
   All user-sourced strings are rendered with textContent — never innerHTML. */

"use strict";

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

const nzTime = new Intl.DateTimeFormat("en-NZ", {
  timeZone: "Pacific/Auckland", weekday: "short",
  hour: "numeric", minute: "2-digit", day: "numeric", month: "short",
});

const $ = (id) => document.getElementById(id);

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

/* ---------------------------------------------------------------- basemap */

const OSM_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

/* ================================================================ router */

const params = new URLSearchParams(location.search);
const trackRef = (params.get("ref") || "").trim().toUpperCase();

if (trackRef) {
  $("view-form").classList.add("hidden");
  $("view-track").classList.remove("hidden");
  initTrackView(trackRef, false);
} else {
  initFormView();
}

/* ================================================================= form */

let pickedLatLng = null;
let pickedCategory = null;
let photoB64 = null;
let pickMap = null;
let pickMarker = null;
let hazardTimer = null;

function initFormView() {
  const chipBox = $("category-chips");
  for (const [value, meta] of Object.entries(CATEGORY_META)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.dataset.value = value;
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

  pickMap = new maplibregl.Map({
    container: "pick-map",
    style: OSM_STYLE,
    center: [174.7762, -41.2865],
    zoom: 10.8,
    attributionControl: { compact: true },
  });
  pickMap.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  pickMap.on("click", (e) => setPin(e.lngLat.lat, e.lngLat.lng, true));

  $("btn-locate").addEventListener("click", () => {
    if (!navigator.geolocation) return;
    $("btn-locate").textContent = "Finding you…";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        $("btn-locate").textContent = "📍 Use my location";
        setPin(pos.coords.latitude, pos.coords.longitude, true);
        pickMap.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: 15 });
      },
      () => { $("btn-locate").textContent = "📍 Couldn't get a location. Tap the map instead"; },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  });

  $("photo").addEventListener("change", onPhotoPicked);
  $("report-form").addEventListener("submit", onSubmit);

  renderMine();
  loadPublicRows();
}

function setPin(lat, lng, fetchHazard) {
  pickedLatLng = { lat, lng };
  if (!pickMarker) {
    pickMarker = new maplibregl.Marker({ color: "#14524A", draggable: true })
      .setLngLat([lng, lat]).addTo(pickMap);
    pickMarker.on("dragend", () => {
      const p = pickMarker.getLngLat();
      setPin(p.lat, p.lng, true);
    });
  } else {
    pickMarker.setLngLat([lng, lat]);
  }
  if (fetchHazard) {
    clearTimeout(hazardTimer);
    hazardTimer = setTimeout(() => showHazardHint(lat, lng), 500);
  }
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
      add(`Nearest Community Emergency Hub: ${hz.nearest_emergency_hub.name}`, false);
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
  if (!$("description").value.trim()) problems.push("describe what you can see (step 3)");
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
    if (pickedLatLng) { body.lat = pickedLatLng.lat; body.lng = pickedLatLng.lng; }
    if (photoB64) body.photo_b64 = photoB64;
    const report = await getJSON2("/api/reports", body);
    rememberRef(report.ref, report.category, report.place_name);
    history.replaceState(null, "", `/?ref=${report.ref}`);
    $("view-form").classList.add("hidden");
    $("view-track").classList.remove("hidden");
    window.scrollTo(0, 0);
    initTrackView(report.ref, true);
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove("hidden");
    btn.disabled = false;
    btn.textContent = "Send to the council";
  }
}

async function getJSON2(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `request failed (${r.status})`);
  return data;
}

/* ------------------------------------------------------------ my reports */

function rememberRef(ref, category, place) {
  try {
    const mine = JSON.parse(localStorage.getItem("kitea-mine") || "[]");
    mine.unshift({ ref, category, place, at: new Date().toISOString() });
    localStorage.setItem("kitea-mine", JSON.stringify(mine.slice(0, 20)));
  } catch { /* private browsing */ }
}

function renderMine() {
  let mine = [];
  try { mine = JSON.parse(localStorage.getItem("kitea-mine") || "[]"); } catch {}
  if (!mine.length) return;
  $("mine-section").classList.remove("hidden");
  const box = $("mine-rows");
  box.replaceChildren();
  for (const m of mine) {
    const a = document.createElement("a");
    a.className = "report-row";
    a.href = `/?ref=${encodeURIComponent(m.ref)}`;
    a.style.textDecoration = "none";
    a.style.color = "inherit";
    const cat = document.createElement("span");
    cat.className = "cat";
    cat.textContent = `${(CATEGORY_META[m.category] || {}).icon || "📝"} ${m.ref}`;
    const place = document.createElement("span");
    place.className = "place";
    place.textContent = m.place || "";
    const when = document.createElement("span");
    when.className = "when";
    when.textContent = agoText(m.at);
    a.append(cat, place, when);
    box.append(a);
  }
}

async function loadPublicRows() {
  const box = $("public-rows");
  try {
    const data = await getJSON("/api/reports?limit=8");
    box.replaceChildren();
    if (!data.reports.length) {
      const d = document.createElement("div");
      d.className = "rows-empty";
      d.textContent = "Nothing reported recently. When neighbours report, you'll see it here.";
      box.append(d);
      return;
    }
    for (const r of data.reports) {
      const row = document.createElement("div");
      row.className = "report-row";
      const cat = document.createElement("span");
      cat.className = "cat";
      const meta = CATEGORY_META[r.category] || { icon: "📝", label: r.category };
      cat.textContent = `${meta.icon} ${meta.label}`;
      const place = document.createElement("span");
      place.className = "place";
      place.textContent = r.place_name || "";
      const pill = document.createElement("span");
      pill.className = `pill ${r.status}`;
      pill.textContent = (STATUS_COPY[r.status] || {}).title || r.status;
      const when = document.createElement("span");
      when.className = "when";
      when.textContent = agoText(r.created_at);
      row.append(cat, place, pill, when);
      box.append(row);
    }
  } catch {
    box.replaceChildren();
    const d = document.createElement("div");
    d.className = "rows-empty";
    d.textContent = "Couldn't load recent reports.";
    box.append(d);
  }
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
  openStream(ref);
}

async function refreshTrack(ref) {
  try {
    const rep = await getJSON(`/api/reports/${encodeURIComponent(ref)}`);
    $("track-error").classList.add("hidden");
    const meta = CATEGORY_META[rep.category] || { icon: "📝", label: rep.category };
    $("track-summary").textContent =
      `${meta.icon} ${meta.label}` +
      (rep.place_name ? ` · ${rep.place_name}` : "") +
      ` · sent ${fmtTime(rep.created_at)}`;
    renderTimeline(rep);
    renderHub(rep);
  } catch (ex) {
    $("track-error").textContent =
      ex.message.includes("no report")
        ? `No report found for code ${ref}. Check the code and try again.`
        : ex.message;
    $("track-error").classList.remove("hidden");
  }
}

function renderTimeline(rep) {
  const order = ["received", "reviewing", "responding", "resolved"];
  const seen = {};
  for (const ev of rep.history) seen[ev.status] = ev;   // latest event per status wins
  const reachedIdx = Math.max(...rep.history.map(ev => order.indexOf(ev.status)), 0);
  const ol = $("track-timeline");
  ol.replaceChildren();
  order.forEach((status, i) => {
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
    } else if (i > reachedIdx) {
      const note = document.createElement("div");
      note.className = "tl-note";
      note.textContent = "";
      li.append(note);
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

function openStream(ref) {
  const tag = $("track-live"), text = $("track-live-text");
  if (trackSource) trackSource.close();
  trackSource = new EventSource(`/api/stream?ref=${encodeURIComponent(ref)}`);
  trackSource.onopen = () => { tag.classList.add("connected"); text.textContent = "live: updates by itself"; };
  trackSource.onerror = () => { tag.classList.remove("connected"); text.textContent = "reconnecting…"; };
  trackSource.addEventListener("status", () => refreshTrack(ref));
  trackSource.addEventListener("report-updated", () => refreshTrack(ref));
}
