"""
Session-state helpers for the Streamlit app.
"""

import datetime
import uuid


DEFAULTS = {
    "csvs_ready": False,
    "df_calls": None,
    "df_calls_full": None,
    "df_stations": None,
    "active_city": "Rockford",
    "active_state": "IL",
    "estimated_pop": 0,
    "_pop_resolved": False,
    "k_resp": 2,
    "k_guard": 0,
    "r_resp": 2.0,
    "r_guard": 8.0,
    "dfr_rate": 25,
    "deflect_rate": 30,
    "total_original_calls": 0,
    "total_modeled_calls": 0,
    "onboarding_done": False,
    "trigger_sim": False,
    "city_count": 1,
    "brinc_user": "",
    "session_start": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "session_id": str(uuid.uuid4())[:8],
    "public_report_id": "",
    "public_report_url": "",
    "data_source": "unknown",
    "map_build_logged": False,
    "boundary_kind": "place",
    "boundary_source_path": "",
    "location_detection_source": "",
    "boundary_detection_mode": "",
    "master_gdf_override": None,
    "boundary_overlay_gdf": None,
    "boundary_overlay_name": "",
    "boundary_overlay_file": "",
    "file_meta": {},
    "export_event_log": [],
    "export_count": 0,
    "report_build_seconds": None,
    "show_rapid_response_ring_b": True,
    "demo_mode_used": False,
    "sim_mode_used": False,
    "pin_drop_mode": False,
    "pending_pin": None,
    "pin_drop_used": False,
    "doc_custom_intro": "",
    "doc_talking_pt_1": "",
    "doc_talking_pt_2": "",
    "doc_talking_pt_3": "",
    "doc_custom_closing": "",
    "doc_ae_phone": "",
    "inferred_daily_calls_override": None,
    "census_pending": False,
    "census_source_signature": "",
    "census_stage_df": None,
    "census_original_df": None,
    "census_partial_calls_df": None,
    "census_batch_zip_bytes": b"",
    "census_batch_zip_name": "",
    "census_sample_bytes": b"",
    "census_sample_name": "",
    "census_summary": {},
    "census_conversion_summary": {},
    "census_corrected_bytes": b"",
    "census_corrected_name": "",
    "census_corrected_format": "csv",
    "census_download_notice": False,
}


def init_session_state(session_state, slugify, build_public_report_url) -> None:
    for key, value in DEFAULTS.items():
        if key not in session_state:
            session_state[key] = value

    if not session_state.get("public_report_id"):
        city_slug = slugify(session_state.get("active_city", "report"))
        public_token = uuid.uuid4().hex[:16]
        session_state["public_report_id"] = f"{city_slug}-{public_token}"

    _built_public_report_url = build_public_report_url(session_state["public_report_id"])
    _current_public_report_url = str(session_state.get("public_report_url", "") or "").strip()
    if (not _current_public_report_url) or (
        "script.google.com" in _built_public_report_url and "script.google.com" not in _current_public_report_url
    ):
        session_state["public_report_url"] = _built_public_report_url

    if "target_cities" not in session_state:
        session_state["target_cities"] = [
            {"city": "", "state": session_state.get("active_state", "IL")}
        ]
