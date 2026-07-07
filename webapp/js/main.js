/* App wiring: uploads → parse → boundary detect → optimize → render. */
'use strict';

const state = {
  rawCalls: [],                                // all valid-coordinate calls from file
  calls: [],                                   // calls after boundary filter
  stations: [],                                // existing stations (uploaded or clicked)
  suggested: { responder: [], guardian: [] },  // optimizer output per station type
  boundary: null,                              // {feature, name, kind}
};

const $ = id => document.getElementById(id);
const map = initMap('map');

function status(msg, cls = '') {
  const el = $('status');
  el.textContent = msg;
  el.className = cls;
}

function fmtMi(v) { return v == null ? '—' : v.toFixed(2) + ' mi'; }

function respRadius() { return parseFloat($('resp-radius').value) || 2; }
function guardRadius() { return parseFloat($('guard-radius').value) || 8; }

/* Station groups currently displayed. Manual stations carry a kind
   ('responder'|'guardian') and join that group; uploads are 'existing'
   (ring at responder radius). Each ring inherits its group color. */
function activeGroups() {
  const groups = [];
  const byKind = k => state.stations.filter(s => (s.kind || 'existing') === k);
  const existing = byKind('existing');
  if (existing.length) {
    groups.push({ kind: 'existing', stations: existing, radius: respRadius() });
  }
  // manual stations always display; toggles gate only the suggested sets
  const respStations = [...byKind('responder'), ...($('resp-on').checked ? state.suggested.responder : [])];
  if (respStations.length) groups.push({ kind: 'responder', stations: respStations, radius: respRadius() });
  const guardStations = [...byKind('guardian'), ...($('guard-on').checked ? state.suggested.guardian : [])];
  if (guardStations.length) groups.push({ kind: 'guardian', stations: guardStations, radius: guardRadius() });
  return groups;
}

function stationInfoLine() {
  $('sta-info').innerHTML = state.stations.length
    ? `<b>${state.stations.length}</b> station(s): ` +
      state.stations.map(s => s.name || '?').join(', ')
    : '';
}

/* ---------- rendering ---------- */

function refreshCalls() {
  const filterOn = $('boundary-filter').checked && state.boundary;
  state.calls = filterOn
    ? filterPointsToBoundary(state.rawCalls, state.boundary.feature)
    : state.rawCalls.slice();
  setCalls(map, state.calls);
  const dropped = state.rawCalls.length - state.calls.length;
  $('cad-info').innerHTML =
    `<b>${state.calls.length.toLocaleString()}</b> calls plotted` +
    (dropped > 0 ? ` (${dropped.toLocaleString()} outside boundary)` : '') +
    (state.dropNote ? `<br>${state.dropNote}` : '');
}

const GROUP_TITLES = { existing: 'Existing stations', responder: 'Responder', guardian: 'Guardian' };

function refreshStationsAndMetrics() {
  const groups = activeGroups();
  for (const g of groups) {
    g.stats = coverageStats(state.calls, g.stations, g.radius);
    g.perStation = g.stats ? g.stats.perStation : null;
  }
  setStations(map, groups);

  const rows = [];
  for (const g of groups) {
    if (!g.stats) continue;
    rows.push(`<tr class="head"><td>${GROUP_TITLES[g.kind]}</td><td>${g.stations.length} station(s)</td></tr>`);
    rows.push(`<tr><td>Calls within ${g.radius} mi</td><td>${g.stats.coveredPct.toFixed(1)}%</td></tr>`);
    rows.push(`<tr><td>Avg dist to nearest</td><td>${fmtMi(g.stats.avgDistMi)}</td></tr>`);
    rows.push(`<tr><td>Max dist</td><td>${fmtMi(g.stats.maxDistMi)}</td></tr>`);
  }
  if (groups.length > 1) {
    const union = unionCoverageStats(state.calls, groups);
    if (union) {
      rows.push(`<tr class="head"><td>Combined</td><td>${groups.reduce((n, g) => n + g.stations.length, 0)} station(s)</td></tr>`);
      rows.push(`<tr><td>Calls covered by any</td><td>${union.coveredPct.toFixed(1)}%</td></tr>`);
    }
  }
  $('metrics-table').innerHTML = rows.join('');
  $('metrics').classList.toggle('hidden', rows.length === 0);
}

function refreshAll() {
  refreshCalls();
  refreshStationsAndMetrics();
}

/* ---------- boundary ---------- */

async function runBoundaryDetect() {
  if (!state.rawCalls.length) return;
  status('Detecting jurisdiction boundary…');
  $('boundary-info').textContent = 'Looking up…';
  const b = await detectBoundary(state.rawCalls);
  state.boundary = b;
  if (b) {
    $('boundary-info').innerHTML = `<b>${b.name}</b> (${b.kind === 'place' ? 'city/place' : b.kind})`;
    setBoundary(map, b.feature, $('boundary-show').checked);
    status(`Boundary: ${b.name}`, 'ok');
    $('sec-boundary').open = false;
  } else {
    $('boundary-info').textContent = 'No boundary found (TIGERweb + OSM both failed).';
    status('Boundary lookup failed — showing all calls.', 'err');
  }
  refreshAll();
}

/* ---------- optimization ---------- */

function runOptimize() {
  if (!state.calls.length) { status('Load CAD calls first.', 'err'); return; }
  const mode = $('mode-input').value;
  const t0 = performance.now();
  const suggest = (k, radius) => k > 0
    ? (mode === 'greedy' ? greedyMaxCoverage(state.calls, k, radius) : kmeans(state.calls, k))
    : [];

  state.suggested.responder = $('resp-on').checked
    ? suggest(parseInt($('resp-k').value, 10), respRadius()) : [];
  state.suggested.guardian = $('guard-on').checked
    ? suggest(parseInt($('guard-k').value, 10), guardRadius()) : [];

  const ms = performance.now() - t0;
  refreshStationsAndMetrics();
  const parts = [];
  if (state.suggested.responder.length) parts.push(`${state.suggested.responder.length} responder`);
  if (state.suggested.guardian.length) parts.push(`${state.suggested.guardian.length} guardian`);
  status(parts.length
    ? `Suggested ${parts.join(' + ')} station(s) over ${state.calls.length.toLocaleString()} calls in ${ms.toFixed(0)} ms`
    : 'Both station types disabled — nothing to suggest.', parts.length ? 'ok' : 'err');
}

/* ---------- click-to-add stations ---------- */

let manualCount = 0;
let stationSeq = 0;

whenMapReady(map, () => {
  map.on('click', e => {
    if (!$('click-add').checked) return;
    // clicks on an existing station open the popup instead
    const hits = map.queryRenderedFeatures(e.point, { layers: ['stations-pts'] });
    if (hits.length) return;
    manualCount++;
    const kind = $('manual-type').value;
    state.stations.push({
      lat: e.lngLat.lat, lon: e.lngLat.lng,
      name: `Manual ${manualCount}`, kind, manual: true, id: ++stationSeq,
    });
    stationInfoLine();
    refreshStationsAndMetrics();
    status(`Added Manual ${manualCount} (${kind}) at ${e.lngLat.lat.toFixed(5)}, ${e.lngLat.lng.toFixed(5)}`, 'ok');
  });

  map.on('click', 'stations-pts', e => {
    if ($('click-add').checked) return;  // add-mode: don't pop over placement
    const p = e.features[0].properties;
    const sid = p.sid ? Number(p.sid) : null;
    const station = sid ? state.stations.find(s => s.id === sid) : null;
    let html = `<b>${p.label}</b><br>${p.kind} station · ${p.radius} mi` +
      (p.covers != null ? `<br>covers ${Number(p.covers).toLocaleString()} calls` : '');
    if (station) {
      html += `<br><a href="#" class="rn-station">rename</a> · <a href="#" class="rm-station">remove</a>`;
    }
    const popup = new maplibregl.Popup()
      .setLngLat(e.features[0].geometry.coordinates)
      .setHTML(html)
      .addTo(map);
    if (!station) return;
    popup.getElement().querySelector('.rn-station').addEventListener('click', ev => {
      ev.preventDefault();
      const name = prompt('Station name:', station.name);
      if (name && name.trim()) {
        station.name = name.trim();
        popup.remove();
        stationInfoLine();
        refreshStationsAndMetrics();
        status(`Renamed to ${station.name}.`, 'ok');
      }
    });
    popup.getElement().querySelector('.rm-station').addEventListener('click', ev => {
      ev.preventDefault();
      state.stations.splice(state.stations.indexOf(station), 1);
      popup.remove();
      stationInfoLine();
      refreshStationsAndMetrics();
      status('Station removed.', 'ok');
    });
  });
});

/* ---------- file handling ---------- */

/* One dropzone for both file kinds — station list vs CAD calls auto-detected. */
async function handleDataFile(file) {
  status(`Parsing ${file.name}…`);
  try {
    const rows = await parseFile(file);
    if (looksLikeStationFile(file.name, rows)) {
      const { points } = extractPoints(rows, { wantName: true });
      if (!points.length) throw new Error('No rows with valid coordinates.');
      points.forEach(p => { p.kind = 'existing'; p.id = ++stationSeq; });
      state.stations = points;
      stationInfoLine();
      if (!state.rawCalls.length) fitToPoints(map, points);
      refreshStationsAndMetrics();
      status(`Loaded ${points.length} station(s) from ${file.name}.`, 'ok');
    } else {
      const { points, dropped, latCol, lonCol } = extractPoints(rows);
      if (!points.length) throw new Error('No rows with valid coordinates.');
      const { kept, removed } = filterOutliers(points);
      if (!kept.length) throw new Error('All rows were coordinate outliers.');
      state.rawCalls = kept;
      state.suggested = { responder: [], guardian: [] };
      const droppedBits = [];
      if (dropped) droppedBits.push(`${dropped.toLocaleString()} bad coords`);
      if (removed) droppedBits.push(`${removed.toLocaleString()} outliers`);
      state.dropNote = `cols: ${latCol}/${lonCol}` +
        (droppedBits.length ? ` · dropped ${droppedBits.join(', ')}` : '');
      fitToPoints(map, kept);
      refreshAll();
      status(`Loaded ${kept.length.toLocaleString()} calls.`, 'ok');
      await runBoundaryDetect();
      runOptimize();
    }
    $('sec-data').open = false;
  } catch (e) {
    status(`Parse error (${file.name}): ${e.message}`, 'err');
  }
}

async function handleFiles(fileList) {
  // Stations first so a simultaneous CAD drop optimizes against them.
  const files = Array.from(fileList)
    .sort((a, b) => (/station/i.test(b.name) ? 1 : 0) - (/station/i.test(a.name) ? 1 : 0));
  for (const f of files) await handleDataFile(f);
}

function wireDropzone(zoneId, inputId, handler) {
  const zone = $(zoneId), input = $(inputId);
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('drag');
    if (e.dataTransfer.files.length) handler(e.dataTransfer.files);
  });
  input.addEventListener('change', () => { if (input.files.length) handler(input.files); });
}

/* ---------- demo data ---------- */

/* Seeded synthetic calls inside a boundary polygon — 3 hotspots + uniform noise. */
function genPointsInBoundary(feature, n) {
  const [minX, minY, maxX, maxY] = turf.bbox(feature);
  // OSM city polygons can have 10k+ vertices — simplify for the containment
  // test only (display still uses the full-detail boundary)
  let testPoly = feature;
  try { testPoly = turf.simplify(feature, { tolerance: 0.001, highQuality: false }); } catch {}
  let seed = 42;
  const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  const gauss = () => (rand() + rand() + rand() + rand() - 2) / 2;
  const inPoly = (lat, lon) => turf.booleanPointInPolygon([lon, lat], testPoly);
  const rndInside = () => {
    for (let t = 0; t < 200; t++) {
      const lat = minY + rand() * (maxY - minY), lon = minX + rand() * (maxX - minX);
      if (inPoly(lat, lon)) return { lat, lon };
    }
    return { lat: (minY + maxY) / 2, lon: (minX + maxX) / 2 };
  };
  const s = Math.min(maxX - minX, maxY - minY) * 0.08;
  const hotspots = [
    { ...rndInside(), w: 0.4 }, { ...rndInside(), w: 0.3 }, { ...rndInside(), w: 0.2 },
  ];
  const points = [];
  let attempts = 0;
  while (points.length < n && attempts++ < n * 20) {
    const r = rand();
    let acc = 0, h = null;
    for (const hs of hotspots) { acc += hs.w; if (r < acc) { h = hs; break; } }
    const agency = rand() < 0.7 ? 'police' : (rand() < 0.7 ? 'fire' : 'ems');
    let lat, lon;
    if (h) {
      lat = h.lat + gauss() * s; lon = h.lon + gauss() * s * 1.3;
      if (!inPoly(lat, lon)) continue;    // hotspot spill outside boundary — reject
    } else {
      ({ lat, lon } = rndInside());
    }
    points.push({ lat, lon, agency });
  }
  return points;
}

/* Demo for an arbitrary US city — geocode boundary, estimate volume from
   OSM population when available (60% rule of thumb), fall back to 100k pop. */
async function loadDemoCity(query) {
  status(`Looking up ${query}…`);
  try {
    const geo = await geocodeCity(query);
    if (!geo) { status(`No boundary found for "${query}" — try "City, ST".`, 'err'); return; }
    const pop = geo.population || 100000;
    const callCount = Math.min(Math.round(pop * 0.6), 150000);
    status(`Generating ${callCount.toLocaleString()} demo calls for ${geo.name}…`);
    const points = genPointsInBoundary(geo.feature, callCount);
    state.rawCalls = points;
    state.suggested = { responder: [], guardian: [] };
    state.dropNote = geo.population
      ? `demo: 60% of pop. ${geo.population.toLocaleString()}`
      : 'demo: pop. unknown — assumed 100,000';
    const c = turf.centerOfMass(geo.feature).geometry.coordinates;
    state.stations = [{ lat: c[1], lon: c[0], name: 'HQ', kind: 'existing', id: ++stationSeq }];
    state.boundary = { feature: geo.feature, name: geo.name, kind: 'osm' };
    setBoundary(map, geo.feature, $('boundary-show').checked);
    $('boundary-info').innerHTML = `<b>${geo.name}</b> (demo boundary)`;
    $('sta-info').innerHTML = '<b>1</b> demo station (HQ)';
    fitToPoints(map, points);
    refreshAll();
    status(`Demo data loaded for ${geo.name}.`, 'ok');
    $('sec-data').open = false;
    $('sec-boundary').open = false;
    runOptimize();
  } catch (e) {
    status(`Demo lookup failed: ${e.message}`, 'err');
  }
}

function loadDemo() {
  const q = $('demo-city').value.trim();
  if (q) { loadDemoCity(q); return; }
  // Synthetic calls clustered around Naperville, IL — 3 hotspots + uniform noise.
  // Annual CFS volume modeled as 60% of city population (DFR rule of thumb).
  const NAPERVILLE_POP = 149540;
  const CALL_COUNT = Math.round(NAPERVILLE_POP * 0.6);
  const hotspots = [
    { lat: 41.772, lon: -88.150, w: 0.4, s: 0.012 },
    { lat: 41.750, lon: -88.117, w: 0.3, s: 0.015 },
    { lat: 41.789, lon: -88.204, w: 0.2, s: 0.010 },
  ];
  let seed = 42;
  const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  const gauss = () => (rand() + rand() + rand() + rand() - 2) / 2;
  const points = [];
  for (let i = 0; i < CALL_COUNT; i++) {
    const r = rand();
    let acc = 0, h = null;
    for (const hs of hotspots) { acc += hs.w; if (r < acc) { h = hs; break; } }
    const agency = rand() < 0.7 ? 'police' : (rand() < 0.7 ? 'fire' : 'ems');
    if (h) {
      points.push({ lat: h.lat + gauss() * h.s, lon: h.lon + gauss() * h.s * 1.3, agency });
    } else {
      points.push({ lat: 41.72 + rand() * 0.09, lon: -88.22 + rand() * 0.13, agency });
    }
  }
  state.rawCalls = points;
  state.suggested = { responder: [], guardian: [] };
  state.stations = [{ lat: 41.7719, lon: -88.1478, name: 'HQ', kind: 'existing', id: ++stationSeq }];
  $('cad-info').innerHTML =
    `<b>${points.length.toLocaleString()}</b> demo calls (60% of pop. ${NAPERVILLE_POP.toLocaleString()})`;
  $('sta-info').innerHTML = '<b>1</b> demo station (HQ)';
  fitToPoints(map, points);
  refreshAll();
  status('Demo data loaded.', 'ok');
  $('sec-data').open = false;
  runBoundaryDetect().then(runOptimize);
}

/* ---------- export ---------- */

async function runExport() {
  if (!state.calls.length) { status('Load CAD calls first.', 'err'); return; }
  status('Building HTML report…');
  const n = await exportHtmlReport(state, activeGroups(), $('metrics-table').innerHTML, dotStyle(state.calls.length));
  status(`Exported HTML report (${n.toLocaleString()} calls).`, 'ok');
}

/* ---------- events ---------- */

wireDropzone('cad-drop', 'cad-file', handleFiles);
$('demo-btn').addEventListener('click', loadDemo);
$('demo-city').addEventListener('keydown', e => { if (e.key === 'Enter') loadDemo(); });
$('export-btn').addEventListener('click', runExport);
$('boundary-btn').addEventListener('click', runBoundaryDetect);
$('optimize-btn').addEventListener('click', runOptimize);

for (const [slider, out] of [['resp-k', 'resp-k-out'], ['guard-k', 'guard-k-out']]) {
  $(slider).addEventListener('input', () => { $(out).value = $(slider).value; });
  $(slider).addEventListener('change', () => { if (state.calls.length) runOptimize(); });
}
// radius edits always re-draw rings (manual stations too), re-optimize when calls exist
for (const id of ['resp-radius', 'guard-radius']) {
  $(id).addEventListener('change', () => {
    if (state.calls.length) runOptimize();
    else refreshStationsAndMetrics();
  });
  $(id).addEventListener('input', () => refreshStationsAndMetrics());
}
$('mode-input').addEventListener('change', () => { if (state.calls.length) runOptimize(); });
// toggles: recompute only if that type has no suggestions yet, else just re-render
for (const id of ['resp-on', 'guard-on']) {
  $(id).addEventListener('change', () => {
    const kind = id === 'resp-on' ? 'responder' : 'guardian';
    if ($(id).checked && !state.suggested[kind].length && state.calls.length) runOptimize();
    else refreshStationsAndMetrics();
  });
}
$('boundary-filter').addEventListener('change', () => {
  refreshAll();
  if (state.calls.length && (state.suggested.responder.length || state.suggested.guardian.length)) runOptimize();
});
$('boundary-show').addEventListener('change', () => {
  if (state.boundary) setBoundary(map, state.boundary.feature, $('boundary-show').checked);
});
$('click-add').addEventListener('change', () => {
  map.getCanvas().style.cursor = $('click-add').checked ? 'crosshair' : '';
});

window.app = { state, map, loadDemo, runOptimize, runBoundaryDetect, activeGroups };  // debug/test hook
status('Ready. Load a CAD file or demo data.');
