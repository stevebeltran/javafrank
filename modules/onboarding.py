"""Helpers for onboarding and saved deployment restore."""

import io
import json
import os
import glob
import time
import re
import sys
import urllib.parse
import urllib.request

import geopandas as gpd
import numpy as np
import pandas as pd
import datetime
import random


def _normalize_display_text(value):
    text = str(value)
    try:
        return text.encode("latin1").decode("utf-8")
    except Exception:
        return text


_OPT_CACHE_KEYS = (
    '_opt_cache_key',
    '_opt_best_combo',
    '_opt_chrono_r',
    '_opt_chrono_g',
)


def detect_brinc_file(uploaded_files):
    for uploaded_file in uploaded_files:
        fname = str(getattr(uploaded_file, 'name', '')).lower()
        if '.brinc' not in fname and not fname.endswith('.json'):
            continue
        try:
            uploaded_file.seek(0)
            peek = json.loads(uploaded_file.getvalue().decode('utf-8'))
            if 'k_resp' in peek and 'calls_data' in peek:
                return uploaded_file
        except Exception:
            continue
    return None


def load_brinc_save_data(brinc_file):
    brinc_file.seek(0)
    return json.loads(brinc_file.getvalue().decode('utf-8'))


def restore_brinc_session(session_state, save_data):
    session_state['active_city'] = str(save_data.get('city', 'Unknown')).title()
    session_state['active_state'] = save_data.get('state', 'US')
    session_state['k_resp'] = save_data.get('k_resp', 2)
    session_state['k_guard'] = save_data.get('k_guard', 0)
    session_state['r_resp'] = save_data.get('r_resp', 2.0)
    session_state['r_guard'] = save_data.get('r_guard', 8.0)
    session_state['dfr_rate'] = save_data.get('dfr_rate', 25)
    session_state['deflect_rate'] = save_data.get('deflect_rate', 30)

    session_state['pinned_guard_names'] = save_data.get('pinned_guard_names', [])
    session_state['pinned_resp_names'] = save_data.get('pinned_resp_names', [])
    session_state['lock_guard_ms'] = list(session_state['pinned_guard_names'])
    session_state['lock_resp_ms'] = [
        s for s in session_state['pinned_resp_names']
        if s not in session_state['pinned_guard_names']
    ]

    custom_stations = save_data.get('custom_stations')
    if custom_stations:
        try:
            custom_df = pd.DataFrame(custom_stations)
            if not custom_df.empty and 'lat' in custom_df.columns and 'lon' in custom_df.columns:
                session_state['custom_stations'] = custom_df
        except Exception:
            pass

    resp_strategy = save_data.get('resp_strategy', 'Call Coverage')
    guard_strategy = save_data.get('guard_strategy', 'Land Coverage')
    session_state['resp_strat_idx'] = 0 if resp_strategy == 'Call Coverage' else 1
    session_state['guard_strat_idx'] = 0 if guard_strategy == 'Call Coverage' else 1
    session_state['deployment_mode_idx'] = save_data.get('deployment_mode_idx', 1)
    session_state['incremental_build'] = save_data.get('incremental_build', True)
    session_state['auto_cap_dfr'] = save_data.get('auto_cap_dfr', True)
    session_state['use_county_boundary'] = save_data.get('use_county_boundary', False)
    session_state['pin_drop_used'] = save_data.get('pin_drop_used', False)
    session_state['_brinc_k_override'] = True
    session_state.pop('_auto_minimums_sig', None)

    target_cities = save_data.get('target_cities')
    if isinstance(target_cities, list):
        restored_targets = []
        for target in target_cities:
            if not isinstance(target, dict):
                continue
            restored_targets.append({
                'city': str(target.get('city', '') or '').strip(),
                'state': str(target.get('state', session_state.get('active_state', '')) or '').strip().upper(),
            })
        if restored_targets:
            session_state['target_cities'] = restored_targets
            session_state['city_count'] = max(1, int(save_data.get('city_count', len(restored_targets)) or len(restored_targets)))
        else:
            session_state['target_cities'] = [{'city': session_state['active_city'], 'state': session_state['active_state']}]
            session_state['city_count'] = 1
    else:
        session_state['target_cities'] = [{'city': session_state['active_city'], 'state': session_state['active_state']}]
        session_state['city_count'] = 1

    saved_jurisdiction_names = save_data.get('saved_jurisdiction_names')
    if isinstance(saved_jurisdiction_names, list):
        session_state['saved_jurisdiction_names'] = [
            str(name or '').strip() for name in saved_jurisdiction_names if str(name or '').strip()
        ]
    else:
        session_state['saved_jurisdiction_names'] = []

    for cache_key in _OPT_CACHE_KEYS:
        session_state.pop(cache_key, None)

    calls_data = save_data.get('calls_data')
    if calls_data:
        calls_df = pd.DataFrame(calls_data)
        if 'lat' not in calls_df.columns or 'lon' not in calls_df.columns:
            raise ValueError(".brinc file is missing required 'lat'/'lon' columns in calls data.")
        calls_df['lat'] = pd.to_numeric(calls_df['lat'], errors='coerce')
        calls_df['lon'] = pd.to_numeric(calls_df['lon'], errors='coerce')
        calls_df = calls_df.dropna(subset=['lat', 'lon']).reset_index(drop=True)
        if calls_df.empty:
            raise ValueError('.brinc file contains no valid coordinate data after parsing.')
        session_state['df_calls'] = calls_df
        session_state['df_calls_full'] = calls_df.copy()
        session_state['total_original_calls'] = int(save_data.get('total_original_calls', len(calls_df)) or len(calls_df))
        session_state['total_modeled_calls'] = int(save_data.get('total_modeled_calls', len(calls_df)) or len(calls_df))

    stations_data = save_data.get('stations_data')
    if stations_data:
        stations_df = pd.DataFrame(stations_data)
        if 'lat' in stations_df.columns and 'lon' in stations_df.columns:
            stations_df['lat'] = pd.to_numeric(stations_df['lat'], errors='coerce')
            stations_df['lon'] = pd.to_numeric(stations_df['lon'], errors='coerce')
            stations_df = stations_df.dropna(subset=['lat', 'lon']).reset_index(drop=True)
            session_state['df_stations'] = stations_df

    session_state['boundary_kind'] = save_data.get('boundary_kind', 'place')
    session_state['boundary_source_path'] = save_data.get('boundary_source_path', '')

    boundary_geojson = save_data.get('boundary_geojson')
    if boundary_geojson:
        try:
            boundary_gdf = gpd.read_file(io.StringIO(boundary_geojson))
            if not boundary_gdf.empty:
                session_state['master_gdf_override'] = boundary_gdf
        except Exception:
            pass

    if session_state.get('master_gdf_override') is None and calls_data:
        try:
            app_mod = sys.modules.get('__main__')
            resolver = getattr(app_mod, '_select_best_boundary_for_calls', None) if app_mod is not None else None
            if resolver is None:
                import app as app_mod  # Local import to avoid tightening the module dependency graph.
                resolver = getattr(app_mod, '_select_best_boundary_for_calls', None)

            if resolver is not None:
                boundary_success, boundary_gdf, boundary_kind, _ = resolver(
                    calls_df,
                    session_state.get('active_city', ''),
                    session_state.get('active_state', ''),
                    prefer_county=bool(session_state.get('use_county_boundary', False)),
                )
                if boundary_success and boundary_gdf is not None and not boundary_gdf.empty:
                    session_state['master_gdf_override'] = boundary_gdf
                    session_state['boundary_kind'] = boundary_kind
        except Exception:
            pass
    session_state['boundary_overlay_gdf'] = None
    session_state['boundary_overlay_name'] = ''
    session_state['boundary_overlay_file'] = ''

    if save_data.get('faa_geojson'):
        session_state['_faa_geojson_cache'] = save_data['faa_geojson']

    session_state['brinc_user'] = save_data.get('brinc_user', '')
    session_state['pricing_tier'] = save_data.get('pricing_tier', 'Safe Guard')
    session_state['custom_responder_cost'] = int(save_data.get('custom_responder_cost', 79999) or 79999)
    session_state['custom_guardian_cost'] = int(save_data.get('custom_guardian_cost', 159999) or 159999)
    session_state['data_source'] = 'brinc_file'
    session_state['demo_mode_used'] = False
    session_state['sim_mode_used'] = False
    session_state['map_build_logged'] = False
    session_state['csvs_ready'] = True

    # ── Extended session state ────────────────────────────────────────────────
    # Jurisdiction metrics (only restore if explicitly saved; calls-derived
    # total_original_calls is already set above from len(calls_df))
    if 'estimated_pop' in save_data:
        session_state['estimated_pop'] = int(save_data['estimated_pop'] or 0)
    session_state['_pop_resolved'] = bool(save_data.get('_pop_resolved', False))
    if 'total_original_calls' in save_data and 'calls_data' not in save_data:
        session_state['total_original_calls'] = int(save_data['total_original_calls'] or 0)
    if 'total_modeled_calls' in save_data and 'calls_data' not in save_data:
        session_state['total_modeled_calls'] = int(save_data['total_modeled_calls'] or 0)
    if 'population_reference_kind' in save_data:
        session_state['population_reference_kind'] = str(save_data.get('population_reference_kind') or '')
    if isinstance(save_data.get('population_reference_targets'), list):
        session_state['population_reference_targets'] = [
            str(target or '').strip() for target in save_data.get('population_reference_targets', []) if str(target or '').strip()
        ]
    if save_data.get('inferred_daily_calls_override') is not None:
        session_state['inferred_daily_calls_override'] = save_data['inferred_daily_calls_override']
    if save_data.get('active_dept_name'):
        session_state['active_dept_name'] = save_data['active_dept_name']
    if save_data.get('file_meta'):
        session_state['file_meta'] = dict(save_data['file_meta'])
    if save_data.get('session_start'):
        session_state['session_start'] = str(save_data['session_start'])
    if isinstance(save_data.get('export_event_log'), list):
        session_state['export_event_log'] = [str(item or '') for item in save_data.get('export_event_log', [])]
    if 'export_count' in save_data:
        session_state['export_count'] = int(save_data.get('export_count') or 0)

    # Display options — restore widget keys so toggles/sliders pick up saved state
    _bool_display_keys = [
        'show_satellite_b', 'show_boundaries_b', 'show_faa_b', 'show_no_fly_b',
        'show_obstacles_b', 'show_coverage_b', 'show_cell_towers_b', 'show_heatmap_b',
        'show_dots_b', 'show_rapid_response_ring_b', 'simulate_traffic_b', 'show_health_b', 'show_financials_b',
        'simple_cards_b',
    ]
    for _k in _bool_display_keys:
        if _k in save_data:
            session_state[_k] = bool(save_data[_k])

    # Document customization
    for _k in ('doc_custom_intro', 'doc_talking_pt_1', 'doc_talking_pt_2',
                'doc_talking_pt_3', 'doc_custom_closing', 'doc_ae_phone'):
        if _k in save_data:
            session_state[_k] = str(save_data[_k] or '')


def split_uploaded_files(uploaded_files, is_boundary_sidecar, looks_like_stations):
    file_list = list(uploaded_files)
    call_files = []
    station_file = None
    boundary_files = []

    for uploaded_file in file_list:
        if is_boundary_sidecar(uploaded_file.name):
            boundary_files.append(uploaded_file)
        elif looks_like_stations(uploaded_file.name):
            station_file = uploaded_file
        else:
            call_files.append(uploaded_file)

    if len(call_files) == 2 and not station_file:
        first_file, second_file = call_files
        first_file.seek(0)
        first_size = len(first_file.read())
        first_file.seek(0)
        second_file.seek(0)
        second_size = len(second_file.read())
        second_file.seek(0)
        larger = max(first_size, second_size)
        smaller = min(first_size, second_size)
        # Only reassign the smaller file as stations if it is at least 10x smaller —
        # two similarly-sized files are almost certainly both CAD exports.
        if smaller > 0 and larger / smaller >= 10:
            if first_size >= second_size:
                call_files = [first_file]
                station_file = second_file
            else:
                call_files = [second_file]
                station_file = first_file

    if station_file is None and len(call_files) > 1:
        for candidate in list(call_files):
            if _looks_like_station_upload_content(candidate):
                station_file = candidate
                call_files = [uploaded_file for uploaded_file in call_files if uploaded_file is not candidate]
                break

    return call_files, station_file, boundary_files


def _looks_like_station_upload_content(uploaded_file):
    """Best-effort station-file detector for uploads without a helpful filename."""
    try:
        station_df = _read_station_upload(uploaded_file)
        station_df = _normalize_station_columns(station_df)
        station_df, single_col_note = _extract_single_column_station_addresses(station_df)
        cols = {str(column).lower().strip() for column in station_df.columns}
        row_count = len(station_df)
        if single_col_note:
            return True
        if not cols:
            return False
        if row_count > 40:
            return False
        has_coords = {'lat', 'lon'}.issubset(cols)
        has_station_shape = bool(cols & {'name', 'type', 'address', 'lat', 'lon'})
        cad_like = bool(cols & {'date', 'time', 'priority', 'call_type_desc', 'nature', 'description'})
        return bool(has_coords and has_station_shape and not cad_like)
    except Exception:
        return False


def _read_station_upload(uploaded_file):
    station_name = str(getattr(uploaded_file, 'name', '')).lower()
    if station_name.endswith(('.xlsx', '.xls', '.xlsm', '.xlsb')):
        engine = 'xlrd' if station_name.endswith('.xls') else 'pyxlsb' if station_name.endswith('.xlsb') else 'openpyxl'
        uploaded_file.seek(0)
        return pd.read_excel(io.BytesIO(uploaded_file.getvalue()), engine=engine)
    uploaded_file.seek(0)
    return pd.read_csv(uploaded_file)


def _normalize_station_columns(station_df):
    station_df = station_df.copy()
    station_df.columns = [str(column).lower().strip() for column in station_df.columns]
    if 'latitude' in station_df.columns:
        station_df = station_df.rename(columns={'latitude': 'lat'})
    if 'longitude' in station_df.columns:
        station_df = station_df.rename(columns={'longitude': 'lon'})
    if 'station_name' in station_df.columns:
        station_df = station_df.rename(columns={'station_name': 'name'})
    if 'station_type' in station_df.columns:
        station_df = station_df.rename(columns={'station_type': 'type'})
    return station_df


def _extract_single_column_station_addresses(station_df):
    if station_df is None or station_df.empty or len(station_df.columns) != 1:
        return station_df, None

    sole_col = station_df.columns[0]
    header_value = str(sole_col).strip()
    series = station_df.iloc[:, 0]
    values = [str(value).strip() for value in series.tolist() if pd.notna(value) and str(value).strip()]
    header_looks_like_address = any(ch.isdigit() for ch in header_value) and ',' in header_value

    if not values and not header_looks_like_address:
        return station_df, None

    address_rows = []
    if header_looks_like_address:
        address_rows.append(header_value)
    address_rows.extend(values)
    if not address_rows:
        return station_df, None

    extracted_df = pd.DataFrame({'address': address_rows})
    return extracted_df, 'Detected a single-column address list and treated each row as a station address.'


def _station_label_from_address(address_value, fallback_label):
    """Create a concise station label from an uploaded address string."""
    text = str(address_value or '').strip()
    if not text:
        return fallback_label

    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r',?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$', '', text)
    text = text.strip(' ,')
    return text or fallback_label


def _normalize_station_state_abbr(state_value, us_states_abbr=None):
    text = str(state_value or '').strip()
    if not text:
        return ''
    upper = text.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    if us_states_abbr:
        return str(us_states_abbr.get(text.title(), '') or '').strip().upper()
    return ''


def infer_simulation_targets_from_station_file(
    sim_uploader,
    forward_geocode,
    reverse_geocode_state,
    us_states_abbr,
    default_state='',
):
    station_df = _read_station_upload(sim_uploader)
    station_df = _normalize_station_columns(station_df)
    station_df, _single_col_note = _extract_single_column_station_addresses(station_df)

    city_col = next(
        (c for c in station_df.columns if c in ['city', 'town', 'village', 'municipality']),
        None,
    )
    state_col = next((c for c in station_df.columns if c in ['state', 'state_abbr', 'st']), None)
    addr_col = next((c for c in station_df.columns if any(a in c for a in ['address', 'street', 'location'])), None)
    fallback_state = _normalize_station_state_abbr(default_state, us_states_abbr)

    inferred_targets = []
    seen = set()
    geocode_used = False

    for _, row in station_df.iterrows():
        city_name = str(row[city_col]).strip() if city_col and pd.notna(row[city_col]) else ''
        state_name = (
            _normalize_station_state_abbr(row[state_col], us_states_abbr)
            if state_col and pd.notna(row[state_col]) else ''
        )
        address_value = str(row[addr_col]).strip() if addr_col and pd.notna(row[addr_col]) else ''

        if (not city_name or not state_name) and address_value:
            lat, lon = forward_geocode(address_value)
            if lat is not None and lon is not None:
                geocode_used = True
                state_full, reverse_city = reverse_geocode_state(lat, lon)
                if reverse_city and not city_name:
                    city_name = str(reverse_city).strip()
                if state_full and not state_name:
                    state_name = _normalize_station_state_abbr(state_full, us_states_abbr)
            time.sleep(1)

        if city_name and not state_name:
            state_name = fallback_state

        if not city_name or not state_name:
            continue

        dedupe_key = (city_name.strip().lower(), state_name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        inferred_targets.append({'city': city_name.strip(), 'state': state_name})

    notice = ''
    if inferred_targets and geocode_used:
        notice = 'Derived jurisdiction targets from the uploaded stations file.'
    return inferred_targets, notice


def load_station_file(station_file):
    stations_df = _read_station_upload(station_file)
    stations_df = _normalize_station_columns(stations_df)
    stations_df, single_col_note = _extract_single_column_station_addresses(stations_df)

    if 'lat' not in stations_df.columns or 'lon' not in stations_df.columns:
        if single_col_note:
            raise ValueError('Detected address rows but no lat/lon columns. In Path 01, address-only station files are geocoded during simulation upload.')
        raise ValueError('Could not find lat/lon columns.')

    stations_df['lat'] = pd.to_numeric(stations_df['lat'], errors='coerce')
    stations_df['lon'] = pd.to_numeric(stations_df['lon'], errors='coerce')

    if 'name' not in stations_df.columns:
        if 'address' in stations_df.columns:
            stations_df['name'] = [
                _station_label_from_address(addr, f"Site {i+1}")
                for i, addr in enumerate(stations_df['address'])
            ]
        else:
            stations_df['name'] = [f"Site {i+1}" for i in range(len(stations_df))]
    else:
        stations_df['name'] = stations_df['name'].fillna('').astype(str).str.strip()
        stations_df['name'] = stations_df['name'].replace(r'(?i)^(null|<null>|nan|none)$', '', regex=True)
        if 'address' in stations_df.columns:
            stations_df['name'] = [
                name if name else _station_label_from_address(addr, f"Site {i+1}")
                for i, (name, addr) in enumerate(zip(stations_df['name'], stations_df['address']))
            ]
        else:
            stations_df['name'] = [name if name else f"Site {i+1}" for i, name in enumerate(stations_df['name'])]

    counts = {}
    deduped_names = []
    for name in stations_df['name']:
        if name in counts:
            counts[name] += 1
            deduped_names.append(f"{name} ({counts[name]})")
        else:
            counts[name] = 0
            deduped_names.append(name)
    stations_df['name'] = deduped_names

    if 'type' not in stations_df.columns:
        stations_df['type'] = 'Police'

    stations_df = stations_df.dropna(subset=['lat', 'lon']).reset_index(drop=True)
    return stations_df, 'Loaded stations from file.'


_BBOX_STATES = (
    ("FL", 24.5, 31.0, -87.6, -79.9),
    ("CA", 32.5, 42.0, -124.5, -114.1),
    ("TX", 25.8, 36.5, -106.6, -93.5),
    ("NY", 40.5, 45.0, -79.8, -71.9),
    ("IL", 36.9, 42.5, -91.5, -87.0),
    ("GA", 30.4, 35.0, -85.6, -80.8),
    ("NC", 33.8, 36.6, -84.3, -75.5),
    ("OH", 38.4, 42.0, -84.8, -80.5),
    ("PA", 39.7, 42.3, -80.5, -74.7),
    ("WA", 45.5, 49.0, -124.7, -116.9),
    ("AZ", 31.3, 37.0, -114.8, -109.0),
    ("CO", 36.9, 41.0, -109.1, -102.0),
    ("MO", 35.9, 40.6, -95.8, -89.1),
    ("NM", 31.3, 37.0, -109.1, -103.0),
    ("OR", 41.9, 46.2, -124.6, -116.5),
    ("TN", 34.9, 36.7, -90.3, -81.6),
    ("VA", 36.5, 39.5, -83.7, -75.2),
    ("SC", 32.0, 35.2, -83.4, -78.5),
    ("MI", 41.7, 48.3, -90.4, -82.4),
    ("WI", 42.5, 47.1, -92.9, -86.2),
    ("MN", 43.5, 49.4, -97.2, -89.5),
    ("IA", 40.4, 43.5, -96.6, -90.1),
    ("KS", 36.9, 40.0, -102.1, -94.6),
    ("NE", 40.0, 43.0, -104.1, -95.3),
    ("OK", 33.6, 37.0, -103.0, -94.4),
    ("AR", 33.0, 36.5, -94.6, -89.6),
    ("LA", 28.9, 33.0, -94.0, -88.8),
    ("MS", 30.2, 35.0, -91.7, -88.1),
    ("AL", 30.2, 35.0, -88.5, -84.9),
    ("IN", 37.8, 41.8, -88.1, -84.8),
    ("KY", 36.5, 39.1, -89.6, -81.9),
    ("WV", 37.2, 40.6, -82.6, -77.7),
    ("MD", 37.9, 39.7, -79.5, -75.0),
    ("DE", 38.4, 39.8, -75.8, -75.0),
    ("NJ", 38.9, 41.4, -75.6, -73.9),
    ("CT", 41.0, 42.1, -73.7, -71.8),
    ("RI", 41.1, 42.0, -71.9, -71.1),
    ("MA", 41.2, 42.9, -73.5, -69.9),
    ("VT", 42.7, 45.0, -73.4, -71.5),
    ("NH", 42.7, 45.3, -72.6, -70.7),
    ("ME", 43.1, 47.5, -71.1, -66.9),
    ("NV", 35.0, 42.0, -120.0, -114.0),
    ("UT", 36.9, 42.0, -114.1, -109.0),
    ("ID", 41.9, 49.0, -117.2, -111.0),
    ("MT", 44.4, 49.0, -116.1, -104.0),
    ("WY", 40.9, 45.0, -111.1, -104.0),
    ("ND", 45.9, 49.0, -104.1, -96.6),
    ("SD", 42.5, 45.9, -104.1, -96.4),
    ("AK", 54.0, 71.5, -168.0, -130.0),
    ("HI", 18.9, 22.2, -160.2, -154.8),
)


def detect_location_from_calls(df_calls, state_fips, us_states_abbr, reverse_geocode_state):
    detected_city = None
    detected_state = None
    detection_source = 'unknown'

    if '_csv_city' in df_calls.columns:
        city_val = str(df_calls['_csv_city'].iloc[0]).strip().title()
        if city_val and city_val.lower() not in ('nan', 'none', ''):
            detected_city = city_val
            detection_source = 'file'

    if '_csv_state' in df_calls.columns:
        state_val = str(df_calls['_csv_state'].iloc[0]).strip().upper()
        if state_val in state_fips:
            detected_state = state_val
            detection_source = 'file'
        elif state_val.title() in us_states_abbr:
            detected_state = us_states_abbr[state_val.title()]
            detection_source = 'file'

    if detected_city and not detected_state:
        try:
            geo_url = f"https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(detected_city)}&limit=1&countrycodes=us"
            req_geo = urllib.request.Request(geo_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
            with urllib.request.urlopen(req_geo, timeout=8) as resp_geo:
                geo_result = json.loads(resp_geo.read().decode('utf-8'))
            if geo_result:
                display_name = geo_result[0].get('display_name', '')
                parts = [p.strip() for p in display_name.split(',')]
                state_full = parts[2] if len(parts) >= 3 else ''
                if state_full in us_states_abbr:
                    detected_state = us_states_abbr[state_full]
                    detection_source = 'file'
        except Exception:
            pass

    if not detected_city or not detected_state:
        try:
            cen_lat = float(df_calls['lat'].median())
            cen_lon = float(df_calls['lon'].median())
            detected_state_full, detected_city_rg = reverse_geocode_state(cen_lat, cen_lon)
            if detected_state_full and detected_state_full in us_states_abbr:
                if not detected_state:
                    detected_state = us_states_abbr[detected_state_full]
                if not detected_city and detected_city_rg and detected_city_rg != 'Unknown City':
                    detected_city = detected_city_rg
                detection_source = 'centroid'
        except Exception:
            pass

    if not detected_city or not detected_state:
        try:
            cen_lat_fb = float(df_calls['lat'].median())
            cen_lon_fb = float(df_calls['lon'].median())
            fcc_url = (
                f"https://geo.fcc.gov/api/census/block/find"
                f"?latitude={cen_lat_fb}&longitude={cen_lon_fb}"
                f"&format=json&showall=false"
            )
            fcc_req = urllib.request.Request(
                fcc_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'}
            )
            with urllib.request.urlopen(fcc_req, timeout=8) as fcc_resp:
                fcc_data = json.loads(fcc_resp.read().decode('utf-8'))
            fcc_county = fcc_data.get('County', {}).get('name', '')
            fcc_state = fcc_data.get('State', {}).get('code', '')
            if fcc_county and fcc_state and fcc_state in state_fips:
                if not detected_state:
                    detected_state = fcc_state
                if not detected_city:
                    detected_city = fcc_county
                detection_source = 'fcc_centroid'
        except Exception:
            pass

    if not detected_state:
        try:
            cen_lat = float(df_calls['lat'].median())
            cen_lon = float(df_calls['lon'].median())
            for state_code, lat0, lat1, lon0, lon1 in _BBOX_STATES:
                if lat0 <= cen_lat <= lat1 and lon0 <= cen_lon <= lon1:
                    detected_state = state_code
                    detection_source = 'coord_bbox'
                    break
        except Exception:
            pass

    return detected_city, detected_state, detection_source


def clear_stale_boundary_shapefiles(shapefile_dir):
    try:
        for stale_path in glob.glob(os.path.join(shapefile_dir, '*.shp')):
            for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
                candidate = stale_path.replace('.shp', ext)
                try:
                    if os.path.exists(candidate):
                        os.remove(candidate)
                except Exception:
                    pass
    except Exception:
        pass


def resolve_uploaded_boundaries(
    st,
    session_state,
    df_calls,
    df_calls_full,
    state_fips,
    find_jurisdictions_by_coordinates,
    select_best_boundary_for_calls,
    save_boundary_gdf,
):
    stage_box = st.empty()
    stage_progress = st.progress(0, text="Resolving uploaded boundary…")

    def set_stage(step_pct, message):
        stage_box.info(message)
        try:
            stage_progress.progress(int(step_pct), text=message)
        except Exception:
            stage_progress.progress(int(step_pct))

    set_stage(15, "Checking uploaded CAD coordinates for an existing boundary match…")
    clear_stale_boundary_shapefiles('jurisdiction_data')
    session_state['boundary_source_path'] = ''
    session_state['master_gdf_override'] = None

    calls_for_boundary = df_calls_full if df_calls_full is not None and len(df_calls_full) > 0 else df_calls
    file_meta = session_state.get('file_meta') or {}
    file_city = str(file_meta.get('file_inferred_city', '') or '').strip()
    file_state = str(file_meta.get('file_inferred_state', '') or '').strip().upper()
    prefer_file_boundary = str(session_state.get('location_detection_source', '') or '').strip().lower() == 'file'

    def _name_based_candidate():
        if not file_city or not file_state or file_state not in state_fips:
            return None
        set_stage(35, "Using the file-inferred city/state to resolve the boundary…")
        boundary_success, boundary_gdf, boundary_kind, boundary_hits = select_best_boundary_for_calls(
            calls_for_boundary,
            file_city,
            file_state,
            prefer_county=False,
        )
        if not boundary_success or boundary_gdf is None:
            return None
        return {
            'source': 'file_name',
            'name': file_city,
            'state': file_state,
            'kind': boundary_kind,
            'gdf': boundary_gdf,
            'hits': int(boundary_hits or 0),
        }

    def _coord_based_candidate():
        set_stage(35, "Looking for a boundary in the local cache…")
        coord_gdf = find_jurisdictions_by_coordinates(calls_for_boundary)
        if coord_gdf is None or coord_gdf.empty:
            return None
        top = coord_gdf.iloc[0]
        display_name = str(top.get('DISPLAY_NAME', '') or '').strip()
        if not display_name:
            return None
        boundary_kind = str(top.get('boundary_kind', '') or '').strip().lower()
        if boundary_kind not in {'place', 'county', 'state'}:
            boundary_kind = 'county' if display_name.lower().endswith(' county') else 'place'
        return {
            'source': 'coordinates',
            'name': display_name,
            'state': file_state or str(session_state.get('active_state', '') or '').strip().upper(),
            'kind': boundary_kind,
            'gdf': coord_gdf[['DISPLAY_NAME', 'geometry']].copy(),
            'hits': int(top.get('data_count', 0) or 0),
        }

    name_candidate = _name_based_candidate() if prefer_file_boundary else None
    coord_candidate = _coord_based_candidate()

    chosen_candidate = None
    if name_candidate and coord_candidate:
        name_hits = int(name_candidate.get('hits', 0) or 0)
        coord_hits = int(coord_candidate.get('hits', 0) or 0)
        coord_name = str(coord_candidate.get('name', '') or '').strip().lower()
        name_name = str(name_candidate.get('name', '') or '').strip().lower()
        if coord_hits > name_hits or (coord_hits == name_hits and coord_name and name_name and coord_name != name_name):
            chosen_candidate = coord_candidate
            set_stage(70, f"Coordinates confirmed {coord_candidate['name']} with {coord_hits:,} matching call(s).")
        else:
            chosen_candidate = name_candidate
            set_stage(70, f"File name confirmed {name_candidate['name']} with {name_hits:,} matching call(s).")
    else:
        chosen_candidate = coord_candidate or name_candidate

    if chosen_candidate is None:
        detected_city = session_state.get('active_city', '')
        detected_state = session_state.get('active_state', '')
        if not detected_city or not detected_state or detected_state not in state_fips:
            set_stage(100, "No active city/state was available for boundary resolution.")
            stage_progress.empty()
            stage_box.empty()
            return

        city_text = str(detected_city).strip()
        prefer_county = str(session_state.get('location_detection_source', '')) == 'centroid'
        set_stage(55, "Selecting the best county or place boundary for the current jurisdiction…")
        boundary_success, boundary_gdf, boundary_kind, _ = select_best_boundary_for_calls(
            calls_for_boundary,
            city_text,
            detected_state,
            prefer_county=prefer_county,
        )
        session_state['boundary_kind'] = boundary_kind
        session_state['boundary_detection_mode'] = 'detected_city_fallback'
        if boundary_success and boundary_gdf is not None:
            set_stage(85, "Saving the resolved boundary for faster reuse next time…")
            saved_path = save_boundary_gdf(boundary_gdf, boundary_kind, city_text, detected_state)
            session_state['boundary_source_path'] = saved_path or ''
            session_state['active_city'] = city_text
            session_state['active_state'] = detected_state
            session_state['master_gdf_override'] = boundary_gdf.copy()
        set_stage(100, "Boundary resolution complete.")
        stage_progress.empty()
        stage_box.empty()
        return

    chosen_gdf = chosen_candidate['gdf']
    chosen_kind = chosen_candidate['kind']
    chosen_name = chosen_candidate['name']
    chosen_state = chosen_candidate['state']
    session_state['boundary_detection_mode'] = chosen_candidate['source']
    session_state['boundary_kind'] = chosen_kind
    session_state['active_city'] = chosen_name
    if chosen_state:
        session_state['active_state'] = chosen_state
    set_stage(85, "Saving the resolved boundary for faster reuse next time…")
    saved_path = save_boundary_gdf(
        chosen_gdf,
        chosen_kind,
        chosen_name,
        chosen_state or file_state or str(session_state.get('active_state', '') or '').strip().upper(),
    )
    session_state['boundary_source_path'] = saved_path or ''
    session_state['master_gdf_override'] = chosen_gdf.copy()
    set_stage(100, "Boundary resolution complete.")
    stage_progress.empty()
    stage_box.empty()


def split_simulation_optional_files(optional_files, is_boundary_sidecar, looks_like_stations):
    station_file = None
    boundary_files = []
    non_boundary_files = []
    for optional_file in list(optional_files or []):
        if is_boundary_sidecar(optional_file.name):
            boundary_files.append(optional_file)
        else:
            non_boundary_files.append(optional_file)

    for optional_file in non_boundary_files:
        if looks_like_stations(optional_file.name):
            station_file = optional_file
            break

    if station_file is None and len(non_boundary_files) == 1:
        station_file = non_boundary_files[0]

    if station_file is None and len(non_boundary_files) > 1:
        for optional_file in non_boundary_files:
            if _looks_like_station_upload_content(optional_file):
                station_file = optional_file
                break

    unused_files = [
        optional_file.name for optional_file in non_boundary_files
        if station_file is None or optional_file.name != station_file.name
    ]
    return station_file, boundary_files, unused_files


def load_simulation_boundary_overlay(session_state, boundary_files, load_uploaded_boundary_overlay):
    session_state['boundary_overlay_gdf'] = None
    session_state['boundary_overlay_name'] = ''
    session_state['boundary_overlay_file'] = ''
    if not boundary_files:
        return None

    overlay_gdf, overlay_name, overlay_file = load_uploaded_boundary_overlay(boundary_files)
    session_state['boundary_overlay_gdf'] = overlay_gdf
    session_state['boundary_overlay_name'] = overlay_name
    session_state['boundary_overlay_file'] = overlay_file
    return overlay_file


def load_simulation_custom_stations(sim_uploader, active_targets, forward_geocode, search_public_facility_candidates=None):
    station_df = _read_station_upload(sim_uploader)
    station_df = _normalize_station_columns(station_df)
    station_df, _single_col_note = _extract_single_column_station_addresses(station_df)
    lat_col = next((c for c in station_df.columns if c in ['lat', 'latitude', 'y']), None)
    lon_col = next((c for c in station_df.columns if c in ['lon', 'long', 'longitude', 'x']), None)
    addr_col = next((c for c in station_df.columns if any(a in c for a in ['address', 'street', 'location'])), None)
    name_col = next((c for c in station_df.columns if any(n in c for n in ['name', 'station', 'facility', 'dept'])), None)
    type_col = next((c for c in station_df.columns if any(t in c for t in ['type', 'category'])), None)
    public_facility_types = {'Police', 'Fire', 'School', 'Government', 'Library'}

    def _looks_like_street_address(text):
        raw = str(text or '').strip().lower()
        if not raw or not re.search(r'\d', raw):
            return False
        street_tokens = (
            ' st', ' street', ' rd', ' road', ' ave', ' avenue', ' blvd', ' boulevard',
            ' dr', ' drive', ' ln', ' lane', ' ct', ' court', ' pkwy', ' parkway',
            ' hwy', ' highway', ' ter', ' terrace', ' cir', ' circle', ' way', ' pl',
            ' place', ' n ', ' s ', ' e ', ' w ',
        )
        return any(token in raw for token in street_tokens)

    parsed_stations = []
    ungeocoded = []
    for idx, row in station_df.iterrows():
        addr_str = str(row[addr_col]).strip() if addr_col and pd.notna(row[addr_col]) else ''
        station_label = (
            str(row[name_col]).strip()
            if name_col and pd.notna(row[name_col]) and str(row[name_col]).strip()
            else _station_label_from_address(addr_str, f'Custom Station {idx+1}')
        )
        station_type = str(row[type_col]) if type_col and pd.notna(row[type_col]) else 'Custom'
        station_lat, station_lon = None, None

        if lat_col and lon_col and pd.notna(row[lat_col]) and pd.notna(row[lon_col]):
            station_lat, station_lon = float(row[lat_col]), float(row[lon_col])
        elif addr_col and pd.notna(row[addr_col]):
            if search_public_facility_candidates and station_type in public_facility_types:
                city_hint = active_targets[0]['city'] if active_targets else ''
                state_hint = active_targets[0]['state'] if active_targets else ''
                public_matches = search_public_facility_candidates(
                    addr_str,
                    station_type,
                    limit=1,
                    preferred_city=city_hint,
                    preferred_state=state_hint,
                )
                if public_matches:
                    station_lat, station_lon = float(public_matches[0]['lat']), float(public_matches[0]['lon'])
                elif _looks_like_street_address(addr_str):
                    station_lat, station_lon = forward_geocode(addr_str)
                    if station_lat is None and active_targets:
                        station_lat, station_lon = forward_geocode(
                            f"{addr_str}, {active_targets[0]['city']}, {active_targets[0]['state']}"
                        )
            else:
                station_lat, station_lon = forward_geocode(addr_str)
                if station_lat is None and active_targets:
                    station_lat, station_lon = forward_geocode(
                        f"{addr_str}, {active_targets[0]['city']}, {active_targets[0]['state']}"
                    )
            if station_lat is None:
                ungeocoded.append(addr_str)
            time.sleep(1)

        if station_lat and station_lon:
            parsed_stations.append({
                'name': station_label,
                'lat': station_lat,
                'lon': station_lon,
                'type': station_type,
                'address': addr_str,
            })

    if not parsed_stations:
        return None, ungeocoded
    return pd.DataFrame(parsed_stations), ungeocoded



def resolve_demo_stations(
    df_calls,
    city_poly,
    sim_uploader,
    active_targets,
    forward_geocode,
    search_public_facility_candidates,
    generate_stations_from_calls,
    generate_random_points_in_polygon,
):
    notices = []
    warnings = []

    if sim_uploader is not None:
        try:
            custom_station_df, ungeocoded_addresses = load_simulation_custom_stations(
                sim_uploader,
                active_targets,
                forward_geocode,
                search_public_facility_candidates,
            )
            notices.extend([f"Could not geocode: {addr_str}" for addr_str in ungeocoded_addresses])
            if custom_station_df is not None and not custom_station_df.empty:
                return custom_station_df, True, notices, warnings
            warnings.append("Could not geocode or parse your custom stations. Falling back to generated stations.")
        except Exception as exc:
            warnings.append(f"Error reading custom stations: {exc}. Falling back to generated stations.")

    try:
        stations_df, osm_note = generate_stations_from_calls(df_calls)
    except Exception as exc:
        stations_df, osm_note = None, f"Remote station lookup failed: {exc}"

    if stations_df is not None and not stations_df.empty:
        notices.append(osm_note)
        return stations_df, False, notices, warnings

    warnings.append(f"{osm_note}. Falling back to random placements.")
    station_points = generate_random_points_in_polygon(city_poly, 100)
    station_types = ['Police', 'Fire', 'EMS'] * 34
    fallback_df = pd.DataFrame({
        'name': [f'Call-Density Station {i+1}' for i in range(len(station_points))],
        'lat': [point[0] for point in station_points],
        'lon': [point[1] for point in station_points],
        'type': station_types[:len(station_points)],
        'source': ['CALL_DENSITY'] * len(station_points),
    })
    return fallback_df, False, notices, warnings

def build_demo_boundaries(
    session_state,
    active_targets,
    state_fips,
    known_populations,
    demo_cities,
    fetch_county_boundary_local,
    fetch_place_boundary_local,
    fetch_tiger_state_shapefile,
    save_boundary_gdf,
    fetch_census_population,
    fetch_census_state_population,
):
    all_gdfs = []
    boundary_records = []
    total_estimated_pop = 0
    all_populations_verified = True
    boundary_messages = []
    warnings = []
    rerun_demo_target = None

    for index, loc in enumerate(active_targets):
        city_name = loc['city'].strip()
        state_name = loc['state']
        is_state = not city_name and state_name in state_fips
        city_name_lower = city_name.lower()
        is_county = city_name_lower.endswith(' county')
        is_township = city_name_lower.endswith(' township')
        boundary_kind = 'state' if is_state else ('county' if is_county else 'place')

        if is_state:
            success, temp_gdf = fetch_tiger_state_shapefile(state_fips[state_name], state_name, 'jurisdiction_data')
            if success:
                boundary_kind = 'state'
                city_name = state_name
        elif is_county:
            success, temp_gdf = fetch_county_boundary_local(state_name, city_name)
            if not success:
                success, temp_gdf = fetch_county_boundary_local(state_name, city_name + ' County')
            if success:
                boundary_kind = 'county'
        elif is_township:
            success, temp_gdf = fetch_place_boundary_local(state_name, city_name)
            if success:
                boundary_kind = 'place'
        else:
            success, temp_gdf = fetch_place_boundary_local(state_name, city_name)
            if success:
                boundary_kind = 'place'
            else:
                success, temp_gdf = fetch_county_boundary_local(state_name, city_name)
                if not success:
                    success, temp_gdf = fetch_county_boundary_local(state_name, city_name + ' County')
                if success:
                    boundary_kind = 'county'

        is_county = boundary_kind == 'county'
        is_state = boundary_kind == 'state'
        session_state['boundary_kind'] = boundary_kind

        if success and temp_gdf is not None:
            saved_path = save_boundary_gdf(temp_gdf, boundary_kind, city_name, state_name)
            if index == 0:
                session_state['boundary_source_path'] = saved_path or ''

        if success:
            all_gdfs.append(temp_gdf)
            population = (
                fetch_census_state_population(state_fips[state_name])
                if is_state else
                fetch_census_population(state_fips[state_name], city_name, is_county=is_county)
            )
            if population:
                total_estimated_pop += population
                boundary_messages.append(f"✅ {city_name or state_name} population verified: {population:,}")
            else:
                all_populations_verified = False
                gdf_proj = temp_gdf.to_crs(epsg=3857)
                area_sq_mi = gdf_proj.geometry.area.sum() / 2589988.11
                default_density = 35 if is_state else (120 if is_county else 3500)
                estimated_pop = known_populations.get(city_name or state_name, int(area_sq_mi * default_density))
                total_estimated_pop += estimated_pop
                boundary_messages.append(f"⚠️ {city_name or state_name} population estimated: {estimated_pop:,}")
                population = estimated_pop
            boundary_records.append({
                'name': city_name or state_name,
                'state': state_name,
                'boundary_kind': boundary_kind,
                'population': int(population or 0),
                'geometry': temp_gdf.geometry.union_all(),
            })
        else:
            warnings.append(f"⚠️ Could not find a boundary for {city_name or state_name}, {state_name}. Try another city or state.")
            if session_state.get('_last_demo_city') == city_name:
                candidates = [city for city in demo_cities if city[0] != city_name]
                rerun_demo_target = random.choice(candidates)

    if not all_gdfs:
        all_populations_verified = False

    boundary_messages = [_normalize_display_text(msg) for msg in boundary_messages]
    warnings = [_normalize_display_text(msg) for msg in warnings]

    return all_gdfs, boundary_records, total_estimated_pop, boundary_messages, warnings, rerun_demo_target, all_populations_verified


def _allocate_demo_counts(weights, total_count):
    if total_count <= 0:
        return [0 for _ in weights]
    weight_total = sum(max(float(weight or 0), 0.0) for weight in weights)
    if weight_total <= 0:
        base = total_count // max(len(weights), 1)
        counts = [base for _ in weights]
        for index in range(total_count - sum(counts)):
            counts[index % max(len(weights), 1)] += 1
        return counts

    raw = [(max(float(weight or 0), 0.0) / weight_total) * total_count for weight in weights]
    counts = [int(value) for value in raw]
    remainder = total_count - sum(counts)
    order = sorted(
        range(len(raw)),
        key=lambda index: (raw[index] - counts[index], weights[index]),
        reverse=True,
    )
    for index in order[:remainder]:
        counts[index] += 1
    return counts


def build_demo_calls(city_poly, total_estimated_pop, generate_clustered_calls, boundary_records=None, max_preview_points=None):
    annual_cfs = int(total_estimated_pop * 0.6)
    if boundary_records:
        boundary_weights = [int(record.get('population', 0) or 0) * 0.6 for record in boundary_records]
        weighted_annual_cfs = sum(int(weight) for weight in boundary_weights)
        if weighted_annual_cfs > 0:
            annual_cfs = weighted_annual_cfs
    simulated_points_count = max(int(round(annual_cfs)), 0)
    preview_cap = None
    if max_preview_points is not None:
        try:
            preview_cap = max(0, int(max_preview_points))
        except Exception:
            preview_cap = None
    if preview_cap:
        # Keep the live preview responsive for county-scale inputs while
        # preserving the annual call estimate in annual_cfs.
        simulated_points_count = min(simulated_points_count, preview_cap)
    np.random.seed(42)
    random.seed(42)
    call_points = []

    if boundary_records:
        boundary_weights = [int(record.get('population', 0) or 0) * 0.6 for record in boundary_records]
        allocations = _allocate_demo_counts(boundary_weights, simulated_points_count)
        for record, allocation in zip(boundary_records, allocations):
            if allocation <= 0:
                continue
            record_geometry = record.get('geometry')
            if record_geometry is None or record_geometry.is_empty:
                continue
            call_points.extend(generate_clustered_calls(record_geometry, allocation))
        random.shuffle(call_points)

    if not call_points:
        call_points = generate_clustered_calls(city_poly, simulated_points_count)

    base_date = datetime.datetime.now() - datetime.timedelta(days=364)
    fake_datetimes = [
        base_date + datetime.timedelta(
            days=random.randint(0, 364),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        for _ in range(simulated_points_count)
    ]

    demo_df = pd.DataFrame({
        'lat': [point[0] for point in call_points],
        'lon': [point[1] for point in call_points],
        'priority': np.random.choice([1, 2, 3], simulated_points_count, p=[0.15, 0.35, 0.50]),
        'date': [dt.strftime('%Y-%m-%d') for dt in fake_datetimes],
        'time': [dt.strftime('%H:%M:%S') for dt in fake_datetimes],
    })
    return demo_df, annual_cfs, simulated_points_count




