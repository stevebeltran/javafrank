"""Geospatial utilities - random point generation, clustering, circle coordinates."""
import streamlit as st
import math
import random
import pandas as pd
from shapely.geometry import Polygon

# Demo constants
FAST_DEMO_STATION_COUNT = 10
FAST_DEMO_CACHE_VERSION = "2026-05-15-fast-demo-v1"

def _prepare_sampling_polygon(polygon):
    if polygon is None:
        return None
    try:
        if isinstance(polygon, MultiPolygon):
            non_empty = [p for p in polygon.geoms if p is not None and not p.is_empty]
            polygon = MultiPolygon(non_empty) if non_empty else None
        if polygon is None or polygon.is_empty:
            return None
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon is None or polygon.is_empty:
            return None
        return polygon
    except Exception:
        return None


def generate_random_points_in_polygon(polygon, num_points):
    polygon = _prepare_sampling_polygon(polygon)
    target = max(0, int(num_points))
    if target == 0 or polygon is None:
        return []

    points = []
    seen = set()
    minx, miny, maxx, maxy = polygon.bounds

    for _ in range(200):
        if len(points) >= target:
            break
        x_coords = np.random.uniform(minx, maxx, 1000)
        y_coords = np.random.uniform(miny, maxy, 1000)
        for x, y in zip(x_coords, y_coords):
            if len(points) >= target:
                break
            pt = Point(x, y)
            if polygon.covers(pt):
                key = (round(y, 8), round(x, 8))
                if key not in seen:
                    seen.add(key)
                    points.append((y, x))

    if len(points) < target:
        rep = polygon.representative_point()
        fallback = (rep.y, rep.x)
        while len(points) < target:
            points.append(fallback)
    return points


def generate_clustered_calls(polygon, num_points):
    polygon = _prepare_sampling_polygon(polygon)
    target = max(0, int(num_points))
    if target == 0 or polygon is None:
        return []

    minx, miny, maxx, maxy = polygon.bounds
    hotspots = []
    hotspot_target = min(max(1, random.randint(5, 15)), target)

    for _ in range(5000):
        if len(hotspots) >= hotspot_target:
            break
        hx, hy = random.uniform(minx, maxx), random.uniform(miny, maxy)
        if polygon.covers(Point(hx, hy)):
            hotspots.append((hx, hy))

    if not hotspots:
        rep = polygon.representative_point()
        hotspots = [(rep.x, rep.y)]

    points = []
    target_clustered = int(target * 0.75)
    sigma_x = max((maxx - minx) / 18.0, 1e-4)
    sigma_y = max((maxy - miny) / 18.0, 1e-4)

    for _ in range(max(target * 60, 2000)):
        if len(points) >= target_clustered:
            break
        hx, hy = random.choice(hotspots)
        px, py = np.random.normal(hx, sigma_x), np.random.normal(hy, sigma_y)
        if polygon.covers(Point(px, py)):
            points.append((py, px))

    remaining = target - len(points)
    if remaining > 0:
        points.extend(generate_random_points_in_polygon(polygon, remaining))

    if len(points) > target:
        points = points[:target]
    np.random.shuffle(points)
    return points


@st.cache_data(show_spinner=False)
def load_fast_demo_payload(city_name, state_name, station_count=FAST_DEMO_STATION_COUNT, cache_version=FAST_DEMO_CACHE_VERSION):
    """Build and cache the smallest useful payload for Path 03."""
    city_name = str(city_name or "").strip()
    state_name = str(state_name or "").strip().upper()
    if not city_name or not state_name:
        return None

    success, temp_gdf = fetch_place_boundary_local(state_name, city_name)
    boundary_kind = "place"
    if not success:
        success, temp_gdf = fetch_county_boundary_local(state_name, city_name)
        if not success:
            success, temp_gdf = fetch_county_boundary_local(state_name, f"{city_name} County")
        if success:
            boundary_kind = "county"

    if not success or temp_gdf is None or temp_gdf.empty:
        return None

    boundary_gdf = temp_gdf.copy()
    city_poly = boundary_gdf.geometry.union_all()
    population = int(KNOWN_POPULATIONS.get(city_name, 0) or 0)
    boundary_records = [{
        "name": city_name or state_name,
        "state": state_name,
        "boundary_kind": boundary_kind,
        "population": population,
        "geometry": city_poly,
    }]
    boundary_messages = [f"✅ {city_name or state_name} population loaded from local cache: {population:,}"]
    boundary_warnings = []
    saved_path = save_boundary_gdf(boundary_gdf, boundary_kind, city_name, state_name)

    selected_name_col = next(
        (column for column in ["NAME", "DISTRICT", "NAMELSAD"] if column in boundary_gdf.columns),
        None,
    )
    master_gdf_override = boundary_gdf.copy()
    if selected_name_col is None:
        master_gdf_override["DISPLAY_NAME"] = city_name or state_name
    else:
        master_gdf_override["DISPLAY_NAME"] = master_gdf_override[selected_name_col].astype(str)
    master_gdf_override["data_count"] = 1
    master_gdf_override = master_gdf_override[["DISPLAY_NAME", "data_count", "geometry"]].copy()

    total_estimated_pop = population
    df_demo, annual_cfs, simulated_points_count = build_demo_calls(
        city_poly,
        total_estimated_pop,
        generate_clustered_calls,
        boundary_records=boundary_records,
    )

    station_target = max(1, min(int(station_count or FAST_DEMO_STATION_COUNT), FAST_DEMO_STATION_COUNT))
    station_points = generate_random_points_in_polygon(city_poly, station_target)
    station_types = (["Police", "Fire", "EMS"] * ((station_target + 2) // 3))[:station_target]
    stations_df = pd.DataFrame({
        "name": [f"Preloaded Demo Station {i + 1}" for i in range(len(station_points))],
        "lat": [point[0] for point in station_points],
        "lon": [point[1] for point in station_points],
        "type": station_types[:len(station_points)],
        "source": ["PRELOADED_DEMO"] * len(station_points),
    })

    return {
        "all_gdfs": [boundary_gdf],
        "boundary_records": boundary_records,
        "total_estimated_pop": total_estimated_pop,
        "boundary_messages": boundary_messages,
        "boundary_warnings": boundary_warnings,
        "rerun_demo_target": None,
        "all_populations_verified": True,
        "boundary_source_path": saved_path or "",
        "master_gdf_override": master_gdf_override,
        "city_poly": city_poly,
        "df_demo": df_demo,
        "annual_cfs": annual_cfs,
        "simulated_points_count": simulated_points_count,
        "stations_df": stations_df,
        "stations_user_uploaded": False,
        "station_notices": ["Loaded 10 precomputed demo stations from local cache."],
        "station_warnings": [],
    }

def estimate_grants(population):
    if population > 1000000: return "$1.5M - $3.0M+"
    elif population > 500000: return "$500k - $1.5M"
    elif population > 250000: return "$250k - $500k"
    elif population > 100000: return "$100k - $250k"
    else: return "$25k - $100k"

def get_circle_coords(lat, lon, r_mi=2.0):
    angles = np.linspace(0, 2*np.pi, 100)
    c_lats = lat + (r_mi/69.172) * np.sin(angles)
    c_lons = lon + (r_mi/(69.172 * np.cos(np.radians(lat)))) * np.cos(angles)
    return c_lats, c_lons

