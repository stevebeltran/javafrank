/* MapLibre map: clustered call dots, boundary fill, station groups (existing /
   responder / guardian) with coverage rings. */
'use strict';

/* Background/hidden tabs suspend requestAnimationFrame, which stalls MapLibre's
   style load and render loop entirely. Fall back to a timer when a frame isn't
   serviced promptly; native rAF still wins when the tab is visible. */
(function shimRaf() {
  const nativeRaf = window.requestAnimationFrame.bind(window);
  const nativeCancel = window.cancelAnimationFrame.bind(window);
  window.requestAnimationFrame = cb => {
    let done = false;
    const id = nativeRaf(t => { done = true; cb(t); });
    setTimeout(() => { if (!done) { nativeCancel(id); cb(performance.now()); } }, 120);
    return id;
  };
})();

const EMPTY_FC = { type: 'FeatureCollection', features: [] };

const KIND_COLORS = { existing: '#4caf50', responder: '#e040fb', guardian: '#00bcd4' };
const KIND_COLOR_EXPR = ['match', ['get', 'kind'],
  'existing', KIND_COLORS.existing, 'responder', KIND_COLORS.responder, KIND_COLORS.guardian];

const CALL_COLOR = '#2dc8ff';

/* Dot styles — all render every point (no cluster bubbles), CALL_COLOR cyan.
   Size/opacity ladders ported from app.py:7909 (Plotly size≈diameter → radius/2). */
function pySize(n) { return n > 150000 ? 2 : n > 50000 ? 3 : n > 20000 ? 4 : 5; }
function pyOpacity(n) {
  return n > 150000 ? 0.06 : n > 50000 ? 0.10 : n > 20000 ? 0.18 : n > 10000 ? 0.28 : 0.4;
}

const DOT_STYLES = {
  // 1 — Python match: fixed adaptive size + heavy alpha blending (density cloud)
  1: n => ({
    core: { radius: pySize(n) / 2 + 0.6, opacity: pyOpacity(n), blur: 0 },
    halo: null,
  }),
  // 2 — Glow: soft halo under a brighter core; densities bloom like a heatmap
  2: n => ({
    core: { radius: Math.max(1.2, pySize(n) / 2), opacity: Math.min(0.55, pyOpacity(n) * 3), blur: 0 },
    halo: { radius: pySize(n) * 1.8, opacity: Math.max(0.04, pyOpacity(n) / 2), blur: 1 },
  }),
  // 3 — Crisp: constant small dots, zoom-scaled, higher opacity
  3: () => ({
    core: { radius: ['interpolate', ['linear'], ['zoom'], 8, 1.3, 12, 2.4, 15, 4.5], opacity: 0.45, blur: 0 },
    halo: null,
  }),
};

function applyDotStyle(map, styleId) {
  whenMapReady(map, () => {
    const n = map.__callCount || 0;
    const s = DOT_STYLES[styleId](n);
    map.setPaintProperty('calls-pts', 'circle-radius', s.core.radius);
    map.setPaintProperty('calls-pts', 'circle-opacity', s.core.opacity);
    map.setPaintProperty('calls-pts', 'circle-blur', s.core.blur);
    if (s.halo) {
      map.setPaintProperty('calls-halo', 'circle-radius', s.halo.radius);
      map.setPaintProperty('calls-halo', 'circle-opacity', s.halo.opacity);
      map.setPaintProperty('calls-halo', 'circle-blur', s.halo.blur);
      map.setLayoutProperty('calls-halo', 'visibility', 'visible');
    } else {
      map.setLayoutProperty('calls-halo', 'visibility', 'none');
    }
    map.__dotStyle = styleId;
  });
}

/* Sources/layers exist only after the map 'load' event — queue any earlier calls. */
function whenMapReady(map, fn) {
  if (map.__ready) { fn(); return; }
  (map.__q = map.__q || []).push(fn);
}

function initMap(container) {
  const map = new maplibregl.Map({
    container,
    style: {
      version: 8,
      glyphs: 'https://fonts.openmaptiles.org/{fontstack}/{range}.pbf',
      sources: {
        carto: {
          type: 'raster',
          tiles: [
            'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
            'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
            'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
          ],
          tileSize: 256,
          attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
        },
      },
      layers: [{ id: 'basemap', type: 'raster', source: 'carto' }],
    },
    center: [-98.5, 39.8],
    zoom: 4,
  });
  map.addControl(new maplibregl.NavigationControl(), 'top-right');

  map.on('load', () => {
    map.addSource('boundary', { type: 'geojson', data: EMPTY_FC });
    map.addSource('calls', { type: 'geojson', data: EMPTY_FC });
    map.addSource('rings', { type: 'geojson', data: EMPTY_FC });
    map.addSource('stations', { type: 'geojson', data: EMPTY_FC });

    map.addLayer({
      id: 'boundary-fill', type: 'fill', source: 'boundary',
      paint: { 'fill-color': '#29b6f6', 'fill-opacity': 0.06 },
    });
    map.addLayer({
      id: 'boundary-line', type: 'line', source: 'boundary',
      paint: { 'line-color': '#29b6f6', 'line-width': 2, 'line-dasharray': [3, 2] },
    });
    map.addLayer({
      id: 'calls-halo', type: 'circle', source: 'calls',
      layout: { visibility: 'none' },
      paint: { 'circle-radius': 6, 'circle-color': CALL_COLOR, 'circle-opacity': 0.05, 'circle-blur': 1 },
    });
    map.addLayer({
      id: 'calls-pts', type: 'circle', source: 'calls',
      paint: { 'circle-radius': 2.5, 'circle-color': CALL_COLOR, 'circle-opacity': 0.4 },
    });
    map.addLayer({
      id: 'rings-fill', type: 'fill', source: 'rings',
      paint: { 'fill-color': KIND_COLOR_EXPR, 'fill-opacity': 0.08 },
    });
    map.addLayer({
      id: 'rings-line', type: 'line', source: 'rings',
      paint: { 'line-color': KIND_COLOR_EXPR, 'line-width': 1.5, 'line-opacity': 0.8 },
    });
    map.addLayer({
      id: 'stations-pts', type: 'circle', source: 'stations',
      paint: {
        'circle-radius': 7,
        'circle-color': KIND_COLOR_EXPR,
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2,
      },
    });
    map.addLayer({
      id: 'stations-labels', type: 'symbol', source: 'stations',
      layout: {
        'text-field': ['get', 'label'],
        'text-size': 11, 'text-offset': [0, 1.3], 'text-anchor': 'top',
        'text-font': ['Open Sans Regular'],
      },
      paint: { 'text-color': '#ffffff', 'text-halo-color': '#000000', 'text-halo-width': 1.2 },
    });

    map.on('mouseenter', 'stations-pts', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'stations-pts', () => { map.getCanvas().style.cursor = ''; });

    map.__ready = true;
    (map.__q || []).forEach(fn => fn());
    map.__q = [];
  });
  return map;
}

function setCalls(map, points) {
  whenMapReady(map, () => {
    map.__callCount = points.length;
    map.getSource('calls').setData(pointsToGeoJSON(points));
    applyDotStyle(map, map.__dotStyle || 1);
  });
}

function setBoundary(map, feature, visible) {
  whenMapReady(map, () => {
    map.getSource('boundary').setData(feature || EMPTY_FC);
    for (const id of ['boundary-fill', 'boundary-line']) {
      map.setLayoutProperty(id, 'visibility', visible && feature ? 'visible' : 'none');
    }
  });
}

/* groups: [{stations: [{lat,lon,name}], kind: 'existing'|'responder'|'guardian',
             radius: miles, perStation?: counts}] */
function buildStationFeatures(groups) {
  const feats = [];
  for (const g of groups) {
    g.stations.forEach((s, i) => {
      feats.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        properties: {
          kind: g.kind,
          idx: i,
          sid: s.id || null,
          label: s.name ||
            (g.kind === 'responder' ? `R${i + 1}` : g.kind === 'guardian' ? `G${i + 1}` : `Station ${i + 1}`),
          covers: g.perStation ? g.perStation[i] : null,
          radius: g.radius,
        },
      });
    });
  }
  return feats;
}

function setStations(map, groups) {
  whenMapReady(map, () => {
    const feats = buildStationFeatures(groups);
    map.getSource('stations').setData({ type: 'FeatureCollection', features: feats });

    const rings = feats.map(f => {
      const ring = turf.circle(f.geometry.coordinates, f.properties.radius, { steps: 48, units: 'miles' });
      ring.properties.kind = f.properties.kind;
      return ring;
    });
    map.getSource('rings').setData({ type: 'FeatureCollection', features: rings });
  });
}

function fitToPoints(map, points, pad = 60) {
  if (!points.length) return;
  let minX = 180, minY = 90, maxX = -180, maxY = -90;
  for (const p of points) {
    if (p.lon < minX) minX = p.lon;
    if (p.lon > maxX) maxX = p.lon;
    if (p.lat < minY) minY = p.lat;
    if (p.lat > maxY) maxY = p.lat;
  }
  map.fitBounds([[minX, minY], [maxX, maxY]], { padding: pad, duration: 600, maxZoom: 13 });
}
