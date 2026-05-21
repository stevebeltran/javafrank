"""Transient build notice rendering for authenticated users."""
import html
import json
import streamlit as st
import streamlit.components.v1 as components


def _get_active_session_rows():
    try:
        from modules.admin_dashboard import _prune_active_sessions
        return _prune_active_sessions()
    except Exception:
        return []


def render_transient_build_notice(__version__, __build_datetime__, __build_timestamp__):
    """Show a transient build notice on every app load for the target account."""
    _notice_email = str(
        st.session_state.get('google_user_email', '')
        or st.session_state.get('_last_user_email', '')
        or getattr(st.user, 'email', '')
        or ''
    ).strip().lower()
    if _notice_email != 'steven.beltran@brincdrones.com':
        return

    _active_sessions = _get_active_session_rows()
    _current_session_id = str(st.session_state.get("session_id", "") or "").strip()
    _current_user_email = str(
        st.session_state.get("google_user_email", "")
        or getattr(st.user, "email", "")
        or ""
    ).strip().lower()
    _current_user_name = str(
        st.session_state.get("google_user_name", "")
        or getattr(st.user, "name", "")
        or (_current_user_email.split("@", 1)[0] if _current_user_email else "Current user")
    ).strip()
    if _current_session_id and not any(
        str((_item.get("session_id", "") or "")).strip() == _current_session_id
        for _item in _active_sessions
    ):
        _active_sessions = [
            {
                "session_id": _current_session_id,
                "name": _current_user_name,
                "email": _current_user_email,
            },
            *_active_sessions,
        ]

    _active_names = []
    _seen_names = set()
    for _item in _active_sessions:
        _name = str((_item.get("name") or _item.get("email") or "Unknown")).strip()
        _key = _name.lower()
        if not _name or _key in _seen_names:
            continue
        _seen_names.add(_key)
        _active_names.append(_name)
        if len(_active_names) >= 4:
            break

    _active_count = len(_active_sessions)
    if _active_names:
        _active_names_html = " · ".join(
            f'<span class="active-user-name">{html.escape(_name)}</span>'
            for _name in _active_names
        )
        if _active_count > len(_active_names):
            _active_users_line = (
                f'<div class="active-users">'
                f'<span class="active-users-label">Active users</span> '
                f'<span class="active-users-count">({_active_count})</span> '
                f'<span class="active-users-list">{_active_names_html} +{_active_count - len(_active_names)} more</span>'
                f'</div>'
            )
        else:
            _active_users_line = (
                f'<div class="active-users">'
                f'<span class="active-users-label">Active users</span> '
                f'<span class="active-users-count">({_active_count})</span> '
                f'<span class="active-users-list">{_active_names_html}</span>'
                f'</div>'
            )
    else:
        _active_users_line = (
            '<div class="active-users">'
            '<span class="active-users-label">Active users</span> '
            '<span class="active-users-count">(0)</span> '
            '<span class="active-users-list">No active sessions detected yet.</span>'
            '</div>'
        )

    components.html(
        f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
</head>
<body>
<script>
(function() {{
  try {{
    var version = {json.dumps(__version__)};
    var buildTime = {json.dumps(__build_datetime__)};
    var buildTimestamp = {json.dumps(__build_timestamp__)};
    var parentWin = window.parent;
    var doc = parentWin.document;

    var existing = doc.getElementById('brinc-build-notice-wrap');
    if (existing && existing.parentNode) {{
      existing.parentNode.removeChild(existing);
    }}
    var styleId = 'brinc-build-notice-style';
    var style = doc.getElementById(styleId);
    if (!style) {{
      style = doc.createElement('style');
      style.id = styleId;
      style.textContent = `
        @keyframes brincBuildNoticeFade {{
            0% {{ opacity: 0; transform: translate(-50%, -46%) scale(0.985); }}
            6% {{ opacity: 1; transform: translate(-50%, -50%) scale(1); }}
            88% {{ opacity: 1; }}
            100% {{ opacity: 0; visibility: hidden; transform: translate(-50%, -54%) scale(0.985); }}
        }}
        #brinc-build-notice-wrap {{
            position: fixed;
            inset: 0;
            z-index: 100000;
            pointer-events: none;
        }}
        #brinc-build-notice-wrap .brinc-build-notice {{
            position: absolute;
            left: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
            min-width: 280px;
            padding: 18px 22px;
            border-radius: 18px;
            background: rgba(8, 12, 20, 0.94);
            border: 1px solid rgba(148, 163, 184, 0.26);
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.28);
            color: #f8fafc;
            text-align: center;
            font-family: 'IBM Plex Mono', monospace;
            animation: brincBuildNoticeFade 8s ease forwards;
        }}
        #brinc-build-notice-wrap .brinc-build-notice .label {{
            font-size: 0.68rem;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: rgba(191, 219, 254, 0.82);
        }}
        #brinc-build-notice-wrap .brinc-build-notice .version {{
            margin-top: 6px;
            font-size: 0.78rem;
            letter-spacing: 0.08em;
            color: rgba(226, 232, 240, 0.88);
        }}
        #brinc-build-notice-wrap .brinc-build-notice .time {{
            margin-top: 8px;
            font-size: 1.08rem;
            font-weight: 900;
            letter-spacing: 0.02em;
            color: #ff4444;
        }}
        #brinc-build-notice-wrap .brinc-build-notice .relative {{
            margin-top: 6px;
            font-size: 0.74rem;
            letter-spacing: 0.05em;
            color: rgba(226, 232, 240, 0.82);
        }}
        #brinc-build-notice-wrap .brinc-build-notice .active-users {{
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid rgba(74, 222, 128, 0.18);
            font-size: 0.72rem;
            line-height: 1.45;
            letter-spacing: 0.03em;
            color: rgba(226, 232, 240, 0.86);
        }}
        #brinc-build-notice-wrap .brinc-build-notice .active-users-label {{
            color: rgba(191, 219, 254, 0.82);
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font-size: 0.64rem;
            font-weight: 800;
        }}
        #brinc-build-notice-wrap .brinc-build-notice .active-users-count {{
            color: rgba(226, 232, 240, 0.88);
            font-weight: 700;
        }}
        #brinc-build-notice-wrap .brinc-build-notice .active-users-list {{
            display: block;
            margin-top: 4px;
        }}
        #brinc-build-notice-wrap .brinc-build-notice .active-user-name {{
            color: #39ff14;
            font-weight: 900;
            text-shadow: 0 0 10px rgba(57, 255, 20, 0.5);
        }}
      `;
      doc.head.appendChild(style);
    }}

    function formatElapsed(ms) {{
      var totalMinutes = Math.max(0, Math.floor(ms / 60000));
      if (totalMinutes < 1) {{
        return 'just now';
      }}
      if (totalMinutes < 60) {{
        return totalMinutes + ' minute' + (totalMinutes === 1 ? '' : 's') + ' ago';
      }}
      var totalHours = Math.floor(totalMinutes / 60);
      if (totalHours < 24) {{
        var leftoverMinutes = totalMinutes % 60;
        var hourText = totalHours + ' hour' + (totalHours === 1 ? '' : 's');
        if (leftoverMinutes > 0) {{
          hourText += ' ' + leftoverMinutes + ' minute' + (leftoverMinutes === 1 ? '' : 's');
        }}
        return hourText + ' ago';
      }}
      var totalDays = Math.floor(totalHours / 24);
      return totalDays + ' day' + (totalDays === 1 ? '' : 's') + ' ago';
    }}

    var buildDate = new Date(buildTimestamp * 1000);
    var chicagoTime = new Intl.DateTimeFormat('en-US', {{
      timeZone: 'America/Chicago',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
      timeZoneName: 'short'
    }}).format(buildDate);
    var elapsedText = formatElapsed(Date.now() - buildDate.getTime());

    var wrap = doc.createElement('div');
    wrap.id = 'brinc-build-notice-wrap';
    wrap.setAttribute('aria-hidden', 'true');
    wrap.innerHTML = `
      <div class="brinc-build-notice">
        <div class="label">Last updated</div>
        <div class="version">Version ${{version}}</div>
        <div class="time">${{chicagoTime}}</div>
        <div class="relative">${{elapsedText}}</div>
        ${_active_users_line}
      </div>
    `;
    doc.body.appendChild(wrap);

    parentWin.setTimeout(function() {{
      var el = doc.getElementById('brinc-build-notice-wrap');
      if (el && el.parentNode) {{
        el.parentNode.removeChild(el);
      }}
    }}, 8000);
  }} catch (e) {{}}
}})();
</script>
</body>
</html>
        """,
        height=0,
        scrolling=False,
    )
