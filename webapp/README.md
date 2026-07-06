# DFR Site Survey — frontend-only JS scaffold

Zero-build static app. No Python, no secrets, no bundler. Open `index.html` from any
static file server and it runs.

## Run

```
npx --yes http-server webapp -p 8321 -c-1
# → http://localhost:8321
```

Deploy = copy this folder to GitHub Pages / Netlify / Cloudflare Pages.

## Features

- **Single dropzone** — CAD calls and station lists both go in the top box
  (multi-file drop OK); file kind auto-detected (row count, name/address vs
  date columns). Column detection ported from `modules/cad_parser.py` (CV
  variants) plus numeric-range sniffing fallback. Invalid coordinates dropped.
- **Map** — MapLibre GL, CARTO dark basemap. Calls are single dots colored by
  agency: police blue, fire red, EMS amber, other gray. Agency column
  auto-detected (handles Motorola combo codes: l, lf, lfe, f, i).
- **Boundary lookup** — Census TIGERweb REST (no key, CORS-enabled).
  Incorporated place first, county fallback, Nominatim last resort. Layer IDs
  discovered at runtime. Optional filter of calls to boundary.
- **Station optimization** — two modes:
  - K-means (k-means++/farthest-first seeding) centroids
  - Greedy max-coverage: dense k-means candidates, pick k covering most calls
    within the drone radius
  Responder (2 mi, magenta) and Guardian (8 mi, cyan) are independent sets —
  toggle each on/off, own count + radius; combined union coverage shown when
  both active. "Click map to add station" drops manual stations (remove via
  station popup).
- **Clustered rendering** — calls cluster into count-sized circles colored by
  dominant agency (MapLibre/supercluster); individual dots only past zoom 14.
  76k calls render as ~26 circles at city zoom.
- **Metrics** — % calls within radius, avg/max distance to nearest station,
  compared for existing vs suggested stations.
- **HTML export** — one-click standalone report (all points, legend, boundary,
  station placement + rings, metrics, BRINC branding). Only external deps are
  MapLibre + basemap tiles from CDN.
- **Demo data** — synthetic Naperville calls sized at 60% of city population
  (annual-CFS rule of thumb), ~89.7k points.

## Perf (measured, 100k calls)

- k-means (k=5): ~135 ms
- greedy max-coverage: ~1.6 s
- coverage stats: ~32 ms

## Libraries (CDN, pinned)

MapLibre GL 4.7.1 · Turf 7.1 · PapaParse 5.4.1 · SheetJS 0.18.5

## Not included (by design)

PDF export, email/Sheets logging, RF propagation, regulatory layers.
Regulatory parquet layers could be added later via DuckDB-WASM or PMTiles
without a backend.
