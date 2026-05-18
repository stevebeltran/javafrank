"""Utility functions for caching, hashing, and display calculations."""
import streamlit as st
import hashlib
import json
import os
import pandas as pd
from shapely.wkb import loads as _wkb_loads

def calculate_zoom(min_lon, max_lon, min_lat, max_lat):
    lon_diff = max_lon - min_lon
    lat_diff = max_lat - min_lat
    if lon_diff <= 0 or lat_diff <= 0: return 12
    return min(max(min(np.log2(360/lon_diff), np.log2(180/lat_diff)) + 1.6, 5), 18)

def _df_latlon_signature(df):
    if df is None or len(df) == 0:
        return None
    if 'lat' not in df.columns or 'lon' not in df.columns:
        return ('missing-latlon', len(df), tuple(map(str, df.columns[:8])))

    coords = df[['lat', 'lon']].copy()
    coords['lat'] = pd.to_numeric(coords['lat'], errors='coerce')
    coords['lon'] = pd.to_numeric(coords['lon'], errors='coerce')
    coords = coords.dropna()
    if coords.empty:
        return ('empty', len(df))

    return (
        len(coords),
        round(float(coords['lat'].min()), 5),
        round(float(coords['lat'].max()), 5),
        round(float(coords['lon'].min()), 5),
        round(float(coords['lon'].max()), 5),
    )

def _jurisdiction_scan_signature(calls_df, shapefile_dir, preferred_shp=None):
    shp_meta = []
    for shp_path in sorted(glob.glob(os.path.join(shapefile_dir, "*.shp"))):
        try:
            _stat = os.stat(shp_path)
            shp_meta.append((os.path.basename(shp_path), int(_stat.st_mtime), _stat.st_size))
        except Exception:
            shp_meta.append((os.path.basename(shp_path), 0, 0))

    preferred_meta = None
    if preferred_shp:
        try:
            _pstat = os.stat(preferred_shp)
            preferred_meta = (preferred_shp, int(_pstat.st_mtime), _pstat.st_size)
        except Exception:
            preferred_meta = (preferred_shp, 0, 0)

    return (
        _df_latlon_signature(calls_df),
        tuple(shp_meta),
        preferred_meta,
    )

def get_relevant_jurisdictions_cached(calls_df, shapefile_dir, preferred_shp=None):
    cache_key = _jurisdiction_scan_signature(calls_df, shapefile_dir, preferred_shp)
    if st.session_state.get('_jurisdiction_scan_cache_key') == cache_key:
        cached = st.session_state.get('_jurisdiction_scan_cache_value')
        return cached.copy() if cached is not None else None

    result = find_relevant_jurisdictions(calls_df, shapefile_dir, preferred_shp=preferred_shp)
    st.session_state['_jurisdiction_scan_cache_key'] = cache_key
    st.session_state['_jurisdiction_scan_cache_value'] = result.copy() if result is not None else None
    return result

def find_relevant_jurisdictions(calls_df, shapefile_dir, preferred_shp=None):
    if calls_df is None:
        return None
    full_points = calls_df[['lat', 'lon']].copy()
    full_points = full_points[(full_points.lat.abs() > 1) & (full_points.lon.abs() > 1)]
    scan_points = full_points.sample(50000, random_state=42) if len(full_points) > 50000 else full_points
    points_gdf = gpd.GeoDataFrame(scan_points, geometry=gpd.points_from_xy(scan_points.lon, scan_points.lat), crs="EPSG:4326")
    total_bounds = points_gdf.total_bounds

    # Always scan all saved shapefiles in the directory so multi-jurisdiction
    # uploads show every boundary, not just the first one saved.
    shp_files = glob.glob(os.path.join(shapefile_dir, "*.shp"))
    # If no shapefiles exist at all and a preferred path was given, use just that
    if not shp_files and preferred_shp and os.path.exists(preferred_shp):
        shp_files = [preferred_shp]

    relevant_polys = []
    _calls_minx, _calls_miny, _calls_maxx, _calls_maxy = total_bounds
    for shp_path in shp_files:
        try:
            import fiona
            with fiona.open(shp_path) as _shp_src:
                _shp_bounds = _shp_src.bounds
            _no_overlap = (
                _shp_bounds[2] < _calls_minx or _shp_bounds[0] > _calls_maxx or
                _shp_bounds[3] < _calls_miny or _shp_bounds[1] > _calls_maxy
            )
            if _no_overlap:
                continue
        except Exception:
            pass

        try:
            gdf_chunk = gpd.read_file(shp_path, bbox=tuple(total_bounds))
            if not gdf_chunk.empty:
                if gdf_chunk.crs is None: gdf_chunk.set_crs(epsg=4269, inplace=True)
                gdf_chunk = gdf_chunk.to_crs(epsg=4326)
                hits = gpd.sjoin(gdf_chunk, points_gdf, how="inner", predicate="intersects")
                if not hits.empty:
                    subset = gdf_chunk.loc[hits.index.unique()].copy()
                    subset['data_count'] = hits.index.value_counts()
                    name_col = next((c for c in ['NAME','DISTRICT','NAMELSAD'] if c in subset.columns), subset.columns[0])
                    subset['DISPLAY_NAME'] = subset[name_col].astype(str)
                    relevant_polys.append(subset)
        except Exception: continue
    if not relevant_polys: return None
    master_gdf = pd.concat(relevant_polys, ignore_index=True).sort_values(by='data_count', ascending=False)
    master_gdf = master_gdf.dissolve(by='DISPLAY_NAME', aggfunc={'data_count': 'sum'}).reset_index()
    master_gdf = master_gdf.sort_values(by='data_count', ascending=False)
    if master_gdf['data_count'].sum() > 0:
        master_gdf['pct_share'] = master_gdf['data_count'] / master_gdf['data_count'].sum()
        master_gdf['cum_share'] = master_gdf['pct_share'].cumsum()
        mask = (master_gdf['cum_share'] <= 0.98) | (master_gdf['pct_share'] > 0.01)
        mask.iloc[0] = True
        return master_gdf[mask]
    return master_gdf

@st.cache_data(show_spinner=False)
def build_display_calls(df_calls_full, _city_m, epsg_code, max_points=300000, seed=42, bounds_hash=''):
    if df_calls_full is None or len(df_calls_full) == 0:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    df = df_calls_full.copy()
    if 'lat' not in df.columns or 'lon' not in df.columns:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
    df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
    df = df.dropna(subset=['lat', 'lon']).reset_index(drop=True)
    if df.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")
    try:
        gdf_m = gdf.to_crs(epsg=int(epsg_code))
        # Buffer 300 m so calls at polygon edges aren't clipped by precision gaps
        # (especially common when switching to a county boundary)
        _clip_geom = _city_m.buffer(300) if _city_m is not None else None
        calls_in_city = gdf_m[gdf_m.within(_clip_geom)] if _clip_geom is not None else gdf_m
    except Exception:
        calls_in_city = gdf

    if calls_in_city.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    if len(calls_in_city) <= max_points:
        return calls_in_city.to_crs(epsg=4326)

    sampled = calls_in_city.copy()
    minx, miny, maxx, maxy = sampled.total_bounds
    span_x = max(maxx - minx, 1.0)
    span_y = max(maxy - miny, 1.0)
    target_cells = max(25, int(np.sqrt(max_points) * 0.7))
    nx = max(25, min(120, target_cells))
    ny = max(25, min(120, int(target_cells * (span_y / span_x))))

    sampled['_gx'] = np.floor((sampled.geometry.x - minx) / span_x * nx).clip(0, nx - 1).astype(int)
    sampled['_gy'] = np.floor((sampled.geometry.y - miny) / span_y * ny).clip(0, ny - 1).astype(int)
    sampled['_cell'] = sampled['_gx'].astype(str) + '_' + sampled['_gy'].astype(str)

    counts = sampled['_cell'].value_counts()
    alloc = np.maximum(1, np.floor(counts / counts.sum() * max_points).astype(int))
    shortfall = int(max_points - alloc.sum())
    if shortfall > 0:
        remainders = (counts / counts.sum() * max_points) - np.floor(counts / counts.sum() * max_points)
        for cell in remainders.sort_values(ascending=False).index[:shortfall]:
            alloc.loc[cell] += 1

    parts = []
    for cell, group in sampled.groupby('_cell', sort=False):
        take = int(min(len(group), alloc.get(cell, 1)))
        if take >= len(group):
            parts.append(group)
        elif take > 0:
            parts.append(group.sample(take, random_state=seed))

    if not parts:
        display_calls = sampled.sample(max_points, random_state=seed)
    else:
        display_calls = pd.concat(parts, ignore_index=False)
        if len(display_calls) > max_points:
            display_calls = display_calls.sample(max_points, random_state=seed)

    display_calls = display_calls.drop(columns=['_gx', '_gy', '_cell'], errors='ignore')
    return display_calls.to_crs(epsg=4326)

# ============================================================
# PAGE CONFIG — must be the first Streamlit command
# ============================================================
st.set_page_config(
    layout="wide",
    initial_sidebar_state="expanded",
    page_title="BRINC Drone-as-First-Responder",
    page_icon="https://brincdrones.com/favicon.ico"
)

# ============================================================
# GOOGLE OAUTH LOGIN GATE
# ============================================================
# Activates only when [auth] section is present in secrets.toml.
# Falls through silently if auth is not configured (local dev without secrets).
