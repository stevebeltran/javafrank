"""Coverage analysis and carrier analysis functions."""
import os
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.wkb import loads as _wkb_loads
from modules import faa_rf

def _get_coverage_analysis_cache() -> dict:
    """Returns the shared analysis-result dict for this worker process."""
    return {}


def _coverage_geom_cache_key(geom):
    if geom is None or geom.is_empty:
        return None
    try:
        return geom.wkb_hex
    except Exception:
        try:
            return geom.wkb.hex()
        except Exception:
            return str(geom.bounds)


def _decode_coverage_geometry(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return _wkb_loads(bytes(value))
        return _wkb_loads(bytes.fromhex(value))
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _load_coverage(state_abbr: str):
    """Load raw cell_coverage/{STATE}.parquet rows; returns GeoDataFrame or None."""
    state_abbr = (state_abbr or '').strip().upper()
    if not state_abbr:
        return None
    path = os.path.join('cell_coverage', f'{state_abbr}.parquet')
    if not os.path.exists(path):
        return None
    try:
        try:
            df = pd.read_parquet(path, columns=['carrier', 'color', 'geometry_wkb'])
        except Exception:
            df = pd.read_parquet(path)
        df = df[['carrier', 'color', 'geometry_wkb']].copy()
        df['geometry'] = df['geometry_wkb'].apply(_decode_coverage_geometry)
        gdf = gpd.GeoDataFrame(df[['carrier', 'color']], geometry=df['geometry'], crs='EPSG:4326')
        return gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _load_dissolved_coverage(state_abbr: str):
    """Load carrier-dissolved statewide coverage, used only for the full-map overlay."""
    state_abbr = (state_abbr or '').strip().upper()
    if not state_abbr:
        return None

    gdf = _load_coverage(state_abbr)
    if gdf is None or gdf.empty:
        return gdf

    dissolved_rows = []
    for (carrier, color), group in gdf.groupby(['carrier', 'color'], sort=False):
        geom = unary_union(group.geometry.tolist())
        if geom is None or geom.is_empty:
            continue
        try:
            geom = geom.simplify(0.0008, preserve_topology=True)
        except Exception:
            pass
        dissolved_rows.append({'carrier': carrier, 'color': color, 'geometry': geom})

    return gpd.GeoDataFrame(dissolved_rows, geometry='geometry', crs='EPSG:4326')


def add_coverage_traces(fig, state_abbr: str, visible=True):
    """Add AT&T / T-Mobile / Verizon 4G LTE polygon traces."""
    gdf = _load_dissolved_coverage(state_abbr)
    if gdf is None or gdf.empty:
        return

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        carrier = row['carrier']
        color   = row['color']
        rings = []
        if geom.geom_type == 'Polygon':
            rings = [geom.exterior]
        elif geom.geom_type == 'MultiPolygon':
            rings = [p.exterior for p in geom.geoms]
        else:
            continue

        lons_all, lats_all = [], []
        for ring in rings:
            xs, ys = ring.coords.xy
            lons_all.extend(list(xs) + [None])
            lats_all.extend(list(ys) + [None])

        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        fig.add_trace(go.Scattermap(
            lon=lons_all, lat=lats_all,
            mode='lines', fill='toself',
            fillcolor=f"rgba({r},{g},{b},0.25)",
            line=dict(color=color, width=1),
            name=f"{carrier} 4G LTE",
            hoverinfo='name',
            visible=visible,
        ))


def _carrier_coverage_analysis(state_abbr: str, boundary_geom):
    """
    Intersects each carrier's coverage with the jurisdiction boundary.
    Returns list of dicts sorted by coverage % descending:
      {'carrier', 'color', 'pct', 'poly'}
    """
    if not state_abbr or boundary_geom is None or boundary_geom.is_empty:
        return []

    cache_key = ((state_abbr or '').strip().upper(), _coverage_geom_cache_key(boundary_geom))
    _analysis_cache = _get_coverage_analysis_cache()
    if cache_key in _analysis_cache:
        return _analysis_cache[cache_key]

    gdf = _load_coverage(state_abbr)
    if gdf is None or gdf.empty:
        return []

    boundary_area = boundary_geom.area
    if boundary_area <= 0:
        return []

    try:
        from shapely.geometry import box
        from shapely.prepared import prep
        bbox_geom = box(*boundary_geom.bounds)
        try:
            candidate_idx = gdf.sindex.query(bbox_geom, predicate='intersects')
            candidate_gdf = gdf.iloc[candidate_idx]
        except Exception:
            candidate_gdf = gdf[gdf.geometry.intersects(bbox_geom)]
        prepared_boundary = prep(boundary_geom)
    except Exception:
        candidate_gdf = gdf
        prepared_boundary = None

    carrier_meta = list(gdf[['carrier', 'color']].drop_duplicates().itertuples(index=False, name=None))
    clipped_by_carrier = {carrier: [] for carrier, _ in carrier_meta}

    for row in candidate_gdf.itertuples(index=False):
        poly = row.geometry
        if poly is None or poly.is_empty:
            continue
        try:
            if prepared_boundary is not None and not prepared_boundary.intersects(poly):
                continue
            clipped = poly.intersection(boundary_geom)
        except Exception:
            continue
        if clipped is not None and not clipped.is_empty:
            clipped_by_carrier.setdefault(row.carrier, []).append(clipped)

    results = []
    for carrier, color in carrier_meta:
        pieces = clipped_by_carrier.get(carrier) or []
        if not pieces:
            results.append({'carrier': carrier, 'color': color, 'pct': 0.0, 'poly': None})
            continue
        try:
            clipped = unary_union(pieces) if len(pieces) > 1 else pieces[0]
            try:
                clipped = clipped.simplify(0.0005, preserve_topology=True)
            except Exception:
                pass
            pct = min(100.0, clipped.area / boundary_area * 100)
        except Exception:
            clipped = None
            pct = 0.0
        results.append({'carrier': carrier, 'color': color, 'pct': pct, 'poly': clipped})

    results = sorted(results, key=lambda x: x['pct'], reverse=True)
    _analysis_cache[cache_key] = results
    return results


def _build_carrier_mini_map(cinfo, boundary_geom, center_lat, center_lon, zoom, map_style):
    """Build a small Plotly map showing jurisdiction boundary + one carrier's coverage."""
    fig = go.Figure()

    # Jurisdiction outline
    if boundary_geom is not None and not boundary_geom.is_empty:
        geoms = [boundary_geom] if isinstance(boundary_geom, Polygon) else list(boundary_geom.geoms)
        for gi, g in enumerate(geoms):
            bx, by = g.exterior.coords.xy
            fig.add_trace(go.Scattermap(
                mode='lines', lon=list(bx), lat=list(by),
                line=dict(color='#ffffff', width=1.5),
                showlegend=False, hoverinfo='skip'
            ))

    # Coverage fill
    poly = cinfo.get('poly')
    if poly is not None and not poly.is_empty:
        color = cinfo['color']
        r, g_c, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        rings = ([poly.exterior] if poly.geom_type == 'Polygon'
                 else [p.exterior for p in poly.geoms])
        lons, lats = [], []
        for ring in rings:
            xs, ys = ring.coords.xy
            lons.extend(list(xs) + [None])
            lats.extend(list(ys) + [None])
        fig.add_trace(go.Scattermap(
            lon=lons, lat=lats, mode='lines', fill='toself',
            fillcolor=f"rgba({r},{g_c},{b},0.40)",
            line=dict(color=color, width=1),
            showlegend=False, hoverinfo='skip'
        ))

    fig.update_layout(
        map=dict(center=dict(lat=center_lat, lon=center_lon),
                 zoom=max(8, zoom - 1), style=map_style),
        margin=dict(l=0, r=0, t=0, b=0),
        height=210, showlegend=False,
    )
    return fig
