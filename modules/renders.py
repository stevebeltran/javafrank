"""Render components for the main application."""
import html
import textwrap

import streamlit as st
import streamlit.components.v1 as components


def render_in_app_faq(__version__, __build_datetime__, FAQ_CHANGELOG):
    """Render in-app FAQ/Help panel with version and changelog.

    Args:
        __version__: Version string to display
        __build_datetime__: Build timestamp to display
        FAQ_CHANGELOG: List of changelog entries with version, timestamp, summary
    """
    _faq_items = [
        (
            "What do I do on this page?",
            "Choose a data path to analyze coverage and create deployment recommendations. "
            "Path 01: simulated data or upload a stations file. "
            "Path 02: upload Calls for Service files, CAD files, and stations files (CSV format). "
            "Path 03: load a random city with pre-loaded data and stations. "
            "The program uses customer data only to configure the map—no data is stored or transmitted.",
        ),
        (
            "What is this system for?",
            "It helps a customer understand where BRINC Drone as First Responder can add value, "
            "how coverage improves, and what a proposed deployment could look like in their jurisdiction.",
        ),
        (
            "What data do I need?",
            "Usually a CAD or incident file with location data, plus the city or region they care about. "
            "If you have an existing stations file, you can upload that too. "
            "The system uses this information to build a jurisdiction-specific view.",
        ),
        (
            "How does the system choose the jurisdiction?",
            "It uses the incident locations and the selected area to infer the most relevant city, county, or service area, then lets you confirm the final scope.",
        ),
        (
            "What is the difference between Responder and Guardian?",
            "Responder is the shorter-range tactical option. Guardian is the longer-range coverage "
            "and overwatch option. In a customer conversation, you can position them as different "
            "layers of the same response strategy.",
        ),
        (
            "Can the customer choose stations?",
            "Yes. The system can recommend stations automatically, and the user can also add, pin, "
            "or lock stations to match local operations and preferences.",
        ),
        (
            "What can I show after the demo?",
            "A deployment plan, an executive summary, map-based coverage views, station recommendations, "
            "and exportable artifacts that support follow-up conversations.",
        ),
        (
            "What should I say if someone asks how accurate it is?",
            "Explain that it is a planning and decision-support tool. It uses the customer's incident "
            "data and geography to produce a defendable recommendation, but it is not a substitute for "
            "local operational judgment.",
        ),
        (
            "How should an account executive position the value?",
            "Focus on faster situational awareness, broader coverage, clearer station placement decisions, "
            "and a stronger story for leadership, grants, and internal planning.",
        ),
    ]
    _faq_html = [
        '<div class="faq-shell">',
        '<div class="faq-intro">Quick answers for customer conversations, workflow, station strategy, deployment planning, and executive positioning.</div>',
    ]
    for _question, _answer in _faq_items:
        _faq_html.append(
            f'<div class="faq-item">'
            f'<div class="faq-q">{html.escape(_question)}</div>'
            f'<div class="faq-a">{html.escape(_answer)}</div>'
            f'</div>'
        )
    _faq_html.append(
        f'<div class="faq-footer"><div class="faq-footer-label">Version &amp; Changelog</div><div class="faq-version-line">Current version: {html.escape(__version__)} | Build time: {html.escape(__build_datetime__)}</div>'
    )
    for _entry in FAQ_CHANGELOG:
        _changelog_text = "v{version} | {timestamp} | {summary}".format(
            version=_entry["version"],
            timestamp=_entry["timestamp"],
            summary=_entry["summary"],
        )
        _faq_html.append(
            f'<div class="faq-changelog-line">{html.escape(_changelog_text)}</div>'
        )
    _faq_html.append("</div></div>")

    components.html(
        textwrap.dedent(
            f"""
            <style>
            .faq-float {{
                width: 100%;
                max-width: 680px;
                margin: 8px auto 0;
                font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                position: relative;
            }}
            .faq-float > * {{
                pointer-events: auto;
            }}
            .faq-dock {{
                display: flex;
                align-items: flex-start;
                justify-content: center;
                width: 100%;
            }}
            .faq-float summary {{
                list-style: none;
                margin: 0;
            }}
            .faq-float summary::-webkit-details-marker {{
                display: none;
            }}
            .faq-pill {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 12px;
                border-radius: 999px;
                background: linear-gradient(180deg, rgba(17, 30, 39, 0.98), rgba(8, 16, 22, 0.96));
                border: 1px solid rgba(0, 210, 255, 0.72);
                color: #f4fbff;
                font-size: 0.78rem;
                font-weight: 800;
                letter-spacing: 0.04em;
                cursor: pointer;
                box-shadow:
                    0 0 0 1px rgba(0, 210, 255, 0.14),
                    0 10px 24px rgba(0, 0, 0, 0.28),
                    0 0 24px rgba(0, 210, 255, 0.14);
                backdrop-filter: blur(8px);
                -webkit-backdrop-filter: blur(8px);
                transition: transform 120ms ease, border-color 120ms ease, box-shadow 120ms ease, background 120ms ease;
            }}
            .faq-pill:hover {{
                transform: translateY(-1px);
                border-color: rgba(102, 230, 255, 0.96);
                background: linear-gradient(180deg, rgba(22, 42, 54, 0.99), rgba(10, 21, 28, 0.98));
                box-shadow:
                    0 0 0 1px rgba(0, 210, 255, 0.18),
                    0 12px 28px rgba(0, 0, 0, 0.34),
                    0 0 28px rgba(0, 210, 255, 0.2);
            }}
            .faq-pill::before {{
                content: "?";
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 18px;
                height: 18px;
                border-radius: 999px;
                background: rgba(0, 210, 255, 0.12);
                border: 1px solid rgba(0, 210, 255, 0.72);
                color: #8be9ff;
                font-size: 0.76rem;
                font-weight: 900;
                line-height: 1;
                flex: 0 0 auto;
            }}
            .faq-panel {{
                margin-top: 8px;
                background: rgba(7, 11, 18, 0.97);
                border: 1px solid rgba(0, 210, 255, 0.2);
                border-radius: 16px;
                box-shadow: 0 24px 60px rgba(0, 0, 0, 0.34);
                overflow: hidden;
                width: min(560px, calc(100vw - 28px));
            }}
            .faq-panel-inner {{
                max-height: min(78vh, 760px);
                overflow-y: auto;
                padding: 14px 14px 12px;
            }}
            .faq-shell {{
                padding: 2px 0 0;
            }}
            .faq-intro {{
                color: rgba(235, 242, 248, 0.78);
                font-size: 0.84rem;
                line-height: 1.45;
                margin: 0 0 12px;
            }}
            .faq-item {{
                padding: 10px 0 11px;
                border-top: 1px solid rgba(116, 255, 186, 0.14);
            }}
            .faq-item:first-of-type {{
                border-top: 0;
                padding-top: 0;
            }}
            .faq-q {{
                color: #f5fff8;
                font-size: 0.93rem;
                font-weight: 800;
                line-height: 1.35;
                margin-bottom: 4px;
            }}
            .faq-a {{
                color: rgba(225, 236, 242, 0.84);
                font-size: 0.83rem;
                line-height: 1.48;
            }}
            .faq-footer {{
                margin-top: 14px;
                padding-top: 10px;
                border-top: 1px solid rgba(116, 255, 186, 0.18);
            }}
            .faq-footer-label {{
                color: #7cffc9;
                font-size: 0.68rem;
                font-weight: 800;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                margin-bottom: 6px;
            }}
            .faq-version-line,
            .faq-changelog-line {{
                color: rgba(225, 236, 242, 0.78);
                font-size: 0.73rem;
                line-height: 1.4;
            }}
            .faq-changelog-line {{
                margin-top: 4px;
            }}
            @media (max-width: 700px) {{
                .faq-float {{
                    width: calc(100vw - 28px);
                }}
                .faq-panel {{
                    width: calc(100vw - 28px);
                }}
            }}
            </style>
            <div class="faq-float">
                <div class="faq-dock">
                    <details>
                        <summary class="faq-pill">Help / FAQ</summary>
                        <div class="faq-panel">
                            <div class="faq-panel-inner">
                                {"".join(_faq_html)}
                            </div>
                        </div>
                    </details>
                </div>
            </div>
            """
        ),
        height=850,
    )
