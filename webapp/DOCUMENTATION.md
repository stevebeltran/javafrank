# BRINC DFR Site Survey — Web App Documentation

_Comprehensive reference for the frontend-only JavaScript port. Last updated: 2026-07-06._

---

## 1. What this is

A zero-build, frontend-only web application for Drone-First-Responder (DFR) site
surveys. It is a port of the core workflow from the Python/Streamlit
"Frankenstein" app (`app.py` + `modules/`) with **no Python, no server-side
code, no secrets, and no build step**. Everything runs in the browser.

**Core workflow:** upload CAD calls-for-service data and an optional station
list → auto-detect the jurisdiction boundary → visualize calls on a dark map →
place/optimize Responder and Guardian drone stations → compare coverage
metrics → export a self-contained HTML report.

**Repo:** https://github.com/stevebeltran/javafrank (`webapp/` folder, branch
`main`). Original Streamlit app lives at the repo root and is untouched.

---

## 2. Running it

```
npx --yes http-server webapp -p 8321 -c-1
# → http://localhost:8321
```

Any static file server works. Deploying = copy the `webapp/` folder to GitHub
Pages / Netlify / Cloudflare Pages. The only runtime network dependencies are
CDN libraries, CARTO basemap tiles, and the Census TIGERweb API — all keyless.

`.claude/launch.json` contains the same server config for the Claude Code
preview panel.

---

## 3. File map

| File | Purpose |
|---|---|
| `index.html` | Single page: sidebar (collapsible sections 1–4) + map. Pinned CDN libs. |
| `css/style.css` | Dark theme, panels, legend, dropzone, details/summary styling. |
| `js/parsers.js` | File parsing + column detection + agency classification + station-vs-CAD detection. |
| `js/optimize.js` | Geometry/math: projection, k-means, greedy max-coverage, coverage stats, union coverage, outlier filter. |
| `js/boundary.js` | Jurisdiction boundary lookup (TIGERweb → Nominatim fallback) + boundary point filter. |
| `js/mapview.js` | MapLibre setup, all sources/layers, dot style, station/ring rendering, rAF shim. |
| `js/export.js` | Standalone HTML report builder (blob download). |
| `js/main.js` | State, UI wiring, upload routing, click-to-add, demo data, metrics table. |
| `assets/brinc_logo.png` | BRINC wordmark (from repo `logo.png`), CSS-inverted to white. |
| `assets/responder_station.png` | Responder Station render (from repo `gigs.png`), black bg dropped via `mix-blend-mode: screen`. |
| `README.md` | Short feature summary. |

Script load order matters: `parsers → export → optimize → boundary → mapview → main`.
All modules are plain scripts sharing the global scope (no bundler/imports).

### CDN dependencies (pinned)

- MapLibre GL 4.7.1 — map rendering
- Turf 7.1.0 — circles, bbox, point-in-polygon
- PapaParse 5.4.1 — CSV parsing
- SheetJS (xlsx) 0.18.5 — Excel parsing

---

## 4. Data ingestion (`parsers.js`)

### 4.1 One dropzone, auto-detected file kind

Section 1 accepts CAD calls **and** station lists (multi-file drop OK).
`looksLikeStationFile()` decides:

1. Filename contains `station|facilit|substation|site` → station list.
2. ≤200 rows **and** (`capacity`/`station` column, or a name/address column
   with no date column) → station list.
3. Otherwise → CAD calls.

When both are dropped together, stations are processed first so the CAD
optimization sees them.

### 4.2 Column detection

Ported from `modules/cad_parser.py` (`CV` dict). Matching normalizes column
names to compact form (`Y Coord` → `ycoord`) and tries exact matches before
substring matches. Recognized variants include:

- **lat:** latitude, lat, y coord, ycoord, geoy, map_y, gps_lat, northing, …
- **lon:** longitude, lon, long, x coord, xcoord, geox, map_x, easting, …
- **name:** station name, station, name, label, site, facility, …
- **type:** call type, nature, event_type, description, problem, …
- **date:** received date, incident date, timestamp, datetime, … (used only for
  station-vs-CAD detection)

**Fallback:** if no named lat/lon column matches, numeric columns are sniffed
by value range (US-biased: lat 17..72, lon −180..−60, ≥90% of sampled values).

**Informative-column pick:** when several "type" columns match (e.g. Motorola
exports have a degenerate `Call Type` = `l` on every row next to a descriptive
`Nature`), the column with the most distinct/longest values over a 500-row
sample wins.

### 4.3 Agency classification

Each call gets `agency ∈ {police, fire, ems, other}`:

- A column qualifies as the agency column when ≥70% of sampled non-empty
  values are agency tokens (`l`, `f`, `e`, `pd`, `fire`, `police`, …) or
  Motorola combo codes.
- Combo codes (`lf`, `lfe` = joint law/fire/EMS response) classify by first
  letter: `l`→police, `f`→fire, `e/m`→EMS.
- Nampa Motorola file result: 78,522 police / 3 fire / 99 other (`i` info calls).

(Currently agency affects only data plumbing/export payload — map dots are a
single cyan color; see §6.)

### 4.4 Row filtering

Two passes:

1. **Bad coordinates** — rows outside valid lat/lon ranges (or 0/blank) are
   dropped during extraction.
2. **Outliers** (`filterOutliers`, optimize.js) — distance of every point from
   the *median* center; anything beyond `max(25 mi, 4 × 90th-percentile)` is
   discarded. Kills wrong-state geocode errors while keeping legitimate
   county-wide spread. Skipped for files under 20 rows.

Dropped counts are reported in the Data section info line and excluded from
the map, metrics, optimization, boundary detection, and zoom fit.

### 4.5 Validated real-world files

- `3.2025-3.2026 CFS - Motorola Data (2).csv` (Nampa PD, 79,550 rows) →
  78,624 valid calls, `Y Coord`/`X Coord` detected, types from `Nature`.
- `stations.csv` (2 stations, `NAME`/`Latitude`/`Longitude`/`CAPACITY`).

---

## 5. Boundary lookup (`boundary.js`)

Auto-runs after a CAD load ("Re-detect boundary" button re-runs it).

1. Median center of all calls is computed (robust to residual outliers).
2. **Census TIGERweb** ArcGIS REST (keyless, CORS-enabled):
   - Service `Places_CouSub_ConCity_SubMCD` → *Incorporated Places* layer
     (layer ID discovered at runtime from service metadata, never hardcoded).
   - Point-intersect query, `f=geojson`, with esri-JSON → GeoJSON fallback.
   - If no city/place contains the point → `State_County` service, *Counties*
     layer.
3. **Nominatim** (OSM) reverse geocode with `polygon_geojson=1` as last resort.
4. All fetches retry 3× with backoff (transient DNS/network).

Result renders as a dashed blue polygon with 6% fill. Controls:

- **Filter calls to boundary** (default on) — spatial filter via Turf
  point-in-polygon with bbox pre-check; excluded calls are counted in the info
  line and ignored by metrics/optimization.
- **Show boundary** — visibility toggle.

The Boundary section auto-collapses once a boundary is found.

Verified lookups: Naperville city (demo), Nampa city (real data).

---

## 6. Map rendering (`mapview.js`)

MapLibre GL with an inline style (no style server):

- **Basemap:** CARTO `dark_all` raster tiles (keyless, OSM attribution).
- **Glyphs:** `fonts.openmaptiles.org` (required for station text labels).

Layer stack (bottom → top):
`boundary-fill, boundary-line, calls-pts, rings-fill, rings-line, stations-pts, stations-labels`.

### 6.1 Call dots — "Python match" style (locked in)

Every point renders (no clustering, no count bubbles). Color `#2dc8ff`.
Size/opacity ladders ported from `app.py:7909` (Plotly `size` ≈ diameter →
MapLibre radius = size/2 + 0.6):

| Call count | radius px | opacity |
|---|---|---|
| >150k | 1.6 | 0.06 |
| >50k | 2.1 | 0.10 |
| >20k | 2.6 | 0.18 |
| >10k | 3.1 | 0.28 |
| ≤10k | 3.1 | 0.40 |

Dense areas read as a cyan glow through alpha stacking — matches the original
Plotly look. Style re-applies automatically on every `setCalls`.

### 6.2 Stations and rings

Three kinds, each with a dot color, and **every coverage ring matches its
center dot's color**:

| Kind | Color | Source | Ring radius |
|---|---|---|---|
| `existing` | green `#4caf50` | uploaded station file / demo HQ | responder radius input |
| `responder` | magenta `#e040fb` | optimizer + manual placements | responder radius input |
| `guardian` | teal `#00bcd4` | optimizer + manual placements | guardian radius input |

Rings are Turf circles (48 steps, miles) rebuilt on every refresh, so editing
a radius input redraws them immediately — even before any optimization run.
Labels: uploaded names, `R1…`/`G1…` for suggestions, `Manual N` (renamable)
for click-placed.

An **on-map legend** (bottom-left panel) lists call color + all three station
kinds. The BRINC wordmark sits top-left of the sidebar; the Responder Station
render overlays bottom-right of the map (`mix-blend-mode: screen` removes its
black background).

### 6.3 Hidden-tab rAF shim

MapLibre's render loop stalls when the browser tab is hidden (rAF suspended).
A shim falls back to a 120 ms timer per frame when a native frame isn't
serviced — native rAF still wins when visible. Needed for headless
verification; harmless in normal use.

---

## 7. Station optimization (`optimize.js`, section 3 UI)

### 7.1 Distance model

`projectMiles()` — equirectangular projection around the mean latitude; all
distances in miles. Accurate at city scale and much faster than haversine per
pair.

### 7.2 Two independent station types

Responder (default 3 stations, 2 mi radius) and Guardian (default 1 station,
8 mi radius). Each has: enable checkbox, count slider (**0–10**, 0 = none),
and an editable radius input. Toggles hide only the *suggested* sets —
manually placed stations always display.

### 7.3 Algorithms (Mode select)

- **K-means centroids** — k-means with farthest-first (deterministic
  k-means++-style) seeding, 60 iterations max, early exit on convergence.
  Minimizes average distance.
- **Max coverage (greedy)** — builds ~60 candidate sites via dense k-means,
  then greedily picks the site covering the most currently-uncovered calls
  within the radius, k times. Better when demand is multi-modal.

Optimization re-runs automatically on any control change (count, radius, mode,
toggle, boundary filter). Suggestions recompute over the *filtered* call set.

**Measured performance (100k calls):** k-means ≈ 135 ms, greedy ≈ 1.6 s,
coverage stats ≈ 32 ms. 76k-call demo optimizes in <100 ms.

### 7.4 Metrics (sidebar table)

Per active group (existing / responder / guardian):

- **Calls within R mi** — % of calls with nearest group station ≤ radius
- **Avg dist to nearest** / **Max dist**
- Per-station covered-call counts (shown in station popups)

When 2+ groups are active, a **Combined** row shows union coverage — a call
counts as covered if *any* group covers it at that group's own radius.

### 7.5 Manual stations

- **Click map to add** checkbox + **Type** select (Responder/Guardian). Click
  drops `Manual N` with that type's color/ring/radius; crosshair cursor while
  armed.
- Click any manual/uploaded station (add-mode off) → popup with kind, radius,
  covered-call count, **rename** (prompt) and **remove** links. Suggested
  stations show info only.

---

## 8. Demo data

"Load demo data" generates synthetic Naperville, IL calls: 3 Gaussian hotspots
+ uniform noise, deterministic seeded PRNG. Volume = **60% of city population**
(149,540 → 89,724 calls), the annual-CFS rule of thumb. Adds one existing
station (HQ). Exercises the full pipeline including live TIGERweb boundary
lookup.

---

## 9. HTML export (`export.js`)

"Export HTML report" downloads
`brinc_site_survey_<jurisdiction>.html` (~3 MB at 76k calls), fully
self-contained except MapLibre CDN + basemap tiles:

- All call points (compact `[lat, lon, agencyCode]` at 5-decimal precision),
  rendered with the same Python-match dot style (style snapshot embedded).
- Boundary polygon, all active station groups with matching-color rings
  (radii as configured at export time).
- Legend, metrics table snapshot, jurisdiction + timestamp header.
- BRINC logo and Responder Station render embedded as base64.

---

## 10. UI layout

Sidebar sections (1 and 2 are collapsible `<details>`, auto-collapse when done):

1. **Data** — dropzone, demo button, info lines, color legend. Collapses after
   a successful upload.
2. **Boundary** — detected name, filter/show toggles, re-detect. Collapses
   after detection.
3. **Station Optimization** — responder block, guardian block, mode,
   click-to-add row, Suggest button.
4. **Export** — HTML report button.

Metrics table appears between 3 and 4 when data exists. Status line pinned at
sidebar bottom (errors red, success green).

---

## 11. Design decisions & gotchas

- **No build step** on purpose — edit a file, refresh. All CDN versions pinned.
- **Globals over modules** — simple for this size; load order in index.html
  is the only contract.
- **Map-ready queue** (`whenMapReady`) — MapLibre sources exist only after the
  `load` event; all setters queue until then (fixes crash when a file was
  dropped before map init finished).
- **TIGERweb service name** is `Places_CouSub_ConCity_SubMCD` (not
  `…SubMinCD`); layer IDs are looked up at runtime because vintages shift.
- **Radius inputs are live** — `input` event redraws rings, `change` re-runs
  optimization. Rings always match the current input value.
- **Stations carry `id` + `kind`** — popups resolve stations by id (survives
  reordering); uploaded = `existing`, click-placed = chosen type with
  `manual: true`.
- **Windows/OneDrive path** — repo lives under Google Drive sync; git works
  but expect LF→CRLF warnings (harmless).
- **Secrets stay out of git** — `.streamlit/osecrets.toml` and other local
  files are untracked on purpose. Only `webapp/` + `.claude/launch.json` are
  committed from this effort.

---

## 12. Not included (by design)

PDF export, email/Google Sheets logging, admin dashboard, RF propagation,
regulatory layers (FAA airspace / cell towers / no-fly zones), census batch
geocoding, address geocoding for station lists (lat/lon columns required).

Natural next steps if wanted: regulatory layers via PMTiles/DuckDB-WASM
(no backend needed), address geocoding via Census single-line API,
call-type/priority filters, elbow chart for choosing station count.

---

## 13. Commit history (webapp)

| Commit | Summary |
|---|---|
| `b0541d3` | feat(webapp): initial frontend-only app (parsing, map, boundary, optimization, export) |
| `7e2bfb3` | feat(webapp): collapsible panels, outlier filter, live ring sync |
| `a394af3` | refactor(webapp): lock in Python-match dot style, remove variants |
| `f608b1f` | fix(webapp): always show manually placed stations |

Remote: `javafrank` → https://github.com/stevebeltran/javafrank.git
(`origin` still points at Frankenstein.git and is untouched.)
