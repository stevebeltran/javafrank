"""Boundary and jurisdiction lookups using local parquets and Census TIGER shapefiles."""
import streamlit as st
import geopandas as gpd
import os
import re
import json
import urllib.request
import urllib.parse
import io
import zipfile
import glob
from shapely.geometry import Point
from modules.config import STATE_FIPS, KNOWN_POPULATIONS
from modules.geocoding import forward_geocode

def lookup_zip_code(zip_code: str):
    """
    Look up a US ZIP code and return (city, state_abbr, county) using the free
    Zippopotam.us API.  Returns (None, None, None) on failure.
    """
    zip_code = zip_code.strip()
    if not re.match(r'^\d{5}$', zip_code):
        return None, None, None
    try:
        url = f"https://api.zippopotam.us/us/{zip_code}"
        req = urllib.request.Request(url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        place = data['places'][0]
        city  = place['place name']
        state = place['state abbreviation']
        return city, state, place.get('state', '')
    except Exception:
        return None, None, None

@st.cache_data
def normalize_jurisdiction_name(name):
    if not name:
        return ""
    name = str(name).lower().strip()
    name = re.sub(r'\bst\b\.?', 'saint', name)
    name = re.sub(r'[^a-z0-9\s-]', ' ', name)
    for suffix in [' city', ' town', ' village', ' borough', ' township', ' cdp', ' municipality', ' county', ' parish']:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
            break
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def lookup_county_for_city(city_name, state_abbr):
    """Use Nominatim reverse-geocode to find the county name for a city that
    doesn't directly match a county name in the local parquet."""
    try:
        lat, lon = forward_geocode(f"{city_name}, {state_abbr}, USA")
        if lat is None: return None
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=8&addressdetails=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        county_raw = data.get('address', {}).get('county', '')
        # Nominatim returns "Winnebago County" — strip the suffix
        county_name = county_raw.replace(' County', '').replace(' Parish', '').replace(' Borough', '').strip()
        return county_name if county_name else None
    except Exception:
        return None

def fetch_county_by_centroid(df_calls, state_abbr):
    """Find the county boundary that contains the median centroid of the call data.

    Uses a pure spatial lookup against counties_lite.parquet — no network calls,
    no name-matching.  Returns (True, GeoDataFrame) or (False, None).
    """
    local_file = "counties_lite.parquet"
    if not os.path.exists(local_file):
        return False, None

    state_fips = STATE_FIPS.get(state_abbr)
    if not state_fips:
        return False, None

    try:
        lat = float(df_calls['lat'].dropna().median())
        lon = float(df_calls['lon'].dropna().median())
    except Exception:
        return False, None

    try:
        gdf = gpd.read_parquet(local_file)
        state_rows = gdf[gdf['STATEFP'] == state_fips].copy()
        if state_rows.empty:
            return False, None

        from shapely.geometry import Point
        pt = Point(lon, lat)  # geographic order: (x=lon, y=lat)

        containing = state_rows[state_rows.geometry.contains(pt)]
        if containing.empty:
            # Fall back to nearest centroid in case the point lands on a boundary
            state_rows = state_rows.copy()
            state_rows['_dist'] = state_rows.geometry.distance(pt)
            containing = state_rows.nsmallest(1, '_dist')

        if not containing.empty:
            result = containing[['NAME', 'geometry']].copy()
            result['NAME'] = result['NAME'].astype(str) + " County"
            return True, result
    except Exception as e:
        print(f"[BRINC] fetch_county_by_centroid failed: {e}")

    return False, None


@st.cache_data
def fetch_county_boundary_local(state_abbr, county_name_input):
    # 1. Clean the input
    search_name = normalize_jurisdiction_name(county_name_input)
        
    state_fips = STATE_FIPS.get(state_abbr)
    if not state_fips: return False, None
    
    # 2. Look for our new ultra-compressed parquet file
    local_file = "counties_lite.parquet"
    if not os.path.exists(local_file):
        print(f"[BRINC] Missing {local_file} — ensure it is present in the repository.")
        return False, None

    # 3. Read directly from the Parquet file instantly
    try:
        # Geopandas reads Parquet files in milliseconds!
        gdf = gpd.read_parquet(local_file)

        # Filter for the exact State FIPS code and County Name
        match = gdf[(gdf['STATEFP'] == state_fips) & (gdf['NAME'].str.lower() == search_name)]

        if not match.empty:
            # Put the word "County" back on for the UI displays
            match = match.copy()
            match['NAME'] = match['NAME'] + " County"
            return True, match[['NAME', 'geometry']]
    except Exception as e:
        print(f"[BRINC] fetch_county_boundary_local failed: {e}")

    return False, None

@st.cache_data
def fetch_place_boundary_local(state_abbr, place_name_input):
    """Look up a city/town/CDP boundary from the local places_lite.parquet.
    Returns (True, GeoDataFrame) on success, (False, None) if not found or
    the file doesn't exist yet (falls back to county lookup in caller)."""
    local_file = "places_lite.parquet"
    if not os.path.exists(local_file):
        return False, None   # file not yet added — caller falls back to county

    state_fips = STATE_FIPS.get(state_abbr)
    if not state_fips: return False, None

    search_name = normalize_jurisdiction_name(place_name_input)

    try:
        gdf = gpd.read_parquet(local_file)
        state_rows = gdf[gdf["STATEFP"] == state_fips]

        state_rows = state_rows.copy()
        state_rows['_norm_name'] = state_rows['NAME'].astype(str).apply(normalize_jurisdiction_name)
        if 'NAMELSAD' in state_rows.columns:
            state_rows['_norm_lsad'] = state_rows['NAMELSAD'].astype(str).apply(normalize_jurisdiction_name)
        else:
            state_rows['_norm_lsad'] = state_rows['_norm_name']

        # Exact normalized match first
        match = state_rows[(state_rows['_norm_name'] == search_name) | (state_rows['_norm_lsad'] == search_name)]

        # Partial normalized match fallback (e.g. Fort Worth / Fort Worth city)
        if match.empty:
            match = state_rows[
                state_rows['_norm_name'].str.startswith(search_name) |
                state_rows['_norm_lsad'].str.startswith(search_name)
            ]
            if not match.empty:
                match = match.copy()
                match['_diff'] = match['NAME'].astype(str).str.len() - len(search_name)
                match = match.sort_values('_diff').head(1)

        if match.empty:
            return False, None

        result = match.copy()
        # Use NAMELSAD for display if available (e.g. "Rockford city"), else NAME
        name_col = "NAMELSAD" if "NAMELSAD" in result.columns else "NAME"
        result["NAME"] = result[name_col].astype(str)
        return True, result[["NAME", "geometry"]]

    except Exception:
        return False, None

@st.cache_data
def reverse_geocode_state(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10&addressdetails=1"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode('utf-8'))
            address = data.get('address', {})
            state = address.get('state', '')
            city = (
                address.get('city')
                or address.get('town')
                or address.get('village')
                or address.get('municipality')
                or address.get('hamlet')
            )
            return state, city
    except Exception:
        return None, None

_PLACE_SUFFIXES = (
    ' city', ' town', ' village', ' borough', ' township', ' cdp', ' municipality',
    ' county', ' parish', ' census area', ' city and borough', ' borough county',
    ' urban county', ' unified government', ' metro government',
)


def _normalize_population_lookup_name(value):
    text = str(value or '').strip().lower()
    text = text.replace('&', ' and ')
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    for suffix in _PLACE_SUFFIXES:
        if text.endswith(suffix):
            text = text[:-len(suffix)].strip()
            break
    return text


def _population_lookup_aliases(value):
    base = _normalize_population_lookup_name(value)
    aliases = {base} if base else set()
    if not base:
        return aliases
    aliases.add(base.replace('saint ', 'st '))
    aliases.add(base.replace('st ', 'saint '))
    aliases.add(base.replace('-', ' '))
    aliases.add(base.replace('saint ', 'st ').replace('-', ' '))
    aliases.add(base.replace('st ', 'saint ').replace('-', ' '))
    return {alias.strip() for alias in aliases if alias.strip()}


def _lookup_known_population(place_name):
    direct = KNOWN_POPULATIONS.get(place_name)
    if direct is not None:
        return direct
    aliases = _population_lookup_aliases(place_name)
    for known_name, pop in KNOWN_POPULATIONS.items():
        if _normalize_population_lookup_name(known_name) in aliases:
            return pop
    return None


def _lookup_population_for_boundary(state_abbr, city_name, boundary_kind='place'):
    state_fips = STATE_FIPS.get(str(state_abbr or '').strip().upper(), '')
    if not state_fips:
        return None
    if boundary_kind == 'state':
        return fetch_census_state_population(state_fips)
    lookup_name = city_name or state_abbr
    return fetch_census_population(state_fips, lookup_name, is_county=(boundary_kind == 'county'))


def _refresh_reference_population(session_state, selected_names=None):
    state_abbr = str(session_state.get('active_state', '') or '').strip().upper()
    boundary_kind = str(session_state.get('boundary_kind', 'place') or 'place').strip().lower()
    if session_state.get('use_county_boundary'):
        boundary_kind = 'county'

    targets = []
    for name in (selected_names or []):
        clean_name = str(name or '').strip()
        if clean_name and clean_name not in targets:
            targets.append(clean_name)

    if not targets:
        fallback_name = session_state.get('active_city') or session_state.get('active_state') or ''
        fallback_name = str(fallback_name or '').strip()
        if fallback_name:
            targets.append(fallback_name)

    total_population = 0
    all_targets_resolved = bool(targets)

    if boundary_kind == 'state':
        resolved = _lookup_population_for_boundary(state_abbr, state_abbr, boundary_kind='state')
        total_population = int(resolved or 0)
        all_targets_resolved = bool(resolved)
    elif state_abbr and targets:
        for target_name in targets:
            resolved = _lookup_population_for_boundary(
                state_abbr,
                target_name,
                boundary_kind=boundary_kind,
            )
            if resolved:
                total_population += int(resolved)
            else:
                all_targets_resolved = False
    else:
        all_targets_resolved = False

    session_state['estimated_pop'] = int(total_population or 0)
    session_state['_pop_resolved'] = bool(total_population) and all_targets_resolved
    session_state['population_reference_kind'] = boundary_kind
    session_state['population_reference_targets'] = targets
    return int(total_population or 0)


@st.cache_data
def fetch_census_population(state_fips, place_name, is_county=False):
    if is_county:
        url = f"https://api.census.gov/data/2020/dec/pl?get=P1_001N,NAME&for=county:*&in=state:{state_fips}"
    else:
        url = f"https://api.census.gov/data/2020/dec/pl?get=P1_001N,NAME&for=place:*&in=state:{state_fips}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            search_aliases = _population_lookup_aliases(place_name)
            exact_match = None
            prefix_match = None
            for row in data[1:]:
                place_full = str(row[1]).split(',')[0].strip()
                place_aliases = _population_lookup_aliases(place_full)
                if search_aliases & place_aliases:
                    exact_match = int(row[0])
                    break
                for search_name in search_aliases:
                    if any(
                        alias.startswith(search_name + ' ')
                        or alias.startswith(search_name + '-')
                        for alias in place_aliases
                    ):
                        prefix_match = int(row[0])
                        break
                if prefix_match is not None:
                    break
            if exact_match is not None:
                return exact_match
            if prefix_match is not None:
                return prefix_match
    except Exception:
        pass
    return _lookup_known_population(place_name)

@st.cache_data
def fetch_census_state_population(state_fips):
    url = f"https://api.census.gov/data/2020/dec/pl?get=P1_001N,NAME&for=state:{state_fips}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            if len(data) > 1 and len(data[1]) > 0:
                return int(data[1][0])
    except Exception:
        pass
    return None

SHAPEFILE_DIR = "jurisdiction_data"
try:
    os.makedirs(SHAPEFILE_DIR, exist_ok=True)
except OSError:
    pass  # Directory creation failed; will use temp storage if needed

def _sanitize_boundary_token(value):
    return str(value or "").strip().replace(" ", "_").replace("/", "_")

def _boundary_shp_base(kind, name, state_abbr):
    return os.path.join(SHAPEFILE_DIR, f"{kind}__{_sanitize_boundary_token(name)}_{state_abbr}")

def save_boundary_gdf(boundary_gdf, kind, name, state_abbr):
    """Save boundary to a type-specific shapefile base so place/county do not overwrite each other."""
    try:
        base = _boundary_shp_base(kind, name, state_abbr)
        # Remove older files for this exact base so a fresh write wins cleanly
        for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
            fp = base + ext
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception as e:
                    print(f"[BRINC] Could not remove old shapefile {fp}: {e}")
        boundary_gdf.to_file(base + ".shp")
        return base + ".shp"
    except Exception as e:
        print(f"[BRINC] save_boundary_gdf failed for {kind}/{name}/{state_abbr}: {e}")
        return None

def load_saved_boundary(kind, name, state_abbr):
    """Load a previously saved boundary, preferring the exact typed name."""
    try:
        exact = _boundary_shp_base(kind, name, state_abbr) + ".shp"
        if os.path.exists(exact):
            gdf = gpd.read_file(exact)
            if gdf.crs is None:
                gdf = gdf.set_crs(epsg=4269)
            return gdf.to_crs(epsg=4326)
    except Exception as e:
        print(f"[BRINC] load_saved_boundary failed for {kind}/{name}/{state_abbr}: {e}")
    return None

@st.cache_data
def fetch_tiger_state_shapefile(state_fips, state_abbr, output_dir):
    temp_dir = os.path.join(output_dir, "temp_tiger_states")
    cached_shp = os.path.join(temp_dir, "tl_2023_us_state.shp")
    gdf = None

    if os.path.exists(cached_shp):
        try:
            gdf = gpd.read_file(cached_shp)
        except Exception:
            gdf = None

    if gdf is None:
        for year in ["2023", "2022"]:
            url = f"https://www2.census.gov/geo/tiger/TIGER{year}/STATE/tl_{year}_us_state.zip"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "BRINC_COS_Optimizer/1.0"})
                with urllib.request.urlopen(req, timeout=45) as resp:
                    zip_data = resp.read()
                zip_file = zipfile.ZipFile(io.BytesIO(zip_data))
                os.makedirs(temp_dir, exist_ok=True)
                zip_file.extractall(temp_dir)
                shp_files = glob.glob(os.path.join(temp_dir, "*.shp"))
                if shp_files:
                    gdf = gpd.read_file(shp_files[0])
                    break
            except Exception:
                continue

    if gdf is None:
        return False, None

    try:
        state_gdf = gdf[gdf['STATEFP'].astype(str) == str(state_fips)].copy()
        if state_gdf.empty:
            return False, None
        if 'STUSPS' in state_gdf.columns:
            _abbr_rows = state_gdf[state_gdf['STUSPS'].astype(str).str.upper() == str(state_abbr).upper()].copy()
            if not _abbr_rows.empty:
                state_gdf = _abbr_rows
        state_gdf = state_gdf.dissolve().reset_index(drop=True)
        state_gdf['NAME'] = str(state_abbr).upper()
        if state_gdf.crs is None:
            state_gdf = state_gdf.set_crs(epsg=4269)
        state_gdf = state_gdf.to_crs(epsg=4326)
        save_path = os.path.join(output_dir, f"state_{state_abbr.upper()}_{state_fips}.shp")
        state_gdf.to_file(save_path)
        return True, state_gdf[['NAME', 'geometry']]
    except Exception as e:
        print(f"[BRINC] fetch_tiger_state_shapefile failed for {state_abbr}: {e}")
        return False, None

@st.cache_data
def fetch_tiger_city_shapefile(state_fips, city_name, output_dir):
    # Check if we already downloaded and cached this state's places file
    temp_dir = os.path.join(output_dir, f"temp_tiger_{state_fips}")
    cached_shp = os.path.join(temp_dir, f"tl_2023_{state_fips}_place.shp")
    gdf = None

    if os.path.exists(cached_shp):
        try:
            gdf = gpd.read_file(cached_shp)
        except Exception:
            gdf = None

    if gdf is None:
        # Download from Census TIGER — try 2023 then 2022 as fallback
        for year in ["2023", "2022"]:
            url = f"https://www2.census.gov/geo/tiger/TIGER{year}/PLACE/tl_{year}_{state_fips}_place.zip"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "BRINC_COS_Optimizer/1.0"})
                with urllib.request.urlopen(req, timeout=45) as resp:
                    zip_data = resp.read()
                zip_file = zipfile.ZipFile(io.BytesIO(zip_data))
                os.makedirs(temp_dir, exist_ok=True)
                zip_file.extractall(temp_dir)
                shp_files = glob.glob(os.path.join(temp_dir, "*.shp"))
                if shp_files:
                    gdf = gpd.read_file(shp_files[0])
                    break
            except Exception:
                continue

    if gdf is None:
        return False, None

    try:
        search_name = city_name.lower().strip()
        exact_mask = gdf['NAME'].str.lower().str.strip() == search_name
        if exact_mask.any():
            city_gdf = gdf[exact_mask].copy()
        else:
            # Partial match — prefer the longest name match to avoid tiny place with same substring
            partial = gdf[gdf['NAME'].str.lower().str.contains(search_name, case=False, na=False)].copy()
            if partial.empty:
                return False, None
            # Pick the row whose NAME most closely matches (shortest extra chars)
            partial['_diff'] = partial['NAME'].str.len() - len(search_name)
            city_gdf = partial.sort_values('_diff').head(1)

        if city_gdf.empty:
            return False, None

        city_gdf = city_gdf.dissolve(by='NAME').reset_index()
        if city_gdf.crs is None:
            city_gdf = city_gdf.set_crs(epsg=4269)
        city_gdf = city_gdf.to_crs(epsg=4326)
        save_path = os.path.join(output_dir, f"{city_name.replace(' ', '_')}_{state_fips}.shp")
        city_gdf.to_file(save_path)
        return True, city_gdf
    except Exception as e:
        print(f"[BRINC] fetch_tiger_city_shapefile failed for {city_name}: {e}")
        return False, None

