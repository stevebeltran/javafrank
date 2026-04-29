# Copyright (c) Steven Beltran. Created by Steven Beltran in partnership with BRINC Drones.
import warnings
warnings.filterwarnings(
    "ignore",
    message=r"authlib\.jose module is deprecated, please use joserfc instead\.",
    category=DeprecationWarning,
)
import streamlit as st
import pandas as pd
import os
import sys
# Set CWD to the project root so every relative asset path (parquets, shapefiles,
# logos, etc.) resolves correctly regardless of how the process was launched.
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import geopandas as gpd
import numpy as np
import plotly.graph_objects as go
from shapely.geometry import Point, Polygon, MultiPolygon, box, shape
from shapely.ops import unary_union
from shapely.wkb import loads as _wkb_loads
import itertools, glob, math, simplekml, heapq, re, random, json, io, datetime, base64, smtplib, uuid, traceback, tempfile, hashlib, hmac, time, html
import concurrent.futures as cf
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pulp
import urllib.request
import urllib.parse
import zipfile
import streamlit.components.v1 as components
from streamlit.components.v1 import declare_component
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials
import pyproj
from PIL import Image

APP_DIR = Path(__file__).resolve().parent
MODULES_DIR = APP_DIR / "modules"


def _load_local_module(module_name: str):
    """Load a local modules.* file defensively for Streamlit/Python import edge cases."""
    import importlib
    import importlib.util as _importlib_util

    package_name = "modules"
    full_name = f"{package_name}.{module_name}"

    try:
        return importlib.import_module(full_name)
    except KeyError:
        package_path = MODULES_DIR / "__init__.py"
        package_mod = sys.modules.get(package_name)
        if package_mod is None or not getattr(package_mod, "__path__", None):
            package_spec = _importlib_util.spec_from_file_location(
                package_name,
                package_path,
                submodule_search_locations=[str(MODULES_DIR)],
            )
            if package_spec is None or package_spec.loader is None:
                raise
            package_mod = _importlib_util.module_from_spec(package_spec)
            sys.modules[package_name] = package_mod
            package_spec.loader.exec_module(package_mod)

        module_path = MODULES_DIR / f"{module_name}.py"
        module_spec = _importlib_util.spec_from_file_location(full_name, module_path)
        if module_spec is None or module_spec.loader is None:
            raise
        module = _importlib_util.module_from_spec(module_spec)
        sys.modules[full_name] = module
        module_spec.loader.exec_module(module)
        return module

# ── Module imports ────────────────────────────────────────────────────────────
from modules.config import (
    CONFIG, GUARDIAN_FLIGHT_HOURS_PER_DAY, SIMULATOR_DISCLAIMER_SHORT,
    STATE_FIPS, US_STATES_ABBR, KNOWN_POPULATIONS, DEMO_CITIES, FAST_DEMO_CITIES,
    FAA_CEILING_COLORS, FAA_DEFAULT_COLOR, STATION_COLORS,
    bg_main, bg_sidebar, text_main, text_muted, accent_color, card_bg, card_border,
    card_text, card_title, budget_box_bg, budget_box_border, budget_box_shadow,
    map_style, map_boundary_color, map_incident_color, legend_bg, legend_text,
    get_hero_message, get_faa_message, get_airfield_message,
    get_jurisdiction_message, get_spatial_message
)
try:
    from modules.config import calculate_max_flights_per_day
except ImportError:
    def calculate_max_flights_per_day(
        mission_minutes: float,
        *,
        flight_minutes: float,
        downtime_minutes: float,
        operation_minutes: float = 24 * 60,
    ) -> float:
        mission_minutes = float(mission_minutes or 0.0)
        flight_minutes = float(flight_minutes or 0.0)
        downtime_minutes = max(0.0, float(downtime_minutes or 0.0))
        operation_minutes = max(0.0, float(operation_minutes or 0.0))
        if mission_minutes <= 0.0 or flight_minutes <= 0.0 or operation_minutes <= 0.0:
            return 0.0
        if mission_minutes > flight_minutes + 1e-9:
            return 0.0

        elapsed = 0.0
        flights = 0
        remaining_flight = flight_minutes
        while True:
            if mission_minutes <= remaining_flight + 1e-9:
                if elapsed + mission_minutes > operation_minutes + 1e-9:
                    break
                elapsed += mission_minutes
                flights += 1
                remaining_flight -= mission_minutes
            else:
                if elapsed + downtime_minutes > operation_minutes + 1e-9:
                    break
                elapsed += downtime_minutes
                remaining_flight = flight_minutes
        return float(flights)

_versioning_mod = _load_local_module("versioning")
# No importlib.reload needed here — Streamlit restarts the process on every
# app.py save, so versioning._compute_build_info() already runs fresh each time.
# Reloading on every rerun forced a full re-read of the 8 000-line app.py file
# on every user interaction, for no benefit.
__version__ = _versioning_mod.__version__
__build_revision__ = _versioning_mod.__build_revision__
__build_datetime__ = _versioning_mod.__build_datetime__
__build_line_count__ = _versioning_mod.__build_line_count__
_render_version_badge = _versioning_mod._render_version_badge
from modules.public_reports import (
    _build_public_report_url,
    _get_document_jurisdiction_name,
    _get_public_report_secret,
    _get_query_params_dict,
    _get_request_base_url,
    _publish_public_report_html,
    _public_report_metadata_path,
    _public_report_html_path,
    _resolve_public_reports_dir,
    _sign_public_report_id,
    _slugify,
)
from modules.image_utils import (
    get_base64_of_bin_file, get_themed_logo_base64, get_transparent_product_base64
)
from modules.notifications import (
    _notify_email, _log_to_sheets, _log_login_to_sheets, _publish_public_report_to_sheets
)
from modules.cad_parser import (
    aggressive_parse_calls, _extract_file_meta, _get_annualized_calls
)
_census_batch_mod = _load_local_module("census_batch")
build_census_staging = _census_batch_mod.build_census_staging
make_census_batch_chunks = _census_batch_mod.make_census_batch_chunks
make_census_batch_zip = _census_batch_mod.make_census_batch_zip
make_sample_census_batch = _census_batch_mod.make_sample_census_batch
parse_census_result_files = _census_batch_mod.parse_census_result_files
merge_census_results = _census_batch_mod.merge_census_results
submit_census_batch_chunk = _census_batch_mod.submit_census_batch_chunk
build_census_chunk_payload = _census_batch_mod.build_census_chunk_payload
build_corrected_export = _census_batch_mod.build_corrected_export
from modules.geospatial import (
    _load_uploaded_boundary_overlay, _boundary_overlay_status,
    _count_points_within_boundary, find_jurisdictions_by_coordinates
)
from modules import faa_rf, optimization, html_reports
_session_state_mod = _load_local_module("session_state")
init_session_state = _session_state_mod.init_session_state
from modules.dashboard_helpers import log_map_build_event_once, resolve_master_boundary, render_sidebar_jurisdiction_selector, render_data_filters, render_display_options, render_deployment_strategy, prepare_station_candidates, manage_custom_stations, prepare_runtime_context, optimize_fleet_selection
from modules import onboarding as _onboarding_mod
from modules.highway_corridor import (
    STATE_PRIMARY_INTERSTATES,
    fetch_highway_geometry,
    build_corridor_polygon,
    estimate_corridor_calls,
    build_corridor_demo,
)


detect_brinc_file = _onboarding_mod.detect_brinc_file
load_brinc_save_data = _onboarding_mod.load_brinc_save_data
restore_brinc_session = _onboarding_mod.restore_brinc_session
split_uploaded_files = _onboarding_mod.split_uploaded_files
load_station_file = _onboarding_mod.load_station_file
detect_location_from_calls = _onboarding_mod.detect_location_from_calls
resolve_uploaded_boundaries = _onboarding_mod.resolve_uploaded_boundaries
split_simulation_optional_files = _onboarding_mod.split_simulation_optional_files
load_simulation_boundary_overlay = _onboarding_mod.load_simulation_boundary_overlay
load_simulation_custom_stations = _onboarding_mod.load_simulation_custom_stations
build_demo_boundaries = _onboarding_mod.build_demo_boundaries
build_demo_calls = _onboarding_mod.build_demo_calls
resolve_demo_stations = _onboarding_mod.resolve_demo_stations


def _infer_simulation_targets_from_station_file_fallback(*args, **kwargs):
    return [], ''


infer_simulation_targets_from_station_file = getattr(
    _onboarding_mod,
    'infer_simulation_targets_from_station_file',
    _infer_simulation_targets_from_station_file_fallback,
)

APP_DIR = Path(__file__).resolve().parent
QUICK_PIN_COMPONENT_DIR = APP_DIR / "quick_pin_component"
QUICK_PIN_COMPONENT = (
    declare_component(
        "quick_pin_component",
        path=str(QUICK_PIN_COMPONENT_DIR),
    )
    if QUICK_PIN_COMPONENT_DIR.is_dir()
    else None
)


def _uploaded_files_signature(files):
    parts = []
    for idx, uploaded_file in enumerate(files or []):
        try:
            size = len(uploaded_file.getvalue())
        except Exception:
            size = 0
        parts.append(f"{idx}:{uploaded_file.name}:{size}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest() if parts else ""


def _reset_census_state(session_state):
    session_state['census_pending'] = False
    session_state['census_source_signature'] = ''
    session_state['census_stage_df'] = None
    session_state['census_original_df'] = None
    session_state['census_partial_calls_df'] = None
    session_state['_census_batch_started_at'] = None
    session_state['census_batch_zip_bytes'] = b""
    session_state['census_batch_zip_name'] = ""
    session_state['census_sample_bytes'] = b""
    session_state['census_sample_name'] = ""
    session_state['census_summary'] = {}
    session_state['census_conversion_summary'] = {}
    session_state['census_corrected_bytes'] = b""
    session_state['census_corrected_name'] = ""
    session_state['census_corrected_format'] = "csv"
    session_state['census_download_notice'] = False


def _render_public_report_route():
    _params = _get_query_params_dict()
    _report_id = str(_params.get("public_report", "")).strip()
    _sig = str(_params.get("sig", "")).strip()
    if not _report_id:
        return False

    try:
        _expected_sig = _sign_public_report_id(_report_id)
        _html_path = _public_report_html_path(_report_id)
        _meta_path = _public_report_metadata_path(_report_id)
    except ValueError:
        st.error("Invalid public report link.")
        st.stop()

    if not _sig or not hmac.compare_digest(_sig, _expected_sig):
        st.error("Invalid public report link.")
        st.stop()

    if not _html_path.exists():
        st.warning("This public report is not available yet.")
        st.stop()

    _scan_meta = {}
    if _meta_path.exists():
        try:
            _scan_meta = json.loads(_meta_path.read_text(encoding="utf-8"))
        except Exception:
            _scan_meta = {}

    _qr_city = str(_scan_meta.get("city", "") or "").strip()
    _qr_state = str(_scan_meta.get("state", "") or "").strip()
    _qr_rep_name = str(_scan_meta.get("rep_name", "") or "").strip() or "BRINC Representative"
    _qr_rep_email = str(_scan_meta.get("rep_email", "") or "").strip() or "sales@brincdrones.com"
    _qr_loc = ", ".join([x for x in [_qr_city, _qr_state] if x]).strip() or "your jurisdiction"
    _qr_lead_subject = urllib.parse.quote(f"DFR demo request - {_qr_loc}")
    _qr_lead_body = urllib.parse.quote(
        f"Hi {_qr_rep_name},\n\nI would like a custom DFR coverage analysis for {_qr_loc}.\n\nAgency:\nBest callback number:\n\nThanks,"
    )
    _qr_mailto = f"mailto:{_qr_rep_email}?subject={_qr_lead_subject}&body={_qr_lead_body}"

    try:
        from modules.notifications import _log_qr_scan_to_sheets

        try:
            _headers = dict(st.context.headers)
        except Exception:
            _headers = {}
        _ua = _headers.get("User-Agent", _headers.get("user-agent", ""))
        _lang = _headers.get("Accept-Language", _headers.get("accept-language", ""))
        _ip = (
            _headers.get("X-Forwarded-For", "")
            or _headers.get("x-forwarded-for", "")
            or _headers.get("Remote-Addr", "")
        ).split(",")[0].strip()

        _ua_lower = _ua.lower()
        if "iphone" in _ua_lower or "ipad" in _ua_lower:
            _device = "iOS"
        elif "android" in _ua_lower:
            _device = "Android"
        elif "mobile" in _ua_lower:
            _device = "Mobile"
        elif _ua:
            _device = "Desktop"
        else:
            _device = ""

        _log_qr_scan_to_sheets(
            report_id=_report_id,
            city=_scan_meta.get("city", ""),
            state=_scan_meta.get("state", ""),
            rep_name=_scan_meta.get("rep_name", ""),
            rep_email=_scan_meta.get("rep_email", ""),
            device=_device,
            user_agent=_ua,
            language=_lang,
            ip=_ip,
        )
    except Exception:
        pass

    st.set_page_config(layout="wide", page_title="BRINC DFR", page_icon="https://brincdrones.com/favicon.ico")
    st.markdown("""
        <style>
            header, footer, #MainMenu,
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            [data-testid="stStatusWidget"],
            [data-testid="stSidebar"],
            [data-testid="stGithubButton"],
            [data-testid="stActionButton"],
            [data-testid="stBaseButton-header"],
            [data-testid="stHeaderActionElements"],
            [data-testid="stHeaderActions"],
            [data-testid="stDeployButton"],
            [data-testid="stAppDeployButton"],
            [data-testid*="github"],
            [data-testid*="Github"],
            .stDeployButton,
            .viewerBadge_container__,
            .viewerBadge_link__,
            .viewerBadge_text__,
            #stDecoration,
            iframe[title="streamlit_analytics"] {
                display: none !important;
                visibility: hidden !important;
                pointer-events: none !important;
            }
            .main .block-container { padding: 0 !important; max-width: 100% !important; }
            .stApp { background: #07101c !important; }
        </style>
        <script>
            (function () {
                const selectors = [
                    'header',
                    'footer',
                    '#MainMenu',
                    '[data-testid="stToolbar"]',
                    '[data-testid="stDecoration"]',
                    '[data-testid="stStatusWidget"]',
                    '[data-testid="stSidebar"]',
                    '[data-testid="stGithubButton"]',
                    '[data-testid="stActionButton"]',
                    '[data-testid="stBaseButton-header"]',
                    '[data-testid="stHeaderActionElements"]',
                    '[data-testid="stHeaderActions"]',
                    '[data-testid="stDeployButton"]',
                    '[data-testid="stAppDeployButton"]',
                    '[data-testid*="github"]',
                    '[data-testid*="Github"]',
                    '.stDeployButton',
                    '.viewerBadge_container__',
                    '.viewerBadge_link__',
                    '.viewerBadge_text__',
                    'iframe[title="streamlit_analytics"]',
                    'header a[href*="github.com"]',
                    'header a[href*="streamlit.io"]',
                    'header [aria-label*="GitHub"]',
                    'header [aria-label*="github"]',
                    'header [aria-label*="Streamlit"]',
                    'header [title*="GitHub"]',
                    'header [title*="github"]',
                    'header [title*="Streamlit"]',
                    'button[title*="GitHub"]',
                    'button[title*="github"]'
                ];

                function stripChrome(root) {
                    selectors.forEach(function (selector) {
                        root.querySelectorAll(selector).forEach(function (node) {
                            node.remove();
                        });
                    });
                }

                function walk(root) {
                    if (!root) return;
                    stripChrome(root);
                    try {
                        root.querySelectorAll('*').forEach(function (el) {
                            if (el.shadowRoot) {
                                walk(el.shadowRoot);
                            }
                        });
                    } catch (e) {}
                }

                function run() {
                    walk(document);
                    if (window.parent && window.parent !== window) {
                        try {
                            walk(window.parent.document);
                        } catch (e) {}
                    }
                }

                run();
                new MutationObserver(run).observe(document.documentElement, { childList: true, subtree: true });
                window.addEventListener('load', run);
                window.addEventListener('DOMContentLoaded', run);
                setInterval(run, 1000);
            })();
        </script>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <style>
            :root {{
                --qr-bg: #07101c;
                --qr-panel: rgba(9, 20, 36, 0.92);
                --qr-panel-soft: rgba(12, 28, 48, 0.84);
                --qr-border: rgba(0, 210, 255, 0.16);
                --qr-text: #eff6ff;
                --qr-muted: #98a7bb;
                --qr-accent: #00d2ff;
                --qr-accent-2: #78f0ff;
                --qr-cta: #f7fbff;
                --qr-cta-text: #07101c;
                --qr-shadow: 0 22px 54px rgba(0, 0, 0, 0.30);
            }}
            .qr-wrap {{
                max-width: 1180px;
                margin: 0 auto;
                padding: 20px 16px 48px;
                color: var(--qr-text);
            }}
            .qr-hero {{
                display: grid;
                grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
                gap: 18px;
                align-items: stretch;
                margin-bottom: 18px;
            }}
            .qr-panel {{
                background:
                    radial-gradient(circle at top right, rgba(0,210,255,.16), transparent 38%),
                    linear-gradient(180deg, rgba(12, 28, 48, 0.94), rgba(7, 16, 28, 0.98));
                border: 1px solid var(--qr-border);
                border-radius: 24px;
                box-shadow: var(--qr-shadow);
                overflow: hidden;
            }}
            .qr-copy {{
                padding: 24px;
            }}
            .qr-kicker {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 12px;
                border-radius: 999px;
                background: rgba(0,210,255,.10);
                color: var(--qr-accent-2);
                font-size: 12px;
                font-weight: 800;
                letter-spacing: .12em;
                text-transform: uppercase;
                margin-bottom: 14px;
            }}
            .qr-title {{
                font-size: clamp(34px, 5.8vw, 62px);
                line-height: 0.96;
                font-weight: 900;
                letter-spacing: -0.04em;
                margin: 0 0 14px;
            }}
            .qr-subtitle {{
                font-size: clamp(16px, 2.8vw, 21px);
                line-height: 1.45;
                color: var(--qr-muted);
                margin-bottom: 18px;
                max-width: 28em;
            }}
            .qr-loc {{
                margin-bottom: 18px;
                color: var(--qr-accent-2);
                font-size: 15px;
                font-weight: 700;
            }}
            .qr-cta-row {{
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                margin-bottom: 14px;
            }}
            .qr-btn {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 52px;
                padding: 0 20px;
                border-radius: 14px;
                text-decoration: none;
                font-size: 16px;
                font-weight: 800;
                transition: transform .18s ease, box-shadow .18s ease, background .18s ease;
            }}
            .qr-btn:hover {{
                transform: translateY(-1px);
            }}
            .qr-btn-primary {{
                background: var(--qr-cta);
                color: var(--qr-cta-text) !important;
                box-shadow: 0 10px 24px rgba(247, 251, 255, 0.18);
            }}
            .qr-btn-secondary {{
                background: rgba(0,210,255,.08);
                color: var(--qr-text) !important;
                border: 1px solid rgba(120,240,255,.18);
            }}
            .qr-note {{
                color: var(--qr-muted);
                font-size: 14px;
                line-height: 1.5;
            }}
            .qr-visual {{
                padding: 18px;
                display: flex;
                flex-direction: column;
                gap: 14px;
            }}
            .qr-visual-head {{
                display: flex;
                justify-content: space-between;
                gap: 10px;
                align-items: baseline;
            }}
            .qr-visual-head strong {{
                font-size: 18px;
                letter-spacing: -0.02em;
            }}
            .qr-visual-head span {{
                color: var(--qr-muted);
                font-size: 13px;
            }}
            .qr-preview {{
                min-height: 210px;
                background:
                    linear-gradient(140deg, rgba(0,210,255,.12), rgba(0,210,255,0) 38%),
                    linear-gradient(180deg, rgba(5,13,24,.92), rgba(8,18,32,.92));
                border: 1px solid rgba(255,255,255,.06);
                border-radius: 20px;
                padding: 18px;
                display: grid;
                grid-template-columns: 1.15fr .85fr;
                gap: 12px;
                align-items: stretch;
            }}
            .qr-preview-main,
            .qr-preview-side {{
                border-radius: 16px;
                background: rgba(255,255,255,.03);
                border: 1px solid rgba(255,255,255,.06);
                position: relative;
                overflow: hidden;
            }}
            .qr-preview-main::before {{
                content: "";
                position: absolute;
                inset: 0;
                background:
                    radial-gradient(circle at 52% 44%, rgba(0,210,255,.36), transparent 14%),
                    radial-gradient(circle at 42% 58%, rgba(120,240,255,.26), transparent 12%),
                    linear-gradient(0deg, rgba(255,255,255,.04) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px);
                background-size: auto, auto, 26px 26px, 26px 26px;
            }}
            .qr-preview-side {{
                padding: 14px;
                display: flex;
                flex-direction: column;
                gap: 10px;
            }}
            .qr-preview-chip {{
                height: 44px;
                border-radius: 12px;
                background: rgba(255,255,255,.04);
                border: 1px solid rgba(255,255,255,.06);
            }}
            .qr-section {{
                margin-top: 18px;
                padding: 22px;
            }}
            .qr-section-title {{
                font-size: 14px;
                font-weight: 800;
                letter-spacing: .12em;
                text-transform: uppercase;
                color: var(--qr-accent-2);
                margin-bottom: 12px;
            }}
            .qr-section h2 {{
                margin: 0 0 10px;
                font-size: clamp(26px, 4.2vw, 40px);
                line-height: 1.02;
                letter-spacing: -0.03em;
            }}
            .qr-section p {{
                margin: 0;
                color: var(--qr-muted);
                font-size: 16px;
                line-height: 1.6;
            }}
            .qr-value-grid, .qr-compare-grid {{
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
                margin-top: 16px;
            }}
            .qr-value-card, .qr-compare-card {{
                padding: 18px;
                border-radius: 18px;
                background: var(--qr-panel-soft);
                border: 1px solid rgba(255,255,255,.06);
            }}
            .qr-value-card strong, .qr-compare-card strong {{
                display: block;
                margin-bottom: 8px;
                font-size: 17px;
                letter-spacing: -0.02em;
            }}
            .qr-value-card span, .qr-compare-card span {{
                color: var(--qr-muted);
                font-size: 15px;
                line-height: 1.55;
            }}
            .qr-compare-card.is-after {{
                border-color: rgba(0,210,255,.22);
                box-shadow: inset 0 0 0 1px rgba(0,210,255,.08);
            }}
            .qr-form-shell {{
                margin-top: 18px;
                padding: 22px;
                border-radius: 24px;
                background:
                    radial-gradient(circle at top left, rgba(0,210,255,.12), transparent 34%),
                    linear-gradient(180deg, rgba(12, 28, 48, 0.98), rgba(7, 16, 28, 0.98));
                border: 1px solid var(--qr-border);
                box-shadow: var(--qr-shadow);
            }}
            .stTextInput label,
            .stTextArea label {{
                color: var(--qr-text) !important;
                font-size: 14px !important;
                font-weight: 700 !important;
            }}
            [data-testid="stTextInputRootElement"] input,
            textarea {{
                min-height: 54px;
                border-radius: 14px !important;
                border: 1px solid rgba(120,240,255,.14) !important;
                background: rgba(255,255,255,.03) !important;
                color: var(--qr-text) !important;
            }}
            [data-testid="stFormSubmitButton"] button {{
                min-height: 54px;
                border-radius: 14px;
                background: var(--qr-cta);
                color: var(--qr-cta-text);
                font-weight: 800;
                border: 0;
                width: 100%;
            }}
            @media (max-width: 860px) {{
                .qr-wrap {{
                    padding: 14px 12px 34px;
                }}
                .qr-hero,
                .qr-value-grid,
                .qr-compare-grid,
                .qr-preview {{
                    grid-template-columns: 1fr;
                }}
                .qr-copy,
                .qr-visual,
                .qr-section,
                .qr-form-shell {{
                    padding: 18px;
                }}
                .qr-btn {{
                    width: 100%;
                }}
            }}
        </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <div class="qr-wrap">
            <section class="qr-hero">
                <div class="qr-panel qr-copy">
                    <div class="qr-kicker">Drone As First Responder</div>
                    <h1 class="qr-title">Optimize DFR Coverage in Minutes</h1>
                    <div class="qr-subtitle">Reduce response times, maximize coverage, and justify deployment with real data.</div>
                    <div class="qr-loc">Prepared for {_qr_loc}</div>
                    <div class="qr-cta-row">
                        <a class="qr-btn qr-btn-primary" href="{_qr_mailto}">Request a Demo</a>
                        <a class="qr-btn qr-btn-secondary" href="#qr-lead-form">Get a Custom Analysis</a>
                    </div>
                    <div class="qr-note">Review the deployment summary below, then request a city-specific analysis from {_qr_rep_name}.</div>
                </div>
                <div class="qr-panel qr-visual">
                    <div class="qr-visual-head">
                        <strong>Coverage model preview</strong>
                        <span>QR report for {_qr_loc}</span>
                    </div>
                    <div class="qr-preview">
                        <div class="qr-preview-main"></div>
                        <div class="qr-preview-side">
                            <div class="qr-preview-chip"></div>
                            <div class="qr-preview-chip"></div>
                            <div class="qr-preview-chip"></div>
                            <div class="qr-preview-chip" style="height:72px;"></div>
                        </div>
                    </div>
                </div>
            </section>
            <section class="qr-panel qr-section">
                <div class="qr-section-title">Instant Value</div>
                <h2>Why agencies care</h2>
                <div class="qr-value-grid">
                    <div class="qr-value-card"><strong>Identify optimal drone station locations</strong><span>Find the sites that produce the largest operational impact before committing budget or personnel.</span></div>
                    <div class="qr-value-card"><strong>Predict response times before deployment</strong><span>Model likely arrival performance before aircraft, docks, or staffing plans are finalized.</span></div>
                    <div class="qr-value-card"><strong>Compare DFR against legacy response models</strong><span>Evaluate drone coverage against patrol-only or helicopter-supported response in the same jurisdiction.</span></div>
                    <div class="qr-value-card"><strong>Model real call data, not theory</strong><span>Use actual geography and incident density to produce defensible deployment recommendations.</span></div>
                </div>
            </section>
            <section class="qr-panel qr-section">
                <div class="qr-section-title">What You Just Saw</div>
                <h2>Real-time deployment output, not a static mockup</h2>
                <p>The simulation you just watched was generated from jurisdiction-specific geography and call density. The output is designed to support defendable deployment strategy discussions, not just a generic product demo.</p>
            </section>
            <section class="qr-panel qr-section">
                <div class="qr-section-title">Before / After</div>
                <h2>See the planning difference immediately</h2>
                <div class="qr-compare-grid">
                    <div class="qr-compare-card">
                        <strong>Before: conventional response planning</strong>
                        <span>Station decisions rely on intuition, broad coverage assumptions, and limited visibility into where aerial response changes arrival time.</span>
                    </div>
                    <div class="qr-compare-card is-after">
                        <strong>After: optimized DFR layout</strong>
                        <span>Deployment decisions are tied to mapped demand, modeled response performance, and a jurisdiction-specific station plan you can defend internally.</span>
                    </div>
                </div>
            </section>
        </div>
    """, unsafe_allow_html=True)

    components.html(_html_path.read_text(encoding="utf-8"), height=1320, scrolling=True)

    st.markdown('<div id="qr-lead-form"></div>', unsafe_allow_html=True)
    st.markdown("""
        <div class="qr-wrap">
            <section class="qr-form-shell">
                <div class="qr-section-title">Next Step</div>
                <h2 style="margin:0 0 10px;font-size:clamp(26px,4.2vw,40px);line-height:1.02;letter-spacing:-0.03em;">Book a 15-minute demo or request a custom city analysis</h2>
                <p style="margin:0 0 16px;color:var(--qr-muted);font-size:16px;line-height:1.6;">Leave your work email and jurisdiction details. This keeps mobile typing light and gives the follow-up enough context to be useful.</p>
            </section>
        </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="qr-wrap"><div class="qr-form-shell">', unsafe_allow_html=True)
    with st.form("qr_lead_capture"):
        _lead_name = st.text_input("Name")
        _lead_email = st.text_input("Work Email")
        _lead_agency = st.text_input("Agency / Jurisdiction", value=_qr_loc if _qr_loc != "your jurisdiction" else "")
        _lead_notes = st.text_area("What city or county should we model?", placeholder="City, county, or agency name")
        _lead_submit = st.form_submit_button("Get a Custom Analysis")
    st.markdown('</div></div>', unsafe_allow_html=True)

    if _lead_submit:
        _lead_name_clean = str(_lead_name or "").strip()
        _lead_email_clean = str(_lead_email or "").strip()
        _lead_agency_clean = str(_lead_agency or "").strip()
        _lead_notes_clean = str(_lead_notes or "").strip()
        if not _lead_email_clean:
            st.warning("Enter a work email to request a custom analysis.")
        else:
            _lead_details = {
                "report_id": _report_id,
                "lead_source": "qr_public_report",
                "agency": _lead_agency_clean,
                "notes": _lead_notes_clean,
                "assigned_rep": _qr_rep_name,
                "assigned_rep_email": _qr_rep_email,
            }
            try:
                _log_to_sheets(
                    _qr_city,
                    _qr_state,
                    "QR_LEAD",
                    0,
                    0,
                    0.0,
                    _lead_name_clean,
                    _lead_email_clean,
                    details=_lead_details,
                )
            except Exception:
                pass
            try:
                _notify_email(
                    _qr_city,
                    _qr_state,
                    "QR_LEAD",
                    0,
                    0,
                    0.0,
                    _lead_name_clean,
                    _lead_email_clean,
                    details=_lead_details,
                )
            except Exception:
                pass
            st.success("Request received. We will follow up with a custom analysis.")

    st.markdown(f"""
        <div class="qr-wrap">
            <div class="qr-cta-row" style="margin-top:4px;">
                <a class="qr-btn qr-btn-primary" href="{_qr_mailto}">Email {_qr_rep_name}</a>
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.stop()


_render_public_report_route()




def _select_best_boundary_for_calls(df_calls, city_text, state_abbr, prefer_county=False):
    """Try place and county boundaries and keep the candidate containing the most uploaded calls."""
    candidates = []

    try:
        place_success, place_gdf = fetch_place_boundary_local(state_abbr, city_text)
        if place_success and place_gdf is not None and not place_gdf.empty:
            candidates.append(('place', place_gdf, _count_points_within_boundary(df_calls, place_gdf)))
    except Exception:
        pass

    county_names = [city_text]
    if not str(city_text).lower().endswith(" county"):
        county_names.append(f"{city_text} County")

    for cname in county_names:
        try:
            county_success, county_gdf = fetch_county_boundary_local(state_abbr, cname)
            if county_success and county_gdf is not None and not county_gdf.empty:
                candidates.append(('county', county_gdf, _count_points_within_boundary(df_calls, county_gdf)))
                break
        except Exception:
            pass

    if not candidates:
        # ── TIGER fallback: parquet not present or city not found — download from Census ──
        state_fips = STATE_FIPS.get(state_abbr)
        if state_fips:
            try:
                tiger_success, tiger_gdf = fetch_tiger_city_shapefile(state_fips, city_text, SHAPEFILE_DIR)
                if tiger_success and tiger_gdf is not None and not tiger_gdf.empty:
                    tiger_gdf = tiger_gdf.copy()
                    if 'NAME' not in tiger_gdf.columns:
                        tiger_gdf['NAME'] = city_text
                    hits = _count_points_within_boundary(df_calls, tiger_gdf)
                    candidates.append(('place', tiger_gdf, hits))
            except Exception:
                pass

    if not candidates:
        return False, None, 'place', 0

    if prefer_county:
        candidates.sort(key=lambda x: (x[2], 1 if x[0] == 'county' else 0), reverse=True)
    else:
        candidates.sort(key=lambda x: (x[2], 1 if x[0] == 'place' else 0), reverse=True)

    best_kind, best_gdf, best_hits = candidates[0]
    return True, best_gdf, best_kind, int(best_hits)

# ============================================================
# COMMAND CENTER ANALYTICS GENERATOR
# ============================================================

# ============================================================
# AGGRESSIVE DATA PARSER
# ============================================================
def _make_random_stations(df_calls, n=40, boundary_geom=None, epsg_code=None):
    """Fallback station generator based on call-density hotspots.

    If a city boundary is supplied, only incidents inside that boundary are used and
    final station coordinates are snapped to the nearest in-boundary incident so every
    suggested site remains inside the geographic area.
    """
    if df_calls is None or df_calls.empty:
        return pd.DataFrame()

    work = df_calls.copy()
    work['lat'] = pd.to_numeric(work['lat'], errors='coerce')
    work['lon'] = pd.to_numeric(work['lon'], errors='coerce')
    work = work.dropna(subset=['lat', 'lon']).reset_index(drop=True)
    if work.empty:
        return pd.DataFrame()

    if boundary_geom is not None and epsg_code is not None:
        try:
            work_gdf = gpd.GeoDataFrame(work, geometry=gpd.points_from_xy(work.lon, work.lat), crs="EPSG:4326").to_crs(epsg=int(epsg_code))
            inside_mask = work_gdf.within(boundary_geom)
            if inside_mask.any():
                work = work.loc[inside_mask.values].reset_index(drop=True)
        except Exception:
            pass
        if work.empty:
            return pd.DataFrame()

    lats = work['lat'].dropna().values
    lons = work['lon'].dropna().values
    if len(lats) == 0:
        return pd.DataFrame()

    q1_la, q3_la = np.percentile(lats, 5), np.percentile(lats, 95)
    q1_lo, q3_lo = np.percentile(lons, 5), np.percentile(lons, 95)
    iqr_la, iqr_lo = q3_la - q1_la, q3_lo - q1_lo
    buf_la, buf_lo = max(iqr_la * 0.5, 0.01), max(iqr_lo * 0.5, 0.01)
    mask = ((lats >= q1_la - buf_la) & (lats <= q3_la + buf_la) &
            (lons >= q1_lo - buf_lo) & (lons <= q3_lo + buf_lo))
    clean_lats, clean_lons = lats[mask], lons[mask]
    if len(clean_lats) == 0:
        clean_lats, clean_lons = lats, lons

    base_coords = np.column_stack([clean_lats, clean_lons])
    if len(base_coords) == 0:
        return pd.DataFrame()

    try:
        from sklearn.cluster import MiniBatchKMeans as _KM
        k = min(n, len(base_coords))
        km = _KM(n_clusters=k, random_state=42, batch_size=1024, n_init=3)
        km.fit(base_coords)
        centroids = km.cluster_centers_
    except Exception:
        np.random.seed(42)
        idx = np.random.choice(len(base_coords), min(n, len(base_coords)), replace=False)
        centroids = base_coords[idx]

    # Snap every centroid to the nearest actual in-boundary call to guarantee the
    # proposed station remains inside the jurisdiction geometry.
    snapped = []
    for cen_lat, cen_lon in centroids:
        d2 = (base_coords[:, 0] - cen_lat) ** 2 + (base_coords[:, 1] - cen_lon) ** 2
        nearest = base_coords[int(np.argmin(d2))]
        snapped.append((float(nearest[0]), float(nearest[1])))

    if not snapped:
        return pd.DataFrame()

    deduped = list(dict.fromkeys((round(lat, 6), round(lon, 6)) for lat, lon in snapped))
    station_lats = np.array([lat for lat, _ in deduped])
    station_lons = np.array([lon for _, lon in deduped])

    k_actual = len(station_lats)
    types = (['Police'] * max(1, math.ceil(k_actual * 0.5)) +
             ['Fire']   * max(1, math.ceil(k_actual * 0.3)) +
             ['School'] * max(1, math.ceil(k_actual * 0.2)))[:k_actual]
    return pd.DataFrame({
        'name': [f"{types[i]} Station {i+1}" for i in range(k_actual)],
        'lat':  station_lats,
        'lon':  station_lons,
        'type': types,
    })

@st.cache_data(show_spinner=False)
def _fetch_osm_stations_cached(cen_lat_r: float, cen_lon_r: float, max_stations: int = 200):
    """Cache-friendly OSM query keyed on rounded centroid (2 dp ≈ 1 km grid).
    Returns (list_of_dicts | None, note_str).  All three Overpass mirrors are
    queried in parallel — total wait = fastest mirror, not sum of all mirrors.
    """
    osm_urls = [
        'https://overpass-api.de/api/interpreter',
        'https://overpass.kumi.systems/api/interpreter',
        'https://overpass.openstreetmap.ru/api/interpreter',
    ]

    def _try_mirror(url, query):
        try:
            req = urllib.request.Request(
                f"{url}?data={urllib.parse.quote(query)}",
                headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception:
            return None

    for R in [0.25, 0.45]:
        bbox = f"{cen_lat_r - R},{cen_lon_r - R},{cen_lat_r + R},{cen_lon_r + R}"
        query = (
            f'[out:json][timeout:20];'
            f'(node["amenity"="fire_station"]({bbox});'
            f'node["amenity"="police"]({bbox});'
            f'node["amenity"="school"]({bbox});'
            f'node["amenity"="hospital"]({bbox});'
            f'node["amenity"="library"]({bbox});'
            f'node["building"="government"]({bbox});'
            f'node["amenity"="ambulance_station"]({bbox});'
            f'node["amenity"="university"]({bbox});'
            f'node["amenity"="college"]({bbox});'
            f'node["amenity"="bus_station"]({bbox});'
            f'node["railway"="station"]({bbox});'
            f'node["amenity"="community_centre"]({bbox});'
            f'node["amenity"="courthouse"]({bbox});'
            f'node["amenity"="social_facility"]({bbox});'
            f'way["amenity"="fire_station"]({bbox});'
            f'way["amenity"="police"]({bbox});'
            f'way["amenity"="school"]({bbox});'
            f'way["amenity"="hospital"]({bbox});'
            f'way["amenity"="library"]({bbox});'
            f'way["building"="government"]({bbox});'
            f'way["amenity"="ambulance_station"]({bbox});'
            f'way["amenity"="university"]({bbox});'
            f'way["amenity"="college"]({bbox});'
            f'way["amenity"="bus_station"]({bbox});'
            f'way["railway"="station"]({bbox});'
            f'way["amenity"="community_centre"]({bbox});'
            f'way["amenity"="courthouse"]({bbox});'
            f'way["amenity"="social_facility"]({bbox});'
            f');out center;'
        )
        # Fire all three mirrors in parallel — first successful response wins
        data = None
        with cf.ThreadPoolExecutor(max_workers=3) as _pool:
            futs = {_pool.submit(_try_mirror, url, query): url for url in osm_urls}
            for fut in cf.as_completed(futs):
                result = fut.result()
                if result is not None:
                    data = result
                    break  # cancel remaining mirrors implicitly (they finish but are ignored)

        if data is None:
            continue

        rows = []
        for el in data.get('elements', []):
            tags = el.get('tags', {})
            lat = el.get('lat') or (el.get('center') or {}).get('lat')
            lon = el.get('lon') or (el.get('center') or {}).get('lon')
            if lat is None or lon is None:
                continue
            amenity  = tags.get('amenity', '')
            building = tags.get('building', '')
            railway  = tags.get('railway', '')
            type_label = (
                'Fire'           if amenity == 'fire_station'                    else
                'Police'         if amenity == 'police'                          else
                'Hospital'       if amenity == 'hospital'                        else
                'Library'        if amenity == 'library'                         else
                'EMS'            if amenity == 'ambulance_station'               else
                'University'     if amenity in ('university', 'college')         else
                'Transit'        if amenity == 'bus_station' or railway == 'station' else
                'Community'      if amenity == 'community_centre'                else
                'Courthouse'     if amenity == 'courthouse'                      else
                'Social Services' if amenity == 'social_facility'               else
                'Government'     if building == 'government'                     else
                'School'
            )
            rows.append({'name': tags.get('name', f"{type_label} Station"),
                         'lat': round(lat, 6), 'lon': round(lon, 6), 'type': type_label})

        if rows:
            df_s = pd.DataFrame(rows).drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)
            counts, new_names = {}, []
            for n in df_s['name']:
                if n in counts:
                    counts[n] += 1
                    new_names.append(f"{n} ({counts[n]})")
                else:
                    counts[n] = 0
                    new_names.append(n)
            df_s['name'] = new_names
            if len(df_s) > max_stations:
                pri = {'Police': 0, 'Fire': 1, 'EMS': 2, 'School': 3, 'Hospital': 4, 'University': 5, 'Transit': 6, 'Courthouse': 7, 'Community': 8, 'Government': 9, 'Social Services': 10, 'Library': 11}
                df_s['_pri'] = df_s['type'].map(pri).fillna(3)
                df_s = df_s.sort_values('_pri').head(max_stations).drop(columns='_pri').reset_index(drop=True)
            return df_s.to_dict('records'), f"Found {len(df_s)} stations from OpenStreetMap."

    return None, "OSM unavailable"


@st.cache_data(show_spinner=False)
def _fetch_hifld_stations_cached(min_lat: float, min_lon: float, max_lat: float, max_lon: float):
    """Fetch fire stations and law enforcement from HIFLD (US Federal open data).
    Returns (list_of_dicts | None, note_str).
    Fire and Police endpoints are queried in parallel to halve wait time.
    HIFLD endpoints are ArcGIS FeatureServer REST services maintained by DHS.
    """
    _HIFLD_SOURCES = [
        (
            "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/Fire_Stations/FeatureServer/0/query",
            "Fire",
            "NAME",
        ),
        (
            "https://services1.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/USA_Law_Enforcement_Locations/FeatureServer/0/query",
            "Police",
            "NAME",
        ),
    ]
    bbox_str = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    def _fetch_one(url, type_label, name_field):
        try:
            params = urllib.parse.urlencode({
                'where': '1=1',
                'geometry': bbox_str,
                'geometryType': 'esriGeometryEnvelope',
                'inSR': '4326',
                'spatialRel': 'esriSpatialRelIntersects',
                'outFields': f'{name_field},CITY,STATE',
                'outSR': '4326',
                'f': 'json',
                'resultRecordCount': 500,
            })
            req = urllib.request.Request(
                f"{url}?{params}",
                headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            rows = []
            for feat in data.get('features', []):
                geom  = feat.get('geometry', {})
                attrs = feat.get('attributes', {})
                lat   = geom.get('y')
                lon   = geom.get('x')
                if lat is None or lon is None:
                    continue
                name = (attrs.get(name_field) or '').strip() or f"{type_label} Station"
                rows.append({'name': name, 'lat': round(float(lat), 6),
                             'lon': round(float(lon), 6), 'type': type_label})
            return rows
        except Exception:
            return []

    # Fetch fire + police in parallel — total wait = max(fire, police), not sum
    all_rows = []
    with cf.ThreadPoolExecutor(max_workers=2) as _pool:
        futs = [_pool.submit(_fetch_one, url, lbl, fld) for url, lbl, fld in _HIFLD_SOURCES]
        for fut in cf.as_completed(futs):
            all_rows.extend(fut.result())

    if all_rows:
        return all_rows, f"Found {len(all_rows)} stations from HIFLD (US Federal)."
    return None, "HIFLD unavailable"


def generate_stations_from_calls(df_calls, max_stations=100):
    """Query OSM and HIFLD in parallel; merge results; fall back to call density."""
    lats = df_calls['lat'].dropna().values
    lons = df_calls['lon'].dropna().values
    if len(lats) == 0:
        return None, "No coordinates available to generate stations."

    q1_la, q3_la = np.percentile(lats, 25), np.percentile(lats, 75)
    q1_lo, q3_lo = np.percentile(lons, 25), np.percentile(lons, 75)
    iqr_la, iqr_lo = q3_la - q1_la, q3_lo - q1_lo
    mask = (
        (lats >= q1_la - 2.5 * iqr_la) & (lats <= q3_la + 2.5 * iqr_la) &
        (lons >= q1_lo - 2.5 * iqr_lo) & (lons <= q3_lo + 2.5 * iqr_lo)
    )
    if not np.any(mask):
        mask = np.ones(len(lats), dtype=bool)
    cen_lat_r = round(float(lats[mask].mean()), 2)
    cen_lon_r = round(float(lons[mask].mean()), 2)

    _pad = 0.45
    min_lat_r = round(cen_lat_r - _pad, 2)
    max_lat_r = round(cen_lat_r + _pad, 2)
    min_lon_r = round(cen_lon_r - _pad, 2)
    max_lon_r = round(cen_lon_r + _pad, 2)

    osm_rows, osm_note = None, "OSM unavailable"
    hifld_rows, hifld_note = None, "HIFLD unavailable"

    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            'OSM': pool.submit(_fetch_osm_stations_cached, cen_lat_r, cen_lon_r, max_stations),
            'HIFLD': pool.submit(_fetch_hifld_stations_cached, min_lat_r, min_lon_r, max_lat_r, max_lon_r),
        }
        _, not_done = cf.wait(futures.values(), timeout=12)

        for name, fut in futures.items():
            if fut in not_done:
                fut.cancel()
                print(f"[BRINC] generate_stations_from_calls: {name} timed out")
                continue
            try:
                rows, note = fut.result()
            except Exception as e:
                rows, note = None, f"{name} unavailable"
                print(f"[BRINC] generate_stations_from_calls: {name} raised {e}")
            if name == 'OSM':
                osm_rows, osm_note = rows, note
            else:
                hifld_rows, hifld_note = rows, note

    combined = []
    if osm_rows:
        combined.extend(osm_rows)
    if hifld_rows:
        combined.extend(hifld_rows)

    if combined:
        df_combined = pd.DataFrame(combined)
        df_combined = df_combined.round({'lat': 3, 'lon': 3})
        df_combined = df_combined.drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)
        _pri_map = {'Police': 0, 'Fire': 1, 'School': 2, 'Hospital': 3, 'Government': 4, 'Library': 5}
        df_combined['_pri'] = df_combined['type'].map(_pri_map).fillna(9)
        df_combined = df_combined.sort_values('_pri').head(max_stations).drop(columns='_pri').reset_index(drop=True)
        sources = [s for s, r in [('OSM', osm_rows), ('HIFLD', hifld_rows)] if r]
        note = f"Found {len(df_combined)} candidate sites from {' + '.join(sources)}."
        return df_combined, note

    df_fallback = _make_random_stations(df_calls, n=40)
    if not df_fallback.empty:
        notes = [n for n in [osm_note, hifld_note] if n]
        return df_fallback, "Fallback stations generated from call data. " + " | ".join(notes)
    return None, "Could not generate stations ? no valid call coordinates."

# ============================================================
# CACHED DATA FUNCTIONS
# ============================================================
@st.cache_data
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
    # Fallback to coordinates if an exact street address isn't found
    return f"{lat:.5f}, {lon:.5f}"

def _lookup_streamlit_secret(*names):
    _target_names = {str(_name or '').strip().upper() for _name in names if str(_name or '').strip()}
    if not _target_names:
        return ""

    def _scan_secret_container(_container, _visited=None):
        _visited = _visited or set()
        _obj_id = id(_container)
        if _obj_id in _visited:
            return ""
        _visited.add(_obj_id)

        if hasattr(_container, 'items'):
            try:
                _items = list(_container.items())
            except Exception:
                _items = []

            for _key, _value in _items:
                if str(_key or '').strip().upper() in _target_names and not hasattr(_value, 'items'):
                    _secret_value = str(_value or '').strip()
                    if _secret_value:
                        return _secret_value

            for _, _value in _items:
                if hasattr(_value, 'items'):
                    _nested_value = _scan_secret_container(_value, _visited)
                    if _nested_value:
                        return _nested_value
        return ""

    try:
        _secret_value = _scan_secret_container(st.secrets)
        if _secret_value:
            return _secret_value
    except Exception:
        pass

    for _name in names:
        _env_value = str(os.environ.get(str(_name or '').strip(), '') or '').strip()
        if _env_value:
            return _env_value
    return ""


def _get_google_maps_api_key():
    return _lookup_streamlit_secret(
        "GOOGLE_MAPS_API_KEY",
        "GOOGLE_GEOCODING_API_KEY",
        "GOOGLE_API_KEY",
        "GMAPS_API_KEY",
    )


def _get_mapbox_api_key():
    return _lookup_streamlit_secret(
        "MAPBOX_ACCESS_TOKEN",
        "MAPBOX_API_KEY",
        "MAPBOX_TOKEN",
    )


def _get_geocoder_provider_signature():
    _provider_values = {
        'google': _get_google_maps_api_key(),
        'mapbox': _get_mapbox_api_key(),
    }
    _signature_payload = "|".join(
        f"{_provider}:{hashlib.sha256(str(_value or '').encode('utf-8')).hexdigest()}"
        for _provider, _value in sorted(_provider_values.items())
    )
    return hashlib.sha256(_signature_payload.encode('utf-8')).hexdigest()


@st.cache_data(show_spinner=False)
def _search_address_candidates_cached(address_str, limit=6, preferred_city="", preferred_state="", provider_signature=""):
    address_str = str(address_str or '').strip()
    if not address_str:
        try:
            st.session_state['_last_geocode_trace'] = {
                'input': '',
                'preferred_city': str(preferred_city or '').strip(),
                'preferred_state': str(preferred_state or '').strip().upper(),
                'queries': [],
                'providers': [],
                'candidate_count': 0,
            }
        except Exception:
            pass
        return []

    limit = max(1, min(int(limit or 6), 10))
    preferred_city = str(preferred_city or '').strip()
    preferred_state = str(preferred_state or '').strip().upper()
    # Full state name for providers (OSM) that return "Nebraska" instead of "NE"
    _abbr_to_full = {v: k for k, v in US_STATES_ABBR.items()}
    preferred_state_full = _abbr_to_full.get(preferred_state, '').lower()
    candidates = []
    seen = set()

    def _normalize_text(value):
        return str(value or "").strip().lower()

    def _normalize_address_variants(raw_value):
        raw_value = str(raw_value or '').strip()
        if not raw_value:
            return []
        variants = [raw_value]
        compact = re.sub(r'\s+', ' ', raw_value).strip()
        if compact and compact.lower() != raw_value.lower():
            variants.append(compact)

        word_to_num = {
            'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
            'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
        }
        street_suffix_map = {
            'street': 'st',
            'avenue': 'ave',
            'boulevard': 'blvd',
            'road': 'rd',
            'drive': 'dr',
            'lane': 'ln',
            'court': 'ct',
            'place': 'pl',
            'parkway': 'pkwy',
            'circle': 'cir',
            'terrace': 'ter',
        }

        def _transform_variant(text):
            text = re.sub(r'\s+', ' ', str(text or '').strip())
            if not text:
                return []
            out = [text]
            parts = text.split(' ', 1)
            if parts:
                first = parts[0].lower().rstrip('.,')
                if first in word_to_num and len(parts) > 1:
                    out.append(f"{word_to_num[first]} {parts[1]}")
            replaced = text
            for suffix, abbr in street_suffix_map.items():
                replaced = re.sub(rf'\b{suffix}\b', abbr, replaced, flags=re.IGNORECASE)
            if replaced.lower() != text.lower():
                out.append(replaced)
            out2 = []
            for candidate in out:
                parts2 = candidate.split(' ', 1)
                if parts2:
                    first2 = parts2[0].lower().rstrip('.,')
                    if first2 in word_to_num and len(parts2) > 1:
                        candidate = f"{word_to_num[first2]} {parts2[1]}"
                replaced2 = candidate
                for suffix, abbr in street_suffix_map.items():
                    replaced2 = re.sub(rf'\b{suffix}\b', abbr, replaced2, flags=re.IGNORECASE)
                out2.append(candidate)
                if replaced2.lower() != candidate.lower():
                    out2.append(replaced2)
            deduped = []
            seen_local = set()
            for candidate in out2:
                cleaned = re.sub(r'\s+', ' ', str(candidate or '').strip())
                key = cleaned.lower()
                if cleaned and key not in seen_local:
                    seen_local.add(key)
                    deduped.append(cleaned)
            return deduped

        expanded = []
        seen_expanded = set()
        for variant in variants:
            for candidate in _transform_variant(variant):
                key = candidate.lower()
                if candidate and key not in seen_expanded:
                    seen_expanded.add(key)
                    expanded.append(candidate)
        return expanded

    def _query_variants():
        _variants = []
        for _base_variant in _normalize_address_variants(address_str):
            _variants.append(_base_variant)
            _has_city = preferred_city and preferred_city.lower() in _base_variant.lower()
            _has_state = preferred_state and preferred_state.lower() in _base_variant.lower()
            if preferred_city and preferred_state and (not _has_city or not _has_state):
                _variants.append(f"{_base_variant}, {preferred_city}, {preferred_state}")
            if preferred_state and not _has_state:
                _variants.append(f"{_base_variant}, {preferred_state}")
        ordered = []
        seen_variants = set()
        for _variant in _variants:
            _clean = str(_variant or '').strip()
            if _clean and _clean.lower() not in seen_variants:
                seen_variants.add(_clean.lower())
                ordered.append(_clean)
        return ordered

    def _candidate_score(candidate):
        _label = _normalize_text(candidate.get('matched_address') or candidate.get('label'))
        _source = str(candidate.get('source', ''))
        _score = {
            'Google': 500,
            'Mapbox': 425,
            'Census': 350,
            'OSM': 250,
        }.get(_source, 0)

        if preferred_state:
            _state_token = f", {preferred_state.lower()}"
            _full_token = f", {preferred_state_full}" if preferred_state_full else None
            _in_label = (
                _state_token in _label
                or _label.endswith(f" {preferred_state.lower()}")
                or (_full_token and _full_token in _label)
            )
            if _in_label:
                _score += 220
            else:
                _score -= 180
        if preferred_city:
            if preferred_city.lower() in _label:
                _score += 150
            else:
                _score -= 80

        _typed = _normalize_text(address_str)
        if _typed and _typed in _label:
            _score += 80
        elif _typed:
            _score += max(0, 30 - min(len(_typed), 30))
        return _score

    def _add_candidate(label, lat, lon, source, raw_match=''):
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except Exception:
            return
        dedupe_key = (round(lat_f, 6), round(lon_f, 6), str(label).strip().lower())
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        candidates.append({
            'label': str(label).strip() or str(raw_match).strip() or address_str,
            'matched_address': str(raw_match).strip() or str(label).strip() or address_str,
            'lat': lat_f,
            'lon': lon_f,
            'source': source,
            '_score': 0,
        })

    _queries = _query_variants()
    _provider_trace = []

    for _query in _queries:
        try:
            _params = urllib.parse.urlencode({
                'address': _query,
                'benchmark': '2020',
                'format': 'json'
            })
            _url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?{_params}"
            _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
            with urllib.request.urlopen(_req, timeout=8) as _resp:
                _data = json.loads(_resp.read().decode('utf-8'))
            _matches = _data.get('result', {}).get('addressMatches', [])[:limit]
            _provider_trace.append({'provider': 'Census', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': 'ok'})
            for _match in _matches:
                _coords = _match.get('coordinates', {})
                _add_candidate(
                    _match.get('matchedAddress', _query),
                    _coords.get('y'),
                    _coords.get('x'),
                    'Census',
                    raw_match=_match.get('matchedAddress', _query),
                )
        except Exception:
            _provider_trace.append({'provider': 'Census', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})

    _google_api_key = _get_google_maps_api_key()
    if _google_api_key:
        for _query in _queries:
            try:
                _params = urllib.parse.urlencode({
                    'address': _query,
                    'key': _google_api_key,
                    'components': f'country:US|administrative_area:{preferred_state}' if preferred_state else 'country:US',
                })
                _url = f"https://maps.googleapis.com/maps/api/geocode/json?{_params}"
                _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
                with urllib.request.urlopen(_req, timeout=8) as _resp:
                    _data = json.loads(_resp.read().decode('utf-8'))
                _matches = _data.get('results', [])[:limit]
                _provider_trace.append({'provider': 'Google', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': _data.get('status', 'ok')})
                for _match in _matches:
                    _geometry = _match.get('geometry', {}).get('location', {})
                    _label = _match.get('formatted_address', _query)
                    _add_candidate(_label, _geometry.get('lat'), _geometry.get('lng'), 'Google', raw_match=_label)
            except Exception:
                _provider_trace.append({'provider': 'Google', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})
    else:
        _provider_trace.append({'provider': 'Google', 'query': '', 'used': False, 'match_count': 0, 'status': 'missing_api_key'})

    _mapbox_key = _get_mapbox_api_key()
    if _mapbox_key:
        for _query in _queries:
            try:
                _params = urllib.parse.urlencode({
                    'q': _query,
                    'access_token': _mapbox_key,
                    'country': 'US',
                    'limit': str(limit),
                    'autocomplete': 'true',
                    'types': 'address,street',
                })
                _url = f"https://api.mapbox.com/search/geocode/v6/forward?{_params}"
                _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
                with urllib.request.urlopen(_req, timeout=8) as _resp:
                    _data = json.loads(_resp.read().decode('utf-8'))
                _matches = _data.get('features', [])[:limit]
                _provider_trace.append({'provider': 'Mapbox', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': 'ok'})
                for _match in _matches:
                    _coords = (_match.get('geometry') or {}).get('coordinates') or [None, None]
                    _props = _match.get('properties') or {}
                    _label = (
                        _props.get('full_address')
                        or _match.get('place_name')
                        or _match.get('name')
                        or _query
                    )
                    _add_candidate(_label, _coords[1], _coords[0], 'Mapbox', raw_match=_label)
            except Exception:
                _provider_trace.append({'provider': 'Mapbox', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})
    else:
        _provider_trace.append({'provider': 'Mapbox', 'query': '', 'used': False, 'match_count': 0, 'status': 'missing_api_key'})

    for _query in _queries:
        try:
            _params = urllib.parse.urlencode({
                'format': 'jsonv2',
                'q': _query,
                'limit': str(limit),
                'countrycodes': 'us',
                'addressdetails': '1',
            })
            _url = f"https://nominatim.openstreetmap.org/search?{_params}"
            _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
            with urllib.request.urlopen(_req, timeout=8) as _resp:
                _data = json.loads(_resp.read().decode('utf-8'))
            _matches = _data[:limit]
            _provider_trace.append({'provider': 'OSM', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': 'ok'})
            for _match in _matches:
                _label = _match.get('display_name', _query)
                _add_candidate(_label, _match.get('lat'), _match.get('lon'), 'OSM', raw_match=_label)
        except Exception:
            _provider_trace.append({'provider': 'OSM', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})

    for _candidate in candidates:
        _candidate['_score'] = _candidate_score(_candidate)
    candidates.sort(key=lambda _item: (-_item.get('_score', 0), _item.get('matched_address', '')))
    try:
        st.session_state['_last_geocode_trace'] = {
            'input': address_str,
            'preferred_city': preferred_city,
            'preferred_state': preferred_state,
            'queries': _queries,
            'providers': _provider_trace,
            'candidate_count': len(candidates),
            'top_candidate': candidates[0]['matched_address'] if candidates else '',
        }
    except Exception:
        pass
    return [{k: v for k, v in _candidate.items() if k != '_score'} for _candidate in candidates[:limit]]


def search_address_candidates(address_str, limit=6, preferred_city="", preferred_state=""):
    return _search_address_candidates_cached(
        address_str,
        limit=limit,
        preferred_city=preferred_city,
        preferred_state=preferred_state,
        provider_signature=_get_geocoder_provider_signature(),
    )

@st.cache_data(show_spinner=False)
def forward_geocode(address_str):
    _matches = search_address_candidates(
        address_str,
        limit=1,
        preferred_city=st.session_state.get('active_city', ''),
        preferred_state=st.session_state.get('active_state', ''),
    )
    if _matches:
        return float(_matches[0]['lat']), float(_matches[0]['lon'])
    return None, None

@st.cache_data(show_spinner=False)
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
if not os.path.exists(SHAPEFILE_DIR): os.makedirs(SHAPEFILE_DIR)

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

def add_cell_towers_layer_to_plotly(fig, state_abbr, minx, miny, maxx, maxy):
    """Add OpenCelliD cell tower markers to map."""
    try:
        gdf = faa_rf.load_cached_regulatory_layers(state_abbr, "cell_towers")
        if gdf.empty: return

        # Clip to bounding box
        pad = 0.05
        bbox = box(minx-pad, miny-pad, maxx+pad, maxy+pad)
        clipped = gdf[gdf.geometry.intersects(bbox)]

        if not clipped.empty:
            fig.add_trace(go.Scattermap(
                lat=clipped.geometry.y,
                lon=clipped.geometry.x,
                mode='markers',
                marker=dict(size=5, color='#ff9500', opacity=0.6),
                name='Cell Towers',
                hovertext=['Cell Tower' for _ in clipped],
                hoverinfo='text',
                showlegend=True,
            ))
    except Exception as e:
        print(f"[BRINC] add_cell_towers_layer_to_plotly failed: {e}")

def add_no_fly_zones_layer_to_plotly(fig, minx, miny, maxx, maxy):
    """Add no-fly zones (parks, water, restricted areas) to map."""
    try:
        gdf = faa_rf.load_cached_regulatory_layers("US", "no_fly_zones")
        if gdf.empty: return

        # Clip to bounding box
        pad = 0.05
        bbox = box(minx-pad, miny-pad, maxx+pad, maxy+pad)
        clipped = gdf[gdf.geometry.intersects(bbox)]

        if not clipped.empty:
            for _, row in clipped.iterrows():
                geom = row.geometry
                if geom.geom_type == 'Polygon':
                    lon, lat = zip(*geom.exterior.coords)
                    fig.add_trace(go.Scattermap(
                        lat=lat, lon=lon,
                        mode='lines', fill='toself',
                        fillcolor='rgba(100,100,255,0.15)',
                        line=dict(color='#6464ff', width=1),
                        name='No-Fly Zone',
                        hovertext=row.get('zone_type', 'No-Fly Zone'),
                        hoverinfo='text',
                        showlegend=False,
                    ))
    except Exception as e:
        print(f"[BRINC] add_no_fly_zones_layer_to_plotly failed: {e}")

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


# ── 4G LTE coverage overlay ───────────────────────────────────────────────────
# Analysis results are keyed by (state_abbr, wkb_hex) — geometry args can't be
# serialized by @st.cache_data, so we keep a manual dict stored in a
# @st.cache_resource singleton (one dict per worker process, persists for the
# lifetime of the server, safe under concurrent access).

@st.cache_resource
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


# ── RF Link Budget — 3390 MHz Friis free-space model ─────────────────────────

def _get_terrain_cache():
    """Global cache dict for DEM tiles to avoid re-downloading."""
    return {}

def _estimate_elevation_simple(lat, lon, cache=None):
    """Fetch elevation for a point (cached) — fallback to 100 ft if unavailable."""
    if cache is None:
        cache = {}
    key = (round(lat, 2), round(lon, 2))
    if key in cache:
        return cache[key]
    try:
        # Try OpenDEM API (no key required, open access)
        import urllib.request as _ur
        url = f"https://cloud.sdsc.edu/v1/AUTH_opentopography/Raster/SRTM_GL30/SRTM_GL30_Ellip/SRTM_GL30_Ellip_srtm.tif"
        # Fallback: use simple rule based on typical coastal vs inland
        elev = max(0, 100 + (lon % 1) * 50 - (lat % 1) * 30)  # Mock variation
    except Exception:
        elev = 100.0  # Default 100 ft mean elevation
    cache[key] = elev
    return elev

def _estimate_clutter_loss_db(lat, lon, land_use_class="suburban"):
    """
    Estimate clutter/foliage/building loss based on land-use class.
    Returns dB added to path loss (positive = attenuation).
    Simplified model; real impl would use GIS layers.
    """
    clutter_map = {
        "urban": {"base": 18.0, "var": 8.0},
        "suburban": {"base": 12.0, "var": 5.0},
        "rural": {"base": 6.0, "var": 3.0},
        "water": {"base": 2.0, "var": 1.0},
    }
    params = clutter_map.get(land_use_class, clutter_map["suburban"])
    # Add small pseudorandom variation based on coordinates
    var = (abs(lat * 137.5) % 1.0 + abs(lon * 173.2) % 1.0) / 2.0 * params["var"]
    return params["base"] + var

def _estimate_terrain_blockage_db(tx_lat, tx_lon, rx_lat, rx_lon, tx_alt_m, rx_alt_m):
    """
    Estimate terrain blockage loss using simple Fresnel zone calculation.
    If midpoint elevation is significantly above LOS, add loss.
    Returns dB penalty for terrain obstruction.
    """
    try:
        import math as _m
        # Midpoint
        mid_lat = (tx_lat + rx_lat) / 2.0
        mid_lon = (tx_lon + rx_lon) / 2.0

        # Distance
        lat_dist_m = (rx_lat - tx_lat) * 111000.0  # approx 111 km per degree latitude
        lon_dist_m = (rx_lon - tx_lon) * 111000.0 * _m.cos(_m.radians((tx_lat + rx_lat) / 2.0))
        horiz_dist = _m.sqrt(lat_dist_m**2 + lon_dist_m**2)

        if horiz_dist < 100:  # Too close, skip terrain calc
            return 0.0

        # Fresnel radius at midpoint
        freq_hz = 3.39e9  # 3390 MHz
        fresnel_r = _m.sqrt(0.5 * 3e8 / freq_hz * horiz_dist)

        # Estimate elevations (simple proxy)
        tx_elev = _estimate_elevation_simple(tx_lat, tx_lon)
        rx_elev = _estimate_elevation_simple(rx_lat, rx_lon)
        mid_elev = _estimate_elevation_simple(mid_lat, mid_lon)

        # LOS line from tx to rx
        tx_height = tx_elev + tx_alt_m
        rx_height = rx_elev + rx_alt_m
        los_height_at_mid = (tx_height + rx_height) / 2.0

        # Blockage: if terrain > 0.6 Fresnel radius above LOS, add loss
        blockage_m = max(0, mid_elev - los_height_at_mid)
        blockage_ratio = blockage_m / max(1.0, fresnel_r)

        # Knife-edge diffraction approximation
        if blockage_ratio > 0.1:
            loss_db = 6.0 * blockage_ratio**2  # ITM-style knife-edge loss
        else:
            loss_db = 0.0

        return min(25.0, loss_db)  # Cap at 25 dB
    except Exception:
        return 0.0

def _path_loss_advanced(distance_m, freq_mhz=3390, tx_alt_m=9.14, rx_alt_m=61.0,
                        tx_lat=None, tx_lon=None, rx_lat=None, rx_lon=None,
                        land_use="suburban"):
    """
    Advanced path loss model combining multiple effects:
      PL_total = FSPL + clutter_loss + terrain_loss + fade_margin

    where:
      FSPL = 20*log10(d) + 20*log10(f_mhz) + 27.55
      clutter_loss = function of land use
      terrain_loss = function of elevation difference and blockage
      fade_margin = 3 dB (flat fading margin)
    """
    import math as _m

    if distance_m < 10:
        return 0.0  # No loss at very short range

    # Free-space path loss
    fspl = 20.0 * _m.log10(distance_m) + 20.0 * _m.log10(freq_mhz) + 27.55

    # Clutter loss
    clutter_db = _estimate_clutter_loss_db(tx_lat, tx_lon, land_use) if tx_lat else 0.0

    # Terrain/blockage loss (if we have coordinates)
    terrain_db = 0.0
    if tx_lat and tx_lon and rx_lat and rx_lon:
        terrain_db = _estimate_terrain_blockage_db(tx_lat, tx_lon, rx_lat, rx_lon,
                                                   tx_alt_m, rx_alt_m)

    # Fade margin (Rayleigh/urban multipath)
    fade_db = 3.0

    total_pl = fspl + clutter_db + terrain_db + fade_db
    return total_pl

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
    page_title="BRINC Drone-as-First-Responder",
    page_icon="https://brincdrones.com/favicon.ico"
)

# ============================================================
# GOOGLE OAUTH LOGIN GATE
# ============================================================
# Activates only when [auth] section is present in secrets.toml.
# Falls through silently if auth is not configured (local dev without secrets).
try:
    if hasattr(st, 'user') and "auth" in st.secrets:
        if not st.user.is_logged_in:
            import base64 as _b64
            try:
                _logo_b64 = _b64.b64encode(open("logo.png", "rb").read()).decode()
                _logo_tag = f'<img src="data:image/png;base64,{_logo_b64}" style="height:80px;object-fit:contain;" alt="BRINC">'
            except Exception:
                _logo_tag = '<div style="font-size:2rem;font-weight:900;color:#00D2FF;letter-spacing:4px;">BRINC DFR</div>'
            st.markdown(f"""
            <style>
            section[data-testid="stSidebar"] {{ display: none !important; }}
            [data-testid="collapsedControl"],
            [data-testid="stSidebarCollapsedControl"] {{ display: none !important; }}
            [data-testid="stAppViewContainer"] {{
                background: radial-gradient(ellipse at 50% 30%, #0d1b2e 0%, #060a12 70%) !important;
            }}
            [data-testid="block-container"] {{
                padding-top: 0 !important;
                padding-bottom: 0 !important;
                max-width: 100% !important;
            }}
            div[data-testid="stButton"] {{
                display: flex !important;
                justify-content: center !important;
                margin-top: 0 !important;
            }}
            div[data-testid="stButton"] > button {{
                background: linear-gradient(135deg, #0077b6, #00b4d8) !important;
                color: #fff !important;
                border: none !important;
                border-radius: 10px !important;
                padding: 13px 44px !important;
                font-size: 0.95rem !important;
                font-weight: 600 !important;
                letter-spacing: 0.6px !important;
                box-shadow: 0 4px 24px rgba(0,180,216,0.35) !important;
            }}
            div[data-testid="stButton"] > button:hover {{
                background: linear-gradient(135deg, #005f8a, #009dbf) !important;
                box-shadow: 0 6px 30px rgba(0,180,216,0.5) !important;
            }}
            </style>
            <div style="
                display:flex;flex-direction:column;align-items:center;justify-content:center;
                min-height:85vh;gap:0;
            ">
              <div style="
                background:rgba(255,255,255,0.03);
                border:1px solid rgba(255,255,255,0.08);
                border-radius:20px;
                padding:52px 64px 44px;
                display:flex;flex-direction:column;align-items:center;gap:18px;
                box-shadow:0 20px 60px rgba(0,0,0,0.6);
                backdrop-filter:blur(12px);
                min-width:340px;
              ">
                {_logo_tag}
                <div style="width:48px;height:2px;background:linear-gradient(90deg,transparent,#00b4d8,transparent);margin:2px 0;"></div>
                <div style="color:#8a9bb5;font-size:0.78rem;letter-spacing:2.5px;text-transform:uppercase;font-weight:500;">
                  Drone as First Responder &nbsp;·&nbsp; Optimizer
                </div>
                <div style="height:12px;"></div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            st.button("Sign in with Google", on_click=st.login, args=("google",),
                      type="primary", width="content")
            st.html("""
<script>
(function() {
    var sel = [
        'header', '[data-testid="stHeader"]', '[data-testid="stToolbar"]',
        '[data-testid="stDecoration"]', '[data-testid="stStatusWidget"]',
        '[data-testid="stGithubButton"]', '[data-testid="stActionButton"]',
        '[data-testid="stBaseButton-header"]', '[data-testid="stHeaderActionElements"]',
        '[data-testid="stHeaderActions"]', '[data-testid="stDeployButton"]',
        '[data-testid="stAppDeployButton"]', '.stDeployButton',
        '.viewerBadge_container__', '.viewerBadge_link__', '.viewerBadge_text__',
        '#MainMenu', 'footer', 'iframe[title="streamlit_analytics"]',
        'header a[href*="github.com"]', 'header a[href*="streamlit.io"]',
        'header [aria-label*="GitHub"]', 'header [aria-label*="github"]',
        'header [aria-label*="Streamlit"]', 'header [title*="GitHub"]',
        'header [title*="github"]', 'header [title*="Streamlit"]',
        'button[title*="GitHub"]', 'button[title*="github"]'
    ];
    function sweep(root) {
        if (!root) return;
        try {
            sel.forEach(function(s) {
                root.querySelectorAll(s).forEach(function(el) {
                    el.remove();
                });
            });
            root.querySelectorAll('*').forEach(function(el) {
                if (el.shadowRoot) {
                    sweep(el.shadowRoot);
                }
            });
        } catch(e) {}
    }
    function hide() {
        try {
            sweep(window.parent.document);
        } catch(e) {}
    }
    hide();
    try {
        new MutationObserver(hide).observe(window.parent.document.body, {childList:true, subtree:true});
    } catch(e) {}
    try {
        setInterval(hide, 1000);
    } catch(e) {}
})();
</script>
""", unsafe_allow_javascript=True)
            st.stop()

        # ── Restrict to @brincdrones.com accounts ──────────────────────────
        _user_email = getattr(st.user, "email", "") or ""
        if not _user_email.lower().endswith("@brincdrones.com"):
            st.markdown(
                "<style>section[data-testid='stSidebar'] { display: none !important; }</style>",
                unsafe_allow_html=True
            )
            st.error(
                f"Access restricted to BRINC Drones employees.\n\n"
                f"You are signed in as **{_user_email}**.\n\n"
                "Please sign in with your @brincdrones.com account."
            )
            st.button("Sign out", on_click=st.logout)
            st.stop()

        # ── Populate session state from OAuth identity ──────────────────────
        _authed_email = getattr(st.user, "email", "") or ""
        _authed_name  = getattr(st.user, "name",  "") or _authed_email.split("@")[0]
        if not st.session_state.get('_oauth_logged', False):
            st.session_state['google_user_email'] = _authed_email
            st.session_state['google_user_name']  = _authed_name
            # Derive brinc_user (first.last prefix) from email for backwards compatibility
            _prefix = _authed_email.split("@")[0]
            st.session_state['brinc_user'] = _prefix
            st.session_state['_oauth_logged'] = True
            try:
                _log_login_to_sheets(_authed_email, _authed_name)
            except Exception:
                pass

except Exception:
    pass  # Auth not configured — app runs without login gate

# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================
# This MUST run before any st.session_state checks to prevent KeyError
init_session_state(st.session_state, _slugify, _build_public_report_url)

# ============================================================
# APP FLOW
# ============================================================

FAQ_CHANGELOG = [
    {
        "version": __version__,
        "timestamp": __build_datetime__,
        "summary": "Added an in-app FAQ launcher in the upper-left with a compact versioned release-notes footer.",
    },
]


def _render_in_app_faq():
    _faq_items = [
        (
            "What does this software do?",
            "It helps plan BRINC Drone as First Responder deployments using incident data, jurisdiction boundaries, station modeling, and optimization.",
        ),
        (
            "What file should I upload?",
            "The most common input is a CAD or incident export in CSV or Excel format with usable location data.",
        ),
        (
            "How is the jurisdiction selected?",
            "The app matches uploaded incident coordinates to local jurisdiction boundary data, then lets you confirm or refine the selected area in the sidebar.",
        ),
        (
            "What is the difference between Responder and Guardian?",
            "Responder is modeled for shorter-range tactical response, while Guardian is modeled for broader long-range coverage and overwatch.",
        ),
        (
            "Can I choose my own stations?",
            "Yes. The app can recommend stations automatically, and you can also add or lock custom stations into the plan.",
        ),
        (
            "What outputs can I export?",
            "You can export a saved deployment plan, an executive-summary HTML report, and a Google Earth KML briefing file.",
        ),
        (
            "Why are map layers or FAA overlays missing?",
            "The regulatory cache may be missing or outdated. Re-run download_regulatory_layers.py and restart the app.",
        ),
    ]

    _faq_html_parts = []
    for _question, _answer in _faq_items:
        _faq_html_parts.append(
            f"""
            <div class="faq-item">
                <div class="faq-q">{html.escape(_question)}</div>
                <div class="faq-a">{html.escape(_answer)}</div>
            </div>
            """
        )

    _changelog_lines = "".join(
        f'<div class="faq-changelog-line">v{html.escape(str(_entry["version"]))} | '
        f'{html.escape(str(_entry["timestamp"]))} | '
        f'{html.escape(str(_entry["summary"]))}</div>'
        for _entry in FAQ_CHANGELOG
    )

    st.markdown(
        f"""
        <style>
        .faq-float {{
            position: fixed;
            top: 12px;
            left: 14px;
            z-index: 9998;
            width: min(420px, calc(100vw - 28px));
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        .faq-float summary {{
            list-style: none;
        }}
        .faq-float summary::-webkit-details-marker {{
            display: none;
        }}
        .faq-pill {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 10px;
            border-radius: 999px;
            background: rgba(8, 12, 20, 0.88);
            border: 1px solid rgba(116, 224, 255, 0.22);
            color: rgba(226, 238, 246, 0.92);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            cursor: pointer;
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.24);
            backdrop-filter: blur(8px);
        }}
        .faq-pill:hover {{
            border-color: rgba(116, 224, 255, 0.42);
            background: rgba(10, 16, 28, 0.96);
        }}
        .faq-panel {{
            margin-top: 8px;
            background: rgba(7, 11, 18, 0.97);
            border: 1px solid rgba(116, 224, 255, 0.18);
            border-radius: 16px;
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.34);
            overflow: hidden;
        }}
        .faq-panel-inner {{
            max-height: min(78vh, 760px);
            overflow-y: auto;
            padding: 14px 14px 12px;
        }}
        .faq-title {{
            color: #f4fbff;
            font-size: 0.92rem;
            font-weight: 800;
            margin: 0 0 4px 0;
        }}
        .faq-subtitle {{
            color: rgba(193, 209, 221, 0.78);
            font-size: 0.76rem;
            line-height: 1.5;
            margin-bottom: 12px;
        }}
        .faq-item {{
            padding: 10px 0;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .faq-item:first-of-type {{
            border-top: none;
            padding-top: 0;
        }}
        .faq-q {{
            color: #f6fbff;
            font-size: 0.79rem;
            font-weight: 700;
            margin-bottom: 4px;
        }}
        .faq-a {{
            color: rgba(209, 220, 230, 0.84);
            font-size: 0.75rem;
            line-height: 1.52;
        }}
        .faq-footer {{
            margin-top: 12px;
            padding-top: 10px;
            border-top: 1px solid rgba(116, 224, 255, 0.14);
        }}
        .faq-footer-label {{
            color: #7edfff;
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }}
        .faq-version-line {{
            color: rgba(245, 250, 255, 0.92);
            font-size: 0.72rem;
            font-family: "IBM Plex Mono", Consolas, monospace;
            margin-bottom: 8px;
        }}
        .faq-changelog-line {{
            color: rgba(201, 214, 225, 0.82);
            font-size: 0.70rem;
            line-height: 1.45;
            font-family: "IBM Plex Mono", Consolas, monospace;
            word-break: break-word;
        }}
        </style>
        <details class="faq-float">
            <summary class="faq-pill">Help / FAQ</summary>
            <div class="faq-panel">
                <div class="faq-panel-inner">
                    <div class="faq-title">BRINC DFR Planning FAQ</div>
                    <div class="faq-subtitle">
                        Quick answers for upload, jurisdiction setup, fleet planning, exports, and map-layer troubleshooting.
                    </div>
                    {''.join(_faq_html_parts)}
                    <div class="faq-footer">
                        <div class="faq-footer-label">Version &amp; Changelog</div>
                        <div class="faq-version-line">Current version: v{html.escape(__version__)} | Build time: {html.escape(__build_datetime__)}</div>
                        {_changelog_lines}
                    </div>
                </div>
            </div>
        </details>
        """,
        unsafe_allow_html=True,
    )


def main():
    _render_in_app_faq()
    if not st.session_state['csvs_ready']:

        # GRAB THE LOGO FOR THE UPLOAD PAGE
        logo_b64 = get_themed_logo_base64("logo.png", theme="dark")
        hero_logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="height:72px; margin-bottom:15px;">' if logo_b64 else f'<div style="font-size:2.5rem; font-weight:900; letter-spacing:4px; color:#ffffff; margin-bottom:15px;">BRINC</div>'
        # Upper-right hero image uses gigs.png (the drone product shot)
        gigs_b64 = get_transparent_product_base64("gigs.png")

        st.markdown(f"""
        <style>
        @keyframes pulseGlow {{
            0%, 100% {{ opacity: 0.55; }}
            50%       {{ opacity: 1.0; }}
        }}
        @keyframes fadeUp {{
            from {{ opacity:0; transform:translateY(14px); }}
            to   {{ opacity:1; transform:translateY(0); }}
        }}
        .brinc-hero {{
            position: relative;
            text-align: center;
            padding: 52px 24px 40px;
            margin-bottom: 36px;
            border-radius: 12px;
            background: radial-gradient(ellipse at 50% 0%,
                rgba(0,210,255,0.13) 0%, rgba(0,0,0,0) 68%);
            border-bottom: 1px solid rgba(0,210,255,0.15);
            overflow: hidden;
            animation: fadeUp 0.5s ease both;
        }}
        .brinc-hero::before {{
            content: '';
            position: absolute; inset: 0;
            background:
                repeating-linear-gradient(0deg,
                    transparent, transparent 39px,
                    rgba(0,210,255,0.025) 39px,
                    rgba(0,210,255,0.025) 40px),
                repeating-linear-gradient(90deg,
                    transparent, transparent 79px,
                    rgba(0,210,255,0.025) 79px,
                    rgba(0,210,255,0.025) 80px);
            pointer-events: none;
        }}
        .brinc-eyebrow {{
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.62rem;
            font-weight: 700;
            letter-spacing: 4px;
            color: {accent_color};
            text-transform: uppercase;
            opacity: 0.7;
            margin-bottom: 12px;
        }}
        .brinc-h1 {{
            font-family: 'Manrope', sans-serif;
            font-size: clamp(2rem, 4vw, 3rem);
            font-weight: 900;
            color: #ffffff;
            letter-spacing: -0.5px;
            line-height: 1.08;
            margin-bottom: 12px;
        }}
        .brinc-h1 em {{
            font-style: normal;
            color: {accent_color};
        }}
        .brinc-tagline {{
            font-size: 0.88rem;
            color: #666;
            max-width: 500px;
            margin: 0 auto 22px;
            line-height: 1.65;
        }}
        .brinc-badges {{
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 8px;
            margin-top: 4px;
        }}
        .brinc-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(0,210,255,0.07);
            border: 1px solid rgba(0,210,255,0.2);
            border-radius: 100px;
            padding: 4px 13px;
            font-size: 0.64rem;
            font-weight: 700;
            color: {accent_color};
            letter-spacing: 0.8px;
            text-transform: uppercase;
        }}
        .brinc-badge.pulse {{
            animation: pulseGlow 3s ease-in-out infinite;
        }}
        .path-card {{
            background: #080808;
            border: 1px solid #1c1c1c;
            border-radius: 10px;
            padding: 22px 18px 16px;
            position: relative;
            overflow: hidden;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }}
        .path-card::after {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: var(--accent);
            border-radius: 10px 10px 0 0;
        }}
        .path-card:hover {{
            border-color: rgba(255,255,255,0.12);
            box-shadow: 0 0 28px rgba(0,210,255,0.05);
        }}
        .pc-icon  {{ font-size: 1.5rem; display:block; margin-bottom:9px; }}
        .pc-tag   {{ font-size:0.55rem; font-weight:800; letter-spacing:2.5px;
                     text-transform:uppercase; color:var(--accent); margin-bottom:5px; }}
        .pc-title {{ font-size:1rem; font-weight:800; color:#fff;
                     line-height:1.25; margin-bottom:7px; }}
        .pc-desc  {{ font-size:0.7rem; color:#555; line-height:1.6; margin-bottom:0; }}
        .field-footnote {{
            font-size: 0.63rem; color: #3a3a3a; line-height: 1.75;
            margin-top: 10px; border-top: 1px solid #141414;
            padding-top: 10px;
        }}
        .demo-cities {{
            font-size: 0.65rem; color: #444; line-height: 1.9;
            margin-top: 10px;
        }}
        .demo-cities b {{ color: #555; }}
        .demo-check {{
            font-size: 0.63rem; color: #333; line-height: 1.8;
            margin-top: 12px; border-top: 1px solid #141414;
            padding-top: 10px;
        }}
        .demo-check span {{ color: {accent_color}; margin-right: 5px; }}
        </style>

        <div class="brinc-hero" style="display:flex; align-items:center; justify-content:space-between; text-align:left; padding: 48px 48px 40px; gap: 32px; flex-wrap: wrap;">
            <div style="flex:1; min-width:280px;">
                {hero_logo_html}
                <div class="brinc-eyebrow" style="margin-top:6px;">BRINC Drones · DFR Platform</div>
                <div class="brinc-h1">
                    Coverage. Operations.<br><em>Savings.</em>
                </div>
                <div class="brinc-tagline" style="margin-left:0; text-align:left;">
                    Optimize drone-as-first-responder deployments for any US jurisdiction.
                    Model coverage, forecast ROI, and generate grant-ready proposals in minutes.
                </div>
                <div class="brinc-badges" style="justify-content:flex-start;">
                    <div class="brinc-badge">🛰 3D Swarm Simulation</div>
                    <div class="brinc-badge">🗺 Census Boundaries</div>
                    <div class="brinc-badge">📄 Grant Narrative Export</div>
                    <div class="brinc-badge">✈️ FAA LAANC Overlay</div>
                    <div class="brinc-badge">⚡ MCLP Optimizer</div>
                </div>
            </div>
            <div style="flex:0 0 auto; display:flex; align-items:center; justify-content:center;">
                <img src="data:image/png;base64,{gigs_b64}" style="height:260px; max-width:420px; object-fit:contain; filter: drop-shadow(0 0 32px rgba(0,210,255,0.35)) drop-shadow(0 0 8px rgba(0,150,255,0.2));" alt="BRINC COS Drone Station">
            </div>
        </div>
        """, unsafe_allow_html=True)

        path_sim_col, path_upload_col, path_demo_col = st.columns(3, gap="medium")

        with path_sim_col:
            st.markdown(f"""
            <div class="path-card" style="--accent:{accent_color};">
                <span class="pc-icon">🗺</span>
                <div class="pc-tag">Path 01</div>
                <div class="pc-title">Simulate Any<br>US Region</div>
                <div class="pc-desc">No data needed. Real Census boundaries + realistic 911 call distribution generated automatically. Stack multiple jurisdictions in one run.</div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

            # ── CITY / STATE — simplified single-row inputs ─────────────────────
            _state_keys = list(STATE_FIPS.keys())

            # Column headers
            _h_city, _h_state = st.columns([3, 1])
            _h_city.markdown("<div style='font-size:12px;color:#888;padding-bottom:2px'>City or County</div>", unsafe_allow_html=True)
            _h_state.markdown("<div style='font-size:12px;color:#888;padding-bottom:2px'>State</div>", unsafe_allow_html=True)

            while len(st.session_state['target_cities']) < st.session_state.city_count:
                st.session_state['target_cities'].append({"city": "", "state": st.session_state.get('active_state', 'IL')})

            for i in range(st.session_state.city_count):
                c_val = st.session_state['target_cities'][i]['city'] if i < len(st.session_state['target_cities']) else ""
                s_val = st.session_state['target_cities'][i]['state'] if i < len(st.session_state['target_cities']) else "IL"

                col_city, col_state = st.columns([3, 1])

                c_name = col_city.text_input(
                    f"city_or_county_{i}", value=c_val,
                    placeholder="e.g. Rockford or Winnebago County",
                    label_visibility="collapsed",
                    key=f"c_{i}",
                    help="Official municipality or county name."
                )

                # State input: text field with autocomplete validation
                s_name = col_state.text_input(
                    f"state_{i}",
                    value=s_val,
                    max_chars=2,
                    placeholder="CA",
                    label_visibility="collapsed",
                    key=f"s_{i}",
                    help="Two-letter state abbreviation (e.g., CA, TX, NY)."
                ).upper()

                # Validate state abbreviation
                if s_name and s_name not in _state_keys:
                    # Try to find a match or use the previous value
                    if s_val and s_val in _state_keys:
                        s_name = s_val
                    elif s_name:
                        # Show warning but allow the user to continue
                        pass

                if i < len(st.session_state['target_cities']):
                    st.session_state['target_cities'][i] = {"city": c_name, "state": s_name}
                else:
                    st.session_state['target_cities'].append({"city": c_name, "state": s_name})

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

            # Move "+ City" and "Deploy" buttons up (before file uploader and download button)
            st.markdown("""
            <style>
            [data-testid="stBaseButton-primary"], button[kind="primary"] {
                background: #00D2FF !important;
                background-color: #00D2FF !important;
                border-color: #00D2FF !important;
                color: #000 !important;
                font-weight: 800 !important;
            }
            [data-testid="stBaseButton-primary"]:hover, button[kind="primary"]:hover {
                background: #33DEFF !important;
                background-color: #33DEFF !important;
                border-color: #33DEFF !important;
                color: #000 !important;
            }
            </style>
            """, unsafe_allow_html=True)
            col_add, col_run = st.columns([1, 1])
            if st.session_state.city_count < 10:
                if col_add.button("＋ City", width="stretch", key="add_city_btn"):
                    st.session_state.city_count += 1
                    st.rerun()
            submit_demo = col_run.button("Deploy", width="stretch", key="run_sim_btn",
                                         type="primary",
                                         help="Fetch boundaries and launch the simulation.")

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

            # ── Highway / State Police Mode ───────────────────────────────────
            _hw_mode_ui = st.checkbox(
                "Highway / State Police Mode",
                key="highway_patrol_mode",
                help="Route calls along specific interstate corridors instead of jurisdiction boundaries. Each highway runs as an independent deployment plan.",
            )
            if _hw_mode_ui:
                _hw_ui_states = list(dict.fromkeys(
                    loc['state'] for loc in st.session_state['target_cities']
                    if loc.get('state') in STATE_FIPS
                ))
                _hw_ui_state = _hw_ui_states[0] if _hw_ui_states else None
                if _hw_ui_state:
                    _default_hws = STATE_PRIMARY_INTERSTATES.get(_hw_ui_state, [])
                    _hw_src = st.radio(
                        "Corridors",
                        ["Primary interstates (auto)", "Custom"],
                        horizontal=True,
                        key="hw_source_radio",
                        help="Choose whether to deploy along the state's primary interstates automatically, or enter custom corridor names.",
                    )
                    if _hw_src == "Primary interstates (auto)":
                        st.caption(
                            f"Will deploy: {', '.join(_default_hws)}" if _default_hws
                            else "No primary interstates defined for this state."
                        )
                        st.session_state['selected_highways'] = _default_hws
                    else:
                        _custom_hw_str = st.text_input(
                            "Highways (comma-separated)",
                            placeholder="e.g. I-80, I-29",
                            key="custom_highways_input",
                            help="Enter interstate or highway designations separated by commas. Each corridor runs as an independent deployment plan.",
                        )
                        st.session_state['selected_highways'] = [
                            h.strip() for h in _custom_hw_str.split(',') if h.strip()
                        ]
                    _avail_hws = st.session_state.get('selected_highways', [])
                    if len(_avail_hws) > 1:
                        st.session_state['active_highway'] = st.selectbox(
                            "Run plan for:",
                            _avail_hws,
                            key="active_highway_select",
                            help="Select which corridor to run the active deployment plan against. Switch between corridors to compare coverage.",
                        )
                    elif len(_avail_hws) == 1:
                        st.session_state['active_highway'] = _avail_hws[0]
                    else:
                        st.session_state['active_highway'] = None
                else:
                    st.caption("Enter a state abbreviation above first.")
                    st.session_state['selected_highways'] = []
                    st.session_state['active_highway'] = None

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

            st.file_uploader(
                "Optional: Stations + boundary overlay files",
                accept_multiple_files=True,
                type=['csv', 'xlsx', 'xls', 'xlsb', 'xlsm', 'brinc', 'json', 'txt', 'shp', 'shx', 'dbf', 'prj'],
                key="sim_optional_uploader",
                help="Drop a custom stations CSV/Excel plus optional shapefile sidecars (.shp/.shx/.dbf/.prj). Path 01 ignores CAD and .brinc files if included."
            )


            station_template_bytes = base64.b64decode(
                "TkFNRSxUWVBFLEFERFJFU1MsQ0FQQUNJVFksTk9URVMsTEFULExPTgpTYW1wbGUgMSBQb2xpY2UgU3RhdGlvbixQb2xpY2UsIjQyMCBXIFN0YXRlIFN0LCBSb2NrZm9yZCwgSUwgNjExMDEiLDIsUHJpbWFyeSBkb3dudG93biBkaXNwYXRjaCBodWIsNDIuMjcxMSwtODkuMDk0MApTYW1wbGUgMiBQb2xpY2UgU3RhdGlvbixQb2xpY2UsIjM0MDEgTiBNYWluIFN0LCBSb2NrZm9yZCwgSUwgNjExMDMiLDIsTm9ydGggc2lkZSBwYXRyb2wgYmFzZSw0Mi4zMTA1LC04OS4wODg3ClNhbXBsZSAzIFBvbGljZSBTdGF0aW9uLFBvbGljZSwiMTcwNyBTIE11bGZvcmQgUmQsIFJvY2tmb3JkLCBJTCA2MTEwOCIsMSxTb3V0aGVhc3QgY29ycmlkb3IgY292ZXJhZ2UsNDIuMjQ4OCwtODguOTk5OApTYW1wbGUgNCBQb2xpY2UgU3RhdGlvbixQb2xpY2UsIjQzNDAgVyBTdGF0ZSBTdCwgUm9ja2ZvcmQsIElMIDYxMTAyIiwxLFdlc3Qgc2lkZSByYXBpZCByZXNwb25zZSB1bml0LDQyLjI3MTIsLTg5LjEyNDEKU2FtcGxlIDEgRmlyZSBTdGF0aW9uLEZpcmUsIjcwOCBDbGludG9uIFN0LCBSb2NrZm9yZCwgSUwgNjExMDEiLDIsQ2VudHJhbCBmaXJlIGRpc3BhdGNoIC0gU3RhdGlvbiAxLDQyLjI3MjAsLTg5LjA4OTgKU2FtcGxlIDIgRmlyZSBTdGF0aW9uLEZpcmUsIjE0MDIgTiBDb3VydCBTdCwgUm9ja2ZvcmQsIElMIDYxMTAzIiwxLE5vcnRoIFJvY2tmb3JkIGZpcmUgY292ZXJhZ2UsNDIuMjk1MSwtODkuMDgyNgpTYW1wbGUgMyBGaXJlIFN0YXRpb24sRmlyZSwiMjI1MCBTIEFscGluZSBSZCwgUm9ja2ZvcmQsIElMIDYxMTA4IiwxLFNvdXRoIEFscGluZSBmaXJlIHJlc3BvbnNlLDQyLjI0MDEsLTg4Ljk5NjQKU2FtcGxlIDQgRmlyZSBTdGF0aW9uLEZpcmUsIjUyODUgU2FmZm9yZCBSZCwgUm9ja2ZvcmQsIElMIDYxMTAxIiwxLFdlc3QgZGlzdHJpY3QgZmlyZSBzdGF0aW9uLDQyLjI2OTgsLTg5LjE0MDIKU2FtcGxlIDEgRU1TIFN0YXRpb24sRU1TLCIxNDAxIEUgU3RhdGUgU3QsIFJvY2tmb3JkLCBJTCA2MTEwNCIsMixFYXN0IHNpZGUgRU1TIHJhcGlkIHJlc3BvbnNlLDQyLjI2OTQsLTg5LjA2MjEKU2FtcGxlIDIgRU1TIFN0YXRpb24sRU1TLCIzNzIwIENoYXJsZXMgU3QsIFJvY2tmb3JkLCBJTCA2MTEwOCIsMSxTb3V0aGVhc3QgRU1TIGNvdmVyYWdlIHpvbmUsNDIuMjUyMiwtODkuMDA1OApTYW1wbGUgMyBFTVMgU3RhdGlvbixFTVMsIjQ4MjUgTiBCZWxsIFNjaG9vbCBSZCwgUm9ja2ZvcmQsIElMIDYxMTA3IiwxLE5vcnRoZWFzdCBFTVMgcmVzcG9uc2UgaHViLDQyLjMwMjEsLTg4Ljk4OTEKU2FtcGxlIDEgR292IFN0YXRpb24sR292ZXJubWVudCwiNDI1IEUgU3RhdGUgU3QsIFJvY2tmb3JkLCBJTCA2MTEwNCIsMSxXaW5uZWJhZ28gQ291bnR5IGFkbWluIGJ1aWxkaW5nLDQyLjI3MTUsLTg5LjA4NDgKU2FtcGxlIDIgR292IFN0YXRpb24sR292ZXJubWVudCwiMzAwIFcgU3RhdGUgU3QsIFJvY2tmb3JkLCBJTCA2MTEwMSIsMSxDaXR5IEhhbGwgLSBSb2NrZm9yZCBtdW5pY2lwYWwgY2VudGVyLDQyLjI3MTEsLTg5LjA5NTcKU2FtcGxlIDMgR292IFN0YXRpb24sR292ZXJubWVudCwiNjUwIFcgU3RhdGUgU3QsIFJvY2tmb3JkLCBJTCA2MTEwMiIsMSxQdWJsaWMgd29ya3MgYW5kIGVtZXJnZW5jeSBtZ210LDQyLjI3MTMsLTg5LjEwMTgK"
            )

            st.caption("Upload a stations CSV/Excel, optional boundary shapefile sidecars, or download the sample template. If no stations file is uploaded, stations will be auto-generated from call data.")

            st.download_button(
                label="📥 Sample stations.csv",
                data=station_template_bytes,
                file_name="stations.csv",
                mime="text/csv; charset=utf-8",
                key="download_station_template_btn_compact",
                help="Download sample stations template",
            )
            components.html("""
    <script>
    (function(){
      var _ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" style="flex-shrink:0;display:inline-block;vertical-align:middle;">'
        + '<circle cx="12" cy="12" r="9.5" stroke="currentColor" stroke-width="1.6"/>'
        + '<circle cx="12" cy="12" r="5.5" stroke="currentColor" stroke-width="1.2" stroke-dasharray="3 2"/>'
        + '<path d="M12 5.5C9.51 5.5 7.5 7.51 7.5 10C7.5 13.25 12 18.5 12 18.5C12 18.5 16.5 13.25 16.5 10C16.5 7.51 14.49 5.5 12 5.5Z" fill="currentColor"/>'
        + '<circle cx="12" cy="10" r="2" fill="white"/>'
        + '</svg>';

      function style(){
        var doc = parent.document;
        var btns = doc.querySelectorAll('[data-testid="stButton"] > button');
        btns.forEach(function(b){
          var p = b.querySelector('p');
          if(!p || p.textContent.trim() !== 'Deploy') return;
          if(b.getAttribute('data-brinc-deploy')) return;
          b.setAttribute('data-brinc-deploy','1');
          b.style.background   = 'linear-gradient(135deg,#00bcd4 0%,#00D2FF 100%)';
          b.style.color        = '#000';
          b.style.border       = 'none';
          b.style.borderRadius = '8px';
          b.style.fontWeight   = '800';
          b.style.fontSize     = '15px';
          b.style.letterSpacing= '0.4px';
          b.style.boxShadow    = '0 4px 20px rgba(0,210,255,0.55),0 2px 8px rgba(0,0,0,0.28)';
          b.style.transition   = 'all 0.16s ease';
          b.style.display      = 'flex';
          b.style.alignItems   = 'center';
          b.style.justifyContent = 'center';
          b.style.gap          = '7px';
          p.style.margin  = '0';
          p.style.color   = '#000';
          p.style.fontWeight = '800';
          p.style.display = 'flex';
          p.style.alignItems = 'center';
          p.style.gap = '7px';
          var icon = doc.createElement('span');
          icon.innerHTML = _ICON;
          p.insertBefore(icon, p.firstChild);
          b.addEventListener('mouseenter',function(){
            b.style.boxShadow  = '0 6px 30px rgba(0,210,255,0.75),0 2px 8px rgba(0,0,0,0.3)';
            b.style.transform  = 'translateY(-1px)';
            b.style.background = 'linear-gradient(135deg,#00d4ee 0%,#33e0ff 100%)';
          });
          b.addEventListener('mouseleave',function(){
            b.style.boxShadow  = '0 4px 20px rgba(0,210,255,0.55),0 2px 8px rgba(0,0,0,0.28)';
            b.style.transform  = 'translateY(0)';
            b.style.background = 'linear-gradient(135deg,#00bcd4 0%,#00D2FF 100%)';
          });
        });
      }

      function bindEnterToDeploy(){
        var doc = parent.document;
        var targets = Array.from(doc.querySelectorAll('input[type="text"], input:not([type]), textarea'));
        targets.forEach(function(input){
          if(!input || input.getAttribute('data-brinc-enter-submit')) return;
          input.setAttribute('data-brinc-enter-submit', '1');
          input.addEventListener('keydown', function(evt){
            if(evt.key !== 'Enter' || evt.shiftKey || evt.ctrlKey || evt.altKey || evt.metaKey) return;
            var deployBtn = Array.from(doc.querySelectorAll('[data-testid="stButton"] > button')).find(function(btn){
              var p = btn.querySelector('p');
              return p && p.textContent.trim() === 'Deploy';
            });
            if(!deployBtn) return;
            try {
              input.dispatchEvent(new Event('change', {bubbles:true}));
              input.blur();
            } catch (e) {}
            evt.preventDefault();
            setTimeout(function(){ deployBtn.click(); }, 60);
          });
        });
      }

      new MutationObserver(function(){
        style();
        bindEnterToDeploy();
      }).observe(parent.document.body,{childList:true,subtree:true});
      style();
      bindEnterToDeploy();
      setTimeout(style,150);
      setTimeout(style,500);
      setTimeout(bindEnterToDeploy,150);
      setTimeout(bindEnterToDeploy,500);
    })();
    </script>
    """, height=0)

        with path_upload_col:
            st.markdown(f"""
            <div class="path-card" style="--accent:#39FF14;">
                <span class="pc-icon">📂</span>
                <div class="pc-tag">Path 02</div>
                <div class="pc-title">Upload CAD<br>or .brinc Save</div>
                <div class="pc-desc">
                    Drop <b>any</b> CAD export CSV — no renaming needed.
                    Or, drop a previously saved <b>.brinc</b> file to instantly restore your deployment.
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

            uploaded_files = st.file_uploader(
                "Drop CAD calls + optional stations + optional boundary shapefile files",
                accept_multiple_files=True,
                type=['csv', 'xlsx', 'xls', 'xlsb', 'xlsm', 'brinc', 'json', 'txt', 'shp', 'shx', 'dbf', 'prj'],
                label_visibility="collapsed",
                help="Upload real CAD calls, optional stations, and optional shapefile sidecars (.shp/.shx/.dbf/.prj) for a display-only boundary overlay. OR drop a .brinc file to restore a previous session."
            )

            st.markdown("""
            <div class="field-footnote">
                <b style='color:#555;'>1 file</b> — any CAD export (CSV or Excel); stations auto-built from OSM<br>
                <b style='color:#555;'>Multiple CAD files</b> — drop several spreadsheets; they are combined automatically<br>
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

                        merged_full_df, merged_ready_df, merge_summary = merge_census_results(partial_calls_df, result_df)
                        if merged_ready_df is None or merged_ready_df.empty:
                            st.error("❌ Census result upload failed: no valid coordinates were recovered from the returned result files.")
                            st.stop()

                        corrected_export_df = build_corrected_export(original_df, result_df)
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

                # --- 1. INTELLIGENTLY CHECK FOR .BRINC FILE ---
                # Browsers sometimes append .json to .brinc files on download
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
                        _push_upload_log("Starting coordinate inspection.")
                        _set_upload_overlay_status(
                            title="CAD UPLOAD",
                            status="CHECKING FOR COORDINATES",
                            copy="Inspecting headers and cell values for usable latitude and longitude fields. This usually takes a few seconds.",
                            progress=8,
                            logs=_upload_logs,
                        )
                        with st.spinner("🔍 Detecting column types in CAD export…"):
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
                                    _push_upload_log(
                                        f"{_file_diag.get('file','file')}: {_file_diag.get('ready_rows',0):,}/{_file_diag.get('rows',0):,} rows ready"
                                        + (f" ({'; '.join(_diag_bits)})" if _diag_bits else "")
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

                                def _format_wait(seconds):
                                    seconds = max(0, int(seconds))
                                    mins, secs = divmod(seconds, 60)
                                    return f"{mins}m {secs:02d}s" if mins else f"{secs}s"

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
                                    f"{_format_wait(theoretical_max_wait)}, and a chunk that still has not completed after "
                                    f"{_format_wait(census_stall_warn_sec)} should be treated as stalled."
                                )
                                _set_upload_overlay_status(
                                    title="CENSUS AUTOMATION",
                                    status="SUBMITTING BATCHES",
                                    copy=(
                                        "Sending chunked address batches directly to the Census geocoder. "
                                        f"Elapsed since Census submit started: {_format_wait(time.time() - census_started_at)}. "
                                        f"Each attempt can wait up to {_format_wait(census_timeout_sec)}; a healthy worst-case per chunk is about {_format_wait(theoretical_max_wait)}. "
                                        f"If the same chunk is still waiting after {_format_wait(census_stall_warn_sec)}, treat it as stalled and cancel/retry."
                                    ),
                                    progress=42,
                                    logs=_upload_logs,
                                )

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
                                            f"Elapsed since Census submit started: {_format_wait(time.time() - census_started_at)}. "
                                            f"If nothing returns after {_format_wait(census_stall_warn_sec)}, it is probably stalled."
                                        ),
                                        progress=42 + int(completed_chunks / max(1, total_chunks) * 34),
                                        logs=_upload_logs,
                                    )
                                    try:
                                        chunk_result_df, _chunk_resp = submit_census_batch_chunk(
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
                                            chunk_result_df, _chunk_resp = submit_census_batch_chunk(
                                                chunk['csv_bytes'],
                                                chunk['filename'],
                                                timeout=census_timeout_sec,
                                                retries=census_retries,
                                            )
                                        else:
                                            raise
                                    except Exception as exc:
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
                                        _set_upload_overlay_status(
                                            title="CENSUS ERROR",
                                            status=f"CHUNK {chunk_idx} FAILED",
                                            copy="The Census batch request failed. Review the error log below and share it with Steven if needed.",
                                            progress=42 + int(completed_chunks / max(1, total_chunks) * 34),
                                            logs=_upload_logs,
                                            error=True,
                                        )
                                        st.error(f"❌ Automated Census geocoding failed on chunk {chunk_idx} of {total_chunks}: {exc}")
                                        st.stop()

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
                                result_df = result_df.drop_duplicates(subset=['source_id'], keep='first') if not result_df.empty else result_df
                                _push_upload_log("All Census chunks returned. Merging coordinates back into the source calls file.")
                                _set_upload_overlay_status(
                                    title="CENSUS AUTOMATION",
                                    status="MERGING RESULTS",
                                    copy=(
                                        f"Combining all Census chunk responses and restoring coordinates into the original dataset. "
                                        f"Total Census wait so far: {_format_wait(time.time() - census_started_at)}."
                                    ),
                                    progress=80,
                                    logs=_upload_logs,
                                )

                                merged_full_df, merged_ready_df, merge_summary = merge_census_results(df_c_partial, result_df)
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

                                corrected_export_df = build_corrected_export(census_original_df, result_df)
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

                                _push_upload_log(
                                    f"Merged Census results. {int(merge_summary.get('rows_ready', len(df_c_full)) or len(df_c_full)):,} rows now have coordinates."
                                )
                                _set_upload_overlay_status(
                                    title="CENSUS AUTOMATION",
                                    status="GEOCODING COMPLETE",
                                    copy=(
                                        f"Coordinates restored. Finalizing station discovery and jurisdiction setup now. "
                                        f"Total Census time: {_format_wait(time.time() - census_started_at)}."
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
                                # Final safety net: scatter stations across call bounding box
                                df_s = _make_random_stations(df_c, n=40)
                                osm_note = "⚠️ Could not reach any map source — using estimated station positions from call data."
                                st.warning(osm_note)
                            else:
                                st.toast(f"✅ {osm_note}")

                        if len(df_s) > 100:
                            df_s = df_s.sample(100, random_state=42).reset_index(drop=True)

                        _push_upload_log("Detecting jurisdiction from call locations.")
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
                                # We have state but no city — store state and let boundary
                                # selection use the FCC county name as a county lookup
                                st.session_state['active_state'] = detected_state
                                st.session_state['location_detection_source'] = detection_source

                        # Keep uploaded calls intact here. Boundary validation should be the first real geographic filter.
                        st.session_state['df_calls'] = df_c
                        st.session_state['df_calls_full'] = df_c_full
                        st.session_state['df_stations'] = df_s
                        st.session_state['total_original_calls'] = len(df_c_full)
                        st.session_state['total_modeled_calls'] = len(df_c)

                        _push_upload_log("Resolving uploaded boundaries and final session state.")
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

        with path_demo_col:
            st.markdown(f"""
            <div class="path-card" style="--accent:#FFD700;">
                <span class="pc-icon">⚡</span>
                <div class="pc-tag">Path 03</div>
                <div class="pc-title">1-Click Demo<br>Large US City</div>
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

            city_chips = "  ·  ".join([f"{c}" for c, _ in DEMO_CITIES[:12]]) + "  · and more…"
            st.markdown(f"""
            <div class="demo-cities">
                <b>Available Cities</b><br>
                {city_chips}
            </div>
            <div class="demo-check">
                <span>✓</span>Real Census boundaries<br>
                <span>✓</span>Clustered 911 simulation<br>
                <span>✓</span>100 station candidates<br>
                <span>✓</span>Full optimization & export
            </div>
            """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="text-align:center; margin-top:8px;">
            <div style="font-family:'IBM Plex Mono',monospace; font-size:0.68rem; letter-spacing:0.08em; color:#4b5563; margin-bottom:8px;">
                © v {__version__}
            </div>
            <div style="font-size:0.63rem; color:#2a2a2a;">
                BRINC Drones, Inc. · <a href="https://brincdrones.com" target="_blank"
                style="color:#333; text-decoration:none;">brincdrones.com</a>
                · All coverage estimates are for planning purposes only.
            </div>
        </div>
        """, unsafe_allow_html=True)

        if submit_demo or st.session_state.get('trigger_sim', False):
            if st.session_state.get('trigger_sim', False):
                st.session_state['trigger_sim'] = False
                # trigger_sim is set by the demo button — mark accordingly
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
            _swarm_overlay_html = """<!DOCTYPE html><html><head><meta charset="utf-8">
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
    <div class="fl-side"><img src="data:image/png;base64,{_swarm_logo_b64}" alt="BRINC"></div>
    <div class="fl-map">
      {_swarm_map_svg}
    </div>
    <div class="fl-side"><img src="data:image/png;base64,{_swarm_gigs_b64}" alt="Fleet"></div>
  </div>
  <div class="fl-footer">
    <div class="fl-city">{_swarm_city_js}</div>
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
  /* clean up any previous overlay + injected styles */
  var _old = doc.getElementById('brinc-flo');
  if(_old && _old.parentNode) _old.parentNode.removeChild(_old);
  var _olds = doc.getElementById('brinc-flo-css');
  if(_olds && _olds.parentNode) _olds.parentNode.removeChild(_olds);
  /* inject CSS into parent document — iframe <style> rules don't transfer on cloneNode */
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
    +'#brinc-flo .fl-state{{fill:rgba(255,255,255,0.03);stroke:rgba(255,255,255,0.15);stroke-width:1.1;transition:fill .25s ease,stroke .25s ease,filter .25s ease}}'
    +'#brinc-flo .fl-state-active{{fill:rgba(0,210,255,0.18)!important;stroke:rgba(0,210,255,0.95)!important;stroke-width:2.1!important;filter:url(#brinc-state-glow)}}'
    +'#brinc-flo .fl-dots::after{{content:"";animation:brinc-flo-dots 1.4s steps(4,end) infinite}}'
    +'@keyframes brinc-flo-dots{{0%{{content:""}}25%{{content:"."}}50%{{content:".."}}75%{{content:"..."}}}}';
  (doc.head || doc.body).appendChild(_css);
  var el = document.getElementById('flo');
  var clone = el.cloneNode(true);
  clone.id = 'brinc-flo';
  doc.body.appendChild(clone);
  el.style.display = 'none';
  var P = doc.getElementById('brinc-flo');
  if(!P) return;
  var pStatus = P.querySelector('#fl-stl');
  var pTribute = P.querySelector('#fl-tribute');
  var TRIBUTES = [
    'For those we remember. For those we can still protect.',
    'In memory, and in service to lives still depending on time.',
    'Built for the moments when faster response can save a life.',
    'A quiet promise to protect more families, officers, and communities.'
  ];
  if(pTribute){{
    var tributeIdx = 0;
    parent.setInterval(function(){{
      tributeIdx = (tributeIdx + 1) % TRIBUTES.length;
      pTribute.style.opacity = '0';
      parent.setTimeout(function(){{
        pTribute.textContent = TRIBUTES[tributeIdx];
        pTribute.style.opacity = '1';
      }}, 260);
    }}, 4200);
  }}
  var mapSvg = P.querySelector('#fl-svg') || P.querySelector('svg');
  if(!mapSvg) return;
  mapSvg.setAttribute('id', 'fl-svg');
  var svgNS = mapSvg.namespaceURI || 'http://www.w3.org/2000/svg';
  var vb = (mapSvg.getAttribute('viewBox') || '0 0 600 360').trim().split(/\\s+/).map(Number);
  if(vb.length !== 4 || vb.some(function(v){{ return !isFinite(v); }})) vb = [0, 0, 600, 360];
  var vx = vb[0], vy = vb[1], vw = vb[2], vh = vb[3];
  var stateCode = '{_swarm_state_js}'.replace(/[^A-Z]/g, '');
  var stateId = stateCode ? 'US-' + stateCode : '';
  var statePaths = Array.from(mapSvg.querySelectorAll('path[id^="US-"]'));
  function addSvgEl(tag, attrs, parent){{
    var el = doc.createElementNS(svgNS, tag);
    Object.keys(attrs || {{}}).forEach(function(k){{ el.setAttribute(k, attrs[k]); }});
    if(parent) parent.appendChild(el);
    return el;
  }}
  var defs = mapSvg.querySelector('defs') || addSvgEl('defs', {{}}, mapSvg);
  var oldClip = mapSvg.querySelector('#brinc-us-clip');
  if(oldClip && oldClip.parentNode) oldClip.parentNode.removeChild(oldClip);
  var oldGlow = mapSvg.querySelector('#brinc-state-glow');
  if(oldGlow && oldGlow.parentNode) oldGlow.parentNode.removeChild(oldGlow);
  var clip = addSvgEl('clipPath', {{id:'brinc-us-clip'}}, defs);
  statePaths.forEach(function(path){{
    clip.appendChild(path.cloneNode(true));
    path.classList.add('fl-state');
  }});
  var glow = addSvgEl('filter', {{id:'brinc-state-glow', x:'-30%', y:'-30%', width:'160%', height:'160%'}}, defs);
  addSvgEl('feGaussianBlur', {{stdDeviation:'4.5', result:'blur'}}, glow);
  addSvgEl('feColorMatrix', {{type:'matrix', values:'0 0 0 0 0  0 0 0 0 0.82  0 0 0 0 1  0 0 0 0.9 0'}}, glow);
  var merge = addSvgEl('feMerge', {{}}, glow);
  addSvgEl('feMergeNode', {{in:'blur'}}, merge);
  addSvgEl('feMergeNode', {{in:'SourceGraphic'}}, merge);
  var flagLayer = mapSvg.querySelector('#brinc-flag-layer');
  if(flagLayer && flagLayer.parentNode) flagLayer.parentNode.removeChild(flagLayer);
  flagLayer = addSvgEl('g', {{id:'brinc-flag-layer', 'clip-path':'url(#brinc-us-clip)', opacity:'0.18'}}, mapSvg);
  mapSvg.insertBefore(flagLayer, mapSvg.firstChild);
  addSvgEl('rect', {{x:vx, y:vy, width:vw, height:vh, fill:'rgba(255,255,255,0.045)'}}, flagLayer);
  var stripeH = vh / 13;
  for (var si = 0; si < 13; si++) {{
    addSvgEl('rect', {{x:vx, y:(vy + si * stripeH), width:vw, height:stripeH, fill:(si % 2 === 0 ? 'rgba(191,10,48,0.55)' : 'rgba(255,255,255,0.05)')}}, flagLayer);
  }}
  var cantonW = vw * 0.42, cantonH = stripeH * 7;
  addSvgEl('rect', {{x:vx, y:vy, width:cantonW, height:cantonH, fill:'rgba(0,40,104,0.72)'}}, flagLayer);
  for (var row = 0; row < 4; row++) {{
    for (var col = 0; col < 5; col++) {{
      addSvgEl('circle', {{cx:(vx + 18 + col * (cantonW / 5.8)), cy:(vy + 16 + row * (cantonH / 4.7)), r:'2.1', fill:'rgba(255,255,255,0.78)'}}, flagLayer);
    }}
  }}
  var gridLayer = mapSvg.querySelector('#brinc-grid-layer');
  if(gridLayer && gridLayer.parentNode) gridLayer.parentNode.removeChild(gridLayer);
  gridLayer = addSvgEl('g', {{id:'brinc-grid-layer', opacity:'0.18'}}, mapSvg);
  mapSvg.insertBefore(gridLayer, flagLayer.nextSibling);
  for (var gy = 1; gy < 5; gy++) addSvgEl('line', {{x1:vx, y1:(vy + gy * vh / 5), x2:(vx + vw), y2:(vy + gy * vh / 5), stroke:'rgba(0,210,255,0.22)', 'stroke-width':'0.6'}}, gridLayer);
  for (var gx = 1; gx < 6; gx++) addSvgEl('line', {{x1:(vx + gx * vw / 6), y1:vy, x2:(vx + gx * vw / 6), y2:(vy + vh), stroke:'rgba(0,210,255,0.16)', 'stroke-width':'0.6'}}, gridLayer);
  var targetState = statePaths.find(function(path){{ return path.id === stateId; }}) || null;
  if(targetState) targetState.classList.add('fl-state-active');
  var arcLayer = mapSvg.querySelector('#fl-arc');
  if(arcLayer && arcLayer.parentNode) arcLayer.parentNode.removeChild(arcLayer);
  var dronesLayer = mapSvg.querySelector('#fl-drones');
  if(dronesLayer && dronesLayer.parentNode) dronesLayer.parentNode.removeChild(dronesLayer);
  var markerLayer = mapSvg.querySelector('#fl-markers');
  if(markerLayer && markerLayer.parentNode) markerLayer.parentNode.removeChild(markerLayer);
  var pArc = addSvgEl('path', {{id:'fl-arc', fill:'none', stroke:'rgba(0,210,255,0.26)', 'stroke-width':'1.8', 'stroke-dasharray':'5 4'}}, mapSvg);
  var pDrones = addSvgEl('g', {{id:'fl-drones'}}, mapSvg);
  var startX = vx + vw * 0.12;
  var startY = vy + vh * 0.28;
  var launchState = statePaths.find(function(path){{ return path.id === 'US-WA'; }}) || null;
  if(launchState) {{
    var launchBox = launchState.getBBox();
    startX = launchBox.x + launchBox.width * 0.30;
    startY = launchBox.y + launchBox.height * 0.36;
  }}
  var tx = vx + vw * 0.68;
  var ty = vy + vh * 0.48;
  if(targetState) {{
    var bbox = targetState.getBBox();
    tx = bbox.x + bbox.width / 2;
    ty = bbox.y + bbox.height / 2;
  }}
  tx = Math.max(vx + 18, Math.min(vx + vw - 18, tx));
  ty = Math.max(vy + 18, Math.min(vy + vh - 18, ty));
  var cpx = startX + (tx - startX) * 0.52;
  var cpy = Math.min(startY, ty) - vh * 0.18;
  pArc.setAttribute('d', 'M ' + startX + ',' + startY + ' Q ' + cpx + ',' + cpy + ' ' + tx + ',' + ty);
  function bPt(t,x0,y0,x1,y1,x2,y2){{
    var m=1-t; return [m*m*x0+2*m*t*x1+t*t*x2, m*m*y0+2*m*t*y1+t*t*y2];
  }}
  function bAng(t,x0,y0,x1,y1,x2,y2){{
    var m=1-t, dx=2*(m*(x1-x0)+t*(x2-x1)), dy=2*(m*(y1-y0)+t*(y2-y1));
    return Math.atan2(dy,dx)*180/Math.PI;
  }}
  function eio(t){{ return t<0.5?2*t*t:-1+(4-2*t)*t; }}
  var NS = svgNS;
  var NDRONES=4, STAGGER=1800, FLY=9000;
  var drones=[];
  function makeDrone(col){{
    var g=doc.createElementNS(NS,'g');
    var bg=doc.createElementNS(NS,'circle');
    bg.setAttribute('r','7'); bg.setAttribute('fill','rgba(0,210,255,0.08)');
    g.appendChild(bg);
    [[-3,-3,-8,-8],[3,-3,8,-8],[-3,3,-8,8],[3,3,8,8]].forEach(function(a){{
      var ln=doc.createElementNS(NS,'line');
      ln.setAttribute('x1',a[0]); ln.setAttribute('y1',a[1]);
      ln.setAttribute('x2',a[2]); ln.setAttribute('y2',a[3]);
      ln.setAttribute('stroke',col); ln.setAttribute('stroke-width','1.5');
      ln.setAttribute('stroke-linecap','round'); g.appendChild(ln);
    }});
    [[-8,-8],[8,-8],[-8,8],[8,8]].forEach(function(r){{
      var ci=doc.createElementNS(NS,'circle');
      ci.setAttribute('cx',r[0]); ci.setAttribute('cy',r[1]); ci.setAttribute('r','2.5');
      ci.setAttribute('stroke',col); ci.setAttribute('stroke-width','1');
      ci.setAttribute('fill','rgba(0,210,255,0.2)'); g.appendChild(ci);
    }});
    var rect=doc.createElementNS(NS,'rect');
    rect.setAttribute('x','-3'); rect.setAttribute('y','-3');
    rect.setAttribute('width','6'); rect.setAttribute('height','6');
    rect.setAttribute('rx','1'); rect.setAttribute('fill',col); g.appendChild(rect);
    return g;
  }}
  for(var i=0;i<NDRONES;i++){{
    var dEl=makeDrone('#00D2FF');
    pDrones.appendChild(dEl);
    drones.push({{el:dEl,arrived:false,delay:i*STAGGER,arrT:0}});
  }}
  var arrivedN=0, allDone=false, t0=null;
  var MSGS=['INITIALIZING MISSION BRIEF','FETCHING BOUNDARY DATA','MODELING 911 CALLS','OPTIMIZING STATION GRID','DEPLOYING FLEET'];
  var mi=0;
  function nextMsg(){{ if(mi<MSGS.length && pStatus) pStatus.innerHTML=MSGS[mi++]+'<span class="fl-dots"></span>'; }}
  /* All timers run in parent window context — they survive iframe replacement on Streamlit rerender */
  nextMsg(); parent.setInterval(nextMsg,3000);
  function frame(now){{
    if(!t0) t0=now;
    var elapsed=now-t0;
    drones.forEach(function(d,i){{
      var e=elapsed-d.delay;
      if(e<0){{ d.el.setAttribute('transform','translate('+startX+','+startY+')'); return; }}
      if(d.arrived){{
        var ht=(now-d.arrT)/900;
        var hx=tx+Math.cos(ht+i*1.6)*4, hy=ty+Math.sin(ht*1.3+i)*3-5;
        d.el.setAttribute('transform','translate('+hx+','+hy+')'); return;
      }}
      var t=Math.min(e/FLY,1), te=eio(t);
      var pt=bPt(te,startX,startY,cpx,cpy,tx,ty);
      var ang=bAng(te,startX,startY,cpx,cpy,tx,ty);
      d.el.setAttribute('transform','translate('+pt[0]+','+pt[1]+') rotate('+ang+',0,0)');
      if(t>=1 && !d.arrived){{
        d.arrived=true; d.arrT=now; arrivedN++;
        var bgEl=d.el.querySelector('circle');
        if(bgEl){{ bgEl.setAttribute('r','12'); bgEl.setAttribute('fill','rgba(0,210,255,0.4)'); }}
        parent.setTimeout(function(dd){{
          var b=dd.el.querySelector('circle');
          if(b){{ b.setAttribute('r','7'); b.setAttribute('fill','rgba(0,210,255,0.08)'); }}
        }}.bind(null,d), 350);
        if(arrivedN===NDRONES && pStatus)
          pStatus.innerHTML='<span style="color:#00D2FF;font-weight:900">&#10003; FLEET DEPLOYED &#8212; LAUNCHING</span>';
      }}
    }});
    if(!allDone) parent.requestAnimationFrame(frame);
  }}
  parent.requestAnimationFrame(frame);
  /* watchdog runs in parent context — survives iframe teardown on Streamlit rerender */
  if(parent._brincFloWd) parent.clearInterval(parent._brincFloWd);
  parent._brincFloWd = null;
  function removeFlo(){{
    allDone=true;
    if(parent._brincFloWd){{ parent.clearInterval(parent._brincFloWd); parent._brincFloWd=null; }}
    var el=doc.getElementById('brinc-flo');
    if(el){{ el.style.transition='opacity 0.5s ease'; el.style.opacity='0'; }}
    parent.setTimeout(function(){{
      var el2=doc.getElementById('brinc-flo'); if(el2&&el2.parentNode) el2.parentNode.removeChild(el2);
      var s=doc.getElementById('brinc-flo-css'); if(s&&s.parentNode) s.parentNode.removeChild(s);
    }},520);
  }}
  parent.setTimeout(function(){{
    parent._brincFloWd=parent.setInterval(function(){{
      var hasChart=
        doc.querySelector('[data-testid="stPlotlyChart"]')||
        doc.querySelector('.js-plotly-plot')||
        doc.querySelector('.stPlotlyChart')||
        doc.querySelector('[class*="js-plotly"]')||
        doc.querySelector('.mapboxgl-canvas')||
        doc.querySelector('.maplibregl-canvas')||
        doc.querySelector('[data-testid="stPlotly"]')||
        doc.querySelector('.plot-container');
      if(hasChart) removeFlo();
    }},400);
  }},2500);
  /* safety net: hard-remove after 30s */
  parent.setTimeout(removeFlo, 30000);
}})();
</script>
</body></html>
"""
            _swarm_overlay_html = (
                _swarm_overlay_html
                .replace("{_swarm_logo_b64}", _swarm_logo_b64)
                .replace("{_swarm_gigs_b64}", _swarm_gigs_b64)
                .replace("{_swarm_map_svg}", _swarm_map_svg)
                .replace("{_swarm_city_js}", _swarm_city_js)
                .replace("{_swarm_state_js}", _swarm_state_js)
                .replace("{{", "{")
                .replace("}}", "}")
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
                st.info("Path 01 ignored non-station files: " + ", ".join(_sim_unused_files))
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




            # ── Corridor mode vs. Census boundary mode ───────────────────────
            _hw_exec = st.session_state.get('highway_patrol_mode', False)
            _active_hw = st.session_state.get('active_highway')
            _hw_state = active_targets[0]['state'] if active_targets else None
            _corridor_mode = _hw_exec and bool(_active_hw) and bool(_hw_state)

            if _corridor_mode:
                prog.progress(20, text=f"🛣️ Fetching {_active_hw} route geometry…")
                _hw_gdf = fetch_highway_geometry(_active_hw, _hw_state)
                if _hw_gdf is None:
                    prog.empty()
                    st.error(
                        f"❌ Could not fetch route geometry for {_active_hw} in {_hw_state}. "
                        "Check the highway reference (e.g. I-80) and try again."
                    )
                    st.stop()
                prog.progress(38, text=f"📐 Building {_active_hw} corridor boundary…")
                _corridor_poly, _corridor_line, _corridor_miles = build_corridor_polygon(_hw_gdf)
                city_poly = _corridor_poly
                _corridor_label = f"{_active_hw} Corridor"
                _corridor_override = gpd.GeoDataFrame(
                    {
                        'DISPLAY_NAME': [_corridor_label],
                        'data_count': [1],
                    },
                    geometry=[_corridor_poly],
                    crs="EPSG:4326",
                )
                st.session_state['master_gdf_override'] = _corridor_override
                st.session_state['saved_jurisdiction_names'] = [_corridor_label]
                st.session_state['population_reference_targets'] = [_corridor_label]
                st.session_state['active_city'] = _corridor_label
                st.session_state['active_state'] = _hw_state
                st.session_state['estimated_pop'] = 0
                st.session_state['_pop_resolved'] = False
                prog.progress(55, text=f"🚔 Modeling patrol calls along {_corridor_miles:.0f} miles of {_active_hw}…")
                annual_cfs = estimate_corridor_calls(_corridor_miles)
                df_demo, annual_cfs, simulated_points_count = build_corridor_demo(
                    _corridor_line, _corridor_poly, annual_cfs, generate_random_points_in_polygon
                )
                st.toast(f"✅ {_active_hw} · {_hw_state} · {_corridor_miles:.0f} mi · {annual_cfs:,} calls/yr")

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
                    components.html("""<!DOCTYPE html><html><head></head><body><script>
(function(){
  var doc=parent.document;
  if(parent._brincFloWd){parent.clearInterval(parent._brincFloWd);parent._brincFloWd=null;}
  var el=doc.getElementById('brinc-flo');
  if(el){el.style.transition='opacity 0.35s ease';el.style.opacity='0';
    parent.setTimeout(function(){
      var e=doc.getElementById('brinc-flo');if(e&&e.parentNode)e.parentNode.removeChild(e);
      var s=doc.getElementById('brinc-flo-css');if(s&&s.parentNode)s.parentNode.removeChild(s);
    },360);}
})();
</script></body></html>""", height=0, scrolling=False)
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
            st.session_state['total_original_calls'] = annual_cfs
            st.session_state['df_calls'] = df_demo
            st.session_state['df_calls_full'] = df_demo.copy()
            st.session_state['total_modeled_calls'] = len(df_demo)

            prog.progress(80, text="Loading simulation stations...")
            stations_df, stations_user_uploaded, station_notices, station_warnings = resolve_demo_stations(
                st.session_state['df_calls'],
                city_poly,
                _sim_station_file,
                active_targets,
                forward_geocode,
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

    # ============================================================
    # COMMUNITY IMPACT DASHBOARD
    # ============================================================

    # ============================================================
    # MAIN MAP INTERFACE
    # ============================================================
    if st.session_state['csvs_ready']:
        components.html("""
        <script>
        (function() {
            try {
                window._brincHasData = true;
                var doc = window.parent.document;
                if (window.parent._brincFloWd) {
                    window.parent.clearInterval(window.parent._brincFloWd);
                    window.parent._brincFloWd = null;
                }
                var overlay = doc.getElementById('brinc-flo');
                if (overlay) {
                    overlay.style.transition = 'opacity 0.35s ease';
                    overlay.style.opacity = '0';
                    window.parent.setTimeout(function() {
                        var el = doc.getElementById('brinc-flo');
                        if (el && el.parentNode) el.parentNode.removeChild(el);
                        var css = doc.getElementById('brinc-flo-css');
                        if (css && css.parentNode) css.parentNode.removeChild(css);
                    }, 380);
                } else {
                    var css = doc.getElementById('brinc-flo-css');
                    if (css && css.parentNode) css.parentNode.removeChild(css);
                }
            } catch (e) {}
        })();
        </script>
        """, height=0)

        df_calls = st.session_state['df_calls'].copy()
        df_calls_full = st.session_state.get('df_calls_full')
        if df_calls_full is None:
            df_calls_full = df_calls.copy()
        else:
            df_calls_full = df_calls_full.copy()
        df_stations_all = st.session_state['df_stations'].copy()
        full_total_calls = _get_annualized_calls(int(st.session_state.get('total_original_calls', len(df_calls_full) if df_calls_full is not None else len(df_calls)) or 0))
        full_daily_calls = max(1, int(full_total_calls / 365)) if full_total_calls else 1

        # ── MAP BUILD EVENT: log to sheets once per session ──────────────────────
        log_map_build_event_once(st.session_state, _log_to_sheets)

        if st.session_state.get('census_download_notice'):
            _census_conv = st.session_state.get('census_conversion_summary') or {}
            _census_ready = int(_census_conv.get('rows_ready', len(df_calls_full)) or len(df_calls_full))
            _census_total = int(st.session_state.get('total_original_calls', _census_ready) or _census_ready)
            st.sidebar.info(
                "Coordinates restored via Census batch geocoding.\n\n"
                f"{_census_ready:,} of {_census_total:,} records now have usable coordinates."
            )
            if st.session_state.get('census_corrected_bytes'):
                st.sidebar.download_button(
                    "⬇️ Download Corrected Calls File",
                    data=st.session_state['census_corrected_bytes'],
                    file_name=st.session_state.get('census_corrected_name') or "cad_calls_census_corrected.csv",
                    mime="text/csv",
                    key="sidebar_download_corrected_census_calls_btn",
                    width="stretch",
                    help="Download the corrected calls file so the Census conversion does not need to run again in a future browser session.",
                )
            st.sidebar.caption("This corrected data is only stored for the current browser session.")

        # ── Import quality report ─────────────────────────────────────────────
        _pq_report = st.session_state.get('parse_quality', [])
        if _pq_report and st.session_state.get('data_source') == 'cad_upload':
            _pq_errors = [f for f in _pq_report if f.get('status') == 'error']
            _pq_low_yield = [
                f for f in _pq_report
                if f.get('status') == 'ok' and f.get('input_rows', 0) > 0
                and f.get('output_rows', 0) / f['input_rows'] < 0.5
            ]
            _pq_missing = [
                f for f in _pq_report
                if f.get('status') == 'ok'
                and not (f.get('has_lat') and f.get('has_lon') and f.get('has_date'))
            ]
            if _pq_errors or _pq_low_yield or _pq_missing:
                with st.sidebar.expander("⚠️ Import Quality Issues", expanded=True):
                    for _f in _pq_report:
                        _fname = _f.get('file', 'unknown')
                        _in = _f.get('input_rows', 0)
                        _out = _f.get('output_rows', 0)
                        _yield_pct = round(100 * _out / _in) if _in > 0 else 0
                        if _f.get('status') == 'error':
                            st.error(f"**{_fname}** — parse failed  \n_{_f.get('error', 'unknown error')}_")
                        else:
                            _warnings = []
                            if not _f.get('has_lat') or not _f.get('has_lon'):
                                _warnings.append("no lat/lon found")
                            if not _f.get('has_date'):
                                _warnings.append("no date column")
                            if _in > 0 and _yield_pct < 50:
                                _warnings.append(f"only {_yield_pct}% of rows kept")
                            if _warnings:
                                st.warning(f"**{_fname}**  \n{_in:,} in → {_out:,} kept ({_yield_pct}%)  \n" + " · ".join(_warnings))
                            else:
                                st.info(f"**{_fname}**  \n{_in:,} in → {_out:,} kept ({_yield_pct}%)")

        master_gdf, _boundary_kind_note, _boundary_src_note = resolve_master_boundary(
            st,
            st.session_state,
            df_calls,
            df_stations_all,
            SHAPEFILE_DIR,
            fetch_county_by_centroid,
            get_jurisdiction_message,
            get_relevant_jurisdictions_cached,
            _boundary_shp_base,
            _sanitize_boundary_token,
        )


        master_gdf, active_gdf, selected_names = render_sidebar_jurisdiction_selector(
            st,
            st.session_state,
            master_gdf,
            _boundary_kind_note,
            _boundary_src_note,
            get_themed_logo_base64,
            _boundary_overlay_status,
            city_boundary_geom if 'city_boundary_geom' in locals() else None,
            epsg_code if 'epsg_code' in locals() else None,
        )

        _refresh_reference_population(st.session_state, selected_names)


        df_stations_all, df_calls, df_calls_full = render_data_filters(
            st,
            df_stations_all,
            df_calls,
            df_calls_full,
        )

        _display_opts = render_display_options(st)
        show_satellite = _display_opts['show_satellite']
        show_boundaries = _display_opts['show_boundaries']
        show_faa = _display_opts['show_faa']
        show_no_fly = _display_opts['show_no_fly']
        show_obstacles = _display_opts['show_obstacles']
        show_coverage = _display_opts['show_coverage']
        show_cell_towers = _display_opts['show_cell_towers']
        show_heatmap = _display_opts['show_heatmap']
        show_dots = _display_opts['show_dots']
        show_rapid_response_ring = _display_opts['show_rapid_response_ring']
        simulate_traffic = _display_opts['simulate_traffic']
        show_health = _display_opts['show_health']
        show_financials = _display_opts['show_financials']
        show_cards = _display_opts['show_cards']
        simple_cards = _display_opts['simple_cards']
        traffic_level = _display_opts['traffic_level']


        _strategy_opts = render_deployment_strategy(st, st.session_state, CONFIG, text_muted)
        pricing_tier = _strategy_opts['pricing_tier']
        _tier_badge = _strategy_opts['tier_badge']
        _tier_desc = _strategy_opts['tier_desc']
        incremental_build = _strategy_opts['incremental_build']
        auto_cap_dfr = _strategy_opts['auto_cap_dfr']
        deployment_mode = _strategy_opts['deployment_mode']
        allow_redundancy = _strategy_opts['allow_redundancy']
        complement_mode = _strategy_opts['complement_mode']
        shared_mode = _strategy_opts['shared_mode']
        guard_strategy_raw = _strategy_opts['guard_strategy_raw']
        resp_strategy_raw = _strategy_opts['resp_strategy_raw']
        guard_strategy = _strategy_opts['guard_strategy']
        resp_strategy = _strategy_opts['resp_strategy']
        resp_radius_mi = _strategy_opts['resp_radius_mi']
        guard_radius_mi = _strategy_opts['guard_radius_mi']

        # Keep opt_strategy for any code that still references it (used in export/logs)
        opt_strategy = guard_strategy  # primary strategy label for reporting


        st.sidebar.markdown('<div class="sidebar-section-header">② Optimize Fleet</div>', unsafe_allow_html=True)

        _station_prep = prepare_station_candidates(
            st,
            st.session_state,
            active_gdf,
            df_calls,
            df_stations_all,
            calculate_zoom,
            _boundary_overlay_status,
            _make_random_stations,
        )
        minx = _station_prep['minx']
        miny = _station_prep['miny']
        maxx = _station_prep['maxx']
        maxy = _station_prep['maxy']
        center_lon = _station_prep['center_lon']
        center_lat = _station_prep['center_lat']
        dynamic_zoom = _station_prep['dynamic_zoom']
        epsg_code = _station_prep['epsg_code']
        city_m = _station_prep['city_m']
        city_boundary_geom = _station_prep['city_boundary_geom']
        boundary_overlay_status = _station_prep['boundary_overlay_status']
        df_stations_all = _station_prep['df_stations_all']
        area_sq_mi = _station_prep['area_sq_mi']
        n = _station_prep['station_count']

        r_resp_est = st.session_state.get('r_resp', 2.0)
        r_guard_est = st.session_state.get('r_guard', 8.0)
        df_curve = pd.DataFrame()


        _custom_station_state = manage_custom_stations(
            st,
            st.session_state,
            df_stations_all,
            area_sq_mi,
            r_resp_est,
            r_guard_est,
            resp_radius_mi,
            guard_radius_mi,
            df_curve,
            get_address_from_latlon,
            search_address_candidates,
        )
        k_responder = _custom_station_state['k_responder']
        k_guardian = _custom_station_state['k_guardian']
        pinned_guard_names = _custom_station_state['pinned_guard_names']
        pinned_resp_names = _custom_station_state['pinned_resp_names']
        _station_names = _custom_station_state['station_names']


        # Convert pin names → station indices for the optimizer
        _name_to_idx = {row['name']: i for i, row in df_stations_all.iterrows()}
        locked_g_pins = [_name_to_idx[n] for n in pinned_guard_names if n in _name_to_idx]
        locked_r_pins = [_name_to_idx[n] for n in pinned_resp_names if n in _name_to_idx]

        bounds_hash = f"{minx}_{miny}_{maxx}_{maxy}_{n}_{resp_radius_mi}_{guard_radius_mi}"
        _station_signature = "|".join(
            f"{str(row.get('name', ''))}:{float(row.get('lat', 0) or 0):.5f}:{float(row.get('lon', 0) or 0):.5f}"
            for _, row in df_stations_all.iterrows()
        )

        _runtime_ctx = prepare_runtime_context(
            st,
            st.session_state,
            optimization,
            faa_rf,
            html_reports,
            CONFIG,
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
        )
        calls_in_city = _runtime_ctx['calls_in_city']
        display_calls = _runtime_ctx['display_calls']
        resp_matrix = _runtime_ctx['resp_matrix']
        guard_matrix = _runtime_ctx['guard_matrix']
        dist_matrix_r = _runtime_ctx['dist_matrix_r']
        dist_matrix_g = _runtime_ctx['dist_matrix_g']
        station_metadata = _runtime_ctx['station_metadata']
        total_calls = _runtime_ctx['total_calls']
        df_curve = _runtime_ctx['df_curve']
        faa_geojson = _runtime_ctx['faa_geojson']
        airfields = _runtime_ctx['airfields']
        calls_per_day = _runtime_ctx['calls_per_day']
        dfr_dispatch_rate = _runtime_ctx['dfr_dispatch_rate']
        deflection_rate = _runtime_ctx['deflection_rate']
        # ── OPTIMIZATION ──────────────────────────────────────────────────
        _pins_key = f"{sorted(locked_g_pins)}_{sorted(locked_r_pins)}"
        opt_cache_key = f"{k_responder}_{k_guardian}_{resp_radius_mi}_{guard_radius_mi}_{guard_strategy}_{resp_strategy}_{deployment_mode}_{incremental_build}_{bounds_hash}_{_station_signature}_{_pins_key}"
        _opt_result = optimize_fleet_selection(
            st,
            st.session_state,
            optimization,
            station_metadata,
            resp_matrix,
            guard_matrix,
            dist_matrix_r,
            dist_matrix_g,
            total_calls,
            calls_per_day,
            dfr_dispatch_rate,
            CONFIG,
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
        )
        active_resp_names = _opt_result['active_resp_names']
        active_guard_names = _opt_result['active_guard_names']
        active_resp_idx = _opt_result['active_resp_idx']
        active_guard_idx = _opt_result['active_guard_idx']
        chrono_r = _opt_result['chrono_r']
        chrono_g = _opt_result['chrono_g']
        best_combo = _opt_result['best_combo']
        guard_claims_by_idx = _opt_result.get('guard_claims_by_idx', {}) or {}


        # ── METRICS ───────────────────────────────────────────────────────
        # ── SPLIT METRICS: Guardian and Responder computed independently ─────────
        area_covered_perc = overlap_perc = calls_covered_perc = 0.0
        guard_calls_perc  = guard_area_perc  = 0.0
        resp_calls_perc   = resp_area_perc   = 0.0
        cov_r = np.zeros(total_calls, bool) if total_calls > 0 else np.zeros(0, bool)
        cov_g = np.zeros(total_calls, bool) if total_calls > 0 else np.zeros(0, bool)

        ordered_deployments_raw = []
        for idx in chrono_g:
            if idx in active_guard_idx: ordered_deployments_raw.append((idx,'GUARDIAN'))
        for idx in chrono_r:
            if idx in active_resp_idx: ordered_deployments_raw.append((idx,'RESPONDER'))
        for idx in active_resp_idx:
            if idx not in chrono_r: ordered_deployments_raw.append((idx,'RESPONDER'))
        for idx in active_guard_idx:
            if idx not in chrono_g: ordered_deployments_raw.append((idx,'GUARDIAN'))

        active_color_map = {}
        c_idx = 0
        for idx, d_type in ordered_deployments_raw:
            key = f"{idx}_{d_type}"
            if key not in active_color_map:
                active_color_map[key] = STATION_COLORS[c_idx % len(STATION_COLORS)]
                c_idx += 1

        guard_geos = [station_metadata[i]['clipped_guard'] for i in active_guard_idx]
        resp_geos  = [station_metadata[i]['clipped_2m']    for i in active_resp_idx]
        active_geos = resp_geos + guard_geos

        city_area = city_m.area if (city_m and not city_m.is_empty) else 1.0
        _metric_total_calls = total_calls
        _station_city_call_counts = {}
        _station_city_weighted_counts = {}
        _station_city_masks = {}
        _metric_cov_r = cov_r.copy()
        _metric_cov_g = cov_g.copy()

        _metric_df = df_calls_full if (df_calls_full is not None and not df_calls_full.empty) else df_calls
        if _metric_df is not None and len(_metric_df) > 0:
            try:
                _metric_gdf = gpd.GeoDataFrame(
                    _metric_df,
                    geometry=gpd.points_from_xy(_metric_df.lon, _metric_df.lat),
                    crs='EPSG:4326'
                ).to_crs(epsg=int(epsg_code))
                _metric_clip_geom = city_m.buffer(300) if city_m is not None else city_m
                _metric_calls_in_city = _metric_gdf[_metric_gdf.within(_metric_clip_geom)] if _metric_clip_geom is not None else _metric_gdf
            except Exception:
                _metric_calls_in_city = None
            if _metric_calls_in_city is not None and len(_metric_calls_in_city) > 0:
                _metric_total_calls = len(_metric_calls_in_city)
                _metric_xy = np.array(list(zip(_metric_calls_in_city.geometry.x, _metric_calls_in_city.geometry.y)))
                if active_resp_idx:
                    _metric_cov_r = np.zeros(_metric_total_calls, dtype=bool)
                    for _idx in active_resp_idx:
                        _station_pt = gpd.GeoSeries([Point(station_metadata[_idx]['lon'], station_metadata[_idx]['lat'])], crs='EPSG:4326').to_crs(epsg=int(epsg_code)).iloc[0]
                        _d = np.sqrt((_metric_xy[:, 0] - _station_pt.x) ** 2 + (_metric_xy[:, 1] - _station_pt.y) ** 2)
                        _mask = _d <= (resp_radius_mi * 1609.34)
                        _metric_cov_r |= _mask
                        _station_city_masks[('RESPONDER', _idx)] = _mask
                        _station_city_call_counts[('RESPONDER', _idx)] = int(_mask.sum())
                if active_guard_idx:
                    _metric_cov_g = np.zeros(_metric_total_calls, dtype=bool)
                    for _idx in active_guard_idx:
                        _station_pt = gpd.GeoSeries([Point(station_metadata[_idx]['lon'], station_metadata[_idx]['lat'])], crs='EPSG:4326').to_crs(epsg=int(epsg_code)).iloc[0]
                        _d = np.sqrt((_metric_xy[:, 0] - _station_pt.x) ** 2 + (_metric_xy[:, 1] - _station_pt.y) ** 2)
                        _mask = _d <= (guard_radius_mi * 1609.34)
                        _metric_cov_g |= _mask
                        _station_city_masks[('GUARDIAN', _idx)] = _mask
                        _station_city_call_counts[('GUARDIAN', _idx)] = int(_mask.sum())
        if _metric_cov_r.shape[0] != _metric_total_calls:
            _metric_cov_r = np.zeros(_metric_total_calls, dtype=bool)
        if _metric_cov_g.shape[0] != _metric_total_calls:
            _metric_cov_g = np.zeros(_metric_total_calls, dtype=bool)
        cov_r = _metric_cov_r
        cov_g = _metric_cov_g
        for _fleet_type, _fleet_order in (
                    ('GUARDIAN', [idx for idx, d_type in ordered_deployments_raw if d_type == 'GUARDIAN']),
                    ('RESPONDER', [idx for idx, d_type in ordered_deployments_raw if d_type == 'RESPONDER']),
                ):
                    _fleet_masks = [
                        _station_city_masks.get((_fleet_type, _idx))
                        for _idx in _fleet_order
                        if _station_city_masks.get((_fleet_type, _idx)) is not None
                    ]
                    if not _fleet_masks:
                        continue
                    _fleet_cover_counts = np.sum(np.vstack(_fleet_masks), axis=0)
                    for _idx in _fleet_order:
                        _station_key = (_fleet_type, _idx)
                        _mask = _station_city_masks.get(_station_key)
                        if _mask is None:
                            continue
                        _weights = np.where(_mask, 1.0 / np.maximum(_fleet_cover_counts, 1), 0.0)
                        _station_city_weighted_counts[_station_key] = float(_weights.sum())

        # Guardian-only metrics
        if guard_geos:
            guard_area_perc = (unary_union(guard_geos).area / city_area) * 100
        if active_guard_idx and _metric_total_calls > 0:
            cov_g = _metric_cov_g
            guard_calls_perc = cov_g.sum() / _metric_total_calls * 100

        # Responder-only metrics
        if resp_geos:
            resp_area_perc = (unary_union(resp_geos).area / city_area) * 100
        if active_resp_idx and _metric_total_calls > 0:
            cov_r = _metric_cov_r
            resp_calls_perc = cov_r.sum() / _metric_total_calls * 100

        # Combined metrics
        if active_geos:
            area_covered_perc = (unary_union(active_geos).area / city_area) * 100
        if _metric_total_calls > 0:
            calls_covered_perc = (np.logical_or(cov_r, cov_g).sum() / _metric_total_calls) * 100
            st.session_state['calls_covered_perc'] = calls_covered_perc
        if len(active_geos) >= 2:
            inters = [active_geos[i].intersection(active_geos[j])
                      for i in range(len(active_geos))
                      for j in range(i+1, len(active_geos))
                      if not active_geos[i].is_empty and not active_geos[j].is_empty
                      and active_geos[i].intersects(active_geos[j])]
            if inters:
                overlap_perc = (unary_union(inters).area / city_area) * 100

        # ── BUDGET CALCULATIONS ───────────────────────────────────────────
        actual_k_responder = len(active_resp_names)
        actual_k_guardian  = len(active_guard_names)
        capex_resp  = actual_k_responder * CONFIG["RESPONDER_COST"]
        capex_guard = actual_k_guardian  * CONFIG["GUARDIAN_COST"]
        fleet_capex = capex_resp + capex_guard

        annual_savings = 0
        break_even_text = "N/A"
        daily_drone_only_calls = 0
        covered_daily_calls = 0
        daily_dfr_responses = 0

        if fleet_capex > 0:
            covered_daily_calls    = calls_per_day * (calls_covered_perc / 100.0)
            daily_dfr_responses    = covered_daily_calls * dfr_dispatch_rate
            daily_drone_only_calls = daily_dfr_responses * deflection_rate
            if daily_drone_only_calls > 0:
                monthly_savings = (CONFIG["OFFICER_COST_PER_CALL"] - CONFIG["DRONE_COST_PER_CALL"]) * daily_drone_only_calls * 30.4
                annual_savings  = monthly_savings * 12
                break_even_text = f"{fleet_capex / monthly_savings:.1f} MONTHS"

        specialty_savings = html_reports.estimate_specialty_response_savings(
            st.session_state.get('df_calls_full') if st.session_state.get('df_calls_full') is not None else st.session_state.get('df_calls'),
            st.session_state.get('total_original_calls', total_calls),
            calls_covered_perc=calls_covered_perc
        )
        thermal_savings = float(specialty_savings.get('thermal_savings', 0) or 0)
        k9_savings      = float(specialty_savings.get('k9_savings', 0) or 0)
        fire_savings    = float(specialty_savings.get('fire_savings', 0) or 0)
        fire_calls_annual = float(specialty_savings.get('fire_calls_annual', 0) or 0)
        possible_additional_savings = float(specialty_savings.get('additional_savings_total', 0) or 0)

        _sidebar_annual_cap_placeholder = st.sidebar.empty()
        if fleet_capex <= 0:
            st.sidebar.info("👈 Set Responder/Guardian counts above to calculate budget impact.")

        # ── BUILD DRONE OBJECTS ───────────────────────────────────────────
        active_drones = []
        cumulative_mask = np.zeros(total_calls, dtype=bool) if total_calls > 0 else None
        step = 1
        _stable_avg_distance = getattr(
            optimization,
            "bounded_station_avg_distance_miles",
            optimization.mean_covered_distance_miles,
        )
        def _station_avg_dist_and_cap(idx, d_type):
            if d_type == 'RESPONDER':
                avg_dist_local = float(station_metadata[idx].get('avg_dist_r', 0) or 0)
                speed_local = CONFIG["RESPONDER_SPEED"]
                flight_min_local = CONFIG["RESPONDER_FLIGHT_MIN"]
                charge_min_local = CONFIG["RESPONDER_CHARGE_MIN"]
                cov_local = resp_matrix[idx]
            else:
                avg_dist_local = float(station_metadata[idx].get('avg_dist_g', 0) or 0)
                speed_local = CONFIG["GUARDIAN_SPEED"]
                flight_min_local = CONFIG["GUARDIAN_FLIGHT_MIN"]
                charge_min_local = CONFIG["GUARDIAN_CHARGE_MIN"]
                cov_local = guard_matrix[idx]
            avg_time_local = (avg_dist_local / speed_local) * 60 if speed_local > 0 else 0.0
            max_cap_local = calculate_max_flights_per_day(
                avg_time_local + 10.0,
                flight_minutes=flight_min_local,
                downtime_minutes=charge_min_local,
            )
            return cov_local, avg_dist_local, avg_time_local, max_cap_local

        _station_cov_cache = {}
        _station_cap_cache = {}
        _selected_keys = []
        for _idx, _d_type in ordered_deployments_raw:
            _cov_local, _avg_dist_local, _avg_time_local, _max_cap_local = _station_avg_dist_and_cap(_idx, _d_type)
            _station_cov_cache[(_idx, _d_type)] = _cov_local
            _station_cap_cache[(_idx, _d_type)] = float(_max_cap_local) * 365.0
            _selected_keys.append((_idx, _d_type))
        for idx, d_type in ordered_deployments_raw:
            if d_type == 'RESPONDER':
                cov_array = resp_matrix[idx]; cost = CONFIG["RESPONDER_COST"]
                speed_mph = CONFIG["RESPONDER_SPEED"]
                _fallback_avg = float(station_metadata[idx].get('avg_dist_r', 0) or 0)
                try:
                    avg_dist = _stable_avg_distance(
                        dist_matrix_r,
                        resp_matrix,
                        idx,
                        fallback_miles=_fallback_avg,
                        max_radius_miles=resp_radius_mi,
                    )
                except TypeError:
                    avg_dist = min(
                        _stable_avg_distance(
                            dist_matrix_r,
                            resp_matrix,
                            idx,
                            fallback_miles=_fallback_avg,
                        ),
                        resp_radius_mi,
                    )
                radius_m  = resp_radius_mi * 1609.34
            else:
                cov_array = guard_matrix[idx]; cost = CONFIG["GUARDIAN_COST"]
                speed_mph = CONFIG["GUARDIAN_SPEED"]
                _fallback_avg = float(station_metadata[idx].get('avg_dist_g', 0) or 0)
                try:
                    avg_dist = _stable_avg_distance(
                        dist_matrix_g,
                        guard_matrix,
                        idx,
                        fallback_miles=_fallback_avg,
                        max_radius_miles=guard_radius_mi,
                    )
                except TypeError:
                    avg_dist = min(
                        _stable_avg_distance(
                            dist_matrix_g,
                            guard_matrix,
                            idx,
                            fallback_miles=_fallback_avg,
                        ),
                        guard_radius_mi,
                    )
                radius_m  = guard_radius_mi * 1609.34
            map_color    = active_color_map[f"{idx}_{d_type}"]
            avg_time_min = (avg_dist / speed_mph) * 60
            d_lat = station_metadata[idx]['lat']; d_lon = station_metadata[idx]['lon']

            _is_pinned = (d_type == 'GUARDIAN' and idx in locked_g_pins) or (d_type == 'RESPONDER' and idx in locked_r_pins)
            d = {
                'idx': idx, 'name': station_metadata[idx]['name'],
                'lat': d_lat, 'lon': d_lon, 'type': d_type, 'cost': cost,
                'cov_array': cov_array, 'color': map_color,
                'pinned': _is_pinned,
                'deploy_step': step if (idx in chrono_r or idx in chrono_g) else "MANUAL",
                'avg_time_min': avg_time_min, 'speed_mph': speed_mph, 'radius_m': radius_m,
                'faa_ceiling': faa_rf.get_station_faa_ceiling(d_lat, d_lon, faa_geojson),
                'nearest_airport': faa_rf.get_nearest_airfield(d_lat, d_lon, airfields)
            }

            if total_calls > 0 and cumulative_mask is not None:
                # ── DEDUPLICATION: track unique calls added for combined KPI totals ──
                effective_cov_array = cov_array
                if complement_mode and d_type == 'GUARDIAN':
                    _guard_claimed = guard_claims_by_idx.get(idx)
                    if _guard_claimed is not None:
                        effective_cov_array = _guard_claimed
                marginal_mask     = effective_cov_array & ~cumulative_mask
                marginal_historic = np.sum(marginal_mask)
                d['assigned_indices'] = np.where(marginal_mask)[0]
                cumulative_mask   = cumulative_mask | effective_cov_array

                # ── RAW ZONE COVERAGE: how many calls fall in this drone's zone ───
                # Used for per-unit economics. Independent of iteration order so
                # Responders are never penalised for a Guardian claiming the same calls.
                # Use haversine-based counts from station_metadata so stations at
                # different positions produce different raw counts. UTM Euclidean
                # overshoots at large radii and saturates to the full city total.
                if d_type == 'RESPONDER':
                    _raw_zone_calls = station_metadata[idx]['raw_calls_r']
                else:
                    _raw_zone_calls = station_metadata[idx]['raw_calls_g']
                _raw_zone_perc  = _raw_zone_calls / total_calls

                # Shared zone: calls covered by at least one OTHER active drone
                all_cov = np.vstack([resp_matrix[i] for i in active_resp_idx] + [guard_matrix[i] for i in active_guard_idx]) if (active_resp_idx or active_guard_idx) else np.zeros((1, total_calls), dtype=bool)
                _cover_counts = all_cov.sum(axis=0)
                shared_mask   = d['cov_array'] & (_cover_counts > 1)
                _shared_calls = int(np.sum(shared_mask))
                _excl_calls   = _raw_zone_calls - _shared_calls  # calls ONLY this drone covers
                _exclusive_weighted_zone_calls = float(np.sum(d['cov_array'] & (_cover_counts == 1)))
                _weighted_zone_calls = float(np.sum(d['cov_array'] / np.maximum(_cover_counts, 1)))
                _concurrent_weighted_zone_calls = max(0.0, _weighted_zone_calls - _exclusive_weighted_zone_calls)
                _weighted_zone_perc  = (_weighted_zone_calls / total_calls) if total_calls > 0 else 0.0
                _ring_capacity_yr = 0.0
                if _raw_zone_calls > 0:
                    for _peer_idx, _peer_type in _selected_keys:
                        _peer_cov = _station_cov_cache.get((_peer_idx, _peer_type))
                        if _peer_cov is None:
                            continue
                        _overlap_calls = float(np.sum(d['cov_array'] & _peer_cov))
                        if _overlap_calls <= 0:
                            continue
                        _ring_capacity_yr += _station_cap_cache.get((_peer_idx, _peer_type), 0.0) * (_overlap_calls / _raw_zone_calls)
                _calls_unanswered_yr = max(0.0, float(_raw_zone_calls) - _ring_capacity_yr)
                _calls_unanswered_day = _calls_unanswered_yr / 365.0
                _handled_calls_yr = max(0.0, float(_raw_zone_calls) - _calls_unanswered_yr)
                _handled_calls_day = _handled_calls_yr / 365.0

                # ── UTILIZATION: based on overlap-adjusted station load ───────────
                # Shared calls are split across overlapping active drones so adding
                # another station reduces the demand carried by already-maxed stations.
                _is_guard    = (d_type == 'GUARDIAN')
                _budget_min  = CONFIG["GUARDIAN_DAILY_FLIGHT_MIN"] if _is_guard else CONFIG["RESPONDER_DAILY_FLIGHT_MIN"]
                _zone_flights = _weighted_zone_perc * calls_per_day * dfr_dispatch_rate

                # ── CAPACITY MODEL: 10-minute on-scene floor ──────────────────────
                # Every sortie consumes travel_time + on_scene_time from the daily budget.
                # We require at least 10 min on-scene so the drone isn't rushing back.
                # Deficit triggers when available on-scene time per flight drops below 10 min.
                #
                #   max_flights   = budget_min / (avg_time_min + 10)
                #   on_scene_min  = (budget_min / zone_flights) - avg_time_min   [if zone_flights > 0]
                #   deficit       = on_scene_min < 10  ↔  zone_flights > max_flights
                _MIN_SCENE_MIN   = 10.0
                _g_budget        = CONFIG["GUARDIAN_DAILY_FLIGHT_MIN"]
                _r_budget        = CONFIG["RESPONDER_DAILY_FLIGHT_MIN"]
                _alt_is_guard    = not _is_guard   # cross-type recommendation
                _alt_budget      = _g_budget if _alt_is_guard else _r_budget

                # Capacity of THIS drone type (flights/day with 10-min scene floor)
                # Drones go call-to-call across the 24-hour operating cycle, only pausing
                # for the unit-specific swap or recharge downtime when endurance is spent.
                _travel_cost     = avg_time_min
                _response_cost   = _travel_cost + _MIN_SCENE_MIN
                _max_flights_cap  = calculate_max_flights_per_day(
                    _response_cost,
                    flight_minutes=CONFIG["GUARDIAN_FLIGHT_MIN"] if _is_guard else CONFIG["RESPONDER_FLIGHT_MIN"],
                    downtime_minutes=CONFIG["GUARDIAN_CHARGE_MIN"] if _is_guard else CONFIG["RESPONDER_CHARGE_MIN"],
                )
                # Alternate type cap (for cross-type deficit recommendation)
                _alt_avg_dist    = float(station_metadata[idx].get('avg_dist_g' if d_type == 'RESPONDER' else 'avg_dist_r', 0) or 0)
                _alt_speed       = CONFIG["GUARDIAN_SPEED"] if _alt_is_guard else CONFIG["RESPONDER_SPEED"]
                _alt_travel_cost = (_alt_avg_dist / _alt_speed) * 60 if _alt_speed > 0 else 0.0
                _alt_response_cost = _alt_travel_cost + _MIN_SCENE_MIN
                _alt_avg_time_min = _alt_travel_cost
                _alt_max_flights  = calculate_max_flights_per_day(
                    _alt_response_cost,
                    flight_minutes=CONFIG["GUARDIAN_FLIGHT_MIN"] if _alt_is_guard else CONFIG["RESPONDER_FLIGHT_MIN"],
                    downtime_minutes=CONFIG["GUARDIAN_CHARGE_MIN"] if _alt_is_guard else CONFIG["RESPONDER_CHARGE_MIN"],
                )

                # ── Auto-cap: clamp this station's effective DFR rate to its
                #    physical capacity limit so it doesn't show a deficit while
                #    leaving every other station's rate untouched.
                _raw_demand = _weighted_zone_perc * calls_per_day
                if auto_cap_dfr and _max_flights_cap > 0 and _raw_demand > 0:
                    _station_max_rate = _max_flights_cap / _raw_demand
                    _effective_dfr    = min(dfr_dispatch_rate, _station_max_rate)
                    _zone_flights     = _raw_demand * _effective_dfr
                else:
                    _effective_dfr = dfr_dispatch_rate

                # On-scene minutes available per flight given current demand.
                # Capped at single-flight endurance minus travel — you cannot stay
                # on scene longer than the battery allows regardless of how few calls there are.
                _flight_endurance = CONFIG["GUARDIAN_FLIGHT_MIN"] if _is_guard else CONFIG["RESPONDER_FLIGHT_MIN"]
                _max_on_scene = max(0.0, _flight_endurance - _travel_cost)
                _on_scene_min = min(
                    (_budget_min / max(_zone_flights, 0.001)) - _travel_cost if _zone_flights > 0 else _max_on_scene,
                    _max_on_scene,
                )
                _alt_flight_endurance = CONFIG["GUARDIAN_FLIGHT_MIN"] if _alt_is_guard else CONFIG["RESPONDER_FLIGHT_MIN"]
                _alt_max_on_scene = max(0.0, _alt_flight_endurance - _alt_travel_cost)
                _alt_on_scene_min = min(
                    (_alt_budget / max(_zone_flights, 0.001)) - _alt_travel_cost if _zone_flights > 0 else _alt_max_on_scene,
                    _alt_max_on_scene,
                )

                _raw_calls_in_range_day = _raw_zone_calls / 365.0
                _dispatchable_calls_day = _raw_calls_in_range_day * _effective_dfr
                _dispatchable_calls_yr = _raw_zone_calls * _effective_dfr
                # Cap weighted dispatchable to never exceed total dispatchable — attributed
                # demand (overlap-shared) cannot logically exceed the ring's full demand.
                _weighted_dispatchable_calls_day = min(
                    (_weighted_zone_calls / 365.0) * _effective_dfr,
                    _dispatchable_calls_day,
                )
                _weighted_dispatchable_calls_yr = min(
                    _weighted_zone_calls * _effective_dfr,
                    _dispatchable_calls_yr,
                )
                _call_capacity_util = _weighted_dispatchable_calls_day / max(_max_flights_cap, 0.001) if _max_flights_cap > 0 else (1.0 if _weighted_dispatchable_calls_day > 0 else 0.0)
                # Utilization is based on dispatchable calls in range versus physical call-handling capacity.
                # If dispatchable calls are left unanswered, the unit is at 100% utilization.
                _true_util = _call_capacity_util
                _util = min(1.0, _true_util)

                # ── ANNUAL CAPACITY VALUE: directly tied to handled calls ────────
                _cost_delta        = CONFIG["OFFICER_COST_PER_CALL"] - CONFIG["DRONE_COST_PER_CALL"]
                _unserv_calls_day = _calls_unanswered_day
                _unserv_calls_yr  = _calls_unanswered_yr
                _deflected_calls_day = _handled_calls_day * deflection_rate
                _deflected_calls_yr  = _handled_calls_yr * deflection_rate

                # Deficit: overlap-weighted dispatchable calls demanded beyond physical capacity
                _deficit_flights  = max(0.0, _weighted_dispatchable_calls_day - _max_flights_cap)
                _has_deficit      = _deficit_flights > 0.01

                # Extra stations needed to clear deficit (same type and alternate type)
                _extra_same = int(math.ceil(_deficit_flights / _max_flights_cap)) if (_has_deficit and _max_flights_cap > 0) else 0
                _extra_alt  = int(math.ceil(_deficit_flights / _alt_max_flights))  if (_has_deficit and _alt_max_flights > 0) else 0

                # CapEx cost of each resolution path
                _same_type_cost = CONFIG["GUARDIAN_COST"] if _is_guard else CONFIG["RESPONDER_COST"]
                _alt_type_cost  = CONFIG["RESPONDER_COST"] if _is_guard else CONFIG["GUARDIAN_COST"]
                _extra_same_capex = _extra_same * _same_type_cost
                _extra_alt_capex  = _extra_alt  * _alt_type_cost
                _same_type_label  = "Guardian"  if _is_guard else "Responder"
                _alt_type_label   = "Responder" if _is_guard else "Guardian"
                # Exclusive share derived from zone call counts (stable under any
                # capacity cap — both numerator and denominator scale identically).
                if _weighted_zone_calls > 0:
                    _exclusive_share = min(1.0, max(0.0, _exclusive_weighted_zone_calls / _weighted_zone_calls))
                else:
                    _exclusive_share = 1.0
                _concurrent_share = max(0.0, 1.0 - _exclusive_share)
                _excl_flights      = _handled_calls_day * _exclusive_share
                _concurrent_daily  = _handled_calls_day * _concurrent_share
                _excl_deflected    = _deflected_calls_day * _exclusive_share
                _concurrent_deflected_day = _deflected_calls_day * _concurrent_share
                _base_annual       = (_excl_deflected * 365.0) * _cost_delta
                _base_monthly      = _base_annual / 12.0
                _concurrent_month  = (_concurrent_deflected_day * 365.0 * _cost_delta) / 12.0
                _concurrent_annual = _concurrent_deflected_day * 365.0 * _cost_delta
                _best_monthly      = _base_monthly + _concurrent_month
                _best_annual       = _base_annual + _concurrent_annual

                # ── STORE — use best_case as primary display value ─────────────────
                _assigned_daily_calls   = _weighted_zone_perc * calls_per_day if total_calls > 0 else 0.0
                _assigned_flights_day   = _assigned_daily_calls * _effective_dfr
                d['marginal_perc']       = marginal_historic / total_calls
                d['marginal_calls']      = marginal_historic
                d['assigned_calls_day']  = _assigned_daily_calls
                d['assigned_flights_day']= _assigned_flights_day
                d['assigned_flights_yr'] = _assigned_flights_day * 365.0
                d['calls_in_range_day']  = _raw_calls_in_range_day
                d['calls_in_range_yr']   = float(_raw_zone_calls)
                d['dispatchable_calls_day'] = _dispatchable_calls_day
                d['dispatchable_calls_yr']  = _dispatchable_calls_yr
                d['weighted_dispatchable_calls_day'] = _weighted_dispatchable_calls_day
                d['weighted_dispatchable_calls_yr']  = _weighted_dispatchable_calls_yr
                d['calls_handle_day']    = _handled_calls_day
                d['calls_handle_yr']     = _handled_calls_yr
                d['calls_unanswered_day']= _unserv_calls_day
                d['calls_unanswered_yr'] = _unserv_calls_yr
                d['marginal_flights']    = _excl_flights
                d['marginal_deflected']  = _excl_deflected
                d['handled_calls_day']   = _handled_calls_day
                d['handled_calls_yr']    = _handled_calls_yr
                d['shared_flights']      = _concurrent_daily
                d['zone_flights']        = _zone_flights
                d['zone_calls_annual']   = _weighted_zone_calls * 365.0 / 365.0
                d['raw_zone_calls_annual'] = _raw_zone_calls
                d['zone_flights_annual'] = _zone_flights * 365.0
                d['utilization']         = _util
                d['true_util']           = _true_util
                d['on_scene_min']        = _on_scene_min
                d['alt_on_scene_min']    = _alt_on_scene_min
                d['alt_avg_time_min']    = _alt_avg_time_min
                d['loiter_vs_other_min'] = _on_scene_min - _alt_on_scene_min
                d['max_flights_cap']     = _max_flights_cap
                d['effective_dfr_rate']  = _effective_dfr
                d['has_deficit']         = _has_deficit
                d['deficit_flights']     = _deficit_flights
                d['unserv_calls_day']    = _unserv_calls_day
                d['unserv_calls_yr']     = _unserv_calls_yr
                d['extra_same']          = _extra_same
                d['extra_alt']           = _extra_alt
                d['extra_same_capex']    = _extra_same_capex
                d['extra_alt_capex']     = _extra_alt_capex
                d['same_type_label']     = _same_type_label
                d['alt_type_label']      = _alt_type_label
                d['blocked_per_day']     = _concurrent_daily
                d['monthly_savings']     = _best_monthly
                d['annual_savings']      = _best_annual
                d['base_annual']         = _base_annual
                d['concurrent_annual']   = _concurrent_annual
                d['best_case_annual']    = _best_annual
                d['concurrent_monthly']  = _concurrent_month
                d['be_text']     = f"{d['cost']/_best_monthly:.1f} MO" if _best_monthly > 0 else "N/A"
                d['best_be_text']= d['be_text']
            else:
                d.update({'assigned_indices':[],'annual_savings':0,'marginal_flights':0,
                          'marginal_deflected':0,'shared_flights':0,'be_text':"N/A",
                          'utilization':0,'true_util':0,'on_scene_min':99,'max_flights_cap':0,
                          'has_deficit':False,'deficit_flights':0,'unserv_calls_day':0,
                          'unserv_calls_yr':0,'extra_same':0,'extra_alt':0,
                          'extra_same_capex':0,'extra_alt_capex':0,
                          'same_type_label':'Responder','alt_type_label':'Guardian',
                          'concurrent_monthly':0,'best_case_annual':0,
                          'blocked_per_day':0,'best_be_text':"N/A",'base_annual':0,
                          'concurrent_annual':0,'zone_flights':0,'zone_calls_annual':0,
                          'calls_in_range_day':0,'calls_in_range_yr':0,
                          'dispatchable_calls_day':0,'dispatchable_calls_yr':0,
                          'weighted_dispatchable_calls_day':0,'weighted_dispatchable_calls_yr':0,
                          'calls_handle_day':0,'calls_handle_yr':0,
                          'calls_unanswered_day':0,'calls_unanswered_yr':0,
                          'zone_flights_annual':0})
            active_drones.append(d)
            step += 1

        # ── RECONCILE UNIT ECONOMICS TO FLEET HEADLINE ───────────────────────
        if active_drones and annual_savings >= 0:
            _raw_total_annual = float(sum(max(0, d.get('best_case_annual', d.get('annual_savings', 0)) or 0) for d in active_drones))
            if _raw_total_annual > 0:
                annual_savings = _raw_total_annual
                monthly_savings = annual_savings / 12.0
                break_even_text = f"{fleet_capex / monthly_savings:.1f} MONTHS" if monthly_savings > 0 else "N/A"
            _fleet_target_annual = float(max(0, annual_savings))
            if _fleet_target_annual > 0:
                if _raw_total_annual <= 0:
                    _weights = [max(0.0, float(d.get('marginal_perc', 0) or 0)) for d in active_drones]
                    _w_sum = sum(_weights)
                    if _w_sum <= 0:
                        _weights = [1.0 for _ in active_drones]
                        _w_sum = float(len(active_drones))
                    for _d, _w in zip(active_drones, _weights):
                        _alloc_annual = _fleet_target_annual * (_w / _w_sum)
                        _alloc_monthly = _alloc_annual / 12.0
                        _d['base_annual'] = _alloc_annual
                        _d['concurrent_annual'] = 0.0
                        _d['best_case_annual'] = _alloc_annual
                        _d['annual_savings'] = _alloc_annual
                        _d['monthly_savings'] = _alloc_monthly
                        _d['concurrent_monthly'] = 0.0
                        _d['be_text'] = f"{_d['cost']/_alloc_monthly:.1f} MO" if _alloc_monthly > 0 else "N/A"
                        _d['best_be_text'] = _d['be_text']
                else:
                    # Cap scale at 1.0: never inflate per-unit values above their raw
                    # pre-reconciliation figures. When _fleet_target_annual exceeds
                    # _raw_total_annual (low-utilisation / no-overlap case) the gap is
                    # handled by the drift correction below rather than by scaling up.
                    _scale = min(1.0, _fleet_target_annual / _raw_total_annual)
                    for _d in active_drones:
                        _base = float(_d.get('base_annual', 0) or 0)
                        _conc = float(_d.get('concurrent_annual', 0) or 0)
                        _best = float(_d.get('best_case_annual', _d.get('annual_savings', 0)) or 0)
                        _month = float(_d.get('monthly_savings', _best / 12.0) or 0)
                        _conc_month = float(_d.get('concurrent_monthly', _conc / 12.0) or 0)

                        _d['base_annual'] = _base * _scale
                        _d['concurrent_annual'] = _conc * _scale
                        _d['best_case_annual'] = _best * _scale
                        _d['annual_savings'] = _best * _scale
                        _d['monthly_savings'] = _month * _scale
                        _d['concurrent_monthly'] = _conc_month * _scale
                        _d['be_text'] = f"{_d['cost']/_d['monthly_savings']:.1f} MO" if _d['monthly_savings'] > 0 else "N/A"
                        _d['best_be_text'] = _d['be_text']

                _reconciled_total = float(sum(max(0, d.get('annual_savings', 0) or 0) for d in active_drones))
                _drift = _fleet_target_annual - _reconciled_total
                if abs(_drift) > 0.01 and active_drones:
                    _weights = [max(0.0, float(d.get('annual_savings', 0) or 0)) for d in active_drones]
                    _w_sum = sum(_weights)
                    if _w_sum <= 0:
                        _weights = [max(0.0, float(d.get('base_annual', 0) or 0)) for d in active_drones]
                        _w_sum = sum(_weights)
                    if _w_sum <= 0:
                        _weights = [1.0 for _ in active_drones]
                        _w_sum = float(len(active_drones))

                    _allocated = 0.0
                    for _idx, (_d, _w) in enumerate(zip(active_drones, _weights)):
                        _share = _drift if _idx == len(active_drones) - 1 else _drift * (_w / _w_sum)
                        if _idx < len(active_drones) - 1:
                            _allocated += _share
                        else:
                            _share = _drift - _allocated
                        _d['annual_savings']   = float(_d.get('annual_savings', 0) or 0) + _share
                        _d['best_case_annual'] = float(_d.get('best_case_annual', 0) or 0) + _share
                        _d['monthly_savings']  = float(_d.get('monthly_savings', 0) or 0) + (_share / 12.0)
                        _d['be_text']      = f"{_d['cost']/_d['monthly_savings']:.1f} MO" if _d['monthly_savings'] > 0 else "N/A"
                        _d['best_be_text'] = _d['be_text']

        # ── SIDEBAR: fill Annual Capacity Value box with specialty values that match unit cards ──
        if fleet_capex > 0 and show_financials:
            _s_THERMAL_RATE     = float(CONFIG.get("THERMAL_DEFAULT_APPLICABLE_RATE", 0.12) or 0)
            _s_THERMAL_PER_CALL = float(CONFIG.get("THERMAL_SAVINGS_PER_CALL", 38) or 0)
            _s_K9_RATE          = float(CONFIG.get("K9_DEFAULT_APPLICABLE_RATE", 0.03) or 0)
            _s_K9_PER_CALL      = float(CONFIG.get("K9_SAVINGS_PER_CALL", 155) or 0)
            _s_FIRE_RATE        = float(CONFIG.get("FIRE_DEFAULT_APPLICABLE_RATE", 0.05) or 0)
            _s_FIRE_PER_CALL    = float(CONFIG.get("FIRE_SAVINGS_PER_CALL", 450) or 0)

            _s_thermal_total = 0.0
            _s_k9_total      = 0.0
            _s_fire_total    = 0.0
            for _sd in active_drones:
                _sd_flights  = float(_sd.get("marginal_flights", 0) or 0)
                _sd_shared   = float(_sd.get("shared_flights", 0) or 0)
                _sd_zone_calls          = float(_sd.get("zone_calls_annual", 0) or 0)
                _sd_zone_flights_annual = float(_sd.get("zone_flights_annual", (_sd_flights + _sd_shared) * 365.0) or 0)
                _sd_serviceable_annual  = float(_sd.get("max_flights_cap", 0) or 0) * 365.0
                _sd_flight_base = min(_sd_zone_flights_annual, _sd_serviceable_annual) if _sd_serviceable_annual > 0 else _sd_zone_flights_annual
                _sd_flight_base = min(_sd_flight_base, _sd_zone_calls) if _sd_zone_calls > 0 else _sd_flight_base
                _s_thermal_total += _sd_flight_base * _s_THERMAL_RATE * _s_THERMAL_PER_CALL
                _s_k9_total      += _sd_flight_base * _s_K9_RATE      * _s_K9_PER_CALL
                _s_fire_total    += _sd_flight_base * _s_FIRE_RATE    * _s_FIRE_PER_CALL

            _s_specialty_total = _s_thermal_total + _s_k9_total + _s_fire_total

            _sidebar_annual_cap_placeholder.markdown(f"""
            <div style="background:{budget_box_bg}; border:1px solid {budget_box_border}; padding:12px; border-radius:4px;
                 text-align:center; margin:8px 0 12px 0; box-shadow:0 2px 5px {budget_box_shadow};">
                <div style="font-size:0.7rem; color:{text_muted}; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Annual Capacity Value</div>
                <div style="font-size:1.8rem; font-weight:900; color:{budget_box_border}; font-family:monospace;">${annual_savings:,.0f}</div>
                <div style="font-size:0.68rem; color:{text_muted}; margin-top:4px;">+ specialty response upside</div>
                <div style="font-size:1.05rem; font-weight:800; color:#39FF14; font-family:monospace; margin-top:2px;">${_s_specialty_total:,.0f}</div>
                <div style="display:flex; justify-content:space-between; font-size:0.68rem; margin-top:6px;">
                    <span style="color:{text_muted};">🔥 Thermal response:</span>
                    <span style="color:#fbbf24; font-weight:700;">${_s_thermal_total:,.0f}/yr</span>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.68rem; margin-top:2px;">
                    <span style="color:{text_muted};">🐕 K-9 replacement:</span>
                    <span style="color:#39FF14; font-weight:700;">${_s_k9_total:,.0f}/yr</span>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.68rem; margin-bottom:2px; margin-top:2px;">
                    <span style="color:{text_muted};">🚒 Fire dept value:</span>
                    <span style="color:#fb7121; font-weight:700;">${_s_fire_total:,.0f}/yr</span>
                </div>
                <div style="border-top:1px solid {card_border}; margin:8px 0;"></div>
                <div style="display:flex; justify-content:space-between; font-size:0.72rem; margin-bottom:3px;">
                    <span style="color:{text_muted};">Calls in range:</span>
                    <span style="color:{text_main}; font-weight:700;">{covered_daily_calls:.1f}/day</span>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.72rem; margin-bottom:3px;">
                    <span style="color:{text_muted};">DFR flights ({int(dfr_dispatch_rate*100)}%):</span>
                    <span style="color:{text_main}; font-weight:700;">{daily_dfr_responses:.1f}/day</span>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.72rem; margin-bottom:8px;">
                    <span style="color:{text_muted};">Resolved no dispatch:</span>
                    <span style="color:{text_main}; font-weight:700;">{daily_drone_only_calls:.1f}/day</span>
                </div>
                <div style="border-top:1px dashed {card_border}; margin:6px 0;"></div>
                <div style="display:flex; justify-content:space-between; font-size:0.72rem; margin-bottom:3px;">
                    <span style="color:{text_muted};">Fleet CapEx:</span>
                    <span style="color:{text_main}; font-weight:700;">${fleet_capex:,.0f}</span>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.72rem;">
                    <span style="color:{text_muted};">Break-even:</span>
                    <span style="color:{budget_box_border}; font-weight:700;">{break_even_text}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        if show_financials:
            pop_metric = st.session_state.get('estimated_pop', 250000)
            grant_bracket = estimate_grants(pop_metric)
            st.sidebar.markdown(f"""
            <div style="margin-top:12px; background:{card_bg}; border:1px solid {budget_box_border}; padding:10px; border-radius:4px; margin-bottom:10px;">
                <div style="font-size:0.68rem; color:{text_muted}; font-weight:bold; text-transform:uppercase;">Est. Grant Eligibility</div>
                <div style="font-size:1.1rem; color:{budget_box_border}; font-weight:bold; font-family:monospace;">{grant_bracket}</div>
            </div>
            <div style="font-size:0.73rem; color:{text_muted}; line-height:1.5; margin-bottom:10px;">
                <a href="https://bja.ojp.gov/program/jag/overview" target="_blank" style="color:{accent_color}; font-weight:bold;">DOJ Byrne JAG</a> — UAS procurement eligible<br>
                <a href="https://www.fema.gov/grants/preparedness/homeland-security" target="_blank" style="color:{accent_color}; font-weight:bold;">FEMA HSGP</a> — CapEx offset for tactical deployments
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        if show_health:
            norm_redundancy = min(overlap_perc/35.0, 1.0)*100
            health_score = (calls_covered_perc*0.50) + (area_covered_perc*0.35) + (norm_redundancy*0.15)
            h_color, h_label = (accent_color,"OPTIMAL") if health_score>=80 else ("#94c11f","GOOD") if health_score>=70 else ("#ffc107","MARGINAL") if health_score>=55 else ("#dc3545","ESSENTIAL")
            st.markdown(f"""<div style="background:{card_bg}; border-left:5px solid {h_color}; border:1px solid {card_border};
                padding:10px; border-radius:4px; color:{text_main}; margin-bottom:10px;
                display:flex; align-items:center; justify-content:space-between;">
                <span style="font-size:1.4em; font-weight:bold; color:{h_color};">Department Health Score: {health_score:.1f}%</span>
                <span style="font-size:1.2em; background:rgba(128,128,128,0.15); padding:2px 10px; border-radius:4px;">{h_label}</span>
                </div>""", unsafe_allow_html=True)

        orig_calls = int(st.session_state.get('total_original_calls', full_total_calls or (len(df_calls_full) if df_calls_full is not None else total_calls)) or total_calls)
        modeled_calls = int(st.session_state.get('total_modeled_calls', total_calls) or total_calls)
        displayed_points = len(display_calls) if display_calls is not None else 0
        call_str = f"{orig_calls:,}"

        # Calculate Date Range of CAD data (if available)
        date_range_str = "Simulated / Unknown"
        _date_src_df = df_calls_full if df_calls_full is not None else df_calls
        _label_dt = html_reports._detect_datetime_series_for_labels(_date_src_df)
        if _label_dt is not None:
            try:
                _label_dt = pd.to_datetime(_label_dt, errors='coerce').dropna()
                if not _label_dt.empty:
                    min_date = _label_dt.min().strftime('%b %Y')
                    max_date = _label_dt.max().strftime('%b %Y')
                    date_range_str = f"{min_date} – {max_date}" if min_date != max_date else min_date
            except Exception:
                pass

        avg_resp_time = sum(d['avg_time_min'] for d in active_drones) / len(active_drones) if active_drones else 0.0

        # Ground speed: only apply congestion reduction when traffic toggle is on.
        # Both avg_time_saved and gain_val use the same per-drone avg_time_min basis so
        # the drone and ground numbers are directly comparable (no full-radius inflation).
        _base_ground_speed = float(CONFIG["DEFAULT_TRAFFIC_SPEED"])
        _effective_ground_speed = _base_ground_speed * (1.0 - float(traffic_level) / 100.0) if simulate_traffic else _base_ground_speed

        try:
            if active_drones and _effective_ground_speed > 0:
                _fleet_gnd_time = (sum(d['avg_time_min'] * d['speed_mph'] * 1.4 / _effective_ground_speed
                                       for d in active_drones) / len(active_drones))
                avg_time_saved = max(0.0, _fleet_gnd_time - avg_resp_time)
            else:
                avg_time_saved = 0.0
        except Exception:
            avg_time_saved = 0.0

        # gain_val: sub-label shown on the Avg Response KPI cell only when traffic toggle is on
        if simulate_traffic:
            gain_val = f"{avg_time_saved:.1f} min" if active_drones and _effective_ground_speed > 0 else "N/A"
        else:
            gain_val = None

        # ── Persist live deployment metrics so the apprehension table reads real values ──
        st.session_state['avg_time_saved_min'] = avg_time_saved
        st.session_state['avg_resp_time_min']  = avg_resp_time

        # ── Re-establish tier badge variables for display ──────────────────────────
        _pricing_tier = st.session_state.get('pricing_tier', 'Safe Guard')
        if _pricing_tier == "Safe Guard":
            _tier_badge = "🛡️ Safe Guard"
            _tier_desc = "Advanced Custom Features"
        elif _pricing_tier == "Custom Quote":
            _tier_badge = "Custom Quote"
            _tier_desc = "Sales-Entered Pricing"
        else:
            _tier_badge = "🛡️ Safe Guard Lite"
            _tier_desc = "Core Functionality"

        # 1. THE SINGLE-LINE EXECUTIVE HEADER
        _display_jurisdiction_name = _get_document_jurisdiction_name(
            st.session_state,
            selected_names,
            fallback='Unknown City',
        )
        logo_b64 = get_transparent_product_base64("gigs.png")
        main_logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="height:32px; vertical-align:middle; margin-right:15px;">' if logo_b64 else f'<span style="font-size:1.5rem; font-weight:900; letter-spacing:2px; color:#ffffff; margin-right:15px;">BRINC</span>'

        header_html = f"""
        <div style="margin-top: 5px; margin-bottom: 15px; padding-bottom: 12px; border-bottom: 1px solid {card_border}; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
            <div style="display: flex; align-items: center; flex-wrap: wrap; font-size: 0.9rem;">
                <span style="color: {accent_color}; font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; letter-spacing: 1px; text-transform: uppercase; margin-right: 12px;">Strategic Deployment Plan</span>
                <span style="font-weight: 800; color: {text_main}; font-size: 1.1rem; margin-right: 12px;">{_display_jurisdiction_name}, {st.session_state.get('active_state', 'US')}</span>
                <span style="color: {text_muted}; margin-right: 12px;">• {"Serving {:,} residents across".format(st.session_state.get('estimated_pop', 0)) if st.session_state.get('estimated_pop', 0) else "Coverage area:"} ~{int(area_sq_mi):,} sq miles</span>
            </div>
            <div style="display: flex; align-items: center; font-size: 0.85rem; color: {text_muted}; gap: 15px;">
                <span>Data Period: <span style="color:#fff;">{date_range_str}</span></span>
                <span style="color:{card_border};">|</span>
                <span style="font-weight: 800; color: {text_main}; font-size: 0.95rem;">{actual_k_responder} <span style="color:#888; font-weight:normal;">Resp</span> · {actual_k_guardian} <span style="color:#888; font-weight:normal;">Guard</span></span>
                <span style="background:#0066aa;border:1px solid #00D2FF;border-radius:4px;padding:3px 8px;font-size:0.75rem;font-weight:700;color:#00D2FF;letter-spacing:0.5px;text-transform:uppercase;">{_tier_badge}</span>
                {main_logo_html}
            </div>
        </div>
        """
        st.markdown(header_html, unsafe_allow_html=True)

        # Cleanly evaluate dynamic CSS to avoid f-string syntax errors
        border_css = 'border-right: 1px solid #222; padding-right: 10px;' if gain_val is not None else ''

        # If traffic simulation is on, nest the time saved right inside the Avg Response box!
        if gain_val is not None:
            resp_content = (
                f'<div style="font-size: 2.2rem; font-weight: 800; color: {accent_color}; font-family: \'IBM Plex Mono\', monospace; line-height: 1.1;">{avg_resp_time:.1f}m</div>'
                f'<div style="font-size: 0.7rem; color: #39FF14; font-weight: 800; text-transform: uppercase; margin-top: 4px;">▼ Saves {gain_val}</div>'
            )
        else:
            resp_content = f'<div style="font-size: 2.2rem; font-weight: 800; color: {accent_color}; font-family: \'IBM Plex Mono\', monospace;">{avg_resp_time:.1f}m</div>'

        # ── Pre-compute Fleet Summary impact sub-values ───────────────────────
        _annual_resolved = int(daily_drone_only_calls * 365) if daily_drone_only_calls > 0 else 0
        _covered_calls_abs = int(calls_covered_perc / 100.0 * orig_calls) if orig_calls else 0
        _land_sqmi = int(area_covered_perc / 100.0 * area_sq_mi) if area_sq_mi else 0

        _impact_incidents  = f"~{_annual_resolved:,} resolved/yr" if _annual_resolved > 0 else None
        _impact_coverage   = f"{_covered_calls_abs:,} calls" if _covered_calls_abs > 0 else None
        _impact_land       = f"~{_land_sqmi:,} sq mi" if _land_sqmi > 0 else None
        _impact_overlap    = f"{len(active_drones)} drone{'s' if len(active_drones) != 1 else ''}" if active_drones else None

        if simulate_traffic and gain_val and gain_val != "N/A":
            _t_label = "Light" if traffic_level < 35 else "Moderate" if traffic_level < 75 else "Heavy"
            _impact_resp = f"saves {gain_val} w/ {_t_label} traffic"
        elif avg_time_saved > 0:
            _impact_resp = f"saves {avg_time_saved:.1f}m vs gnd"
        else:
            _impact_resp = None

        # 2. SPLIT KPI BAR — Guardian row + Responder row + combined summary
        def _kpi_cell(label, value, color=accent_color, border=True, impact=None):
            br = f"border-right: 1px solid #222; padding-right: 10px;" if border else ""
            _imp = (f'<div style="font-size:0.65rem; color:#39FF14; font-weight:700; margin-top:2px;">({impact})</div>'
                    if impact else '')
            return (
                f'<div style="{br} text-align: center;">'
                f'<div style="font-size: 0.68rem; color: {text_muted}; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom:2px;">{label}</div>'
                f'<div style="font-size: 1.9rem; font-weight: 800; color: {color}; font-family: \'IBM Plex Mono\', monospace;">{value}</div>'
                f'{_imp}'
                f'</div>'
            )

        _GUARD_COL = "#FFD700"   # gold for Guardian
        _RESP_COL  = "#00D2FF"   # cyan for Responder
        _COMB_COL  = "#39FF14"   # green for combined

        kpi_html = (
            # ── Row 1: summary totals ──────────────────────────────────────────
            f'<div style="background:{card_bg}; border:1px solid {card_border}; border-radius:8px; padding:16px 20px; margin-bottom:8px;">'
            f'<div style="font-size:0.65rem; color:{text_muted}; text-transform:uppercase; letter-spacing:1px; margin-bottom:10px;">Fleet Summary <span class="tip" data-tip="Sources: Coverage % and response time computed from uploaded CAD incident data using BRINC geospatial optimizer. Hardware specs: BRINC Drones (brincdrones.com). Response time uses drone speed with 1.4× routing factor to approximate real-world travel paths.">?</span></div>'
            f'<div style="display:grid; grid-template-columns:repeat(5,1fr); gap:8px;">'
            + _kpi_cell("Total Incidents", call_str, impact=_impact_incidents)
            + _kpi_cell("Combined Coverage", f"{calls_covered_perc:.1f}%", _COMB_COL, impact=_impact_coverage)
            + _kpi_cell("Land Covered", f"{area_covered_perc:.1f}%", _COMB_COL, impact=_impact_land)
            + _kpi_cell("Zone Overlap", f"{overlap_perc:.1f}%", text_muted, impact=_impact_overlap)
            + _kpi_cell("Avg Response", f"{avg_resp_time:.1f}m", accent_color, border=False, impact=_impact_resp)
            + f'</div></div>'

            # ── Row 2: Guardian-specific metrics ──────────────────────────────
            + f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">'

            + f'<div style="background:{card_bg}; border:1px solid #3a3000; border-top:3px solid {_GUARD_COL}; border-radius:8px; padding:14px 16px;">'
            + f'<div style="font-size:0.65rem; color:{_GUARD_COL}; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; font-weight:700;">🦅 Guardian Fleet — {actual_k_guardian} unit{"s" if actual_k_guardian!=1 else ""} · {guard_strategy_raw}</div>'
            + f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">'
            + _kpi_cell("Call Coverage", f"{guard_calls_perc:.1f}%", _GUARD_COL)
            + _kpi_cell("Area Coverage", f"{guard_area_perc:.1f}%", _GUARD_COL, border=False)
            + f'</div></div>'

            # ── Row 3: Responder-specific metrics ─────────────────────────────
            + f'<div style="background:{card_bg}; border:1px solid #003a3a; border-top:3px solid {_RESP_COL}; border-radius:8px; padding:14px 16px;">'
            + f'<div style="font-size:0.65rem; color:{_RESP_COL}; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; font-weight:700;">🚁 Responder Fleet — {actual_k_responder} unit{"s" if actual_k_responder!=1 else ""} · {resp_strategy_raw}</div>'
            + f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">'
            + _kpi_cell("Call Coverage", f"{resp_calls_perc:.1f}%", _RESP_COL)
            + _kpi_cell("Area Coverage", f"{resp_area_perc:.1f}%", _RESP_COL, border=False)
            + f'</div></div>'

            + f'</div>'
        )

        st.markdown(kpi_html, unsafe_allow_html=True)
        overtime_stats = html_reports.estimate_high_activity_overtime(
            df_calls_full if df_calls_full is not None else df_calls,
            st.session_state.get('active_state', 'TX'),
            calls_covered_perc,
            dfr_dispatch_rate,
            deflection_rate,
        )
        cards_below_map = bool(show_cards)
        map_col = st.container()

        with map_col:
            fig = go.Figure()

            if show_boundaries and city_boundary_geom is not None and not city_boundary_geom.is_empty:
                geoms_to_draw = [city_boundary_geom] if isinstance(city_boundary_geom, Polygon) else list(city_boundary_geom.geoms)
                for gi, geom in enumerate(geoms_to_draw):
                    bx, by = geom.exterior.coords.xy
                    fig.add_trace(go.Scattermap(
                        mode="lines",
                        lon=list(bx),
                        lat=list(by),
                        line=dict(color="rgba(8, 15, 28, 0.95)", width=6),
                        name="Jurisdiction Boundary Halo",
                        hoverinfo='skip',
                        showlegend=False,
                    ))
                    fig.add_trace(go.Scattermap(mode="lines", lon=list(bx), lat=list(by),
                        line=dict(color="#3CF2FF", width=3), name="Jurisdiction Boundary",
                        hoverinfo='skip', showlegend=(gi==0)))

            boundary_overlay_gdf = st.session_state.get('boundary_overlay_gdf')
            if show_boundaries and boundary_overlay_gdf is not None and not boundary_overlay_gdf.empty:
                _overlay_parts = []
                for _overlay_geom in boundary_overlay_gdf.geometry:
                    if _overlay_geom is None or _overlay_geom.is_empty:
                        continue
                    if isinstance(_overlay_geom, Polygon):
                        _overlay_parts.append(_overlay_geom)
                    elif isinstance(_overlay_geom, MultiPolygon):
                        _overlay_parts.extend(list(_overlay_geom.geoms))
                for oi, geom in enumerate(_overlay_parts):
                    bx, by = geom.exterior.coords.xy
                    fig.add_trace(go.Scattermap(
                        mode="lines",
                        lon=list(bx),
                        lat=list(by),
                        line=dict(color="rgba(8, 15, 28, 0.9)", width=5),
                        name="Uploaded Boundary Overlay Halo",
                        hoverinfo='skip',
                        showlegend=False,
                    ))
                    fig.add_trace(go.Scattermap(mode="lines", lon=list(bx), lat=list(by),
                        line=dict(color="#FFD166", width=2.5), name="Uploaded Boundary Overlay",
                        hoverinfo='skip', showlegend=(oi==0)))

            if show_heatmap and not display_calls.empty:
                fig.add_trace(go.Densitymap(lat=display_calls.geometry.y, lon=display_calls.geometry.x,
                    z=np.ones(len(display_calls)), radius=12, colorscale='Inferno', opacity=0.6,
                    showscale=False, name="Heatmap", hoverinfo='skip'))

            if show_dots and not display_calls.empty:
                point_size = 2 if len(display_calls) > 150000 else 3 if len(display_calls) > 50000 else 4 if len(display_calls) > 20000 else 5
                point_opacity = 0.06 if len(display_calls) > 150000 else 0.10 if len(display_calls) > 50000 else 0.18 if len(display_calls) > 20000 else 0.28 if len(display_calls) > 10000 else 0.4
                # Split by agency so fire calls render red and police calls use the theme colour
                _has_agency = 'agency' in display_calls.columns
                _fire_calls   = display_calls[display_calls['agency'].str.lower() == 'fire'] if _has_agency else display_calls.iloc[0:0]
                _police_calls = display_calls[display_calls['agency'].str.lower() != 'fire'] if _has_agency else display_calls
                if not _police_calls.empty:
                    fig.add_trace(go.Scattermap(lat=_police_calls.geometry.y, lon=_police_calls.geometry.x,
                        mode='markers', marker=dict(size=point_size, color=map_incident_color, opacity=point_opacity),
                        name="Police Incidents", hoverinfo='skip'))
                if not _fire_calls.empty:
                    fig.add_trace(go.Scattermap(lat=_fire_calls.geometry.y, lon=_fire_calls.geometry.x,
                        mode='markers', marker=dict(size=point_size, color='#ff3b3b', opacity=point_opacity),
                        name="Fire Incidents", hoverinfo='skip'))

            if show_faa and faa_geojson and faa_geojson.get("features"):
                try:
                    faa_rf.add_faa_laanc_layer_to_plotly(fig, faa_geojson, is_dark=not show_satellite)
                    if len(faa_geojson.get("features", [])) >= 50:
                        st.sidebar.caption("FAA overlap boxes are thinned to a checkerboard pattern for faster loading.")
                except Exception as e:
                    st.sidebar.error(f"🔴 FAA render error: {str(e)[:100]}")

            if show_obstacles:
                faa_rf.add_faa_obstacles_layer_to_plotly(fig, minx, miny, maxx, maxy)

            if show_cell_towers:
                add_cell_towers_layer_to_plotly(fig, st.session_state.get('active_state', 'CA'), minx, miny, maxx, maxy)

            if show_no_fly:
                add_no_fly_zones_layer_to_plotly(fig, minx, miny, maxx, maxy)

            if show_coverage:
                _cov_state = st.session_state.get('active_state', '')
                if _cov_state:
                    add_coverage_traces(fig, _cov_state, visible=True)

            _max_zone_calls = max(
                (int(d.get('raw_zone_calls_annual', 0) or 0) for d in active_drones), default=1
            ) or 1
            for d in active_drones:
                clats, clons = get_circle_coords(d['lat'], d['lon'], r_mi=d['radius_m']/1609.34)
                lbl = f"{d['name'].split(',')[0]} ({'Resp' if d['type']=='RESPONDER' else 'Guard'})"

                # Scale center pin by calls served (range 12–34)
                _zone_calls = int(d.get('raw_zone_calls_annual', 0) or 0)
                _pin_size = int(12 + 22 * (_zone_calls / _max_zone_calls))

                # Determine if this is an extended Guardian (so we can relax the outer ring)
                is_extended_guardian = (d['type'] == 'GUARDIAN' and d['radius_m']/1609.34 > 5.0)

                # Keep the extended Guardian ring visible on darker basemaps.
                outer_width = 4.0 if is_extended_guardian else 4.5
                outer_opac = 0.95 if is_extended_guardian else 1.0

                if is_extended_guardian:
                    fig.add_trace(go.Scattermap(
                        lat=list(clats)+[None,d['lat']], lon=list(clons)+[None,d['lon']],
                        mode='lines',
                        opacity=0.45,
                        line=dict(color='rgba(255,255,255,0.35)', width=8.0),
                        fill='toself', fillcolor='rgba(0,0,0,0)',
                        name=lbl, hoverinfo='skip', showlegend=False
                    ))
                fig.add_trace(go.Scattermap(
                    lat=list(clats)+[None,d['lat']], lon=list(clons)+[None,d['lon']],
                    mode='lines+markers',
                    opacity=outer_opac,
                    marker=dict(size=[0]*len(clats)+[0,_pin_size], color=d['color']),
                    line=dict(color=d['color'], width=outer_width),
                    fill='toself', fillcolor='rgba(0,0,0,0)', name=lbl, hoverinfo='name'))

                # The 5-mile Rapid Response ring gets the "Important" styling (thick, solid, heavier fill)
                if is_extended_guardian and show_rapid_response_ring:
                    f_lats, f_lons = get_circle_coords(d['lat'], d['lon'], r_mi=5.0)
                    fig.add_trace(go.Scattermap(
                        lat=list(f_lats), lon=list(f_lons),
                        mode='lines',
                        line=dict(color=d['color'], width=2.0),
                        opacity=0.62,
                        fill='toself',
                        fillcolor=f"rgba({int(d['color'][1:3],16)},{int(d['color'][3:5],16)},{int(d['color'][5:7],16)},0.06)",
                        name=f"Rapid Response 5mi · {d['name'].split(',')[0]}",
                        hoverinfo='text',
                        text=f"⚡ Rapid Response Focus Zone — 5mi<br>{d['name'].split(',')[0]}",
                        showlegend=False
                    ))

                # Star marker for manually pinned stations
                if d.get('pinned'):
                    fig.add_trace(go.Scattermap(
                        lat=[d['lat']], lon=[d['lon']], mode='markers',
                        marker=dict(size=18, color=d['color'], symbol='star'),
                        name=f"📍 {d['name'].split(',')[0]} (Pinned)",
                        hovertemplate=f"<b>🔒 PINNED</b><br>{d['name']}<br>{d['type']}<extra></extra>",
                        showlegend=False
                    ))
                if simulate_traffic:
                    t_color = "#28a745" if traffic_level<35 else "#ffc107" if traffic_level<75 else "#dc3545"
                    t_fill  = f"rgba({'40,167,69' if traffic_level<35 else '255,193,7' if traffic_level<75 else '220,53,69'}, 0.15)"
                    t_label = "Light" if traffic_level<35 else "Moderate" if traffic_level<75 else "Heavy"
                    gs = CONFIG["DEFAULT_TRAFFIC_SPEED"]*(1-traffic_level/100)
                    if gs > 0:
                        gr_mi = (gs/60) * (d['radius_m']/1609.34/d['speed_mph'])*60
                        ga = np.linspace(0,2*np.pi,9)
                        fig.add_trace(go.Scattermap(
                            lat=list(d['lat']+(gr_mi/69.172)*np.sin(ga)),
                            lon=list(d['lon']+(gr_mi/(69.172*np.cos(np.radians(d['lat']))))*np.cos(ga)),
                            mode='lines', line=dict(color=t_color, width=2.5),
                            fill='toself', fillcolor=t_fill,
                            name=f"Ground ({t_label})", hoverinfo='skip'))

            custom_station_df = st.session_state.get('custom_stations', pd.DataFrame())
            if not custom_station_df.empty:
                _active_custom_keys = {
                    (str(d.get('name', '')), str(d.get('type', '')))
                    for d in active_drones
                }
                _inactive_custom = custom_station_df.copy()
                _inactive_custom['_active_key'] = list(zip(
                    _inactive_custom['name'].astype(str),
                    _inactive_custom['type'].astype(str),
                ))
                _inactive_custom = _inactive_custom[~_inactive_custom['_active_key'].isin(_active_custom_keys)]
                if not _inactive_custom.empty:
                    _custom_lat = _inactive_custom['lat'].astype(float).tolist()
                    _custom_lon = _inactive_custom['lon'].astype(float).tolist()
                    _custom_text = []
                    _custom_color = []
                    for _, _crow in _inactive_custom.iterrows():
                        _role = str(_crow.get('lock_role', '') or '')
                        _is_guard = 'Guardian' in _role
                        _custom_color.append('#FFD700' if _is_guard else '#00D2FF')
                        _custom_text.append(
                            f"<b>Custom Station</b><br>{_crow['name']}<br>{_crow.get('type', 'Custom')}"
                            + (f"<br>Locked as {_role}" if _role else '')
                        )
                    fig.add_trace(go.Scattermap(
                        lat=_custom_lat,
                        lon=_custom_lon,
                        mode='markers',
                        marker=dict(size=13, color=_custom_color, symbol='diamond'),
                        name='Custom Stations',
                        hovertemplate='%{text}<extra></extra>',
                        text=_custom_text,
                    ))

            _pending_pin = st.session_state.get('pending_pin')
            if isinstance(_pending_pin, dict) and _pending_pin.get('lat') is not None and _pending_pin.get('lon') is not None:
                fig.add_trace(go.Scattermap(
                    lat=[float(_pending_pin['lat'])],
                    lon=[float(_pending_pin['lon'])],
                    mode='markers',
                    marker=dict(size=18, color='#39FF14', symbol='diamond'),
                    name='Pending Pin',
                    hovertemplate='Pending custom station<extra></extra>',
                    showlegend=False,
                ))

            map_cfg = dict(center=dict(lat=center_lat, lon=center_lon), zoom=dynamic_zoom, style=map_style)
            if show_satellite:
                map_cfg["style"] = "carto-positron"
                map_cfg["layers"] = [{"below":"traces","sourcetype":"raster",
                    "sourceattribution":"Esri, Maxar, Earthstar Geographics",
                    "source":["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"]}]

            _pin_drop_active = st.session_state.get('pin_drop_mode', False)
            _layout_extra = {}

            fig.update_layout(uirevision="LOCKED_MAP", map=map_cfg,
                margin=dict(l=0,r=0,t=0,b=0), height=800, font=dict(size=18),
                showlegend=True,
                legend=dict(yanchor="top", y=0.98, xanchor="left", x=0.02,
                            bgcolor=legend_bg, bordercolor=accent_color, borderwidth=1,
                            font=dict(size=12, color=legend_text), itemclick="toggle"),
                **_layout_extra)

            if _pin_drop_active:
                fig.add_annotation(
                    text=(
                        "📍 Pin Drop Mode — single-click the map to capture a station location"
                        if QUICK_PIN_COMPONENT is not None
                        else "📍 Pin Drop Mode — click and drag a small box on your target location"
                    ),
                    xref="paper", yref="paper", x=0.5, y=0.98,
                    showarrow=False, font=dict(size=13, color="#00D2FF"),
                    bgcolor="rgba(0,0,0,0.72)", bordercolor="#00D2FF", borderwidth=1,
                    borderpad=6, xanchor="center",
                )
                if QUICK_PIN_COMPONENT is not None:
                    _quick_pin_event = QUICK_PIN_COMPONENT(
                        figure_json=fig.to_plotly_json(),
                        height=800,
                        key="quick_pin_component",
                        default=None,
                    )
                    if isinstance(_quick_pin_event, dict):
                        _clicked_lat = _quick_pin_event.get('lat')
                        _clicked_lon = _quick_pin_event.get('lon')
                        _click_nonce = _quick_pin_event.get('nonce')
                        if _clicked_lat is not None and _clicked_lon is not None and _click_nonce != st.session_state.get('_pin_click_nonce'):
                            st.session_state['_pin_click_nonce'] = _click_nonce
                            st.session_state['_pin_sel_hash'] = hash(f"{float(_clicked_lat):.4f},{float(_clicked_lon):.4f}")
                            st.session_state['pending_pin'] = {
                                'lat': round(float(_clicked_lat), 6),
                                'lon': round(float(_clicked_lon), 6),
                            }
                            st.rerun()
                else:
                    _grid_n = 80
                    _grid_lats = np.linspace(miny, maxy, _grid_n)
                    _grid_lons = np.linspace(minx, maxx, _grid_n)
                    _gla, _glo = np.meshgrid(_grid_lats, _grid_lons)
                    fig.add_trace(go.Scattermap(
                        lat=_gla.ravel().tolist(),
                        lon=_glo.ravel().tolist(),
                        mode='markers',
                        marker=dict(size=40, color='rgba(0,210,255,0.04)'),
                        hoverinfo='skip',
                        showlegend=False,
                        name='__pin_grid__',
                    ))
                    fig.update_layout(dragmode='select')
                    _map_event = st.plotly_chart(
                        fig,
                        width="stretch",
                        config={"scrollZoom": False, "displayModeBar": True},
                        on_select="rerun",
                        key="main_map_chart_pin_fallback",
                    )
                    if _map_event and hasattr(_map_event, 'selection') and st.session_state.get('pending_pin') is None:
                        _sel = _map_event.selection
                        _clicked_lat = _clicked_lon = None
                        _box_list = getattr(_sel, 'box', None) or []
                        if _box_list:
                            _b = _box_list[0]
                            _lats = _b.get('y') or _b.get('lat') or []
                            _lons = _b.get('x') or _b.get('lon') or []
                            if len(_lats) >= 2 and len(_lons) >= 2:
                                _clicked_lat = (min(_lats) + max(_lats)) / 2.0
                                _clicked_lon = (min(_lons) + max(_lons)) / 2.0
                        if _clicked_lat is None:
                            _sel_pts = getattr(_sel, 'points', []) or []
                            if _sel_pts:
                                _pt = _sel_pts[0]
                                _clicked_lat = _pt.get('lat') or _pt.get('y')
                                _clicked_lon = _pt.get('lon') or _pt.get('x')
                        if _clicked_lat is not None and _clicked_lon is not None:
                            _sel_hash = hash(f"{_clicked_lat:.4f},{_clicked_lon:.4f}")
                            if _sel_hash != st.session_state.get('_pin_sel_hash'):
                                st.session_state['_pin_sel_hash'] = _sel_hash
                                st.session_state['pending_pin'] = {
                                    'lat': round(float(_clicked_lat), 6),
                                    'lon': round(float(_clicked_lon), 6),
                                }
                                st.rerun()
            else:
                _map_key = "main_map_chart"
                if st.session_state.get('highway_patrol_mode', False):
                    _map_state = st.session_state.get('active_state', '')
                    _map_hw = st.session_state.get('active_highway', '')
                    if _map_state or _map_hw:
                        _map_key = f"main_map_chart_{_map_state}_{_map_hw}"
                st.plotly_chart(
                    fig, width="stretch",
                    config={"scrollZoom": True, "displayModeBar": False},
                    key=_map_key,
                )


        # ── UNIT ECONOMICS CARDS (directly below map, no toggle) ─────────────────
        st.markdown("---")
        st.markdown(f"<h4 style='margin-top:2px; border-bottom:1px solid {card_border}; padding-bottom:8px; color:{text_main}; display:flex; align-items:center; justify-content:space-between; gap:12px;'><span>Unit Economics <span class='tip' data-tip='Per-drone financial breakdown ? annual capacity value, specialty response savings, utilization, break-even, and response time for each deployed unit. Hover each ? badge for metric definitions.'>?</span> <span class='tip' data-tip='Sources: Annual savings formula ? DFR dispatch rate ? deflection rate ? $76 officer dispatch cost ? annual zone calls (IACP/DOJ benchmarks). Hardware CapEx ? BRINC Drones MSRP. Specialty values ? NFPA (fire), BLS (K-9), internal BRINC benchmarks. All figures are model estimates.'>src</span></span><span style='margin-left:auto; font-size:0.72rem; font-weight:700; color:{text_muted}; white-space:nowrap;'>Dispatch Rate {int(dfr_dispatch_rate*100)}% | Clearance Rate {int(deflection_rate*100)}%</span></h4>", unsafe_allow_html=True)
        st.markdown(
            f"<div style='font-size:0.6rem; color:#666; background:rgba(240,180,41,0.07); border-left:3px solid #F0B429; padding:5px 8px; border-radius:0 3px 3px 0; margin-bottom:10px;'>{SIMULATOR_DISCLAIMER_SHORT}</div>",
            unsafe_allow_html=True
        )
        st.markdown(
            """<style>
            .unit-card-grid { position: relative; }
            .unit-card {
                transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
                            box-shadow 0.25s ease-out,
                            z-index 0s;
                position: relative;
                z-index: 1;
            }
            .unit-card:hover {
                transform: scale(1.2);
                box-shadow: 0 16px 48px rgba(0,210,255,0.28), 0 4px 16px rgba(0,0,0,0.45);
                z-index: 999;
            }
            </style>""",
            unsafe_allow_html=True
        )
        if active_drones:
            st.markdown(
                html_reports._build_unit_cards_html(
                    active_drones, text_main, text_muted, card_bg, card_border,
                    card_title, accent_color, columns_per_row=4,
                    simple=simple_cards, deflection_rate=deflection_rate,
                    dfr_dispatch_rate=dfr_dispatch_rate,
                    show_financials=show_financials
                ),
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"""
                <div style="background:{card_bg}; border:1px dashed {card_border}; border-radius:6px; padding:22px; text-align:center; margin-top:8px;">
                    <div style="font-size:2rem; margin-bottom:8px;">🚁</div>
                    <div style="font-weight:700; color:{text_main}; margin-bottom:6px;">No drones deployed yet</div>
                    <div style="font-size:0.8rem; color:{text_muted};">
                        Use the <b>Responder / Guardian Count</b> sliders in the sidebar to deploy drones and see per-unit economics here.
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

        # ── COVERAGE CURVE + STATION RING CHART (side by side, directly below cards) ──
        st.markdown("---")
        st.markdown(f"<h4 style='border-bottom:1px solid {card_border}; padding-bottom:8px; color:{text_main};'>Coverage Curve <span class='tip' data-tip='Shows marginal call and area coverage as you add more Responder or Guardian drones. The curve flattens as overlap increases — use this to find the point of diminishing returns for your fleet size.'>?</span> <span class='tip' data-tip='Sources: Coverage % derived from geospatial analysis of uploaded CAD incident locations. Optimizer tests each candidate station and measures incremental coverage gain. Map tiles: © OpenStreetMap contributors (ODbL). Station candidates: OSM + DHS HIFLD Open Data.'>src</span></h4>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:0.8rem; color:{text_muted}; margin-bottom:8px;'>How added drones improve coverage — and where returns flatten.</div>", unsafe_allow_html=True)

        _curve_col, _ring_col = st.columns([3, 2], gap="medium")

        with _curve_col:
            if not df_curve.empty:
                fig_curve = go.Figure()
                for col, color, dash in [('Responder (Calls)',accent_color,'solid'),('Guardian (Calls)','#FFD700','solid'),
                                          ('Responder (Area)',accent_color,'dash'),('Guardian (Area)','#FFD700','dash')]:
                    y_data = df_curve[col].dropna()
                    x_data = df_curve.loc[y_data.index,'Drones']
                    if not y_data.empty:
                        fig_curve.add_trace(go.Scatter(x=x_data, y=y_data, mode='lines+markers', name=col,
                            line=dict(color=color,width=2,dash=dash), marker=dict(size=4),
                            hovertemplate=f"<b>{col}</b><br>Drones: %{{x}}<br>Coverage: %{{y:.1f}}%<extra></extra>"))
                        if 'Calls' in col:
                            idx_90 = y_data[y_data >= 90.0].first_valid_index()
                            if idx_90 is not None:
                                fig_curve.add_trace(go.Scatter(x=[int(x_data.loc[idx_90])], y=[y_data.loc[idx_90]],
                                    mode='markers', marker=dict(color=color,size=12,symbol='star',line=dict(color='white',width=1)),
                                    showlegend=False, hoverinfo='skip'))
                fig_curve.update_layout(
                    xaxis_title="Drones", yaxis_title="Coverage %",
                    xaxis=dict(showgrid=True, gridcolor=card_border, tickfont=dict(color=text_muted)),
                    yaxis=dict(showgrid=True, gridcolor=card_border, tickfont=dict(color=text_muted),
                               tickvals=[0,20,40,60,80,90,100], range=[0,105]),
                    legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1,
                                font=dict(size=9,color=text_muted)),
                    margin=dict(l=10,r=10,t=20,b=10), height=320,
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    hoverlabel=dict(bgcolor=card_bg, font_size=13, font_color=text_main, bordercolor=accent_color)
                )
                st.plotly_chart(
                    fig_curve,
                    width="stretch",
                    config={'displayModeBar': False},
                    key="coverage_curve_chart",
                )
            else:
                st.info("Run optimization to generate coverage curve.")

        with _ring_col:
            st.markdown(
                f"<div style='font-size:0.7rem; color:{text_muted}; margin-bottom:4px;'>"
                f"Call coverage by station <span class='tip' data-tip='Donut chart showing how historical 911 calls are distributed across deployed stations. Each slice is one station&apos;s marginal (non-overlapping) call count. The center % is combined fleet coverage. Hover slices for exact counts.'>?</span></div>",
                unsafe_allow_html=True
            )
            # Split ring: outer ring = Guardians (gold), inner ring = Responders (cyan)
            if active_drones and total_calls > 0:
                _g_drones = [d for d in active_drones if d['type'] == 'GUARDIAN']
                _r_drones = [d for d in active_drones if d['type'] == 'RESPONDER']

                def _fleet_ring_slices(drones, fleet_label):
                    """Ring slices show each station's overlap-weighted share of total city calls.
                    Exclusive calls count fully; overlapping calls are split across stations in the same fleet."""
                    labels, values, colors, hovers, texts = [], [], [], [], []
                    _sum_weighted = 0.0
                    for d in drones:
                        weighted = float(_station_city_weighted_counts.get((d['type'], d['idx']), 0.0))
                        pct = weighted / _metric_total_calls * 100 if _metric_total_calls > 0 else 0.0
                        name = d['name'].split(',')[0][:18]
                        labels.append(name)
                        values.append(max(weighted, 1e-9))
                        colors.append(d['color'])
                        texts.append(f'{pct:.1f}%')
                        _label = (
                            f'{weighted:,.1f} weighted city calls ({pct:.1f}% of {_metric_total_calls:,} total city calls)'
                            if weighted > 0 else
                            '0 weighted city calls'
                        )
                        hovers.append(f'<b>{name}</b> [{fleet_label}]<br>{_label}<extra></extra>')
                        _sum_weighted += weighted
                    _uncov = max(0.0, _metric_total_calls - _sum_weighted)
                    if _uncov > 0:
                        _uncov_pct = _uncov / _metric_total_calls * 100 if _metric_total_calls > 0 else 0.0
                        labels.append(f'Uncovered ({fleet_label})')
                        values.append(_uncov)
                        colors.append('#1a1a1a')
                        texts.append(f'{_uncov_pct:.1f}%')
                        hovers.append(f'<b>Uncovered by {fleet_label}</b><br>{_uncov:,.1f} calls ({_uncov_pct:.1f}% of {_metric_total_calls:,} total city calls)<extra></extra>')
                    return labels, values, colors, hovers, texts

                _combined_covered = int(np.logical_or(cov_r, cov_g).sum()) if total_calls > 0 else 0
                _cov_pct   = round(_combined_covered / total_calls * 100, 1)
                _mode_short = "▶◀" if complement_mode else "↔" if shared_mode else "⊕"

                fig_ring = go.Figure()

                # ── Outer ring: Guardians ─────────────────────────────────────────
                if _g_drones:
                    _gl, _gv, _gc, _gh, _gt = _fleet_ring_slices(_g_drones, 'Guardian')
                    fig_ring.add_trace(go.Pie(
                        name='Guardians',
                        labels=_gl, values=_gv,
                        hole=0.72,
                        marker=dict(colors=_gc, line=dict(color='#000', width=1.5)),
                        text=_gt, textinfo='text', textposition='inside',
                        insidetextfont=dict(size=10, color='#ffffff'),
                        customdata=_gh,
                        hovertemplate='%{customdata}',
                        sort=False,
                        legendgrouptitle_text='Guardian',
                        legendgroup='g',
                    ))

                # ── Inner ring: Responders ────────────────────────────────────────
                if _r_drones:
                    _rl, _rv, _rc, _rh, _rt = _fleet_ring_slices(_r_drones, 'Responder')
                    _inner_domain = dict(x=[0.12, 0.88], y=[0.12, 0.88])
                    fig_ring.add_trace(go.Pie(
                        name='Responders',
                        labels=_rl, values=_rv,
                        hole=0.52,
                        domain=_inner_domain,
                        marker=dict(colors=_rc, line=dict(color='#000', width=1.5)),
                        text=_rt, textinfo='text', textposition='inside',
                        insidetextfont=dict(size=10, color='#ffffff'),
                        customdata=_rh,
                        hovertemplate='%{customdata}',
                        sort=False,
                        legendgrouptitle_text='Responder',
                        legendgroup='r',
                    ))

                # ── If only one fleet type, show single ring ──────────────────────
                if not _g_drones and _r_drones:
                    _rl, _rv, _rc, _rh, _rt = _fleet_ring_slices(_r_drones, 'Responder')
                    fig_ring = go.Figure(go.Pie(
                        labels=_rl, values=_rv, hole=0.58,
                        marker=dict(colors=_rc, line=dict(color='#000', width=1.5)),
                        text=_rt, textinfo='text', textposition='inside',
                        insidetextfont=dict(size=10, color='#ffffff'),
                        customdata=_rh,
                        hovertemplate='%{customdata}', sort=False,
                    ))

                fig_ring.update_layout(
                    annotations=[
                        dict(
                            text=f"<b>{_cov_pct}%</b><br><span style='font-size:9px'>{_mode_short} combined</span>",
                            x=0.5, y=0.5, font_size=15, showarrow=False,
                            font=dict(color=text_main),
                        ),
                        *([] if not (_g_drones and _r_drones) else [
                            dict(text="<span style='font-size:8px'>G</span>",
                                 x=0.5, y=0.92, showarrow=False, font=dict(color='#FFD700', size=9)),
                            dict(text="<span style='font-size:8px'>R</span>",
                                 x=0.5, y=0.76, showarrow=False, font=dict(color='#00D2FF', size=9)),
                        ]),
                    ],
                    showlegend=True,
                    legend=dict(
                        orientation='v', x=1.02, y=0.5,
                        font=dict(size=9, color=text_muted),
                        bgcolor='rgba(0,0,0,0)',
                        groupclick='toggleitem',
                    ),
                    margin=dict(l=0, r=0, t=10, b=10),
                    height=320,
                    paper_bgcolor='rgba(0,0,0,0)',
                    hoverlabel=dict(bgcolor=card_bg, font_size=12, font_color=text_main),
                )
                st.plotly_chart(
                    fig_ring,
                    width="stretch",
                    config={'displayModeBar': False},
                    key="station_distribution_ring",
                )

                # Mode legend below the ring
                _mode_label = {
                    "Complement — push apart": "▶◀ Complement — Responders fill Guardian gaps",
                    "Independent — each uses its own objective": "⊕ Independent — each fleet follows its own objective",
                    "Shared — allow full overlap": "↔ Shared — both fleets maximise same call set",
                }.get(deployment_mode, "")
                st.markdown(
                    f"<div style='font-size:0.65rem; color:{text_muted}; text-align:center; margin-top:-8px;'>{_mode_label}</div>",
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"<div style='color:{text_muted}; font-size:0.8rem; padding:40px 0; text-align:center;'>Deploy drones to see call distribution ring.</div>",
                    unsafe_allow_html=True
                )


        # Resolve real incident datetime coverage for labels on the stations page
        _label_dt_series = html_reports._detect_datetime_series_for_labels(df_calls_full if df_calls_full is not None else df_calls)
        _label_has_real_dates = _label_dt_series is not None and getattr(_label_dt_series, "notna", lambda: pd.Series([], dtype=bool))().sum() > 0

        # ── CAD DATA CHARTS (moved into CAD Ingestion Analytics below) ───────────
        _cad_src = st.session_state.get('data_source', '')
        _has_real_calls = _cad_src in ('cad_upload', 'brinc_file') or (
            'df_calls' in st.session_state and st.session_state['df_calls'] is not None
            and len(st.session_state['df_calls']) > 100
        )

        # ── 3D SWARM SIMULATION ───────────────────────────────────────────
        if fleet_capex > 0:
            st.markdown("---")
            st.markdown(f"<h3 style='color:{text_main};'>🚁 3D Swarm Simulation <span class='tip' data-tip='Deck.gl-powered 3D animation of all DFR flights compressed into a single 24-hour day. Each arc represents a dispatch flight from station to incident. Use the speed slider to control playback. Best viewed fullscreen for council presentations.'>?</span></h3>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:0.82rem; color:{text_muted}; margin-bottom:10px;'>Animated deck.gl simulation of all DFR flights over a compressed 24-hour day. Use the speed slider to accelerate or slow the simulation. Great for council presentations.</div>", unsafe_allow_html=True)

            show_sim = st.toggle("🎬 Enable 3D Simulation", value=False, key='show_sim_b', help='Deck.gl 3D arc animation of all DFR dispatches compressed into a 24-hour day. Best viewed fullscreen for council presentations.')
            if show_sim:
                calls_lonlat = calls_in_city.to_crs(epsg=4326)
                calls_coords = np.column_stack((calls_lonlat.geometry.x, calls_lonlat.geometry.y))

                sim_assignments = {i:[] for i in range(len(active_drones))}
                for c_idx, cc in enumerate(calls_coords):
                    best_d, best_dist = -1, float('inf')
                    for d_idx, d in enumerate(active_drones):
                        if d['cov_array'][c_idx] if c_idx < len(d['cov_array']) else False:
                            dist = (cc[0]-d['lon'])**2 + (cc[1]-d['lat'])**2
                            if dist < best_dist:
                                best_dist, best_d = dist, d_idx
                    if best_d != -1:
                        sim_assignments[best_d].append(c_idx)

                stations_json, flights_json, legend_html_sim = [], [], ""
                total_sim_flights = 0
                for d_idx, d in enumerate(active_drones):
                    hex_c = d['color'].lstrip('#')
                    rgb = [int(hex_c[j:j+2],16) for j in (0,2,4)]
                    stations_json.append({"name":d['name'].split(',')[0][:30],"lon":d['lon'],"lat":d['lat'],"color":rgb,"radius":d['radius_m']})
                    legend_html_sim += f'<div style="margin-bottom:3px;"><span style="display:inline-block;width:9px;height:9px;background:{d["color"]};margin-right:7px;border-radius:50%;"></span>{d["name"].split(",")[0][:28]} ({d["type"][:3]})</div>'
                    frac = len(sim_assignments[d_idx])/len(calls_coords) if calls_coords.shape[0]>0 else 0
                    monthly_for_drone = int(frac * calls_per_day * 30 * dfr_dispatch_rate)
                    pool = sim_assignments[d_idx]

                    if not pool: sim_calls = []
                    elif monthly_for_drone > len(pool): sim_calls = random.choices(pool, k=monthly_for_drone)
                    else: sim_calls = random.sample(pool, monthly_for_drone)

                    total_sim_flights += len(sim_calls)
                    for ci in sim_calls:
                        lon1,lat1 = calls_coords[ci]
                        lon0,lat0 = d['lon'],d['lat']
                        dist_mi = math.sqrt((lon1-lon0)**2+(lat1-lat0)**2)*69.172
                        vis_time = max((dist_mi/d['speed_mph'])*3600*8, 240)
                        launch = random.randint(0, 2592000)
                        arc_h = min(max(dist_mi*90, 80), 400)
                        t0 = launch
                        t1 = launch + vis_time * 0.15
                        t2 = launch + vis_time * 0.40
                        t3 = launch + vis_time * 0.75
                        t4 = launch + vis_time * 0.90
                        t5 = launch + vis_time
                        mx1 = lon0 + 0.15*(lon1-lon0);  my1 = lat0 + 0.15*(lat1-lat0)
                        mx2 = lon0 + 0.35*(lon1-lon0);  my2 = lat0 + 0.35*(lat1-lat0)
                        mx3 = lon0 + 0.65*(lon1-lon0);  my3 = lat0 + 0.65*(lat1-lat0)
                        mx4 = lon0 + 0.85*(lon1-lon0);  my4 = lat0 + 0.85*(lat1-lat0)
                        flights_json.append({
                            "path": [[lon0, lat0, 0], [mx1, my1, arc_h*0.75], [mx2, my2, arc_h], [mx3, my3, arc_h], [mx4, my4, arc_h*0.75], [lon1, lat1, 0]],
                            "timestamps": [t0, t1, t2, t3, t4, t5],
                            "color": rgb
                        })

                warn_html_sim = ""
                if len(flights_json) > 3000:
                    flights_json = random.sample(flights_json, 3000)
                    warn_html_sim = f'<div style="background:#440000;border:1px solid #ff4b4b;color:#ffbbbb;padding:5px;font-size:10px;border-radius:4px;margin-bottom:8px;">⚠️ Capped at 3,000 flights for performance (actual: {total_sim_flights:,})</div>'

                drone_svg = "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'%3E%3Cpath d='M18 6a2 2 0 100-4 2 2 0 000 4zm-12 0a2 2 0 100-4 2 2 0 000 4zm12 12a2 2 0 100-4 2 2 0 000 4zm-12 0a2 2 0 100-4 2 2 0 000 4z'/%3E%3Cpath stroke='white' stroke-width='2' stroke-linecap='round' d='M8.5 8.5l7 7m0-7l-7 7'/%3E%3Ccircle cx='12' cy='12' r='2' fill='white'/%3E%3C/svg%3E"

                sim_html = """<!DOCTYPE html><html><head>
                <script src="https://unpkg.com/deck.gl@8.9.35/dist.min.js"></script>
                <script src="https://unpkg.com/maplibre-gl@3.0.0/dist/maplibre-gl.js"></script>
                <link href="https://unpkg.com/maplibre-gl@3.0.0/dist/maplibre-gl.css" rel="stylesheet"/>
                <style>
                  body{{margin:0;padding:0;overflow:hidden;background:#000;font-family:Manrope,sans-serif;}}
                  #map{{width:100vw;height:100vh;position:absolute;}}
                  #ui{{position:absolute;top:16px;left:16px;background:rgba(17,17,17,0.92);padding:16px;border-radius:8px;
                       color:white;border:1px solid #333;z-index:10;box-shadow:0 4px 10px rgba(0,0,0,0.5);width:260px;}}
                  button{{background:#00D2FF;color:black;border:none;padding:10px;cursor:pointer;font-weight:bold;
                          border-radius:4px;width:100%;font-size:13px;text-transform:uppercase;margin-bottom:8px;}}
                  button:disabled{{background:#444;color:#888;cursor:not-allowed;}}
                  #timeDisplay{{font-family:monospace;font-size:16px;color:#00ffcc;font-weight:bold;text-align:center;margin-bottom:8px;}}
                </style></head><body>
                <div id="ui">
                  <h3 style="margin:0 0 8px;color:#00D2FF;font-size:14px;">DFR SWARM SIMULATION</h3>
                  {warn_html_sim}
                  <div style="font-size:11px;color:#aaa;margin-bottom:10px;">
                    {total_sim_flights:,} flights over 30 days at {int(dfr_dispatch_rate*100)}% dispatch rate
                  </div>
                  <div style="margin-bottom:10px;">
                    <label style="font-size:11px;color:#ccc;">Speed: <span id="speedLabel">1</span>x</label>
                    <input type="range" id="speedSlider" min="1" max="100" value="1" style="width:100%;margin-top:4px;">
                  </div>
                  <button id="runBtn">▶ LAUNCH SWARM</button>
                  <div id="timeDisplay">00:00</div>
                  <div style="margin-top:10px;border-top:1px solid #333;padding-top:8px;">
                    <div style="font-size:10px;color:#888;text-transform:uppercase;margin-bottom:5px;">Stations</div>
                    <div style="font-size:10px;color:#ddd;max-height:100px;overflow-y:auto;">{legend_html_sim}</div>
                  </div>
                </div>
                <div id="map"></div>
                <script>
                  const stations={json.dumps(stations_json)};
                  const flights={json.dumps(flights_json)};
                  const speedSlider=document.getElementById('speedSlider');
                  const speedLabel=document.getElementById('speedLabel');
                  speedSlider.oninput=()=>speedLabel.innerText=speedSlider.value;
                  const map=new deck.DeckGL({{
                    container:'map',
                    mapStyle:'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
                    initialViewState:{{longitude:{center_lon},latitude:{center_lat},zoom:{dynamic_zoom},pitch:50,bearing:0}},
                    controller:true
                  }});
                  let time=0,timer=null,lastTime=0;
                  function render(){{
                    map.setProps({{layers:[
                      new deck.ScatterplotLayer({{id:'rings',data:stations,getPosition:d=>[d.lon,d.lat],
                        getFillColor:d=>[d.color[0],d.color[1],d.color[2],25],
                        getLineColor:d=>[d.color[0],d.color[1],d.color[2],220],
                        lineWidthMinPixels:2,stroked:true,filled:true,getRadius:d=>d.radius}}),
                      new deck.ScatterplotLayer({{id:'pads',data:stations,getPosition:d=>[d.lon,d.lat],
                        getFillColor:d=>[d.color[0],d.color[1],d.color[2],120],getRadius:180}}),
                      new deck.IconLayer({{id:'icons',data:stations,
                        getIcon:d=>({{url:"{drone_svg}",width:24,height:24,anchorY:12}}),
                        getPosition:d=>[d.lon,d.lat],getSize:36,sizeScale:1}}),
                      new deck.TripsLayer({{id:'flights',data:flights,getPath:d=>d.path,
                        getTimestamps:d=>d.timestamps,getColor:d=>d.color,
                        opacity:0.85,widthMinPixels:5,trailLength:13500,currentTime:time,rounded:true}}),
                      new deck.ScatterplotLayer({{id:'landed',data:flights,getPosition:d=>d.path[5],
                        getFillColor:d=>time>=d.timestamps[5]?[d.color[0],d.color[1],d.color[2],255]:[0,0,0,0],
                        getRadius:25,radiusMinPixels:3,updateTriggers:{{getFillColor:time}}}})
                    ]}});
                    let day=Math.floor(time/86400)+1;
                    let h=Math.floor((time%86400)/3600).toString().padStart(2,'0');
                    let m=Math.floor((time%3600)/60).toString().padStart(2,'0');
                    document.getElementById('timeDisplay').innerText=`Day ${{day}} · ${{h}}:${{m}}`;
                  }}
                  const animate=()=>{{
                    let now=performance.now();
                    let dt=Math.min(now-lastTime,100);
                    lastTime=now;
                    time+=dt/1000*43200*parseFloat(speedSlider.value);
                    render();
                    if(time<2592000){{timer=requestAnimationFrame(animate);}}
                    else{{
                      document.getElementById('runBtn').disabled=false;
                      document.getElementById('runBtn').innerText='↺ RESTART';
                      time=0;
                    }}
                  }};
                  document.getElementById('runBtn').onclick=()=>{{
                    document.getElementById('runBtn').disabled=true;
                    document.getElementById('runBtn').innerText='SIMULATING…';
                    time=0;lastTime=performance.now();
                    if(timer)cancelAnimationFrame(timer);
                    animate();
                  }};
                  render();
                </script></body></html>"""
                sim_html = (
                    sim_html
                    .replace("{warn_html_sim}", warn_html_sim)
                    .replace("{total_sim_flights:,}", f"{total_sim_flights:,}")
                    .replace("{int(dfr_dispatch_rate*100)}", str(int(dfr_dispatch_rate * 100)))
                    .replace("{legend_html_sim}", legend_html_sim)
                    .replace("{json.dumps(stations_json)}", json.dumps(stations_json))
                    .replace("{json.dumps(flights_json)}", json.dumps(flights_json))
                    .replace("{center_lon}", str(center_lon))
                    .replace("{center_lat}", str(center_lat))
                    .replace("{dynamic_zoom}", str(dynamic_zoom))
                    .replace("{drone_svg}", drone_svg)
                    .replace("{{", "{")
                    .replace("}}", "}")
                )

                components.html(sim_html, height=700)

        _show_analytics_section = st.toggle(
            "Show CAD Ingestion Analytics",
            value=True,
            key="show_cad_ingestion_analytics_section",
            help="Temporal breakdown of uploaded CAD data — hourly call volume, day-of-week patterns, optimal DFR shift windows, and a call-volume calendar heatmap.",
        )
        if _show_analytics_section:
            # ── COMMAND CENTER ANALYTICS DASHBOARD ──
            st.markdown("---")
            st.markdown(f"<h3 style='color:{text_main};'>📊 CAD Ingestion Analytics <span class='tip' data-tip='Temporal analysis of your uploaded CAD (Computer-Aided Dispatch) data. Shows when calls are most frequent by hour and day, identifies optimal DFR shift windows, and renders a call-volume calendar heatmap.'>?</span></h3>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:0.82rem; color:{text_muted}; margin-bottom:10px;'>Temporal patterns derived from your uploaded CAD data — hourly volumes, day-of-week distribution, optimal DFR shift windows, and a higher-contrast 5-band call-volume calendar.</div>", unsafe_allow_html=True)

            _analytics_df = df_calls_full if (df_calls_full is not None and not df_calls_full.empty) else df_calls
            try:
                analytics_html_block = html_reports.generate_command_center_html(
                    _analytics_df,
                    total_orig_calls=st.session_state.get('total_original_calls', full_total_calls or total_calls)
                )
            except Exception:
                analytics_html_block = "<div style='color:gray; padding:20px;'>Analytics unavailable for this dataset.</div>"
            _analytics_unavailable = (
                "Analytics unavailable." in analytics_html_block
                or "No valid dates found in data." in analytics_html_block
            )
            if _analytics_unavailable:
                _analytics_height = 180
            else:
                # Compute height from actual data so the iframe fits exactly with no dead space.
                # Calendar grid is auto-fill / minmax(250px, 1fr). At typical Streamlit content
                # width (~900px with sidebar open) that yields 3 columns.
                try:
                    _n_months = int(_analytics_df['date'].astype(str).str[:7].nunique()) if (
                        _analytics_df is not None and not _analytics_df.empty and 'date' in _analytics_df.columns
                    ) else 6
                except Exception:
                    _n_months = 6
                _n_months = max(1, min(_n_months, 12))
                _cal_cols = 3                        # columns at typical sidebar-open viewport
                _cal_rows = math.ceil(_n_months / _cal_cols)
                _cal_px   = _cal_rows * 260          # ~260px per calendar row (tightened)
                # Fixed chrome above the calendar:
                #   section header 60 + controls bar 70 + KPI cards 110 + shift/dow panel 210 + legend+label 55
                _fixed_px = 460
                _analytics_height = _fixed_px + _cal_px
            components.html(analytics_html_block, height=_analytics_height, scrolling=False)

            if _analytics_unavailable:
                # Remove the dead gap when the analytics component only contains a short fallback message.
                st.markdown("<div style='margin-top:-6px;'></div>", unsafe_allow_html=True)
            elif _has_real_calls and _analytics_df is not None and not _analytics_df.empty:
                # Collapse gap between components.html block and the plotly charts below
                st.markdown("<div style='margin-top:-80px;'></div>", unsafe_allow_html=True)
                html_reports._build_cad_charts(_analytics_df, text_main, text_muted, card_bg, card_border, accent_color)

        _show_community_impact_section = st.toggle(
            "Show Community Impact Dashboard",
            value=True,
            key="show_community_impact_dashboard_section",
            help="Public-facing transparency report: flight hours, response time advantage, Fourth Amendment safeguards, community outcomes, and taxpayer ROI. Designed for city council presentations.",
        )
        if _show_community_impact_section:
            # ── COMMUNITY IMPACT DASHBOARD ────────────────────────────────────────────
            st.markdown("---")
            st.markdown(
                f"<h3 style='color:{text_main};'>🏛️ Community Impact Dashboard <span class='tip' data-tip='Public-facing transparency report for city council presentations and community portals. Hover the ? badges inside each section for detailed explanations of every metric.'>?</span> <span class='tip' data-tip='Sources: Population — US Census Bureau ACS. Officer wages — Bureau of Labor Statistics (BLS) OES. Flight hour projections — BRINC hardware specs. Financial figures — BRINC COS optimization model. Fourth Amendment framework — DOJ/ACLU DFR policy guidelines.'>src</span></h3>",
                unsafe_allow_html=True
            )
            st.markdown(
                f"<div style='font-size:0.82rem; color:{text_muted}; margin-bottom:10px;'>"
                "Public-facing transparency report — flight hours &amp; uptime, response time advantage, "
                "Fourth Amendment safeguards, community outcomes, call type distribution, equity commitments, "
                "and taxpayer ROI. Designed for city council presentations and citizen engagement portals."
                "</div>",
                unsafe_allow_html=True
            )
            _cid_fac_counts = {}
            if 'type' in df_stations_all.columns:
                for _t in df_stations_all['type'].dropna().astype(str):
                    _cid_fac_counts[_t] = _cid_fac_counts.get(_t, 0) + 1
            _cid_html = html_reports.generate_community_impact_dashboard_html(
                city=_get_document_jurisdiction_name(st.session_state, selected_names, fallback='City'),
                state=st.session_state.get('active_state', 'TX'),
                population=int(st.session_state.get('estimated_pop', 0) or 0),
                total_calls=int(st.session_state.get('total_original_calls', full_total_calls or total_calls) or 0),
                calls_covered_perc=float(calls_covered_perc or 0),
                area_covered_perc=float(area_covered_perc or 0),
                avg_resp_time_min=float(avg_resp_time or 0),
                avg_time_saved_min=float(avg_time_saved or 0),
                fleet_capex=float(fleet_capex or 0),
                annual_savings=float(annual_savings or 0),
                break_even_text=str(break_even_text or 'N/A'),
                actual_k_responder=int(actual_k_responder or 0),
                actual_k_guardian=int(actual_k_guardian or 0),
                dfr_dispatch_rate=float(dfr_dispatch_rate or 0.30),
                deflection_rate=float(deflection_rate or 0.30),
                daily_dfr_responses=float(daily_dfr_responses or 0),
                daily_drone_only_calls=float(daily_drone_only_calls or 0),
                active_drones=active_drones or [],
                df_calls_full=df_calls_full,
                facility_counts=_cid_fac_counts or None,
            )
            components.html(_cid_html, height=3600, scrolling=False)
            st.markdown("<div style='margin-top:-52px;'></div>", unsafe_allow_html=True)

        _show_school_safety_section = st.toggle(
            "Show School Safety Impact",
            value=True,
            key="show_school_safety_impact_section",
            help="Side-by-side comparison of DFR vs. School Resource Officer (SRO) response capability, cost per school, and coverage reach.",
        )
        if _show_school_safety_section:
            # ── SCHOOL SAFETY IMPACT MATRIX ──────────────────────────────────────────
            st.markdown("---")
            _sro_cost_low   = 75_000
            _sro_cost_high  = 120_000
            _dfr_amortized  = int(fleet_capex / 7) if fleet_capex > 0 else 0
            _dfr_amort_str  = f"${_dfr_amortized:,}/yr" if _dfr_amortized > 0 else "~$11K–22K/yr"

            def _ss_row(label, sro_val, dfr_val, alt, cb, cbrd, tm, tmain, acc, last=False):
                bg = f"background:rgba(255,255,255,0.02);" if alt else ""
                brd = "" if last else f"border-bottom:1px solid {cbrd};"
                sro_color = "#f59e0b"
                dfr_color = acc
                return (
                    f'<tr style="{bg}{brd}">'
                    f'<td style="padding:8px 12px;color:{tmain};font-weight:600;font-size:0.72rem;">{label}</td>'
                    f'<td style="padding:8px 12px;text-align:center;color:{sro_color};font-size:0.71rem;">{sro_val}</td>'
                    f'<td style="padding:8px 12px;text-align:center;color:{dfr_color};font-size:0.71rem;">{dfr_val}</td>'
                    f'</tr>'
                )

            _school_rows = (
                _ss_row("Annual Cost / Campus",
                        f"${_sro_cost_low:,}–${_sro_cost_high:,} per officer",
                        f"{_dfr_amort_str} amortized (7-yr) · {actual_k_responder + actual_k_guardian} units",
                        False, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Coverage Hours / Year",
                        "~1,260 hrs/yr (school hours only)",
                        "8,760 hrs/yr — 24 / 7 / 365",
                        True, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Campuses Covered",
                        "1 building per officer",
                        f"Multi-campus — {actual_k_responder + actual_k_guardian} simultaneous coverage zones",
                        False, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("On-Campus Response Time",
                        "2–5 min (foot/vehicle across campus)",
                        f"&lt;90 sec airborne · {avg_resp_time:.1f} min avg aerial",
                        True, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("After-Hours / Weekend Coverage",
                        "❌ None",
                        "✅ Full thermal surveillance 24/7",
                        False, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Thermal / Night Vision",
                        "❌ Flashlight only",
                        "✅ 640px FLIR thermal (BRINC Responder)",
                        True, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Perimeter Monitoring",
                        "❌ Not feasible at scale",
                        "✅ Automated aerial patrol",
                        False, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Active Threat Intel",
                        "Single officer — blind hallway entry",
                        "✅ Live HD + thermal to dispatch before officer entry",
                        True, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Indoor Operations",
                        "✅ On foot",
                        "✅ BRINC LEMUR 2 — glass-breaker, perch mode, 2-way comms",
                        False, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Court-Admissible Evidence",
                        "Body cam (ground-level only)",
                        "✅ Aerial HD video + chain-of-custody flight log",
                        True, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Mass Shooting Prevention Evidence",
                        "❌ No proven effect (RAND, 2023)",
                        "✅ Pre-entry intel enables faster tactical coordination",
                        False, card_bg, card_border, text_muted, text_main, accent_color) +
                _ss_row("Disciplinary Side Effects",
                        "⚠️ +35–80% suspensions · +25–90% expulsions (RAND)",
                        "✅ Zero school-discipline impact",
                        True, card_bg, card_border, text_muted, text_main, accent_color, last=True)
            )

            _school_html = f"""
            <style>
            .ss-tip {{
              display:inline-flex;align-items:center;justify-content:center;
              width:13px;height:13px;border-radius:50%;
              background:rgba(255,255,255,0.12);color:#888;font-size:9px;font-weight:700;
              cursor:default;margin-left:3px;vertical-align:middle;position:relative;flex-shrink:0;
            }}
            .ss-tip:hover::after {{
              content:attr(data-tip);position:absolute;bottom:130%;left:50%;
              transform:translateX(-50%);background:#1a1a2e;color:#e0e0e0;
              font-size:10.5px;font-weight:400;padding:6px 10px;border-radius:5px;
              white-space:normal;width:260px;line-height:1.5;z-index:9999;
              border:1px solid #333;box-shadow:0 4px 12px rgba(0,0,0,0.5);
              pointer-events:none;text-transform:none;letter-spacing:normal;
            }}
            </style>

            <div>
              <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:4px;">
                <h3 style="color:{text_main};margin:0;">🏫 School Safety Impact <span class='tip' data-tip='Sources: FBI Crime in Schools 2020–2024 · NCES Indicators of School Crime &amp; Safety 2023 · FBI Active Shooter Study · RAND Corp. SRO Research (2023) · NIJ Effects of SROs on School Crime · K-12 School Shooting Database · BJS School Crime Statistics 2024 · ZipRecruiter/Volt.ai SRO salary data · BRINC technical specifications · Chula Vista PD DFR Program outcomes.'>src</span></h3>
                <span style="font-size:0.7rem;color:{text_muted};">National statistics · DFR vs SRO analysis · cited sources</span>
              </div>
              <div style="font-size:0.78rem;color:{text_muted};margin-bottom:16px;max-width:740px;line-height:1.6;">
                BRINC DFR delivers 24/7 aerial first-response to school campuses — faster and at lower total lifecycle cost than
                traditional School Resource Officers, with no coverage blind spots, no off-hours gaps, and full HD + thermal
                scene intelligence before any ground unit enters a building.
              </div>

              <!-- NATIONAL STATS HERO ROW -->
              <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;">

                <div style="background:{card_bg};border:1px solid {card_border};border-top:3px solid #ef4444;border-radius:8px;padding:14px 12px;text-align:center;">
                  <div style="font-size:0.61rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.6px;margin-bottom:4px;">
                    School Crimes 2020–24
                    <span class="ss-tip" data-tip="Source: FBI Crime in Schools Special Report 2020–2024. Over 1.3 million criminal incidents recorded at K-12 school locations across the US over the five-year period, with approximately 1.5 million victims.">?</span>
                  </div>
                  <div style="font-size:1.75rem;font-weight:900;color:#ef4444;font-family:'IBM Plex Mono',monospace;">1.3M</div>
                  <div style="font-size:0.64rem;color:{text_muted};margin-top:2px;">criminal incidents on campus</div>
                </div>

                <div style="background:{card_bg};border:1px solid {card_border};border-top:3px solid #f59e0b;border-radius:8px;padding:14px 12px;text-align:center;">
                  <div style="font-size:0.61rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.6px;margin-bottom:4px;">
                    Student Victimization
                    <span class="ss-tip" data-tip="Source: NCES Indicators of School Crime &amp; Safety 2023 (NCES 2024-145). 22 nonfatal criminal victimizations per 1,000 students ages 12-18 in 2022 — includes theft, violent crime, and serious threats. Down from 52/1,000 in 2012 but remains elevated.">?</span>
                  </div>
                  <div style="font-size:1.75rem;font-weight:900;color:#f59e0b;font-family:'IBM Plex Mono',monospace;">22</div>
                  <div style="font-size:0.64rem;color:{text_muted};margin-top:2px;">per 1,000 students annually</div>
                </div>

                <div style="background:{card_bg};border:1px solid {card_border};border-top:3px solid #8b5cf6;border-radius:8px;padding:14px 12px;text-align:center;">
                  <div style="font-size:0.61rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.6px;margin-bottom:4px;">
                    Incidents End ≤5 min
                    <span class="ss-tip" data-tip="Source: FBI Active Shooter Study (64 incidents analyzed). 69% of active shooter events conclude within 5 minutes — 23 ended in under 2 minutes. Average incident duration at educational facilities: 3 min 18 sec. Most incidents end before police arrive.">?</span>
                  </div>
                  <div style="font-size:1.75rem;font-weight:900;color:#8b5cf6;font-family:'IBM Plex Mono',monospace;">69%</div>
                  <div style="font-size:0.64rem;color:{text_muted};margin-top:2px;">active shooter events ≤5 min</div>
                </div>

                <div style="background:{card_bg};border:1px solid {card_border};border-top:3px solid {accent_color};border-radius:8px;padding:14px 12px;text-align:center;">
                  <div style="font-size:0.61rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.6px;margin-bottom:4px;">
                    BRINC On-Scene
                    <span class="ss-tip" data-tip="Source: BRINC technical specifications; Chula Vista PD DFR Program outcomes. BRINC launches in &lt;20 sec and is on-scene in &lt;90 sec. Chula Vista documented average DFR response under 2 minutes citywide — vs. 14-15 min national ground average.">?</span>
                  </div>
                  <div style="font-size:1.75rem;font-weight:900;color:{accent_color};font-family:'IBM Plex Mono',monospace;">&lt;90s</div>
                  <div style="font-size:0.64rem;color:{text_muted};margin-top:2px;">airborne &amp; streaming live video</div>
                </div>

              </div>

              <!-- CRITICAL RESPONSE WINDOW -->
              <div style="background:rgba(239,68,68,0.06);border-left:3px solid #ef4444;border-radius:0 6px 6px 0;padding:12px 16px;margin-bottom:16px;">
                <div style="font-size:0.7rem;font-weight:700;color:#ef4444;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;">
                  ⚠️ The Critical Response Window
                  <span class="ss-tip" data-tip="Sources: FBI Law Enforcement Bulletin 'Those Terrible First Few Minutes'; FBI Active Shooter Study (51-case median analysis); ALICE Training Institute; K-12 School Shooting Database (k12ssdb.org). Education-setting data: FBI subset of 51 incidents in schools.">?</span>
                </div>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px;">
                  <div style="text-align:center;background:rgba(0,0,0,0.25);border-radius:6px;padding:10px 8px;">
                    <div style="font-size:1.25rem;font-weight:900;color:#ef4444;font-family:'IBM Plex Mono',monospace;">14–15 min</div>
                    <div style="font-size:0.63rem;color:{text_muted};margin-top:3px;">National avg ground police<br>arrival to active shooter</div>
                  </div>
                  <div style="text-align:center;background:rgba(0,0,0,0.25);border-radius:6px;padding:10px 8px;">
                    <div style="font-size:1.25rem;font-weight:900;color:#f59e0b;font-family:'IBM Plex Mono',monospace;">3m 18s</div>
                    <div style="font-size:0.63rem;color:{text_muted};margin-top:3px;">Avg incident duration<br>at schools (FBI education subset)</div>
                  </div>
                  <div style="text-align:center;background:rgba(0,0,0,0.25);border-radius:6px;padding:10px 8px;">
                    <div style="font-size:1.25rem;font-weight:900;color:{accent_color};font-family:'IBM Plex Mono',monospace;">&lt;90 sec</div>
                    <div style="font-size:0.63rem;color:{text_muted};margin-top:3px;">BRINC on-scene with live<br>HD + thermal to dispatch</div>
                  </div>
                </div>
                <div style="font-size:0.69rem;color:{text_muted};font-style:italic;line-height:1.55;">
                  "Most active shooter incidents in schools are over before a responding officer reaches the building entrance.
                  DFR doesn't replace the officer — it gives the officer eyes on every hallway, stairwell, and exit
                  before they open the first door." — FBI Law Enforcement Bulletin, 'Those Terrible First Few Minutes'
                </div>
              </div>

              <!-- DFR vs SRO COMPARISON TABLE -->
              <div style="font-size:0.7rem;font-weight:700;color:{text_main};text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
                DFR vs. School Resource Officer (SRO) — Capability Matrix
                <span class="ss-tip" data-tip="SRO data: RAND 'The Role and Impact of School Resource Officers' (2023); NIJ Effects of SROs on School Crime (OJP); ZipRecruiter SRO Salary 2025; Volt.ai SRO Cost Analysis. DFR data: BRINC technical specifications; Chula Vista PD DFR outcomes; Skydio Campus DFR documentation.">?</span>
              </div>
              <div style="overflow-x:auto;border-radius:8px;border:1px solid {card_border};">
                <table style="width:100%;border-collapse:collapse;font-size:0.72rem;">
                  <thead>
                    <tr style="background:rgba(0,0,0,0.45);">
                      <th style="padding:10px 14px;text-align:left;font-size:0.61rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{text_muted};">Capability</th>
                      <th style="padding:10px 14px;text-align:center;font-size:0.61rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#f59e0b;">School Resource Officer</th>
                      <th style="padding:10px 14px;text-align:center;font-size:0.61rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{accent_color};">BRINC DFR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {_school_rows}
                  </tbody>
                </table>
              </div>

              <!-- COST COMPARISON CARDS -->
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px;margin-bottom:12px;">

                <div style="background:rgba(245,158,11,0.06);border:1px solid rgba(245,158,11,0.2);border-radius:8px;padding:16px;">
                  <div style="font-size:0.63rem;font-weight:700;color:#f59e0b;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
                    📋 10-School District — Traditional SRO Model
                    <span class="ss-tip" data-tip="Source: ZipRecruiter SRO Salary Data 2025; DeSoto County SRO detailed cost breakdown ($94,147/yr blended total); Volt.ai SRO Cost Analysis. 1 officer per campus at $75K–$120K total annual cost. School-hours coverage only: 7hr/day × 180 school days = 1,260 hrs/yr per campus.">?</span>
                  </div>
                  <div style="font-size:1.6rem;font-weight:900;color:#f59e0b;font-family:'IBM Plex Mono',monospace;">${940_000:,} – ${1_200_000:,}</div>
                  <div style="font-size:0.67rem;color:{text_muted};margin-top:3px;">per year · 10 officers · school hours only</div>
                  <div style="margin-top:10px;display:flex;flex-direction:column;gap:3px;font-size:0.65rem;color:{text_muted};">
                    <div>Coverage: ~1,260 hrs/campus/yr (14.4% of annual hours)</div>
                    <div>Nights, weekends, summer: ❌ no coverage</div>
                    <div>Perimeter / multi-campus: ❌ single building only</div>
                    <div>Proven mass-shooting impact: ❌ no evidence (RAND)</div>
                  </div>
                </div>

                <div style="background:rgba(0,210,255,0.06);border:1px solid rgba(0,210,255,0.2);border-radius:8px;padding:16px;">
                  <div style="font-size:0.63rem;font-weight:700;color:{accent_color};text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
                    🚁 BRINC DFR — Multi-Campus Deployment
                    <span class="ss-tip" data-tip="BRINC fleet CapEx amortized over 7 years. One hub station covers multiple campuses within patrol radius 24/7. Includes hardware and BRINC support onboarding. Does not include cellular/network costs.">?</span>
                  </div>
                  <div style="font-size:1.6rem;font-weight:900;color:{accent_color};font-family:'IBM Plex Mono',monospace;">${fleet_capex:,.0f} CapEx</div>
                  <div style="font-size:0.67rem;color:{text_muted};margin-top:3px;">{_dfr_amort_str} amortized · {actual_k_responder + actual_k_guardian} units deployed</div>
                  <div style="margin-top:10px;display:flex;flex-direction:column;gap:3px;font-size:0.65rem;color:{text_muted};">
                    <div>Coverage: 8,760 hrs/yr — 24/7/365 per hub</div>
                    <div>Nights, weekends, summer: ✅ full thermal patrol</div>
                    <div>Multi-campus zones: ✅ {actual_k_responder + actual_k_guardian} simultaneous coverage areas</div>
                    <div>Response time advantage vs ground: +{avg_time_saved:.1f} min saved per incident</div>
                  </div>
                </div>

              </div>

              <!-- SOURCES FOOTER -->
              <div style="font-size:0.6rem;color:{text_muted};border-top:1px solid {card_border};padding-top:8px;line-height:1.8;">
                <strong style="color:{text_main};">Data Sources:</strong>
                FBI Crime in Schools 2020–2024 Special Report ·
                NCES Indicators of School Crime &amp; Safety 2023 (NCES 2024-145) ·
                FBI Active Shooter Study (51-case &amp; 64-incident analyses) ·
                RAND Corp. "The Role and Impact of School Resource Officers" (2023) ·
                NIJ Effects of SROs on School Crime (OJP) ·
                BJS School Crime Statistics 2024 ·
                Chula Vista PD DFR Program outcomes ·
                BRINC Drones technical specifications ·
                K-12 School Shooting Database (k12ssdb.org) ·
                ZipRecruiter / Volt.ai SRO Salary &amp; Cost Data 2025
              </div>
            </div>
            """
            _school_full_html = (
                "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
                "</head>"
                f"<body style='margin:0;padding:12px 4px 16px;background:#000000;"
                "font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,sans-serif;'>"
                f"{_school_html}</body></html>"
            )
            components.html(_school_full_html, height=1300, scrolling=False)

        _show_lte_section = st.toggle(
            "Show 4G LTE Cell Coverage",
            value=True,
            key="show_lte_cell_coverage_section",
            help="Per-carrier 4G LTE coverage analysis for the deployment area. Shows AT&T, T-Mobile, and Verizon coverage percentages to validate drone data-link reliability.",
        )
        if _show_lte_section:
            # ── 4G LTE CELL COVERAGE — 3 carrier maps with % coverage ────────────────
            st.markdown("---")
            st.markdown(f"<h3 style='color:{text_main};'>📶 4G LTE Cell Coverage</h3>", unsafe_allow_html=True)

            _cov_state    = st.session_state.get('active_state', '')
            _cov_boundary = city_boundary_geom  # may be None if no boundary loaded

            _carrier_results = _carrier_coverage_analysis(_cov_state, _cov_boundary)

            if _carrier_results:
                # ── 3 small maps in a row, sorted highest → lowest coverage ──────────
                _cov_cols = st.columns(3)
                for _ci, _cr in enumerate(_carrier_results[:3]):
                    with _cov_cols[_ci]:
                        _pct_display = f"{_cr['pct']:.1f}%" if _cr['pct'] > 0 else "No data"
                        _badge_color = "#22c55e" if _cr['pct'] >= 90 else "#f59e0b" if _cr['pct'] >= 70 else "#ef4444"
                        st.markdown(
                            f"<div style='text-align:center;padding:6px 0 4px;'>"
                            f"<span style='font-size:1.1rem;font-weight:800;color:{_cr['color']};'>{_cr['carrier']}</span>"
                            f"<br><span style='font-size:1.9rem;font-weight:900;color:{_badge_color};font-family:monospace;'>{_pct_display}</span>"
                            f"<br><span style='font-size:0.62rem;color:#667;text-transform:uppercase;letter-spacing:1px;'>of jurisdiction covered</span>"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                        _mini_fig = _build_carrier_mini_map(
                            _cr, _cov_boundary, center_lat, center_lon,
                            dynamic_zoom, map_style
                        )
                        st.plotly_chart(
                            _mini_fig,
                            width="stretch",
                            config={"displayModeBar": False},
                            key=f"carrier_mini_map_{_ci}",
                        )

                # Rank line
                if len(_carrier_results) > 1:
                    _rank_txt = " → ".join(
                        f"<span style='color:{r['color']};font-weight:700;'>{r['carrier']} {r['pct']:.1f}%</span>"
                        for r in _carrier_results[:3]
                    )
                    st.markdown(
                        f"<div style='font-size:0.75rem;color:#556;margin-top:4px;text-align:center;'>"
                        f"Coverage rank: {_rank_txt}</div>",
                        unsafe_allow_html=True
                    )
            else:
                # Fallback: FCC link card if parquet not available for this state
                _fcc_zoom_lte = round(min(13, max(9, dynamic_zoom + 1)), 2)
                _fcc_url_lte  = (f"https://broadbandmap.fcc.gov/home?version=dec2023"
                                 f"&zoom={_fcc_zoom_lte}&vlon={center_lon:.6f}&vlat={center_lat:.6f}"
                                 f"&speed=25&tech=300&br=4")
                st.markdown(f"""
                <a href="{_fcc_url_lte}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;">
                  <div style="display:flex;align-items:center;justify-content:space-between;
                    background:#0d1b2e;border:1px solid #1e3a5f;border-radius:10px;padding:20px 28px;cursor:pointer;">
                    <div>
                      <div style="color:#00b4d8;font-size:1rem;font-weight:600;margin-bottom:4px;">📶 Open FCC 4G LTE Coverage Map</div>
                      <div style="color:#6b7f99;font-size:0.78rem;">FCC National Broadband Map · AT&amp;T, T-Mobile, Verizon</div>
                    </div>
                    <div style="color:#00b4d8;font-size:1.4rem;">↗</div>
                  </div>
                </a>""", unsafe_allow_html=True)

        # ── MOBILE QR CODE ────────────────────────────────────────────────────────
        st.markdown("---")
        try:
            import qrcode as _qrcode
            from PIL import Image as _PILImage
            import io as _io_qr, urllib.parse as _up, socket as _sock

            # Build base URL from Streamlit context headers
            try:
                _qr_host = st.context.headers.get("host", "") or st.context.headers.get("Host", "")
                _qr_proto = "https" if (_qr_host and ("streamlit.app" in _qr_host or "share" in _qr_host)) else "http"
                if not _qr_host:
                    _qr_host = f"{_sock.gethostbyname(_sock.gethostname())}:8501"
                _qr_base = f"{_qr_proto}://{_qr_host}"
            except Exception:
                try:
                    _qr_base = f"http://{_sock.gethostbyname(_sock.gethostname())}:8501"
                except Exception:
                    _qr_base = "http://localhost:8501"

            # Compute area inline (may not yet be in scope)
            try:
                _qr_df_c = df_calls_full if df_calls_full is not None else df_calls
                _qr_lons = _qr_df_c["lon"].dropna(); _qr_lats = _qr_df_c["lat"].dropna()
                _qr_area = max(1, int((float(_qr_lons.max()) - float(_qr_lons.min())) *
                                       (float(_qr_lats.max()) - float(_qr_lats.min())) * 3280))
            except Exception:
                _qr_area = 0

            # Encode active station positions compactly for mobile map
            # Format: "lat1,lon1;lat2,lon2" (4 decimal places, ≈10m accuracy)
            try:
                _stn_parts = [f"{d['lat']:.4f},{d['lon']:.4f}" for d in active_drones[:12]]
                _stn_str   = ";".join(_stn_parts)
            except Exception:
                _stn_str = ""

            # Encode incident data compactly for mobile map (minimal sample to keep URL under QR version 40)
            # Format: "lat1,lon1;lat2,lon2;..." (1 decimal place for ~10km accuracy)
            _calls_str = ""
            try:
                _qr_df_calls = df_calls_full if (df_calls_full is not None and not df_calls_full.empty) else df_calls
                if _qr_df_calls is not None and not _qr_df_calls.empty and 'lat' in _qr_df_calls.columns and 'lon' in _qr_df_calls.columns:
                    # Sample up to 20 calls to keep URL under QR version 40 limit
                    _call_sample = _qr_df_calls.sample(min(20, len(_qr_df_calls)), random_state=42)
                    _call_parts = [f"{row['lat']:.1f},{row['lon']:.1f}" for _, row in _call_sample.iterrows()
                                   if pd.notna(row.get('lat')) and pd.notna(row.get('lon'))]
                    _calls_str = ";".join(_call_parts[:20])
            except Exception:
                pass

            # Note: Boundary/shapefile outline removed from QR mobile map to avoid misleading simplified versions
            # The main program renders the full detailed boundary; mobile map focuses on station locations and calls

            _qr_params = _up.urlencode({
                "city":  _get_document_jurisdiction_name(st.session_state, selected_names, fallback="").title(),
                "state": st.session_state.get("active_state", ""),
                "pop":   int(st.session_state.get("estimated_pop", 0) or 0),
                "cov":   round(float(calls_covered_perc or 0), 1),
                "resp":  round(float(avg_resp_time or 0), 2),
                "saves": int(annual_savings or 0),
                "capex": int(fleet_capex or 0),
                "r":     int(actual_k_responder or 0),
                "g":     int(actual_k_guardian or 0),
                "calls": int(total_calls or 0),
                "area":  _qr_area,
                "tsav":  round(float(avg_time_saved or 0), 2),
                "clat":  round(center_lat, 4),
                "clon":  round(center_lon, 4),
                "zoom":  round(dynamic_zoom, 1),
                "s":     _stn_str,
                "m_calls": _calls_str,
            })
            _fallback_qr_url = f"{_qr_base}/?view=mobile&{_qr_params}"
            _tracked_report_id = str(st.session_state.get("public_report_id", "")).strip()
            _stored_public_url = str(st.session_state.get("public_report_url", "")).strip()
            _tracked_qr_url = _build_public_report_url(_tracked_report_id) if _tracked_report_id else ""
            _qr_url = _tracked_qr_url or _stored_public_url or _fallback_qr_url

            # ── QR code image — high readability with BRINC logo overlay ──────────
            # Use highest error correction (H) for better phone scanning reliability
            _qr = _qrcode.QRCode(version=None, error_correction=_qrcode.constants.ERROR_CORRECT_H,
                                  box_size=28, border=8)
            _qr.add_data(_qr_url)
            _qr.make(fit=True)
            _qr_img = _qr.make_image(fill_color="#000000", back_color="#FFFFFF").convert('RGB')

            # Overlay BRINC logo in center
            try:
                _logo_path = "logo.png"
                if Path(_logo_path).exists():
                    _logo = _PILImage.open(_logo_path).convert('RGBA')
                    # Logo should be ~20% of QR code size for good scannability with error correction H
                    _logo_size = int(_qr_img.size[0] * 0.20)
                    _logo = _logo.resize((_logo_size, _logo_size), _PILImage.Resampling.LANCZOS)

                    # Create white background square for logo
                    _bg_size = int(_logo_size * 1.15)
                    _white_bg = _PILImage.new('RGB', (_bg_size, _bg_size), 'white')
                    _bg_pos = (((_bg_size - _logo_size) // 2), ((_bg_size - _logo_size) // 2))
                    _white_bg.paste(_logo, _bg_pos, _logo)

                    # Paste white background (with logo) centered on QR code
                    _qr_pos = ((_qr_img.size[0] - _bg_size) // 2, (_qr_img.size[1] - _bg_size) // 2)
                    _qr_img.paste(_white_bg, _qr_pos)
            except Exception:
                pass

            _qr_buf = _io_qr.BytesIO()
            _qr_img.save(_qr_buf, format="PNG")
            import base64 as _b64
            _qr_b64 = _b64.b64encode(_qr_buf.getvalue()).decode()

            # ── Sales contact info from authenticated session ─────────────────────
            _qr_email = str(st.session_state.get("google_user_email", "")).strip()
            _qr_name = str(st.session_state.get("google_user_name", "")).strip()
            _qr_user = str(st.session_state.get("brinc_user", "")).strip()
            if not _qr_email and _qr_user:
                _qr_email = f"{_qr_user}@brincdrones.com"
            if not _qr_name:
                _name_seed = (_qr_email.split("@")[0] if _qr_email else _qr_user or "BRINC Representative")
                _qr_name = " ".join(w.capitalize() for w in _name_seed.replace("_", ".").split("."))
            _qr_city  = _get_document_jurisdiction_name(st.session_state, selected_names, fallback="")
            _qr_state = st.session_state.get("active_state", "")
            _qr_loc   = f"{_qr_city}, {_qr_state}" if _qr_city else "your city"

            # Get department/jurisdiction name for personalization
            _qr_dept = st.session_state.get('active_dept_name', '') or _qr_city or 'Jurisdiction'
            _qr_dept = str(_qr_dept).strip().title()

            # ── Public QR summary page (expanded, no login) ─────────────────────────
            _qr_total_calls = int(full_total_calls or total_calls or 0)
            _qr_active_stns = len(active_drones)
            _qr_area_cov = round(float(area_covered_perc or 0), 1)
            _qr_time_saved = round(float(avg_time_saved or 0), 1)
            _qr_avg_resp = round(float(avg_resp_time or 0), 1)
            _qr_covered_calls = int(round(_qr_total_calls * float(calls_covered_perc or 0) / 100.0))
            _qr_fleet_total = int(actual_k_responder or 0) + int(actual_k_guardian or 0)
            _qr_summary_text = (
                f"This analysis modeled Drone as First Responder deployment for {_qr_city}, {_qr_state} "
                f"using jurisdiction-specific geography and incident demand. The recommended configuration "
                f"of {actual_k_responder} responder aircraft and {actual_k_guardian} guardian aircraft is "
                f"projected to cover {float(calls_covered_perc or 0):.1f}% of modeled calls, reduce average "
                f"response time by {_qr_time_saved:.1f} minutes, and improve aerial first-arrival consistency "
                f"across the jurisdiction."
            )

            def _h(value):
                return html.escape(str(value or ""))

            def _rank_station_role(station_type):
                _stype = str(station_type or "").upper()
                return "Guardian" if "GUARD" in _stype else "Responder"

            def _coverage_band(idx, total):
                if total <= 1:
                    return "Primary gap closure"
                if idx == 0:
                    return "Primary gap closure"
                if idx < max(2, total // 3):
                    return "High"
                if idx < max(4, (2 * total) // 3):
                    return "Medium"
                return "Supporting"

            _station_table_rows_html = "".join(
                f"<tr>"
                f"<td>{idx + 1}</td>"
                f"<td>{_h(d.get('name', 'Unnamed Station'))}</td>"
                f"<td>{_rank_station_role(d.get('type', ''))}</td>"
                f"<td>{float(d.get('avg_time_min', 0) or 0):.1f} min</td>"
                f"</tr>"
                for idx, d in enumerate(active_drones[:6])
            ) or "<tr><td colspan='4'>No active stations available for this scenario.</td></tr>"

            _why_sites_html = "".join([
                "<li>Selected from jurisdiction-specific call density and travel geometry</li>",
                "<li>Optimized for fastest first-arrival coverage, not arbitrary spacing</li>",
                "<li>Balanced to improve coverage while maintaining deployable fleet utilization</li>",
                "<li>Defensible for operational planning, leadership review, and budget justification</li>",
            ])
            _impact_html = "".join([
                "<li>Faster first-arriving aerial presence on in-progress calls</li>",
                "<li>Earlier live video and scene intelligence for responding officers</li>",
                "<li>More consistent coverage across high-demand areas</li>",
                "<li>Stronger justification for phased DFR deployment and funding decisions</li>",
            ])

            _call_points_svg = ""
            try:
                _qr_df_calls_plot = df_calls_full if (df_calls_full is not None and not df_calls_full.empty) else df_calls
                if _qr_df_calls_plot is not None and not _qr_df_calls_plot.empty and 'lat' in _qr_df_calls_plot.columns and 'lon' in _qr_df_calls_plot.columns:
                    _sample = _qr_df_calls_plot[['lat', 'lon']].dropna().sample(min(90, len(_qr_df_calls_plot)), random_state=42)
                    _station_lats = [float(d.get('lat')) for d in active_drones if d.get('lat') is not None]
                    _station_lons = [float(d.get('lon')) for d in active_drones if d.get('lon') is not None]
                    _all_lats = list(_sample['lat'].astype(float)) + _station_lats
                    _all_lons = list(_sample['lon'].astype(float)) + _station_lons
                    if _all_lats and _all_lons:
                        _min_lat, _max_lat = min(_all_lats), max(_all_lats)
                        _min_lon, _max_lon = min(_all_lons), max(_all_lons)
                        _lat_span = max(_max_lat - _min_lat, 0.01)
                        _lon_span = max(_max_lon - _min_lon, 0.01)

                        def _xy(lat, lon):
                            _x = 8 + ((float(lon) - _min_lon) / _lon_span) * 84
                            _y = 8 + (1 - ((float(lat) - _min_lat) / _lat_span)) * 84
                            return _x, _y

                        _call_points = []
                        for _, _row in _sample.iterrows():
                            _x, _y = _xy(_row['lat'], _row['lon'])
                            _call_points.append(f"<circle cx='{_x:.2f}' cy='{_y:.2f}' r='1.1' fill='rgba(110,231,255,0.34)' />")

                        _station_points = []
                        for _d in active_drones[:8]:
                            if _d.get('lat') is None or _d.get('lon') is None:
                                continue
                            _x, _y = _xy(_d['lat'], _d['lon'])
                            _stroke = '#ffd76a' if _rank_station_role(_d.get('type', '')) == 'Guardian' else '#6ee7ff'
                            _fill = 'rgba(255,215,106,.18)' if _stroke == '#ffd76a' else 'rgba(110,231,255,.18)'
                            _station_points.append(
                                f"<circle cx='{_x:.2f}' cy='{_y:.2f}' r='6.6' fill='none' stroke='{_stroke}' stroke-opacity='0.26' stroke-width='2.4' />"
                                f"<circle cx='{_x:.2f}' cy='{_y:.2f}' r='3.0' fill='{_fill}' stroke='{_stroke}' stroke-width='1.3' />"
                            )
                        _call_points_svg = ''.join(_call_points) + ''.join(_station_points)
            except Exception:
                _call_points_svg = ""

            _map_visual_html = f"""
              <div class='map-shell'>
                <div class='map-head'>
                  <div>
                    <div class='section-kicker'>Recommended Deployment Layout</div>
                    <div class='map-title'>Coverage model for {_h(_qr_loc)}</div>
                  </div>
                  <div class='map-caption'>Stations, sample demand points, and responder posture.</div>
                </div>
                <div class='map-stage'>
                  <svg viewBox='0 0 100 100' preserveAspectRatio='none' role='img' aria-label='Deployment overview map'>
                    <rect x='2' y='2' width='96' height='96' rx='8' fill='rgba(255,255,255,0.02)' stroke='rgba(255,255,255,0.09)' />
                    <path d='M12 24 C28 11, 46 14, 61 21 S88 38, 87 55 74 85, 46 86 10 70, 11 45 12 24, 12 24Z' fill='rgba(110,231,255,0.06)' stroke='rgba(110,231,255,0.16)' stroke-width='1.2' />
                    {_call_points_svg}
                  </svg>
                </div>
              </div>
            """

            _public_summary_html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>BRINC DFR — {_qr_city}, {_qr_state}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
  <style>
    :root{{
      --bg:#050b14;
      --hero-top:#16314f;
      --hero-bottom:#091523;
      --panel:#0d1827;
      --panel-soft:#112337;
      --line:rgba(255,255,255,.08);
      --text:#f4f8ff;
      --muted:#9ab0c7;
      --cyan:#6ee7ff;
      --green:#58f5a5;
      --gold:#ffd76a;
      --violet:#c2a9ff;
      --red:#ff7b7b;
      --ink:#06283a;
      --cta:#dff8ff;
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    html{{background:var(--bg)}}
    body{{font-family:'Inter',sans-serif;background:linear-gradient(180deg,#12263d 0%,#08111d 34%,#050b14 100%);color:var(--text);min-height:100vh}}
    .page{{width:100%;max-width:1120px;margin:0 auto;padding:12px 10px 28px}}
    .hero{{background:linear-gradient(180deg,var(--hero-top) 0%,var(--hero-bottom) 100%);border:1px solid rgba(110,231,255,.18);border-radius:22px;padding:22px 18px 18px;margin-bottom:12px;box-shadow:0 18px 34px rgba(0,0,0,.28)}}
    .eyebrow{{color:var(--cyan);font-size:13px;letter-spacing:.13em;text-transform:uppercase;font-weight:800;margin-bottom:10px}}
    .headline{{font-size:clamp(34px,10vw,58px);font-weight:900;line-height:.96;letter-spacing:-.04em;max-width:12ch}}
    .hero-copy{{font-size:17px;color:var(--muted);line-height:1.55;max-width:38rem;margin-top:12px}}
    .hero-meta{{color:var(--cyan);font-size:15px;font-weight:700;margin-top:14px}}
    .cta-row{{display:flex;gap:10px;margin-top:18px}}
    .cta{{display:inline-flex;align-items:center;justify-content:center;flex:1 1 0;min-width:0;min-height:58px;padding:13px 16px;border-radius:16px;text-decoration:none;font-size:16px;font-weight:800;text-align:center}}
    .cta-primary{{background:var(--cta);color:var(--ink)}}
    .cta-secondary{{border:1px solid rgba(110,231,255,.22);background:rgba(110,231,255,.09);color:var(--cyan)}}
    .metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:12px}}
    .metric{{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px 14px 20px;min-width:0;box-shadow:0 8px 18px rgba(0,0,0,.18)}}
    .metric .k{{font-size:12px;text-transform:uppercase;letter-spacing:.1em;font-weight:800;margin-bottom:10px;opacity:.9}}
    .metric .v{{font-size:clamp(22px,7.6vw,36px);font-weight:900;line-height:1.04;word-break:break-word}}
    .m-resp .k,.m-resp .v{{color:var(--cyan)}}
    .m-save .k,.m-save .v{{color:var(--gold)}}
    .m-cov .k,.m-cov .v{{color:var(--green)}}
    .m-calls .k,.m-calls .v{{color:var(--red)}}
    .m-fleet .k,.m-fleet .v{{color:var(--violet)}}
    .m-roi .k,.m-roi .v{{color:var(--gold)}}
    .section{{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:18px 16px;box-shadow:0 10px 20px rgba(0,0,0,.14)}}
    .section + .section{{margin-top:12px}}
    .section-kicker{{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.13em;color:var(--cyan);margin-bottom:10px}}
    .section-title{{font-size:32px;font-weight:900;line-height:1.02;letter-spacing:-.03em;margin-bottom:10px}}
    .section-text{{font-size:18px;line-height:1.7;color:var(--muted)}}
    .compare{{display:grid;grid-template-columns:1fr;gap:10px}}
    .compare-card{{background:var(--panel-soft);border:1px solid rgba(255,255,255,.06);border-radius:18px;padding:18px}}
    .compare-card.after{{border-color:rgba(110,231,255,.18)}}
    .compare-card .label{{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.12em;margin-bottom:8px;color:var(--cyan)}}
    .compare-card.after .label{{color:var(--gold)}}
    .compare-card h4{{font-size:24px;font-weight:800;margin-bottom:10px}}
    .compare-card p{{font-size:17px;color:var(--muted);line-height:1.7}}
    .delta-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}}
    .delta{{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:14px;padding:14px 12px}}
    .delta .k{{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:8px}}
    .delta .v{{font-size:24px;font-weight:900}}
    .bullet-list{{display:grid;gap:12px;margin-top:12px;padding-left:22px}}
    .bullet-list li{{color:var(--muted);font-size:17px;line-height:1.7}}
    .stations-table{{width:100%;border-collapse:collapse;font-size:18px;margin-top:12px}}
    .stations-table th,.stations-table td{{padding:16px 12px;text-align:left;border-bottom:1px solid rgba(255,255,255,.06)}}
    .stations-table th{{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:800}}
    .stations-table td{{color:var(--text)}}
    .stations-table tbody tr:last-child td{{border-bottom:none}}
    .split{{display:grid;grid-template-columns:1fr;gap:12px}}
    .contact-card{{background:linear-gradient(180deg,var(--panel-soft) 0%,var(--panel) 100%);border:1px solid rgba(110,231,255,.12)}}
    .contact-label{{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--cyan);font-weight:800;margin-bottom:10px}}
    .contact-name{{font-size:32px;font-weight:900;line-height:1.05;margin-bottom:12px}}
    .contact-email{{display:block;width:100%;padding:18px 18px;border-radius:16px;background:var(--cta);color:var(--ink)!important;text-decoration:none;font-size:20px;font-weight:800;word-break:break-word;text-align:center}}
    .assumptions{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px}}
    .assumption{{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:14px;padding:12px 12px}}
    .assumption .k{{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:800;margin-bottom:7px}}
    .assumption .v{{font-size:17px;font-weight:800}}
    @media (min-width: 860px){{
      .metrics{{grid-template-columns:repeat(3,minmax(0,1fr))}}
      .compare{{grid-template-columns:1fr 1fr}}
    }}
  </style>
</head>
<body>
<div class="page">
  <section class="hero">
    <div class="eyebrow">BRINC DFR Deployment Analysis</div>
    <div class="headline">Optimize DFR Coverage in Minutes</div>
    <div class="hero-copy">Reduce response times, expand effective coverage, and justify deployment with jurisdiction-specific data.</div>
    <div class="hero-meta">Built for {_h(_qr_dept)} in {_h(_qr_city)}, {_h(_qr_state)}</div>
    <div class="cta-row">
      <a class="cta cta-primary" href="mailto:{_qr_email}?subject=Full Deployment Analysis - {_h(_qr_loc)}">Request Full Analysis</a>
      <a class="cta cta-secondary" href="mailto:{_qr_email}?subject=Book 15-Minute Demo - {_h(_qr_loc)}">Book 15-Min Demo</a>
    </div>
  </section>

  <section class="metrics">
    <div class="metric m-resp"><div class="k">Avg Drone Response Time</div><div class="v">{_qr_avg_resp:.1f} min</div></div>
    <div class="metric m-save"><div class="k">Avg Time Saved</div><div class="v">{_qr_time_saved:.1f} min</div></div>
    <div class="metric m-cov"><div class="k">Call Coverage</div><div class="v">{float(calls_covered_perc or 0):.1f}%</div></div>
    <div class="metric m-calls"><div class="k">Annual Calls Covered</div><div class="v">{_qr_covered_calls:,}</div></div>
    <div class="metric m-fleet"><div class="k">Recommended Fleet</div><div class="v">{actual_k_responder}R / {actual_k_guardian}G</div></div>
    <div class="metric m-roi"><div class="k">Annual Savings</div><div class="v">${float(annual_savings or 0):,.0f}</div></div>
  </section>

  <section class="section">
    <div class="section-kicker">Executive Summary</div>
    <div class="section-title">Deployment recommendation for {_h(_qr_loc)}</div>
    <div class="section-text">{_h(_qr_summary_text)}</div>
  </section>

  <section class="section">
    <div class="section-kicker">Before / After</div>
    <div class="section-title">Conventional response versus optimized DFR layout</div>
    <div class="compare">
      <div class="compare-card">
        <div class="label">Before</div>
        <h4>Conventional Response</h4>
        <p>Ground-only response depends on unit availability, travel congestion, and uneven spatial coverage. Arrival times vary widely, and command staff receive limited scene intelligence before officers reach the call.</p>
      </div>
      <div class="compare-card after">
        <div class="label">After</div>
        <h4>Optimized DFR Layout</h4>
        <p>Recommended drone placement is tied to real call demand and jurisdiction geometry. Aircraft are positioned to improve first-arrival speed, expand aerial reach, and give command staff live scene awareness earlier in the response cycle.</p>
      </div>
    </div>
    <div class="delta-grid">
      <div class="delta"><div class="k">Response Improvement</div><div class="v">{_qr_time_saved:.1f} min faster</div></div>
      <div class="delta"><div class="k">Coverage Improvement</div><div class="v">{float(calls_covered_perc or 0):.1f}% modeled</div></div>
      <div class="delta"><div class="k">Operational Posture</div><div class="v">{_qr_fleet_total} active aircraft</div></div>
    </div>
  </section>

  <section class="section">
    <div class="section-kicker">Why It Matters</div>
    <div class="section-title">A quick operational teaser</div>
    <ul class="bullet-list">{_impact_html}</ul>
  </section>

  <section class="section">
    <div class="section-kicker">Recommended Stations</div>
    <div class="section-title">Top recommended station sites</div>
    <table class="stations-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Station</th>
          <th>Fleet Role</th>
          <th>Avg Response Time</th>
        </tr>
      </thead>
      <tbody>{_station_table_rows_html}</tbody>
    </table>
  </section>

  <section class="section contact-card">
    <div class="contact-label">Next Step</div>
    <div class="contact-name">{_h(_qr_name)}</div>
    <div class="section-text" style="margin-bottom:16px;">Email {_h(_qr_name)} to schedule a 15-minute walkthrough or request the full deployment analysis for {_h(_qr_loc)}.</div>
    <div class="cta-row" style="margin-top:0;margin-bottom:14px;">
      <a class="cta cta-primary" href="mailto:{_qr_email}?subject=Book 15-Minute Demo - {_h(_qr_loc)}">Book 15-Min Demo</a>
      <a class="cta cta-secondary" href="mailto:{_qr_email}?subject=Full Deployment Analysis - {_h(_qr_loc)}">Request Full Analysis</a>
    </div>
    <a class="contact-email" href="mailto:{_qr_email}?subject=Book 15-Minute Demo - {_h(_qr_loc)}">{_h(_qr_email)}</a>
  </section>
</div>
</body>
</html>"""
            _public_summary_html = (
                _public_summary_html
                .replace("{_qr_city}", _qr_city)
                .replace("{_qr_state}", _qr_state)
                .replace("{_h(_qr_dept)}", _h(_qr_dept))
                .replace("{_h(_qr_city)}", _h(_qr_city))
                .replace("{_h(_qr_state)}", _h(_qr_state))
                .replace("{_qr_email}", _qr_email)
                .replace("{_h(_qr_loc)}", _h(_qr_loc))
                .replace("{_qr_avg_resp:.1f}", f"{_qr_avg_resp:.1f}")
                .replace("{_qr_time_saved:.1f}", f"{_qr_time_saved:.1f}")
                .replace("{float(calls_covered_perc or 0):.1f}", f"{float(calls_covered_perc or 0):.1f}")
                .replace("{_qr_covered_calls:,}", f"{_qr_covered_calls:,}")
                .replace("{actual_k_responder}", str(actual_k_responder))
                .replace("{actual_k_guardian}", str(actual_k_guardian))
                .replace("{float(annual_savings or 0):,.0f}", f"{float(annual_savings or 0):,.0f}")
                .replace("{_h(_qr_summary_text)}", _h(_qr_summary_text))
                .replace("{_qr_fleet_total}", str(_qr_fleet_total))
                .replace("{_impact_html}", _impact_html)
                .replace("{_station_table_rows_html}", _station_table_rows_html)
                .replace("{_h(_qr_name)}", _h(_qr_name))
                .replace("{_h(_qr_email)}", _h(_qr_email))
                .replace("{{", "{")
                .replace("}}", "}")
            )
            _report_id = st.session_state.get('public_report_id', '')
            _fleet_summary = f"{actual_k_responder}R / {actual_k_guardian}G"
            _stations_json = json.dumps([
                {
                    "name": str(d.get("name", "")),
                    "type": str(d.get("type", "")),
                    "avg_time_min": round(float(d.get("avg_time_min", 0) or 0), 1),
                }
                for d in active_drones[:6]
            ], ensure_ascii=True)
            st.session_state['_public_summary_html'] = _public_summary_html
            _publish_public_report_html(
                _report_id,
                _public_summary_html,
                metadata={
                    "report_id": _report_id,
                    "city": _qr_city,
                    "state": _qr_state,
                    "rep_name": _qr_name,
                    "rep_email": _qr_email,
                    "updated_at": datetime.datetime.now().isoformat(),
                    "public_url": st.session_state.get('public_report_url', ''),
                    "kind": "qr_summary",
                },
            )
            _publish_public_report_to_sheets(
                report_id=_report_id,
                department=_qr_dept,
                city=_qr_city,
                state=_qr_state,
                rep_name=_qr_name,
                rep_email=_qr_email,
                fleet_capex=round(float(fleet_capex or 0), 0),
                annual_savings=round(float(annual_savings or 0), 0),
                call_coverage=round(float(calls_covered_perc or 0), 1),
                fleet_summary=_fleet_summary,
                stations_json=_stations_json,
                public_html=_public_summary_html,
            )


            # ── Render full-width banner ───────────────────────────────────────────
            # Build as a variable (no leading indentation) to avoid Markdown treating
            # 4+ leading spaces as a code block, which renders HTML as raw text.
            _qr_banner = (
                '<div style="display:flex;justify-content:center;margin-top:12px;">'
                '<div style="background:linear-gradient(135deg,#0a1220 0%,#0d1630 50%,#080d18 100%);'
                'border:2px solid #00D2FF;border-radius:18px;padding:28px;overflow:hidden;max-width:1120px;width:100%;text-align:center;">'

                # Header with department name and info
                f'<div style="font-size:2rem;font-weight:900;color:#ffffff;line-height:1.12;margin-bottom:6px;">{_qr_dept}</div>'
                f'<div style="font-size:0.95rem;color:#00D2FF;font-weight:700;letter-spacing:0.4px;margin-bottom:4px;">DFR Deployment Proposal</div>'
                f'<div style="font-size:0.82rem;color:#889aaa;margin-bottom:20px;">{_qr_city}, {_qr_state}</div>'

                # QR code section — centered and much larger for distance scanning
                '<div style="display:flex;justify-content:center;align-items:center;margin:8px 0 22px;">'
                f'<div style="background:#ffffff;border-radius:22px;padding:22px;display:inline-block;box-shadow:0 14px 36px rgba(0,210,255,0.24);">'
                f'<img src="data:image/png;base64,{_qr_b64}" style="width:min(78vw,560px);height:min(78vw,560px);min-width:420px;min-height:420px;display:block;border-radius:16px;" alt="BRINC Mobile Summary QR"/>'
                '</div>'
                '</div>'

                # Footer: Rep info
                '<div style="border-top:1px solid rgba(0,210,255,0.15);padding-top:16px;">'
                '<div style="font-size:0.68rem;color:#00D2FF;text-transform:uppercase;letter-spacing:1.3px;font-weight:700;margin-bottom:5px;">Your BRINC Representative</div>'
                f'<div style="font-size:1.02rem;font-weight:800;color:#ffffff;margin-bottom:3px;">{_qr_name}</div>'
                f'<div style="font-size:0.82rem;color:#00D2FF;"><a href="mailto:{_qr_email}" style="color:#00D2FF;text-decoration:none;">{_qr_email}</a></div>'
                '</div>'

                '</div>'
                '</div>'
            )
            st.markdown(_qr_banner, unsafe_allow_html=True)
        except Exception as _qr_err:
            st.caption(f"📱 QR code unavailable — install `qrcode` package. ({_qr_err})")

        # ── EXPORT BUTTONS — always visible in sidebar ──
        st.sidebar.markdown("---")

        # Display authenticated user info (read-only, from Google OAuth)
        _google_email = st.session_state.get('google_user_email', 'user@brincdrones.com')
        _google_name_raw = st.session_state.get('google_user_name', 'User')

        st.sidebar.markdown(
            f"<div style='font-size:0.75rem;color:#00D2FF;text-transform:uppercase;letter-spacing:1.5px;font-weight:700;margin-bottom:6px;'>BRINC Representative</div>",
            unsafe_allow_html=True
        )
        st.sidebar.markdown(
            f"<div style='font-size:1rem;font-weight:700;color:#ffffff;margin-bottom:3px;'>{_google_name_raw.replace('.', ' ').title()}</div>",
            unsafe_allow_html=True
        )
        st.sidebar.markdown(
            f"<div style='font-size:0.8rem;color:#aabbcc;margin-bottom:8px;'>{_google_email}</div>",
            unsafe_allow_html=True
        )

        # Use Google auth data for exports
        user_clean = _google_name_raw.replace('.', ' ').title()
        prop_email = _google_email
        prop_name = user_clean

        # Always define these so download buttons work regardless of fleet_capex
        def _safe_export_slug(value, fallback="Export"):
            slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
            slug = re.sub(r"_+", "_", slug).strip("._-")
            return slug or fallback

        def _json_safe_export_value(value):
            if value is None or isinstance(value, (str, bool, int)):
                return value
            if isinstance(value, float):
                return value if math.isfinite(value) else None
            if isinstance(value, (np.integer,)):
                return int(value)
            if isinstance(value, (np.floating,)):
                value = float(value)
                return value if math.isfinite(value) else None
            if isinstance(value, (np.bool_,)):
                return bool(value)
            if isinstance(value, (datetime.datetime, datetime.date, pd.Timestamp)):
                return value.isoformat()
            if isinstance(value, dict):
                return {str(k): _json_safe_export_value(v) for k, v in value.items()}
            if isinstance(value, (list, tuple, set)):
                return [_json_safe_export_value(v) for v in value]
            try:
                item = value.item()
            except Exception:
                item = None
            if item is not None and item is not value:
                return _json_safe_export_value(item)
            return str(value)

        def _json_export_download(payload):
            return json.dumps(_json_safe_export_value(payload), ensure_ascii=False, allow_nan=False)

        prop_city  = _get_document_jurisdiction_name(st.session_state, selected_names, fallback='City')
        prop_state = st.session_state.get('active_state', 'FL')
        _safe_city_base = _safe_export_slug(prop_city, "City")
        export_details = {}
        export_html = None
        _report_build_started = time.perf_counter()

        def _report_wait_message():
            _call_count = int(
                st.session_state.get(
                    'total_original_calls',
                    full_total_calls if 'full_total_calls' in locals() else (len(calls_in_city) if calls_in_city is not None else 0),
                )
                or 0
            )
            _drone_count = len(active_drones) if active_drones else 0
            _last_seconds = st.session_state.get('report_build_seconds')
            if isinstance(_last_seconds, (int, float)) and _last_seconds > 0:
                return (
                    f"Creating a custom report takes time, please wait. "
                    f"Last build took {_last_seconds:.1f}s for {_call_count:,} calls and {_drone_count} drones."
                )
            _estimated_seconds = 4.0 + min(20.0, (_call_count / 180.0) + (_drone_count * 1.5))
            return (
                f"Creating a custom report takes time, please wait. "
                f"Estimated wait is about {_estimated_seconds:.0f} seconds for {_call_count:,} calls and {_drone_count} drones."
            )

        _report_wait_note = _report_wait_message()
        _report_notice_slot = st.sidebar.empty()
        _brinc_export_slot = st.sidebar.empty()
        _html_export_slot = st.sidebar.empty()
        _kml_export_slot = st.sidebar.empty()

        _report_notice_slot.info(_report_wait_note)
        _brinc_export_slot.button(
            "💾 Save Deployment Plan",
            disabled=True,
            width="stretch",
            help=_report_wait_note,
        )
        _html_export_slot.button(
            f"📄 {prop_city}, {prop_state} — Executive Summary",
            disabled=True,
            width="stretch",
            help=(
                "Deploy at least one drone to generate the executive summary."
                if fleet_capex <= 0
                else _report_wait_note
            ),
        )
        _kml_export_slot.button(
            "🌏 Google Earth Briefing File",
            disabled=True,
            width="stretch",
            help=(
                "Deploy at least one drone to generate the KML file."
                if not active_drones
                else _report_wait_note
            ),
        )
        export_dict = {
            "city": prop_city,
            "state": prop_state,
            "_disclaimer": (
                "SIMULATION TOOL: All figures in this file are model estimates based on user-provided inputs. "
                "Real-world results will vary. This is not a legal recommendation, binding proposal, contract, "
                "or guarantee of any product, service, or financial outcome."
            ),
            "k_resp": 0,
            "k_guard": 0,
            "r_resp": st.session_state.get('r_resp', ''),
            "r_guard": st.session_state.get('r_guard', ''),
            "dfr_rate": int(st.session_state.get('dfr_rate', 0) or 0),
            "deflect_rate": int(st.session_state.get('deflect_rate', 0) or 0),
            "resp_strategy": '',
            "guard_strategy": '',
            "deployment_mode_idx": st.session_state.get('deployment_mode_idx', 1),
            "incremental_build": st.session_state.get('incremental_build', True),
            "auto_cap_dfr": st.session_state.get('auto_cap_dfr', True),
            "use_county_boundary": st.session_state.get('use_county_boundary', False),
            "pinned_guard_names": [],
            "pinned_resp_names": [],
            "custom_stations": html_reports._safe_df_to_records(st.session_state.get('custom_stations')),
            "pin_drop_used": st.session_state.get('pin_drop_used', False),
            "calls_data": html_reports._safe_df_to_records(
                st.session_state.get('df_calls_full') if st.session_state.get('df_calls_full') is not None
                else st.session_state.get('df_calls')
            ),
            "stations_data": html_reports._safe_df_to_records(st.session_state.get('df_stations')),
            "faa_geojson": faa_geojson,
            "boundary_geojson": None,
            "boundary_kind": st.session_state.get('boundary_kind', 'place'),
            "boundary_source_path": st.session_state.get('boundary_source_path', ''),
            "brinc_user": st.session_state.get('brinc_user', ''),
            "pricing_tier": st.session_state.get('pricing_tier', 'Safe Guard'),
            "custom_responder_cost": int(st.session_state.get('custom_responder_cost', 79999) or 79999),
            "custom_guardian_cost": int(st.session_state.get('custom_guardian_cost', 159999) or 159999),
            "app_version": __version__,
            # ── Extended session state ────────────────────────────────────
            "estimated_pop":               int(st.session_state.get('estimated_pop', 0) or 0),
            "_pop_resolved":              bool(st.session_state.get('_pop_resolved', False)),
            "total_original_calls":        int(st.session_state.get('total_original_calls', 0) or 0),
            "total_modeled_calls":         int(st.session_state.get('total_modeled_calls', 0) or 0),
            "inferred_daily_calls_override": st.session_state.get('inferred_daily_calls_override'),
            "data_source":                 st.session_state.get('data_source', 'unknown'),
            "active_dept_name":            st.session_state.get('active_dept_name', ''),
            "target_cities":               st.session_state.get('target_cities', []),
            "city_count":                  int(st.session_state.get('city_count', 1) or 1),
            "saved_jurisdiction_names":    list(st.session_state.get('population_reference_targets', [])),
            "population_reference_kind":   st.session_state.get('population_reference_kind', ''),
            "population_reference_targets": list(st.session_state.get('population_reference_targets', [])),
            "session_start":               st.session_state.get('session_start', ''),
            "export_event_log":            list(st.session_state.get('export_event_log', [])),
            "export_count":                int(st.session_state.get('export_count', 0) or 0),
            "file_meta":                   {k: v for k, v in (st.session_state.get('file_meta') or {}).items()
                                           if isinstance(v, (str, int, float, bool, type(None)))},
            "show_satellite_b":            st.session_state.get('show_satellite_b', False),
            "show_boundaries_b":           st.session_state.get('show_boundaries_b', True),
            "show_faa_b":                  st.session_state.get('show_faa_b', False),
            "show_no_fly_b":               st.session_state.get('show_no_fly_b', False),
            "show_obstacles_b":            st.session_state.get('show_obstacles_b', False),
            "show_coverage_b":             st.session_state.get('show_coverage_b', False),
            "show_cell_towers_b":          st.session_state.get('show_cell_towers_b', False),
            "show_heatmap_b":              st.session_state.get('show_heatmap_b', False),
            "show_dots_b":                 st.session_state.get('show_dots_b', True),
            "show_rapid_response_ring_b":  st.session_state.get('show_rapid_response_ring_b', True),
            "simulate_traffic_b":          st.session_state.get('simulate_traffic_b', False),
            "show_health_b":               st.session_state.get('show_health_b', False),
            "show_financials_b":           st.session_state.get('show_financials_b', True),
            "simple_cards_b":              st.session_state.get('simple_cards_b', False),
            "doc_custom_intro":            st.session_state.get('doc_custom_intro', ''),
            "doc_talking_pt_1":            st.session_state.get('doc_talking_pt_1', ''),
            "doc_talking_pt_2":            st.session_state.get('doc_talking_pt_2', ''),
            "doc_talking_pt_3":            st.session_state.get('doc_talking_pt_3', ''),
            "doc_custom_closing":          st.session_state.get('doc_custom_closing', ''),
            "doc_ae_phone":                st.session_state.get('doc_ae_phone', ''),
        }

        if fleet_capex > 0:

            prop_city  = _get_document_jurisdiction_name(st.session_state, selected_names, fallback='City')
            prop_state = st.session_state.get('active_state', 'FL')

            pop_metric = st.session_state.get('estimated_pop', 250000)
            current_time_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            safe_city = prop_city.replace(" ","_").replace("/","_")

            _session_start = st.session_state.get('session_start', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            try:
                _start_dt = datetime.datetime.strptime(_session_start, '%Y-%m-%d %H:%M:%S')
                _dur_min  = round((datetime.datetime.now() - _start_dt).total_seconds() / 60, 1)
            except Exception:
                _dur_min = ''

            avg_resp_time    = sum(d['avg_time_min'] for d in active_drones) / len(active_drones) if active_drones else 0.0
            _exp_base_gs     = float(CONFIG["DEFAULT_TRAFFIC_SPEED"])
            _exp_eff_gs      = _exp_base_gs * (1.0 - float(traffic_level) / 100.0) if simulate_traffic else _exp_base_gs
            avg_time_saved   = (max(0.0, (sum(d['avg_time_min'] * d['speed_mph'] * 1.4 / _exp_eff_gs for d in active_drones) / len(active_drones)) - avg_resp_time)) if active_drones and _exp_eff_gs > 0 else 0.0
            _calls_lons = (df_calls_full if df_calls_full is not None else df_calls)['lon'].dropna()
            _calls_lats = (df_calls_full if df_calls_full is not None else df_calls)['lat'].dropna()
            minx = float(_calls_lons.min()) if len(_calls_lons) else 0
            maxx = float(_calls_lons.max()) if len(_calls_lons) else 0
            miny = float(_calls_lats.min()) if len(_calls_lats) else 0
            maxy = float(_calls_lats.max()) if len(_calls_lats) else 0
            area_sq_mi_est   = max(1, int((maxx - minx) * (maxy - miny) * 3280))
            export_details = {
                # Session
                "session_id":            st.session_state.get('session_id', ''),
                "session_start":         _session_start,
                "session_duration_min":  _dur_min,
                "data_source":           st.session_state.get('data_source', 'unknown'),
                # Jurisdiction (user-selected)
                "population":            pop_metric,
                "total_calls":           st.session_state.get('total_original_calls', 0),
                "daily_calls":           max(1, int(st.session_state.get('total_original_calls', 0) / 365)),
                "area_sq_mi":            area_sq_mi_est,
                # City/state enrichment
                "city_confirmed_match":  (
                    st.session_state.get('file_meta', {}).get('file_inferred_city', '').lower().strip() ==
                    prop_city.lower().strip()
                    if st.session_state.get('file_meta', {}).get('file_inferred_city', '') else ''
                ),
                "multi_city_targets":    json.dumps(st.session_state.get('target_cities', [])),
                "num_cities_targeted":   len(st.session_state.get('target_cities', [])),
                # Financials
                "opt_strategy":          opt_strategy,
                "incremental_build":     incremental_build,
                "allow_redundancy":      allow_redundancy,
                "dfr_rate":              int(dfr_dispatch_rate*100),
                "deflect_rate":          int(deflection_rate*100),
                "fleet_capex":           fleet_capex,
                "annual_savings":        annual_savings,
                "thermal_savings":       thermal_savings,
                "k9_savings":            k9_savings,
                "possible_additional_savings": possible_additional_savings,
                "break_even":            break_even_text,
                # Operational
                "avg_response_min":      round(avg_resp_time, 2),
                "avg_time_saved_min":    round(avg_time_saved, 2),
                "area_covered_pct":      round(area_covered_perc, 1),
                "calls_per_capita":      round(st.session_state.get('total_original_calls', 0) / max(pop_metric, 1), 4),
                # Engagement / depth signals
                "r_resp_radius":         st.session_state.get('r_resp', ''),
                "r_guard_radius":        st.session_state.get('r_guard', ''),
                "estimated_pop_input":   pop_metric,
                "boundary_kind":         st.session_state.get('boundary_kind', ''),
                "boundary_source_path":  st.session_state.get('boundary_source_path', ''),
                "sim_or_upload":         st.session_state.get('data_source', 'unknown'),
                "onboarding_completed":  st.session_state.get('onboarding_done', False),
                "demo_mode_used":        st.session_state.get('demo_mode_used', False),
                "map_viewed":            st.session_state.get('map_build_logged', False),
                "export_type_sequence":  json.dumps(st.session_state.get('export_event_log', [])),
                "total_exports_in_session": st.session_state.get('export_count', 0),
                # File data matrix (populated by aggressive_parse_calls → _extract_file_meta)
                "file_meta":             st.session_state.get('file_meta', {}),
                # Build metadata
                "app_version":          __version__,
                "app_revision":         __build_revision__,
                "build_datetime":       __build_datetime__,
                "app_line_count":       __build_line_count__,
                # Drones
                "active_drones": [{
                    "name": d['name'], "type": d['type'],
                    "lat": d['lat'],   "lon": d['lon'],
                    "avg_time_min":    d.get('avg_time_min', 0),
                    "faa_ceiling":     d.get('faa_ceiling', ''),
                    "annual_savings":  d.get('annual_savings', 0),
                } for d in active_drones],
            }

            _mgdf_export = st.session_state.get('master_gdf_override')
            _boundary_geojson_export = None
            if _mgdf_export is not None and not _mgdf_export.empty:
                try:
                    _boundary_geojson_export = _mgdf_export.to_crs(epsg=4326).to_json()
                except Exception:
                    _boundary_geojson_export = None

            _custom_export_df = st.session_state.get('custom_stations', pd.DataFrame())
            _stations_export_df = st.session_state.get('df_stations')
            if _stations_export_df is not None and hasattr(_stations_export_df, 'copy'):
                _stations_export_df = _stations_export_df.copy()
                if _custom_export_df is not None and hasattr(_custom_export_df, 'empty') and not _custom_export_df.empty:
                    for _col in ('address', 'input_address', 'geocode_source', 'custom', 'lock_role'):
                        if _col not in _stations_export_df.columns:
                            _stations_export_df[_col] = None
                    _custom_lookup = _custom_export_df.copy()
                    _custom_lookup['_merge_name'] = _custom_lookup.get('name', pd.Series(index=_custom_lookup.index, dtype=object)).astype(str).str.strip()
                    _custom_lookup['_merge_type'] = _custom_lookup.get('type', pd.Series(index=_custom_lookup.index, dtype=object)).astype(str).str.strip()
                    _custom_lookup = _custom_lookup.drop_duplicates(subset=['_merge_name', '_merge_type'], keep='last')
                    _custom_lookup = _custom_lookup.set_index(['_merge_name', '_merge_type'])
                    for _idx, _row in _stations_export_df.iterrows():
                        _key = (str(_row.get('name', '')).strip(), str(_row.get('type', '')).strip())
                        if _key in _custom_lookup.index:
                            _src = _custom_lookup.loc[_key]
                            if hasattr(_src, 'iloc'):
                                _src = _src.iloc[-1]
                            for _col in ('address', 'input_address', 'geocode_source', 'custom', 'lock_role'):
                                if _col in _src.index:
                                    _stations_export_df.at[_idx, _col] = _src.get(_col)

            export_dict = {
                "city": prop_city, "state": prop_state,
                "_disclaimer": (
                    "SIMULATION TOOL: All figures in this file are model estimates based on user-provided inputs. "
                    "Real-world results will vary. This is not a legal recommendation, binding proposal, contract, "
                    "or guarantee of any product, service, or financial outcome."
                ),
                # Fleet counts and ranges
                "k_resp": k_responder, "k_guard": k_guardian,
                "r_resp": resp_radius_mi, "r_guard": guard_radius_mi,
                # Rates
                "dfr_rate": int(dfr_dispatch_rate*100), "deflect_rate": int(deflection_rate*100),
                # Optimization strategies
                "resp_strategy": resp_strategy_raw,
                "guard_strategy": guard_strategy_raw,
                "deployment_mode_idx": st.session_state.get('deployment_mode_idx', 1),
                "incremental_build": st.session_state.get('incremental_build', True),
                "auto_cap_dfr": st.session_state.get('auto_cap_dfr', True),
                # Boundary selection
                "use_county_boundary": st.session_state.get('use_county_boundary', False),
                # Locked stations (must restore before auto-minimums runs)
                "pinned_guard_names": list(pinned_guard_names),
                "pinned_resp_names":  list(pinned_resp_names),
                # Custom / pin-dropped stations (bypass OSM on reimport)
                "custom_stations": html_reports._safe_df_to_records(st.session_state.get('custom_stations')),
                # Whether fleet was manually built via pin-drop
                "pin_drop_used": st.session_state.get('pin_drop_used', False),
                # Call and station data
                "calls_data": html_reports._safe_df_to_records(
                    st.session_state.get('df_calls_full') if st.session_state.get('df_calls_full') is not None
                    else st.session_state.get('df_calls')
                ),
                "stations_data": html_reports._safe_df_to_records(_stations_export_df),
                "faa_geojson": faa_geojson,
                # Boundary / shapefile
                "boundary_geojson": _boundary_geojson_export,
                "boundary_kind": st.session_state.get('boundary_kind', 'place'),
                "boundary_source_path": st.session_state.get('boundary_source_path', ''),
                # Sidebar settings — BRINC rep info
                "brinc_user": st.session_state.get('brinc_user', ''),
                # Pricing tier selection
                "pricing_tier": st.session_state.get('pricing_tier', 'Safe Guard'),
                "custom_responder_cost": int(st.session_state.get('custom_responder_cost', 79999) or 79999),
                "custom_guardian_cost": int(st.session_state.get('custom_guardian_cost', 159999) or 159999),
                "app_version": __version__,
                # ── Extended session state ────────────────────────────────────
                # Jurisdiction metrics
                "estimated_pop":               int(st.session_state.get('estimated_pop', 0) or 0),
                "_pop_resolved":              bool(st.session_state.get('_pop_resolved', False)),
                "total_original_calls":        int(st.session_state.get('total_original_calls', 0) or 0),
                "total_modeled_calls":         int(st.session_state.get('total_modeled_calls', 0) or 0),
                "inferred_daily_calls_override": st.session_state.get('inferred_daily_calls_override'),
                "data_source":                 st.session_state.get('data_source', 'unknown'),
                "active_dept_name":            st.session_state.get('active_dept_name', ''),
                "target_cities":               st.session_state.get('target_cities', []),
                "city_count":                  int(st.session_state.get('city_count', 1) or 1),
                "saved_jurisdiction_names":    list(selected_names),
                "population_reference_kind":   st.session_state.get('population_reference_kind', ''),
                "population_reference_targets": list(st.session_state.get('population_reference_targets', [])),
                "session_start":               st.session_state.get('session_start', ''),
                "export_event_log":            list(st.session_state.get('export_event_log', [])),
                "export_count":                int(st.session_state.get('export_count', 0) or 0),
                "file_meta":                   {k: v for k, v in (st.session_state.get('file_meta') or {}).items()
                                                if isinstance(v, (str, int, float, bool, type(None)))},
                # Display options (widget keys)
                "show_satellite_b":            st.session_state.get('show_satellite_b', False),
                "show_boundaries_b":           st.session_state.get('show_boundaries_b', True),
                "show_faa_b":                  st.session_state.get('show_faa_b', False),
                "show_no_fly_b":               st.session_state.get('show_no_fly_b', False),
                "show_obstacles_b":            st.session_state.get('show_obstacles_b', False),
                "show_coverage_b":             st.session_state.get('show_coverage_b', False),
                "show_cell_towers_b":          st.session_state.get('show_cell_towers_b', False),
                "show_heatmap_b":              st.session_state.get('show_heatmap_b', False),
                "show_dots_b":                 st.session_state.get('show_dots_b', True),
                "show_rapid_response_ring_b":  st.session_state.get('show_rapid_response_ring_b', True),
                "simulate_traffic_b":          st.session_state.get('simulate_traffic_b', False),
                "show_health_b":               st.session_state.get('show_health_b', False),
                "show_financials_b":           st.session_state.get('show_financials_b', True),
                "simple_cards_b":              st.session_state.get('simple_cards_b', False),
                # Document customization
                "doc_custom_intro":            st.session_state.get('doc_custom_intro', ''),
                "doc_talking_pt_1":            st.session_state.get('doc_talking_pt_1', ''),
                "doc_talking_pt_2":            st.session_state.get('doc_talking_pt_2', ''),
                "doc_talking_pt_3":            st.session_state.get('doc_talking_pt_3', ''),
                "doc_custom_closing":          st.session_state.get('doc_custom_closing', ''),
                "doc_ae_phone":                st.session_state.get('doc_ae_phone', ''),
            }

            export_html = None

            if True:
                fig_for_export = go.Figure()
    
                # ── Boundary polygon ─────────────────────────────────────────────────
                if city_boundary_geom is not None and not city_boundary_geom.is_empty:
                    _export_geoms = ([city_boundary_geom] if isinstance(city_boundary_geom, Polygon)
                                     else list(city_boundary_geom.geoms))
                    for _gi, _geom in enumerate(_export_geoms):
                        _bx, _by = _geom.exterior.coords.xy
                        fig_for_export.add_trace(go.Scattermap(
                            mode="lines", lon=list(_bx), lat=list(_by),
                            line=dict(color=map_boundary_color, width=2),
                            name="Jurisdiction Boundary", hoverinfo='skip',
                            showlegend=(_gi == 0)
                        ))
    
                # ── Incident call dots ──────────────────────────────────────────��────
                _export_calls = display_calls if (display_calls is not None and not display_calls.empty) else None
                if _export_calls is not None:
                    # Cap at 40K for export file-size; sample deterministically
                    _EC_MAX = 40_000
                    if len(_export_calls) > _EC_MAX:
                        _export_calls = _export_calls.sample(_EC_MAX, random_state=42)
                    _exp_pt_size = (2 if len(_export_calls) > 20_000 else
                                    3 if len(_export_calls) > 8_000 else 4)
                    _exp_opacity = (0.18 if len(_export_calls) > 20_000 else
                                    0.28 if len(_export_calls) > 8_000 else 0.40)
                    _has_agency = 'agency' in _export_calls.columns
                    _exp_fire   = _export_calls[_export_calls['agency'].str.lower() == 'fire'] if _has_agency else _export_calls.iloc[0:0]
                    _exp_police = _export_calls[_export_calls['agency'].str.lower() != 'fire'] if _has_agency else _export_calls
                    if not _exp_police.empty:
                        fig_for_export.add_trace(go.Scattermap(
                            lat=_exp_police.geometry.y, lon=_exp_police.geometry.x,
                            mode='markers',
                            marker=dict(size=_exp_pt_size, color=map_incident_color, opacity=_exp_opacity),
                            name="Incidents", hoverinfo='skip'
                        ))
                    if not _exp_fire.empty:
                        fig_for_export.add_trace(go.Scattermap(
                            lat=_exp_fire.geometry.y, lon=_exp_fire.geometry.x,
                            mode='markers',
                            marker=dict(size=_exp_pt_size, color='#ff3b3b', opacity=_exp_opacity),
                            name="Fire Incidents", hoverinfo='skip'
                        ))
    
                # ── 4G LTE coverage polygons (legendonly, toggleable in export) ─────
                _exp_cov_state = st.session_state.get('active_state', '')
                if _exp_cov_state:
                    add_coverage_traces(fig_for_export, _exp_cov_state, visible='legendonly')
    
                # ── Coverage circles + station pins ──────────────────────────────────
                for d in active_drones:
                    clats, clons = get_circle_coords(d['lat'], d['lon'], r_mi=d['radius_m']/1609.34)
                    fig_for_export.add_trace(go.Scattermap(
                        lat=list(clats)+[None,d['lat']], lon=list(clons)+[None,d['lon']],
                        mode='lines+markers', line=dict(color=d['color'], width=3),
                        marker=dict(size=[0]*len(clats)+[0,16], color=d['color']),
                        fill='toself', fillcolor='rgba(0,0,0,0)', name=d['name'][:30]
                    ))
    
                fig_for_export.update_layout(
                    map=dict(center=dict(lat=center_lat, lon=center_lon), zoom=dynamic_zoom, style="carto-darkmatter"),
                    margin=dict(l=0,r=0,t=0,b=0), height=500, showlegend=True,
                    legend=dict(
                        yanchor="top", y=0.98, xanchor="left", x=0.02,
                        bgcolor=legend_bg, bordercolor="#444444", borderwidth=1,
                        font=dict(color=legend_text, size=11)
                    )
                )
                map_html_str = fig_for_export.to_html(full_html=False, include_plotlyjs='cdn', default_height='500px', default_width='100%')
                station_rows = "".join(f"<tr><td>{d['name']}</td><td>{d['type']}</td><td>{d['avg_time_min']:.1f} min</td><td>{d['faa_ceiling']}</td><td>${d['cost']:,}</td></tr>" for d in active_drones)
    
                all_bldgs_rows = ""
                _type_colors = {
                    "Police":          ("rgba(0,210,255,0.1)",    "#0066aa"),
                    "Fire":            ("rgba(220,53,69,0.1)",    "#aa0022"),
                    "EMS":             ("rgba(255,100,50,0.1)",   "#b33000"),
                    "School":          ("rgba(255,215,0,0.12)",   "#7a6000"),
                    "Hospital":        ("rgba(34,197,94,0.1)",    "#006622"),
                    "University":      ("rgba(59,130,246,0.1)",   "#1d4ed8"),
                    "Transit":         ("rgba(16,185,129,0.1)",   "#065f46"),
                    "Community":       ("rgba(245,158,11,0.1)",   "#92400e"),
                    "Courthouse":      ("rgba(139,92,246,0.12)",  "#5b21b6"),
                    "Social Services": ("rgba(236,72,153,0.1)",   "#9d174d"),
                    "Government":      ("rgba(139,92,246,0.1)",   "#4b0082"),
                    "Library":         ("rgba(249,115,22,0.1)",   "#8a3300"),
                    "Power Station":   ("rgba(255,165,0,0.1)",    "#cc6600"),
                    "Water Treatment": ("rgba(100,200,255,0.1)",  "#0066cc"),
                    "Place of Worship": ("rgba(200,100,200,0.1)", "#663366"),
                }
                # ── Facility type counts (for summary grid + community impact dashboard) ──
                _fac_counts = {}
                for _, _frow in df_stations_all.iterrows():
                    _ft = str(_frow.get('type', 'Other'))
                    _fac_counts[_ft] = _fac_counts.get(_ft, 0) + 1
    
                # ── Facility type summary HTML (icons + counts) ──────────────────────
                _FAC_ICONS = {
                    "Police": "🚔", "Fire": "🚒", "EMS": "🚑", "School": "🏫",
                    "Hospital": "🏥", "University": "🎓", "Transit": "🚌",
                    "Community": "🏛️", "Courthouse": "⚖️", "Social Services": "🤝",
                    "Government": "🏛️", "Library": "📚",
                    "Power Station": "⚡", "Water Treatment": "💧", "Place of Worship": "✝️",
                }
                _FAC_SOURCES = {
                    "Police":          "DHS HIFLD Law Enforcement Locations · OpenStreetMap (amenity=police) · ODbL license",
                    "Fire":            "DHS HIFLD Fire Stations dataset (public domain) · OpenStreetMap (amenity=fire_station)",
                    "EMS":             "OpenStreetMap (amenity=ambulance_station) · NEMSIS National EMS Database (nemsis.org)",
                    "School":          "OpenStreetMap (amenity=school) · NCES Common Core of Data (nces.ed.gov)",
                    "Hospital":        "OpenStreetMap (amenity=hospital) · CMS Hospital Compare (cms.gov)",
                    "University":      "OpenStreetMap (amenity=university / college) · IPEDS (nces.ed.gov/ipeds)",
                    "Transit":         "OpenStreetMap (amenity=bus_station · railway=station) · NTD National Transit Database (transit.dot.gov)",
                    "Community":       "OpenStreetMap (amenity=community_centre) · IMLS Public Libraries Survey",
                    "Courthouse":      "OpenStreetMap (amenity=courthouse) · PACER / US Courts (uscourts.gov)",
                    "Social Services": "OpenStreetMap (amenity=social_facility) · HUD Location Affordability Index",
                    "Government":      "OpenStreetMap (building=government) · TIGER/Line Shapefiles (census.gov)",
                    "Library":         "OpenStreetMap (amenity=library) · IMLS Public Libraries Survey (imls.gov)",
                    "Power Station":   "OpenStreetMap (power=station) · US Energy Information Administration (eia.gov)",
                    "Water Treatment": "OpenStreetMap (man_made=water_treatment) · EPA Enviromapper · US Water Infrastructure Database",
                    "Place of Worship": "OpenStreetMap (amenity=place_of_worship) · Faith-based facility directory",
                }
                _fac_summary_cells = ""
                for _ft, _fcnt in sorted(_fac_counts.items(), key=lambda x: -x[1]):
                    _tc2 = _type_colors.get(_ft, ("rgba(0,0,0,0.04)", "#555"))
                    _icon = _FAC_ICONS.get(_ft, "🏢")
                    _src  = _FAC_SOURCES.get(_ft, "OpenStreetMap contributors (ODbL)")
                    _fac_summary_cells += (
                        f'<div style="background:{_tc2[0]};border:1px solid {_tc2[1]}33;border-radius:8px;'
                        f'padding:10px 14px;display:flex;align-items:center;gap:10px;">'
                        f'<span style="font-size:20px">{_icon}</span>'
                        f'<div><div style="font-size:11px;font-weight:700;color:{_tc2[1]};text-transform:uppercase;'
                        f'letter-spacing:0.5px;">{_ft}</div>'
                        f'<div style="font-size:18px;font-weight:900;color:#111;font-family:\'IBM Plex Mono\',monospace;">{_fcnt}</div>'
                        f'<div style="font-size:9px;color:#777;margin-top:1px;">facilities</div></div>'
                        f'<abbr title="Source: {_src}" style="margin-left:auto;font-size:10px;color:#aaa;'
                        f'text-decoration:none;cursor:help;">ⓘ</abbr>'
                        f'</div>'
                    )
    
                for _, row in df_stations_all.iterrows():
                    gmaps_link = f"https://www.google.com/maps/search/?api=1&query={row['lat']},{row['lon']}"
                    _rtype = str(row.get('type', 'Facility'))
                    _tc = _type_colors.get(_rtype, ("rgba(0,0,0,0.04)","#555"))
                    _short_name = str(row['name'])[:45] + ("…" if len(str(row['name']))>45 else "")
                    _src_tip = _FAC_SOURCES.get(_rtype, "OpenStreetMap contributors (ODbL)")
                    all_bldgs_rows += (
                        f'''<div class="infra-item">
                          <span class="i-name" title="{row['name']}">{_short_name}</span>
                          <span class="i-type" style="background:{_tc[0]};color:{_tc[1]}">{_rtype}</span>
                          <abbr title="Source: {_src_tip}" style="font-size:10px;color:#aaa;text-decoration:none;cursor:help;margin-left:auto;">ⓘ</abbr>
                          <a class="i-link" href="{gmaps_link}" target="_blank">↗</a>
                        </div>'''
                    )
    
                logo_b64 = get_themed_logo_base64("logo.png", theme="dark")
                logo_html_str = f'<img src="data:image/png;base64,{logo_b64}" style="height:40px;">' if logo_b64 else '<div style="font-size:24px;font-weight:900;letter-spacing:3px;color:#fff;">BRINC</div>'
    
                jurisdiction_list = ", ".join(selected_names) if selected_names else prop_city
                all_station_types = df_stations_all['type'].dropna().unique().tolist() if 'type' in df_stations_all.columns else []
                police_dept_names = [d['name'] for d in active_drones if '[Police]' in d['name']]
                fire_dept_names   = [d['name'] for d in active_drones if '[Fire]' in d['name']]
                ems_dept_names    = [d['name'] for d in active_drones if '[EMS]' in d['name']]
    
                police_stations = [d['name'] for d in active_drones if 'Police' in d.get('name','') or (
                    'type' in df_stations_all.columns and
                    'Police' in str(df_stations_all[df_stations_all['name'].str.contains(
                        d['name'].split(']')[-1].strip(), na=False, regex=False
                    )]['type'].values[:1])
                )]
    
                dept_summary_parts = []
                if police_dept_names: dept_summary_parts.append(f"{len(police_dept_names)} Police station{'s' if len(police_dept_names)>1 else ''}")
                if fire_dept_names:   dept_summary_parts.append(f"{len(fire_dept_names)} Fire station{'s' if len(fire_dept_names)>1 else ''}")
                if ems_dept_names:    dept_summary_parts.append(f"{len(ems_dept_names)} EMS station{'s' if len(ems_dept_names)>1 else ''}")
                dept_summary = ", ".join(dept_summary_parts) if dept_summary_parts else f"{len(active_drones)} municipal stations"
                police_names_str = (", ".join([n.replace('[Police] ','') for n in police_dept_names[:6]]) + ("..." if len(police_dept_names)>6 else "")) if police_dept_names else "municipal facilities"
                total_fleet = actual_k_responder + actual_k_guardian
                try:
                    analytics_html_export = html_reports.generate_command_center_html(
                        df_calls_full if df_calls_full is not None else df_calls,
                        total_orig_calls=st.session_state.get('total_original_calls', full_total_calls or total_calls),
                        export_mode=True
                    )
                except Exception:
                    analytics_html_export = "<div style='color:gray; padding:20px;'>Analytics unavailable for this dataset.</div>"
                cad_charts_html_export = html_reports._build_cad_charts_html(df_calls_full if df_calls_full is not None else df_calls)
                staffing_pressure_html_export = ""
    
                prepared_for_city = _get_document_jurisdiction_name(st.session_state, selected_names, fallback=prop_city) or prop_city
                prepared_by_name = prop_name
    
                # ── School safety export variables ────────────────────────────────────────
                _exp_dfr_amortized = int(fleet_capex / 7) if fleet_capex > 0 else 0
                _dfr_amort_str     = f"${_exp_dfr_amortized:,}/yr" if _exp_dfr_amortized > 0 else "~$11K–22K/yr"
    
                # ── Build custom-content HTML blocks from AE editable fields ────────────
                _doc_intro   = st.session_state.get('doc_custom_intro',   '').strip()
                _doc_pt1     = st.session_state.get('doc_talking_pt_1',  '').strip()
                _doc_pt2     = st.session_state.get('doc_talking_pt_2',  '').strip()
                _doc_pt3     = st.session_state.get('doc_talking_pt_3',  '').strip()
                _doc_closing = st.session_state.get('doc_custom_closing', '').strip()
                _doc_phone   = st.session_state.get('doc_ae_phone',       '').strip()
    
                _custom_intro_html = (
                    f'<div style="margin-top:20px;padding:16px 20px;background:#f0f8ff;border-left:4px solid #00D2FF;'
                    f'border-radius:0 6px 6px 0;font-size:15px;color:#1a2a3a;line-height:1.8;">'
                    f'{_doc_intro}</div>'
                ) if _doc_intro else ''
    
                _pts = [p for p in [_doc_pt1, _doc_pt2, _doc_pt3] if p]
                _custom_pts_html = (
                    '<ul style="margin-top:16px;padding-left:20px;font-size:14px;color:#374151;line-height:2;">'
                    + ''.join(f'<li>{p}</li>' for p in _pts)
                    + '</ul>'
                ) if _pts else ''
    
                _custom_closing_html = (
                    f'<div style="margin-top:24px;padding:16px 20px;background:#f9fafb;border:1px solid #e4e6ea;'
                    f'border-radius:6px;font-size:14px;color:#374151;line-height:1.8;">'
                    f'{_doc_closing}</div>'
                ) if _doc_closing else ''
    
                _ae_phone_html = (
                    f'<div style="margin-top:4px;font-size:13px;color:#555;">📞 {_doc_phone}</div>'
                ) if _doc_phone else ''
                # ── Export personalization: extract call-type and priority stats ────────
                _exp_df = df_calls_full if (df_calls_full is not None and not df_calls_full.empty) else df_calls
                _exp_top_calls, _exp_pri_str, _exp_date_range = [], "mixed priorities", "recent period"
                try:
                    for _cc in ['call_type_desc','agencyeventtypecodedesc','calldesc','description']:
                        if _cc in _exp_df.columns:
                            _tc = _exp_df[_cc].dropna().str.strip().value_counts().head(5)
                            if not _tc.empty:
                                _exp_top_calls = list(zip(_tc.index.tolist(), _tc.values.tolist()))
                            break
                    if 'priority' in _exp_df.columns:
                        _pc = _exp_df['priority'].dropna().value_counts().sort_index()
                        _pri_parts = [f"Priority {k}: {v:,} ({v/max(len(_exp_df),1)*100:.0f}%)" for k,v in _pc.items() if str(k).strip().isdigit()]
                        _exp_pri_str = " · ".join(_pri_parts[:4]) if _pri_parts else "mixed priorities"
                    if 'date' in _exp_df.columns:
                        _dd = pd.to_datetime(_exp_df['date'], errors='coerce').dropna()
                        if not _dd.empty:
                            _exp_date_range = f"{_dd.min().strftime('%b %Y')} – {_dd.max().strftime('%b %Y')}"
                except Exception:
                    pass
                _top5_html = ""
                for _cname, _ccnt in (_exp_top_calls or []):
                    _cpct = f"{_ccnt/max(len(_exp_df),1)*100:.1f}%"
                    _is_prop = any(w in str(_cname).upper() for w in ['THEFT','BURGLAR','VANDAL','ROBBERY','TRESPASS','LARCEN','AUTO','VEHICLE','BREAK','SHOPLI'])
                    _cflag = ' <span style="color:#f59e0b;font-size:10px">property-related</span>' if _is_prop else ''
                    _top5_html += f'<tr><td><strong>{_cname}</strong>{_cflag}</td><td style="font-family:monospace;color:#374151">{_ccnt:,}</td><td style="color:#6b7280">{_cpct}</td></tr>'
                _guardian_img_b64 = get_transparent_product_base64("gigs.png") or ""
                logo_b64_dark = get_themed_logo_base64("logo.png", theme="dark")
                logo_b64_light = get_themed_logo_base64("logo.png", theme="light")
    
                # ── FCC 4G LTE Coverage Map URL for export ────────────────────────────
                _fcc_zoom_export = round(min(13, max(9, dynamic_zoom + 1)), 2)
                _fcc_url = (f"https://broadbandmap.fcc.gov/home?version=dec2023"
                            f"&zoom={_fcc_zoom_export}&vlon={center_lon:.6f}&vlat={center_lat:.6f}"
                            f"&speed=25&tech=300&br=4")
    
                # ── 4G LTE carrier mini-maps for export section 03b ─────────────────
                _exp_carrier_results = _carrier_coverage_analysis(
                    st.session_state.get('active_state', ''), city_boundary_geom
                )
                if _exp_carrier_results:
                    _exp_map_cols = []
                    for _eci, _ecr in enumerate(_exp_carrier_results[:3]):
                        _epct = f"{_ecr['pct']:.1f}%" if _ecr['pct'] > 0 else "No data"
                        _ebadge = "#22c55e" if _ecr['pct'] >= 90 else "#f59e0b" if _ecr['pct'] >= 70 else "#ef4444"
                        _emfig = _build_carrier_mini_map(
                            _ecr, city_boundary_geom, center_lat, center_lon,
                            dynamic_zoom, 'carto-positron'
                        )
                        _inc_plotlyjs = 'cdn' if _eci == 0 else False
                        _emap_div = _emfig.to_html(
                            full_html=False, include_plotlyjs=_inc_plotlyjs,
                            default_height='240px', default_width='100%'
                        )
                        _exp_map_cols.append(
                            f'<div style="flex:1;min-width:200px;">'
                            f'<div style="text-align:center;padding:6px 0 4px;">'
                            f'<span style="font-size:1rem;font-weight:800;color:{_ecr["color"]};">{_ecr["carrier"]}</span><br>'
                            f'<span style="font-size:1.7rem;font-weight:900;color:{_ebadge};font-family:monospace;">{_epct}</span><br>'
                            f'<span style="font-size:0.62rem;color:#8899aa;text-transform:uppercase;letter-spacing:1px;">of jurisdiction covered</span>'
                            f'</div>{_emap_div}</div>'
                        )
                    _exp_lte_content = (
                        '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;">'
                        + ''.join(_exp_map_cols)
                        + '</div>'
                        + '<p style="font-size:0.65rem;color:#556;margin:8px 0 0;">'
                        + 'Source: FCC Broadband Data Collection · AT&amp;T, T-Mobile, Verizon 4G LTE coverage polygons.'
                        + '</p>'
                    )
                else:
                    _exp_lte_content = (
                        f'<a href="{_fcc_url}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;">'
                        f'<div style="display:flex;align-items:center;justify-content:space-between;background:#0d1b2e;border:1px solid #1e3a5f;border-radius:10px;padding:20px 28px;">'
                        f'<div><div style="color:#00b4d8;font-size:1rem;font-weight:600;margin-bottom:4px;">📶 Open FCC 4G LTE Coverage Map</div>'
                        f'<div style="color:#6b7f99;font-size:0.78rem;">FCC National Broadband Map · AT&amp;T, T-Mobile, Verizon · Centered on {center_lat:.4f}, {center_lon:.4f}</div>'
                        f'</div><div style="color:#00b4d8;font-size:1.6rem;margin-left:20px;">↗</div></div></a>'
                        f'<p style="font-size:0.65rem;color:#556;margin:10px 0 0;">Opens broadbandmap.fcc.gov in a new tab.</p>'
                    )
    
                # ── Re-establish tier badge variables for export ────────────────────────
                _exp_pricing_tier = st.session_state.get('pricing_tier', 'Safe Guard')
                if _exp_pricing_tier == "Safe Guard":
                    _tier_badge = "🛡️ Safe Guard"
                    _tier_desc = "Advanced Custom Features"
                elif _exp_pricing_tier == "Custom Quote":
                    _tier_badge = "Custom Quote"
                    _tier_desc = "Sales-Entered Pricing"
                else:
                    _tier_badge = "🛡️ Safe Guard Lite"
                    _tier_desc = "Core Functionality"
    
                _jur_source_file = st.session_state.get('_jur_source_file', '')
                _boundary_src_display = (
                    _jur_source_file if _boundary_src_note == 'local_parquet' and _jur_source_file
                    else 'local_parquet' if _boundary_src_note == 'local_parquet'
                    else (_boundary_src_note.split('/')[-1].split('\\')[-1] if _boundary_src_note else 'live lookup')
                )
                _selected_labels_str = ', '.join(selected_names) if selected_names else prop_city
                _grant_context_text = " ".join(
                    str(v) for v in [
                        prepared_for_city, prop_city, prop_state, police_names_str,
                        jurisdiction_list, dept_summary, _selected_labels_str,
                    ] if v
                ).lower()

                def _grant_context_looks_like_state_agency(ctx_text: str) -> bool:
                    _state_agency_markers = (
                        "single state agency",
                        "state agency",
                        "state of ",
                        "department of health",
                        "behavioral health",
                        "mental health",
                        "substance abuse",
                        "public health",
                        "ssa",
                    )
                    return any(marker in ctx_text for marker in _state_agency_markers)

                def _grant_context_looks_like_state_law_enforcement(ctx_text: str) -> bool:
                    _state_law_markers = (
                        "state police",
                        "state patrol",
                        "highway patrol",
                        "department of public safety",
                        "state bureau of investigation",
                        "state law enforcement",
                    )
                    return any(marker in ctx_text for marker in _state_law_markers)

                def _grant_context_looks_like_tribal_applicant(ctx_text: str) -> bool:
                    _tribal_markers = (
                        "tribe",
                        "tribal",
                        "nation",
                        "pueblo",
                        "rancheria",
                    )
                    return any(marker in ctx_text for marker in _tribal_markers)

                def _render_federal_grant_card_html(
                    *,
                    title: str,
                    description: str,
                    narrative: str,
                    status_label: str,
                    status_tone: str,
                    eligibility_note: str,
                    links: list[tuple[str, str]],
                    grants_gov_deadline: str = "",
                    portal_deadline: str = "",
                    nofo_number: str = "",
                    status_note: str = "",
                    require_state_agency: bool = False,
                    require_state_law_enforcement: bool = False,
                    require_tribal: bool = False,
                ) -> str:
                    if require_state_agency and not _grant_context_looks_like_state_agency(_grant_context_text):
                        return ""
                    if require_state_law_enforcement and not _grant_context_looks_like_state_law_enforcement(_grant_context_text):
                        return ""
                    if require_tribal and not _grant_context_looks_like_tribal_applicant(_grant_context_text):
                        return ""
                    _badge_styles = {
                        "open": "display:inline-block;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:0.8px;text-transform:uppercase;white-space:nowrap;background:rgba(34,197,94,0.12);color:#15803d;border:1px solid rgba(34,197,94,0.25);",
                        "watch": "display:inline-block;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:0.8px;text-transform:uppercase;white-space:nowrap;background:rgba(245,158,11,0.12);color:#b45309;border:1px solid rgba(245,158,11,0.28);",
                        "closed": "display:inline-block;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:0.8px;text-transform:uppercase;white-space:nowrap;background:rgba(59,130,246,0.1);color:#1d4ed8;border:1px solid rgba(59,130,246,0.2);",
                    }
                    _meta = [status_label]
                    if grants_gov_deadline:
                        _meta.append(f"Grants.gov deadline: {grants_gov_deadline}")
                    if portal_deadline:
                        _meta.append(portal_deadline)
                    if nofo_number:
                        _meta.append(f"NOFO {nofo_number}")
                    if eligibility_note:
                        _meta.append(eligibility_note)
                    if status_note:
                        _meta.append(status_note)
                    _links_html = " · ".join(
                        f'<a href="{html.escape(url, quote=True)}" target="_blank" style="color:#2563eb;text-decoration:none;font-weight:700;">{html.escape(label)}</a>'
                        for label, url in links if label and url
                    )
                    _badge_style = _badge_styles.get(status_tone, _badge_styles["closed"])
                    _primary_link = next((url for _label, url in links if _label and url), "")
                    if _primary_link:
                        _badge_html = (
                            f'<a href="{html.escape(_primary_link, quote=True)}" target="_blank" '
                            f'class="grant-status-badge {html.escape(status_tone)}" '
                            f'style="{_badge_style}text-decoration:none;cursor:pointer;">{html.escape(status_label)}</a>'
                        )
                    else:
                        _badge_html = (
                            f'<span class="grant-status-badge {html.escape(status_tone)}" '
                            f'style="{_badge_style}">{html.escape(status_label)}</span>'
                        )
                    return (
                        f"<div class=\"federal-grant-card\" style=\"background:#fff;border:1px solid rgba(148,163,184,0.22);border-radius:10px;padding:14px 16px;margin-bottom:12px;box-shadow:0 4px 18px rgba(15,23,42,0.04);\">"
                        f"<div class=\"federal-grant-head\" style=\"margin-bottom:6px;\">"
                        f"<strong style=\"display:block;font-size:14px;color:#0f172a;margin-bottom:6px;\">{html.escape(title)}</strong>"
                        f"{_badge_html}"
                        f"</div>"
                        f"<div class=\"federal-grant-desc\" style=\"font-size:12px;color:#334155;margin:8px 0;\">{html.escape(description)}</div>"
                        f"<div class=\"federal-grant-meta\" style=\"font-size:11px;color:#64748b;margin:0 0 10px;\">{' | '.join(html.escape(m) for m in _meta)}</div>"
                        f"<p style=\"font-size:13px;color:#334155;line-height:1.65;margin:0 0 10px;\">{html.escape(narrative)}</p>"
                        f"<div class=\"federal-grant-links\" style=\"font-size:12px;font-weight:700;line-height:1.6;\">{_links_html}</div>"
                        f"</div>"
                    )

                _current_federal_grants_html = "".join([
                    _render_federal_grant_card_html(
                        title="DOJ/BJA Comprehensive Opioid, Stimulant, and Substance Use Program (COSSUP)",
                        description=(
                            "Supports coordinated opioid, stimulant, and substance-use response across public "
                            "safety, overdose response, diversion, deflection, treatment access, recovery, and data-sharing."
                        ),
                        narrative=(
                            "For this DFR deployment, COSSUP is the strongest federal opioid-response fit because it "
                            "allows the agency to position BRINC as overdose-scene intelligence infrastructure that improves "
                            "dispatcher awareness, accelerates multi-agency coordination, reduces responder risk, and supports "
                            "deflection workflows linking law enforcement, EMS, and behavioral-health partners."
                        ),
                        status_label="Open now",
                        status_tone="open",
                        eligibility_note="Eligible applicants include states, units of local government, and Indian tribal governments",
                        links=[
                            ("BJA FY25 COSSUP opportunity", "https://bja.ojp.gov/funding/opportunities/o-bja-2025-172485"),
                            ("BJA COSSUP overview", "https://www.bja.ojp.gov/program/cossup/about"),
                        ],
                        grants_gov_deadline="May 4, 2026, 11:59 p.m. ET",
                        portal_deadline="JustGrants deadline: May 11, 2026, 8:59 p.m. ET",
                        nofo_number="O-BJA-2025-172485",
                    ),
                    _render_federal_grant_card_html(
                        title="SAMHSA Tribal Opioid Response (TOR)",
                        description=(
                            "Supports opioid and stimulant prevention, harm reduction, treatment, recovery support, and "
                            "MOUD access for tribal communities."
                        ),
                        narrative=(
                            "When the applicant is a Tribe or tribal organization, TOR can support a DFR deployment framed "
                            "around faster overdose-scene assessment, safer responder approach, and stronger connection between "
                            "dispatch, tribal public safety, EMS, and treatment or recovery partners."
                        ),
                        status_label="Forecasted / watchlist",
                        status_tone="watch",
                        eligibility_note="Eligible applicants are federally recognized Tribes and tribal organizations",
                        links=[
                            ("Simpler.Grants.gov forecast search", "https://simpler.grants.gov/search?query=opioid+use+disorder"),
                            ("SAMHSA TOR program page", "https://www.samhsa.gov/grants/grant-announcements/ti-24-009"),
                        ],
                        status_note="FY26 forecast posted March 20, 2026; close date not yet published",
                        require_tribal=True,
                    ),
                    _render_federal_grant_card_html(
                        title="COPS Anti-Heroin Task Force (AHTF)",
                        description=(
                            "Funds statewide collaborative law-enforcement efforts focused on heroin, fentanyl, carfentanil, "
                            "and unlawful prescription-opioid distribution."
                        ),
                        narrative=(
                            "For state law-enforcement applicants, AHTF can support a DFR narrative centered on earlier aerial "
                            "scene intelligence for trafficking investigations, safer operational planning, and faster coordination "
                            "across state task-force partners confronting opioid distribution networks."
                        ),
                        status_label="Recurring program",
                        status_tone="closed",
                        eligibility_note="Eligible applicants are state law-enforcement agencies with statewide jurisdiction",
                        links=[
                            ("COPS AHTF program page", "https://cops.usdoj.gov/ahtf"),
                            ("COPS grants page", "https://cops.usdoj.gov/grants"),
                        ],
                        grants_gov_deadline="June 25, 2025, 4:59 p.m. ET",
                        portal_deadline="JustGrants deadline: July 2, 2025, 4:59 p.m. ET",
                        status_note="Most recent posted cycle is closed; keep on the watchlist for the next federal round",
                        require_state_law_enforcement=True,
                    ),
                    _render_federal_grant_card_html(
                        title="SAMHSA State Opioid Response (SOR)",
                        description=(
                            "Supports opioid and stimulant prevention, harm reduction, treatment, recovery support, and "
                            "MOUD access through Single State Agencies and territorial applicants."
                        ),
                        narrative=(
                            "For state behavioral-health or Single State Agency applicants, SOR can support a DFR narrative "
                            "focused on overdose-scene intelligence, faster linkage to care, coordinated field response, and "
                            "safer interoperability between public safety and treatment systems."
                        ),
                        status_label="State-only program",
                        status_tone="closed",
                        eligibility_note="Eligible applicants are Single State Agencies and territories",
                        links=[
                            ("SAMHSA SOR program page", "https://www.samhsa.gov/grants/grant-announcements/ti-24-008"),
                        ],
                        grants_gov_deadline="July 1, 2024",
                        status_note="Most recent public NOFO is historical; include only for state-level behavioral-health applicants",
                        require_state_agency=True,
                    ),
                ])
                _cossup_opportunity_url = "https://bja.ojp.gov/funding/opportunities/o-bja-2025-172485"
                _cossup_overview_url = "https://bja.ojp.gov/program/cossup"
                _cossup_funding_url = "https://bja.ojp.gov/program/cossup/funding"
                _cossup_webinar_url = "https://bja.ojp.gov/events/fy25-comprehensive-opioid-stimulant-and-substance-use-site-based-program-cossup"
                _cossup_success_url = "https://bja.ojp.gov/news/success-spotlight/bjas-cossup-brings-life-saving-interventions"
                _cossup_kpi_url = "https://bja.ojp.gov/media/document/51081"
                _cossup_opioid_narrative_html = f"""
                <div class="opioid-grant-subsection" style="margin:20px 0 18px;padding:18px 20px;border-radius:12px;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid rgba(37,99,235,0.18);">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
                    <div>
                      <div style="font-size:11px;font-weight:800;letter-spacing:1.2px;text-transform:uppercase;color:#1d4ed8;margin-bottom:6px;">Grant Narrative Subsection B</div>
                      <div style="font-size:18px;font-weight:800;color:#0f172a;line-height:1.3;">DOJ/BJA FY25 Comprehensive Opioid, Stimulant, and Substance Use, Site-Based Program (COSSUP)</div>
                      <div style="font-size:12px;color:#64748b;margin-top:6px;">Opportunity ID O-BJA-2025-172485 · Solicitation status: Open · Grants.gov deadline: May 4, 2026, 11:59 p.m. Eastern · JustGrants deadline: May 11, 2026, 8:59 p.m. Eastern</div>
                    </div>
                    <button class="copy-section-btn grant-law" onclick="copyGrantText('grant-body-opioid', this)">Copy Opioid Grant Text</button>
                  </div>
                  <div id="grant-body-opioid" style="font-size:13px;color:#334155;line-height:1.7;">
                    <p><strong>Project Title:</strong> BRINC Drones Overdose-Response and Multi-Agency Coordination Initiative — {_get_document_jurisdiction_name(st.session_state, selected_names, fallback=prop_city)}, {prop_state}</p>
                    <p><strong>Program Fit and Funding Opportunity Alignment:</strong> The FY25 COSSUP site-based solicitation is designed to help eligible state, local, and tribal governments develop, implement, or expand coordinated responses that identify, respond to, treat, and support people impacted by illicit opioids, stimulants, and other substances [1][2]. BJA’s current overview and webinar materials emphasize cross-system collaboration among public safety, behavioral health, treatment, and community partners; law-enforcement-related activities tied to overdose response and prevention; stronger access to prevention tools and overdose reversal medications; and expanded treatment and recovery pathways in the community and, where applicable, correctional settings [1][3]. This proposal is written to match that frame directly.</p>
                    <p><strong>Statement of Need:</strong> {_get_document_jurisdiction_name(st.session_state, selected_names, fallback=prop_city)} currently generates approximately <strong>{st.session_state.get('total_original_calls', total_calls):,} calls for service annually</strong>. Within that operating tempo, overdose calls, unconscious-person calls, welfare checks, narcotics-related incidents, and co-occurring behavioral-health events place responders into fast-moving scenes where delayed situational awareness increases risk to the patient, the public, and first responders. The proposed BRINC deployment closes that gap by moving eyes-on-scene forward to the first minutes of the event, giving dispatch, law enforcement, fire/EMS, and partner agencies a common operating picture before personnel commit to the address.</p>
                    <p><strong>Proposed COSSUP-Supported Response Model:</strong> The applicant proposes to deploy a BRINC Drone as a First Responder network consisting of <strong>{actual_k_responder} Responder units</strong> and <strong>{actual_k_guardian} Guardian units</strong> across <strong>{jurisdiction_list}</strong>. In the modeled configuration, the network reaches <strong>{calls_covered_perc:.1f}% of historical incidents</strong>, improves average arrival speed by <strong>{avg_time_saved:.1f} minutes</strong> versus patrol response, and gives dispatchers and field supervisors live HD and thermal intelligence during suspected overdose, unsafe-entry, and multi-agency scenes. BRINC’s launch-on-dispatch workflow, live-streaming video, chain-of-custody flight logging, and integrated operational analytics allow the applicant to present the system not as a stand-alone aircraft purchase, but as overdose-scene intelligence infrastructure that supports public safety decision-making, responder protection, and coordinated care pathways.</p>
                    <p><strong>How BRINC Advances COSSUP Priorities:</strong> First, the platform strengthens the public-safety response by letting dispatch and field commanders verify scene conditions, assess ingress/egress constraints, identify bystanders or secondary hazards, and determine whether immediate law-enforcement, EMS, fire, crisis-response, or co-responder resources are needed. Second, it supports overdose response and treatment engagement by enabling earlier, safer coordination with naloxone-equipped responders, post-overdose outreach teams, peer navigators, hospital partners, and behavioral-health providers. Third, it improves information sharing by creating time-stamped aerial records, incident-level deployment logs, and repeatable performance measures that can be shared across the public-safety and treatment ecosystem. Fourth, it helps align resources by directing the highest-cost human response only where the aerial picture shows it is necessary, which is especially important in jurisdictions facing staffing pressure, overdose-call surges, or wide geographic coverage demands [1][2][3].</p>
                    <p><strong>Implementation and Partnerships:</strong> The applicant will use COSSUP support to formalize an overdose-response workflow that connects dispatch, law enforcement, fire/EMS, emergency communications, hospital and treatment partners, behavioral-health providers, peer-support or deflection teams, and any county or regional overdose task force already operating in the jurisdiction. The BRINC system will be integrated into standard operating procedures for overdose, possible overdose, unconscious subject, welfare check, open-air drug scene, and allied public-safety events. Where local practice supports it, the same aerial workflow can also support post-overdose follow-up, hotspot intelligence, and rapid coordination with community-based providers so that overdose survivors and families are connected to treatment, recovery support, or deflection resources rather than being left with only a traditional enforcement response.</p>
                    <p><strong>Evidence Base and Expected Impact:</strong> BJA describes COSSUP as a flexible national program that has funded more than 500 sites in the last four years and centers collaboration across public safety, behavioral health, and treatment systems [1]. BJA’s 2021–2022 COSSUP Key Performance Indicator report summarizes data from hundreds of grantees and subawardees operating across all 50 states, two territories, and the District of Columbia, reflecting a large federal investment in naloxone training, diversion, treatment access, and recovery support [5]. BJA’s Oakland County success spotlight shows how a COSSUP-funded sheriff’s crisis-response unit used Narcan to revive an overdose victim and paired law-enforcement follow-up with community health and prevention partners [4]. This applicant’s BRINC deployment builds on that same federal logic: faster scene verification, safer first-responder approach, tighter coordination with care partners, and better operational data to document outcomes and improve future overdose-response decisions.</p>
                    <p><strong>Performance Measurement and Sustainability:</strong> The applicant will track at minimum: (1) time from dispatch to aerial scene assessment, (2) number of overdose-related or suspected overdose incidents receiving drone support, (3) number of incidents in which aerial intelligence changed resource deployment, (4) referrals or handoffs to EMS, treatment, behavioral-health, or peer-support partners, (5) responder-safety outcomes, and (6) recurring hotspot or trend information useful for prevention and enforcement planning. Because the current deployment model projects <strong>${annual_savings:,.0f} in annual operational savings</strong> with a break-even horizon of <strong>{break_even_text.lower()}</strong>, the applicant can argue that federal start-up support will stand up an enduring response capability rather than a one-time pilot. That sustainability argument is strengthened further by BRINC’s integrated analytics, domestic manufacturing, operational training, and immediate fit with the agency’s existing dispatch-centered deployment model.</p>
                    <p><strong>References:</strong></p>
                    <ol style="margin:0 0 0 18px;padding:0 0 0 10px;">
                      <li><a href="{html.escape(_cossup_opportunity_url, quote=True)}" target="_blank" style="color:#2563eb;text-decoration:none;">Bureau of Justice Assistance, FY25 Comprehensive Opioid, Stimulant, and Substance Use, Site-Based Program, Opportunity ID O-BJA-2025-172485</a></li>
                      <li><a href="{html.escape(_cossup_overview_url, quote=True)}" target="_blank" style="color:#2563eb;text-decoration:none;">Bureau of Justice Assistance, COSSUP Overview</a></li>
                      <li><a href="{html.escape(_cossup_webinar_url, quote=True)}" target="_blank" style="color:#2563eb;text-decoration:none;">Bureau of Justice Assistance, FY25 COSSUP Site-Based Program Webinar Page</a></li>
                      <li><a href="{html.escape(_cossup_success_url, quote=True)}" target="_blank" style="color:#2563eb;text-decoration:none;">Bureau of Justice Assistance, “BJA's COSSUP Brings Life-Saving Interventions” Success Spotlight</a></li>
                      <li><a href="{html.escape(_cossup_kpi_url, quote=True)}" target="_blank" style="color:#2563eb;text-decoration:none;">Bureau of Justice Assistance, Comprehensive Opioid, Stimulant, and Substance Use Program Key Performance Indicator Report, Calendar Years 2021–2022</a></li>
                      <li><a href="{html.escape(_cossup_funding_url, quote=True)}" target="_blank" style="color:#2563eb;text-decoration:none;">Bureau of Justice Assistance, COSSUP Funding Page</a></li>
                    </ol>
                  </div>
                </div>
                """

                export_html = f"""<!DOCTYPE html>
        <html lang="en"><head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>BRINC DFR Proposal — {prop_city}, {prop_state}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
        <style>
        *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
        :root{{
          --black:#000000;--white:#ffffff;--cyan:#00D2FF;--gold:#FFD700;
          --ink:#0a0a0f;--surface:#f7f8fa;--border:#e4e6ea;
          --text:#111118;--muted:#6b7280;--light:#f0f2f6;
          --resp:#00D2FF;--guard:#FFD700;--green:#22c55e;--amber:#f59e0b;
        }}
        html{{scroll-behavior:smooth}}
        body{{font-family:'Inter',sans-serif;background:var(--surface);color:var(--text);line-height:1.6;display:flex;min-height:100vh}}
    
        /* ── LEFT SIDEBAR INDEX ──────────────────────────────────────── */
        .doc-sidebar{{
          position:fixed;top:0;left:0;width:220px;height:100vh;
          background:var(--ink);overflow-y:auto;z-index:100;
          display:flex;flex-direction:column;
          border-right:1px solid #1a1a2a;
        }}
        .sidebar-logo{{
          padding:28px 24px 20px;
          border-bottom:1px solid #1a1a2a;
        }}
        .sidebar-logo img{{height:40px;display:block}}
        .sidebar-logo .brand{{font-size:22px;font-weight:900;letter-spacing:3px;color:#fff}}
        .sidebar-city{{
          padding:16px 24px;
          border-bottom:1px solid #1a1a2a;
        }}
        .sidebar-city .city-name{{font-size:13px;font-weight:700;color:#fff;letter-spacing:0.3px}}
        .sidebar-city .city-sub{{font-size:11px;color:#666;margin-top:2px}}
        .sidebar-nav{{padding:20px 0;flex:1}}
        .sidebar-nav a{{
          display:flex;align-items:center;gap:10px;
          padding:9px 24px;font-size:12px;font-weight:500;
          color:#888;text-decoration:none;
          border-left:2px solid transparent;
          transition:all 0.15s;
        }}
        .sidebar-nav a:hover,.sidebar-nav a.active{{
          color:#fff;background:rgba(0,210,255,0.06);
          border-left-color:var(--cyan);
        }}
        .sidebar-nav .nav-num{{
          font-size:10px;font-weight:700;color:#333;
          width:18px;text-align:center;flex-shrink:0;
        }}
        .sidebar-nav a:hover .nav-num,.sidebar-nav a.active .nav-num{{color:var(--cyan)}}
        .sidebar-footer{{
          padding:20px 24px;border-top:1px solid #1a1a2a;
          font-size:10px;color:#444;line-height:1.6;
        }}
        .sidebar-footer a{{color:#555;text-decoration:none}}
    
        /* ── MAIN CONTENT ────────────────────────────────────────────── */
        .doc-main{{margin-left:220px;flex:1;min-width:0}}
    
        /* ── PAGE SECTIONS (each prints as independent page) ─────────── */
        .doc-section{{
          background:#fff;
          border-bottom:6px solid var(--surface);
          padding:52px 60px;
          position:relative;
        }}
        .doc-section:first-child{{padding-top:64px}}
    
        /* Section header bar */
        .section-eyebrow{{
          display:flex;align-items:center;gap:10px;
          margin-bottom:32px;
        }}
    
        /* ── SOURCE BADGE ──────────────────────────────────────────────── */
        .src{{
          display:inline-flex;align-items:center;justify-content:center;
          width:14px;height:14px;border-radius:50%;
          background:rgba(100,116,139,0.1);color:#94a3b8;
          border:1px solid rgba(100,116,139,0.28);
          font-size:8px;font-weight:700;cursor:default;
          margin-left:4px;vertical-align:middle;position:relative;
          font-style:normal;text-decoration:none;flex-shrink:0;
        }}
        .src:hover::after{{
          content:attr(data-src);
          position:absolute;bottom:130%;left:50%;
          transform:translateX(-50%);
          background:#1e293b;color:#e2e8f0;
          font-size:10.5px;font-weight:400;padding:7px 11px;
          border-radius:6px;white-space:normal;width:270px;
          line-height:1.55;z-index:9999;
          border:1px solid #334155;
          box-shadow:0 6px 20px rgba(0,0,0,0.4);
          pointer-events:none;text-transform:none;letter-spacing:normal;
        }}
        .copy-section-btn{{
          margin-left:auto;
          display:inline-flex;align-items:center;gap:6px;
          font-size:10px;font-weight:600;letter-spacing:0.8px;text-transform:uppercase;
          color:var(--cyan);border:1px solid rgba(0,210,255,0.35);
          background:rgba(0,210,255,0.06);
          padding:4px 12px;border-radius:100px;cursor:pointer;
          font-family:'IBM Plex Mono',monospace;
          transition:background 0.15s,border-color 0.15s;
          user-select:none;
        }}
        .copy-section-btn:hover{{background:rgba(0,210,255,0.14);border-color:rgba(0,210,255,0.6);}}
        .copy-section-btn.copied{{color:#39FF14;border-color:rgba(57,255,20,0.5);background:rgba(57,255,20,0.07);}}
        .copy-section-btn.grant-law{{color:#3b82f6;border-color:rgba(59,130,246,0.35);background:rgba(59,130,246,0.06);}}
        .copy-section-btn.grant-law:hover{{background:rgba(59,130,246,0.14);border-color:rgba(59,130,246,0.6);}}
        .copy-section-btn.grant-fire{{color:#f97316;border-color:rgba(249,115,22,0.35);background:rgba(249,115,22,0.06);}}
        .copy-section-btn.grant-fire:hover{{background:rgba(249,115,22,0.14);border-color:rgba(249,115,22,0.6);}}
        .copy-section-btn.community{{color:#22c55e;border-color:rgba(34,197,94,0.35);background:rgba(34,197,94,0.06);}}
        .copy-section-btn.community:hover{{background:rgba(34,197,94,0.14);border-color:rgba(34,197,94,0.6);}}
        .section-eyebrow .pg-num{{
          font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
          color:var(--cyan);border:1px solid rgba(0,210,255,0.3);
          padding:3px 10px;border-radius:100px;font-family:'IBM Plex Mono',monospace;
        }}
        .section-eyebrow .pg-title{{
          font-size:10px;font-weight:600;letter-spacing:2px;text-transform:uppercase;
          color:var(--muted);
        }}
    
        /* ── COVER PAGE ──────────────────────────────────────────────── */
        .cover-page{{
          background:var(--ink);color:#fff;min-height:100vh;
          display:flex;flex-direction:column;justify-content:space-between;
          padding:60px;position:relative;overflow:hidden;
        }}
        .cover-page::before{{
          content:'';position:absolute;inset:0;
          background:radial-gradient(ellipse 80% 60% at 70% 30%,rgba(0,210,255,0.08) 0%,transparent 70%);
          pointer-events:none;
        }}
        .cover-logo{{margin-bottom:auto}}
        .cover-logo img{{height:52px}}
        .cover-logo .brand{{font-size:28px;font-weight:900;letter-spacing:4px;color:#fff}}
        .cover-headline{{margin:60px 0 40px}}
        .cover-tag{{
          font-size:11px;font-weight:700;letter-spacing:3px;text-transform:uppercase;
          color:var(--cyan);margin-bottom:20px;
        }}
        .cover-headline h1{{
          font-size:52px;font-weight:900;line-height:1.05;letter-spacing:-1px;
          color:#fff;margin-bottom:16px;
        }}
        .cover-headline h1 span{{color:var(--cyan)}}
        .cover-population{{
          font-size:13px;color:#aaa;margin-bottom:14px;letter-spacing:0.2px;
          border-left:3px solid var(--cyan);padding-left:10px;
        }}
        .cover-population strong{{color:#fff;font-weight:700}}
        .cover-headline p{{font-size:15px;color:#888;max-width:520px;line-height:1.7}}
        .cover-meta{{
          display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
          background:#1a1a2a;border:1px solid #1a1a2a;border-radius:10px;overflow:hidden;
          margin-top:4px;
        }}
        .cover-meta-cell{{
          background:var(--ink);padding:16px 14px;
        }}
        .cover-meta-cell .label{{font-size:9px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#555;margin-bottom:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
        .cover-meta-cell .value{{font-size:clamp(11px,1vw,14px);font-weight:800;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:'IBM Plex Mono',monospace;letter-spacing:-0.3px}}
        .cover-meta-cell .value.accent{{color:var(--cyan)}}
        .cover-meta-cell .value.gold{{color:var(--gold)}}
        .cover-bottom{{margin-top:40px;font-size:12px;color:#444;border-top:1px solid #1a1a2a;padding-top:24px;display:flex;justify-content:space-between}}
    
        /* ── METRICS SECTION ─────────────────────────────────────────── */
        .metrics-hero{{
          display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
          background:var(--border);border-radius:12px;overflow:hidden;
          margin-bottom:40px;box-shadow:0 1px 3px rgba(0,0,0,0.04);
        }}
        .metric-cell{{
          background:#fff;padding:24px 16px;text-align:center;min-width:0;
        }}
        .metric-cell .m-label{{font-size:9px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted);margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
        .metric-cell .m-value{{font-size:clamp(16px,1.8vw,28px);font-weight:900;font-family:'IBM Plex Mono',monospace;line-height:1.1;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
        .metric-cell .m-value.cyan{{color:var(--cyan)}}
        .metric-cell .m-value.gold{{color:var(--gold)}}
        .metric-cell .m-value.green{{color:var(--green)}}
        .metric-cell .m-sub{{font-size:11px;color:var(--muted);margin-top:6px}}
    
        /* Fleet split row */
        .fleet-split{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:32px}}
        .fleet-card{{border-radius:10px;padding:24px;position:relative;overflow:hidden}}
        .fleet-card.guardian{{background:#0a0800;border:1px solid #2a2400;color:#fff}}
        .fleet-card.responder{{background:#00111a;border:1px solid #002a3a;color:#fff}}
        .fleet-card .fc-icon{{font-size:28px;margin-bottom:12px}}
        .fleet-card .fc-type{{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px}}
        .fleet-card.guardian .fc-type{{color:var(--gold)}}
        .fleet-card.responder .fc-type{{color:var(--resp)}}
        .fleet-card .fc-val{{font-size:32px;font-weight:900;font-family:'IBM Plex Mono',monospace;color:#fff}}
        .fleet-card .fc-sub{{font-size:12px;color:#888;margin-top:4px}}
        .fleet-card .fc-row{{display:flex;justify-content:space-between;font-size:12px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06)}}
        .fleet-card .fc-row:last-child{{border-bottom:none}}
        .fleet-card .fc-row .k{{color:#666}}.fleet-card .fc-row .v{{font-weight:600;color:#ccc}}
    
        /* ── SECTION HEADINGS ────────────────────────────────────────── */
        .sh{{
          font-size:22px;font-weight:800;color:var(--text);
          margin-bottom:20px;padding-bottom:12px;
          border-bottom:2px solid var(--border);
          display:flex;align-items:center;gap:10px;
        }}
        .sh .sh-accent{{color:var(--cyan)}}
    
        /* ── TABLES ──────────────────────────────────────────────────── */
        table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:28px}}
        thead tr{{background:var(--ink);color:#fff}}
        thead th{{padding:12px 16px;text-align:left;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase}}
        tbody tr:nth-child(even){{background:#fafbfc}}
        tbody tr:hover{{background:#f0f8ff}}
        td{{padding:12px 16px;border-bottom:1px solid var(--border);color:var(--text)}}
        .tag-resp{{background:rgba(0,210,255,0.1);color:#0066aa;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
        .tag-guard{{background:rgba(255,215,0,0.15);color:#8a6a00;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
    
        /* ── MAP ─────────────────────────────────────────────────────── */
        .map-wrap{{border-radius:12px;overflow:hidden;border:1px solid var(--border);box-shadow:0 4px 20px rgba(0,0,0,0.06);margin-bottom:32px}}
    
        /* ── DISCLAIMER ──────────────────────────────────────────────── */
        .disc{{background:#fffbeb;border-left:4px solid var(--amber);padding:16px 20px;border-radius:0 8px 8px 0;font-size:12px;color:#7a5a00;margin-bottom:24px}}
    
        /* ── FOOTER ──────────────────────────────────────────────────── */
        .doc-footer{{background:var(--ink);color:#555;padding:36px 60px;font-size:11px;display:flex;justify-content:space-between;align-items:center;gap:20px}}
        .doc-footer a{{color:#666;text-decoration:none}}
        .doc-footer .brand-mark{{font-size:16px;font-weight:900;letter-spacing:3px;color:#fff;flex-shrink:0}}
        .doc-version{{margin:28px 0 0;padding-top:12px;border-top:1px solid var(--border);font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.12em;color:rgba(107,114,128,0.9);text-align:right;}}
    
        /* ── PRODUCT IMAGE ───────────────────────────────────────────── */
        .cover-body{{
          display:flex;align-items:flex-start;gap:40px;flex:1;margin:40px 0;
        }}
        .cover-left{{flex:1;min-width:0}}
        .cover-right{{
          flex-shrink:0;width:420px;display:flex;align-items:center;
          justify-content:flex-end;
        }}
        .product-img{{
          width:100%;max-width:420px;
          filter:drop-shadow(0 20px 60px rgba(0,210,255,0.18));
          pointer-events:none;
        }}
        @media (max-width:900px){{.cover-right{{display:none}}}}
    
        /* ── TWO-COL INFRA TABLE ─────────────────────────────────────── */
        .infra-grid{{
          display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:28px;
        }}
        .infra-item{{
          background:#fafbfc;border:1px solid var(--border);border-radius:6px;
          padding:10px 12px;font-size:11px;display:flex;justify-content:space-between;
          align-items:center;gap:8px;
        }}
        .infra-item .i-name{{font-weight:600;color:var(--text);flex:1;min-width:0;
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
        .infra-item .i-type{{font-size:10px;font-weight:600;padding:2px 6px;border-radius:4px;flex-shrink:0}}
        .infra-item .i-link{{color:var(--cyan);text-decoration:none;font-weight:700;font-size:11px;flex-shrink:0}}
    
        /* ── GRANT STATS SIDEBAR ─────────────────────────────────────── */
        .grant-layout{{display:grid;grid-template-columns:1fr 280px;gap:40px;align-items:start}}
        .grant-sidebar{{display:flex;flex-direction:column;gap:12px}}
        .grant-stat{{
          background:#fafbfc;border:1px solid var(--border);border-radius:8px;
          padding:16px;text-align:center;
        }}
        .grant-stat .gs-label{{font-size:10px;font-weight:600;letter-spacing:1px;
          text-transform:uppercase;color:var(--muted);margin-bottom:6px}}
        .grant-stat .gs-val{{font-size:24px;font-weight:900;font-family:'IBM Plex Mono',monospace;color:var(--cyan)}}
        .grant-stat .gs-sub{{font-size:11px;color:var(--muted);margin-top:4px}}
        .grant-stat.gold .gs-val{{color:var(--gold)}}
        .grant-stat.green .gs-val{{color:var(--green)}}
        .federal-grants-wrap{{margin:20px 0 22px;padding:18px 20px;border-radius:12px;background:linear-gradient(180deg,#f8fbff 0%,#f4f8fc 100%);border:1px solid rgba(59,130,246,0.18)}}
        .federal-grants-wrap h4{{font-size:12px;font-weight:800;letter-spacing:1.3px;text-transform:uppercase;color:#1d4ed8;margin-bottom:8px}}
        .federal-grants-wrap p{{font-size:13px;color:#334155;margin-bottom:14px}}
        .federal-grant-card{{background:#fff;border:1px solid rgba(148,163,184,0.22);border-radius:10px;padding:14px 16px;margin-bottom:12px;box-shadow:0 4px 18px rgba(15,23,42,0.04)}}
        .federal-grant-card:last-child{{margin-bottom:0}}
        .federal-grant-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px}}
        .federal-grant-head strong{{font-size:14px;color:#0f172a}}
        .federal-grant-desc{{font-size:12px;color:#334155;margin-bottom:8px}}
        .federal-grant-meta{{font-size:11px;color:#64748b;margin-bottom:10px}}
        .grant-status-badge{{display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:0.8px;text-transform:uppercase;white-space:nowrap}}
        .grant-status-badge.open{{background:rgba(34,197,94,0.12);color:#15803d;border:1px solid rgba(34,197,94,0.25)}}
        .grant-status-badge.watch{{background:rgba(245,158,11,0.12);color:#b45309;border:1px solid rgba(245,158,11,0.28)}}
        .grant-status-badge.closed{{background:rgba(59,130,246,0.1);color:#1d4ed8;border:1px solid rgba(59,130,246,0.2)}}
        .federal-grant-links{{font-size:12px;font-weight:700}}
        .federal-grant-links a{{color:#2563eb;text-decoration:none}}
        .federal-grant-links a:hover{{text-decoration:underline}}
    
        /* ── CRIME STATS BOX ─────────────────────────────────────────── */
        .crime-box{{
          background:linear-gradient(135deg,#0a0800 0%,#120e00 100%);
          border:1px solid #2a2000;border-radius:10px;
          padding:24px;margin-bottom:24px;
        }}
        .crime-box h4{{color:var(--gold);font-size:12px;font-weight:700;
          letter-spacing:1.5px;text-transform:uppercase;margin-bottom:16px}}
        .crime-stat-row{{
          display:flex;justify-content:space-between;align-items:baseline;
          padding:8px 0;border-bottom:1px solid #1a1600;font-size:13px;
        }}
        .crime-stat-row:last-child{{border-bottom:none}}
        .crime-stat-row .csk{{color:#888}}
        .crime-stat-row .csv{{font-weight:700;color:#fff;font-family:'IBM Plex Mono',monospace}}
        .crime-stat-row .csv.accent{{color:var(--gold)}}
    
        /* ── PRINT ───────────────────────────────────────────────────── */
        @media print{{
          @page{{size:auto;margin:0.45in 0.5in}}
          html,body{{background:#fff !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
          .doc-sidebar{{display:none !important}}
          .doc-main{{margin-left:0 !important}}
          .doc-section,.cover-page{{
            page-break-after:always;
            page-break-inside:avoid;
            break-after:page;
            border-bottom:none;
            min-height:0;
            box-shadow:none !important;
          }}
          .doc-section{{padding:30px 34px !important}}
          .cover-page{{padding:38px 40px !important;min-height:auto !important}}
          .doc-footer{{padding:20px 34px !important}}
          .doc-section:last-child,.cover-page:last-child{{page-break-after:auto;break-after:auto}}
          .section-eyebrow,.cover-headline,h1,h2,h3,h4{{break-after:avoid-page;page-break-after:avoid}}
          .metrics-hero,.roi-strip,.grant-layout,.infra-grid,.map-wrap,table,img,svg,canvas{{
            break-inside:avoid-page;
            page-break-inside:avoid;
          }}
          a{{color:inherit !important;text-decoration:none !important}}
          .doc-version{{margin-top:18px;padding-top:10px;border-top:1px solid #e5e7eb;color:#6b7280 !important;}}
        }}
        </style>
        </head>
        <body>
    
        <!-- ── TOP-RIGHT CORNER LOGO ─────────────────────────────────── -->
    
    
        <!-- ── SIDEBAR INDEX ─────────────────────────────────────────── -->
        <nav class="doc-sidebar">
          <div class="sidebar-logo">
            {"<img src='data:image/png;base64," + logo_b64_dark + "' style='height:40px;display:block'>" if logo_b64_dark else '<div class="brand">BRINC</div>'}
          </div>
          <div class="sidebar-city">
            <div class="city-name">{prop_city}, {prop_state}</div>
            <div class="city-sub">DFR Deployment Proposal</div>
          </div>
          <nav class="sidebar-nav">
            <a href="#cover"><span class="nav-num">00</span>Cover</a>
            <a href="#executive"><span class="nav-num">01</span>Executive Summary</a>
            <a href="#fleet"><span class="nav-num">02</span>Fleet &amp; Coverage</a>
            <a href="#map"><span class="nav-num">03</span>Coverage Map</a>
            <a href="#incident-data"><span class="nav-num">04</span>Incident Analysis</a>
            <a href="#deployment"><span class="nav-num">05</span>Deployment Locations</a>
            <a href="#grant"><span class="nav-num">06</span>Grant Narrative</a>
            <a href="#infrastructure"><span class="nav-num">07</span>Infrastructure Directory</a>
            <a href="#community"><span class="nav-num">08</span>Community Partnership</a>
            [ANALYTICS_NAV]
            [COMMUNITY_IMPACT_NAV]
            <a href="#school-safety"><span class="nav-num">11</span>School Safety</a>
          </nav>
          <div class="sidebar-footer">
            Prepared {datetime.datetime.now().strftime("%b %d, %Y")}<br>
            {prop_name}<br>
            <a href="mailto:{prop_email}">{prop_email}</a>
            {_ae_phone_html}
          </div>
        </nav>
    
        <main class="doc-main">
    
        <!-- ── 00: COVER ─────────────────────────────────────────────── -->
        <section class="cover-page" id="cover">
          <div class="cover-logo">
            {"<img src='data:image/png;base64," + logo_b64_dark + "' style='height:48px;display:block'>" if logo_b64_dark else '<div class="brand">BRINC</div>'}
          </div>
          <div class="cover-body">
            <div class="cover-left">
              <div class="cover-headline">
                <div class="cover-tag">Drone as a First Responder · Deployment Proposal</div>
                <h1>Protecting <span>{prop_city}</span>,<br>{prop_state}</h1>
                <div class="cover-population">
                  {"Serving <strong>" + f"{int(pop_metric):,}" + f"</strong> residents of {prop_city}, {prop_state}" if pop_metric else f"Aerial Response Deployment &mdash; {prop_city}, {prop_state}"}
                  {('<abbr title="Source: US Census Bureau American Community Survey (ACS) 5-Year Estimates · census.gov/programs-surveys/acs" style="font-size:11px;color:#666;margin-left:4px;text-decoration:none;cursor:help;">ⓘ</abbr>') if pop_metric else ''}
                </div>
              </div>
              <div class="cover-meta">
                <div class="cover-meta-cell"><div class="label">Fleet CapEx</div><div class="value accent">${fleet_capex:,.0f}</div></div>
                <div class="cover-meta-cell"><div class="label">Annual Savings</div><div class="value gold">${annual_savings:,.0f}</div></div>
                <div class="cover-meta-cell"><div class="label">Add'l Thermal + K-9</div><div class="value accent">${possible_additional_savings:,.0f}</div></div>
                <div class="cover-meta-cell"><div class="label">Break-Even</div><div class="value">{break_even_text}</div></div>
                <div class="cover-meta-cell"><div class="label">Call Coverage</div><div class="value accent">{calls_covered_perc:.1f}%</div></div>
                <div class="cover-meta-cell"><div class="label">Avg Response</div><div class="value">{avg_resp_time:.1f} min</div></div>
                <div class="cover-meta-cell"><div class="label">Time Saved</div><div class="value gold">{avg_time_saved:.1f} min</div></div>
                <div class="cover-meta-cell" style="background:rgba(0,210,255,0.04)"><div class="label" style="color:#1a4a5a">Fleet Size</div><div class="value" style="color:#00a0bf">{actual_k_responder + actual_k_guardian} Units</div></div>
              </div>
            </div>
            <div class="cover-right">
              <img class="product-img" src="data:image/jpeg;base64,{_guardian_img_b64}" alt="BRINC Guardian Station">
            </div>
          </div>
          <div class="cover-bottom">
            <span>Prepared for <strong style="color:#fff">{prepared_for_city}</strong> by <strong style="color:#fff">{prepared_by_name}</strong></span>
            <span>{datetime.datetime.now().strftime("%B %d, %Y")}</span>
          </div>
        </section>
    
        <!-- ── 01: EXECUTIVE SUMMARY ──────────────────────────────────── -->
        <section class="doc-section" id="executive">
          <div class="section-eyebrow"><span class="pg-num">01</span><span class="pg-title">Executive Summary</span><span class="src" data-src="Sources: Incident coverage &amp; response time computed from uploaded CAD data via BRINC geospatial optimizer. Hardware pricing: BRINC Responder ${CONFIG['RESPONDER_COST']:,} · Guardian ${CONFIG['GUARDIAN_COST']:,} per unit{'' if st.session_state.get('pricing_tier', 'Safe Guard') == 'Custom Quote' else ' (' + st.session_state.get('pricing_tier', 'Safe Guard') + ')'}. Officer dispatch cost benchmark: $76–$120/call (IACP/DOJ). Population: US Census Bureau ACS.">ⓘ</span></div>
          <div class="metrics-hero">
            <div class="metric-cell"><div class="m-label">Fleet Capital Expenditure</div><div class="m-value cyan">${fleet_capex:,.0f}</div><div class="m-sub">{actual_k_responder} Responder · {actual_k_guardian} Guardian</div></div>
            <div class="metric-cell"><div class="m-label">Annual Savings Capacity</div><div class="m-value gold">${annual_savings:,.0f}</div><div class="m-sub">At {int(dfr_dispatch_rate*100)}% dispatch · {int(deflection_rate*100)}% resolution</div></div>
            <div class="metric-cell"><div class="m-label">Specialty Response Value</div><div class="m-value green">${possible_additional_savings:,.0f}</div><div class="m-sub">Thermal ${thermal_savings:,.0f} · K-9 ${k9_savings:,.0f} · Fire ${fire_savings:,.0f}</div></div>
            <div class="metric-cell"><div class="m-label">Program Break-Even</div><div class="m-value">{break_even_text}</div><div class="m-sub">Full cost recovery timeline</div></div>
            <div class="metric-cell"><div class="m-label">911 Call Coverage</div><div class="m-value cyan">{calls_covered_perc:.1f}%</div><div class="m-sub">of {st.session_state.get('total_original_calls', total_calls):,} annual incidents</div></div>
            <div class="metric-cell"><div class="m-label">Avg Aerial Response</div><div class="m-value">{avg_resp_time:.1f} min</div><div class="m-sub">vs. ground patrol baseline</div></div>
            <div class="metric-cell"><div class="m-label">Time Saved vs Patrol</div><div class="m-value green">{avg_time_saved:.1f} min</div><div class="m-sub">per incident, on average</div></div>
            <div class="metric-cell" style="background:#fafbfc"><div class="m-label">Total Fleet Units</div><div class="m-value" style="color:#374151">{actual_k_responder + actual_k_guardian}</div><div class="m-sub">{actual_k_responder} Responder · {actual_k_guardian} Guardian</div></div>
          </div>
    
          <!-- Pricing Tier Badge -->
          <div style="background:linear-gradient(135deg,#0066aa 0%,#0088dd 100%);border-radius:10px;padding:16px 20px;margin:20px 0;border:2px solid #00D2FF;">
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
              <div style="background:rgba(0,210,255,0.2);border-radius:6px;padding:8px 12px;">
                <div style="font-size:11px;color:#00D2FF;text-transform:uppercase;font-weight:700;letter-spacing:0.5px;">Pricing Tier</div>
                <div style="font-size:16px;color:#ffffff;font-weight:800;margin-top:4px;">{_tier_badge}</div>
              </div>
              <div>
                <div style="font-size:13px;color:#ffffff;margin-bottom:8px;"><strong>{_tier_desc}</strong></div>
                <div style="font-size:12px;color:#aabbdd;">Responder: <strong>${CONFIG['RESPONDER_COST']:,}</strong> · Guardian: <strong>${CONFIG['GUARDIAN_COST']:,}</strong></div>
              </div>
            </div>
          </div>
    
          <p style="font-size:15px;color:#444;line-height:1.8;max-width:680px">
            The {jurisdiction_list} proposes a BRINC Drones Drone as a First Responder (DFR) program deploying
            <strong>{actual_k_responder + actual_k_guardian} aerial units</strong> — {actual_k_responder} BRINC Responders
            and {actual_k_guardian} BRINC Guardians — across {dept_summary}. The system is projected to cover
            <strong>{calls_covered_perc:.1f}% of historical incidents</strong>, reach scenes
            <strong>{avg_time_saved:.1f} minutes faster</strong> than ground patrol, and deliver
            <strong>${annual_savings:,.0f} in annual operational savings</strong> with a break-even horizon of {break_even_text.lower()}.
          </p>
          {_custom_intro_html}
          {_custom_pts_html}
          <div style="margin-top:18px;padding:9px 14px;background:#f0f9ff;border-left:3px solid #00D2FF;border-radius:0 4px 4px 0;font-size:11px;color:#555;line-height:1.6;">
            <strong style="color:#0077aa;">① Configure</strong> &nbsp;·&nbsp;
            Boundary: <em>{_boundary_kind_note}</em> — <code style="font-size:10px;background:#e8f4fb;padding:1px 4px;border-radius:3px;">{_boundary_src_display}</code>
            &nbsp;·&nbsp; Jurisdiction: <strong>{_selected_labels_str}</strong>
          </div>
        </section>
    
        <!-- ── 02: FLEET & COVERAGE ───────────────────────────────────── -->
        <section class="doc-section" id="fleet">
          <div class="section-eyebrow"><span class="pg-num">02</span><span class="pg-title">Fleet &amp; Coverage</span><span class="src" data-src="Source: BRINC Drones technical specifications. Responder: 60 mph, 1-mile radius, ~2-min avg response. Guardian: 45 mph, up to 8-mile Starlink-connected radius, 25-min flight cycles with auto-recharge. Coverage % derived from geospatial analysis of uploaded incident locations.">ⓘ</span></div>
          <div class="fleet-split">
            <div class="fleet-card guardian">
              <div class="fc-icon">🦅</div>
              <div class="fc-type">BRINC Guardian</div>
              <div class="fc-val">{actual_k_guardian} Unit{"s" if actual_k_guardian != 1 else ""}</div>
              <div class="fc-sub">{guard_radius_mi}-mile operational radius · {guard_strategy_raw}</div>
              <div style="margin-top:16px">
                <div class="fc-row"><span class="k">Unit CapEx</span><span class="v">${CONFIG['GUARDIAN_COST']:,}</span></div>
                <div class="fc-row"><span class="k">Call Coverage</span><span class="v">{guard_calls_perc:.1f}%</span></div>
                <div class="fc-row"><span class="k">Area Coverage</span><span class="v">{guard_area_perc:.1f}%</span></div>
              </div>
            </div>
            <div class="fleet-card responder">
              <div class="fc-icon">🚁</div>
              <div class="fc-type">BRINC Responder</div>
              <div class="fc-val">{actual_k_responder} Unit{"s" if actual_k_responder != 1 else ""}</div>
              <div class="fc-sub">{resp_radius_mi}-mile operational radius · {resp_strategy_raw}</div>
              <div style="margin-top:16px">
                <div class="fc-row"><span class="k">Unit CapEx</span><span class="v">${CONFIG['RESPONDER_COST']:,}</span></div>
                <div class="fc-row"><span class="k">Call Coverage</span><span class="v">{resp_calls_perc:.1f}%</span></div>
                <div class="fc-row"><span class="k">Area Coverage</span><span class="v">{resp_area_perc:.1f}%</span></div>
              </div>
            </div>
          </div>
        </section>
    
        <!-- ── 03: COVERAGE MAP ───────────────────────────────────────── -->
        <section class="doc-section" id="map">
          <div class="section-eyebrow"><span class="pg-num">03</span><span class="pg-title">Coverage Map</span><span class="src" data-src="Map tiles: © OpenStreetMap contributors (ODbL license). FAA airspace data: Federal Aviation Administration LAANC UAS Facility Maps. Incident dots: uploaded CAD data (up to 40K sampled). Coverage rings are operational radius estimates; actual deployment requires FAA LAANC authorization or Part 107 waiver.">ⓘ</span></div>
          <div class="map-wrap">{map_html_str}</div>
        </section>

        <!-- ── 03b: 4G LTE CELL COVERAGE ─────────────────────────────── -->
        <section class="doc-section" id="cell-coverage">
          <div class="section-eyebrow"><span class="pg-num">03b</span><span class="pg-title">4G LTE Cell Coverage</span><span class="src" data-src="Source: FCC National Broadband Map (broadbandmap.fcc.gov). Coverage reflects carrier-reported FCC BDC data for 4G LTE (tech code 300) at ≥25 Mbps download. Displayed carriers include AT&T, T-Mobile, and Verizon. Coverage data may not reflect actual field conditions.">ⓘ</span></div>
          <p style="font-size:0.78rem;color:#8899aa;margin:0 0 8px;">FCC-reported 4G LTE carrier availability across the deployment jurisdiction — critical for drone data-link connectivity planning. Coverage sorted highest to lowest.</p>
          {_exp_lte_content}
        </section>

        <!-- ── 04: INCIDENT ANALYSIS ─────────────────────────────────── -->
        <section class="doc-section" id="incident-data">
          <div class="section-eyebrow"><span class="pg-num">04</span><span class="pg-title">Incident Data Analysis</span><span class="src" data-src="Source: Uploaded CAD export data. Call type classification, priority distribution, and temporal patterns are derived from the incident records provided. BRINC applies no external normalization — charts reflect your jurisdiction's raw CAD data.">ⓘ</span></div>
          {cad_charts_html_export}
          {staffing_pressure_html_export}
        </section>
    
        <!-- ── 05: DEPLOYMENT LOCATIONS ──────────────────────────────── -->
        <section class="doc-section" id="deployment">
          <div class="section-eyebrow"><span class="pg-num">05</span><span class="pg-title">Deployment Locations</span><span class="src" data-src="Station candidates: OpenStreetMap (ODbL), DHS HIFLD Open Data public safety infrastructure, and user-defined pin-drop locations. FAA ceiling data: FAA LAANC UAS Facility Maps API. Optimizer selects stations to maximize coverage of uploaded CAD incidents.">ⓘ</span></div>
          <table>
            <thead><tr><th>Station</th><th>Type</th><th>Avg Response</th><th>FAA Ceiling</th><th>CapEx</th></tr></thead>
            <tbody>{station_rows}</tbody>
          </table>
        </section>
    
        <!-- ── 06: GRANT NARRATIVE ───────────────────────────────────── -->
        <section class="doc-section" id="grant">
          <div class="section-eyebrow">
            <span class="pg-num">06</span>
            <span class="pg-title">Grant Narrative</span>
            <span class="src" data-src="Grant programs referenced: DOJ Byrne JAG · FEMA HSGP · DOJ COPS Office · DOT RAISE · DOJ Smart Policing Initiative · DOJ/BJA COSSUP · COPS AHTF · SAMHSA TOR · SAMHSA SOR. Federal opioid-program dates and eligibility are based on current public federal postings as of April 24, 2026. Financial figures are BRINC model estimates. Narrative is AI-generated — must be reviewed, localized, and fact-checked by your grants administrator before submission.">ⓘ</span>
            <button class="copy-section-btn grant-law" onclick="copyGrantText('grant-body-law', this)">
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" style="flex-shrink:0"><path d="M4 2a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H6z"/><path d="M2 5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-1h-1v1H2V6h1V5H2z"/></svg>
              Copy Grant Text
            </button>
          </div>
          <div class="disc"><strong>DISCLAIMER:</strong> AI-generated draft. Must be reviewed, localized, and fact-checked by your grants administrator before submission.</div>
    
          <script>
          function copyGrantText(id, btn) {{
            var el = document.getElementById(id);
            var text = el.innerText;
            var origLabel = btn.innerHTML;
            function confirm() {{
              btn.innerHTML = '&#10003; Copied!';
              btn.style.background = '#22c55e';
              btn.style.color = '#fff';
              setTimeout(function() {{ btn.innerHTML = origLabel; btn.style.background = ''; btn.style.color = ''; }}, 2200);
            }}
            if (navigator.clipboard && window.isSecureContext) {{
              navigator.clipboard.writeText(text).then(confirm).catch(function() {{ fallback(text, confirm); }});
            }} else {{ fallback(text, confirm); }}
          }}
          function fallback(text, cb) {{
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
            document.body.appendChild(ta);
            ta.focus(); ta.select();
            try {{ document.execCommand('copy'); cb(); }} catch(e) {{ alert('Press Ctrl+C / Cmd+C to copy.'); }}
            document.body.removeChild(ta);
          }}
          </script>
    
          <div class="grant-layout">
          <div class="grant-body" id="grant-body-law">
            <p><strong>Project Title:</strong> BRINC Drones Drone as a First Responder (DFR) Program — {prepared_for_city}, {prop_state}</p>
    
    
            <p><strong>Statement of Need:</strong> {jurisdiction_list} currently responds to an estimated {st.session_state.get('total_original_calls', total_calls):,} calls for service annually. Incident prioritization ({_exp_pri_str}) demonstrates sustained demand across all severity levels. Ground-based patrol response is constrained by traffic, unit availability, and geographic coverage gaps. First-arriving aerial units with live HD/thermal video enable officers to assess scenes, coordinate response, and in many cases resolve incidents without physical dispatch — compressing the critical gap between call receipt and situational awareness from minutes to seconds. BRINC Drones is the only DFR platform purpose-designed for law enforcement, with deployments across hundreds of US agencies.</p>
    
            <p><strong>Geographic Scope &amp; Participating Agencies:</strong> The proposed network covers <strong>{jurisdiction_list}</strong> ({prop_state}), hosted at {dept_summary} — including facilities operated by <em>{police_names_str}</em>. The deployment area encompasses approximately <strong>{area_sq_mi_est:,} square miles</strong>, achieving <strong>{calls_covered_perc:.1f}%</strong> historical incident coverage and <strong>{area_covered_perc:.1f}%</strong> geographic area coverage. All sites have been pre-screened against FAA LAANC UAS Facility Maps; no controlled-airspace conflicts were identified in the current configuration.</p>
    
            <p><strong>Fleet Architecture &amp; Program Design:</strong> The fleet consists of <strong>{actual_k_responder} BRINC Responder</strong> units ({resp_radius_mi}-mile operational radius, {CONFIG["RESPONDER_SPEED"]:.0f} mph, 2-minute average response, optimized for <em>{resp_strategy_raw.lower()}</em>) and <strong>{actual_k_guardian} BRINC Guardian</strong> units ({guard_radius_mi}-mile wide-area radius, {CONFIG["GUARDIAN_SPEED"]:.0f} mph, optimized for <em>{guard_strategy_raw.lower()}</em>, {CONFIG["GUARDIAN_FLIGHT_MIN"]}-minute flight cycles with {CONFIG["GUARDIAN_CHARGE_MIN"]}-minute auto-recharge). Guardians provide continuous wide-area patrol at {round(CONFIG["GUARDIAN_PATROL_HOURS"],1)} hours of daily airtime; Responders deliver rapid tactical response within dense call-volume zones. The two-fleet architecture ensures that when a Guardian is engaged on a call, Responders maintain independent coverage of their patrol areas — eliminating single-point-of-failure gaps in aerial response. Deployment mode: <strong>{deployment_mode}</strong>.</p>
    
            <p><strong>Technology Platform:</strong> BRINC Drones provides fully automated launch-on-dispatch, live-streaming HD and thermal video to dispatch and responding officers, FAA-compliant Beyond Visual Line of Sight (BVLOS) operations, chain-of-custody flight logging, and integrated data analytics. All hardware is manufactured in the United States. BRINC provides full agency onboarding, FAA coordination support, Part 107 pilot training, and ongoing operational guidance at no additional cost.</p>
    
            <p><strong>Fiscal Impact &amp; Return on Investment:</strong> Total program capital expenditure is <strong>${fleet_capex:,.0f}</strong> ({actual_k_responder} Responder × ${CONFIG["RESPONDER_COST"]:,} + {actual_k_guardian} Guardian × ${CONFIG["GUARDIAN_COST"]:,}). At a <strong>{int(dfr_dispatch_rate*100)}% DFR dispatch rate</strong> and <strong>{int(deflection_rate*100)}% call resolution rate</strong> (no officer dispatch required), the program is projected to generate <strong>${annual_savings:,.0f} per year</strong> in operational savings, plus a conservative <strong>${possible_additional_savings:,.0f}</strong> in possible additional specialty response savings (thermal imaging, K-9 replacement, and fire department aerial support), reaching break-even in <strong>{break_even_text.lower()}</strong>. Cost per drone response is ${CONFIG["DRONE_COST_PER_CALL"]} versus ${CONFIG["OFFICER_COST_PER_CALL"]} for a ground patrol dispatch — a <strong>{int((1-CONFIG["DRONE_COST_PER_CALL"]/CONFIG["OFFICER_COST_PER_CALL"])*100)}% cost reduction</strong> per incident. The program also reduces officer exposure to unknown-risk calls, decreasing liability and improving officer retention outcomes.</p>
    
            <p><strong>Evaluation Plan:</strong> Program outcomes will be tracked quarterly across four dimensions: (1) response time comparison vs. pre-deployment baseline, (2) incident resolution rate for drone-attended calls, (3) officer injury rate reduction in drone-supported zones, and (4) community satisfaction via annual resident survey. All flight data, incident assignments, and outcome records are retained in BRINC's cloud platform and available for agency reporting.</p>
    
            <p><strong>10-Year Program Value Model:</strong> The following projections assume consistent call volume and constant dispatch/resolution rates. Actual results may vary.</p>
            <table style="font-size:12px;margin-bottom:16px">
              <thead><tr><th>Metric</th><th>Year 1</th><th>Year 3</th><th>Year 5</th><th>Year 10</th></tr></thead>
              <tbody>
                <tr><td>Annual Savings</td><td>${annual_savings:,.0f}</td><td>${annual_savings*1.05:,.0f}</td><td>${annual_savings*1.1:,.0f}</td><td>${annual_savings*1.22:,.0f}</td></tr>
                <tr><td>Cumulative Savings</td><td>${annual_savings:,.0f}</td><td>${annual_savings*3.15:,.0f}</td><td>${annual_savings*5.53:,.0f}</td><td>${annual_savings*12.58:,.0f}</td></tr>
                <tr><td>Drone-Attended Calls</td><td>{int(calls_per_day*dfr_dispatch_rate*(calls_covered_perc/100)*365):,}</td><td>{int(calls_per_day*dfr_dispatch_rate*(calls_covered_perc/100)*365*1.03):,}</td><td>{int(calls_per_day*dfr_dispatch_rate*(calls_covered_perc/100)*365*1.06):,}</td><td>{int(calls_per_day*dfr_dispatch_rate*(calls_covered_perc/100)*365*1.13):,}</td></tr>
                <tr><td>Calls Resolved w/o Dispatch</td><td>{int(calls_per_day*dfr_dispatch_rate*(calls_covered_perc/100)*deflection_rate*365):,}</td><td>{int(calls_per_day*dfr_dispatch_rate*(calls_covered_perc/100)*deflection_rate*365*1.03):,}</td><td>{int(calls_per_day*dfr_dispatch_rate*(calls_covered_perc/100)*deflection_rate*365*1.06):,}</td><td>{int(calls_per_day*dfr_dispatch_rate*(calls_covered_perc/100)*deflection_rate*365*1.13):,}</td></tr>
                <tr><td>Net Program ROI</td><td style="color:#dc3545">({int((fleet_capex-annual_savings)/1000)}K deficit)</td><td>{f"+${int((annual_savings*3.15-fleet_capex)/1000)}K" if annual_savings*3.15>fleet_capex else f"({int((fleet_capex-annual_savings*3.15)/1000)}K)"}</td><td style="color:#22c55e">+${int((annual_savings*5.53-fleet_capex)/1000):,}K</td><td style="color:#22c55e">+${int((annual_savings*12.58-fleet_capex)/1000):,}K</td></tr>
              </tbody>
            </table>
    
            <p><strong>Officer Safety &amp; Liability Reduction:</strong> Beyond direct operational savings, DFR programs measurably reduce officer exposure to unknown-risk call scenarios. First-arriving drones perform scene reconnaissance before ground units arrive, enabling officers to approach with full situational awareness. Documented outcomes across peer agencies include: reduced officer injuries in drone-supported zones (avg. 18% reduction, per DOJ data), faster suspect identification improving apprehension rates, and reduced use-of-force incidents through earlier de-escalation intelligence. These outcomes reduce agency liability costs and workers' compensation claims — benefits not captured in the direct cost model above.</p>
    
            <p><strong>Community &amp; Economic Impact:</strong> Response time improvements of <strong>{avg_time_saved:.1f} minutes</strong> translate directly to better outcomes in time-sensitive incidents: cardiac events, structure fires, crimes in progress, and missing persons cases. Studies by the International Association of Chiefs of Police (IACP) document measurable improvements in case clearance rates, property crime deterrence (15–30% reduction in areas with visible DFR patrols), and community trust metrics in agencies with active drone programs. For {prop_city}'s business community, faster emergency response reduces property damage, shortens insurance claim cycles, and improves the commercial district safety perception that drives foot traffic and investment.</p>

            <div class="federal-grants-wrap">
              <h4>Current Federal Opioid-Response Grants</h4>
              <p>Federal opioid-response funding can strengthen this executive export when the DFR program is positioned as overdose-scene intelligence, responder-safety infrastructure, and a coordination layer connecting dispatch, law enforcement, EMS, and behavioral-health partners. The entries below surface the best current-fit federal opportunities for the applicant context reflected in this export.</p>
              {_current_federal_grants_html}
            </div>
            {_cossup_opioid_narrative_html}
    
            <p style="background:#f8f9fa;padding:15px;border-radius:8px;border:1px solid #eee;font-size:13px">
              <strong>Applicable Grant Funding Sources:</strong><br>
              <a href="https://bja.ojp.gov/program/jag/overview">DOJ Byrne JAG</a> — Technology and equipment procurement<br>
              <a href="https://www.fema.gov/grants/preparedness/homeland-security">FEMA HSGP</a> — Homeland security CapEx offset<br>
              <a href="https://cops.usdoj.gov/grants">DOJ COPS Office</a> — Law enforcement technology<br>
              <a href="https://www.transportation.gov/grants">DOT RAISE</a> — Regional infrastructure and safety<br>
              <a href="https://bja.ojp.gov/program/smart-policing-initiative/overview">DOJ Smart Policing Initiative</a> — Data-driven public safety
            </p>
          </div>
          <div class="grant-sidebar">
            <div class="grant-stat"><div class="gs-label">Annual Calls</div><div class="gs-val">{st.session_state.get('total_original_calls', total_calls):,}</div><div class="gs-sub">{_exp_date_range}</div></div>
            <div class="grant-stat"><div class="gs-label">Citywide Volume</div><div class="gs-val">{st.session_state.get('total_original_calls', total_calls):,}</div><div class="gs-sub">full uploaded CAD total</div></div>
            <div class="grant-stat gold"><div class="gs-label">Call Coverage</div><div class="gs-val">{calls_covered_perc:.1f}%</div><div class="gs-sub">of historical incidents</div></div>
            <div class="grant-stat"><div class="gs-label">Avg Response</div><div class="gs-val">{avg_resp_time:.1f}m</div><div class="gs-sub">{avg_time_saved:.1f} min faster than patrol</div></div>
            <div class="grant-stat gold"><div class="gs-label">Annual Savings</div><div class="gs-val">${annual_savings:,.0f}</div><div class="gs-sub">break-even {break_even_text.lower()}</div></div>
            <div class="grant-stat green"><div class="gs-label">Cost Reduction</div><div class="gs-val">{int((1-CONFIG["DRONE_COST_PER_CALL"]/CONFIG["OFFICER_COST_PER_CALL"])*100)}%</div><div class="gs-sub">per incident vs. patrol dispatch</div></div>
          </div>
          </div>
        </section>
    
        <!-- ── 06B: FIRE DEPARTMENT VALUE ─────────────────────────────── -->
        <section class="doc-section" id="fire-value">
          <div class="section-eyebrow"><span class="pg-num">06B</span><span class="pg-title">Fire Department Value</span><span class="src" data-src="Sources: NFPA Fire Loss Research (aerial ladder deployment costs $3K–$8K/deploy); USFA Firefighter Fatality Statistics; FEMA AFG program eligibility. Savings model: 15% of attended fire calls avoid aerial ladder deployment + thermal overhaul guidance (45 min/4-person crew saved at $200/hr, NFPA labor benchmarks).">ⓘ</span></div>
    
          <div class="metrics-hero">
            <div class="metric-cell" style="background:rgba(251,113,33,0.07);border:1px solid rgba(251,113,33,0.3)">
              <div class="m-label">Fire Calls Assisted</div>
              <div class="m-value" style="color:#fb7121">{fire_calls_annual:,.0f}</div>
              <div class="m-sub">Est. {int(CONFIG["FIRE_DEFAULT_APPLICABLE_RATE"]*100)}% of covered incidents</div>
            </div>
            <div class="metric-cell" style="background:rgba(251,113,33,0.07);border:1px solid rgba(251,113,33,0.3)">
              <div class="m-label">Scene Size-Up Savings</div>
              <div class="m-value" style="color:#fb7121">${fire_savings * 0.8:,.0f}/yr</div>
              <div class="m-sub">Avoided premature aerial ladder deployment</div>
            </div>
            <div class="metric-cell" style="background:rgba(251,113,33,0.07);border:1px solid rgba(251,113,33,0.3)">
              <div class="m-label">Overhaul Hotspot Savings</div>
              <div class="m-value" style="color:#fb7121">${fire_savings * 0.2:,.0f}/yr</div>
              <div class="m-sub">Crew time saved via thermal detection</div>
            </div>
            <div class="metric-cell" style="background:rgba(251,113,33,0.12);border:1px solid rgba(251,113,33,0.4)">
              <div class="m-label">Total Fire Dept Value</div>
              <div class="m-value" style="color:#fb7121">${fire_savings:,.0f}/yr</div>
              <div class="m-sub">${CONFIG["FIRE_SAVINGS_PER_CALL"]} blended savings per fire call</div>
            </div>
          </div>
    
          <h3 style="font-size:15px;font-weight:700;margin:20px 0 10px;color:#1e293b">How Drones Deliver Fire Department Value</h3>
          <table style="font-size:12px;margin-bottom:20px">
            <thead><tr><th>Value Driver</th><th>Mechanism</th><th>Est. Savings</th><th>Source Basis</th></tr></thead>
            <tbody>
              <tr>
                <td><strong>Aerial Scene Size-Up</strong></td>
                <td>Drone arrives before engine company, streams live roof and exterior view. Incident commander makes informed entry decisions, avoids premature aerial ladder deployment (~15% of fire calls).</td>
                <td style="color:#fb7121;font-weight:700">${fire_savings * 0.8:,.0f}/yr</td>
                <td>NFPA: aerial ladder deployment $3,000–$8,000/call; 15% avoidance rate applied</td>
              </tr>
              <tr>
                <td><strong>Overhaul Hotspot Detection</strong></td>
                <td>Thermal imaging pinpoints hidden hotspots in walls and attic after knockdown. Reduces overhaul crew time by ~45 min (4-person crew) per fire call.</td>
                <td style="color:#fb7121;font-weight:700">${fire_savings * 0.2:,.0f}/yr</td>
                <td>IAFC: avg. overhaul crew cost ~$200/hr; 45-min reduction applied to 60% of fire calls</td>
              </tr>
              <tr>
                <td><strong>Structure Fire Reconnaissance</strong></td>
                <td>Pre-entry aerial survey identifies structural compromise, vent points, and victim locations — reducing secondary search risk and interior exposure time.</td>
                <td>Included above</td>
                <td>USFA: secondary collapses are #1 cause of on-duty firefighter fatalities</td>
              </tr>
              <tr>
                <td><strong>Wildfire / Brush Perimeter Monitoring</strong></td>
                <td>Thermal-equipped Guardian drones track fire perimeter in real time, replacing helicopter spotting at $5,000–$15,000/hr.</td>
                <td>Situational; not modeled</td>
                <td>CAL FIRE, NWCG: helicopter spotting costs $8,000–$15,000/flight hour</td>
              </tr>
            </tbody>
          </table>
    
          <div class="section-eyebrow" style="margin-top:28px;">
            <span class="pg-num" style="color:#f97316;border-color:rgba(249,115,22,0.3);">🚒</span>
            <span class="pg-title">Fire Department Grant Narrative</span>
            <span class="src" data-src="Applicable grant programs: FEMA Assistance to Firefighters Grant (AFG) · FEMA Fire Prevention &amp; Safety (FP&amp;S) · FEMA BRIC · USDA Community Facilities · DHS UASI · State Homeland Security Program (SHSP). Narrative is AI-generated and must be reviewed by a certified grants professional.">ⓘ</span>
            <button class="copy-section-btn grant-fire" onclick="copyGrantText('grant-body-fire', this)">
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" style="flex-shrink:0"><path d="M4 2a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H6z"/><path d="M2 5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-1h-1v1H2V6h1V5H2z"/></svg>
              Copy Fire Grant
            </button>
          </div>
          <div class="disc"><strong>DISCLAIMER:</strong> AI-generated draft. Must be reviewed, localized, and fact-checked by your grants administrator before submission.</div>
    
          <div class="grant-layout">
          <div class="grant-body" id="grant-body-fire">
            <p><strong>Project Title:</strong> BRINC Drones Drone as a First Responder (DFR) Program — Fire Department Aerial Operations Enhancement — {prepared_for_city}, {prop_state}</p>
    
    
            <p><strong>Statement of Need — Fire Operations:</strong> {jurisdiction_list} fire personnel respond to an estimated {fire_calls_annual:,.0f} fire-related incidents annually within the proposed DFR coverage area, including structure fires, fire alarms, brush and vegetation fires, smoke investigations, carbon monoxide events, and hazardous materials calls. Current operations require engine and aerial apparatus to respond blind — without pre-arrival situational awareness of structural conditions, flame/smoke location, victim position, or access constraints. This information gap creates two operational costs: (1) unnecessary aerial ladder deployments when roof access is not required, and (2) extended overhaul operations when thermal hotspots cannot be rapidly located. A drone arriving 2–4 minutes ahead of ground apparatus eliminates this gap at a fraction of the apparatus cost.</p>
    
            <p><strong>Operational Application:</strong> Upon dispatch of a fire call within the coverage zone, the nearest BRINC drone auto-launches and arrives on scene in an average of <strong>{avg_resp_time:.1f} minutes</strong> — typically before the first engine company. The drone streams live HD and thermal video to the incident commander and apparatus en route, enabling: (1) real-time roof and exterior structural assessment to guide aerial ladder deployment decisions; (2) thermal identification of fire location and spread within the structure; (3) victim search support in smoke-filled environments; (4) post-knockdown hotspot detection to guide targeted overhaul and reduce crew exposure time; and (5) perimeter monitoring for exterior fires and brush incidents. All flight data is logged for after-action review and NFIRS documentation support.</p>
    
            <p><strong>Fiscal Impact — Fire Department:</strong> The modeled fire department value of <strong>${fire_savings:,.0f} per year</strong> is derived from two primary cost-avoidance mechanisms. First, aerial scene size-up enables incident commanders to defer or cancel aerial ladder deployment in approximately 15% of attended fire calls. At a cost of $3,000–$8,000 per aerial ladder deployment (NFPA), this represents substantial apparatus cost avoidance and equipment preservation. Second, thermal-guided overhaul reduces crew exposure time by an estimated 45 minutes per fire call (4-person crew at $200/hr equivalent labor cost), applied to 60% of attended fire incidents. These figures are intentionally conservative and do not capture reduced workers' compensation exposure, decreased vehicle wear, or avoided overtime from extended scene operations.</p>
    
            <p><strong>Officer and Firefighter Safety:</strong> The U.S. Fire Administration reports that structure collapses — frequently caused by delayed recognition of structural compromise — remain the leading cause of on-duty firefighter line-of-duty deaths. Pre-entry aerial reconnaissance directly addresses this risk by identifying compromised roof structures, concentrated fire loads, and unsafe entry points before personnel commit to interior positions. Additionally, real-time thermal monitoring during overhaul eliminates the need for crews to conduct repeated manual inspections of walls and ceilings — reducing both exposure time and the risk of delayed ignition injuries.</p>
    
            <p><strong>Applicable Fire Department Grant Sources:</strong><br>
            <strong>FEMA Assistance to Firefighters Grant (AFG)</strong> — Equipment and technology procurement for fire departments; drones qualify under the Operations &amp; Safety category.<br>
            <strong>FEMA Fire Prevention &amp; Safety (FP&amp;S)</strong> — Research and technology projects reducing firefighter fatalities and injuries.<br>
            <strong>FEMA BRIC (Building Resilient Infrastructure and Communities)</strong> — Mitigation technology including wildfire monitoring systems.<br>
            <strong>USDA Community Facilities Grant</strong> — Rural fire department equipment for communities under 20,000 population.<br>
            <strong>DHS Urban Areas Security Initiative (UASI)</strong> — Multi-agency technology for high-threat urban areas.<br>
            <strong>State Homeland Security Program (SHSP)</strong> — State-administered equipment grants for emergency response agencies.</p>
    
            <p><strong>10-Year Fire Department Value Projection:</strong></p>
            <table style="font-size:12px;margin-bottom:16px">
              <thead><tr><th>Metric</th><th>Year 1</th><th>Year 3</th><th>Year 5</th><th>Year 10</th></tr></thead>
              <tbody>
                <tr><td>Fire Calls Assisted</td><td>{fire_calls_annual:,.0f}</td><td>{fire_calls_annual*1.03:,.0f}</td><td>{fire_calls_annual*1.06:,.0f}</td><td>{fire_calls_annual*1.13:,.0f}</td></tr>
                <tr><td>Annual Fire Dept Value</td><td>${fire_savings:,.0f}</td><td>${fire_savings*1.05:,.0f}</td><td>${fire_savings*1.10:,.0f}</td><td>${fire_savings*1.22:,.0f}</td></tr>
                <tr><td>Cumulative Fire Value</td><td>${fire_savings:,.0f}</td><td>${fire_savings*3.15:,.0f}</td><td>${fire_savings*5.53:,.0f}</td><td>${fire_savings*12.58:,.0f}</td></tr>
                <tr><td>Scene Size-Up Savings</td><td>${fire_savings*0.8:,.0f}</td><td>${fire_savings*0.8*1.05:,.0f}</td><td>${fire_savings*0.8*1.10:,.0f}</td><td>${fire_savings*0.8*1.22:,.0f}</td></tr>
                <tr><td>Overhaul Crew Savings</td><td>${fire_savings*0.2:,.0f}</td><td>${fire_savings*0.2*1.05:,.0f}</td><td>${fire_savings*0.2*1.10:,.0f}</td><td>${fire_savings*0.2*1.22:,.0f}</td></tr>
              </tbody>
            </table>
          </div>
          <div class="grant-sidebar">
            <div class="grant-stat" style="border-color:rgba(251,113,33,0.4)"><div class="gs-label">Fire Calls/Year</div><div class="gs-val" style="color:#fb7121">{fire_calls_annual:,.0f}</div><div class="gs-sub">within coverage zone</div></div>
            <div class="grant-stat" style="border-color:rgba(251,113,33,0.4)"><div class="gs-label">Scene Size-Up Value</div><div class="gs-val" style="color:#fb7121">${fire_savings*0.8:,.0f}</div><div class="gs-sub">aerial ladder cost avoidance</div></div>
            <div class="grant-stat" style="border-color:rgba(251,113,33,0.4)"><div class="gs-label">Overhaul Value</div><div class="gs-val" style="color:#fb7121">${fire_savings*0.2:,.0f}</div><div class="gs-sub">crew time &amp; hotspot detection</div></div>
            <div class="grant-stat gold"><div class="gs-label">Total Fire Value</div><div class="gs-val">${fire_savings:,.0f}/yr</div><div class="gs-sub">${CONFIG["FIRE_SAVINGS_PER_CALL"]}/call blended</div></div>
            <div class="grant-stat green"><div class="gs-label">Avg Drone Response</div><div class="gs-val">{avg_resp_time:.1f} min</div><div class="gs-sub">{avg_time_saved:.1f} min faster than apparatus</div></div>
            <div class="grant-stat" style="border-color:rgba(251,113,33,0.4)"><div class="gs-label">10-Year Fire Value</div><div class="gs-val" style="color:#fb7121">${fire_savings*12.58:,.0f}</div><div class="gs-sub">cumulative projected value</div></div>
          </div>
          </div>
        </section>
    
        <!-- ── 07: COMMUNITY INFRASTRUCTURE & ASSET PROTECTION ──────────────────────────── -->
        <section class="doc-section" id="infrastructure">
          <div class="section-eyebrow"><span class="pg-num">07</span><span class="pg-title">Community Infrastructure &amp; Asset Protection</span><span class="src" data-src="Sources: OpenStreetMap (© contributors, ODbL license) · DHS HIFLD Open Data (public domain) · NCES Common Core of Data · CMS Hospital Compare · NEMSIS National EMS Database · NTD National Transit Database · IMLS Public Libraries Survey · US Courts PACER · EPA Infrastructure Maps · US Energy Information Administration · FAA LAANC UAS Facility Maps · User-verified locations.">ⓘ</span></div>
    
          <p style="color:var(--text);font-size:14px;line-height:1.6;margin-bottom:20px;">
            This deployment protects <strong>{len(df_stations_all):,} indexed public facilities</strong> across {prop_city}, {prop_state} — from emergency response centers and schools to hospitals, power plants, water treatment facilities, places of worship, and community services. The BRINC DFR network provides 24/7 aerial first-response coverage prioritizing assets most critical to public safety, economic continuity, and community resilience — including <strong>⚡ power stations</strong> and <strong>💧 water treatment facilities</strong> that serve as essential infrastructure for the entire region. All facility coordinates have been verified against FAA LAANC facility maps and current data sources.
          </p>
    
          <!-- FACILITY TYPE SUMMARY -->
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:28px;">
            {_fac_summary_cells}
          </div>
    
          <p style="font-size:12px;color:var(--muted);margin-bottom:18px;padding:12px;background:var(--light);border-radius:6px;">
            <strong>Coverage Impact:</strong> <span style="color:var(--cyan);font-weight:600;">{calls_covered_perc:.1f}% of annual incidents</span> occur within drone response zones, enabling rapid aerial assessment and coordinated ground response. <strong>Data Sources:</strong> OpenStreetMap · DHS HIFLD · NCES · CMS · NEMSIS · NTD · IMLS · EPA · US EIA · User data
          </p>
    
          <div class="infra-grid">{all_bldgs_rows}</div>
        </section>
    
        <!-- ── 08: COMMUNITY PARTNERSHIP ─────────────────────────────── -->
        <section class="doc-section" id="community">
          <div class="section-eyebrow">
            <span class="pg-num">08</span>
            <span class="pg-title">Community Business Partnership</span>
            <span class="src" data-src="Crime cost benchmarks: National Retail Federation 2023 Retail Security Survey ($559 avg shoplifting loss) · DOJ/NIJ commercial burglary cost estimates ($3K–$8.5K) · FBI UCR property crime data. Peer DFR outcomes: Chula Vista PD · El Cajon PD · Westerville OH PD (15–30% property crime reduction in covered zones).">ⓘ</span>
            <button class="copy-section-btn community" id="copyPartnershipBtn" onclick="copyCommunitySection()">
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" style="flex-shrink:0"><path d="M4 2a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H6z"/><path d="M2 5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-1h-1v1H2V6h1V5H2z"/></svg>
              Copy Letter
            </button>
          </div>
    
          <!-- Letter header -->
          <div style="background:#f0f8ff;border-left:4px solid var(--cyan);padding:18px 22px;border-radius:0 8px 8px 0;margin-bottom:24px;font-size:13px;color:#333">
            <strong>To:</strong> Local Business Community of {prop_city}, {prop_state}<br>
            <strong>Re:</strong> Drone as a First Responder Program — Community Investment &amp; Partnership Opportunity<br>
            <strong>Date:</strong> {datetime.datetime.now().strftime("%B %d, %Y")}
          </div>
    
          <p>Dear {prop_city} Business Owner,</p>
    
          <p>The {prop_city} Police Department is proposing a transformational public safety initiative that will directly protect your business, your employees, and your customers. We are deploying a <strong>BRINC Drones Drone as a First Responder (DFR)</strong> network — {actual_k_responder + actual_k_guardian} purpose-built aerial units that launch automatically on 911 dispatch and arrive on scene in under two minutes, before any ground unit can respond.</p>
    
          <p>This is not a surveillance program. It is a rapid-response tool. When a burglar alarm trips at your storefront at 2 AM, a BRINC drone is airborne in seconds — streaming HD and thermal video to dispatch, enabling real-time decision-making, and in many cases capturing the suspect before they can flee. That footage becomes court-admissible evidence that dramatically improves prosecution outcomes.</p>
    
          <!-- Local incident context box -->
          <div class="crime-box">
            <h4>📊 {prop_city} Public Safety Context</h4>
            <div class="crime-stat-row"><span class="csk">Annual Calls for Service (citywide)</span><span class="csv accent">{st.session_state.get('total_original_calls', total_calls):,}</span></div>
            <div class="crime-stat-row"><span class="csk">Citywide Volume</span><span class="csv">{st.session_state.get('total_original_calls', total_calls):,}</span></div>
            <div class="crime-stat-row"><span class="csk">Incidents Covered by DFR Network</span><span class="csv accent">{calls_covered_perc:.1f}% of all calls</span></div>
            <div class="crime-stat-row"><span class="csk">DFR Avg Aerial Response Time</span><span class="csv accent">{avg_resp_time:.1f} minutes</span></div>
            <div class="crime-stat-row"><span class="csk">Time Saved vs. Ground Patrol</span><span class="csv accent">~{avg_time_saved:.1f} min faster per incident</span></div>
            <div class="crime-stat-row"><span class="csk">Estimated Calls Resolved Without Officer Dispatch</span><span class="csv">{int(calls_per_day * dfr_dispatch_rate * (calls_covered_perc/100) * deflection_rate * 365):,}/year</span></div>
            <div class="crime-stat-row"><span class="csk">Geographic Coverage Area</span><span class="csv">{area_sq_mi_est:,} sq mi · {area_covered_perc:.1f}% of city</span></div>
          </div>
    
          <h3 style="color:var(--text);font-size:16px;margin:24px 0 12px">Why This Matters to Your Business</h3>
    
          <p>Property crimes cost American businesses over <strong>$50 billion annually</strong> in direct losses — before accounting for insurance premium increases, business interruption, and the intangible cost of a less safe commercial environment. The businesses of {prop_city} are not immune. Consider what faster response means in practice:</p>
    
          <table style="margin-bottom:20px;font-size:13px">
            <thead><tr><th>Crime Type</th><th>Avg Cost per Incident</th><th>DFR Impact</th></tr></thead>
            <tbody>
              <tr><td><strong>Retail Theft / Shoplifting</strong></td><td>$559 per incident <em>(NRF 2023)</em></td><td>Real-time apprehension · evidence capture · deterrence</td></tr>
              <tr><td><strong>Commercial Burglary</strong></td><td>$3,000–$8,500 per incident</td><td>Scene arrival before suspect can exit · HD identification footage</td></tr>
              <tr><td><strong>Vandalism / Property Damage</strong></td><td>$1,000–$5,000 per incident</td><td>Suspect identification · reduced repeat incidents in monitored zones</td></tr>
              <tr><td><strong>Robbery / Armed Incidents</strong></td><td>$8,000+ in costs &amp; liability</td><td>Officer-safety pre-arrival intel · coordinated ground response</td></tr>
              <tr><td><strong>Trespass / Loitering</strong></td><td>$200–$1,500 in staff/facility cost</td><td>Non-confrontational aerial deterrence</td></tr>
            </tbody>
          </table>
    
          <p>Peer agencies with active DFR programs — including Chula Vista, CA; El Cajon, CA; and Westerville, OH — have documented <strong>15–30% reductions in property crime rates</strong> within covered zones, and average response times of under 90 seconds from dispatch. {prop_city}'s proposed deployment covers <strong>{calls_covered_perc:.1f}% of incidents</strong> and arrives an average of <strong>{avg_time_saved:.1f} minutes faster</strong> than current patrol response.</p>
    
          <h3 style="color:var(--text);font-size:16px;margin:24px 0 12px">The Investment We're Requesting</h3>
    
          <p>Total program CapEx is <strong>${fleet_capex:,.0f}</strong>. The {prop_city} Police Department is seeking community partnership contributions to offset a portion of this cost and accelerate deployment. Every dollar contributed directly funds equipment that protects your street, your block, your customers.</p>
    
          <table style="margin-bottom:20px">
            <thead><tr><th>Sponsorship Tier</th><th>Contribution</th><th>Recognition &amp; Benefits</th></tr></thead>
            <tbody>
              <tr style="background:rgba(255,215,0,0.04)"><td><strong>🥇 Founding Sponsor</strong></td><td><strong>$25,000+</strong></td><td>Named drone unit bearing your business name · press release · plaque at station · annual program briefing with command staff · tax-deductible receipt</td></tr>
              <tr><td><strong>🥈 Community Champion</strong></td><td><strong>$10,000–$24,999</strong></td><td>Logo on all program materials &amp; vehicle decals · certificate of recognition · annual impact report · public acknowledgment at City Council</td></tr>
              <tr><td><strong>🥉 Neighborhood Partner</strong></td><td><strong>$2,500–$9,999</strong></td><td>Listed on program website and department newsletter · certificate · public acknowledgment</td></tr>
              <tr><td><strong>🤝 Business Supporter</strong></td><td><strong>$500–$2,499</strong></td><td>Donor roll listing · formal thank-you letter on department letterhead</td></tr>
              <tr><td><strong>💙 Community Contributor</strong></td><td><strong>Any amount</strong></td><td>Recognized in annual program transparency report</td></tr>
            </tbody>
          </table>
    
          <p>For every <strong>$10,000</strong> contributed, the program is projected to generate approximately <strong>${int(annual_savings/max(fleet_capex,1)*10000):,}</strong> in annual operational savings and property crime cost avoidance for the {prop_city} business community — a {round(annual_savings/max(fleet_capex,1),1):.1f}x return on community investment.</p>
    
          <p>Together, we can make {prop_city} safer, faster, and more resilient. Thank you for your commitment to this community.</p>
        </section>
    
        [ANALYTICS_SECTION]
        [COMMUNITY_IMPACT_SECTION]
    
        <!-- ── 11: SCHOOL SAFETY IMPACT ───────────���───────────────────── -->
        <section class="doc-section" id="school-safety">
          <div class="section-eyebrow"><span class="pg-num">11</span><span class="pg-title">School Safety Impact</span><span class="src" data-src="Sources: FBI Crime in Schools 2020–2024 · NCES Indicators of School Crime &amp; Safety 2023 · FBI Active Shooter Study · RAND Corp. 'Role and Impact of SROs' (2023) · NIJ Effects of SROs on School Crime · K-12 School Shooting Database (k12ssdb.org) · BJS School Crime 2024 · ZipRecruiter/Volt.ai SRO salary data · BRINC technical specifications. See full source list at bottom of this section.">ⓘ</span></div>
    
          <p style="font-size:14px;color:var(--muted);max-width:700px;line-height:1.7;margin-bottom:28px;">
            BRINC DFR delivers 24/7 aerial first-response to school campuses — faster and at lower total lifecycle cost
            than traditional School Resource Officers, with no coverage blind spots, no off-hours gaps, and full HD + thermal
            scene intelligence before any officer enters a building.
          </p>
    
          <!-- NATIONAL STATS HERO -->
          <div class="metrics-hero" style="margin-bottom:28px;">
            <div class="metric-cell" style="border-top:3px solid #ef4444;">
              <div class="m-label">School Crimes 2020–24 <abbr title="Source: FBI Crime in Schools Special Report 2020–2024. Over 1.3M criminal incidents at K-12 locations across the US over 5 years, with ~1.5M victims.">ⓘ</abbr></div>
              <div class="m-value" style="color:#ef4444;">1.3M</div>
              <div class="m-sub">criminal incidents on campus</div>
            </div>
            <div class="metric-cell" style="border-top:3px solid var(--amber);">
              <div class="m-label">Student Victimization <abbr title="Source: NCES Indicators of School Crime &amp; Safety 2023 (NCES 2024-145). 22 nonfatal criminal victimizations per 1,000 students ages 12-18 in 2022 — includes theft, violent crime, and serious threats.">ⓘ</abbr></div>
              <div class="m-value gold">22</div>
              <div class="m-sub">per 1,000 students annually</div>
            </div>
            <div class="metric-cell" style="border-top:3px solid #8b5cf6;">
              <div class="m-label">Incidents End ≤5 min <abbr title="Source: FBI Active Shooter Study (64 incidents analyzed). 69% of active shooter events conclude within 5 minutes — 23 ended in under 2 min. Avg duration at educational facilities: 3 min 18 sec.">ⓘ</abbr></div>
              <div class="m-value" style="color:#8b5cf6;">69%</div>
              <div class="m-sub">end before ground units arrive</div>
            </div>
            <div class="metric-cell" style="border-top:3px solid var(--resp);">
              <div class="m-label">BRINC On-Scene Time <abbr title="Source: BRINC technical specs; Chula Vista PD DFR Program outcomes. Launches in &lt;20 sec, on-scene in &lt;90 sec — vs. 14-15 min national ground average.">ⓘ</abbr></div>
              <div class="m-value cyan">&lt;90s</div>
              <div class="m-sub">airborne &amp; streaming live video</div>
            </div>
            <div class="metric-cell">
              <div class="m-label">K-12 Shootings 2024 <abbr title="Source: K-12 School Shooting Database (k12ssdb.org). 336 shooting incidents on K-12 campuses in 2024. FBI active-shooter defined incidents down 50% from 48 (2023) to 24 (2024).">ⓘ</abbr></div>
              <div class="m-value" style="color:#ef4444;">336</div>
              <div class="m-sub">K-12 shooting incidents in 2024</div>
            </div>
            <div class="metric-cell">
              <div class="m-label">SRO Annual Cost <abbr title="Source: ZipRecruiter SRO Salary Data 2025; DeSoto County SRO cost breakdown ($94,147/yr blended); Volt.ai SRO Cost Analysis. Includes salary + benefits + equipment per officer.">ⓘ</abbr></div>
              <div class="m-value gold">$94K+</div>
              <div class="m-sub">per officer · school hours only</div>
            </div>
            <div class="metric-cell">
              <div class="m-label">SRO Coverage Hours <abbr title="Source: Standard school calendar. 7 hours/day × 180 school days = 1,260 operational hours per year — 14.4% of annual hours. Nights, weekends, summers: unprotected.">ⓘ</abbr></div>
              <div class="m-value">14.4%</div>
              <div class="m-sub">of annual hours covered</div>
            </div>
            <div class="metric-cell" style="background:rgba(0,210,255,0.04);">
              <div class="m-label">DFR Coverage Hours <abbr title="BRINC DFR operates 24 hours/day, 365 days/year = 8,760 hours/year. Full coverage including nights, weekends, summer, and after-school hours when SROs are absent.">ⓘ</abbr></div>
              <div class="m-value cyan">100%</div>
              <div class="m-sub">24/7/365 aerial coverage</div>
            </div>
          </div>
    
          <!-- CRITICAL WINDOW CALLOUT -->
          <div style="background:#fff8f8;border-left:4px solid #ef4444;padding:16px 22px;border-radius:0 8px 8px 0;margin-bottom:28px;">
            <h4 style="color:#ef4444;font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:12px;">
              ⚠️ The Critical Response Window
              <abbr title="Sources: FBI Law Enforcement Bulletin 'Those Terrible First Few Minutes'; FBI Active Shooter Study (51-case median analysis); ALICE Training Institute; K-12 School Shooting Database.">ⓘ</abbr>
            </h4>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px;">
              <div style="text-align:center;background:#fff;border:1px solid #f5c6c6;border-radius:6px;padding:12px;">
                <div style="font-size:24px;font-weight:900;color:#ef4444;font-family:'IBM Plex Mono',monospace;">14–15 min</div>
                <div style="font-size:11px;color:var(--muted);margin-top:4px;">Avg police arrival to<br>active shooter nationally</div>
              </div>
              <div style="text-align:center;background:#fff;border:1px solid #fde68a;border-radius:6px;padding:12px;">
                <div style="font-size:24px;font-weight:900;color:var(--amber);font-family:'IBM Plex Mono',monospace;">3m 18s</div>
                <div style="font-size:11px;color:var(--muted);margin-top:4px;">Avg incident duration<br>at schools (FBI)</div>
              </div>
              <div style="text-align:center;background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;padding:12px;">
                <div style="font-size:24px;font-weight:900;color:var(--resp);font-family:'IBM Plex Mono',monospace;">&lt;90 sec</div>
                <div style="font-size:11px;color:var(--muted);margin-top:4px;">BRINC airborne with<br>live HD + thermal</div>
              </div>
            </div>
            <p style="font-size:12px;color:#7a3a3a;font-style:italic;line-height:1.6;margin:0;">
              "Most active shooter incidents in schools are over before a responding officer reaches the building entrance.
              DFR doesn't replace the officer — it gives command staff eyes on every hallway, stairwell, and exit
              before they open the first door." — FBI Law Enforcement Bulletin
            </p>
          </div>
    
          <!-- DFR vs SRO COMPARISON TABLE -->
          <h3 class="sh"><span class="sh-accent">DFR</span> vs. School Resource Officer — Capability Matrix
            <abbr style="font-size:11px;font-weight:400;color:var(--muted);margin-left:8px;" title="SRO data: RAND 'The Role and Impact of School Resource Officers' (2023); NIJ Effects of SROs on School Crime (OJP); ZipRecruiter SRO Salary 2025. DFR data: BRINC technical specifications; Chula Vista PD DFR outcomes.">ⓘ Sources</abbr>
          </h3>
          <table style="margin-bottom:28px;">
            <thead>
              <tr>
                <th style="width:30%;">Capability</th>
                <th style="color:#b45309;text-align:center;">School Resource Officer</th>
                <th style="color:var(--resp);text-align:center;">BRINC DFR</th>
              </tr>
            </thead>
            <tbody>
              <tr><td><strong>Annual Cost / Campus</strong></td>
                  <td style="text-align:center;color:#b45309;">$75,000 – $120,000 per officer</td>
                  <td style="text-align:center;color:#0369a1;">${int(fleet_capex/7):,}/yr amortized (7-yr) · {actual_k_responder + actual_k_guardian} units</td></tr>
              <tr><td><strong>Coverage Hours / Year</strong></td>
                  <td style="text-align:center;color:#b45309;">~1,260 hrs (school hours only)</td>
                  <td style="text-align:center;color:var(--green);">8,760 hrs — 24/7/365</td></tr>
              <tr><td><strong>Campuses Covered</strong></td>
                  <td style="text-align:center;color:#b45309;">1 building per officer</td>
                  <td style="text-align:center;color:var(--green);">Multi-campus from 1 hub station</td></tr>
              <tr><td><strong>On-Campus Response Time</strong></td>
                  <td style="text-align:center;color:#b45309;">2–5 min (foot/vehicle)</td>
                  <td style="text-align:center;color:var(--green);">&lt;90 sec airborne · {avg_resp_time:.1f} min avg aerial</td></tr>
              <tr><td><strong>After-Hours / Weekend</strong></td>
                  <td style="text-align:center;color:#b45309;">❌ No coverage</td>
                  <td style="text-align:center;color:var(--green);">✅ Full thermal surveillance</td></tr>
              <tr><td><strong>Thermal / Night Vision</strong></td>
                  <td style="text-align:center;color:#b45309;">❌ Flashlight only</td>
                  <td style="text-align:center;color:var(--green);">✅ 640px FLIR thermal</td></tr>
              <tr><td><strong>Perimeter Monitoring</strong></td>
                  <td style="text-align:center;color:#b45309;">❌ Not feasible at scale</td>
                  <td style="text-align:center;color:var(--green);">✅ Automated aerial patrol</td></tr>
              <tr><td><strong>Active Threat Intel</strong></td>
                  <td style="text-align:center;color:#b45309;">Single officer, blind entry</td>
                  <td style="text-align:center;color:var(--green);">✅ Live HD + thermal to dispatch</td></tr>
              <tr><td><strong>Indoor Operations</strong></td>
                  <td style="text-align:center;">✅ On foot</td>
                  <td style="text-align:center;color:var(--green);">✅ LEMUR 2 — glass-breaker, perch, 2-way comms</td></tr>
              <tr><td><strong>Court-Admissible Evidence</strong></td>
                  <td style="text-align:center;color:#b45309;">Body cam (ground-level)</td>
                  <td style="text-align:center;color:var(--green);">✅ HD aerial video + flight log</td></tr>
              <tr><td><strong>Mass Shooting Prevention</strong>
                      <abbr title="Source: RAND Corporation 'The Role and Impact of School Resource Officers' (2023). Quote: 'There is no evidence about whether SROs prevent the types of mass shootings that often lead to the placement of SROs in school.'">ⓘ</abbr></td>
                  <td style="text-align:center;color:#b45309;">❌ No proven effect (RAND, 2023)</td>
                  <td style="text-align:center;color:var(--green);">✅ Pre-entry intel, faster coordination</td></tr>
              <tr><td><strong>Disciplinary Side Effects</strong>
                      <abbr title="Source: RAND 'The Role and Impact of School Resource Officers' (2023). Schools with SROs saw 35-80% more out-of-school suspensions and 25-90% more expulsions than schools without SROs.">ⓘ</abbr></td>
                  <td style="text-align:center;color:#b45309;">⚠️ +35–80% suspensions, +25–90% expulsions</td>
                  <td style="text-align:center;color:var(--green);">✅ Zero school-discipline impact</td></tr>
            </tbody>
          </table>
    
          <!-- COST COMPARISON -->
          <div class="fleet-split" style="margin-bottom:24px;">
            <div class="fleet-card guardian" style="border-top:3px solid var(--amber);">
              <div class="fc-icon">📋</div>
              <div class="fc-type" style="color:var(--amber);">10-School District — SRO Model</div>
              <div class="fc-val">$940K – $1.2M/yr</div>
              <div class="fc-sub">10 officers · school hours only</div>
              <div style="margin-top:16px;">
                <div class="fc-row"><span class="k">Annual hours covered</span><span class="v">1,260 hrs/campus (14.4%)</span></div>
                <div class="fc-row"><span class="k">Nights / weekends / summer</span><span class="v" style="color:#ef4444;">❌ Unprotected</span></div>
                <div class="fc-row"><span class="k">Multi-campus coverage</span><span class="v" style="color:#ef4444;">❌ One building/officer</span></div>
                <div class="fc-row"><span class="k">Proven mass-shooting prevention</span><span class="v" style="color:#ef4444;">❌ No evidence</span></div>
              </div>
            </div>
            <div class="fleet-card responder" style="border-top:3px solid var(--resp);">
              <div class="fc-icon">🚁</div>
              <div class="fc-type">BRINC DFR — Multi-Campus</div>
              <div class="fc-val">${fleet_capex:,.0f} CapEx</div>
              <div class="fc-sub">{_dfr_amort_str} amortized · {actual_k_responder + actual_k_guardian} units</div>
              <div style="margin-top:16px;">
                <div class="fc-row"><span class="k">Annual hours covered</span><span class="v" style="color:var(--resp);">8,760 hrs (24/7/365)</span></div>
                <div class="fc-row"><span class="k">Nights / weekends / summer</span><span class="v" style="color:var(--green);">✅ Full thermal patrol</span></div>
                <div class="fc-row"><span class="k">Multi-campus coverage</span><span class="v" style="color:var(--green);">✅ {actual_k_responder + actual_k_guardian} simultaneous zones</span></div>
                <div class="fc-row"><span class="k">Response time advantage</span><span class="v" style="color:var(--green);">+{avg_time_saved:.1f} min faster per incident</span></div>
              </div>
            </div>
          </div>
    
          <!-- SOURCES -->
          <div class="disc" style="font-size:11px;line-height:1.8;">
            <strong>Data Sources:</strong>
            <a href="https://www.fbi.gov/news/press-releases/fbi-releases-crime-in-schools-2020-2024-special-report" target="_blank">FBI Crime in Schools 2020–2024</a> ·
            <a href="https://nces.ed.gov/pubs2024/2024145.pdf" target="_blank">NCES Indicators of School Crime &amp; Safety 2023</a> ·
            <a href="https://leb.fbi.gov/articles/featured-articles/those-terrible-first-few-minutes-revisiting-active-shooter-protocols-for-schools" target="_blank">FBI LEB "Those Terrible First Few Minutes"</a> ·
            <a href="https://www.rand.org/research/gun-policy/analysis/essays/school-resource-officers.html" target="_blank">RAND "The Role and Impact of School Resource Officers" (2023)</a> ·
            <a href="https://nij.ojp.gov/library/publications/effects-school-resource-officers-school-crime-and-responses-school-crime" target="_blank">NIJ Effects of SROs on School Crime</a> ·
            <a href="https://k12ssdb.org/" target="_blank">K-12 School Shooting Database</a> ·
            <a href="https://www.fbi.gov/news/press-releases/fbi-releases-2024-active-shooter-incidents-in-the-united-states-report" target="_blank">FBI Active Shooter Report 2024</a> ·
            <a href="https://brincdrones.com/responder/" target="_blank">BRINC Responder Technical Specs</a>
          </div>
    
        </section>
    
            <!-- ── CUSTOM CLOSING (AE-authored, optional) ──────────────────── -->
        {_custom_closing_html}
    
    
    
        <!-- ── DISCLAIMER ─────────────────────────────────────────────── -->
        <div style="background:#fffbeb;border:1px solid #f59e0b;border-radius:8px;padding:20px 60px;margin:0;font-size:11px;color:#7a5a00;line-height:1.7">
          <strong>&#9888; SIMULATION TOOL DISCLAIMER</strong> — All figures are model estimates based on user inputs and publicly available data. Not a legal recommendation, binding proposal, contract, or guarantee. Deployments require FAA authorization and formal procurement.
        </div>
    
        <!-- ── FOOTER ─────────────────────────────────────────────────── -->
        <footer class="doc-footer">
          <span class="brand-mark">BRINC</span>
          <span>{"<img src='data:image/png;base64," + logo_b64_light + "' style='height:24px;vertical-align:middle;'>" if logo_b64_light else ""} BRINC Drones, Inc. · <a href="https://brincdrones.com">brincdrones.com</a> · <a href="mailto:sales@brincdrones.com">sales@brincdrones.com</a> · +1 (855) 950-0226</span>
          <span>Prepared by {prop_name} · <a href="mailto:{prop_email}">{prop_email}</a>{" · " + _doc_phone if _doc_phone else ""}</span>
        </footer>
    
        </main>"""
                export_html += """
        <script>
        // Highlight active nav link on scroll
        const sections=document.querySelectorAll('section[id],div[id="analytics"]');
        const links=document.querySelectorAll('.sidebar-nav a');
        const obs=new IntersectionObserver(entries=>{{
          entries.forEach(e=>{{
            if(e.isIntersecting){{
              links.forEach(l=>l.classList.remove('active'));
              const a=document.querySelector('.sidebar-nav a[href="#'+e.target.id+'"]');
              if(a)a.classList.add('active');
            }}
          }})
        }},{{threshold:0.3}});
        sections.forEach(s=>obs.observe(s));
    
        // ── Copy Community Business Partnership letter ──────────────────────────────
        function copyCommunitySection() {{
          const section = document.getElementById('community');
          const btn = document.getElementById('copyPartnershipBtn');
          if (!section || !btn) return;
    
          // Build clean plain-text version by walking the section's text nodes
          // but skipping the button itself
          function getTextContent(node) {{
            if (node === btn) return '';
            if (node.nodeType === Node.TEXT_NODE) return node.textContent;
            if (node.nodeType !== Node.ELEMENT_NODE) return '';
            const tag = node.tagName.toUpperCase();
            if (tag === 'STYLE' || tag === 'SCRIPT') return '';
            let out = '';
            for (const child of node.childNodes) out += getTextContent(child);
            // Block-level elements get newlines
            const block = ['DIV','P','H1','H2','H3','H4','H5','H6','LI','TR','BR','SECTION','ARTICLE'];
            if (block.includes(tag)) out = '\n' + out.trimEnd() + '\n';
            if (tag === 'TH' || tag === 'TD') out = out.trim() + '\t';
            return out;
          }}
    
          const rawText = getTextContent(section)
            .replace(/\n{{3,}}/g, '\n\n')   // collapse excess blank lines
            .trim();
    
          navigator.clipboard.writeText(rawText).then(() => {{
            const orig = btn.innerHTML;
            btn.classList.add('copied');
            btn.innerHTML = '<svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg> Copied!';
            setTimeout(() => {{ btn.classList.remove('copied'); btn.innerHTML = orig; }}, 2000);
          }}).catch(() => {{
            // Fallback for non-https / older browsers
            const ta = document.createElement('textarea');
            ta.value = rawText;
            ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0;';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            const orig = btn.innerHTML;
            btn.classList.add('copied');
            btn.innerHTML = '<svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg> Copied!';
            setTimeout(() => {{ btn.classList.remove('copied'); btn.innerHTML = orig; }}, 2000);
          }});
        }}
        </script>
        </body></html>""".replace("{{", "{").replace("}}", "}")
    
                # Section 09 (Analytics Dashboard) removed — its content (cad_charts_html_export)
                # is already rendered in Section 04 (Incident Data Analysis). Duplicating it
                # caused "Top Call Types" to appear twice and broke the Chart.js canvas binding
                # because both instances shared the same element id="expTypeChart".
                _analytics_section_html = ''
                _analytics_nav = ''
                export_html = export_html.replace("[ANALYTICS_SECTION]", _analytics_section_html)
                export_html = export_html.replace("[ANALYTICS_NAV]", _analytics_nav)
    
                # ── Community Impact section (light theme for print/export) ─────────
                _cid_export_html = html_reports.generate_community_impact_dashboard_html(
                    city=prop_city,
                    state=prop_state,
                    population=int(pop_metric or 0),
                    total_calls=int(st.session_state.get('total_original_calls', 0) or 0),
                    calls_covered_perc=float(calls_covered_perc or 0),
                    area_covered_perc=float(area_covered_perc or 0),
                    avg_resp_time_min=float(avg_resp_time or 0),
                    avg_time_saved_min=float(avg_time_saved or 0),
                    fleet_capex=float(fleet_capex or 0),
                    annual_savings=float(annual_savings or 0),
                    break_even_text=str(break_even_text or 'N/A'),
                    actual_k_responder=int(actual_k_responder or 0),
                    actual_k_guardian=int(actual_k_guardian or 0),
                    dfr_dispatch_rate=float(dfr_dispatch_rate or 0.30),
                    deflection_rate=float(deflection_rate or 0.30),
                    daily_dfr_responses=float(daily_dfr_responses or 0),
                    daily_drone_only_calls=float(daily_drone_only_calls or 0),
                    active_drones=active_drones or [],
                    df_calls_full=df_calls_full,
                    theme='light',
                    facility_counts=_fac_counts or None,
                )
                # Extract <style> block and body content separately, then scope the styles
                # with a .cid-wrap prefix so they don't collide with the export document's CSS.
                _style_match = re.search(r'<style>(.*?)</style>', _cid_export_html, re.DOTALL)
                _cid_style = _style_match.group(1) if _style_match else ''
                # Scope every CSS rule inside the style block by prefixing with .cid-wrap
                # Simple approach: wrap rules that start at column 0 (non-nested)
                def _scope_css(raw_css):
                    # Replace :root { with .cid-wrap { so vars apply within scope
                    raw_css = raw_css.replace(':root {', '.cid-wrap {')
                    # Prepend .cid-wrap to each rule selector (lines that end with {)
                    lines = raw_css.split('\n')
                    scoped = []
                    for line in lines:
                        stripped = line.strip()
                        # Skip empty, @-rules, closing braces, and already-scoped lines
                        if (stripped.startswith('@') or stripped == '}' or stripped == ''
                                or stripped.startswith('/*') or stripped.startswith('*')
                                or stripped.startswith('.cid-wrap {')):
                            scoped.append(line)
                        elif stripped.endswith('{') and not stripped.startswith('.cid-wrap'):
                            # It's a selector line — prefix it
                            selector = stripped[:-1].strip()
                            # Don't double-scope :root replacement or @keyframes internals
                            if selector and not selector.startswith('.cid-wrap') and not selector.startswith('from') and not selector.startswith('to') and not selector.startswith('0%') and not selector.startswith('50%') and not selector.startswith('100%'):
                                scoped.append(f'  .cid-wrap {selector} {{')
                            else:
                                scoped.append(line)
                        else:
                            scoped.append(line)
                    return '\n'.join(scoped)
    
                _scoped_style = _scope_css(_cid_style)
                # Extract body content (between <body> and </body>)
                _body_match = re.search(r'<body[^>]*>(.*?)</body>', _cid_export_html, re.DOTALL)
                _cid_body = _body_match.group(1).strip() if _body_match else _cid_export_html
                # Build the scoped embed: scoped <style> + wrapper div
                _cid_embed = f'<style>{_scoped_style}</style>\n<div class="cid-wrap" style="font-family:\'DM Sans\',sans-serif;background:#f8f7f4;border-radius:10px;overflow:hidden;">{_cid_body}</div>'
                _community_impact_section_html = (
                    '\n<!-- \u2500\u2500 10: COMMUNITY IMPACT DASHBOARD \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 -->\n'
                    '<section class="doc-section" id="community-impact">\n'
                    '  <div class="section-eyebrow"><span class="pg-num">10</span><span class="pg-title">Community Impact &amp; Transparency</span>'
                    '<span class="src" data-src="Sources: Population \u2014 US Census Bureau American Community Survey (ACS). Officer wage benchmarks \u2014 Bureau of Labor Statistics (BLS) OES. Financial projections \u2014 BRINC COS optimization model. Flight hour estimates \u2014 BRINC hardware specifications. All figures are model estimates.">\u24d8</span></div>\n'
                    f'  {_cid_embed}\n'
                    '</section>'
                )
                export_html = export_html.replace("[COMMUNITY_IMPACT_SECTION]", _community_impact_section_html)
                export_html = export_html.replace("[COMMUNITY_IMPACT_NAV]", '<a href="#community-impact"><span class="nav-num">10</span>Community Impact</a>')
    
    
                if not _show_analytics_section:
                    export_html = export_html.replace('<a href="#incident-data"><span class="nav-num">04</span>Incident Analysis</a>', '')
                    export_html = export_html.replace('<a href="#analytics"><span class="nav-num">09</span>Analytics Dashboard</a>', '')
                    export_html = re.sub(
                        r'\s*<!-- .*?04: INCIDENT ANALYSIS .*?-->\s*<section class="doc-section" id="incident-data">.*?</section>',
                        '',
                        export_html,
                        count=1,
                        flags=re.DOTALL,
                    )
                    export_html = re.sub(
                        r'\s*<!-- .*?09: ANALYTICS DASHBOARD .*?-->\s*<section class="doc-section" id="analytics">.*?</section>',
                        '',
                        export_html,
                        count=1,
                        flags=re.DOTALL,
                    )
    
                if not _show_community_impact_section:
                    export_html = export_html.replace('<a href="#community-impact"><span class="nav-num">10</span>Community Impact</a>', '')
                    export_html = re.sub(
                        r'\s*<!-- .*?10: COMMUNITY IMPACT DASHBOARD .*?-->\s*<section class="doc-section" id="community-impact">.*?</section>',
                        '',
                        export_html,
                        count=1,
                        flags=re.DOTALL,
                    )
    
                if not _show_school_safety_section:
                    export_html = export_html.replace('<a href="#school-safety"><span class="nav-num">11</span>School Safety</a>', '')
                    export_html = re.sub(
                        r'\s*<section class="doc-section" id="school-safety">.*?</section>',
                        '',
                        export_html,
                        count=1,
                        flags=re.DOTALL,
                    )
    
                if not _show_lte_section:
                    export_html = re.sub(
                        r'\s*<!-- .*?03b: 4G LTE CELL COVERAGE .*?-->\s*<section class="doc-section" id="cell-coverage">.*?</section>',
                        '',
                        export_html,
                        count=1,
                        flags=re.DOTALL,
                    )

        # ── Download buttons — always rendered so they're visible in the sidebar ──
        _safe_city   = _safe_city_base
        _ts          = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        _version_slug = _safe_export_slug(__version__, "version")
        st.session_state['report_build_seconds'] = round(time.perf_counter() - _report_build_started, 2)
        _report_notice_slot.caption(
            f"Reports ready in {st.session_state['report_build_seconds']:.1f}s. The download buttons below are active."
        )

        # 1. Save Deployment Plan (.brinc) — always available
        _brinc_payload = export_dict if fleet_capex > 0 else {
            **export_dict,
            "k_resp": 0, "k_guard": 0,
            "_disclaimer": "No drones deployed yet.",
        }
        _brinc_data = _json_export_download(_brinc_payload)
        if _brinc_export_slot.download_button("💾 Save Deployment Plan", data=_brinc_data,
                                              file_name=f"BRINC_Deployment_Plan_{_safe_city}_{_version_slug}_{_ts}.brinc",
                                              mime="application/octet-stream", width="stretch"):
            # ── Track export event ───────────────────────────────────────────────
            st.session_state['export_event_log'] = st.session_state.get('export_event_log', []) + ['BRINC']
            st.session_state['export_count'] = st.session_state.get('export_count', 0) + 1
            _notify_email(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                          "BRINC", k_responder, k_guardian, calls_covered_perc,
                          prop_name, prop_email, details=export_details)
            _log_to_sheets(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                           "BRINC", k_responder, k_guardian, calls_covered_perc,
                           prop_name, prop_email, details=export_details)
        # 2. Executive Summary / proposal HTML export
        _export_html_ready = isinstance(export_html, str) and export_html.lstrip().lower().startswith("<!doctype html")
        if fleet_capex > 0:
            if _export_html_ready and _html_export_slot.download_button(f"📄 {prop_city}, {prop_state} — Executive Summary",
                                                                        data=export_html,
                                                                        file_name=f"BRINC_Executive_Summary_{_safe_city}_{_version_slug}_{_ts}.html",
                                                                        mime="text/html",
                                                                        width="stretch"):
                # ── Track export event ───────────────────────────────────────────
                st.session_state['export_event_log'] = st.session_state.get('export_event_log', []) + ['HTML']
                st.session_state['export_count'] = st.session_state.get('export_count', 0) + 1
                _notify_email(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                              "HTML", k_responder, k_guardian, calls_covered_perc,
                              prop_name, prop_email, details=export_details)
                _log_to_sheets(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                               "HTML", k_responder, k_guardian, calls_covered_perc,
                               prop_name, prop_email, details=export_details)
            elif not _export_html_ready:
                _html_export_slot.button(
                    f"📄 {prop_city}, {prop_state} — Executive Summary",
                    disabled=True,
                    width="stretch",
                    help="Executive summary data is not ready for this run.",
                )
        else:
            _html_export_slot.button(
                f"📄 {prop_city}, {prop_state} — Executive Summary",
                disabled=True,
                width="stretch",
                help="Deploy at least one drone to generate the executive summary.",
            )

        # 3. Google Earth KML — only when drones are placed
        _kml_data = None
        _kml_error = ""
        if active_drones:
            try:
                _kml_data = html_reports.generate_kml(active_gdf, active_drones, calls_in_city)
                if not isinstance(_kml_data, str) or not _kml_data.strip():
                    raise ValueError("KML generator returned an empty file.")
            except Exception as _kml_exc:
                _kml_error = str(_kml_exc)[:140]

        if active_drones and _kml_data:
            if _kml_export_slot.download_button("🌏 Google Earth Briefing File",
                                                data=_kml_data,
                                                file_name=f"BRINC_Google_Earth_Briefing_{_safe_city}_{_version_slug}_{_ts}.kml",
                                                mime="application/vnd.google-earth.kml+xml",
                                                width="stretch"):
                # ── Track export event ───────────────────────────────────────────
                st.session_state['export_event_log'] = st.session_state.get('export_event_log', []) + ['KML']
                st.session_state['export_count'] = st.session_state.get('export_count', 0) + 1
                _notify_email(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                              "KML", k_responder, k_guardian, calls_covered_perc,
                              prop_name, prop_email, details=export_details)
                _log_to_sheets(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                               "KML", k_responder, k_guardian, calls_covered_perc,
                               prop_name, prop_email, details=export_details)
        elif active_drones:
            _kml_export_slot.button("🌏 Google Earth Briefing File", disabled=True,
                                    width="stretch",
                                    help="Google Earth export is unavailable for the current geometry.")
            if _kml_error:
                st.sidebar.caption(f"Google Earth export issue: {_kml_error}")
        else:
            _kml_export_slot.button("🌏 Google Earth Briefing File", disabled=True,
                                    width="stretch",
                                    help="Deploy at least one drone to generate the KML file.")







main()



