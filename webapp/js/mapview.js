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
const BOUNDARY_COLOR = '#ffb300';

/* Per-station ring palette — hues kept away from the cyan call dots and the
   amber boundary line so every ring reads as its own station. */
const RING_PALETTE = [
  '#ff5252', '#ab47bc', '#66bb6a', '#ffee58', '#ff8a65', '#5c6bc0',
  '#26a69a', '#ec407a', '#d4e157', '#8d6e63', '#f48fb1', '#7e57c2',
];

/* Call dots — every point rendered (no cluster bubbles), CALL_COLOR cyan.
   Size/opacity ladders ported from app.py:7909 (Plotly size≈diameter → radius/2):
   translucent density cloud, adaptive to call volume. */
function pySize(n) { return n > 150000 ? 2 : n > 50000 ? 3 : n > 20000 ? 4 : 5; }
function pyOpacity(n) {
  return n > 150000 ? 0.06 : n > 50000 ? 0.10 : n > 20000 ? 0.18 : n > 10000 ? 0.28 : 0.4;
}

function dotStyle(n) {
  return { core: { radius: pySize(n) / 2 + 0.6, opacity: pyOpacity(n), blur: 0 }, halo: null };
}

function applyDotStyle(map) {
  whenMapReady(map, () => {
    const s = dotStyle(map.__callCount || 0);
    map.setPaintProperty('calls-pts', 'circle-radius', s.core.radius);
    map.setPaintProperty('calls-pts', 'circle-opacity', s.core.opacity);
    map.setPaintProperty('calls-pts', 'circle-blur', s.core.blur);
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
      paint: { 'fill-color': BOUNDARY_COLOR, 'fill-opacity': 0.06 },
    });
    map.addLayer({
      id: 'boundary-line', type: 'line', source: 'boundary',
      paint: { 'line-color': BOUNDARY_COLOR, 'line-width': 2, 'line-dasharray': [3, 2] },
    });
    map.addLayer({
      id: 'calls-pts', type: 'circle', source: 'calls',
      paint: { 'circle-radius': 2.5, 'circle-color': CALL_COLOR, 'circle-opacity': 0.4 },
    });
    map.addLayer({
      id: 'rings-line', type: 'line', source: 'rings',
      paint: { 'line-color': ['get', 'ringColor'], 'line-width': 1.5, 'line-opacity': 0.8 },
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
    applyDotStyle(map);
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
  let n = 0;
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
          ringColor: RING_PALETTE[n++ % RING_PALETTE.length],
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
      ring.properties.ringColor = f.properties.ringColor;
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
