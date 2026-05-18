"""Path 02: CAD file upload view and Census batch processing."""
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures as cf
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from modules.config import STATE_FIPS, get_jurisdiction_message, US_STATES_ABBR
from modules.helpers import _uploaded_files_signature, _reset_census_state, format_wait_duration
from modules.onboarding import (
    detect_brinc_file,
    load_brinc_save_data,
    restore_brinc_session,
    split_uploaded_files,
    load_station_file,
    detect_location_from_calls,
    resolve_uploaded_boundaries,
)
from modules.stations import (
    generate_stations_from_calls,
    _make_random_stations,
    _select_best_boundary_for_calls,
)
from modules.boundaries import (
    reverse_geocode_state,
    save_boundary_gdf,
    _refresh_reference_population,
)
from modules.geospatial import (
    find_jurisdictions_by_coordinates,
)
from modules.utilities import (
    get_relevant_jurisdictions_cached,
)
from modules.cad_parser import aggressive_parse_calls
from modules.census_batch import (
    build_census_staging,
    build_intersection_fallback_rows,
    make_census_batch_chunks,
    submit_census_batch_chunk,
    parse_census_result_files,
    merge_census_results,
    build_corrected_export_from_merged,
    make_census_batch_zip,
    make_sample_census_batch,
    build_census_chunk_payload,
)
from modules.geocoding import geocode_intersection_fallback_rows
from modules.notifications import _write_crash_report, _notify_crash_email
from modules.image_utils import get_themed_logo_base64, get_transparent_product_base64


def render():
    """Render Path 02: CAD file upload and Census batch processing."""
    st.markdown(f"""
    <div class="path-card" style="--accent:#39FF14;">
        <span class="pc-icon">📂</span>
        <div class="pc-tag">Path 02</div>
        <div class="pc-title">Upload CAD<br>Incident Files</div>
        <div class="pc-desc">
            Drop <b>any</b> CAD incident file — no renaming needed.
            Or, drop a previously saved <b>.brinc</b> file to instantly restore your deployment.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    uploaded_files = st.file_uploader(
        "Drop CAD incident files + optional stations + optional boundary shapefile files",
        accept_multiple_files=True,
        type=['csv', 'xlsx', 'xls', 'xlsb', 'xlsm', 'numbers', 'brinc', 'json', 'txt', 'shp', 'shx', 'dbf', 'prj'],
        label_visibility="collapsed",
        help="Upload real CAD incident files, optional stations, and optional shapefile sidecars (.shp/.shx/.dbf/.prj) for a display-only boundary overlay. Or drop a .brinc file to restore a previous session."
    )
    st.session_state['_last_uploaded_files'] = [getattr(f, 'name', '') for f in (uploaded_files or [])]

    st.markdown("""
    <div class="field-footnote">
        <b style='color:#555;'>1 file</b> — any CAD incident file; stations auto-built from OSM<br>
        <b style='color:#555;'>Multiple CAD files</b> — drop several incident files; they are combined automatically<br>
        <b style='color:#555;'>CAD + stations</b> — include a file with "station" in the name to supply custom stations<br>
        <b style='color:#39FF14;'>.brinc file</b> — instantly restore a saved deployment<br>
        Max 25,000 calls (sampled) · 100 stations
    </div>
    """, unsafe_allow_html=True)

    def _looks_like_stations(fname):
        n = fname.lower()
        return any(k in n for k in ['station','facility','loc'])

    def _is_boundary_sidecar(fname):
        return Path(fname).suffix.lower() in {'.shp', '.shx', '.dbf', '.prj'}

    current_upload_signature = _uploaded_files_signature(uploaded_files)
    if current_upload_signature and st.session_state.get('census_source_signature') and current_upload_signature != st.session_state.get('census_source_signature'):
        _reset_census_state(st.session_state)

    census_result_files = None
    if st.session_state.get('census_pending'):
        _census_summary = st.session_state.get('census_summary') or {}
        _rows_ready = int(_census_summary.get('rows_ready', 0) or 0)
        _rows_missing = int(_census_summary.get('rows_missing', 0) or 0)
        st.warning(
            f"Census batch conversion is waiting for results. "
            f"{_rows_ready:,} rows are ready for Census formatting and {_rows_missing:,} rows still need address cleanup."
        )
        st.caption(
            "Download the prepared batch files, run them through the Census batch geocoder, "
            "then upload the returned result CSVs here. The prepared data is only kept for this browser session."
        )
        st.info(
            "What is happening now: the app identified that this upload does not contain recoverable coordinates and switched to the Census batch workflow. "
            "Preparing the batch files should usually take a few seconds to about 30 seconds. "
            "After that, total turnaround depends on how quickly the Census files are uploaded there and returned here."
        )
        if st.session_state.get('census_sample_bytes'):
            st.download_button(
                "⬇️ Download Census Sample Batch",
                data=st.session_state['census_sample_bytes'],
                file_name=st.session_state.get('census_sample_name') or "census_sample_batch.csv",
                mime="text/csv",
                key="download_census_sample_batch_btn",
                width="stretch",
            )
        if st.session_state.get('census_batch_zip_bytes'):
            st.download_button(
                "⬇️ Download Census Batch ZIP",
                data=st.session_state['census_batch_zip_bytes'],
                file_name=st.session_state.get('census_batch_zip_name') or "census_batches.zip",
                mime="application/zip",
                key="download_census_batch_zip_btn",
                width="stretch",
            )
        census_result_files = st.file_uploader(
            "Upload returned Census result CSVs",
            accept_multiple_files=True,
            type=['csv', 'txt'],
            key='census_result_files_uploader',
            help="Upload the CSV result files returned by the Census batch geocoder. The app will stitch them together and continue into the stations workflow.",
        )

        if census_result_files:
            with st.spinner("🛰 Stitching Census results back into the CAD file…"):
                result_df = parse_census_result_files(census_result_files)
                partial_calls_df = st.session_state.get('census_partial_calls_df')
                original_df = st.session_state.get('census_original_df')
                if partial_calls_df is None or original_df is None or result_df.empty:
                    st.error("❌ Census result upload failed: missing prepared session data or no valid result rows were found.")
                    st.stop()

                merged_full_df, merged_ready_df, merge_summary = merge_census_results(
                    partial_calls_df,
                    result_df,
                    validate_outputs=False,
                )
                if merged_ready_df is None or merged_ready_df.empty:
                    st.error("❌ Census result upload failed: no valid coordinates were recovered from the returned result files.")
                    st.stop()

                _export_started_at = time.perf_counter()
                corrected_export_df = build_corrected_export_from_merged(merged_full_df)
                corrected_csv = corrected_export_df.to_csv(index=False).encode('utf-8')
                st.session_state['census_corrected_bytes'] = corrected_csv
                st.session_state['census_corrected_name'] = "cad_calls_census_corrected.csv"
                st.session_state['census_conversion_summary'] = merge_summary
                st.session_state['census_download_notice'] = True

                df_c_full = merged_ready_df.reset_index(drop=True).copy()
                if len(df_c_full) > 25000:
                    df_c = df_c_full.sample(25000, random_state=42).reset_index(drop=True)
                    st.toast(f"⚠️ Optimization modeled with {len(df_c):,} representative calls out of {len(df_c_full):,} geocoded incidents.")
                else:
                    df_c = df_c_full.copy()

                call_files_current, station_file_current, boundary_files_current = split_uploaded_files(
                    uploaded_files or [],
                    _is_boundary_sidecar,
                    _looks_like_stations,
                )

                if station_file_current is not None:
                    with st.spinner("🔍 Reading stations file…"):
                        try:
                            df_s, osm_note = load_station_file(station_file_current)
                            st.session_state['stations_user_uploaded'] = True
                        except Exception as e:
                            df_s, osm_note = None, f"Failed: {e}"
                    if df_s is None or df_s.empty:
                        st.error(f"❌ Stations file error: {osm_note}")
                        st.stop()
                else:
                    st.session_state['stations_user_uploaded'] = False
                    with st.spinner("🌐 No stations file detected — querying OpenStreetMap for police, fire & schools; this can take 10-20 seconds…"):
                        df_s, osm_note = generate_stations_from_calls(df_c)
                    if df_s is None or df_s.empty:
                        df_s = _make_random_stations(df_c, n=40)
                        osm_note = "⚠️ Could not reach any map source — using estimated station positions from call data."
                        st.warning(osm_note)
                    else:
                        st.toast(f"✅ {osm_note}")

                if len(df_s) > 100:
                    df_s = df_s.sample(100, random_state=42).reset_index(drop=True)

                with st.spinner("🛰 Census coordinates restored — resolving jurisdiction…"):
                    detected_city, detected_state, detection_source = detect_location_from_calls(
                        df_c,
                        STATE_FIPS,
                        US_STATES_ABBR,
                        reverse_geocode_state,
                    )
                    if detected_city and detected_state:
                        st.session_state['active_city'] = str(detected_city).title()
                        st.session_state['active_state'] = detected_state
                        st.session_state['target_cities'] = [{"city": detected_city, "state": detected_state}]
                        st.session_state['location_detection_source'] = detection_source
                    elif detected_state:
                        st.session_state['active_state'] = detected_state
                        st.session_state['location_detection_source'] = detection_source

                st.session_state['df_calls'] = df_c
                st.session_state['df_calls_full'] = df_c_full
                st.session_state['df_stations'] = df_s
                st.session_state['total_original_calls'] = int(merge_summary.get('rows_total', len(df_c_full)) or len(df_c_full))
                st.session_state['total_modeled_calls'] = len(df_c)

                with st.spinner(get_jurisdiction_message()):
                    resolve_uploaded_boundaries(
                        st,
                        st.session_state,
                        df_c,
                        df_c_full,
                        STATE_FIPS,
                        find_jurisdictions_by_coordinates,
                        _select_best_boundary_for_calls,
                        save_boundary_gdf,
                    )

                try:
                    _refresh_reference_population(st.session_state)
                except Exception:
                    pass

                st.session_state['data_source'] = 'cad_upload'
                st.session_state['demo_mode_used'] = False
                st.session_state['sim_mode_used'] = False
                st.session_state['map_build_logged'] = False
                st.session_state['csvs_ready'] = True
                st.toast("✅ Census batch conversion completed. The corrected calls file is ready for download in the sidebar.")
                _reset_census_state(st.session_state)
                st.session_state['census_corrected_bytes'] = corrected_csv
                st.session_state['census_corrected_name'] = "cad_calls_census_corrected.csv"
                st.session_state['census_conversion_summary'] = merge_summary
                st.session_state['census_download_notice'] = True
                st.rerun()

    if uploaded_files and len(uploaded_files) >= 1 and not (
        st.session_state.get('census_pending') and
        current_upload_signature == st.session_state.get('census_source_signature') and
        not census_result_files
    ):
        _upload_logo_b64 = get_themed_logo_base64("logo.png", theme="dark") or ""
        _upload_gigs_b64 = get_transparent_product_base64("gigs.png") or ""
        _upload_overlay_html = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script>
(function(){{
  var doc = parent.document;
  var old = doc.getElementById('brinc-flo');
  if(old && old.parentNode) old.parentNode.removeChild(old);
  var oldCss = doc.getElementById('brinc-flo-css');
  if(oldCss && oldCss.parentNode) oldCss.parentNode.removeChild(oldCss);
  var css = doc.createElement('style');
  css.id = 'brinc-flo-css';
  css.textContent =
    '#brinc-flo{{position:fixed!important;top:0!important;left:0!important;width:100vw!important;height:100vh!important;background:rgba(4,7,16,0.97)!important;display:flex!important;flex-direction:column!important;align-items:center!important;justify-content:center!important;z-index:2147483647!important;font-family:"IBM Plex Mono",monospace!important}}'
    +'#brinc-flo .fl-panels{{display:flex;align-items:center;justify-content:center;width:100%;max-width:940px;gap:24px;padding:0 24px}}'
    +'#brinc-flo .fl-side{{width:150px;flex-shrink:0;display:flex;align-items:center;justify-content:center}}'
    +'#brinc-flo .fl-side img{{max-width:140px;max-height:90px;object-fit:contain;opacity:0.92}}'
    +'#brinc-flo .fl-map{{flex:1;min-width:0;display:flex;align-items:center;justify-content:center}}'
    +'#brinc-flo .fl-footer{{margin-top:20px;text-align:center;max-width:760px;padding:0 18px}}'
    +'#brinc-flo .fl-city{{font-size:20px;font-weight:900;letter-spacing:3px;color:#fff}}'
    +'#brinc-flo .fl-stline{{font-size:10px;letter-spacing:2px;color:rgba(0,210,255,0.7);text-transform:uppercase;margin-top:7px}}'
    +'#brinc-flo .fl-made{{margin-top:12px;font-size:11px;font-weight:800;letter-spacing:2.6px;color:rgba(255,255,255,0.92);text-transform:uppercase}}'
    +'#brinc-flo .fl-copy{{margin-top:8px;font-size:11px;line-height:1.55;color:rgba(255,255,255,0.62)}}'
    +'#brinc-flo .fl-prog-wrap{{margin:14px auto 0;max-width:520px}}'
    +'#brinc-flo .fl-prog-meta{{display:flex;justify-content:space-between;gap:12px;font-size:10px;letter-spacing:1.6px;color:rgba(255,255,255,0.62);text-transform:uppercase}}'
    +'#brinc-flo .fl-prog{{margin-top:6px;height:7px;border-radius:999px;background:rgba(255,255,255,0.08);overflow:hidden;border:1px solid rgba(255,255,255,0.08)}}'
    +'#brinc-flo .fl-prog-bar{{height:100%;width:4%;background:linear-gradient(90deg,#00D2FF,#39FF14);box-shadow:0 0 18px rgba(0,210,255,0.35);transition:width .28s ease}}'
    +'#brinc-flo .fl-log{{margin:14px auto 0;max-width:620px;min-height:86px;max-height:132px;overflow:auto;text-align:left;padding:12px 14px;border:1px solid rgba(255,255,255,0.08);border-radius:12px;background:rgba(255,255,255,0.03);font-size:11px;line-height:1.5;color:rgba(255,255,255,0.72);white-space:pre-wrap}}'
    +'#brinc-flo .fl-log.error{{border-color:rgba(255,99,99,0.45);background:rgba(110,20,20,0.22);color:rgba(255,215,215,0.95)}}'
    +'#brinc-flo .fl-loader{{position:relative;width:280px;height:180px}}'
    +'#brinc-flo .fl-radar{{position:absolute;inset:18px;border:1px solid rgba(0,210,255,0.22);border-radius:50%}}'
    +'#brinc-flo .fl-radar::before,#brinc-flo .fl-radar::after{{content:"";position:absolute;border:1px solid rgba(0,210,255,0.18);border-radius:50%}}'
    +'#brinc-flo .fl-radar::before{{inset:22px}}'
    +'#brinc-flo .fl-radar::after{{inset:44px}}'
    +'#brinc-flo .fl-sweep{{position:absolute;left:50%;top:50%;width:120px;height:2px;transform-origin:left center;background:linear-gradient(90deg,rgba(0,210,255,0.95),rgba(0,210,255,0));animation:brinc-upload-spin 2.2s linear infinite}}'
    +'#brinc-flo .fl-core{{position:absolute;left:50%;top:50%;width:12px;height:12px;margin-left:-6px;margin-top:-6px;border-radius:50%;background:#00D2FF;box-shadow:0 0 20px rgba(0,210,255,0.65)}}'
    +'#brinc-flo .fl-blip{{position:absolute;width:10px;height:10px;border-radius:50%;background:rgba(0,210,255,0.85);box-shadow:0 0 14px rgba(0,210,255,0.5);animation:brinc-upload-blip 1.8s ease-in-out infinite alternate}}'
    +'#brinc-flo .fl-blip.b1{{left:58px;top:42px;animation-delay:0.1s}}'
    +'#brinc-flo .fl-blip.b2{{right:64px;top:58px;animation-delay:0.5s}}'
    +'#brinc-flo .fl-blip.b3{{left:96px;bottom:38px;animation-delay:0.9s}}'
    +'#brinc-flo .fl-dots::after{{content:"";animation:brinc-flo-dots 1.4s steps(4,end) infinite}}'
    +'@keyframes brinc-flo-dots{{0%{{content:""}}25%{{content:"."}}50%{{content:".."}}75%{{content:"..."}}}}'
    +'@keyframes brinc-upload-spin{{from{{transform:rotate(0deg)}}to{{transform:rotate(360deg)}}}}'
    +'@keyframes brinc-upload-blip{{from{{transform:scale(0.7);opacity:0.45}}to{{transform:scale(1.15);opacity:1}}}}';
  (doc.head || doc.body).appendChild(css);
  var wrap = doc.createElement('div');
  wrap.id = 'brinc-flo';
  wrap.innerHTML = '<div class="fl-panels">'
    + '<div class="fl-side"><img src="data:image/png;base64,{_upload_logo_b64}" alt="BRINC"></div>'
    + '<div class="fl-map"><div class="fl-loader"><div class="fl-radar"></div><div class="fl-sweep"></div><div class="fl-core"></div><div class="fl-blip b1"></div><div class="fl-blip b2"></div><div class="fl-blip b3"></div></div></div>'
    + '<div class="fl-side"><img src="data:image/png;base64,{_upload_gigs_b64}" alt="Fleet"></div>'
    + '</div>'
    + '<div class="fl-footer">'
    + '<div class="fl-city">CAD UPLOAD</div>'
    + '<div class="fl-stline" id="fl-stl">INGESTING INCIDENT DATA<span class="fl-dots"></span></div>'
    + '<div class="fl-made">MADE IN THE USA</div>'
    + '<div class="fl-copy">Parsing calls, resolving boundaries, and preparing deployment analysis.</div>'
    + '<div class="fl-prog-wrap"><div class="fl-prog-meta"><span id="fl-prog-label">Progress</span><span id="fl-prog-pct">0%</span></div><div class="fl-prog"><div class="fl-prog-bar" id="fl-prog-bar"></div></div></div>'
    + '<div class="fl-log" id="fl-log">Waiting to start…</div>'
    + '</div>';
  doc.body.appendChild(wrap);
  var statusEl = wrap.querySelector('#fl-stl');
  var msgs = ['INGESTING INCIDENT DATA','CHECKING FOR LAT/LON','DETECTING COLUMN TYPES','PREPARING CENSUS BATCH IF NEEDED','RESOLVING JURISDICTION','BUILDING STATION GRID','PREPARING ANALYSIS'];
  var mi = 0;
  if(parent._brincFloMsgs) parent.clearInterval(parent._brincFloMsgs);
  parent._brincFloMsgs = parent.setInterval(function(){{
    mi = (mi + 1) % msgs.length;
    if(statusEl) statusEl.innerHTML = msgs[mi] + '<span class="fl-dots"></span>';
  }}, 2400);
}})();
</script>
</body></html>"""
        _upload_overlay_html = (
            _upload_overlay_html
            .replace("{_upload_logo_b64}", _upload_logo_b64)
            .replace("{_upload_gigs_b64}", _upload_gigs_b64)
            .replace("{{", "{")
            .replace("}}", "}")
        )
        components.html(_upload_overlay_html, height=0, scrolling=False)

        def _clear_upload_overlay():
            components.html("""<!DOCTYPE html><html><head></head><body><script>
(function(){
  var doc = parent.document;
  if(parent._brincFloWd){ parent.clearInterval(parent._brincFloWd); parent._brincFloWd = null; }
  if(parent._brincFloMsgs){ parent.clearInterval(parent._brincFloMsgs); parent._brincFloMsgs = null; }
  var el = doc.getElementById('brinc-flo');
  if(el){
    el.style.transition = 'opacity 0.25s ease';
    el.style.opacity = '0';
  }
  parent.setTimeout(function(){
    var e = doc.getElementById('brinc-flo');
    if(e && e.parentNode) e.parentNode.removeChild(e);
    var s = doc.getElementById('brinc-flo-css');
    if(s && s.parentNode) s.parentNode.removeChild(s);
  }, 280);
})();
</script></body></html>""", height=0, scrolling=False)

        def _set_upload_overlay_status(title="", status="", copy="", progress=None, logs=None, error=False):
            _title_js = json.dumps(str(title or ""))
            _status_js = json.dumps(str(status or ""))
            _copy_js = json.dumps(str(copy or ""))
            _progress_val = max(0, min(100, int(progress if progress is not None else 0)))
            _logs_js = json.dumps([str(x) for x in (logs or [])][-8:])
            _error_js = 'true' if error else 'false'
            _upload_overlay_status_html = """<!DOCTYPE html><html><head></head><body><script>
(function(){{
  var doc = parent.document;
  var el = doc.getElementById('brinc-flo');
  if(!el) return;
  var titleEl = el.querySelector('.fl-city');
  var statusEl = el.querySelector('#fl-stl');
  var copyEl = el.querySelector('.fl-copy');
  var progBar = el.querySelector('#fl-prog-bar');
  var progPct = el.querySelector('#fl-prog-pct');
  var logEl = el.querySelector('#fl-log');
  if(titleEl && {_title_js}) titleEl.textContent = {_title_js};
  if(statusEl && {_status_js}) statusEl.innerHTML = {_status_js} + '<span class="fl-dots"></span>';
  if(copyEl && {_copy_js}) copyEl.textContent = {_copy_js};
  if(progBar) progBar.style.width = '{_progress_val}%';
  if(progPct) progPct.textContent = '{_progress_val}%';
  if(logEl){{
    var _lines = {_logs_js};
    logEl.innerHTML = _lines && _lines.length ? _lines.join('<br>') : 'Waiting to start…';
    if({_error_js}) logEl.classList.add('error'); else logEl.classList.remove('error');
  }}
  if(parent._brincFloMsgs){{ parent.clearInterval(parent._brincFloMsgs); parent._brincFloMsgs = null; }}
}})();
</script></body></html>"""
            _upload_overlay_status_html = (
                _upload_overlay_status_html
                .replace("{_title_js}", _title_js)
                .replace("{_status_js}", _status_js)
                .replace("{_copy_js}", _copy_js)
                .replace("{_progress_val}", str(_progress_val))
                .replace("{_logs_js}", _logs_js)
                .replace("{_error_js}", _error_js)
                .replace("{{", "{")
                .replace("}}", "}")
            )
            components.html(_upload_overlay_status_html, height=0, scrolling=False)

        _upload_logs = []

        def _push_upload_log(message):
            _upload_logs.append(str(message))
            return list(_upload_logs[-8:])

        def _mark_upload_step(step_name):
            st.session_state['_upload_crash_step'] = str(step_name)

        def _get_crash_user_email():
            email = str(st.session_state.get('google_user_email', '') or st.session_state.get('_last_user_email', '') or '').strip()
            if email:
                return email
            try:
                email = str(getattr(st.user, 'email', '') or '').strip()
            except Exception:
                email = ''
            return email

        def _get_crash_city_state():
            city = str(st.session_state.get('active_city', '') or '').strip()
            state = str(st.session_state.get('active_state', '') or '').strip()
            return city, state

        def _report_upload_crash(step_name, exc):
            tb_text = traceback.format_exc()
            _push_upload_log(f"❌ Crash at {step_name}: {exc}")
            _push_upload_log("Traceback captured for crash alert.")
            st.session_state['_last_upload_crash'] = {
                'step': str(step_name),
                'error': str(exc),
                'traceback': tb_text,
            }
            crash_report_path = None
            try:
                _city, _state = _get_crash_city_state()
                _files = list(st.session_state.get('_last_uploaded_files', []))
                crash_report_path = _write_crash_report(
                    step_name,
                    str(exc),
                    tb_text,
                    details={
                        'source_app': Path(__file__).resolve().parent.parent.name,
                        'session_id': st.session_state.get('session_id', ''),
                        'user_email': _get_crash_user_email(),
                        'city': _city,
                        'state': _state,
                        'file_count': len(_files),
                        'upload_signature': current_upload_signature if 'current_upload_signature' in locals() else '',
                        'upload_files': _files,
                    },
                )
                if crash_report_path:
                    st.session_state['_last_crash_report_path'] = str(crash_report_path)
                    _push_upload_log(f"Crash report saved to {crash_report_path}")
                _notify_crash_email(
                    step_name,
                    str(exc),
                    tb_text,
                    details={
                        'source_app': Path(__file__).resolve().parent.parent.name,
                        'session_id': st.session_state.get('session_id', ''),
                        'user_email': _get_crash_user_email(),
                        'city': _city,
                        'state': _state,
                        'file_count': len(_files),
                        'upload_signature': current_upload_signature if 'current_upload_signature' in locals() else '',
                        'upload_files': _files,
                    },
                )
            except Exception as _crash_email_exc:
                _push_upload_log(f"⚠ Crash email failed: {_crash_email_exc}")
            if not crash_report_path:
                _push_upload_log("⚠ Local crash report could not be written.")
            try:
                _set_upload_overlay_status(
                    title="UPLOAD ERROR",
                    status="CRASH DETECTED",
                    copy=f"An unexpected error occurred while {step_name}. The full traceback has been logged locally and emailed if notifications are configured.",
                    progress=100,
                    logs=_upload_logs,
                    error=True,
                )
            except Exception:
                pass

        # --- 1. INTELLIGENTLY CHECK FOR .BRINC FILE ---
        # Browsers sometimes append .json to .brinc files on download
        _mark_upload_step("checking for .brinc restore")
        brinc_file = detect_brinc_file(uploaded_files)

        if brinc_file:
            with st.spinner("💾 Restoring saved deployment..."):
                try:
                    save_data = load_brinc_save_data(brinc_file)
                    restore_brinc_session(st.session_state, save_data)
                    st.toast("✅ Deployment restored successfully!")
                    st.rerun()
                except Exception as e:
                    _clear_upload_overlay()
                    st.error(f"❌ Error loading .brinc file: {e}")
                    st.stop()

        else:
            # --- 2. OTHERWISE, PROCESS AS NORMAL CSV CAD DATA ---
            _mark_upload_step("splitting uploaded files")
            st.session_state['active_city'] = ""
            st.session_state['active_state'] = ""
            st.session_state['target_cities'] = []

            call_files, station_file, boundary_files = split_uploaded_files(
                uploaded_files,
                _is_boundary_sidecar,
                _looks_like_stations,
            )
            st.session_state['boundary_overlay_gdf'] = None
            st.session_state['boundary_overlay_name'] = ''
            st.session_state['boundary_overlay_file'] = ''

            if call_files:
                census_auto_processed = False
                _mark_upload_step("inspecting call files for coordinates")
                _push_upload_log("Starting coordinate inspection.")
                _set_upload_overlay_status(
                    title="CAD UPLOAD",
                    status="CHECKING FOR COORDINATES",
                    copy="Inspecting headers and cell values for usable latitude and longitude fields. This usually takes a few seconds.",
                    progress=8,
                    logs=_upload_logs,
                )
                with st.spinner("🔍 Detecting column types in CAD export…"):
                    _mark_upload_step("parsing CAD upload")
                    df_c = aggressive_parse_calls(call_files)
                for _pq_item in st.session_state.get('parse_quality', []):
                    _pq_in = _pq_item.get('input_rows', 0)
                    _pq_out = _pq_item.get('output_rows', 0)
                    if _pq_item.get('status') == 'error':
                        _push_upload_log(f"⚠ {_pq_item['file']}: parse failed — {_pq_item.get('error', '')[:100]}")
                    elif _pq_in > 0:
                        _pq_yield = round(100 * _pq_out / _pq_in)
                        _push_upload_log(f"{_pq_item['file']}: {_pq_in:,} rows in → {_pq_out:,} usable ({_pq_yield}%)")

                if df_c is None or df_c.empty:
                    _push_upload_log("No usable coordinates found. Switching to automated Census batch geocoding.")
                    _set_upload_overlay_status(
                        title="CENSUS REQUIRED",
                        status="COORDINATES NOT FOUND",
                        copy="No usable latitude/longitude values were found in the upload. Preparing automated Census batch geocoding now.",
                        progress=18,
                        logs=_upload_logs,
                    )
                    with st.spinner("🛰 No recoverable coordinates found — preparing Census batch conversion; this usually takes a few seconds…"):
                        _mark_upload_step("building Census staging data")
                        _push_upload_log("Building partial call frame for merge-back.")
                        _set_upload_overlay_status(
                            title="CENSUS REQUIRED",
                            status="BUILDING STAGING DATA",
                            copy="Preparing source rows and merge keys before Census submission.",
                            progress=24,
                            logs=_upload_logs,
                        )
                        df_c_partial = aggressive_parse_calls(call_files, require_valid_coordinates=False)
                        _push_upload_log("Extracting street, city, state, and ZIP fields for Census formatting.")
                        _set_upload_overlay_status(
                            title="CENSUS REQUIRED",
                            status="EXTRACTING ADDRESSES",
                            copy="Deriving Census-ready address fields from the uploaded CAD export.",
                            progress=32,
                            logs=_upload_logs,
                        )
                        census_stage_df, census_original_df, census_summary = build_census_staging(call_files)
                        census_intersection_df = build_intersection_fallback_rows(census_stage_df)
                        st.session_state['census_intersection_df'] = census_intersection_df
                        intersection_result_df = pd.DataFrame()
                        if census_intersection_df is not None and not census_intersection_df.empty:
                            _push_upload_log(
                                f"Preparing fallback geocoding for {len(census_intersection_df):,} intersection row(s)."
                            )
                            _set_upload_overlay_status(
                                title="CENSUS REQUIRED",
                                status="GEOCODING INTERSECTIONS",
                                copy="Geocoding intersection rows separately so they can merge back beside the Census results.",
                                progress=36,
                                logs=_upload_logs,
                            )
                            intersection_result_df = geocode_intersection_fallback_rows(
                                census_intersection_df,
                                max_workers=8,
                                log_fn=_push_upload_log,
                            )
                            st.session_state['census_intersection_result_df'] = intersection_result_df
                            census_summary['intersection_geocoded_rows'] = int(len(intersection_result_df))
                            _push_upload_log(
                                f"Intersection fallback geocoding returned {len(intersection_result_df):,} usable row(s)."
                            )
                        else:
                            st.session_state['census_intersection_result_df'] = pd.DataFrame()
                            census_summary['intersection_geocoded_rows'] = 0
                        if (
                            df_c_partial is None or
                            df_c_partial.empty or
                            '_source_row_id' not in df_c_partial.columns
                        ):
                            _push_upload_log(
                                "Structured CAD parsing was unavailable for merge-back. Falling back to staged source rows for the Census merge."
                            )
                            df_c_partial = census_original_df.copy()
                            if '_source_row_id' not in df_c_partial.columns:
                                df_c_partial['_source_row_id'] = [
                                    f"fallback:{idx}" for idx in range(len(df_c_partial))
                                ]
                            if '_source_file' not in df_c_partial.columns:
                                df_c_partial['_source_file'] = call_files[0].name if call_files else ''
                            if 'priority' not in df_c_partial.columns:
                                df_c_partial['priority'] = 3
                            if 'agency' not in df_c_partial.columns:
                                df_c_partial['agency'] = 'police'
                            _set_upload_overlay_status(
                                title="CENSUS REQUIRED",
                                status="USING MERGE FALLBACK",
                                copy="The upload did not produce a structured CAD dataframe, so the app is preserving the staged source rows and merging coordinates back onto them directly.",
                                progress=34,
                                logs=_upload_logs,
                            )
                        if census_stage_df is None or census_stage_df.empty or int(census_summary.get('rows_ready', 0) or 0) == 0:
                            _clear_upload_overlay()
                            st.error("❌ Calls file error: no valid coordinates were found and the app could not assemble enough address data for Census batch geocoding.")
                            st.stop()

                        for _file_diag in (census_summary.get('files') or [])[:4]:
                            _diag_bits = []
                            if _file_diag.get('street_cols'):
                                _diag_bits.append(f"street={','.join(_file_diag['street_cols'][:3])}")
                            if _file_diag.get('city_col'):
                                _diag_bits.append(f"city={_file_diag['city_col']}")
                            if _file_diag.get('state_col'):
                                _diag_bits.append(f"state={_file_diag['state_col']}")
                            if _file_diag.get('zip_col'):
                                _diag_bits.append(f"zip={_file_diag['zip_col']}")
                            if _file_diag.get('intersection_rows'):
                                _diag_bits.append(f"intersections={int(_file_diag['intersection_rows'])}")
                            _push_upload_log(
                                f"{_file_diag.get('file','file')}: {_file_diag.get('ready_rows',0):,}/{_file_diag.get('rows',0):,} rows ready"
                                + (f" ({'; '.join(_diag_bits)})" if _diag_bits else "")
                            )
                        if census_summary.get('intersection_rows'):
                            _push_upload_log(
                                f"Separated {int(census_summary.get('intersection_rows', 0) or 0):,} intersection row(s) into the alternate fallback frame."
                            )
                        _set_upload_overlay_status(
                            title="CENSUS REQUIRED",
                            status="ADDRESS EXTRACTION COMPLETE",
                            copy="Address extraction finished. Preparing Census batches from the rows with complete street, city, state, and ZIP data.",
                            progress=38,
                            logs=_upload_logs,
                        )

                        census_chunks = make_census_batch_chunks(census_stage_df, chunk_size=5000)
                        census_timeout_sec = 180
                        census_retries = 3
                        census_stall_warn_sec = 600
                        census_started_at = st.session_state.get('_census_batch_started_at')
                        if not isinstance(census_started_at, (int, float)):
                            census_started_at = time.time()
                            st.session_state['_census_batch_started_at'] = census_started_at

                        theoretical_max_wait = (
                            census_timeout_sec * census_retries
                            + sum(min(6, attempt * 2) for attempt in range(1, census_retries))
                        )
                        _push_upload_log(
                            f"Prepared {int(census_summary.get('rows_ready', 0) or 0):,} Census-ready rows across {len(census_chunks)} Census chunk(s)."
                        )
                        _push_upload_log(
                            "Census wait guidance: each POST waits up to "
                            f"{census_timeout_sec}s, total worst-case per chunk is about "
                            f"{format_wait_duration(theoretical_max_wait)}, and a chunk that still has not completed after "
                            f"{format_wait_duration(census_stall_warn_sec)} should be treated as stalled."
                        )
                        _set_upload_overlay_status(
                            title="CENSUS AUTOMATION",
                            status="SUBMITTING BATCHES",
                            copy=(
                                "Sending chunked address batches directly to the Census geocoder. "
                                f"Elapsed since Census submit started: {format_wait_duration(time.time() - census_started_at)}. "
                                f"Each attempt can wait up to {format_wait_duration(census_timeout_sec)}; a healthy worst-case per chunk is about {format_wait_duration(theoretical_max_wait)}. "
                                f"If the same chunk is still waiting after {format_wait_duration(census_stall_warn_sec)}, treat it as stalled and cancel/retry."
                            ),
                            progress=42,
                            logs=_upload_logs,
                        )

                        def _save_census_state_for_manual():
                            st.session_state['census_pending'] = True
                            st.session_state['census_source_signature'] = current_upload_signature
                            st.session_state['census_partial_calls_df'] = df_c_partial
                            st.session_state['census_original_df'] = census_original_df
                            st.session_state['census_summary'] = census_summary
                            _zip = make_census_batch_zip(census_chunks)
                            st.session_state['census_batch_zip_bytes'] = _zip
                            st.session_state['census_batch_zip_name'] = 'census_batches.zip'
                            _samp = make_sample_census_batch(census_stage_df)
                            if _samp:
                                st.session_state['census_sample_bytes'] = _samp['csv_bytes']
                                st.session_state['census_sample_name'] = _samp['filename']

                        census_result_parts = []
                        chunk_queue = list(census_chunks)
                        completed_chunks = 0
                        total_chunks = max(1, len(chunk_queue))
                        while chunk_queue:
                            chunk = chunk_queue.pop(0)
                            chunk_idx = completed_chunks + 1
                            _push_upload_log(
                                f"Submitting chunk {chunk_idx}/{total_chunks} with {chunk['rows']:,} rows to Census."
                            )
                            _set_upload_overlay_status(
                                title="CENSUS AUTOMATION",
                                status=f"SUBMITTING CHUNK {chunk_idx} OF {total_chunks}",
                                copy=(
                                    f"Waiting for the Census batch endpoint to return the geocoded CSV for chunk {chunk_idx} of {total_chunks}. "
                                    f"Elapsed since Census submit started: {format_wait_duration(time.time() - census_started_at)}. "
                                    f"If nothing returns after {format_wait_duration(census_stall_warn_sec)}, it is probably stalled."
                                ),
                                progress=42 + int(completed_chunks / max(1, total_chunks) * 34),
                                logs=_upload_logs,
                            )
                            def _submit_census_chunk():
                                try:
                                    return submit_census_batch_chunk(
                                        chunk['csv_bytes'],
                                        chunk['filename'],
                                        timeout=census_timeout_sec,
                                        retries=census_retries,
                                        attempt_logger=_push_upload_log,
                                    )
                                except TypeError as exc:
                                    if "unexpected keyword argument 'attempt_logger'" in str(exc):
                                        _push_upload_log(
                                            "Live Census module is still using the older submit_census_batch_chunk signature; "
                                            "retrying without per-attempt logs."
                                        )
                                        return submit_census_batch_chunk(
                                            chunk['csv_bytes'],
                                            chunk['filename'],
                                            timeout=census_timeout_sec,
                                            retries=census_retries,
                                        )
                                    raise

                            _census_pool = ThreadPoolExecutor(max_workers=1)
                            try:
                                _chunk_future = _census_pool.submit(_submit_census_chunk)
                                _chunk_wait_started_at = time.time()
                                _chunk_last_heartbeat_at = _chunk_wait_started_at
                                while True:
                                    try:
                                        chunk_result_df, _chunk_resp = _chunk_future.result(timeout=5)
                                        break
                                    except cf.TimeoutError:
                                        _chunk_elapsed = time.time() - _chunk_wait_started_at
                                        if _chunk_elapsed > census_stall_warn_sec:
                                            _push_upload_log(
                                                f"Chunk {chunk_idx}/{total_chunks} stalled after {format_wait_duration(_chunk_elapsed)}."
                                                " Switching to manual Census batch workflow."
                                            )
                                            _census_pool.shutdown(wait=False)
                                            _save_census_state_for_manual()
                                            _clear_upload_overlay()
                                            st.warning(
                                                "⚠️ The Census geocoder did not respond in time. "
                                                "Download the batch files below, submit them at "
                                                "geocoding.geo.census.gov/geocoder, and upload the returned CSVs here to continue."
                                            )
                                            st.rerun()
                                        if _chunk_elapsed - _chunk_last_heartbeat_at >= 15:
                                            _chunk_last_heartbeat_at = _chunk_elapsed
                                            _push_upload_log(
                                                f"Chunk {chunk_idx}/{total_chunks} is still waiting after {format_wait_duration(_chunk_elapsed)}."
                                            )
                                        _set_upload_overlay_status(
                                            title="CENSUS AUTOMATION",
                                            status=f"SUBMITTING CHUNK {chunk_idx} OF {total_chunks}",
                                            copy=(
                                                f"Waiting for the Census batch endpoint to return the geocoded CSV for chunk {chunk_idx} of {total_chunks}. "
                                                f"Elapsed since this chunk started: {format_wait_duration(_chunk_elapsed)}. "
                                                f"If the same chunk is still waiting after {format_wait_duration(census_stall_warn_sec)}, it is probably stalled."
                                            ),
                                            progress=min(
                                                76,
                                                42 + int(
                                                    min(_chunk_elapsed, census_stall_warn_sec)
                                                    / max(1, census_stall_warn_sec)
                                                    * 34
                                                ),
                                            ),
                                            logs=_upload_logs,
                                        )
                                        continue
                            except Exception as exc:
                                _census_pool.shutdown(wait=False)
                                if chunk['rows'] > 1000 and chunk.get('frame') is not None:
                                    _push_upload_log(
                                        f"Chunk {chunk_idx}/{total_chunks} failed: {exc}. Splitting into smaller batches and retrying."
                                    )
                                    split_frame = chunk['frame']
                                    mid = max(1, len(split_frame) // 2)
                                    left = split_frame.iloc[:mid].copy().reset_index(drop=True)
                                    right = split_frame.iloc[mid:].copy().reset_index(drop=True)
                                    retry_chunks = [
                                        build_census_chunk_payload(
                                            left,
                                            chunk_index=chunk['index'],
                                            filename=chunk['filename'].replace('.csv', '_a.csv'),
                                        ),
                                        build_census_chunk_payload(
                                            right,
                                            chunk_index=chunk['index'],
                                            filename=chunk['filename'].replace('.csv', '_b.csv'),
                                        ),
                                    ]
                                    chunk_queue = retry_chunks + chunk_queue
                                    total_chunks += 1
                                    _set_upload_overlay_status(
                                        title="CENSUS AUTOMATION",
                                        status=f"RETRYING CHUNK {chunk_idx}",
                                        copy="The Census endpoint rejected the larger batch. Splitting it into smaller chunks and retrying automatically.",
                                        progress=42 + int(completed_chunks / max(1, total_chunks) * 34),
                                        logs=_upload_logs,
                                    )
                                    continue

                                _push_upload_log(f"Chunk {chunk_idx}/{total_chunks} failed: {exc}")
                                _save_census_state_for_manual()
                                _clear_upload_overlay()
                                st.warning(
                                    f"⚠️ Automated Census geocoding failed on chunk {chunk_idx} of {total_chunks}. "
                                    "Download the batch files below, submit them at "
                                    "geocoding.geo.census.gov/geocoder, and upload the returned CSVs here to continue."
                                )
                                st.rerun()
                            else:
                                _census_pool.shutdown(wait=False)

                            _matched_rows = int((chunk_result_df['lat'].notna() & chunk_result_df['lon'].notna()).sum())
                            _push_upload_log(
                                f"Chunk {chunk_idx}/{total_chunks} completed. Returned {_matched_rows:,} rows with coordinates."
                            )
                            completed_chunks += 1
                            _set_upload_overlay_status(
                                title="CENSUS AUTOMATION",
                                status=f"CHUNK {chunk_idx} COMPLETE",
                                copy="Chunk returned successfully. Parsing and appending results before the next submission.",
                                progress=42 + int(completed_chunks / max(1, total_chunks) * 34),
                                logs=_upload_logs,
                            )
                            census_result_parts.append(chunk_result_df)

                        result_df = pd.concat(census_result_parts, ignore_index=True) if census_result_parts else pd.DataFrame()
                        intersection_result_df = st.session_state.get('census_intersection_result_df')
                        if intersection_result_df is not None and not intersection_result_df.empty:
                            result_df = pd.concat([result_df, intersection_result_df], ignore_index=True)
                            result_df = result_df.drop_duplicates(subset=['source_id'], keep='first')
                            _push_upload_log(
                                f"Added {len(intersection_result_df):,} intersection fallback result(s) to the merge set."
                            )
                        result_df = result_df.drop_duplicates(subset=['source_id'], keep='first') if not result_df.empty else result_df
                        _push_upload_log("All Census chunks returned. Merging coordinates back into the source calls file.")
                        _set_upload_overlay_status(
                            title="CENSUS AUTOMATION",
                            status="MERGING RESULTS",
                            copy=(
                                f"Combining all Census chunk responses and restoring coordinates into the original dataset. "
                                f"Total Census wait so far: {format_wait_duration(time.time() - census_started_at)}."
                            ),
                            progress=80,
                            logs=_upload_logs,
                        )

                        def _merge_census_outputs():
                            _merge_export_started_at = time.perf_counter()
                            merged_full_df, merged_ready_df, merge_summary = merge_census_results(
                                df_c_partial,
                                result_df,
                                validate_outputs=False,
                            )
                            _push_upload_log(
                                f"Census merge helper finished in {format_wait_duration(time.perf_counter() - _merge_export_started_at)} "
                                f"using {merge_summary.get('merge_backend', 'unknown')}."
                            )
                            if merged_ready_df is None or merged_ready_df.empty:
                                return merged_full_df, merged_ready_df, merge_summary, None
                            _corrected_export_started_at = time.perf_counter()
                            corrected_export_df = build_corrected_export_from_merged(merged_full_df)
                            corrected_csv = corrected_export_df.to_csv(index=False).encode('utf-8')
                            _push_upload_log(
                                f"Census corrected export built in {format_wait_duration(time.perf_counter() - _corrected_export_started_at)}."
                            )
                            return merged_full_df, merged_ready_df, merge_summary, corrected_csv

                        _push_upload_log("Merging Census coordinates back into the source calls file.")
                        _set_upload_overlay_status(
                            title="CENSUS AUTOMATION",
                            status="MERGING RESULTS",
                            copy=(
                                f"Combining all Census chunk responses and restoring coordinates into the original dataset. "
                                f"Elapsed since Census submit started: {format_wait_duration(time.time() - census_started_at)}."
                            ),
                            progress=80,
                            logs=_upload_logs,
                        )
                        merged_full_df, merged_ready_df, merge_summary, corrected_csv = _merge_census_outputs()

                        _push_upload_log("Census merge completed. Restoring coordinates into the working dataset.")

                        if merged_ready_df is None or merged_ready_df.empty:
                            _push_upload_log("Census returned no valid coordinates after chunk processing.")
                            _set_upload_overlay_status(
                                title="CENSUS ERROR",
                                status="NO VALID RESULTS",
                                copy="Census responded, but the returned data did not contain any usable coordinates.",
                                progress=84,
                                logs=_upload_logs,
                                error=True,
                            )
                            st.error("❌ Automated Census geocoding completed, but no valid coordinates were returned.")
                            st.stop()

                        st.session_state['census_corrected_bytes'] = corrected_csv
                        st.session_state['census_corrected_name'] = "cad_calls_census_corrected.csv"
                        st.session_state['census_conversion_summary'] = merge_summary
                        st.session_state['census_download_notice'] = True

                        df_c_full = merged_ready_df.reset_index(drop=True).copy()
                        if len(df_c_full) > 25000:
                            df_c = df_c_full.sample(25000, random_state=42).reset_index(drop=True)
                            st.toast(f"⚠️ Optimization modeled with {len(df_c):,} representative calls out of {len(df_c_full):,} geocoded incidents.")
                        else:
                            df_c = df_c_full.copy()

                        _push_upload_log(
                            f"Merged Census results. {int(merge_summary.get('rows_ready', len(df_c_full)) or len(df_c_full)):,} rows now have coordinates."
                        )
                        _set_upload_overlay_status(
                            title="CENSUS AUTOMATION",
                            status="GEOCODING COMPLETE",
                            copy=(
                                f"Coordinates restored. Finalizing station discovery and jurisdiction setup now. "
                                f"Total Census time: {format_wait_duration(time.time() - census_started_at)}."
                            ),
                            progress=88,
                            logs=_upload_logs,
                        )
                        census_auto_processed = True

                if census_auto_processed:
                    df_c_full = df_c_full.reset_index(drop=True).copy()
                else:
                    df_c_full = df_c.reset_index(drop=True).copy()

                if len(df_c_full) > 25000:
                    df_c = df_c_full.sample(25000, random_state=42).reset_index(drop=True)
                    st.toast(f"⚠️ Optimization modeled with {len(df_c):,} representative calls out of {len(df_c_full):,} total incidents.")
                else:
                    df_c = df_c_full.copy()

                st.session_state.update({
                    'total_original_calls': len(df_c_full),
                    'total_modeled_calls': len(df_c),
                })

                if station_file is not None:
                    _mark_upload_step("loading uploaded stations file")
                    _push_upload_log("Loading uploaded stations file.")
                    _set_upload_overlay_status(
                        title="UPLOAD PROCESSING",
                        status="READING STATIONS FILE",
                        copy="Reading the uploaded stations file and validating station coordinates.",
                        progress=91,
                        logs=_upload_logs,
                    )
                    with st.spinner("🔍 Reading stations file…"):
                        try:
                            df_s, osm_note = load_station_file(station_file)
                            st.session_state['stations_user_uploaded'] = True
                        except Exception as e:
                            df_s, osm_note = None, f"Failed: {e}"
                    if df_s is None or df_s.empty:
                        _clear_upload_overlay()
                        st.error(f"❌ Stations file error: {osm_note}")
                        st.stop()
                else:
                    _mark_upload_step("generating stations from calls")
                    _push_upload_log("No stations file provided. Building stations automatically from call data.")
                    _set_upload_overlay_status(
                        title="UPLOAD PROCESSING",
                        status="BUILDING STATIONS",
                        copy="No stations file was uploaded, so station candidates are being generated from the call data.",
                        progress=91,
                        logs=_upload_logs,
                    )
                    st.session_state['stations_user_uploaded'] = False
                    with st.spinner("🌐 No stations file detected — querying OpenStreetMap for police, fire & schools; this can take 10-20 seconds…"):
                        df_s, osm_note = generate_stations_from_calls(df_c)
                    if df_s is None or df_s.empty:
                        df_s = _make_random_stations(df_c, n=40)
                        osm_note = "⚠️ Could not reach any map source — using estimated station positions from call data."
                        st.warning(osm_note)
                    else:
                        st.toast(f"✅ {osm_note}")

                if len(df_s) > 100:
                    df_s = df_s.sample(100, random_state=42).reset_index(drop=True)

                _push_upload_log("Detecting jurisdiction from call locations.")
                _mark_upload_step("detecting jurisdiction from calls")
                _set_upload_overlay_status(
                    title="UPLOAD PROCESSING",
                    status="DETECTING JURISDICTION",
                    copy="Using the restored coordinates to identify the active city/state and resolve the deployment area.",
                    progress=95,
                    logs=_upload_logs,
                )
                with st.spinner(get_jurisdiction_message()):
                    detected_city, detected_state, detection_source = detect_location_from_calls(
                        df_c,
                        STATE_FIPS,
                        US_STATES_ABBR,
                        reverse_geocode_state,
                    )

                    if detected_city and detected_state:
                        st.session_state['active_city'] = str(detected_city).title()
                        st.session_state['active_state'] = detected_state
                        st.session_state['target_cities'] = [{"city": detected_city, "state": detected_state}]
                        st.session_state['location_detection_source'] = detection_source
                        st.toast(f"📍 Detected: {detected_city}, {detected_state}")
                    elif detected_state:
                        st.session_state['active_state'] = detected_state
                        st.session_state['location_detection_source'] = detection_source

                st.session_state['df_calls'] = df_c
                st.session_state['df_calls_full'] = df_c_full
                st.session_state['df_stations'] = df_s
                st.session_state['total_original_calls'] = len(df_c_full)
                st.session_state['total_modeled_calls'] = len(df_c)

                _push_upload_log("Resolving uploaded boundaries and final session state.")
                _mark_upload_step("resolving uploaded boundaries")
                _set_upload_overlay_status(
                    title="UPLOAD PROCESSING",
                    status="FINALIZING DATASET",
                    copy="Saving the restored calls dataset, resolving boundaries, and opening the stations workflow.",
                    progress=98,
                    logs=_upload_logs,
                )
                with st.spinner(get_jurisdiction_message()):
                    resolve_uploaded_boundaries(
                        st,
                        st.session_state,
                        df_c,
                        df_c_full,
                        STATE_FIPS,
                        find_jurisdictions_by_coordinates,
                        _select_best_boundary_for_calls,
                        save_boundary_gdf,
                    )

                try:
                    _refresh_reference_population(st.session_state)
                except Exception:
                    pass

                st.session_state['data_source'] = 'cad_upload'
                st.session_state['demo_mode_used'] = False
                st.session_state['sim_mode_used'] = False
                st.session_state['map_build_logged'] = False
                st.session_state['csvs_ready'] = True
                _push_upload_log("Upload workflow complete. Opening the stations page.")
                _set_upload_overlay_status(
                    title="UPLOAD COMPLETE",
                    status="OPENING STATIONS PAGE",
                    copy="The corrected calls dataset is ready. Transitioning into the stations workflow now.",
                    progress=100,
                    logs=_upload_logs,
                )
                st.rerun()
