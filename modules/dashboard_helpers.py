"""Helpers for dashboard runtime behavior."""

import datetime
import math
import re
import glob
import os

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from shapely.ops import unary_union

from modules.config import calculate_max_flights_per_day, US_STATES_ABBR, text_muted
from modules.versioning import __version__ as _app_version


def log_map_build_event_once(session_state, log_to_sheets):
    if session_state.get('map_build_logged', False):
        return
    # Wait until population has been resolved from census — avoids logging the 65000 default
    if not session_state.get('_pop_resolved', False):
        return

    try:
        map_city = session_state.get('active_city', '')
        map_state = session_state.get('active_state', '')
        brinc_raw = session_state.get('brinc_user', '').strip()
        if not brinc_raw:
            brinc_raw = 'unknown'
        map_name = " ".join(word.capitalize() for word in brinc_raw.split('.'))
        map_email = f"{brinc_raw}@brincdrones.com" if brinc_raw != 'unknown' else ''
        map_pop = session_state.get('estimated_pop', 0)
        map_calls = session_state.get('total_original_calls', 0)
        map_daily = max(1, int(map_calls / 365))
        session_start = session_state.get(
            'session_start',
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        try:
            start_dt = datetime.datetime.strptime(session_start, '%Y-%m-%d %H:%M:%S')
            duration_min = round((datetime.datetime.now() - start_dt).total_seconds() / 60, 1)
        except Exception:
            duration_min = ''

        map_details = {
            'session_id': session_state.get('session_id', ''),
            'session_start': session_start,
            'session_duration_min': duration_min,
            'data_source': session_state.get('data_source', 'unknown'),
            'population': map_pop,
            'total_calls': map_calls,
            'daily_calls': map_daily,
            'area_sq_mi': 0,
            'fleet_capex': 0,
            'annual_savings': 0,
            'break_even': 'N/A',
            'opt_strategy': '',
            'dfr_rate': session_state.get('dfr_rate', 0),
            'deflect_rate': session_state.get('deflect_rate', 0),
            'incremental_build': False,
            'allow_redundancy': False,
            'avg_response_min': 0,
            'avg_time_saved_min': 0,
            'area_covered_pct': 0,
            'active_drones': [],
        }
        log_to_sheets(map_city, map_state, 'MAP_BUILD', 0, 0, 0.0, map_name, map_email, map_details)
        session_state['map_build_logged'] = True
    except Exception:
        pass


def resolve_master_boundary(
    st,
    session_state,
    df_calls,
    df_stations_all,
    shapefile_dir,
    fetch_county_by_centroid,
    get_jurisdiction_message,
    get_relevant_jurisdictions_cached,
    boundary_shp_base,
    sanitize_boundary_token,
):
    use_county = session_state.get('use_county_boundary', False)
    master_override = session_state.get('master_gdf_override')
    stage_box = st.empty()
    stage_progress = st.progress(0, text="Resolving jurisdiction boundary…")

    def set_stage(step_pct, message):
        stage_box.info(message)
        try:
            stage_progress.progress(int(step_pct), text=message)
        except Exception:
            stage_progress.progress(int(step_pct))

    if use_county:
        active_state = session_state.get('active_state', '')
        county_cache_key = f"{active_state}|county"
        if (
            session_state.get('_county_boundary_cache_key') == county_cache_key
            and session_state.get('_county_boundary_gdf') is not None
        ):
            set_stage(100, "Using cached county boundary.")
            master_gdf = session_state['_county_boundary_gdf'].copy()
        else:
            set_stage(20, "Checking county boundary cache and county lookup data…")
            with st.spinner("Loading county boundary…"):
                ok, county_gdf = fetch_county_by_centroid(df_calls, active_state)
            if ok and county_gdf is not None:
                set_stage(60, "County boundary found. Finalizing jurisdiction geometry…")
                county_gdf = county_gdf.copy()
                county_gdf['DISPLAY_NAME'] = county_gdf['NAME'].astype(str)
                county_gdf['data_count'] = len(df_calls)
                session_state['_county_boundary_gdf'] = county_gdf.copy()
                session_state['_county_boundary_cache_key'] = county_cache_key
                master_gdf = county_gdf.copy()
            else:
                st.warning("County boundary not found — check that counties_lite.parquet is present.")
                if master_override is not None and not master_override.empty:
                    set_stage(70, "County boundary unavailable. Using the uploaded override boundary.")
                    master_gdf = master_override.copy()
                else:
                    set_stage(75, "County boundary unavailable. Resolving jurisdiction from uploaded calls…")
                    with st.spinner(get_jurisdiction_message()):
                        preferred_shp = session_state.get('boundary_source_path', '') or None
                        master_gdf = get_relevant_jurisdictions_cached(
                            df_calls,
                            shapefile_dir,
                            preferred_shp=preferred_shp,
                        )
    elif master_override is not None and not master_override.empty:
        set_stage(100, "Using uploaded boundary override.")
        master_gdf = master_override.copy()
    else:
        set_stage(35, "Resolving jurisdiction from uploaded calls…")
        with st.spinner(get_jurisdiction_message()):
            preferred_shp = session_state.get('boundary_source_path', '') or None
            master_gdf = get_relevant_jurisdictions_cached(
                df_calls,
                shapefile_dir,
                preferred_shp=preferred_shp,
            )

    boundary_kind_note = session_state.get('boundary_kind', 'place')
    boundary_src_note = session_state.get('boundary_source_path', '')

    if master_gdf is None or master_gdf.empty:
        shp_files = glob.glob(os.path.join(shapefile_dir, '*.shp'))
        if shp_files:
            try:
                set_stage(60, "Searching local shapefiles for the best matching boundary…")
                preferred_kind = session_state.get('boundary_kind', 'place')
                active_city = session_state.get('active_city', '')
                active_state = session_state.get('active_state', '')
                best = session_state.get('boundary_source_path', '') or None

                if not best:
                    exact = boundary_shp_base(preferred_kind, active_city, active_state) + '.shp'
                    if os.path.exists(exact):
                        best = exact

                if not best:
                    city_key = sanitize_boundary_token(active_city).lower()
                    typed = []
                    other = []
                    for shp_file in shp_files:
                        base = os.path.basename(shp_file).lower()
                        if base.startswith(preferred_kind + '__'):
                            typed.append(shp_file)
                        else:
                            other.append(shp_file)
                    for shp_file in typed + other:
                        if city_key and city_key in os.path.basename(shp_file).lower():
                            best = shp_file
                            break

                if best is None:
                    fb_lat_min = df_calls['lat'].min()
                    fb_lat_max = df_calls['lat'].max()
                    fb_lon_min = df_calls['lon'].min()
                    fb_lon_max = df_calls['lon'].max()
                    overlap_pad = 2.0
                    try:
                        import fiona as optional_fiona
                        fiona_available = True
                    except ImportError:
                        optional_fiona = None
                        fiona_available = False
                    for shp_candidate in shp_files:
                        try:
                            if not fiona_available:
                                raise ImportError('fiona not available')
                            with optional_fiona.open(shp_candidate) as collection:
                                shape_bounds = collection.bounds
                            overlaps = not (
                                shape_bounds[2] < fb_lon_min - overlap_pad
                                or shape_bounds[0] > fb_lon_max + overlap_pad
                                or shape_bounds[3] < fb_lat_min - overlap_pad
                                or shape_bounds[1] > fb_lat_max + overlap_pad
                            )
                            if overlaps:
                                best = shp_candidate
                                break
                        except Exception:
                            best = shp_candidate
                            break
                    if best is None:
                        master_gdf = None
                        raise ValueError('No overlapping shapefiles found')

                fallback_gdf = gpd.read_file(best)
                if fallback_gdf.crs is None:
                    fallback_gdf = fallback_gdf.set_crs(epsg=4269)
                fallback_gdf = fallback_gdf.to_crs(epsg=4326)
                name_col = next(
                    (column for column in ['NAME', 'DISTRICT', 'NAMELSAD'] if column in fallback_gdf.columns),
                    fallback_gdf.columns[0],
                )
                fallback_gdf['DISPLAY_NAME'] = fallback_gdf[name_col].astype(str)
                fallback_gdf['data_count'] = len(df_calls)
                master_gdf = fallback_gdf[['DISPLAY_NAME', 'data_count', 'geometry']]
                session_state['boundary_source_path'] = best
                boundary_src_note = best
                set_stage(90, "Boundary resolved from local shapefile cache.")
            except Exception:
                master_gdf = None

    if master_gdf is None or master_gdf.empty:
        set_stage(95, "No boundary cache matched. Generating a temporary boundary.")
        min_lon, min_lat = df_calls['lon'].min(), df_calls['lat'].min()
        max_lon, max_lat = df_calls['lon'].max(), df_calls['lat'].max()
        lon_pad = (max_lon - min_lon) * 0.1
        lat_pad = (max_lat - min_lat) * 0.1
        poly = box(min_lon - lon_pad, min_lat - lat_pad, max_lon + lon_pad, max_lat + lat_pad)
        master_gdf = gpd.GeoDataFrame(
            {'DISPLAY_NAME': ['Auto-Generated Boundary'], 'data_count': [len(df_calls)]},
            geometry=[poly],
            crs='EPSG:4326',
        )

    stage_progress.empty()
    stage_box.empty()
    return master_gdf, boundary_kind_note, boundary_src_note


def render_sidebar_jurisdiction_selector(
    st,
    session_state,
    master_gdf,
    boundary_kind_note,
    boundary_src_note,
    get_themed_logo_base64,
    boundary_overlay_status,
    city_boundary_geom=None,
    epsg_code=None,
):
    logo_b64 = get_themed_logo_base64('logo.png', theme='dark')
    if logo_b64:
        st.sidebar.markdown(
            f"""
            <div style="background-color: transparent; padding: 40px 20px 10px 20px; margin: -60px -20px 20px -20px; text-align: center; pointer-events: none;">
                <img src="data:image/png;base64,{logo_b64}" style="height: 60px;">
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.sidebar.markdown(
            """
            <div style="background-color: transparent; padding: 40px 20px 10px 20px; margin: -60px -20px 20px -20px; text-align: center; pointer-events: none;">
                <div style="font-size:26px; font-weight:900; letter-spacing:3px; color:#ffffff;">BRINC</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.sidebar.markdown(
        f'<div class="sidebar-section-header">① Configure'
        f'<span style="font-size:0.6rem;font-weight:400;letter-spacing:0.06em;color:rgba(160,175,190,0.6);margin-left:8px;">'
        f'v {_app_version}</span></div>',
        unsafe_allow_html=True,
    )
    jur_source_file = session_state.get('_jur_source_file', '')
    boundary_src_display = (
        jur_source_file if boundary_src_note == 'local_parquet' and jur_source_file
        else 'local_parquet' if boundary_src_note == 'local_parquet'
        else (boundary_src_note.split(chr(47))[-1].split(chr(92))[-1] if boundary_src_note else 'live lookup')
    )
    st.sidebar.caption(f"Boundary: {boundary_kind_note} - {boundary_src_display}")

    sidebar_overlay_gdf = session_state.get('boundary_overlay_gdf')
    if sidebar_overlay_gdf is not None and not sidebar_overlay_gdf.empty:
        overlay_file = session_state.get('boundary_overlay_file', '') or session_state.get('boundary_overlay_name', 'uploaded boundary')
        st.sidebar.caption(f"Overlay: {overlay_file} (display only)")
        sidebar_overlay_status = None
        if city_boundary_geom is not None and not city_boundary_geom.is_empty and epsg_code is not None:
            sidebar_overlay_status = boundary_overlay_status(city_boundary_geom, sidebar_overlay_gdf, epsg_code)
        if sidebar_overlay_status:
            if sidebar_overlay_status['status'] == 'inside':
                st.sidebar.info(sidebar_overlay_status['message'])
            else:
                st.sidebar.warning(sidebar_overlay_status['message'])

    master_gdf = master_gdf.copy()
    if 'DISPLAY_NAME' not in master_gdf.columns:
        master_gdf['DISPLAY_NAME'] = master_gdf.index.astype(str)
    if 'data_count' not in master_gdf.columns:
        master_gdf['data_count'] = 1
    else:
        master_gdf['data_count'] = pd.to_numeric(master_gdf['data_count'], errors='coerce').fillna(0)
        if float(master_gdf['data_count'].sum() or 0) <= 0:
            master_gdf['data_count'] = 1

    total_pts = float(master_gdf['data_count'].sum() or len(master_gdf) or 1)
    master_gdf['LABEL'] = (
        master_gdf['DISPLAY_NAME'].astype(str)
        + ' ('
        + (master_gdf['data_count'] / total_pts * 100).round(1).astype(str)
        + '%)'
    )
    options_map = dict(zip(master_gdf['LABEL'], master_gdf['DISPLAY_NAME']))
    all_options = master_gdf['LABEL'].tolist()
    default_selection = [all_options[0]] if all_options else []
    saved_selection_names = []
    for _saved_name in (session_state.get('saved_jurisdiction_names') or []):
        _saved_text = str(_saved_name or '').strip()
        if _saved_text:
            saved_selection_names.append(_saved_text)
    if saved_selection_names:
        _saved_labels = [label for label, display_name in options_map.items() if display_name in saved_selection_names]
        if _saved_labels:
            default_selection = _saved_labels
    options_signature = tuple(all_options)
    current_selection = [
        label for label in (session_state.get('jurisdictions_multiselect') or [])
        if label in options_map
    ]
    if current_selection:
        default_selection = current_selection

    if session_state.get('_jurisdiction_options_signature') != options_signature:
        session_state['jurisdictions_multiselect'] = default_selection
        session_state['_jurisdiction_options_signature'] = options_signature

    selected_labels = st.sidebar.multiselect(
        'Jurisdictions',
        options=all_options,
        key='jurisdictions_multiselect',
        help='Select which geographic areas to include in coverage analysis.',
    )

    jur_debug = session_state.get('_jur_debug', [])
    jur_source = next((msg.split(': ')[1].split(' ')[0] for msg in jur_debug if 'parquet exists' in msg and 'True' in msg), None)
    if jur_source:
        session_state['_jur_source_file'] = jur_source

    if not selected_labels:
        st.warning('Please select at least one jurisdiction from the sidebar.')
        st.stop()

    selected_names = [options_map[label] for label in selected_labels]
    active_gdf = master_gdf[master_gdf['DISPLAY_NAME'].isin(selected_names)]
    if selected_names and session_state.get('active_city') == 'Orlando':
        session_state['active_city'] = str(selected_names[0]).title()

    return master_gdf, active_gdf, selected_names


def render_data_filters(st, df_stations_all, df_calls, df_calls_full):
    return df_stations_all, df_calls, df_calls_full


def render_display_options(st):
    disp_expander = st.sidebar.expander('👁️ Display Options', expanded=False)
    
    def section_header(label):
        st.markdown(
            f"<div style='font-size:0.7rem; color:{text_muted}; margin:10px 0 4px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>{label}</div>",
            unsafe_allow_html=True,
        )

    with disp_expander:
        section_header('🗺️ Map & Boundaries')
        show_satellite = st.toggle(
            'Satellite Imagery',
            value=False,
            key='show_satellite_b',
            help='Switch the basemap from the default street view to satellite imagery.',
        )
        show_boundaries = st.toggle(
            'Jurisdiction Boundaries',
            value=True,
            key='show_boundaries_b',
            help='Show the selected city or place boundary used for deployment analysis.',
        )
        st.toggle(
            'County Boundary',
            value=False,
            key='use_county_boundary',
            help='Redraw the map using the county boundary instead of the city/place boundary.',
        )

        section_header('✈️ Safety & Airspace')
        show_faa = st.toggle(
            'FAA LAANC Airspace',
            value=False,
            key='show_faa_b',
            help='Show FAA-authorized flight ceilings by area (LAANC). Lighter = higher altitude allowed.',
        )
        show_no_fly = st.toggle(
            'No-Fly Zones',
            value=False,
            key='show_no_fly_b',
            help='Parks, protected areas, and water. Reference for deployment planning.',
        )
        show_obstacles = st.toggle(
            'Flight Hazards',
            value=False,
            key='show_obstacles_b',
            help='FAA Digital Obstacle File: obstacles > 200 ft AGL. Diamond markers.',
        )

        section_header('📶 Infrastructure')
        show_coverage = st.toggle(
            '4G LTE Coverage',
            value=False,
            key='show_coverage_b',
            help='Show AT&T, T-Mobile, and Verizon 4G LTE coverage polygons. Toggle individual carriers in the map legend.',
        )
        show_cell_towers = st.toggle(
            'Cell Towers',
            value=False,
            key='show_cell_towers_b',
            help='OpenCelliD cell tower locations. Useful for data-link RF validation.',
        )

        section_header('🚨 Incident Analysis')
        show_heatmap = st.toggle(
            '911 Call Heatmap',
            value=False,
            key='show_heatmap_b',
            help='Show a density heatmap of 911 call locations to highlight incident concentration.',
        )
        show_dots = st.toggle(
            'Incident Dots',
            value=True,
            key='show_dots_b',
            help='Show individual 911 call locations as dots on the map.',
        )

        section_header('🛠️ Deployment Tools')
        show_station_suggestions = st.toggle(
            'Suggested Station Placements',
            value=True,
            key='show_station_suggestions_b',
            help='Show or hide the suggested station placement workflow and its map markers.',
        )
        if 'show_rapid_response_ring_b' not in st.session_state:
            st.session_state['show_rapid_response_ring_b'] = True
        st.toggle(
            'Rapid Response Ring',
            key='show_rapid_response_ring_b',
            help='Show or hide the highlighted 5-mile rapid response ring around extended Guardian stations.',
        )
        show_rapid_response_ring = bool(st.session_state.get('show_rapid_response_ring_b', True))
        simulate_traffic = st.toggle(
            'Simulate Ground Traffic',
            value=False,
            key='simulate_traffic_b',
            help='Apply traffic-based travel delays to ground response estimates and related metrics.',
        )
        traffic_level = st.slider('Traffic Congestion', 0, 100, 40, help='Simulates road congestion intensity. Higher values extend ground response times and related financial estimates.') if simulate_traffic else 40

        section_header('📊 Interface & Privacy')
        show_health = st.toggle(
            'Health Score',
            value=False,
            key='show_health_b',
            help='Show the department health score summary based on current deployment coverage and utilization.',
        )
        show_financials = st.toggle(
            'Show Financials',
            value=True,
            key='show_financials_b',
            help='Show or hide all financial figures (CapEx, annual savings, ROI, break-even, specialty values) on the cards and in the sidebar.',
        )
        show_cards = True
        simple_cards = st.toggle(
            'Simple Cards',
            value=False,
            key='simple_cards_b',
            help='Show a compact card with just the key numbers: name, type, response time, annual savings, and CapEx.',
        )

    return {
        'show_satellite': show_satellite,
        'show_boundaries': show_boundaries,
        'show_faa': show_faa,
        'show_no_fly': show_no_fly,
        'show_obstacles': show_obstacles,
        'show_coverage': show_coverage,
        'show_cell_towers': show_cell_towers,
        'show_heatmap': show_heatmap,
        'show_dots': show_dots,
        'show_station_suggestions': show_station_suggestions,
        'show_rapid_response_ring': show_rapid_response_ring,
        'simulate_traffic': simulate_traffic,
        'show_health': show_health,
        'show_financials': show_financials,
        'show_cards': show_cards,
        'simple_cards': simple_cards,
        'traffic_level': traffic_level,
    }


def render_deployment_strategy(st, session_state, config, text_muted):
    strat_expander = st.sidebar.expander('⚙️ Deployment Strategy', expanded=False)
    with strat_expander:
        st.markdown(
            f"<div style='font-size:0.7rem; color:{text_muted}; margin:0 0 4px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>Pricing Plan</div>",
            unsafe_allow_html=True,
        )
        pricing_tier = st.radio(
            'Pricing Plan',
            ('Safe Guard', 'Safe Guard Lite', 'Custom Quote'),
            index={'Safe Guard': 0, 'Safe Guard Lite': 1, 'Custom Quote': 2}.get(session_state.get('pricing_tier', 'Safe Guard'), 0),
            label_visibility='collapsed',
            help='Safe Guard (Responder $79,999 | Guardian $159,999): Advanced custom features and add-ons. Safe Guard Lite (Responder $59,999 | Guardian $119,999): Core functionality. Custom Quote: manual per-unit pricing override for sales scenarios.',
        )
        session_state['pricing_tier'] = pricing_tier
        session_state.setdefault('custom_responder_cost', 79999)
        session_state.setdefault('custom_guardian_cost', 159999)

        if pricing_tier == 'Safe Guard':
            config['RESPONDER_COST'] = 79999
            config['GUARDIAN_COST'] = 159999
            tier_badge = '🛡️ Safe Guard'
            tier_desc = 'Advanced Custom Features'
        else:
            config['RESPONDER_COST'] = 59999
            config['GUARDIAN_COST'] = 119999
            tier_badge = '🛡️ Safe Guard Lite'
            tier_desc = 'Core Functionality'

        if pricing_tier == 'Custom Quote':
            custom_responder_cost = int(st.number_input(
                'Custom Responder Price',
                min_value=0,
                step=1000,
                value=int(session_state.get('custom_responder_cost', 79999) or 79999),
                help='Per-unit Responder price used for fleet CapEx, ROI, and report outputs.',
            ))
            custom_guardian_cost = int(st.number_input(
                'Custom Guardian Price',
                min_value=0,
                step=1000,
                value=int(session_state.get('custom_guardian_cost', 159999) or 159999),
                help='Per-unit Guardian price used for fleet CapEx, ROI, and report outputs.',
            ))
            session_state['custom_responder_cost'] = custom_responder_cost
            session_state['custom_guardian_cost'] = custom_guardian_cost
            config['RESPONDER_COST'] = custom_responder_cost
            config['GUARDIAN_COST'] = custom_guardian_cost
            tier_badge = 'Custom Quote'
            tier_desc = 'Sales-Entered Pricing'

        st.markdown('---')

        incremental_build = st.toggle(
            'Phased Rollout',
            value=session_state.get('incremental_build', True),
            key='incremental_build',
            help='Place drones one at a time in priority order. Disable to find the global optimum in a single pass.',
        )
        auto_cap_dfr = st.toggle(
            'Auto-cap over-utilized stations',
            value=True,
            key='auto_cap_dfr',
            help="When on, each station's DFR rate is clamped to its own physical capacity limit — over-utilized stations run at their personal max without reducing the rate for all other stations.",
        )

        st.markdown(
            f"<div style='font-size:0.7rem; color:{text_muted}; margin:8px 0 4px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>Deployment Mode</div>",
            unsafe_allow_html=True,
        )
        deployment_mode = st.radio(
            'Deployment Mode',
            ('Complement — push apart', 'Independent — each uses its own objective', 'Shared — allow full overlap'),
            index=session_state.get('deployment_mode_idx', 1),
            label_visibility='collapsed',
            help=(
                'Complement: Responders fill gaps left by Guardians — no wasted overlap. '
                'Independent: each fleet optimises on its own objective; overlap allowed but not forced. '
                'Shared: both fleets optimise together against the same call set — hotspot stacking.'
            ),
        )
        mode_map = {
            'Complement — push apart': 0,
            'Independent — each uses its own objective': 1,
            'Shared — allow full overlap': 2,
        }
        session_state['deployment_mode_idx'] = mode_map.get(deployment_mode, 1)

        allow_redundancy = deployment_mode != 'Complement — push apart'
        complement_mode = deployment_mode == 'Complement — push apart'
        shared_mode = deployment_mode == 'Shared — allow full overlap'

        st.markdown(
            f"<div style='font-size:0.7rem; color:{text_muted}; margin:10px 0 4px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>Guardian Objective</div>",
            unsafe_allow_html=True,
        )
        guard_strategy_raw = st.radio(
            'Guardian Objective',
            ('Call Coverage', 'Land Coverage'),
            index=session_state.get('guard_strat_idx', 1),
            horizontal=True,
            label_visibility='collapsed',
            help='What the Guardian optimizer maximises. Land Coverage = wide area patrol. Call Coverage = respond to highest-volume locations.',
        )
        session_state['guard_strat_idx'] = 0 if guard_strategy_raw == 'Call Coverage' else 1
        guard_strategy = 'Maximize Call Coverage' if guard_strategy_raw == 'Call Coverage' else 'Maximize Land Coverage'

        st.markdown(
            f"<div style='font-size:0.7rem; color:{text_muted}; margin:10px 0 4px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>Responder Objective</div>",
            unsafe_allow_html=True,
        )
        resp_strategy_raw = st.radio(
            'Responder Objective',
            ('Call Coverage', 'Land Coverage'),
            index=session_state.get('resp_strat_idx', 1),
            horizontal=True,
            label_visibility='collapsed',
            help='What the Responder optimizer maximises. Call Coverage = densest incident areas. Land Coverage = broadest geographic reach.',
        )
        session_state['resp_strat_idx'] = 0 if resp_strategy_raw == 'Call Coverage' else 1
        resp_strategy = 'Maximize Call Coverage' if resp_strategy_raw == 'Call Coverage' else 'Maximize Land Coverage'

        st.markdown(
            f"<div style='font-size:0.7rem; color:{text_muted}; margin:10px 0 4px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>Coverage Ranges</div>",
            unsafe_allow_html=True,
        )
        resp_radius_mi = st.slider('🚁 Responder Range (mi)', 2.0, 3.0, float(session_state.get('r_resp', 2.0)), step=0.5, help='Flight radius for Responder drones. Smaller radius concentrates coverage; larger radius extends reach at the cost of density.')
        guard_radius_mi = st.slider(
            '🦅 Guardian Range (mi) [⚡ 5mi Rapid]',
            1,
            8,
            int(session_state.get('r_guard', 8)),
            help='The 5-mile rapid response focus zone will automatically be highlighted inside the maximum perimeter.',
        )

    return {
        'pricing_tier': pricing_tier,
        'tier_badge': tier_badge,
        'tier_desc': tier_desc,
        'incremental_build': incremental_build,
        'auto_cap_dfr': auto_cap_dfr,
        'deployment_mode': deployment_mode,
        'allow_redundancy': allow_redundancy,
        'complement_mode': complement_mode,
        'shared_mode': shared_mode,
        'guard_strategy_raw': guard_strategy_raw,
        'resp_strategy_raw': resp_strategy_raw,
        'guard_strategy': guard_strategy,
        'resp_strategy': resp_strategy,
        'resp_radius_mi': resp_radius_mi,
        'guard_radius_mi': guard_radius_mi,
    }


def prepare_station_candidates(
    st,
    session_state,
    active_gdf,
    df_calls,
    df_stations_all,
    calculate_zoom,
    boundary_overlay_status_fn,
    make_random_stations,
):
    minx, miny, maxx, maxy = active_gdf.to_crs(epsg=4326).total_bounds
    center_lon = (minx + maxx) / 2
    center_lat = (miny + maxy) / 2
    dynamic_zoom = calculate_zoom(minx, maxx, miny, maxy)
    utm_zone = int((center_lon + 180) / 6) + 1
    epsg_code = int(f'326{utm_zone}') if center_lat > 0 else int(f'327{utm_zone}')

    city_m = None
    city_boundary_geom = None
    try:
        active_utm = active_gdf.to_crs(epsg=epsg_code)
        raw_union = active_utm.geometry.union_all() if hasattr(active_utm.geometry, 'union_all') else active_utm.geometry.unary_union
        clean_geom = raw_union.buffer(1.0).buffer(-1.0)
        if clean_geom.is_empty or not clean_geom.is_valid:
            clean_geom = raw_union.buffer(0)
        if clean_geom.is_empty:
            clean_geom = raw_union
        city_m = clean_geom
        city_boundary_geom = gpd.GeoSeries([clean_geom], crs=epsg_code).to_crs(epsg=4326).iloc[0]
    except Exception as exc:
        st.error(f'Geometry Error: {exc}')
        st.stop()

    boundary_overlay_gdf = session_state.get('boundary_overlay_gdf')
    boundary_overlay_status = boundary_overlay_status_fn(city_boundary_geom, boundary_overlay_gdf, epsg_code)

    stations_user_uploaded = session_state.get('stations_user_uploaded', False)
    if not df_stations_all.empty and city_m is not None:
        station_gdf = gpd.GeoDataFrame(
            df_stations_all,
            geometry=gpd.points_from_xy(df_stations_all.lon, df_stations_all.lat),
            crs='EPSG:4326',
        )
        station_gdf_utm = station_gdf.to_crs(epsg=epsg_code)

        if stations_user_uploaded:
            # Preserve all uploaded candidate stations for optimization.
            # Uploaded files are user-authored deployment inputs, so we do not
            # silently drop rows just because one point falls outside the active
            # boundary polygon.
            pass
        else:
            mask = station_gdf_utm.within(city_m)
            df_inside = df_stations_all[mask].reset_index(drop=True)

            if df_inside.empty:
                st.info(
                    'ℹ️ No OSM public buildings were found inside the jurisdiction boundary. '
                    'Using call-density station placement — stations are snapped to incident '
                    'locations that fall inside the city limits.'
                )
                try:
                    df_stations_all = make_random_stations(df_calls, n=60, boundary_geom=city_m, epsg_code=epsg_code)
                except Exception:
                    df_stations_all = pd.DataFrame()

                if df_stations_all.empty:
                    try:
                        lats = df_calls['lat'].dropna()
                        lons = df_calls['lon'].dropna()
                        grid_lats = np.linspace(lats.quantile(0.1), lats.quantile(0.9), 8)
                        grid_lons = np.linspace(lons.quantile(0.1), lons.quantile(0.9), 8)
                        glat, glon = np.meshgrid(grid_lats, grid_lons)
                        df_stations_all = pd.DataFrame({
                            'name': [f'Call-Density Station {i+1}' for i in range(len(glat.ravel()))],
                            'lat': glat.ravel(),
                            'lon': glon.ravel(),
                            'type': (['Police', 'Fire', 'School'] * 30)[:len(glat.ravel())],
                            'source': ['CALL_DENSITY'] * len(glat.ravel()),
                        })
                    except Exception:
                        df_stations_all = pd.DataFrame()
            else:
                df_stations_all = df_inside

            if not df_stations_all.empty:
                try:
                    final_station_gdf = gpd.GeoDataFrame(
                        df_stations_all,
                        geometry=gpd.points_from_xy(df_stations_all.lon, df_stations_all.lat),
                        crs='EPSG:4326',
                    ).to_crs(epsg=epsg_code)
                    final_mask = final_station_gdf.within(city_m)
                    if final_mask.any():
                        df_stations_all = df_stations_all[final_mask].reset_index(drop=True)
                except Exception:
                    pass

        if df_stations_all.empty:
            st.error(
                '⚠️ No station candidates could be generated. Please upload a CAD file '
                'with valid coordinates, or switch to Simulation mode.'
            )
            st.stop()

    custom_stations = session_state.get('custom_stations', pd.DataFrame())
    if not custom_stations.empty:
        custom_renamed = custom_stations.copy()
        custom_renamed['name'] = '[' + custom_renamed['type'].astype(str) + '] ' + custom_renamed['name'].astype(str)
        keep_cols = [c for c in custom_renamed.columns if c in list(df_stations_all.columns) + ['name', 'lat', 'lon', 'type', 'custom']]
        custom_renamed = custom_renamed[keep_cols]
        df_stations_all = pd.concat([df_stations_all, custom_renamed], ignore_index=True)

    area_sq_mi = city_m.area / 2589988.11 if city_m and not city_m.is_empty else 100.0
    station_count = len(df_stations_all)

    return {
        'minx': minx,
        'miny': miny,
        'maxx': maxx,
        'maxy': maxy,
        'center_lon': center_lon,
        'center_lat': center_lat,
        'dynamic_zoom': dynamic_zoom,
        'epsg_code': epsg_code,
        'city_m': city_m,
        'city_boundary_geom': city_boundary_geom,
        'boundary_overlay_status': boundary_overlay_status,
        'df_stations_all': df_stations_all,
        'area_sq_mi': area_sq_mi,
        'station_count': station_count,
    }


def manage_custom_stations(
    st,
    session_state,
    df_stations_all,
    area_sq_mi,
    r_resp_est,
    r_guard_est,
    resp_radius_mi,
    guard_radius_mi,
    df_curve,
    get_address_from_latlon,
    search_address_candidates,
    search_public_facility_candidates=None,
):
    n = len(df_stations_all)
    resp_state_key = '_fleet_k_resp'
    guard_state_key = '_fleet_k_guard'

    def _current_fleet_count(state_key, legacy_key, default=0):
        return int(session_state.get(state_key, session_state.get(legacy_key, default)) or 0)

    def _set_fleet_counts(resp_value=None, guard_value=None):
        if resp_value is not None:
            session_state[resp_state_key] = int(resp_value)
        if guard_value is not None:
            session_state[guard_state_key] = int(guard_value)

    def _queue_fleet_count_sync(resp_value=None, guard_value=None, mode='set'):
        if resp_value is not None:
            _resp_key = '_pending_k_resp'
            if mode == 'max':
                session_state[_resp_key] = max(int(session_state.get(_resp_key, 0) or 0), int(resp_value))
            else:
                session_state[_resp_key] = int(resp_value)
        if guard_value is not None:
            _guard_key = '_pending_k_guard'
            if mode == 'max':
                session_state[_guard_key] = max(int(session_state.get(_guard_key, 0) or 0), int(guard_value))
            else:
                session_state[_guard_key] = int(guard_value)

    # Count selected stations from Suggested Station Placements (Guardian and Responder only)
    suggestion_modes = session_state.get('suggestion_modes', {})
    n_selected_responder = sum(1 for mode in suggestion_modes.values() if mode == 'Responder')
    n_selected_guardian = sum(1 for mode in suggestion_modes.values() if mode == 'Guardian')
    n_selected_total = sum(1 for mode in suggestion_modes.values() if mode != 'Off')

    # Count custom stations by type
    custom_stations = session_state.get('custom_stations', pd.DataFrame())
    n_custom_responder = len(custom_stations[custom_stations.get('type', '') == 'Responder']) if not custom_stations.empty else 0
    n_custom_guardian = len(custom_stations[custom_stations.get('type', '') == 'Guardian']) if not custom_stations.empty else 0

    # Slider max = suggested stations + custom stations for each type (independent)
    # Guardian can use any uploaded station + custom stations
    max_guard_calc = n + n_custom_guardian
    # Responder can use any uploaded station + custom stations
    max_resp_calc = n + n_custom_responder

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

    def _use_public_facility_lookup():
        return bool(search_public_facility_candidates) and str(custom_type).strip() in public_facility_types

    try:
        pin_r_count = len(session_state.get('pinned_resp_names', []))
        pin_g_count = len(session_state.get('pinned_guard_names', []))
        pin_drop_used = session_state.get('pin_drop_used', False)
        auto_sig = (
            f"{session_state.get('active_city','')}|{session_state.get('active_state','')}|"
            f"{round(area_sq_mi,1)}|{n}|{round(r_resp_est,1)}|{round(r_guard_est,1)}|"
            f"{pin_r_count}|{pin_g_count}|{int(pin_drop_used)}"
        )
        if session_state.get('_auto_minimums_sig') != auto_sig:
            if session_state.pop('_brinc_k_override', False):
                pass
            elif pin_drop_used:
                _set_fleet_counts(
                    resp_value=max(_current_fleet_count(resp_state_key, 'k_resp', pin_r_count), pin_r_count),
                    guard_value=max(_current_fleet_count(guard_state_key, 'k_guard', pin_g_count), pin_g_count),
                )
            else:
                resp_default = 2
                try:
                    resp_curve = df_curve[['Drones', 'Responder (Calls)']].dropna()
                    hit = resp_curve[resp_curve['Responder (Calls)'] >= 85.0]
                    if not hit.empty:
                        resp_default = int(hit.iloc[0]['Drones'])
                except Exception:
                    pass
                resp_default = max(2, min(int(resp_default), max(1, max_resp_calc)))
                guard_default = max(1, min(1, max(1, max_guard_calc)))
                _set_fleet_counts(
                    resp_value=max(resp_default, pin_r_count),
                    guard_value=max(guard_default, pin_g_count),
                )
            session_state['_auto_minimums_sig'] = auto_sig
    except Exception:
        pass

    current_resp_from_modes = n_custom_responder + n_selected_responder
    current_guard_from_modes = n_custom_guardian + n_selected_guardian
    val_r = _current_fleet_count(resp_state_key, 'k_resp', current_resp_from_modes if current_resp_from_modes > 0 else 2)
    val_g = _current_fleet_count(guard_state_key, 'k_guard', current_guard_from_modes if current_guard_from_modes > 0 else 1)

    if '_pending_k_resp' in session_state:
        val_r = int(session_state.pop('_pending_k_resp') or 0)
    if '_pending_k_guard' in session_state:
        val_g = int(session_state.pop('_pending_k_guard') or 0)

    val_r = min(max(0, int(val_r)), max_resp_calc)
    val_g = min(max(0, int(val_g)), max_guard_calc)

    k_responder = st.sidebar.slider('🚁 Responder Count', 0, max(1, max_resp_calc), value=val_r, help='Short-range tactical drones (2-3mi radius).')
    k_guardian = st.sidebar.slider('🦅 Guardian Count', 0, max(1, max_guard_calc), value=val_g, help='Long-range overwatch drones (5-8mi radius).')
    _set_fleet_counts(resp_value=k_responder or 0, guard_value=k_guardian or 0)

    station_names = df_stations_all['name'].tolist() if not df_stations_all.empty else []

    def make_unique_station_label(raw_label, station_type, lat, lon):
        label = (raw_label or '').strip() or f'{lat:.5f}, {lon:.5f}'
        existing_prefixed = set(df_stations_all['name'].astype(str).tolist())
        custom_existing = session_state.get('custom_stations', pd.DataFrame())
        if not custom_existing.empty and {'name', 'type'}.issubset(custom_existing.columns):
            existing_prefixed.update(
                f"[{row['type']}] {row['name']}"
                for _, row in custom_existing[['name', 'type']].dropna().iterrows()
            )
        prefixed = f'[{station_type}] {label}'
        if prefixed not in existing_prefixed:
            return label
        coord_suffix = f' ({lat:.5f}, {lon:.5f})'
        label_with_coords = f'{label}{coord_suffix}'
        prefixed_with_coords = f'[{station_type}] {label_with_coords}'
        if prefixed_with_coords not in existing_prefixed:
            return label_with_coords
        idx = 2
        while f'[{station_type}] {label_with_coords} #{idx}' in existing_prefixed:
            idx += 1
        return f'{label_with_coords} #{idx}'

    def next_custom_station_name():
        custom_stations = session_state.get('custom_stations', pd.DataFrame())
        used_numbers = set()
        if not custom_stations.empty and 'name' in custom_stations.columns:
            for name in custom_stations['name'].astype(str):
                match = re.fullmatch(r'Custom Station (\d+)', name.strip())
                if match:
                    used_numbers.add(int(match.group(1)))
        idx = 1
        while idx in used_numbers:
            idx += 1
        return f'Custom Station {idx}'

    def build_lock_lists(prefixed_label, lock_role):
        guard = [x for x in session_state.get('pinned_guard_names', []) if x != prefixed_label]
        resp = [x for x in session_state.get('pinned_resp_names', []) if x != prefixed_label]
        if lock_role == 'Guardian':
            guard.append(prefixed_label)
        else:
            resp.append(prefixed_label)
        return guard, resp

    def increment_fleet_count(lock_role):
        if lock_role == 'Guardian':
            _queue_fleet_count_sync(guard_value=_current_fleet_count(guard_state_key, 'k_guard') + 1)
        else:
            _queue_fleet_count_sync(resp_value=_current_fleet_count(resp_state_key, 'k_resp') + 1)

    def set_station_locks(new_guard_names, new_resp_names, ensure_capacity=True):
        valid_lock_names = set(station_names)
        custom_existing = session_state.get('custom_stations', pd.DataFrame())
        if not custom_existing.empty and {'name', 'type'}.issubset(custom_existing.columns):
            valid_lock_names.update(
                f"[{row['type']}] {row['name']}"
                for _, row in custom_existing[['name', 'type']].dropna().iterrows()
            )
        guard = [s for s in list(dict.fromkeys(new_guard_names)) if s in valid_lock_names]
        resp = [s for s in list(dict.fromkeys(new_resp_names)) if s in valid_lock_names]
        session_state['pinned_guard_names'] = list(guard)
        session_state['pinned_resp_names'] = list(resp)
        session_state['lock_guard_ms'] = list(guard)
        session_state['lock_resp_ms'] = list(resp)
        if ensure_capacity:
            _queue_fleet_count_sync(
                resp_value=max(_current_fleet_count(resp_state_key, 'k_resp'), len(resp)),
                guard_value=max(_current_fleet_count(guard_state_key, 'k_guard'), len(guard)),
                mode='max',
            )
        session_state.pop('_auto_minimums_sig', None)
        for cache_key in ['_opt_cache_key', '_opt_best_combo', '_opt_chrono_r', '_opt_chrono_g']:
            session_state.pop(cache_key, None)

    def remove_custom_station(station_name, station_type=None):
        custom_stations = session_state.get('custom_stations', pd.DataFrame())
        match_type = station_type
        if match_type is None and not custom_stations.empty and {'name', 'type'}.issubset(custom_stations.columns):
            match = custom_stations[custom_stations['name'].astype(str) == str(station_name)]
            if not match.empty:
                match_type = str(match.iloc[0]['type'])
        names_to_remove = {str(station_name)}
        if match_type:
            names_to_remove.add(f'[{match_type}] {station_name}')
        if not custom_stations.empty and 'name' in custom_stations.columns:
            mask = custom_stations['name'].astype(str) != str(station_name)
            if match_type and 'type' in custom_stations.columns:
                mask |= custom_stations['type'].astype(str) != str(match_type)
            session_state['custom_stations'] = custom_stations.loc[mask].reset_index(drop=True)
        else:
            session_state['custom_stations'] = pd.DataFrame()
        set_station_locks(
            [x for x in session_state.get('pinned_guard_names', []) if x not in names_to_remove],
            [x for x in session_state.get('pinned_resp_names', []) if x not in names_to_remove],
            ensure_capacity=False,
        )
        remaining_custom = session_state.get('custom_stations', pd.DataFrame())
        if remaining_custom.empty and not session_state.get('pinned_guard_names') and not session_state.get('pinned_resp_names'):
            session_state['pin_drop_used'] = False

    saved_g = [s for s in session_state.get('pinned_guard_names', []) if s in station_names]
    saved_r = [s for s in session_state.get('pinned_resp_names', []) if s in station_names]
    set_station_locks(saved_g, saved_r, ensure_capacity=False)

    pinned_guard_names = list(session_state.get('pinned_guard_names', []))
    pinned_resp_names = list(session_state.get('pinned_resp_names', []))

    pin_mode = bool(session_state.get('pin_drop_mode', False))
    if pin_mode:
        st.sidebar.markdown(
            "<div style='background:rgba(0,210,255,0.08);border:1px solid rgba(0,210,255,0.35);border-radius:6px;padding:8px 10px;margin-bottom:8px;font-size:0.72rem;color:#e0e0f0;'><b>Drop Pin Mode Active</b><br>Single-click the map to capture a station location.</div>",
            unsafe_allow_html=True,
        )
        if st.sidebar.button('Cancel Drop Pin', width="stretch", key='cancel_drop_pin_mode_btn'):
            session_state['pin_drop_mode'] = False
            session_state['pending_pin'] = None
            st.rerun()
    if not pin_mode and session_state.get('pending_pin') is not None:
        session_state['pending_pin'] = None

    pending_pin = session_state.get('pending_pin')

    st.sidebar.markdown(
        """
        <style>
        @keyframes pinDropPulse {
            0% { box-shadow: 0 0 0 0 rgba(0, 210, 255, 0.55); transform: scale(1); }
            70% { box-shadow: 0 0 0 10px rgba(0, 210, 255, 0); transform: scale(1.02); }
            100% { box-shadow: 0 0 0 0 rgba(0, 210, 255, 0); transform: scale(1); }
        }
        .pin-drop-cta {
            background: rgba(0, 210, 255, 0.10);
            border: 1px solid rgba(0, 210, 255, 0.45);
            border-radius: 8px;
            padding: 10px 12px;
            margin: 0 0 10px 0;
            color: #e0e0f0;
            animation: pinDropPulse 1.2s ease-in-out infinite;
        }
        .pin-drop-hint {
            font-size: 0.72rem;
            line-height: 1.35;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    custom_display = session_state.get('custom_stations', pd.DataFrame())
    add_expanded = bool(pin_mode or pending_pin is not None or not custom_display.empty)
    add_expander = st.sidebar.expander('Add Custom Station', expanded=add_expanded)
    with add_expander:
        session_state.setdefault('cs_addr_buf', '')
        session_state.setdefault('cs_label_buf', '')
        session_state.setdefault('cs_type_buf', 'Police')
        session_state.setdefault('cs_role_buf', 'Lock as Guardian')
        session_state.setdefault('pp_label_buf', '')
        session_state.setdefault('pp_type_buf', 'Police')
        session_state.setdefault('pp_role_buf', 'Lock as Guardian')

        if st.button('Pin Drop', width="stretch", key='drop_pin_btn', help='Click on the map to add a custom station by location instead of by address.'):
            session_state['pin_drop_mode'] = True
            session_state['show_lock_stations'] = False
            st.rerun()

        if pin_mode and pending_pin is not None:
            st.markdown(
                (
                    "<div class='pin-drop-cta'><div class='pin-drop-hint'>"
                    f"<b>Pin selected.</b> Review the station details below, then click <b>Add Station</b> to place it at {pending_pin['lat']:.5f}, {pending_pin['lon']:.5f}."
                    '</div></div>'
                ),
                unsafe_allow_html=True,
            )
        elif pin_mode:
            st.info('Pin Drop is active. Single-click the map to capture a station location, then return here to add the station.')

        if pin_mode and pending_pin is not None:
            pp_label = st.text_input('Dropped Pin Name', value=session_state['pp_label_buf'], placeholder=next_custom_station_name(), key='pp_label_input', help='Optional station label for the dropped pin. Leave blank to use an auto-generated name.')
            pin_type_opts = ['Police', 'Fire', 'School', 'Government', 'Hospital', 'Library', 'Other']
            pp_type = st.selectbox('Dropped Pin Type', pin_type_opts, index=pin_type_opts.index(session_state['pp_type_buf']) if session_state['pp_type_buf'] in pin_type_opts else 0, key='pp_type_select', help='Category used to label the station and keep it grouped correctly in the model.')
            pp_role = st.radio('Dropped Pin Fleet', ['Lock as Guardian', 'Lock as Responder'], index=0 if 'Guardian' in session_state.get('pp_role_buf', 'Lock as Guardian') else 1, horizontal=True, key='pp_role_radio', help='Choose which fleet this custom station is locked into after it is added.')
            session_state['pp_label_buf'] = pp_label
            session_state['pp_type_buf'] = pp_type
            session_state['pp_role_buf'] = pp_role
            pin_cols = st.columns(2)
            if pin_cols[0].button('Add Station', width="stretch", key='pp_confirm_btn', type='primary', help='Add the dropped pin as a custom station and lock it to the selected fleet.'):
                default_name = next_custom_station_name()
                base_label = (pp_label or '').strip() or default_name
                label = make_unique_station_label(base_label, pp_type, pending_pin['lat'], pending_pin['lon'])
                prefixed_label = f'[{pp_type}] {label}'
                pp_lock_role = 'Guardian' if 'Guardian' in pp_role else 'Responder'
                nearest_addr = get_address_from_latlon(pending_pin['lat'], pending_pin['lon'])
                new_pin_row = pd.DataFrame([{'name': label, 'lat': pending_pin['lat'], 'lon': pending_pin['lon'], 'type': pp_type, 'lock_role': pp_lock_role, 'address': nearest_addr, 'input_address': nearest_addr, 'geocode_source': 'reverse_geocode', 'custom': True}])
                custom_stations = session_state.get('custom_stations', pd.DataFrame())
                session_state['custom_stations'] = pd.concat([custom_stations, new_pin_row], ignore_index=True) if not custom_stations.empty else new_pin_row
                increment_fleet_count(pp_lock_role)
                new_g, new_r = build_lock_lists(prefixed_label, pp_lock_role)
                set_station_locks(new_g, new_r, ensure_capacity=True)
                session_state['pin_drop_used'] = True
                session_state['pending_pin'] = None
                session_state['pp_label_buf'] = ''
                session_state['pin_drop_mode'] = False
                session_state['show_lock_stations'] = False
                session_state.pop('_pin_sel_hash', None)
                st.toast(f'{label} pinned as {pp_lock_role}.')
                st.rerun()
            if pin_cols[1].button('Cancel Pin', width="stretch", key='pp_cancel_btn', help='Discard the dropped pin and exit map-add mode.'):
                session_state['pending_pin'] = None
                session_state['pin_drop_mode'] = False
                session_state.pop('_pin_sel_hash', None)
                st.rerun()
            st.markdown('---')

        custom_addr = st.text_input('Address', value=session_state['cs_addr_buf'], placeholder='123 Main St, Mobile, AL', key='custom_station_addr', help='Street address to geocode into a custom station. Include city and state for the best match.')
        custom_label = st.text_input('Station Name', value=session_state['cs_label_buf'], placeholder='Fire Station 7', key='custom_station_label', help='Optional display name. Leave blank to use the matched address.')
        type_opts = ['Police', 'Fire', 'School', 'Government', 'Hospital', 'Library', 'Other']
        type_idx = type_opts.index(session_state['cs_type_buf']) if session_state['cs_type_buf'] in type_opts else 0
        custom_type = st.selectbox('Station Type', type_opts, index=type_idx, key='custom_station_type', help='Category used to label the station and keep it grouped correctly in the model.')

        addr_query = custom_addr.strip()
        preferred_city = session_state.get('active_city', '')
        preferred_state = session_state.get('active_state', '')
        locality_hint = ", ".join([v for v in [preferred_city, preferred_state] if v])
        if len(addr_query) >= 4:
            if _use_public_facility_lookup():
                addr_matches = search_public_facility_candidates(
                    addr_query,
                    custom_type,
                    limit=6,
                    preferred_city=preferred_city,
                    preferred_state=preferred_state,
                )
            else:
                addr_matches = search_address_candidates(
                    addr_query,
                    limit=6,
                    preferred_city=preferred_city,
                    preferred_state=preferred_state,
                )
        else:
            addr_matches = []

        def _match_in_preferred_state(match):
            if not preferred_state:
                return True
            text = str(match.get('matched_address', '') or '').upper()
            _abbr_to_full = {v: k for k, v in US_STATES_ABBR.items()}
            _full_state = _abbr_to_full.get(preferred_state.upper(), '').upper()
            return (
                f", {preferred_state}" in text
                or text.endswith(f" {preferred_state}")
                or (_full_state and _full_state in text)
            )

        def _match_in_preferred_city(match):
            if not preferred_city:
                return True
            return preferred_city.lower() in str(match.get('matched_address', '') or '').lower()

        addr_option_rows = []
        for idx, match in enumerate(addr_matches, start=1):
            badges = []
            if _match_in_preferred_city(match):
                badges.append('city')
            if _match_in_preferred_state(match):
                badges.append('state')
            if idx == 1:
                badges.append('best')
            badge_text = f" | {', '.join(badges)}" if badges else ''
            addr_option_rows.append({
                'label': f"{idx}. {match['matched_address']} [{match['source']}{badge_text}]",
                'match': match,
            })

        if locality_hint:
            if _use_public_facility_lookup():
                st.caption(f'Public facility suggestions are biased to {locality_hint}.')
            else:
                st.caption(f'Suggestions are biased to {locality_hint}.')

        _geo_trace = session_state.get('_last_geocode_trace') or {}
        _geo_providers = _geo_trace.get('providers') or []
        if addr_query:
            _provider_summary = []
            for _provider_name in ['Google', 'Mapbox', 'Census', 'OSM']:
                _rows = [r for r in _geo_providers if r.get('provider') == _provider_name]
                if not _rows:
                    continue
                _used = any(bool(r.get('used')) for r in _rows)
                _total = sum(int(r.get('match_count') or 0) for r in _rows if r.get('used'))
                _status = next((str(r.get('status')) for r in _rows if not r.get('used')), 'ok')
                if _used:
                    _provider_summary.append(f"{_provider_name}: queried, {_total} match(es)")
                else:
                    _provider_summary.append(f"{_provider_name}: {_status}")
            if _provider_summary:
                st.caption("Providers: " + " | ".join(_provider_summary))
            with st.expander('Geocoder Diagnostics', expanded=False):
                _queries = _geo_trace.get('queries') or []
                if _queries:
                    st.write("Queries tried:")
                    for _q in _queries:
                        st.code(_q)
                if _geo_providers:
                    st.write("Provider results:")
                    for _row in _geo_providers:
                        if _row.get('used'):
                            st.write(f"{_row.get('provider')}: {_row.get('status')} | {_row.get('match_count')} match(es) | {_row.get('query')}")
                        else:
                            st.write(f"{_row.get('provider')}: {_row.get('status')}")

        _geo_trace = session_state.get('_last_geocode_trace') or {}
        _geo_providers = _geo_trace.get('providers') or []
        if addr_query:
            _provider_summary = []
            for _provider_name in ['Google', 'Mapbox', 'Census', 'OSM']:
                _rows = [r for r in _geo_providers if r.get('provider') == _provider_name]
                if not _rows:
                    continue
                _used = any(bool(r.get('used')) for r in _rows)
                _total = sum(int(r.get('match_count') or 0) for r in _rows if r.get('used'))
                _status = next((str(r.get('status')) for r in _rows if not r.get('used')), 'ok')
                if _used:
                    _provider_summary.append(f"{_provider_name}: queried, {_total} match(es)")
                else:
                    _provider_summary.append(f"{_provider_name}: {_status}")
            if _provider_summary:
                st.caption("Providers: " + " | ".join(_provider_summary))
            with st.expander('Geocoder Diagnostics', expanded=False):
                _queries = _geo_trace.get('queries') or []
                if _queries:
                    st.write("Queries tried:")
                    for _q in _queries:
                        st.code(_q)
                if _geo_providers:
                    st.write("Provider results:")
                    for _row in _geo_providers:
                        if _row.get('used'):
                            st.write(f"{_row.get('provider')}: {_row.get('status')} | {_row.get('match_count')} match(es) | {_row.get('query')}")
                        else:
                            st.write(f"{_row.get('provider')}: {_row.get('status')}")

        if addr_option_rows:
            addr_pick = st.selectbox(
                'Suggested Match',
                options=[row['label'] for row in addr_option_rows],
                index=0,
                key='custom_station_match',
                help='Suggestions refresh as you type and are ranked toward the active city and state.',
            )
            selected_match = next(row['match'] for row in addr_option_rows if row['label'] == addr_pick)
            st.caption(f"Using: {selected_match['matched_address']} | {selected_match['lat']:.5f}, {selected_match['lon']:.5f}")
            if preferred_state and not _match_in_preferred_state(selected_match):
                st.warning(f"This suggestion is outside {preferred_state}. Confirm the address before adding it.")
            elif preferred_city and not _match_in_preferred_city(selected_match):
                st.info(f"No exact {preferred_city} city match found. Showing the closest in-state options first.")
        elif len(addr_query) >= 4:
            selected_match = None
            if locality_hint:
                st.caption(f'No suggestions found yet in {locality_hint}. You can still try the add button for a fallback lookup.')
            else:
                st.caption('No suggestions found yet. You can still try the add button for a fallback lookup.')
        else:
            selected_match = None
        role_opts = ['Lock as Guardian', 'Lock as Responder']
        role_idx = role_opts.index(session_state['cs_role_buf']) if session_state['cs_role_buf'] in role_opts else 0
        custom_role = st.radio('Assign To Fleet', role_opts, index=role_idx, horizontal=True, key='custom_station_role', help='Choose which fleet this custom station will be locked into after it is added.')
        session_state['cs_addr_buf'] = custom_addr
        session_state['cs_label_buf'] = custom_label
        session_state['cs_type_buf'] = custom_type
        session_state['cs_role_buf'] = custom_role

        if st.button('Geocode And Add Station', width="stretch", key='geocode_btn', help='Geocode the address, add the station, and lock it to the selected fleet.', type='primary'):
            addr_to_geocode = custom_addr.strip()
            if addr_to_geocode:
                try:
                    match = selected_match
                    if not match:
                        if _use_public_facility_lookup():
                            fallback_matches = search_public_facility_candidates(
                                addr_to_geocode,
                                custom_type,
                                limit=1,
                                preferred_city=preferred_city,
                                preferred_state=preferred_state,
                            )
                            if not fallback_matches and _looks_like_street_address(addr_to_geocode):
                                fallback_matches = search_address_candidates(
                                    addr_to_geocode,
                                    limit=1,
                                    preferred_city=preferred_city,
                                    preferred_state=preferred_state,
                                )
                        else:
                            fallback_matches = search_address_candidates(
                                addr_to_geocode,
                                limit=1,
                                preferred_city=preferred_city,
                                preferred_state=preferred_state,
                            )
                        match = fallback_matches[0] if fallback_matches else None
                    if match:
                        geo_lat = float(match['lat'])
                        geo_lon = float(match['lon'])
                        matched_addr = match.get('matched_address', addr_to_geocode)
                        label = make_unique_station_label(custom_label.strip() or matched_addr, custom_type, geo_lat, geo_lon)
                        prefixed_label = f'[{custom_type}] {label}'
                        new_row = pd.DataFrame([{'name': label, 'lat': geo_lat, 'lon': geo_lon, 'type': custom_type, 'lock_role': 'Guardian' if custom_role == 'Lock as Guardian' else 'Responder', 'address': matched_addr, 'input_address': addr_to_geocode, 'geocode_source': match.get('source', 'lookup'), 'custom': True}])
                        custom_stations = session_state.get('custom_stations', pd.DataFrame())
                        session_state['custom_stations'] = pd.concat([custom_stations, new_row], ignore_index=True) if not custom_stations.empty else new_row
                        custom_lock_role = 'Guardian' if custom_role == 'Lock as Guardian' else 'Responder'
                        increment_fleet_count(custom_lock_role)
                        new_g, new_r = build_lock_lists(prefixed_label, custom_lock_role)
                        set_station_locks(new_g, new_r, ensure_capacity=True)
                        st.success(f'Added and locked: **{label}** ({geo_lat:.4f}, {geo_lon:.4f})\nPinned as {custom_lock_role}.')
                        st.caption(f"Matched address: {matched_addr} [{match.get('source', 'lookup')}]")
                        session_state['cs_addr_buf'] = ''
                        session_state['cs_label_buf'] = ''
                        for cache_key in ['_opt_cache_key', '_opt_best_combo', '_opt_chrono_r', '_opt_chrono_g']:
                            session_state.pop(cache_key, None)
                        st.rerun()
                    else:
                        if _use_public_facility_lookup():
                            st.warning('Public facility not found. Try the station name, a known facility address, or switch the type if this is not a civic building.')
                        else:
                            st.warning('Address not found. Try selecting a suggested match or include city and state.')
                except Exception as ge_exc:
                    st.error(f'Geocoding failed: {ge_exc}')
            else:
                st.warning('Enter an address first.')

        custom_added = custom_display['name'].tolist() if not custom_display.empty else []
        if custom_added:
            st.markdown('---')
            st.caption(f'Custom Stations This Session ({len(custom_added)})')
            custom_disp = session_state.get('custom_stations', pd.DataFrame())
            guard_set = set(session_state.get('pinned_guard_names', []))
            resp_set = set(session_state.get('pinned_resp_names', []))
            for idx, custom_name in enumerate(custom_added[:12]):
                custom_row = custom_disp[custom_disp['name'] == custom_name].iloc[0] if not custom_disp.empty and (custom_disp['name'] == custom_name).any() else None
                prefixed = f"[{custom_row['type']}] {custom_name}" if custom_row is not None else custom_name
                stored_lock_role = str(custom_row.get('lock_role', '')).strip() if custom_row is not None else ''
                is_g = stored_lock_role == 'Guardian' or prefixed in guard_set or custom_name in guard_set
                is_r = stored_lock_role == 'Responder' or prefixed in resp_set or custom_name in resp_set
                badge = 'G' if is_g else 'R' if is_r else '•'
                color = '#FFD700' if is_g else '#00D2FF' if is_r else '#9aa0b4'
                row_cols = st.columns([6, 1])
                row_cols[0].markdown(f"<div style='font-size:0.68rem; color:{color}; padding:4px 0;'>{badge} {prefixed}</div>", unsafe_allow_html=True)
                if row_cols[1].button('X', key=f'remove_custom_station_{idx}_{custom_name}', help='Remove this custom station.', width="stretch"):
                    remove_custom_station(custom_name, None if custom_row is None else str(custom_row['type']))
                    st.rerun()
            if st.button('Remove all custom stations', key='remove_custom', width="stretch", help='Clear every custom station added in this session and remove their fleet locks.'):
                custom_to_rm = session_state.get('custom_stations', pd.DataFrame())
                rm_names = set()
                if not custom_to_rm.empty:
                    for _, row in custom_to_rm.iterrows():
                        rm_names.add(str(row['name']))
                        rm_names.add(f"[{row['type']}] {row['name']}")
                session_state['custom_stations'] = pd.DataFrame()
                session_state['pinned_guard_names'] = [x for x in session_state.get('pinned_guard_names', []) if x not in rm_names]
                session_state['pinned_resp_names'] = [x for x in session_state.get('pinned_resp_names', []) if x not in rm_names]
                if not session_state.get('pinned_guard_names') and not session_state.get('pinned_resp_names'):
                    session_state['pin_drop_used'] = False
                session_state.pop('_auto_minimums_sig', None)
                session_state.pop('_opt_cache_key', None)
                st.rerun()

    lock_expanded = bool(session_state.get('show_lock_stations', False) or pinned_guard_names or pinned_resp_names)
    lock_sync_sig = (tuple(pinned_guard_names), tuple(pinned_resp_names), len(station_names))
    if session_state.get('_lock_widget_sync_sig') != lock_sync_sig:
        session_state['lock_guard_ms_widget_b'] = list(pinned_guard_names)
        session_state['lock_resp_ms_widget_b'] = list(pinned_resp_names)
        session_state['_lock_widget_sync_sig'] = lock_sync_sig
    lock_expander = st.sidebar.expander('Lock Stations', expanded=lock_expanded)
    with lock_expander:
        st.caption('Assign specific stations to Guardian or Responder and force them into the deployed fleet.')
        new_g = st.multiselect('Lock as Guardian', options=station_names, key='lock_guard_ms_widget_b', help='These stations will always be assigned a Guardian drone and deployed into Unit Economics.')
        new_r = st.multiselect('Lock as Responder', options=station_names, key='lock_resp_ms_widget_b', help='These stations will always be assigned a Responder drone and deployed into Unit Economics.')
        if new_g != pinned_guard_names or new_r != pinned_resp_names:
            set_station_locks(new_g, new_r, ensure_capacity=True)
            session_state['show_lock_stations'] = True
            st.rerun()

    pinned_guard_names = list(session_state.get('pinned_guard_names', []))
    pinned_resp_names = list(session_state.get('pinned_resp_names', []))
    session_state['show_lock_stations'] = False

    # Locks are hard constraints: the effective fleet count cannot fall below
    # the number of pinned stations for each role.
    effective_k_guardian = max(int(k_guardian or 0), len(pinned_guard_names))
    effective_k_responder = max(int(k_responder or 0), len(pinned_resp_names))
    if effective_k_guardian != k_guardian or effective_k_responder != k_responder:
        _queue_fleet_count_sync(
            resp_value=effective_k_responder,
            guard_value=effective_k_guardian,
        )
        st.rerun()

    return {
        'k_responder': effective_k_responder,
        'k_guardian': effective_k_guardian,
        'pinned_guard_names': pinned_guard_names,
        'pinned_resp_names': pinned_resp_names,
        'station_names': station_names,
    }


def prepare_runtime_context(
    st,
    session_state,
    optimization_module,
    faa_rf_module,
    html_reports_module,
    config,
    df_calls,
    df_calls_full,
    df_stations_all,
    city_m,
    epsg_code,
    resp_radius_mi,
    guard_radius_mi,
    center_lat,
    center_lon,
    bounds_hash,
    minx,
    miny,
    maxx,
    maxy,
    full_daily_calls,
    full_total_calls,
    text_muted,
    get_spatial_message,
    get_faa_message,
    get_airfield_message,
):
    prog2 = st.sidebar.empty()
    prog2.caption(get_spatial_message())
    calls_in_city, display_calls, resp_matrix, guard_matrix, dist_matrix_r, dist_matrix_g, station_metadata, total_calls = optimization_module.precompute_spatial_data(
        df_calls, df_calls_full, df_stations_all, city_m, epsg_code, resp_radius_mi, guard_radius_mi, center_lat, center_lon, bounds_hash
    )
    if total_calls == 0 and len(df_calls) > 0:
        st.warning('No uploaded calls fell inside the selected jurisdiction boundary. Coverage rings can still render, but call coverage will be 0%. Check city/state selection or clean outlier coordinates in the CAD file.')
    df_curve = optimization_module.compute_all_elbow_curves(
        total_calls,
        resp_matrix,
        guard_matrix,
        [s['clipped_2m'] for s in station_metadata],
        [s['clipped_guard'] for s in station_metadata],
        city_m.area if city_m else 1.0,
        bounds_hash,
        max_stations=100,
    )
    prog2.empty()

    with st.spinner(get_faa_message()):
        faa_geojson = faa_rf_module.load_faa_parquet(minx, miny, maxx, maxy)
        faa_feature_count = len(faa_geojson.get('features', [])) if isinstance(faa_geojson, dict) and faa_geojson.get('features') else 0
        if faa_feature_count == 0:
            st.sidebar.warning('FAA data not loading (0 zones). Check Display Options.')
    airfield_cache = session_state.setdefault('_airfields_cache', {})
    airfield_cache_key = f"{str(session_state.get('active_city', '')).strip().lower()}|{str(session_state.get('active_state', '')).strip().lower()}|{bounds_hash}"
    if airfield_cache_key in airfield_cache:
        airfields = airfield_cache[airfield_cache_key]
    else:
        with st.spinner(get_airfield_message()):
            airfields = faa_rf_module.fetch_airfields(minx, miny, maxx, maxy)
        airfield_cache[airfield_cache_key] = airfields

    st.sidebar.markdown('<div class="sidebar-section-header">③ Budget & Downloads</div>', unsafe_allow_html=True)
    budget_expander = st.sidebar.expander('Budget Inputs', expanded=False)
    with budget_expander:
        st.markdown('---')
        inferred_daily = session_state.get('inferred_daily_calls_override') or full_daily_calls or 1
        inferred_daily = max(1, int(inferred_daily))
        calls_per_day = st.slider('Total Daily Calls (citywide)', 1, max(100, inferred_daily * 3), inferred_daily, help='Total 911 calls per day citywide used to project annual dispatch volume, officer hours saved, and ROI.')
        st.caption(f'Derived from the full uploaded CAD total ({full_total_calls:,} incidents).')
        st.markdown(f"<div style='font-size:0.72rem; color:{text_muted}; margin-top:8px; margin-bottom:2px;'>DFR Dispatch Rate (%)</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:0.65rem; color:#666; margin-bottom:4px;'>What % of in-range calls will the drone be sent to?</div>", unsafe_allow_html=True)
        dfr_dispatch_rate = st.slider('DFR Dispatch Rate', 1, 100, session_state.get('dfr_rate', 25), label_visibility='collapsed', help='Percentage of in-range calls the drone is dispatched to. Higher rates increase coverage and savings projections.') / 100.0
        st.markdown(f"<div style='font-size:0.72rem; color:{text_muted}; margin-top:8px; margin-bottom:2px;'>Calls Resolved Without Officer Dispatch (%)</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:0.65rem; color:#666; margin-bottom:4px;'>Of drone-attended calls, what % close without a patrol car?</div>", unsafe_allow_html=True)
        deflection_rate = st.slider('Resolution Rate', 0, 100, session_state.get('deflect_rate', 30), label_visibility='collapsed', help='Of drone-attended calls, the percentage that close without requiring a patrol car dispatch. Higher values increase officer hours saved.') / 100.0
        session_state['dfr_rate'] = int(dfr_dispatch_rate * 100)
        session_state['deflect_rate'] = int(deflection_rate * 100)

    return {
        'calls_in_city': calls_in_city,
        'display_calls': display_calls,
        'resp_matrix': resp_matrix,
        'guard_matrix': guard_matrix,
        'dist_matrix_r': dist_matrix_r,
        'dist_matrix_g': dist_matrix_g,
        'station_metadata': station_metadata,
        'total_calls': total_calls,
        'df_curve': df_curve,
        'faa_geojson': faa_geojson,
        'airfields': airfields,
        'calls_per_day': calls_per_day,
        'dfr_dispatch_rate': dfr_dispatch_rate,
        'deflection_rate': deflection_rate,
    }



def optimize_fleet_selection(
    st,
    session_state,
    optimization_module,
    station_metadata,
    resp_matrix,
    guard_matrix,
    dist_matrix_r,
    dist_matrix_g,
    total_calls,
    calls_per_day,
    dfr_dispatch_rate,
    config,
    k_responder,
    k_guardian,
    guard_radius_mi,
    allow_redundancy,
    complement_mode,
    shared_mode,
    incremental_build,
    guard_strategy,
    resp_strategy,
    locked_g_pins,
    locked_r_pins,
    n,
    opt_cache_key,
):
    active_resp_names, active_guard_names = [], []
    active_resp_idx, active_guard_idx = [], []
    chrono_r, chrono_g = [], []
    best_combo = None

    if n <= 0:
        st.error(
            '⚠️ No station candidates are available. Upload a stations file with known placement sites, '
            'or switch to a mode that can generate station candidates.'
        )
        return {
            'active_resp_names': active_resp_names,
            'active_guard_names': active_guard_names,
            'active_resp_idx': active_resp_idx,
            'active_guard_idx': active_guard_idx,
            'chrono_r': chrono_r,
            'chrono_g': chrono_g,
            'best_combo': best_combo,
            'guard_claims_by_idx': {},
        }

    k_responder = min(int(k_responder or 0), n)
    k_guardian = min(int(k_guardian or 0), n)

    if k_responder == 0 and k_guardian == 0:
        pass
    else:
        if session_state.get('_opt_cache_key') != opt_cache_key:
            stage_bar = st.empty()
            stage_progress = st.progress(0, text="Preparing optimization…")

            def set_stage(step_pct, message):
                stage_bar.info(message)
                try:
                    stage_progress.progress(int(step_pct), text=message)
                except Exception:
                    stage_progress.progress(int(step_pct))

            def has_meaningful_overlap(geom_a, geom_b, tol=1e-9):
                if geom_a is None or geom_b is None or geom_a.is_empty or geom_b.is_empty:
                    return False
                if not geom_a.intersects(geom_b):
                    return False
                try:
                    return geom_a.intersection(geom_b).area > tol
                except Exception:
                    return not geom_a.touches(geom_b)

            def build_overlap_pairs(geo_list):
                pairs = []
                for i in range(len(geo_list)):
                    for j in range(i + 1, len(geo_list)):
                        if has_meaningful_overlap(geo_list[i], geo_list[j]):
                            pairs.append((i, j))
                return pairs

            def build_cross_overlap_pairs(resp_geos, guard_geos):
                pairs = []
                for r_idx, r_geom in enumerate(resp_geos):
                    for g_idx, g_geom in enumerate(guard_geos):
                        if has_meaningful_overlap(r_geom, g_geom):
                            pairs.append((r_idx, g_idx))
                return pairs

            def build_forbidden_candidates(cross_pairs, selected_guard_idx, forced_resp_idx):
                selected_guard_set = set(selected_guard_idx)
                forced_resp_set = set(forced_resp_idx)
                forbidden = set()
                for r_idx, g_idx in cross_pairs:
                    if g_idx in selected_guard_set and r_idx not in forced_resp_set:
                        forbidden.add(r_idx)
                return forbidden

            def build_guard_serviceable_claims(selected_guard_idx):
                zero_mask = np.zeros(total_calls, dtype=bool)
                zero_claims = {int(idx): zero_mask.copy() for idx in selected_guard_idx}
                if not selected_guard_idx or total_calls <= 0 or calls_per_day <= 0 or dfr_dispatch_rate <= 0:
                    return zero_mask.copy(), zero_claims

                demand_per_call = (calls_per_day * dfr_dispatch_rate) / max(total_calls, 1)
                if demand_per_call <= 0:
                    return zero_mask.copy(), zero_claims

                covered_calls = np.where(guard_matrix[selected_guard_idx].any(axis=0))[0]
                if len(covered_calls) == 0:
                    return zero_mask.copy(), zero_claims

                claimed_mask = np.zeros(total_calls, dtype=bool)
                claims_by_guard = {int(idx): np.zeros(total_calls, dtype=bool) for idx in selected_guard_idx}
                covered_dist = dist_matrix_g[np.ix_(selected_guard_idx, covered_calls)]
                nearest_guard_pos = np.argmin(covered_dist, axis=0)

                min_scene_min = 10.0
                guard_speed = max(float(config["GUARDIAN_SPEED"]), 1.0)

                _stable_avg_distance = getattr(
                    optimization_module,
                    "bounded_station_avg_distance_miles",
                    optimization_module.mean_covered_distance_miles,
                )
                for local_pos, guard_idx in enumerate(selected_guard_idx):
                    assigned_calls = covered_calls[nearest_guard_pos == local_pos]
                    if len(assigned_calls) == 0:
                        continue
                    _fallback_avg = float(station_metadata[guard_idx].get('avg_dist_g', 0) or 0)
                    try:
                        avg_dist = _stable_avg_distance(
                            dist_matrix_g,
                            guard_matrix,
                            guard_idx,
                            fallback_miles=_fallback_avg,
                            max_radius_miles=guard_radius_mi,
                        )
                    except TypeError:
                        avg_dist = min(
                            _stable_avg_distance(
                                dist_matrix_g,
                                guard_matrix,
                                guard_idx,
                                fallback_miles=_fallback_avg,
                            ),
                            guard_radius_mi,
                        )
                    avg_time_min = (avg_dist / guard_speed) * 60.0
                    response_cost = avg_time_min + min_scene_min
                    if response_cost <= 0:
                        continue
                    max_flights_cap = calculate_max_flights_per_day(
                        response_cost,
                        flight_minutes=config["GUARDIAN_FLIGHT_MIN"],
                        downtime_minutes=config["GUARDIAN_CHARGE_MIN"],
                    )
                    serviceable_calls = int(math.floor(max_flights_cap / demand_per_call + 1e-9))
                    if serviceable_calls <= 0:
                        continue
                    if serviceable_calls >= len(assigned_calls):
                        selected_calls = assigned_calls
                    else:
                        assigned_dists = dist_matrix_g[guard_idx, assigned_calls]
                        keep_order = np.argsort(assigned_dists)[:serviceable_calls]
                        selected_calls = assigned_calls[keep_order]
                    claims_by_guard[int(guard_idx)][selected_calls] = True
                    claimed_mask[selected_calls] = True
                return claimed_mask, claims_by_guard

            def greedy_area(geo_list, k, forced, exclude_set, avoid_overlap=False, cross_geo_list=None):
                chosen = list(forced)
                chrono = list(forced)
                current_union = unary_union([geo_list[i] for i in chosen]) if chosen else None
                for _ in range(k - len(forced)):
                    best_idx, best_gain = -1, -1.0
                    for station_idx in range(len(geo_list)):
                        if station_idx in chosen or station_idx in exclude_set:
                            continue
                        geom = geo_list[station_idx]
                        if avoid_overlap:
                            if any(has_meaningful_overlap(geom, geo_list[chosen_idx]) for chosen_idx in chosen):
                                continue
                            if cross_geo_list and any(has_meaningful_overlap(geom, other_geom) for other_geom in cross_geo_list):
                                continue
                        new_area = current_union.union(geom).area if current_union else geom.area
                        gain = new_area - (current_union.area if current_union else 0)
                        if gain > best_gain:
                            best_gain, best_idx = gain, station_idx
                    if best_idx != -1:
                        chosen.append(best_idx)
                        chrono.append(best_idx)
                        geom = geo_list[best_idx]
                        current_union = current_union.union(geom) if current_union else geom
                return chosen, chrono

            guard_geos = [station_metadata[i]['clipped_guard'] for i in range(len(station_metadata))]
            resp_geos = [station_metadata[i]['clipped_2m'] for i in range(len(station_metadata))]
            guard_overlap_pairs = build_overlap_pairs(guard_geos) if complement_mode else []
            resp_overlap_pairs = build_overlap_pairs(resp_geos) if complement_mode else []
            cross_overlap_pairs = build_cross_overlap_pairs(resp_geos, guard_geos) if complement_mode else []
            true_shared_call_mode = (
                shared_mode
                and guard_strategy == 'Maximize Call Coverage'
                and resp_strategy == 'Maximize Call Coverage'
            )

            if true_shared_call_mode:
                set_stage(20, 'Building overlap constraints and shared call coverage model…')
                r_best, g_best, chrono_r, chrono_g = optimization_module.solve_mclp(
                    resp_matrix,
                    guard_matrix,
                    dist_matrix_r,
                    dist_matrix_g,
                    k_responder,
                    k_guardian,
                    True,
                    incremental=incremental_build,
                    forced_r=locked_r_pins,
                    forced_g=locked_g_pins,
                )
                r_best = list(r_best)
                g_best = list(g_best)
            else:
                set_stage(20, 'Building overlap constraints and optimising Guardian fleet…')
                if k_guardian > 0:
                    if guard_strategy == 'Maximize Call Coverage':
                        set_stage(45, 'Solving Guardian fleet placement…')
                        _, g_best, _, chrono_g = optimization_module.solve_mclp(
                            resp_matrix,
                            guard_matrix,
                            dist_matrix_r,
                            dist_matrix_g,
                            0,
                            k_guardian,
                            True,
                            incremental=incremental_build,
                            forced_r=[],
                            forced_g=locked_g_pins,
                            incompatible_gg=guard_overlap_pairs,
                        )
                    else:
                        set_stage(45, 'Selecting Guardian stations from coverage geometry…')
                        g_best, chrono_g = greedy_area(
                            guard_geos,
                            k_guardian,
                            locked_g_pins,
                            set(),
                            avoid_overlap=complement_mode,
                        )
                    g_best = list(g_best)
                else:
                    g_best, chrono_g = [], []

                set_stage(70, 'Optimising Responder fleet…')
                if k_responder > 0:
                    if complement_mode and g_best and total_calls > 0:
                        guard_claimed, guard_claims_by_idx = build_guard_serviceable_claims(g_best)
                        resp_matrix_eff = resp_matrix.copy()
                        resp_matrix_eff[:, guard_claimed] = False
                        dist_matrix_r_eff = dist_matrix_r.copy()
                        forbidden_resp = build_forbidden_candidates(cross_overlap_pairs, g_best, locked_r_pins)
                    else:
                        guard_claims_by_idx = {}
                        resp_matrix_eff = resp_matrix
                        dist_matrix_r_eff = dist_matrix_r
                        forbidden_resp = set()

                    if resp_strategy == 'Maximize Call Coverage':
                        set_stage(85, 'Solving Responder fleet placement…')
                        r_best, _, chrono_r, _ = optimization_module.solve_mclp(
                            resp_matrix_eff,
                            guard_matrix,
                            dist_matrix_r_eff,
                            dist_matrix_g,
                            k_responder,
                            0,
                            allow_redundancy,
                            incremental=incremental_build,
                            forced_r=locked_r_pins,
                            forced_g=[],
                            forbidden_r=forbidden_resp,
                            incompatible_rr=resp_overlap_pairs,
                        )
                        if complement_mode:
                            r_best = [s for s in r_best if s not in set(g_best)]
                    else:
                        set_stage(85, 'Selecting Responder stations from coverage geometry…')
                        excl_resp = set(g_best) if complement_mode else set()
                        cross_guard_geos = [guard_geos[i] for i in g_best] if complement_mode else None
                        r_best, chrono_r = greedy_area(
                            resp_geos,
                            k_responder,
                            locked_r_pins,
                            excl_resp,
                            avoid_overlap=complement_mode,
                            cross_geo_list=cross_guard_geos,
                        )
                else:
                    r_best, chrono_r = [], []

            if not complement_mode:
                guard_claims_by_idx = {}
            set_stage(100, 'Finalizing optimization recommendations…')
            best_combo = (tuple(r_best), tuple(g_best))
            stage_bar.empty()
            stage_progress.empty()
            if true_shared_call_mode:
                st.toast('✅ Shared optimisation complete!', icon='✅')
            elif shared_mode:
                st.toast('✅ Shared mode fell back to independent optimisation for this objective mix.', icon='✅')
            else:
                st.toast('✅ Independent optimisation complete!', icon='✅')
            session_state['_opt_cache_key'] = opt_cache_key
            session_state['_opt_best_combo'] = best_combo
            session_state['_opt_chrono_r'] = chrono_r
            session_state['_opt_chrono_g'] = chrono_g
        else:
            best_combo = session_state.get('_opt_best_combo')
            chrono_r = session_state.get('_opt_chrono_r', [])
            chrono_g = session_state.get('_opt_chrono_g', [])

        if best_combo is not None:
            r_best, g_best = best_combo
            active_resp_names = [station_metadata[i]['name'] for i in r_best]
            active_guard_names = [station_metadata[i]['name'] for i in g_best]
            active_resp_idx = list(r_best)
            active_guard_idx = list(g_best)

    return {
        'active_resp_names': active_resp_names,
        'active_guard_names': active_guard_names,
        'active_resp_idx': active_resp_idx,
        'active_guard_idx': active_guard_idx,
        'chrono_r': chrono_r,
        'chrono_g': chrono_g,
        'best_combo': best_combo,
        'guard_claims_by_idx': guard_claims_by_idx if complement_mode else {},
    }


# ── STATION SUGGESTION ENGINE ────────────────────────────────────────────────

def compute_station_suggestions(
    resp_matrix, guard_matrix, station_metadata, total_calls, city_area,
    max_suggestions=10,
    rank_by='call',
):
    """Rank stations by call coverage and return the top suggestions.

    Each suggestion includes solo call-coverage %, solo land-coverage %, and a
    default role assignment (2 Responder : 1 Guardian repeating pattern).
    """
    if total_calls == 0 or not station_metadata:
        return []

    n_stations = len(station_metadata)
    suggestions = []
    scored = []

    for i in range(n_stations):
        meta = station_metadata[i]
        # Use the raw haversine-based count here instead of the projected mask.
        # The Euclidean matrix can slightly over-claim fringe calls and make
        # central responder sites look like they cover 100% of city calls.
        raw_calls = int(meta.get('raw_calls_r', np.sum(resp_matrix[i])))
        solo_call_pct = (raw_calls / total_calls * 100) if total_calls > 0 else 0
        solo_land_pct = (meta['clipped_2m'].area / city_area * 100) if city_area > 0 else 0
        marginal_calls = raw_calls
        scored.append({
            'station_idx': i,
            'name': meta['name'],
            'address': meta.get('address', ''),
            'lat': meta['lat'],
            'lon': meta['lon'],
            'call_pct': round(solo_call_pct, 1),
            'land_pct': round(solo_land_pct, 1),
            'marginal_calls': marginal_calls,
        })

    primary_metric = 'land_pct' if str(rank_by).strip().lower().startswith('land') else 'call_pct'
    secondary_metric = 'call_pct' if primary_metric == 'land_pct' else 'land_pct'

    # Keep the cards aligned with the active deployment objective while
    # preserving the previous call-volume tie-breaker.
    scored.sort(
        key=lambda s: (
            s.get(primary_metric, 0),
            s.get(secondary_metric, 0),
            s['marginal_calls'],
            -s['station_idx'],
        ),
        reverse=True,
    )

    # Preserve the existing alternating role pattern for the top 10 cards.
    for rank, suggestion in enumerate(scored[:min(max_suggestions, n_stations)]):
        suggestion['rank'] = rank + 1
        suggestion['role'] = 'Guardian' if (rank % 3 == 0) else 'Responder'
        suggestions.append(suggestion)

    return suggestions


def sync_station_suggestion_modes(session_state, suggestions):
    """Keep suggestion mode state aligned with live widget values."""
    if not suggestions:
        return {}

    existing_modes = session_state.get('suggestion_modes', {}) or {}
    synced_modes = {}
    for s in suggestions:
        idx = s['station_idx']
        widget_key = f"suggest_mode_{idx}"
        default_mode = s['role'] if s['rank'] <= 3 else 'Off'
        mode = session_state.get(widget_key, existing_modes.get(idx, default_mode))
        if mode not in ('Guardian', 'Responder', 'Off'):
            mode = 'Off'
        synced_modes[idx] = mode

    session_state['suggestion_modes'] = synced_modes
    session_state['suggestion_toggles'] = {idx: (mode != 'Off') for idx, mode in synced_modes.items()}
    return synced_modes


def render_station_suggestions(st, session_state, suggestions, text_main, text_muted,
                               card_bg, card_border, accent_color, source_label='public data'):
    """Render a compact 2×5 suggestion card grid below the map.

    Returns True if any toggle changed (caller should rerun).
    """
    if not suggestions:
        return False

    mode_options = ['Guardian', 'Responder', 'Off']
    # Initialise mode state on first render.
    if 'suggestion_modes' not in session_state:
        if 'suggestion_toggles' in session_state:
            session_state['suggestion_modes'] = {
                s['station_idx']: (
                    s['role'] if session_state['suggestion_toggles'].get(s['station_idx']) else 'Off'
                )
                for s in suggestions
            }
        else:
            session_state['suggestion_modes'] = {
                s['station_idx']: (s['role'] if s['rank'] <= 3 else 'Off')
                for s in suggestions
            }
    else:
        session_state['suggestion_modes'] = {
            s['station_idx']: session_state['suggestion_modes'].get(
                s['station_idx'],
                s['role'] if s['rank'] <= 3 else 'Off',
            )
            for s in suggestions
        }
    if 'show_suggestion_markers' not in session_state:
        session_state['show_suggestion_markers'] = True
    source_label = session_state.get('station_suggestions_source', source_label)

    modes = session_state['suggestion_modes']
    changed = False

    n_on = sum(1 for v in modes.values() if v != 'Off')
    st.markdown(
        f"<div style='margin-top:12px; margin-bottom:6px; display:flex; align-items:center; "
        f"justify-content:space-between;'>"
        f"<span style='font-size:0.85rem; font-weight:700; color:{text_main};'>"
        f"Suggested Station Placements"
        f"<span style='font-size:0.7rem; font-weight:400; color:{text_muted}; margin-left:8px;'>"
        f"({n_on} shown from {source_label})</span></span></div>",
        unsafe_allow_html=True,
    )
    st.caption('Click a card to compare role assignment. These suggestions are advisory only and do not force the deployment objective or lock the optimizer.')

    # ── Two rows of 5 cards ──────────────────────────────────────────────
    st.markdown(
        """
        <style>
        section.main div[data-testid="stRadio"] div[role="radiogroup"] {
            gap: 0.08rem !important;
            flex-wrap: nowrap !important;
        }
        section.main div[data-testid="stRadio"] label,
        section.main div[data-testid="stRadio"] label p,
        section.main div[data-testid="stRadio"] label span {
            font-size: 0.46rem !important;
            line-height: 0.95 !important;
            white-space: nowrap !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for row_start in range(0, len(suggestions), 5):
        row_items = suggestions[row_start:row_start + 5]
        if not row_items:
            break
        cols = st.columns(len(row_items), gap="small")
        for ci, s in enumerate(row_items):
            idx = s['station_idx']
            mode = modes.get(idx, 'Off')
            mode_color = '#FFD700' if mode == 'Guardian' else '#00D2FF' if mode == 'Responder' else '#9aa0b4'
            mode_abbr = 'G' if mode == 'Guardian' else 'R' if mode == 'Responder' else 'O'
            border_col = mode_color if mode != 'Off' else card_border
            bg = card_bg if mode != 'Off' else 'rgba(30,30,40,0.4)'
            opacity = '1.0' if mode != 'Off' else '0.55'
            widget_key = f"suggest_mode_{idx}"

            # Use address if available, otherwise fall back to name
            display_text = s.get('address', '') or s['name']

            with cols[ci]:
                st.markdown(
                    f"<div style='border:1px solid {border_col}; border-radius:6px; "
                    f"padding:6px 8px; background:{bg}; opacity:{opacity}; "
                    f"min-height:72px; font-size:0.7rem; line-height:1.3;'>"
                    f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
                    f"<span style='font-weight:700; color:{text_main};'>#{s['rank']}</span>"
                    f"<span style='background:{mode_color}; color:#000; font-size:0.55rem; "
                    f"font-weight:800; padding:1px 5px; border-radius:3px;'>{mode_abbr}</span></div>"
                    f"<div style='color:{text_main}; font-weight:600; margin:2px 0; word-wrap:break-word; white-space:normal;'>"
                    f"{display_text}</div>"
                    f"<div style='color:{text_muted}; font-size:0.62rem;'>"
                    f"📞 {s['call_pct']}% calls · 🗺️ {s['land_pct']}% land</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                new_mode = st.radio(
                    'Fleet Mode',
                    options=mode_options,
                    index=mode_options.index(mode) if mode in mode_options else 2,
                    key=widget_key,
                    horizontal=True,
                    label_visibility="collapsed",
                )
                if new_mode != mode:
                    modes[idx] = new_mode
                    changed = True

    # Master toggle to hide map markers
    show_markers = st.checkbox(
        'Show suggested locations on map',
        value=session_state.get('show_suggestion_markers', True),
        key='_suggest_markers_toggle',
    )
    if show_markers != session_state.get('show_suggestion_markers', True):
        session_state['show_suggestion_markers'] = show_markers
        changed = True

    session_state['suggestion_modes'] = modes
    session_state['suggestion_toggles'] = {idx: (mode != 'Off') for idx, mode in modes.items()}
    return changed


def render_station_suggestions_grid(st, session_state, suggestions, text_main, text_muted,
                                    card_bg, card_border, accent_color, source_label='public data'):
    """Render station suggestions with synced widget state and a fixed 5-column grid."""
    if not suggestions:
        return False

    mode_options = ['Guardian', 'Responder', 'Off']
    if 'suggestion_modes' not in session_state:
        if 'suggestion_toggles' in session_state:
            session_state['suggestion_modes'] = {
                s['station_idx']: (
                    s['role'] if session_state['suggestion_toggles'].get(s['station_idx']) else 'Off'
                )
                for s in suggestions
            }
        else:
            session_state['suggestion_modes'] = {
                s['station_idx']: (s['role'] if s['rank'] <= 3 else 'Off')
                for s in suggestions
            }
    else:
        session_state['suggestion_modes'] = {
            s['station_idx']: session_state['suggestion_modes'].get(
                s['station_idx'],
                s['role'] if s['rank'] <= 3 else 'Off',
            )
            for s in suggestions
        }
    if 'show_suggestion_markers' not in session_state:
        session_state['show_suggestion_markers'] = True
    source_label = session_state.get('station_suggestions_source', source_label)

    modes = sync_station_suggestion_modes(session_state, suggestions)
    changed = False

    n_on = sum(1 for v in modes.values() if v != 'Off')
    st.markdown(
        f"<div style='margin-top:12px; margin-bottom:6px; display:flex; align-items:center; "
        f"justify-content:space-between;'>"
        f"<span style='font-size:0.85rem; font-weight:700; color:{text_main};'>"
        f"Suggested Station Placements"
        f"<span style='font-size:0.7rem; font-weight:400; color:{text_muted}; margin-left:8px;'>"
        f"({n_on} shown from {source_label})</span></span></div>",
        unsafe_allow_html=True,
    )
    st.caption('Click a card to compare role assignment. These suggestions are advisory only and do not force the deployment objective or lock the optimizer.')

    st.markdown(
        """
        <style>
        section.main div[data-testid="stRadio"] div[role="radiogroup"] {
            gap: 0.08rem !important;
            flex-wrap: nowrap !important;
        }
        section.main div[data-testid="stRadio"] label,
        section.main div[data-testid="stRadio"] label p,
        section.main div[data-testid="stRadio"] label span {
            font-size: 0.46rem !important;
            line-height: 0.95 !important;
            white-space: nowrap !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for row_start in range(0, len(suggestions), 5):
        row_items = suggestions[row_start:row_start + 5]
        cols = st.columns(5, gap="small")
        for ci in range(5):
            s = row_items[ci] if ci < len(row_items) else None
            with cols[ci]:
                if s is None:
                    st.markdown("<div style='min-height:112px;'></div>", unsafe_allow_html=True)
                    continue

                idx = s['station_idx']
                mode = modes.get(idx, 'Off')
                mode_color = '#FFD700' if mode == 'Guardian' else '#00D2FF' if mode == 'Responder' else '#9aa0b4'
                mode_abbr = 'G' if mode == 'Guardian' else 'R' if mode == 'Responder' else 'O'
                border_col = mode_color if mode != 'Off' else card_border
                bg = card_bg if mode != 'Off' else 'rgba(30,30,40,0.4)'
                opacity = '1.0' if mode != 'Off' else '0.55'
                widget_key = f"suggest_mode_{idx}"
                display_text = s.get('address', '') or s['name']

                st.markdown(
                    f"<div style='border:1px solid {border_col}; border-radius:6px; "
                    f"padding:6px 8px; background:{bg}; opacity:{opacity}; "
                    f"min-height:72px; font-size:0.7rem; line-height:1.3;'>"
                    f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
                    f"<span style='font-weight:700; color:{text_main};'>#{s['rank']}</span>"
                    f"<span style='background:{mode_color}; color:#000; font-size:0.55rem; "
                    f"font-weight:800; padding:1px 5px; border-radius:3px;'>{mode_abbr}</span></div>"
                    f"<div style='color:{text_main}; font-weight:600; margin:2px 0; word-wrap:break-word; white-space:normal;'>"
                    f"{display_text}</div>"
                    f"<div style='color:{text_muted}; font-size:0.62rem;'>"
                    f"📞 {s['call_pct']}% calls · 🗺️ {s['land_pct']}% land</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                new_mode = st.radio(
                    'Fleet Mode',
                    options=mode_options,
                    index=mode_options.index(mode) if mode in mode_options else 2,
                    key=widget_key,
                    horizontal=True,
                    label_visibility="collapsed",
                )
                if new_mode != mode:
                    modes[idx] = new_mode
                    changed = True

    show_markers = st.checkbox(
        'Show suggested locations on map',
        value=session_state.get('show_suggestion_markers', True),
        key='_suggest_markers_toggle',
    )
    if show_markers != session_state.get('show_suggestion_markers', True):
        session_state['show_suggestion_markers'] = show_markers
        changed = True

    sync_station_suggestion_modes(session_state, suggestions)
    return changed
