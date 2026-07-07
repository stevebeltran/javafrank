/* Jurisdiction boundary lookup — Census TIGERweb ArcGIS REST (no key, CORS-enabled).
   Place first, county fallback, Nominatim last resort. Layer IDs discovered at
   runtime from the service metadata so hardcoded IDs can't rot. */
'use strict';

const TIGER = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb';
const _layerCache = {};

async function fetchJsonRetry(url, tries = 3, delayMs = 600) {
  for (let i = 0; ; i++) {
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (e) {
      if (i >= tries - 1) throw e;
      await new Promise(res => setTimeout(res, delayMs * (i + 1)));
    }
  }
}

async function tigerFindLayer(service, nameRegex) {
  const key = service + nameRegex;
  if (_layerCache[key] !== undefined) return _layerCache[key];
  const meta = await fetchJsonRetry(`${TIGER}/${service}/MapServer?f=json`);
  const layer = (meta.layers || []).find(l => nameRegex.test(l.name) && !/label/i.test(l.name));
  _layerCache[key] = layer ? layer.id : null;
  return _layerCache[key];
}

function esriToGeoJSON(feature) {
  // Minimal esri-json → GeoJSON polygon conversion (query fallback when f=geojson unsupported)
  const rings = feature.geometry && feature.geometry.rings;
  if (!rings) return null;
  return {
    type: 'Feature',
    properties: feature.attributes || {},
    geometry: rings.length === 1
      ? { type: 'Polygon', coordinates: rings }
      : { type: 'MultiPolygon', coordinates: rings.map(r => [r]) },
  };
}

async function tigerQueryPoint(service, layerId, lat, lon) {
  const params = new URLSearchParams({
    geometry: `${lon},${lat}`,
    geometryType: 'esriGeometryPoint',
    inSR: '4326',
    spatialRel: 'esriSpatialRelIntersects',
    outFields: 'NAME,GEOID',
    returnGeometry: 'true',
    outSR: '4326',
    f: 'geojson',
  });
  const url = `${TIGER}/${service}/MapServer/${layerId}/query?${params}`;
  const data = await fetchJsonRetry(url);
  if (data.features && data.features.length) {
    const f = data.features[0];
    return f.geometry ? f : esriToGeoJSON(f);
  }
  return null;
}

async function nominatimBoundary(lat, lon) {
  const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}` +
    `&format=jsonv2&polygon_geojson=1&zoom=10`;
  const data = await fetch(url).then(r => r.json());
  if (data.geojson && /polygon/i.test(data.geojson.type)) {
    return {
      type: 'Feature',
      properties: { NAME: data.name || data.display_name },
      geometry: data.geojson,
    };
  }
  return null;
}

/* Forward geocode "City, ST" → boundary polygon + population (when OSM has it).
   Returns {feature, name, population|null} or null. */
async function geocodeCity(query) {
  const url = 'https://nominatim.openstreetmap.org/search?' + new URLSearchParams({
    q: `${query}, USA`, format: 'jsonv2', polygon_geojson: '1', extratags: '1', limit: '1',
  });
  const data = await fetchJsonRetry(url);
  const hit = (data || [])[0];
  if (!hit || !hit.geojson || !/polygon/i.test(hit.geojson.type)) return null;
  const population = (hit.extratags && parseInt(hit.extratags.population, 10)) || null;
  return {
    feature: { type: 'Feature', properties: { NAME: hit.name || hit.display_name }, geometry: hit.geojson },
    name: hit.name || query,
    population,
  };
}

function medianCenter(points) {
  const lats = points.map(p => p.lat).sort((a, b) => a - b);
  const lons = points.map(p => p.lon).sort((a, b) => a - b);
  const mid = arr => arr[Math.floor(arr.length / 2)];
  return { lat: mid(lats), lon: mid(lons) };
}

/* Fraction of calls (sampled, ≤1500) inside a boundary — cheap test for
   "is this polygon actually the jurisdiction that produced these calls?" */
function boundaryCoverageFrac(points, feature) {
  if (!points.length) return 0;
  let f = feature;
  try { f = turf.simplify(feature, { tolerance: 0.001, highQuality: false }); } catch {}
  const step = Math.max(1, Math.floor(points.length / 1500));
  let hit = 0, tot = 0;
  for (let i = 0; i < points.length; i += step) {
    tot++;
    if (turf.booleanPointInPolygon([points[i].lon, points[i].lat], f)) hit++;
  }
  return hit / tot;
}

/* Returns {feature, name, kind} or null. Prefers the city/place polygon, but
   county sheriff / parish CAD data usually centers inside some incorporated
   city — when the place covers under half the calls, fall back to whichever
   of place/county actually contains more of them. */
async function detectBoundary(points) {
  const c = medianCenter(points);
  let place = null;
  try {
    const placeLayer = await tigerFindLayer('Places_CouSub_ConCity_SubMCD', /incorporated places/i);
    if (placeLayer !== null) {
      const f = await tigerQueryPoint('Places_CouSub_ConCity_SubMCD', placeLayer, c.lat, c.lon);
      if (f) place = { feature: f, name: f.properties.NAME, kind: 'place' };
    }
  } catch (e) { console.warn('TIGER place lookup failed', e); }
  const placeFrac = place ? boundaryCoverageFrac(points, place.feature) : 0;
  if (place && placeFrac >= 0.5) return place;
  try {
    const countyLayer = await tigerFindLayer('State_County', /^counties$/i);
    if (countyLayer !== null) {
      const f = await tigerQueryPoint('State_County', countyLayer, c.lat, c.lon);
      if (f && boundaryCoverageFrac(points, f) > placeFrac) {
        return { feature: f, name: f.properties.NAME, kind: 'county' };
      }
    }
  } catch (e) { console.warn('TIGER county lookup failed', e); }
  if (place) return place;
  try {
    const f = await nominatimBoundary(c.lat, c.lon);
    if (f) return { feature: f, name: f.properties.NAME, kind: 'osm' };
  } catch (e) { console.warn('Nominatim fallback failed', e); }
  return null;
}

function filterPointsToBoundary(points, boundaryFeature) {
  const bbox = turf.bbox(boundaryFeature);
  const [minX, minY, maxX, maxY] = bbox;
  return points.filter(p => {
    if (p.lon < minX || p.lon > maxX || p.lat < minY || p.lat > maxY) return false;
    return turf.booleanPointInPolygon([p.lon, p.lat], boundaryFeature);
  });
}
