"""Admin dashboard and session management functions."""
import datetime
import html
import os
import re
import streamlit as st
import textwrap
import threading
import time

# Module-level session tracking
_ACTIVE_SESSION_LOCK = threading.RLock()
_ACTIVE_SESSION_REGISTRY = {}
_ACTIVE_SESSION_TTL_SECONDS = 150

# Import required helper
def _get_query_params_dict():
    """Get query parameters from Streamlit. Placeholder if not available."""
    try:
        from modules.public_reports import _get_query_params_dict as _get_qpd
        return _get_qpd()
    except Exception:
        return {}

def _get_admin_dashboard_emails():
    _raw_values = []
    try:
        _secret_value = st.secrets.get("ADMIN_DASHBOARD_EMAILS", "")
        if isinstance(_secret_value, str):
            _raw_values.append(_secret_value)
        elif isinstance(_secret_value, (list, tuple, set)):
            _raw_values.extend(str(_item) for _item in _secret_value)
        _single_value = st.secrets.get("ADMIN_DASHBOARD_EMAIL", "")
        if _single_value:
            _raw_values.append(str(_single_value))
    except Exception:
        pass

    _env_value = os.getenv("BRINC_ADMIN_DASHBOARD_EMAILS", "")
    if _env_value:
        _raw_values.append(_env_value)

    _emails = set()
    for _chunk in _raw_values:
        for _email in re.split(r"[,\s;]+", str(_chunk).strip()):
            _email = _email.strip().lower()
            if _email:
                _emails.add(_email)
    _emails.add("steven.beltran@brincdrones.com")
    return _emails


def _is_admin_dashboard_user() -> bool:
    _email = str(st.session_state.get("google_user_email", "") or getattr(st.user, "email", "") or "").strip().lower()
    if not _email:
        return False
    return _email in _get_admin_dashboard_emails()


def _apply_admin_fast_jump():
    _params = _get_query_params_dict()
    _jump = str(_params.get("admin_jump", "") or "").strip().lower()
    if not _jump:
        return False
    if not _is_admin_dashboard_user():
        return False

    if _jump == "rockford_il":
        st.session_state["active_city"] = "Rockford"
        st.session_state["active_state"] = "IL"
        st.session_state["target_cities"] = [{"city": "Rockford", "state": "IL"}]
        st.session_state["city_count"] = 1
        st.session_state["use_county_boundary"] = False
        st.session_state["boundary_kind"] = "place"
        st.session_state["boundary_source_path"] = ""
        st.session_state["location_detection_source"] = "admin_fast_jump"
        st.session_state["boundary_detection_mode"] = "admin_fast_jump"
        st.session_state["master_gdf_override"] = None
        st.session_state["boundary_overlay_gdf"] = None
        st.session_state["boundary_overlay_name"] = ""
        st.session_state["boundary_overlay_file"] = ""
        st.session_state["trigger_sim"] = False
        if st.session_state.get("df_calls") is not None and st.session_state.get("df_stations") is not None:
            st.session_state["csvs_ready"] = True
        try:
            st.query_params.clear()
        except Exception:
            pass
        return True

    return False


_apply_admin_fast_jump()


def _prune_active_sessions(now=None):
    _now = now or datetime.datetime.now(datetime.timezone.utc)
    _cutoff = _now - datetime.timedelta(seconds=_ACTIVE_SESSION_TTL_SECONDS)
    with _ACTIVE_SESSION_LOCK:
        _stale = [sid for sid, meta in _ACTIVE_SESSION_REGISTRY.items() if meta.get("last_seen") and meta["last_seen"] < _cutoff]
        for sid in _stale:
            _ACTIVE_SESSION_REGISTRY.pop(sid, None)
        return sorted(_ACTIVE_SESSION_REGISTRY.values(), key=lambda item: item.get("last_seen", _now), reverse=True)


def _track_active_session():
    if not st.session_state.get("_oauth_logged", False):
        return

    _session_id = str(st.session_state.get("session_id", "") or "").strip()
    if not _session_id:
        return

    _now = datetime.datetime.now(datetime.timezone.utc)
    _headers = {}
    try:
        _headers = dict(st.context.headers)
    except Exception:
        _headers = {}

    _user_email = str(st.session_state.get("google_user_email", "") or getattr(st.user, "email", "") or "").strip().lower()
    _user_name = str(st.session_state.get("google_user_name", "") or getattr(st.user, "name", "") or _user_email.split("@")[0]).strip()
    _page_url = ""
    try:
        _page_url = str(st.context.url or "").strip()
    except Exception:
        _page_url = ""

    _meta = {
        "session_id": _session_id,
        "email": _user_email,
        "name": _user_name,
        "city": str(st.session_state.get("active_city", "") or "").strip(),
        "state": str(st.session_state.get("active_state", "") or "").strip(),
        "page": _page_url,
        "ip": str(
            _headers.get("X-Forwarded-For", "")
            or _headers.get("x-forwarded-for", "")
            or _headers.get("Remote-Addr", "")
            or getattr(st.context, "ip_address", "")
            or ""
        ).strip(),
        "user_agent": str(_headers.get("User-Agent", _headers.get("user-agent", "")) or "").strip(),
        "last_seen": _now,
    }

    with _ACTIVE_SESSION_LOCK:
        _ACTIVE_SESSION_REGISTRY[_session_id] = _meta
    _prune_active_sessions(_now)


def _render_live_admin_dashboard():
    if not _is_admin_dashboard_user():
        return

    _active_sessions = _prune_active_sessions()
    _current_session_id = str(st.session_state.get("session_id", "") or "").strip()
    _has_other_sessions = any(
        str(_item.get("session_id", "") or "").strip() != _current_session_id
        for _item in _active_sessions
    )
    _pill_accent = "rgba(255, 77, 77, 0.92)" if _has_other_sessions else "rgba(0, 255, 170, 0.72)"
    _pill_accent_soft = "rgba(255, 77, 77, 0.18)" if _has_other_sessions else "rgba(0, 255, 170, 0.14)"
    _pill_accent_text = "#ff9b9b" if _has_other_sessions else "#7cffc9"
    _pill_bg_top = "rgba(34, 7, 10, 0.98)" if _has_other_sessions else "rgba(10, 20, 10, 0.98)"
    _pill_bg_bottom = "rgba(22, 6, 8, 0.96)" if _has_other_sessions else "rgba(6, 14, 8, 0.96)"
    _pill_hover_top = "rgba(46, 10, 14, 0.99)" if _has_other_sessions else "rgba(12, 30, 18, 0.99)"
    _pill_hover_bottom = "rgba(28, 7, 10, 0.98)" if _has_other_sessions else "rgba(7, 16, 10, 0.98)"
    _pill_shadow = "rgba(255, 77, 77, 0.16)" if _has_other_sessions else "rgba(0, 255, 170, 0.14)"
    _pill_shadow_hover = "rgba(255, 77, 77, 0.22)" if _has_other_sessions else "rgba(0, 255, 170, 0.2)"
    _panel_border = "rgba(255, 77, 77, 0.26)" if _has_other_sessions else "rgba(0, 255, 170, 0.22)"
    _count = len(_active_sessions)
    _rows = []
    for _item in _active_sessions[:12]:
        _seen = _item.get("last_seen")
        _seen_text = _seen.strftime("%H:%M:%S UTC") if isinstance(_seen, datetime.datetime) else "?"
        _rows.append(
            f'<div class="live-admin-row"><div class="live-admin-main"><div class="live-admin-user">{html.escape(_item.get("name") or _item.get("email") or "Unknown")}</div><div class="live-admin-meta">{html.escape(_item.get("email") or "—")} · session {html.escape(_item.get("session_id") or "—")}</div><div class="live-admin-meta">{html.escape(_item.get("city") or "—")}, {html.escape(_item.get("state") or "—")} · {html.escape(_item.get("page") or "current app")}</div></div><div class="live-admin-seen">{html.escape(_seen_text)}</div></div>'
        )

    if not _rows:
        _rows_html = '<div class="live-admin-empty">No active sessions detected yet.</div>'
    else:
        _rows_html = "".join(_rows)

    _stale_seconds = int(_ACTIVE_SESSION_TTL_SECONDS)
    st.markdown(
        textwrap.dedent(f"""
        <style>
        .live-admin-inline {{
            width: 100%;
            max-width: 680px;
            margin: 14px auto 0;
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            position: relative;
        }}
        .live-admin-dock {{
            display: flex;
            align-items: flex-start;
            justify-content: center;
            gap: 8px;
            flex-wrap: wrap;
            width: 100%;
            position: relative;
        }}
        .live-admin-quickjump {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            border-radius: 999px;
            background: linear-gradient(180deg, rgba(17, 33, 18, 0.98), rgba(8, 18, 10, 0.96));
            border: 1px solid rgba(0, 255, 170, 0.72);
            color: #ecfff5;
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            text-decoration: none;
            white-space: nowrap;
            box-shadow:
                0 0 0 1px rgba(0, 255, 170, 0.14),
                0 10px 24px rgba(0, 0, 0, 0.28),
                0 0 24px rgba(0, 255, 170, 0.14);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            transition: transform 120ms ease, border-color 120ms ease, box-shadow 120ms ease, background 120ms ease;
        }}
        .live-admin-quickjump:hover {{
            transform: translateY(-1px);
            border-color: rgba(0, 255, 170, 0.95);
            background: linear-gradient(180deg, rgba(21, 42, 24, 0.99), rgba(10, 24, 12, 0.98));
            box-shadow:
                0 0 0 1px rgba(0, 255, 170, 0.2),
                0 12px 28px rgba(0, 0, 0, 0.34),
                0 0 28px rgba(0, 255, 170, 0.2);
        }}
        .live-admin-quickjump::before {{
            content: "⚡";
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 999px;
            background: rgba(0, 255, 170, 0.14);
            border: 1px solid rgba(0, 255, 170, 0.72);
            color: #7cffc9;
            font-size: 0.72rem;
            line-height: 1;
            flex: 0 0 auto;
        }}
        .live-admin-inline details {{
            position: relative;
        }}
        .live-admin-inline summary {{
            list-style: none;
            margin: 0;
        }}
        .live-admin-inline summary::-webkit-details-marker {{
            display: none;
        }}
        .live-admin-pill {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            border-radius: 999px;
            background: linear-gradient(180deg, {_pill_bg_top}, {_pill_bg_bottom});
            border: 1px solid {_pill_accent};
            color: #f4fff8;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            cursor: pointer;
            box-shadow:
                0 0 0 1px {_pill_accent_soft},
                0 10px 24px rgba(0, 0, 0, 0.28),
                0 0 24px {_pill_shadow};
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        }}
        .live-admin-pill:hover {{
            border-color: {_pill_accent};
            background: linear-gradient(180deg, {_pill_hover_top}, {_pill_hover_bottom});
            box-shadow:
                0 0 0 1px {_pill_accent_soft},
                0 12px 28px rgba(0, 0, 0, 0.34),
                0 0 28px {_pill_shadow_hover};
        }}
        .live-admin-pill::before {{
            content: "●";
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 999px;
            background: {_pill_accent_soft};
            border: 1px solid {_pill_accent};
            color: {_pill_accent_text};
            font-size: 0.7rem;
            line-height: 1;
            flex: 0 0 auto;
        }}
        .live-admin-panel {{
            position: absolute;
            top: 100%;
            left: 50%;
            transform: translateX(-50%);
            margin-top: 8px;
            background: rgba(7, 11, 18, 0.97);
            border: 1px solid {_panel_border};
            border-radius: 16px;
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.34);
            overflow: hidden;
            width: min(560px, calc(100vw - 28px));
            z-index: 9999;
        }}
        .live-admin-panel-inner {{
            max-height: min(78vh, 760px);
            overflow-y: auto;
            padding: 14px 14px 12px;
        }}
        .live-admin-title {{
            color: #f7fff9;
            font-size: 0.96rem;
            font-weight: 800;
            margin: 0 0 4px 0;
        }}
        .live-admin-subtitle {{
            color: rgba(216, 229, 239, 0.84);
            font-size: 0.78rem;
            line-height: 1.5;
            margin-bottom: 12px;
        }}
        .live-admin-stats {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 8px;
            margin-bottom: 12px;
        }}
        .live-admin-stat {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 8px 10px;
        }}
        .live-admin-stat-label {{
            color: rgba(180, 221, 201, 0.82);
            font-size: 0.64rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 3px;
        }}
        .live-admin-stat-value {{
            color: #fbfffc;
            font-size: 0.9rem;
            font-weight: 800;
        }}
        .live-admin-row {{
            display: flex;
            justify-content: space-between;
            gap: 10px;
            padding: 10px 0;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .live-admin-row:first-of-type {{
            border-top: none;
            padding-top: 0;
        }}
        .live-admin-user {{
            color: #fbfeff;
            font-size: 0.82rem;
            font-weight: 700;
            margin-bottom: 3px;
        }}
        .live-admin-meta {{
            color: rgba(220, 230, 238, 0.88);
            font-size: 0.72rem;
            line-height: 1.45;
            word-break: break-word;
        }}
        .live-admin-seen {{
            color: #a8ffd3;
            font-size: 0.7rem;
            font-weight: 700;
            white-space: nowrap;
            margin-top: 2px;
        }}
        .live-admin-empty {{
            color: rgba(220, 230, 238, 0.82);
            font-size: 0.78rem;
            line-height: 1.5;
            padding: 8px 0 4px;
        }}
        .live-admin-note {{
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid rgba(116, 255, 186, 0.14);
            color: rgba(201, 214, 225, 0.82);
            font-size: 0.7rem;
            line-height: 1.45;
        }}
        .live-admin-note strong {{
            color: #f5fff8;
        }}
        @media (max-width: 700px) {{
            .live-admin-inline {{
                max-width: calc(100vw - 28px);
            }}
            .live-admin-panel {{
                width: calc(100vw - 28px);
                left: 50%;
                transform: translateX(-50%);
            }}
        }}
        </style>
        <div class="live-admin-inline">
            <div class="live-admin-dock">
                <details>
                    <summary class="live-admin-pill">Live Users</summary>
                    <div class="live-admin-panel">
                        <div class="live-admin-panel-inner">
                            <div class="live-admin-title">Live User Dashboard</div>
                            <div class="live-admin-subtitle">
                                Admin-only view of recent Streamlit sessions. A session stays visible while it has pinged the app within the last {_stale_seconds} seconds.
                            </div>
                            <div class="live-admin-stats">
                                <div class="live-admin-stat">
                                    <div class="live-admin-stat-label">Active</div>
                                    <div class="live-admin-stat-value">{_count}</div>
                                </div>
                                <div class="live-admin-stat">
                                    <div class="live-admin-stat-label">Stale cutoff</div>
                                    <div class="live-admin-stat-value">{_stale_seconds}s</div>
                                </div>
                                <div class="live-admin-stat">
                                    <div class="live-admin-stat-label">Updated</div>
                                    <div class="live-admin-stat-value">{html.escape(datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S"))} UTC</div>
                                </div>
                            </div>
                            {_rows_html}
                            <div class="live-admin-note">
                                <strong>Scope:</strong> this tracks sessions inside the current Streamlit app process only. If the app restarts or scales across multiple workers, the panel will reflect only the sessions that are still reachable in this process.
                            </div>
                        </div>
                    </div>
                </details>
            </div>
        </div>
        """),
        unsafe_allow_html=True,
    )


if hasattr(st, "fragment"):
    @st.fragment(run_every="20s")
    def _presence_heartbeat_fragment():
        _track_active_session()
else:
    def _presence_heartbeat_fragment():
        _track_active_session()


if hasattr(st, "fragment"):
    @st.fragment(run_every="15s")
    def _live_admin_dashboard_fragment():
        _render_live_admin_dashboard()
else:
    def _live_admin_dashboard_fragment():
        _render_live_admin_dashboard()


