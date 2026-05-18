"""Public QR code report rendering module."""
import hmac
import json
import urllib.parse
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Functions that need to be imported from app.py
# These will be injected as parameters
def render_public_report(
    _get_query_params_dict,
    _sign_public_report_id,
    _public_report_html_path,
    _public_report_metadata_path,
    _log_qr_scan_to_sheets,
    _log_to_sheets,
    _notify_email,
):
    """Render the public QR code report route."""
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

    st.set_page_config(layout="wide", page_title="BRINC DFR", page_icon="https://brincdrones.com/favicon.ico")
    st.markdown("""
        <style>
            header, footer, #MainMenu,
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            [data-testid="stStatusWidget"],
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
