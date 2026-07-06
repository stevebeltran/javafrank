/* Standalone HTML report export — clustered call points, legend, station placement.
   Self-contained except MapLibre + CARTO tiles from CDN (viewer needs internet). */
'use strict';

async function assetDataURL(url) {
  try {
    const blob = await fetch(url).then(r => r.blob());
    return await new Promise(res => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.readAsDataURL(blob);
    });
  } catch { return ''; }
}

const AGENCY_CODE = { police: 0, fire: 1, ems: 2, other: 3 };

/* groups: [{stations, kind, radius, perStation?}] — same shape as main.js activeGroups().
   dot: {core:{radius,opacity,blur}, halo:null|{...}} — snapshot of the chosen dot style. */
async function exportHtmlReport(state, groups, metricsHtml, dot) {
  const [logo, rs] = await Promise.all([
    assetDataURL('assets/brinc_logo.png'),
    assetDataURL('assets/responder_station.png'),
  ]);

  // Compact calls: [lat, lon, agencyCode] with 5-decimal precision (~1 m)
  const calls = state.calls.map(p =>
    [+p.lat.toFixed(5), +p.lon.toFixed(5), AGENCY_CODE[p.agency] ?? 3]);

  const stationFeats = { type: 'FeatureCollection', features: buildStationFeatures(groups) };
  const rings = {
    type: 'FeatureCollection',
    features: stationFeats.features.map(f => {
      const ring = turf.circle(f.geometry.coordinates, f.properties.radius, { steps: 48, units: 'miles' });
      ring.properties.kind = f.properties.kind;
      ring.properties.ringColor = f.properties.ringColor;
      return ring;
    }),
  };

  const lats = state.calls.map(p => p.lat), lons = state.calls.map(p => p.lon);
  const bounds = state.calls.length
    ? [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]]
    : [[-125, 24], [-66, 49]];

  const radiusLabel = groups.map(g => `${GROUP_TITLES?.[g.kind] || g.kind} ${g.radius} mi`).join(' · ');
  const payload = {
    calls,
    stations: stationFeats,
    rings,
    boundary: state.boundary ? state.boundary.feature : null,
    bounds,
    jurisdiction: state.boundary ? state.boundary.name : 'Unknown jurisdiction',
    radiusLabel,
    generated: new Date().toLocaleString(),
    dot: dot || { core: { radius: 2.5, opacity: 0.4, blur: 0 }, halo: null },
  };

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BRINC DFR Site Survey — ${payload.jurisdiction}</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; }
  html, body { height: 100%; }
  body { font: 14px/1.4 -apple-system, "Segoe UI", Roboto, sans-serif; background: #101418; color: #dbe4ec; }
  #map { position: absolute; inset: 0; }
  .panel { position: absolute; background: rgba(24,30,36,.92); border: 1px solid #2c3742; border-radius: 8px; padding: 10px 14px; z-index: 5; }
  #hdr { top: 14px; left: 14px; }
  #hdr img { width: 110px; filter: invert(1); display: block; margin-bottom: 6px; }
  #hdr .t { font-size: 15px; font-weight: 700; }
  #hdr .s { font-size: 11.5px; color: #8496a5; }
  #legend { bottom: 28px; left: 14px; font-size: 12px; }
  #legend div { margin: 3px 0; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: -1px; }
  #metrics { top: 14px; right: 14px; max-width: 260px; font-size: 12px; }
  #metrics table { border-collapse: collapse; width: 100%; }
  #metrics td { padding: 2px 0; border-bottom: 1px solid #2c3742; }
  #metrics td:last-child { text-align: right; font-weight: 700; }
  #metrics tr.head td { color: #8496a5; border-bottom: 1px solid #29b6f6; padding-top: 6px; }
  #rs { position: absolute; right: 16px; bottom: 28px; width: 170px; mix-blend-mode: screen; opacity: .92; pointer-events: none; z-index: 5; }
</style>
</head>
<body>
<div id="map"></div>
<div class="panel" id="hdr">
  ${logo ? `<img src="${logo}" alt="BRINC">` : ''}
  <div class="t">DFR Site Survey — ${payload.jurisdiction}</div>
  <div class="s">${payload.calls.length.toLocaleString()} calls · ${payload.radiusLabel} · ${payload.generated}</div>
</div>
<div class="panel" id="legend">
  <div><span class="sw" style="background:#2dc8ff"></span>Call for service</div>
  <div><span class="sw" style="background:#4caf50"></span>Existing station</div>
  <div><span class="sw" style="background:#e040fb"></span>Responder station</div>
  <div><span class="sw" style="background:#00bcd4"></span>Guardian station</div>
  <div style="color:#8496a5;font-size:11px">Ring = coverage radius, unique color per station</div>
</div>
${metricsHtml ? `<div class="panel" id="metrics"><table>${metricsHtml}</table></div>` : ''}
${rs ? `<img id="rs" src="${rs}" alt="BRINC Responder Station">` : ''}
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"><\/script>
<script>
const DATA = ${JSON.stringify(payload)};
const KIND_COLOR = ['match', ['get', 'kind'], 'existing', '#4caf50', 'responder', '#e040fb', '#00bcd4'];
const CALL_COLOR = '#2dc8ff';
const callsFC = {
  type: 'FeatureCollection',
  features: DATA.calls.map(c => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [c[1], c[0]] },
    properties: {},
  })),
};
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    glyphs: 'https://fonts.openmaptiles.org/{fontstack}/{range}.pbf',
    sources: { carto: { type: 'raster', tiles: [
      'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
      'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
    ], tileSize: 256, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' } },
    layers: [{ id: 'basemap', type: 'raster', source: 'carto' }],
  },
  bounds: DATA.bounds,
  fitBoundsOptions: { padding: 60 },
});
map.addControl(new maplibregl.NavigationControl(), 'bottom-left');
map.on('load', () => {
  if (DATA.boundary) {
    map.addSource('boundary', { type: 'geojson', data: DATA.boundary });
    map.addLayer({ id: 'b-fill', type: 'fill', source: 'boundary', paint: { 'fill-color': '#ffb300', 'fill-opacity': .06 } });
    map.addLayer({ id: 'b-line', type: 'line', source: 'boundary', paint: { 'line-color': '#ffb300', 'line-width': 2, 'line-dasharray': [3, 2] } });
  }
  map.addSource('calls', { type: 'geojson', data: callsFC });
  if (DATA.dot.halo) {
    map.addLayer({ id: 'calls-halo', type: 'circle', source: 'calls', paint: {
      'circle-radius': DATA.dot.halo.radius, 'circle-color': CALL_COLOR,
      'circle-opacity': DATA.dot.halo.opacity, 'circle-blur': DATA.dot.halo.blur } });
  }
  map.addLayer({ id: 'calls', type: 'circle', source: 'calls', paint: {
    'circle-radius': DATA.dot.core.radius, 'circle-color': CALL_COLOR,
    'circle-opacity': DATA.dot.core.opacity, 'circle-blur': DATA.dot.core.blur } });
  map.addSource('rings', { type: 'geojson', data: DATA.rings });
  map.addLayer({ id: 'rings-f', type: 'fill', source: 'rings', paint: {
    'fill-color': ['get', 'ringColor'], 'fill-opacity': .08 } });
  map.addLayer({ id: 'rings-l', type: 'line', source: 'rings', paint: {
    'line-color': ['get', 'ringColor'], 'line-width': 1.5, 'line-opacity': .8 } });
  map.addSource('stations', { type: 'geojson', data: DATA.stations });
  map.addLayer({ id: 'sta', type: 'circle', source: 'stations', paint: {
    'circle-radius': 7, 'circle-color': KIND_COLOR,
    'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
  map.addLayer({ id: 'sta-lbl', type: 'symbol', source: 'stations', layout: {
    'text-field': ['get', 'label'], 'text-size': 11, 'text-offset': [0, 1.3],
    'text-anchor': 'top', 'text-font': ['Open Sans Regular'] },
    paint: { 'text-color': '#fff', 'text-halo-color': '#000', 'text-halo-width': 1.2 } });
});
<\/script>
</body>
</html>`;

  const blob = new Blob([html], { type: 'text/html' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  const slug = payload.jurisdiction.replace(/[^a-z0-9]+/gi, '_').toLowerCase();
  a.download = `brinc_site_survey_${slug}.html`;
  a.click();
  URL.revokeObjectURL(a.href);
  return payload.calls.length;
}
