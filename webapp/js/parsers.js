/* CAD + station file parsing. Column detection ported from modules/cad_parser.py (CV dict). */
'use strict';

const CV = {
  lat: ['latitude','lat','y coord','ycoord','ycoor','addressy','geoy','y_coord','map_y',
        'point_y','gps_lat','gps_latitude','ylat','coord_y','northing','y_wgs','lat_wgs',
        'incident_lat','inc_lat','event_lat','y_coordinate','address_y','ylocation'],
  lon: ['longitude','lon','long','x coord','xcoord','xcoor','addressx','geox','x_coord',
        'map_x','point_x','gps_lon','gps_long','gps_longitude','xlon','coord_x','easting',
        'x_wgs','lon_wgs','incident_lon','inc_lon','event_lon','x_coordinate','address_x','xlocation'],
  name: ['station name','station','name','label','site','facility','location name','title'],
  type: ['call type','call_type','call_type_desc','nature','event_type','type','description','problem'],
  priority: ['call priority','priority level','priority','pri','urgency'],
  date: ['received date','incident date','call date','call creation date','calldatetime','call datetime',
         'timestamp','date','datetime','date time','dispatch date','time received','created'],
};

/* Agency classification — police blue / fire red on the map.
   Motorola exports use single-letter codes (l=law, f=fire, e/m=EMS). */
const AGENCY_TOKENS = {
  police: ['l', 'le', 'p', 'pd', 'police', 'law', 'sheriff', 'so'],
  fire: ['f', 'fd', 'fire'],
  ems: ['e', 'm', 'ems', 'med', 'medical', 'rescue'],
};
const AGENCY_ALL = new Set(Object.values(AGENCY_TOKENS).flat());

function classifyAgency(value) {
  const v = String(value ?? '').trim().toLowerCase();
  if (!v) return 'other';
  for (const [agency, tokens] of Object.entries(AGENCY_TOKENS)) {
    if (tokens.includes(v)) return agency;
  }
  // Motorola combo codes ('lf', 'lfe' = joint law/fire/EMS response) — primary discipline first
  if (/^[lfem]{2,3}$/.test(v)) {
    return { l: 'police', f: 'fire', e: 'ems', m: 'ems' }[v[0]];
  }
  for (const [agency, tokens] of Object.entries(AGENCY_TOKENS)) {
    if (tokens.some(t => t.length > 2 && v.includes(t))) return agency;
  }
  return 'other';
}

/* Find a column whose values are agency codes/names (≥85% of sampled non-empty values). */
function findAgencyColumn(rows, columns) {
  const sample = rows.slice(0, 300);
  let best = null, bestHits = 0;
  for (const col of columns) {
    let hits = 0, n = 0;
    for (const row of sample) {
      const v = String(row[col] ?? '').trim().toLowerCase();
      if (!v) continue;
      n++;
      if (AGENCY_ALL.has(v) || /^[lfem]{2,3}$/.test(v) || /police|fire|sheriff|ems|medical/.test(v)) hits++;
    }
    if (n >= 3 && hits / n >= 0.7 && hits > bestHits) { best = col; bestHits = hits; }
  }
  return best;
}

const compactStr = s => String(s).trim().toLowerCase().replace(/[^a-z0-9]+/g, '');

// Exact compact match wins over substring; earlier patterns rank higher.
function matchColumn(columns, patterns) {
  const compacts = columns.map(compactStr);
  for (const p of patterns) {
    const pc = compactStr(p);
    const i = compacts.indexOf(pc);
    if (i !== -1) return columns[i];
  }
  for (const p of patterns) {
    const pc = compactStr(p);
    const i = compacts.findIndex(c => pc && c.includes(pc));
    if (i !== -1) return columns[i];
  }
  return null;
}

/* All columns matching any pattern, best-ranked first (exact compact match before substring). */
function matchColumnsAll(columns, patterns) {
  const compacts = columns.map(compactStr);
  const hits = [];
  for (const p of patterns) {
    const pc = compactStr(p);
    compacts.forEach((c, i) => {
      if (c === pc && !hits.includes(columns[i])) hits.push(columns[i]);
    });
  }
  for (const p of patterns) {
    const pc = compactStr(p);
    compacts.forEach((c, i) => {
      if (pc && c.includes(pc) && !hits.includes(columns[i])) hits.push(columns[i]);
    });
  }
  return hits;
}

/* Pick the most informative of several candidate label columns. Some CAD exports
   have a degenerate code column (e.g. Motorola 'Call Type' = 'l' on every row)
   next to a descriptive one ('Nature'). Score = distinct values + value length. */
function pickInformativeColumn(rows, candidates) {
  if (candidates.length <= 1) return candidates[0] || null;
  const sample = rows.slice(0, 500);
  let best = candidates[0], bestScore = -1;
  for (const col of candidates) {
    const seen = new Set();
    let lenSum = 0, n = 0;
    for (const row of sample) {
      const v = row[col];
      if (v == null || v === '') continue;
      seen.add(String(v));
      lenSum += String(v).length;
      n++;
    }
    if (!n) continue;
    const score = Math.min(seen.size, 50) * 10 + Math.min(lenSum / n, 30);
    if (score > bestScore) { bestScore = score; best = col; }
  }
  return best;
}

function parseFile(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (ext === 'xlsx' || ext === 'xls') {
    return file.arrayBuffer().then(buf => {
      const wb = XLSX.read(buf, { type: 'array' });
      const sheet = wb.Sheets[wb.SheetNames[0]];
      return XLSX.utils.sheet_to_json(sheet, { defval: null });
    });
  }
  return new Promise((resolve, reject) => {
    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      dynamicTyping: false,
      complete: r => resolve(r.data),
      error: reject,
    });
  });
}

const inLatRange = v => Number.isFinite(v) && v >= -90 && v <= 90 && v !== 0;
const inLonRange = v => Number.isFinite(v) && v >= -180 && v <= 180 && v !== 0;

// Fallback when no named column matches: score numeric columns by value range.
// US-biased: lat 17..72, lon -180..-60.
function sniffCoordColumns(rows, columns) {
  const sample = rows.slice(0, 300);
  let bestLat = null, bestLon = null, bestLatScore = 0, bestLonScore = 0;
  for (const col of columns) {
    let latHits = 0, lonHits = 0, n = 0;
    for (const row of sample) {
      const v = parseFloat(row[col]);
      if (!Number.isFinite(v)) continue;
      n++;
      if (v >= 17 && v <= 72) latHits++;
      if (v >= -180 && v <= -60) lonHits++;
    }
    if (n < sample.length * 0.5) continue;
    if (latHits / n > 0.9 && latHits / n > bestLatScore) { bestLat = col; bestLatScore = latHits / n; }
    if (lonHits / n > 0.9 && lonHits / n > bestLonScore) { bestLon = col; bestLonScore = lonHits / n; }
  }
  return { latCol: bestLat, lonCol: bestLon };
}

function extractPoints(rows, { wantName = false } = {}) {
  if (!rows.length) return { points: [], dropped: 0, latCol: null, lonCol: null };
  const columns = Object.keys(rows[0]);
  let latCol = matchColumn(columns, CV.lat);
  let lonCol = matchColumn(columns, CV.lon);
  if (!latCol || !lonCol) {
    const sniffed = sniffCoordColumns(rows, columns);
    latCol = latCol || sniffed.latCol;
    lonCol = lonCol || sniffed.lonCol;
  }
  if (!latCol || !lonCol || latCol === lonCol) {
    throw new Error(`No lat/lon columns found. Columns: ${columns.join(', ')}`);
  }
  const nameCol = wantName ? matchColumn(columns, CV.name) : null;
  const typeCol = pickInformativeColumn(rows, matchColumnsAll(columns, CV.type));
  const priCol = matchColumn(columns, CV.priority);
  const agencyCol = findAgencyColumn(rows, columns);

  const points = [];
  let dropped = 0;
  for (const row of rows) {
    const lat = parseFloat(row[latCol]);
    const lon = parseFloat(row[lonCol]);
    if (!inLatRange(lat) || !inLonRange(lon)) { dropped++; continue; }
    const p = { lat, lon };
    if (nameCol) p.name = row[nameCol];
    if (typeCol) p.type = row[typeCol];
    if (priCol) p.priority = row[priCol];
    p.agency = agencyCol ? classifyAgency(row[agencyCol]) : 'other';
    points.push(p);
  }
  return { points, dropped, latCol, lonCol, nameCol, agencyCol };
}

/* Station list vs CAD calls: stations are short files with a name/address flavor
   and no per-incident date column. CAD exports are long with dates/priorities. */
function looksLikeStationFile(fileName, rows) {
  if (/station|facilit|substation|site/i.test(fileName)) return true;
  if (!rows.length || rows.length > 200) return false;
  const columns = Object.keys(rows[0]);
  const compacts = columns.map(compactStr);
  if (compacts.some(c => c.includes('capacity') || c.includes('station'))) return true;
  const hasName = !!matchColumn(columns, CV.name);
  const hasAddress = compacts.some(c => c.includes('address'));
  const hasDate = !!matchColumn(columns, CV.date);
  return (hasName || hasAddress) && !hasDate;
}

function pointsToGeoJSON(points, extraProps) {
  return {
    type: 'FeatureCollection',
    features: points.map((p, i) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      properties: { idx: i, name: p.name || null, callType: p.type || null, agency: p.agency || 'other', ...(extraProps || {}) },
    })),
  };
}
