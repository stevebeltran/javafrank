/* Station placement: k-means (k-means++ seeding) + greedy max-coverage, plus coverage stats.
   Distances via equirectangular projection in miles — accurate enough at city scale, fast. */
'use strict';

const EARTH_R_MI = 3958.8;

function projectMiles(points) {
  // Project around mean latitude so x/y are in miles; returns [{x,y},...]
  const meanLat = points.reduce((s, p) => s + p.lat, 0) / points.length;
  const cosLat = Math.cos(meanLat * Math.PI / 180);
  const kx = (Math.PI / 180) * EARTH_R_MI * cosLat;
  const ky = (Math.PI / 180) * EARTH_R_MI;
  return { pts: points.map(p => ({ x: p.lon * kx, y: p.lat * ky })), kx, ky };
}

const dist2 = (a, b) => { const dx = a.x - b.x, dy = a.y - b.y; return dx * dx + dy * dy; };

function kmeans(points, k, iters = 60) {
  if (points.length <= k) return points.map(p => ({ lat: p.lat, lon: p.lon }));
  const { pts, kx, ky } = projectMiles(points);

  // k-means++ seeding (deterministic-ish: seeded from index stride for repeatability)
  const centers = [pts[Math.floor(pts.length / 2)]];
  while (centers.length < k) {
    let bestIdx = 0, bestD = -1;
    // choose point with max distance-to-nearest-center (farthest-first; deterministic)
    for (let i = 0; i < pts.length; i += Math.max(1, Math.floor(pts.length / 2000))) {
      let d = Infinity;
      for (const c of centers) d = Math.min(d, dist2(pts[i], c));
      if (d > bestD) { bestD = d; bestIdx = i; }
    }
    centers.push({ ...pts[bestIdx] });
  }

  const assign = new Int32Array(pts.length);
  for (let it = 0; it < iters; it++) {
    let changed = false;
    for (let i = 0; i < pts.length; i++) {
      let best = 0, bd = Infinity;
      for (let c = 0; c < k; c++) {
        const d = dist2(pts[i], centers[c]);
        if (d < bd) { bd = d; best = c; }
      }
      if (assign[i] !== best) { assign[i] = best; changed = true; }
    }
    const sx = new Float64Array(k), sy = new Float64Array(k), n = new Int32Array(k);
    for (let i = 0; i < pts.length; i++) {
      const c = assign[i];
      sx[c] += pts[i].x; sy[c] += pts[i].y; n[c]++;
    }
    for (let c = 0; c < k; c++) {
      if (n[c] > 0) { centers[c].x = sx[c] / n[c]; centers[c].y = sy[c] / n[c]; }
    }
    if (!changed) break;
  }
  return centers.map(c => ({ lat: c.y / ky, lon: c.x / kx }));
}

/* Greedy max-coverage: candidates = dense k-means centroids; pick k that cover most
   uncovered calls within radius. Beats plain k-means when demand is multi-modal. */
function greedyMaxCoverage(points, k, radiusMiles, nCandidates = 60) {
  const candidates = kmeans(points, Math.min(nCandidates, points.length));
  const { pts, kx, ky } = projectMiles(points);
  const cand = candidates.map(c => ({ x: c.lon * kx, y: c.lat * ky }));
  const r2 = radiusMiles * radiusMiles;

  const covered = new Uint8Array(pts.length);
  const chosen = [];
  for (let round = 0; round < k; round++) {
    let bestC = -1, bestGain = -1;
    for (let c = 0; c < cand.length; c++) {
      if (cand[c].used) continue;
      let gain = 0;
      for (let i = 0; i < pts.length; i++) {
        if (!covered[i] && dist2(pts[i], cand[c]) <= r2) gain++;
      }
      if (gain > bestGain) { bestGain = gain; bestC = c; }
    }
    if (bestC === -1) break;
    cand[bestC].used = true;
    chosen.push(candidates[bestC]);
    for (let i = 0; i < pts.length; i++) {
      if (!covered[i] && dist2(pts[i], cand[bestC]) <= r2) covered[i] = 1;
    }
  }
  return chosen;
}

/* Drop geocode outliers far from the data's bulk: distance from the median
   center beyond max(25 mi, 4×p90) is discarded. Keeps legit county-wide
   spread, kills wrong-state geocodes. */
function filterOutliers(points) {
  if (points.length < 20) return { kept: points, removed: 0 };
  const mid = arr => arr[arr.length >> 1];
  const med = {
    lat: mid([...points.map(p => p.lat)].sort((a, b) => a - b)),
    lon: mid([...points.map(p => p.lon)].sort((a, b) => a - b)),
  };
  const { pts } = projectMiles([med, ...points]);
  const c = pts[0];
  const dists = pts.slice(1).map(p => Math.sqrt(dist2(p, c)));
  const p90 = [...dists].sort((a, b) => a - b)[Math.floor(dists.length * 0.9)];
  const limit = Math.max(25, p90 * 4);
  const kept = [];
  let removed = 0;
  points.forEach((p, i) => { if (dists[i] <= limit) kept.push(p); else removed++; });
  return { kept, removed, limitMiles: limit };
}

/* Coverage by ANY of several station groups, each with its own radius.
   groups: [{stations: [{lat,lon}], radius: miles}] */
function unionCoverageStats(points, groups) {
  const active = groups.filter(g => g.stations.length);
  if (!points.length || !active.length) return null;
  const { pts, kx, ky } = projectMiles(points);
  const sets = active.map(g => ({
    r2: g.radius * g.radius,
    sta: g.stations.map(s => ({ x: s.lon * kx, y: s.lat * ky })),
  }));
  let covered = 0;
  for (let i = 0; i < pts.length; i++) {
    let hit = false;
    for (const set of sets) {
      for (const s of set.sta) {
        if (dist2(pts[i], s) <= set.r2) { hit = true; break; }
      }
      if (hit) break;
    }
    if (hit) covered++;
  }
  return { total: pts.length, covered, coveredPct: 100 * covered / pts.length };
}

function coverageStats(points, stations, radiusMiles) {
  if (!points.length || !stations.length) return null;
  const { pts, kx, ky } = projectMiles(points);
  const sta = stations.map(s => ({ x: s.lon * kx, y: s.lat * ky }));
  const r2 = radiusMiles * radiusMiles;
  let covered = 0, sumD = 0, maxD = 0;
  const perStation = new Int32Array(sta.length);
  for (let i = 0; i < pts.length; i++) {
    let bd = Infinity, bj = 0;
    for (let j = 0; j < sta.length; j++) {
      const d = dist2(pts[i], sta[j]);
      if (d < bd) { bd = d; bj = j; }
    }
    const d = Math.sqrt(bd);
    if (bd <= r2) { covered++; perStation[bj]++; }
    sumD += d;
    if (d > maxD) maxD = d;
  }
  return {
    total: pts.length,
    covered,
    coveredPct: 100 * covered / pts.length,
    avgDistMi: sumD / pts.length,
    maxDistMi: maxD,
    perStation: Array.from(perStation),
  };
}
