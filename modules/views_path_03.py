"""Path 03: Demo mode simulation and deployment configuration."""
import datetime
import os
import random
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from modules.config import (
    DEMO_CITIES, FAST_DEMO_CITIES,
    KNOWN_POPULATIONS, STATE_FIPS, US_STATES_ABBR,
)
from modules.geospatial_utils import (
    generate_clustered_calls, generate_random_points_in_polygon,
    load_fast_demo_payload, FAST_DEMO_STATION_COUNT,
)
from modules.onboarding import (
    build_demo_boundaries, build_demo_calls, infer_simulation_targets_from_station_file,
    load_simulation_boundary_overlay, resolve_demo_stations, split_simulation_optional_files,
)
from modules.census import (
    fetch_census_population, fetch_census_state_population,
)
from modules.geocoding import (
    forward_geocode, search_public_facility_candidates,
)
from modules.boundaries import (
    fetch_county_boundary_local, fetch_place_boundary_local, fetch_tiger_state_shapefile,
    save_boundary_gdf, reverse_geocode_state,
)
from modules.stations import generate_stations_from_calls
from modules.image_utils import get_themed_logo_base64, get_transparent_product_base64


def render(submit_demo, _is_boundary_sidecar, _looks_like_stations, _load_uploaded_boundary_overlay):
    """Render Path 03: Demo city simulation and deployment planning."""
    st.markdown(f"""
    <div class="path-card" style="--accent:#FFD700;">
        <span class="pc-icon">⚡</span>
        <div class="pc-tag">Path 03</div>
        <div class="pc-title">Launch a<br>Demo</div>
        <div class="pc-desc">Instantly spin up a fully pre-configured scenario for a major US city. Ideal for live stakeholder presentations and platform walkthroughs.</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    if st.button("⚡ Launch Random Demo City", width="stretch", key="demo_btn", help="Load a random US city with simulated 911 call data to demo the full DFR deployment workflow."):
        random.seed(datetime.datetime.now().microsecond + os.getpid())
        already_used = st.session_state.get('_last_demo_city', '')
        candidates = [c for c in FAST_DEMO_CITIES if c[0] != already_used]
        rcity, rstate = random.choice(candidates)
        st.session_state['_last_demo_city'] = rcity
        st.session_state['target_cities'] = [{"city": rcity, "state": rstate}]
        st.session_state.city_count = 1
        for i in range(10):
            st.session_state.pop(f"c_{i}", None)
            st.session_state.pop(f"s_{i}", None)
        st.session_state['trigger_sim'] = True
        st.session_state['demo_mode_used'] = True
        st.rerun()

    city_chips = "  ·  ".join([f"{c}" for c, _ in FAST_DEMO_CITIES])
    st.markdown(f"""
    <div class="demo-cities">
        <b>Available Cities</b><br>
        {city_chips}
    </div>
    <div class="demo-check">
        <span>✓</span>Real Census boundaries<br>
        <span>✓</span>Clustered 911 simulation<br>
        <span>✓</span>{FAST_DEMO_STATION_COUNT} preloaded station candidates<br>
        <span>✓</span>Full optimization & export
    </div>
    """, unsafe_allow_html=True)

    # ── Build the demo if submit_demo or trigger_sim is set ──────────────────
    if submit_demo or st.session_state.get('trigger_sim', False):
        if st.session_state.get('trigger_sim', False):
            st.session_state['trigger_sim'] = False
            if not st.session_state.get('demo_mode_used', False):
                st.session_state['demo_mode_used'] = True

        active_targets = [
            {
                'city': str(loc.get('city', '') or '').strip(),
                'state': str(loc.get('state', '') or '').strip().upper(),
            }
            for loc in st.session_state['target_cities']
            if (
                str(loc.get('city', '') or '').strip()
                or (
                    st.session_state.get('highway_patrol_mode', False)
                    and str(loc.get('state', '') or '').strip().upper() in STATE_FIPS
                )
            )
        ]
        if not active_targets:
            _pre_sim_station_file, _, _ = split_simulation_optional_files(
                st.session_state.get('sim_optional_uploader') or [],
                _is_boundary_sidecar,
                _looks_like_stations,
            )
            if _pre_sim_station_file is not None:
                _inferred_targets, _inferred_notice = infer_simulation_targets_from_station_file(
                    _pre_sim_station_file,
                    forward_geocode,
                    reverse_geocode_state,
                    US_STATES_ABBR,
                    default_state=st.session_state.get('active_state', ''),
                )
                if _inferred_targets:
                    active_targets = _inferred_targets
                    st.session_state['target_cities'] = list(_inferred_targets)
                    st.session_state['active_city'] = _inferred_targets[0]['city']
                    st.session_state['active_state'] = _inferred_targets[0]['state']
                    if _inferred_notice:
                        st.toast(_inferred_notice)
        if not active_targets:
            st.error("Please enter at least one valid city, county, or state.")
            st.stop()

        _abbr_to_full = {abbr: name for name, abbr in US_STATES_ABBR.items()}
        if len(active_targets) == 1:
            _target_city = str(active_targets[0]['city']).title()
            if not _target_city:
                _target_city = _abbr_to_full.get(active_targets[0]['state'], active_targets[0]['state'])
            st.session_state['active_city']  = _target_city
            st.session_state['active_state'] = active_targets[0]['state']
        else:
            _target_city = str(active_targets[0]['city']).title()
            if not _target_city:
                _target_city = _abbr_to_full.get(active_targets[0]['state'], active_targets[0]['state'])
            st.session_state['active_city']  = f"{_target_city} & {len(active_targets)-1} others"
            st.session_state['active_state'] = active_targets[0]['state']

        # ── Fetch real population for upload path ─────────────────────────────
        try:
            _upload_pop = 0
            for _t in active_targets:
                _fips = STATE_FIPS.get(_t.get('state', ''), '')
                if _fips:
                    _p = fetch_census_population(_fips, _t.get('city', ''))
                    if _p:
                        _upload_pop += _p
            if _upload_pop > 0:
                st.session_state['estimated_pop'] = _upload_pop
        except Exception:
            pass

        # ── Flight-path loading overlay ───────────────────────────────────────
        _swarm_city = st.session_state.get('active_city', 'Jurisdiction') if active_targets else "Jurisdiction"
        _swarm_logo_b64 = get_themed_logo_base64("logo.png", theme="dark") or ""
        _swarm_gigs_b64 = get_transparent_product_base64("gigs.png") or ""
        _swarm_city_js  = _swarm_city.upper().replace('"', '').replace("'", '')
        _swarm_state_js = str(active_targets[0].get('state', 'US')).upper().replace('"', '').replace("'", '') if active_targets else "US"
        _swarm_map_svg = '<svg id="fl-svg" viewBox="0 0 600 360" xmlns="http://www.w3.org/2000/svg"></svg>'
        try:
            _swarm_map_svg = Path('usa.svg').read_text(encoding='utf-8')
            _swarm_map_svg = re.sub(r'^\s*<\?xml[^>]*>\s*', '', _swarm_map_svg, count=1)
            _swarm_map_svg = re.sub(r'^\s*<!--.*?-->\s*', '', _swarm_map_svg, count=1, flags=re.S)
            _swarm_map_svg = re.sub(r'<svg\b', '<svg id="fl-svg" class="fl-us-map" preserveAspectRatio="xMidYMid meet"', _swarm_map_svg, count=1)
        except Exception:
            pass

        _swarm_overlay_html = _build_swarm_overlay_html(
            _swarm_logo_b64, _swarm_gigs_b64, _swarm_map_svg, _swarm_city_js, _swarm_state_js
        )
        components.html(_swarm_overlay_html, height=0, scrolling=False)

        prog = st.progress(0, text="🫡 Preparing tools worthy of those who serve…")
        all_gdfs = []
        total_estimated_pop = 0
        _sim_station_file, _sim_boundary_files, _sim_unused_files = split_simulation_optional_files(
            st.session_state.get('sim_optional_uploader') or [],
            _is_boundary_sidecar,
            _looks_like_stations,
        )
        if _sim_unused_files:
            st.info("Path 03 ignored non-station files: " + ", ".join(_sim_unused_files))
        if _sim_boundary_files:
            try:
                _overlay_file = load_simulation_boundary_overlay(
                    st.session_state,
                    _sim_boundary_files,
                    _load_uploaded_boundary_overlay,
                )
                st.toast(f"Custom boundary overlay loaded: {_overlay_file}")
            except Exception as _overlay_exc:
                prog.empty()
                st.error(f"Boundary shapefile error: {_overlay_exc}")
                st.stop()

        fast_demo_target_set = {(city, state) for city, state in FAST_DEMO_CITIES}
        is_fast_demo_path = bool(active_targets) and all(
            (str(loc.get('city', '') or '').strip(), str(loc.get('state', '') or '').strip().upper())
            in fast_demo_target_set
            for loc in active_targets
        )

        if is_fast_demo_path:
            city_name = str(active_targets[0].get('city', '') or '').strip()
            state_name = str(active_targets[0].get('state', '') or '').strip().upper()
            fast_payload = load_fast_demo_payload(city_name, state_name)
            if not fast_payload:
                prog.empty()
                _hide_overlay()
                st.error("❌ Could not load the preloaded demo boundaries.")
                st.stop()
            all_gdfs = fast_payload['all_gdfs']
            boundary_records = fast_payload['boundary_records']
            total_estimated_pop = fast_payload['total_estimated_pop']
            boundary_messages = fast_payload['boundary_messages']
            boundary_warnings = fast_payload['boundary_warnings']
            rerun_demo_target = fast_payload['rerun_demo_target']
            all_populations_verified = fast_payload['all_populations_verified']
            st.session_state['boundary_source_path'] = fast_payload['boundary_source_path']
            st.session_state['master_gdf_override'] = fast_payload['master_gdf_override']
            demo_names = [
                str(name).strip()
                for name in fast_payload['master_gdf_override']['DISPLAY_NAME'].tolist()
                if str(name).strip()
            ]
            st.session_state['saved_jurisdiction_names'] = list(dict.fromkeys(demo_names))
            st.session_state['population_reference_targets'] = list(dict.fromkeys(demo_names))
        else:
            all_gdfs, boundary_records, total_estimated_pop, boundary_messages, boundary_warnings, rerun_demo_target, all_populations_verified = build_demo_boundaries(
                st.session_state,
                active_targets,
                STATE_FIPS,
                KNOWN_POPULATIONS,
                DEMO_CITIES,
                fetch_county_boundary_local,
                fetch_place_boundary_local,
                fetch_tiger_state_shapefile,
                save_boundary_gdf,
                fetch_census_population,
                fetch_census_state_population,
            )
            for _msg in boundary_messages:
                st.toast(_msg)
            for _warn in boundary_warnings:
                st.warning(_warn)
            if rerun_demo_target is not None:
                rcity, rstate = rerun_demo_target
                st.session_state['_last_demo_city'] = rcity
                st.session_state['target_cities'] = [{"city": rcity, "state": rstate}]
                for j in range(10):
                    st.session_state.pop(f"c_{j}", None)
                    st.session_state.pop(f"s_{j}", None)
                st.rerun()

            if not all_gdfs:
                prog.empty()
                _hide_overlay()
                st.error("❌ Could not find Census boundaries for any of the entered locations. Check spelling.")
                st.stop()

            _selected_boundary_override = pd.concat(all_gdfs, ignore_index=True).copy()
            _selected_name_col = next(
                (column for column in ['NAME', 'DISTRICT', 'NAMELSAD'] if column in _selected_boundary_override.columns),
                None,
            )
            if _selected_name_col is None:
                _selected_boundary_override['DISPLAY_NAME'] = 'Selected Boundary'
            else:
                _selected_boundary_override['DISPLAY_NAME'] = _selected_boundary_override[_selected_name_col].astype(str)
            _selected_boundary_override['data_count'] = 1
            st.session_state['master_gdf_override'] = _selected_boundary_override[['DISPLAY_NAME', 'data_count', 'geometry']].copy()
            _demo_selected_names = [
                str(name).strip() for name in _selected_boundary_override['DISPLAY_NAME'].tolist()
                if str(name).strip()
            ]
            st.session_state['saved_jurisdiction_names'] = list(dict.fromkeys(_demo_selected_names))
            st.session_state['population_reference_targets'] = list(dict.fromkeys(_demo_selected_names))

            prog.progress(35, text="💙 Boundaries loaded — honoring the officers who know every street…")
            active_city_gdf = pd.concat(all_gdfs, ignore_index=True)
            city_poly = active_city_gdf.geometry.union_all()
            st.session_state['estimated_pop'] = total_estimated_pop
            st.session_state['_pop_resolved'] = all_populations_verified

            prog.progress(55, text="🚔 Modeling 911 calls — every one represents someone who needed help…")
            df_demo, annual_cfs, simulated_points_count = build_demo_calls(
                city_poly,
                total_estimated_pop,
                generate_clustered_calls,
                boundary_records=boundary_records,
            )

        if is_fast_demo_path:
            city_poly = fast_payload['city_poly']
            df_demo = fast_payload['df_demo']
            annual_cfs = fast_payload['annual_cfs']
            simulated_points_count = fast_payload['simulated_points_count']

        st.session_state['total_original_calls'] = annual_cfs
        st.session_state['df_calls'] = df_demo
        st.session_state['df_calls_full'] = df_demo.copy()
        st.session_state['total_modeled_calls'] = len(df_demo)

        prog.progress(80, text="Loading simulation stations...")
        if is_fast_demo_path:
            stations_df = fast_payload['stations_df']
            stations_user_uploaded = fast_payload['stations_user_uploaded']
            station_notices = fast_payload['station_notices']
            station_warnings = fast_payload['station_warnings']
        else:
            stations_df, stations_user_uploaded, station_notices, station_warnings = resolve_demo_stations(
                st.session_state['df_calls'],
                city_poly,
                _sim_station_file,
                active_targets,
                forward_geocode,
                search_public_facility_candidates,
                generate_stations_from_calls,
                generate_random_points_in_polygon,
            )
        for _notice in station_notices:
            st.toast(_notice)
        for _warning in station_warnings:
            st.warning(_warning)
        st.session_state['df_stations'] = stations_df
        st.session_state['stations_user_uploaded'] = stations_user_uploaded

        prog.progress(100, text="✅ Ready — built for the communities they protect and serve.")
        st.session_state['inferred_daily_calls_override'] = int(annual_cfs / 365)
        st.session_state['data_source'] = 'simulation'
        st.session_state['sim_mode_used'] = True
        st.session_state['map_build_logged'] = False
        st.session_state['csvs_ready'] = True
        st.rerun()


def _build_swarm_overlay_html(logo_b64, gigs_b64, map_svg, city_js, state_js):
    """Build the swarm overlay HTML with animation."""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:transparent;overflow:hidden}}
#flo{{
  position:fixed;top:0;left:0;width:100vw;height:100vh;
  background:rgba(4,7,16,0.97);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  z-index:2147483647;font-family:'IBM Plex Mono',monospace;
}}
.fl-panels{{display:flex;align-items:center;justify-content:center;width:100%;max-width:940px;gap:24px;padding:0 24px}}
.fl-side{{width:150px;flex-shrink:0;display:flex;align-items:center;justify-content:center}}
.fl-side img{{max-width:140px;max-height:90px;object-fit:contain;opacity:0.92}}
.fl-map{{flex:1;min-width:0}}
.fl-map svg{{width:100%;height:auto;display:block}}
.fl-footer{{margin-top:20px;text-align:center;max-width:760px;padding:0 18px}}
.fl-city{{font-size:20px;font-weight:900;letter-spacing:3px;color:#fff}}
.fl-stline{{font-size:10px;letter-spacing:2px;color:rgba(0,210,255,0.7);text-transform:uppercase;margin-top:7px}}
.fl-made{{margin-top:12px;font-size:11px;font-weight:800;letter-spacing:2.6px;color:rgba(255,255,255,0.92);text-transform:uppercase}}
.fl-copy{{margin-top:8px;font-size:11px;line-height:1.55;color:rgba(255,255,255,0.62)}}
.fl-tribute-tag{{margin-top:14px;font-size:10px;font-weight:700;letter-spacing:2.8px;color:rgba(255,255,255,0.72);text-transform:uppercase}}
.fl-tribute-line{{margin-top:7px;font-size:10px;line-height:1.5;color:rgba(255,255,255,0.5);min-height:15px;transition:opacity 0.5s ease}}
.fl-dots::after{{content:'';animation:dots 1.4s steps(4,end) infinite}}
@keyframes dots{{0%{{content:''}}25%{{content:'.'}}50%{{content:'..'}}75%{{content:'...'}}}}
</style>
</head><body>
<div id="flo">
  <div class="fl-panels">
    <div class="fl-side"><img src="data:image/png;base64,{logo_b64}" alt="BRINC"></div>
    <div class="fl-map">
      {map_svg}
    </div>
    <div class="fl-side"><img src="data:image/png;base64,{gigs_b64}" alt="Fleet"></div>
  </div>
  <div class="fl-footer">
    <div class="fl-city">{city_js}</div>
    <div class="fl-stline" id="fl-stl">DEPLOYING FLEET<span class="fl-dots"></span></div>
    <div class="fl-made">MADE IN THE USA</div>
    <div class="fl-copy">American-built drone infrastructure supporting domestic jobs, resilient supply chains, and the communities they protect.</div>
    <div class="fl-tribute-tag">ONE OCTOBER</div>
    <div class="fl-tribute-line" id="fl-tribute">For those we remember. For those we can still protect.</div>
  </div>
</div>
<script>
(function(){{
  var doc = parent.document;
  var _old = doc.getElementById('brinc-flo');
  if(_old && _old.parentNode) _old.parentNode.removeChild(_old);
  var _olds = doc.getElementById('brinc-flo-css');
  if(_olds && _olds.parentNode) _olds.parentNode.removeChild(_olds);
  var _css = doc.createElement('style');
  _css.id = 'brinc-flo-css';
  _css.textContent =
    '#brinc-flo{{position:fixed!important;top:0!important;left:0!important;width:100vw!important;height:100vh!important;'
    +'background:rgba(4,7,16,0.97)!important;display:flex!important;flex-direction:column!important;'
    +'align-items:center!important;justify-content:center!important;'
    +'z-index:2147483647!important;font-family:"IBM Plex Mono",monospace!important}}'
    +'#brinc-flo .fl-panels{{display:flex;align-items:center;justify-content:center;width:100%;max-width:940px;gap:24px;padding:0 24px}}'
    +'#brinc-flo .fl-side{{width:150px;flex-shrink:0;display:flex;align-items:center;justify-content:center}}'
    +'#brinc-flo .fl-side img{{max-width:140px;max-height:90px;object-fit:contain;opacity:0.92}}'
    +'#brinc-flo .fl-map{{flex:1;min-width:0}}'
    +'#brinc-flo .fl-map svg{{width:100%;height:auto;display:block}}'
    +'#brinc-flo .fl-footer{{margin-top:20px;text-align:center;max-width:760px;padding:0 18px}}'
    +'#brinc-flo .fl-city{{font-size:20px;font-weight:900;letter-spacing:3px;color:#fff}}'
    +'#brinc-flo .fl-stline{{font-size:10px;letter-spacing:2px;color:rgba(0,210,255,0.7);text-transform:uppercase;margin-top:7px}}'
    +'#brinc-flo .fl-made{{margin-top:12px;font-size:11px;font-weight:800;letter-spacing:2.6px;color:rgba(255,255,255,0.92);text-transform:uppercase}}'
    +'#brinc-flo .fl-copy{{margin-top:8px;font-size:11px;line-height:1.55;color:rgba(255,255,255,0.62)}}'
    +'#brinc-flo .fl-tribute-tag{{margin-top:14px;font-size:10px;font-weight:700;letter-spacing:2.8px;color:rgba(255,255,255,0.72);text-transform:uppercase}}'
    +'#brinc-flo .fl-tribute-line{{margin-top:7px;font-size:10px;line-height:1.5;color:rgba(255,255,255,0.5);min-height:15px;transition:opacity 0.5s ease}}'
    +'#brinc-flo .fl-us-map{{width:100%;height:auto;display:block}}'
    +'@keyframes brinc-flo-dots{{0%{{content:""}}25%{{content:"."}}50%{{content:".."}}75%{{content:"..."}}}}';
  (doc.head || doc.body).appendChild(_css);
  var el = document.getElementById('flo');
  var clone = el.cloneNode(true);
  clone.id = 'brinc-flo';
  doc.body.appendChild(clone);
  el.style.display = 'none';
}})();
</script>
</body></html>
"""


def _hide_overlay():
    """Hide the swarm overlay on error."""
    components.html("""<!DOCTYPE html><html><head></head><body><script>
(function(){{
  var doc = parent.document;
  if(parent._brincFloWd){{parent.clearInterval(parent._brincFloWd);parent._brincFloWd=null;}}
  var el = doc.getElementById('brinc-flo');
  if(el){{el.style.transition='opacity 0.35s ease';el.style.opacity='0';
    parent.setTimeout(function(){{
      var e = doc.getElementById('brinc-flo');if(e && e.parentNode) e.parentNode.removeChild(e);
      var s = doc.getElementById('brinc-flo-css');if(s && s.parentNode) s.parentNode.removeChild(s);
    }}, 360);}}
}})();
</script></body></html>""", height=0, scrolling=False)
