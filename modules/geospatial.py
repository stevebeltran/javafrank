"""Geospatial utilities - boundaries, geocoding, station generation."""

import streamlit as st
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point, Polygon, MultiPolygon, box
from shapely.ops import unary_union
from pathlib import Path
import os, glob, json, re, zipfile, io, math, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import tempfile

from modules.config import STATE_FIPS, US_STATES_ABBR, KNOWN_POPULATIONS


def _load_uploaded_boundary_overlay(uploaded_files):
    """Read uploaded shapefile sidecars into EPSG:4326 for display-only map overlays."""
    if not uploaded_files:
        return None, "", ""

    _files = list(uploaded_files)
    _by_ext = {}
    for _uf in _files:
        _name = Path(_uf.name).name
        _ext = Path(_name).suffix.lower()
        if _ext:
            _by_ext[_ext] = _uf

    _required = ['.shp', '.shx', '.dbf', '.prj']
    _missing = [ext for ext in _required if ext not in _by_ext]
    if _missing:
        raise ValueError(f"Missing required shapefile components: {', '.join(_missing)}")

    with tempfile.TemporaryDirectory() as _td:
        for _uf in _files:
            Path(_td, Path(_uf.name).name).write_bytes(_uf.getvalue())

        _shp_path = str(Path(_td, Path(_by_ext['.shp'].name).name))
        _gdf = gpd.read_file(_shp_path)
        if _gdf is None or _gdf.empty:
            raise ValueError("Uploaded shapefile did not contain any features.")
        if _gdf.crs is None:
            raise ValueError("Uploaded shapefile has no coordinate reference system. Include a valid .prj file.")

        _gdf = _gdf.to_crs(epsg=4326)
        _gdf = _gdf[_gdf.geometry.notna()].copy()
        _gdf = _gdf[~_gdf.geometry.is_empty].copy()
        if _gdf.empty:
            raise ValueError("Uploaded shapefile geometries were empty after loading.")

        _name_col = next((c for c in ['NAME', 'Name', 'name', 'DISTRICT', 'District', 'LABEL', 'Label'] if c in _gdf.columns), None)
        _label = Path(_by_ext['.shp'].name).stem
        if _name_col:
            _gdf['DISPLAY_NAME'] = _gdf[_name_col].astype(str).fillna('').replace('nan', '').str.strip()
            _gdf['DISPLAY_NAME'] = _gdf['DISPLAY_NAME'].replace('', _label)
        else:
            _gdf['DISPLAY_NAME'] = _label

        return _gdf[['DISPLAY_NAME', 'geometry']].copy(), _label, Path(_by_ext['.shp'].name).name


def _boundary_overlay_status(boundary_geom_4326, overlay_gdf, epsg_code):
    if boundary_geom_4326 is None or boundary_geom_4326.is_empty or overlay_gdf is None or overlay_gdf.empty:
        return None
    try:
        _overlay_utm = overlay_gdf.to_crs(epsg=epsg_code)
        _overlay_union = (_overlay_utm.geometry.union_all() if hasattr(_overlay_utm.geometry, 'union_all') else _overlay_utm.geometry.unary_union)
        _boundary_utm = gpd.GeoSeries([boundary_geom_4326], crs='EPSG:4326').to_crs(epsg=epsg_code).iloc[0]
        if _overlay_union.is_empty or _boundary_utm.is_empty:
            return None
        _inter = _overlay_union.intersection(_boundary_utm)
        _overlay_area = float(_overlay_union.area or 0)
        _boundary_area = float(_boundary_utm.area or 0)
        _inter_area = float(_inter.area or 0)
        if _overlay_area <= 0 or _boundary_area <= 0:
            return None
        _pct_overlay_inside = max(0.0, min(100.0, _inter_area / _overlay_area * 100.0))
        _pct_boundary_covered = max(0.0, min(100.0, _inter_area / _boundary_area * 100.0))
        if _inter_area <= 0:
            _status = 'no_overlap'
            _message = 'Uploaded boundary overlay does not overlap the selected city/county boundary.'
        elif _pct_overlay_inside >= 99.5:
            _status = 'inside'
            _message = f"Uploaded boundary overlay sits within the selected boundary ({_pct_overlay_inside:.1f}% inside)."
        elif _pct_boundary_covered >= 99.5:
            _status = 'contains'
            _message = f"Uploaded boundary overlay fully contains the selected boundary ({_pct_overlay_inside:.1f}% of overlay overlaps)."
        else:
            _status = 'partial'
            _message = f"Uploaded boundary overlay partially overlaps the selected boundary ({_pct_overlay_inside:.1f}% of overlay overlaps)."
        return {'status': _status, 'message': _message, 'pct_overlay_inside': _pct_overlay_inside, 'pct_boundary_covered': _pct_boundary_covered}
    except Exception:
        return None


def _count_points_within_boundary(df_calls, boundary_geom_4326):
    """Count calls (points) that fall within a boundary polygon."""
    if df_calls is None or df_calls.empty or boundary_geom_4326 is None:
        return 0
    try:
        _pts = gpd.GeoSeries([Point(row['lon'], row['lat']) for _, row in df_calls.iterrows()], crs='EPSG:4326')
        _cnt = sum(_pts.within(boundary_geom_4326, align=False))
        return int(_cnt)
    except Exception:
        return 0


def find_jurisdictions_by_coordinates(df_calls, min_call_share=0.001, min_call_count=3):
    """
    Purely coordinate-driven jurisdiction lookup.

    Spatially joins call points against places_lite.parquet (and
    counties_lite.parquet as fallback) to find every jurisdiction that
    contains at least `min_call_share` of the uploaded calls OR at least
    `min_call_count` absolute calls.  Returns a GeoDataFrame with columns
    [DISPLAY_NAME, data_count, geometry] sorted descending by data_count,
    or None if nothing is found.
    """
    import traceback as _tb
    _debug_msgs = []
    try:
        if df_calls is None or df_calls.empty:
            _debug_msgs.append("df_calls is None or empty")
            st.session_state['_jur_debug'] = _debug_msgs
            return None

        pts = df_calls.copy()
        pts['lat'] = pd.to_numeric(pts['lat'], errors='coerce')
        pts['lon'] = pd.to_numeric(pts['lon'], errors='coerce')
        pts = pts.dropna(subset=['lat', 'lon'])
        if pts.empty:
            _debug_msgs.append("no valid lat/lon after cleaning")
            st.session_state['_jur_debug'] = _debug_msgs
            return None

        _debug_msgs.append(f"pts count: {len(pts)}, lat range: {pts['lat'].min():.3f}–{pts['lat'].max():.3f}, lon range: {pts['lon'].min():.3f}–{pts['lon'].max():.3f}")

        sample = pts.sample(min(len(pts), 5000), random_state=42) if len(pts) > 5000 else pts
        pts_gdf = gpd.GeoDataFrame(sample, geometry=gpd.points_from_xy(sample.lon, sample.lat), crs='EPSG:4326')
        bbox = tuple(pts_gdf.total_bounds)
        _debug_msgs.append(f"bbox: {bbox}")

        results = []

        for parquet_file, name_col, kind in [
            ('places_lite.parquet',  'NAME', 'place'),
            ('counties_lite.parquet','NAME', 'county'),
        ]:
            _exists = os.path.exists(parquet_file)
            _debug_msgs.append(f"{parquet_file} exists: {_exists}")
            if not _exists:
                continue
            try:
                # Full read then cx filter — bbox kwarg not supported by this parquet build
                poly_gdf = gpd.read_parquet(parquet_file)
                poly_gdf = poly_gdf.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]

                _debug_msgs.append(f"{parquet_file} rows in bbox: {len(poly_gdf)}")
                if poly_gdf is None or poly_gdf.empty:
                    continue
                if poly_gdf.crs is None:
                    poly_gdf = poly_gdf.set_crs(epsg=4326)
                poly_gdf = poly_gdf.to_crs(epsg=4326)

                joined = gpd.sjoin(pts_gdf[['geometry']], poly_gdf[[name_col, 'geometry']], how='left', predicate='within')
                hit_counts = joined[name_col].value_counts().dropna()
                _debug_msgs.append(f"sjoin hits: {dict(list(hit_counts.items())[:10])}")
                if hit_counts.empty:
                    continue

                total = hit_counts.sum()
                for jname, cnt in hit_counts.items():
                    if cnt / total < min_call_share and cnt < min_call_count:
                        continue
                    row = poly_gdf[poly_gdf[name_col] == jname].copy()
                    if row.empty:
                        continue
                    display = str(jname)
                    if kind == 'county' and not display.lower().endswith('county'):
                        display = display + ' County'
                    already = any(r['DISPLAY_NAME'] == display for r in results)
                    if not already:
                        results.append({
                            'DISPLAY_NAME': display,
                            'boundary_kind': kind,
                            'data_count': int(cnt),
                            'geometry': row.geometry.iloc[0],
                        })
            except Exception as _e:
                _debug_msgs.append(f"{parquet_file} ERROR: {_e}\n{_tb.format_exc()[-300:]}")
                continue

            if results and parquet_file.startswith('places'):
                break

        _debug_msgs.append(f"total results: {len(results)}, names: {[r['DISPLAY_NAME'] for r in results]}")
        st.session_state['_jur_debug'] = _debug_msgs

        if not results:
            return None

        out = gpd.GeoDataFrame(results, crs='EPSG:4326')
        out = out.sort_values('data_count', ascending=False).reset_index(drop=True)
        return out

    except Exception as _e:
        _debug_msgs.append(f"OUTER ERROR: {_e}\n{_tb.format_exc()[-400:]}")
        st.session_state['_jur_debug'] = _debug_msgs
        return None


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


def get_address_from_latlon(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'BRINC_DFR_Optimizer_App/2.0'})
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode('utf-8'))
            if 'address' in data:
                addr = data['address']
                road = addr.get('road', '')
                house_number = addr.get('house_number', '')
                city = addr.get('city', addr.get('town', addr.get('village', '')))
                if road:
                    return f"{house_number} {road}, {city}".strip(', ')
    except Exception:
        pass
    return f"{lat:.5f}, {lon:.5f}"
