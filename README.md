# Frankenstein

`Frankenstein` is a Streamlit application for planning BRINC Drone as First Responder deployments. It ingests incident/CAD data, derives a jurisdiction boundary, generates candidate stations, solves fleet placement with mixed-integer optimization, and produces map, budget, RF, and export outputs for proposal workflows.

## What It Does

- Uploads and normalizes CAD / call-for-service data
- Identifies relevant city or county boundaries from local cached shapefiles
- Generates and scores candidate drone stations
- Optimizes Responder and Guardian placement with PuLP
- Renders interactive coverage maps with FAA and infrastructure overlays
- Estimates budget, time savings, operational savings, and grant potential
- Exports deployment plans, executive-summary HTML, and Google Earth KML

## Stack

- Python
- Streamlit
- Pandas / GeoPandas / Shapely / PyProj
- Plotly
- PuLP
- Google Sheets + Gmail integrations via `gspread`, `google-auth`, and SMTP

## Repository Layout

- [`app.py`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/app.py): primary application entry point and most business logic
- [`requirements.txt`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/requirements.txt): Python dependencies
- [`download_regulatory_layers.py`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/download_regulatory_layers.py): downloads and caches FAA / infrastructure overlays
- [`download_fcc_coverage.py`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/download_fcc_coverage.py): helper for coverage data
- [`jurisdiction_data`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/jurisdiction_data): local boundary shapefile cache
- [`regulatory_layers`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/regulatory_layers): cached parquet overlays, generated locally
- [`cell_coverage`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/cell_coverage): local coverage data
- [`patch`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/patch): local patch artifacts
- [`QUICKSTART.md`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/QUICKSTART.md): operational quick start for regulatory layers
- [`REGULATORY_LAYERS_README.md`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/REGULATORY_LAYERS_README.md): deeper notes on cached map layers
- [`RF_COVERAGE_ENGINE_SUMMARY.md`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/RF_COVERAGE_ENGINE_SUMMARY.md): RF modeling notes

## Local Setup

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure Streamlit secrets

The app reads configuration from [`.streamlit/secrets.toml`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/.streamlit/secrets.toml).

Keys referenced in the code include:

- `[auth]` for Google OAuth login
- `GMAIL_ADDRESS`
- `GMAIL_APP_PASSWORD`
- `NOTIFY_EMAIL`
- `NOTIFY_SMS_EMAIL` for an optional extra recipient such as `8152437777@mms.uscc.net`
- `GOOGLE_SHEET_ID`
- `gcp_service_account`

These integrations are optional for basic local exploration, but features such as login, notification emails, and Sheets logging depend on them.

### 4. Cache regulatory layers

Recommended for normal use:

```powershell
python download_regulatory_layers.py
```

This populates `regulatory_layers/*.parquet` and makes FAA / hazards / cell tower / no-fly overlays load quickly.

### 5. Run the app

```powershell
streamlit run app.py
```

## Main User Flows

- Upload CAD or incident data
- Confirm or refine the inferred jurisdiction
- Tune station generation and deployment strategy in the sidebar
- Set Responder and Guardian counts
- Review coverage, response, budget, and RF outputs
- Export a deployment plan, executive summary, or KML

## Data Expectations

The repo already contains several large local datasets and caches. In normal operation the app also expects:

- local jurisdiction boundary files in `jurisdiction_data/`
- cached regulatory parquet files in `regulatory_layers/`
- uploaded CAD / XLSX / CSV / related incident exports from the user

Some generated data is intentionally ignored by git. See [`.gitignore`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/.gitignore).

## Architecture Notes

Current implementation characteristics:

- The application is mostly a monolith in [`app.py`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/app.py), which is roughly 11k lines.
- UI, geospatial data access, optimization, export generation, and external integrations are tightly coupled.
- The `pages/` directory exists but is effectively unused, so this is still a single-app layout rather than a split Streamlit multipage app.

That structure works, but it increases change risk. The most natural refactor boundaries are:

- auth and external integrations
- boundary and geocoding utilities
- regulatory / map overlay loaders
- optimization engine
- export generation
- RF coverage modeling

## Related Docs

- [`QUICKSTART.md`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/QUICKSTART.md)
- [`REGULATORY_LAYERS_README.md`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/REGULATORY_LAYERS_README.md)
- [`RF_COVERAGE_ENGINE_SUMMARY.md`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/RF_COVERAGE_ENGINE_SUMMARY.md)
- [`IMPLEMENTATION_CHECKLIST.md`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/IMPLEMENTATION_CHECKLIST.md)
- [`CODE_CHANGES_REFERENCE.md`](/G:/My%20Drive/PRIVATE%20NO%20ACCESS/Pyton/app/Beta/Frankenstein/CODE_CHANGES_REFERENCE.md)

## Current Repo State

At inspection time:

- branch: `main`
- remote: `origin = https://github.com/stevebeltran/Frankenstein.git`
- latest commit: `a5102d2` on April 8, 2026
- local unstaged change present in `jurisdiction_data/place__springfield_IL.dbf`
