"""Transient build notice rendering for authenticated users."""
import json
import streamlit as st
import streamlit.components.v1 as components


def render_transient_build_notice(__version__, __build_datetime__):
    """Show a transient build notice on every app load for the target account."""
    _notice_email = str(
        st.session_state.get('google_user_email', '')
        or st.session_state.get('_last_user_email', '')
        or getattr(st.user, 'email', '')
        or ''
    ).strip().lower()
    if _notice_email != 'steven.beltran@brincdrones.com':
        return
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
            10% {{ opacity: 1; transform: translate(-50%, -50%) scale(1); }}
            80% {{ opacity: 1; }}
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
            animation: brincBuildNoticeFade 5s ease forwards;
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
            font-weight: 700;
            letter-spacing: 0.02em;
        }}
      `;
      doc.head.appendChild(style);
    }}

    var wrap = doc.createElement('div');
    wrap.id = 'brinc-build-notice-wrap';
    wrap.setAttribute('aria-hidden', 'true');
    wrap.innerHTML = `
      <div class="brinc-build-notice">
        <div class="label">Last updated</div>
        <div class="version">Version ${{version}}</div>
        <div class="time">${{buildTime}}</div>
      </div>
    `;
    doc.body.appendChild(wrap);

    parentWin.setTimeout(function() {{
      var el = doc.getElementById('brinc-build-notice-wrap');
      if (el && el.parentNode) {{
        el.parentNode.removeChild(el);
      }}
    }}, 5000);
  }} catch (e) {{}}
}})();
</script>
</body>
</html>
        """,
        height=0,
        scrolling=False,
    )
