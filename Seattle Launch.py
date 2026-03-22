import streamlit as st
import pandas as pd
import geopandas as gpd
import numpy as np
import plotly.graph_objects as go
from shapely.geometry import Point, Polygon, MultiPolygon, box, shape
from shapely.ops import unary_union
import os
import itertools
import glob
import math
import simplekml
import heapq
from concurrent.futures import ThreadPoolExecutor
import pulp
import re
import random
import json
import urllib.request
import urllib.parse
import zipfile
import io
import datetime
import base64
import streamlit.components.v1 as components
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials

def _notify_email(city, state, file_type, k_resp, k_guard, coverage, name, email):
    try:
        gmail_address  = st.secrets.get("GMAIL_ADDRESS", "")
        app_password   = st.secrets.get("GMAIL_APP_PASSWORD", "")
        notify_address = st.secrets.get("NOTIFY_EMAIL", gmail_address)
        if not gmail_address or not app_password:
            return
        emoji = {"HTML": "📄", "KML": "🌏", "BRINC": "💾"}.get(file_type, "📥")
        subject = f"{emoji} BRINC Download — {file_type} — {city}, {state}"
        body = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;padding:20px;">
        <div style="max-width:500px;margin:0 auto;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
            <div style="background:#000;padding:16px 20px;border-bottom:3px solid #00D2FF;">
                <span style="color:#00D2FF;font-size:18px;font-weight:900;letter-spacing:2px;">BRINC</span>
                <span style="color:#888;font-size:12px;margin-left:8px;">Download Notification</span>
            </div>
            <div style="padding:20px;">
                <table style="width:100%;border-collapse:collapse;font-size:14px;">
                    <tr style="border-bottom:1px solid #f0f0f0;">
                        <td style="padding:8px 4px;color:#888;width:40%;">File Type</td>
                        <td style="padding:8px 4px;font-weight:bold;">{emoji} {file_type}</td>
                    </tr>
                    <tr style="border-bottom:1px solid #f0f0f0;">
                        <td style="padding:8px 4px;color:#888;">City</td>
                        <td style="padding:8px 4px;font-weight:bold;">{city}, {state}</td>
                    </tr>
                    <tr style="border-bottom:1px solid #f0f0f0;">
                        <td style="padding:8px 4px;color:#888;">Fleet</td>
                        <td style="padding:8px 4px;">{k_resp} Responder · {k_guard} Guardian</td>
                    </tr>
                    <tr style="border-bottom:1px solid #f0f0f0;">
                        <td style="padding:8px 4px;color:#888;">Call Coverage</td>
                        <td style="padding:8px 4px;">{coverage:.1f}%</td>
                    </tr>
                    <tr style="border-bottom:1px solid #f0f0f0;">
                        <td style="padding:8px 4px;color:#888;">User Name</td>
                        <td style="padding:8px 4px;">{name if name else '—'}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 4px;color:#888;">User Email</td>
                        <td style="padding:8px 4px;">
                            {f'<a href="mailto:{email}">{email}</a>' if email else '—'}
                        </td>
                    </tr>
                </table>
                <div style="margin-top:16px;font-size:11px;color:#bbb;">
                    {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} UTC
                </div>
            </div>
        </div>
        </body></html>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = gmail_address
        msg["To"]      = notify_address
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as server:
            server.login(gmail_address, app_password)
            server.sendmail(gmail_address, notify_address, msg.as_string())
    except Exception:
        pass


def _log_to_sheets(city, state, file_type, k_resp, k_guard, coverage, name, email):
    try:
        sheet_id   = st.secrets.get("GOOGLE_SHEET_ID", "")
        creds_dict = st.secrets.get("gcp_service_account", {})
        if not sheet_id or not creds_dict:
            return
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds  = Credentials.from_service_account_info(dict(creds_dict), scopes=scopes)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(sheet_id).sheet1
        sheet.append_row([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            city, state, file_type,
            k_resp, k_guard,
            round(coverage, 1),
            name, email
        ])
    except Exception:
        pass


# --- GLOBAL CONFIGURATION ---
CONFIG = {
    "RESPONDER_COST": 80000,
    "GUARDIAN_COST": 160000,
    "RESPONDER_RANGE_MI": 2.0,
    "OFFICER_COST_PER_CALL": 82,
    "DRONE_COST_PER_CALL": 6,
    "DEFAULT_TRAFFIC_SPEED": 35.0,
    "RESPONDER_SPEED": 42.0,
    "GUARDIAN_SPEED": 60.0
}

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
    "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25",
    "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32",
    "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47",
    "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55",
    "WY": "56"
}

US_STATES_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"
}

KNOWN_POPULATIONS = {
    "New York": 8336817, "Los Angeles": 3822238, "Chicago": 2665039, "Houston": 1304379,
    "Phoenix": 1644409, "Philadelphia": 1567258, "San Antonio": 2302878, "San Diego": 1472530,
    "Dallas": 1299544, "San Jose": 1381162, "Austin": 974447, "Jacksonville": 971319,
    "Fort Worth": 956709, "Columbus": 907971, "Indianapolis": 880621, "Charlotte": 897720,
    "San Francisco": 971233, "Seattle": 749256, "Denver": 713252, "Washington": 678972,
    "Nashville": 683622, "Oklahoma City": 694800, "El Paso": 694553, "Boston": 650706,
    "Portland": 635067, "Las Vegas": 656274, "Detroit": 620376, "Memphis": 633104,
    "Louisville": 628594, "Baltimore": 620961, "Milwaukee": 620251, "Albuquerque": 677122,
    "Tucson": 564559, "Fresno": 677102, "Sacramento": 808418, "Kansas City": 697738,
    "Mesa": 504258, "Atlanta": 499127, "Omaha": 508901, "Colorado Springs": 483956,
    "Raleigh": 476587, "Miami": 449514, "Virginia Beach": 455369, "Oakland": 530763,
    "Minneapolis": 563332, "Tulsa": 547239, "Arlington": 398654, "New Orleans": 562503,
    "Wichita": 402263, "Cleveland": 900000, "Tampa": 449514, "Orlando": 316081
}

DEMO_CITIES = [
    ("Las Vegas", "NV"), ("Austin", "TX"), ("Seattle", "WA"),
    ("Denver", "CO"), ("Nashville", "TN"), ("Columbus", "OH"),
    ("Detroit", "MI"), ("San Diego", "CA"), ("Charlotte", "NC"),
    ("Portland", "OR"), ("Memphis", "TN"), ("Louisville", "KY"),
    ("Baltimore", "MD"), ("Milwaukee", "WI"), ("Albuquerque", "NM"),
    ("Tucson", "AZ"), ("Fresno", "CA"), ("Sacramento", "CA"),
    ("Kansas City", "MO"), ("Mesa", "AZ"), ("Atlanta", "GA"),
    ("Omaha", "NE"), ("Colorado Springs", "CO"), ("Raleigh", "NC"),
    ("Miami", "FL"), ("Minneapolis", "MN"), ("Tulsa", "OK"),
    ("Arlington", "TX"), ("Tampa", "FL"), ("New Orleans", "LA"),
    ("Wichita", "KS"), ("Cleveland", "OH"), ("Virginia Beach", "VA"),
    ("Oakland", "CA"), ("Indianapolis", "IN"), ("Jacksonville", "FL"),
    ("Fort Worth", "TX"), ("Boston", "MA"), ("El Paso", "TX"),
    ("Oklahoma City", "OK"), ("Louisville", "KY"), ("Boise", "ID"),
    ("Richmond", "VA"), ("Spokane", "WA"), ("Tacoma", "WA"),
    ("Aurora", "CO"), ("Anaheim", "CA"), ("Bakersfield", "CA"),
    ("Riverside", "CA"), ("Stockton", "CA"), ("Corpus Christi", "TX"),
    ("Lexington", "KY"), ("Henderson", "NV"), ("Saint Paul", "MN"),
    ("Anchorage", "AK"), ("Plano", "TX"), ("Lincoln", "NE"),
    ("Buffalo", "NY"), ("Fort Wayne", "IN"), ("Jersey City", "NJ"),
    ("Chula Vista", "CA"), ("Orlando", "FL"), ("St. Louis", "MO"),
    ("Madison", "WI"), ("Durham", "NC"), ("Lubbock", "TX"),
    ("Winston-Salem", "NC"), ("Garland", "TX"), ("Glendale", "AZ"),
    ("Hialeah", "FL"), ("Scottsdale", "AZ"), ("Irving", "TX"),
    ("Fremont", "CA"), ("Baton Rouge", "LA"), ("Birmingham", "AL"),
    ("Rochester", "NY"), ("Spokane", "WA"), ("Des Moines", "IA"),
    ("Montgomery", "AL"), ("Modesto", "CA"), ("Fayetteville", "NC"),
    ("Tacoma", "WA"), ("Shreveport", "LA"), ("Akron", "OH"),
    ("Grand Rapids", "MI"), ("Huntington Beach", "CA"), ("Little Rock", "AR")
]
FAST_DEMO_CITIES = [
    ("Henderson", "NV"), ("Lincoln", "NE"), ("Boise", "ID"),
    ("Des Moines", "IA"), ("Madison", "WI"), ("Colorado Springs", "CO"),
    ("Richmond", "VA"), ("Raleigh", "NC"), ("Durham", "NC"),
    ("Fort Wayne", "IN"), ("Omaha", "NE"), ("Wichita", "KS"),
    ("Tulsa", "OK"), ("Spokane", "WA"), ("Tacoma", "WA"),
    ("Aurora", "CO"), ("Las Vegas", "NV"), ("Nashville", "TN"),
    ("Columbus", "OH"), ("Charlotte", "NC"), ("Louisville", "KY"),
    ("Indianapolis", "IN"), ("Memphis", "TN"), ("Detroit", "MI"),
    ("Milwaukee", "WI"), ("Minneapolis", "MN"), ("Seattle", "WA"),
    ("Denver", "CO"), ("Portland", "OR"), ("Austin", "TX")
]
FAA_CEILING_COLORS = {
    0:   {"line": "rgba(255,  20,  20, 0.95)", "fill": "rgba(255,  20,  20, 0.20)"},
    50:  {"line": "rgba(255, 120,   0, 0.95)", "fill": "rgba(255, 120,   0, 0.18)"},
    100: {"line": "rgba(255, 210,   0, 0.95)", "fill": "rgba(255, 210,   0, 0.18)"},
    200: {"line": "rgba(180, 230,   0, 0.95)", "fill": "rgba(180, 230,   0, 0.16)"},
    300: {"line": "rgba( 80, 200,  50, 0.95)", "fill": "rgba( 80, 200,  50, 0.16)"},
    400: {"line": "rgba(  0, 180, 100, 0.95)", "fill": "rgba(  0, 180, 100, 0.15)"},
}
FAA_DEFAULT_COLOR = {"line": "rgba(150,150,150,0.8)", "fill": "rgba(150,150,150,0.10)"}

STATION_COLORS = [
    "#00D2FF", "#39FF14", "#FFD700", "#FF007F", "#FF4500",
    "#00FFCC", "#FF3333", "#7FFF00", "#00FFFF", "#FF9900"
]

# ── Feel-good loading messages honoring law enforcement ──────────────────────
HERO_MESSAGES = [
    "🚔 Building safer communities, one drone at a time…",
    "🛡️ Loading data because your officers deserve better tools…",
    "🫡 Honoring the men and women who answer the call every day…",
    "💙 Officers run toward danger so the rest of us don't have to…",
    "🚁 Optimizing so your team gets there first — every time…",
    "🌟 Every second we save is a life better protected…",
    "🤝 Technology in service of the community's greatest heroes…",
    "💪 Your officers deserve every advantage we can give them…",
    "🙏 Dedicated to the families who wait at home while heroes serve…",
    "🏅 Processing data worthy of those who wear the badge with pride…",
    "🌃 Mapping the city your officers protect through every shift…",
    "🔵 Building a network as reliable as the officers who depend on it…",
    "❤️ Because faster response means more lives saved…",
    "🌅 Creating tools that let officers come home safely every night…",
    "🦅 Guardian drones — always watching, always ready to assist…",
    "🏘️ Modeling coverage for the neighborhoods they protect and serve…",
    "📡 Connecting technology to the courage already on the streets…",
    "🧠 Smart systems for smarter, safer law enforcement…",
    "🌟 Every data point represents a community worth protecting…",
    "🚨 Fewer false alarms. More real backup. Better outcomes for all…",
]

FAA_MESSAGES = [
    "✈️ Checking FAA airspace — keeping your drones and your pilots safe…",
    "🛫 Loading LAANC data — because safe skies mean more missions completed…",
    "🗺️ Mapping controlled airspace — so every flight is a legal, safe one…",
    "✈️ FAA compliance check in progress — protecting officers on the ground and drones in the air…",
    "🛡️ Pulling airspace boundaries — safe operations start before takeoff…",
    "🌐 Verifying flight corridors — your pilots deserve a clear path forward…",
    "📡 Syncing with FAA LAANC — because your department deserves zero surprises in the sky…",
    "🛩️ Loading aviation data — the same skies your officers look up to every night…",
]

AIRFIELD_MESSAGES = [
    "🏗️ Locating nearby airfields — coordinating with the aviation community that shares your skies…",
    "📍 Mapping airports near each station — great neighbors make great operators…",
    "🛬 Finding local airfields — because your team coordinates with everyone keeping the community safe…",
    "✈️ Scanning for nearby aviation assets — your drones respect every aircraft they share the sky with…",
    "🗺️ Identifying airport proximity — so your officers always know what's overhead…",
    "🤝 Locating nearby airfields — collaboration between aviation and law enforcement saves lives…",
    "📡 Querying aviation infrastructure — the sky belongs to everyone who protects this community…",
]

JURISDICTION_MESSAGES = [
    "🗺️ Identifying jurisdictions — every boundary represents a community counting on you…",
    "📐 Loading geographic boundaries — the lines officers cross every shift to keep people safe…",
    "🏙️ Mapping your jurisdiction — the streets your officers know better than anyone…",
    "🌆 Matching data to boundaries — every block is someone's home, someone's neighborhood…",
    "📍 Finding your coverage area — the community that trusts you with their safety…",
    "🗺️ Resolving jurisdictions — where every call for help deserves an answer…",
]

SPATIAL_MESSAGES = [
    "⚡ Crunching coverage geometry — because your officers deserve precision, not guesswork…",
    "🧮 Computing spatial matrices — doing the math so your team can focus on what matters…",
    "📊 Building coverage model — every calculation brings faster response one step closer…",
    "🔬 Analyzing incident patterns — understanding the city so your officers can better protect it…",
    "💡 Optimizing station geometry — smart placement means no neighborhood is left behind…",
    "🧠 Modeling response zones — technology standing behind the officers who stand for us…",
]

def get_hero_message():
    return random.choice(HERO_MESSAGES)

def get_faa_message():
    return random.choice(FAA_MESSAGES)

def get_airfield_message():
    return random.choice(AIRFIELD_MESSAGES)

def get_jurisdiction_message():
    return random.choice(JURISDICTION_MESSAGES)

def get_spatial_message():
    return random.choice(SPATIAL_MESSAGES)

def get_base64_of_bin_file(bin_file):
    try:
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    except Exception:
        return None

# --- PAGE CONFIG ---
st.set_page_config(page_title="BRINC COS Drone Optimizer", layout="wide", initial_sidebar_state="expanded")

# --- INITIALIZE SESSION STATE ---
defaults = {
    'csvs_ready': False, 'df_calls': None, 'df_stations': None,
    'active_city': "Orlando", 'active_state': "FL", 'estimated_pop': 316081,
    'k_resp': 0, 'k_guard': 0, 'r_resp': 2.0, 'r_guard': 8.0,
    'dfr_rate': 25, 'deflect_rate': 30, 'total_original_calls': 0,
    'onboarding_done': False, 'trigger_sim': False, 'city_count': 1
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if 'target_cities' not in st.session_state:
    st.session_state['target_cities'] = [{"city": st.session_state.get('active_city', 'Orlando'), "state": st.session_state.get('active_state', 'FL')}]

# --- THEME ---
bg_main = "#000000"
bg_sidebar = "#111111"
text_main = "#ffffff"
text_muted = "#aaaaaa"
accent_color = "#00D2FF"
card_bg = "#111111"
card_border = "#333333"
card_text = "#eeeeee"
card_title = "#ffffff"
budget_box_bg = "#0a0a0a"
budget_box_border = "#00D2FF"
budget_box_shadow = "rgba(0, 210, 255, 0.15)"
map_style = "carto-darkmatter"
map_boundary_color = "#ffffff"
map_incident_color = "#00D2FF"
legend_bg = "rgba(0, 0, 0, 0.7)"
legend_text = "#ffffff"

theme_css = f"""
.stApp, .main {{ background-color: {bg_main} !important; }}
html, body, [class*="css"], p, label, li, h1, h2, h3, h4, h5, h6 {{ font-family: 'Manrope', sans-serif !important; color: {text_main} !important; }}
[data-testid="stSidebar"] {{ background-color: {bg_sidebar} !important; border-right: 1px solid {card_border}; }}
[data-testid="stSidebar"] img {{ filter: invert(1) brightness(2); }}
[data-testid="stFileUploader"] p, [data-testid="stFileUploader"] small {{ color: {text_muted} !important; }}
[data-testid="stFileUploader"] section {{ background-color: #111111 !important; border-color: #333333 !important; }}
div[data-testid="stMetricValue"] {{ font-family: 'IBM Plex Mono', monospace !important; color: {accent_color} !important; }}
div[data-testid="stMetricLabel"] * {{ color: {text_muted} !important; }}
div[data-testid="stExpander"] details {{ background-color: #111111 !important; border-color: #333333 !important; }}
div[data-testid="stExpander"] summary {{ background-color: #111111 !important; color: #ffffff !important; }}
div[data-testid="stExpander"] summary:hover {{ background-color: #222222 !important; }}
div[data-testid="stForm"] {{ background-color: #111111 !important; border-color: #333333 !important; }}
div[data-baseweb="select"] > div {{ background-color: #222222 !important; border-color: #444444 !important; color: #ffffff !important; }}
div[data-baseweb="select"] > div input {{ color: #ffffff !important; }}
div[data-baseweb="select"] span[data-baseweb="tag"] {{ background-color: #333333 !important; color: #ffffff !important; border: 1px solid #555555 !important; }}
div[data-baseweb="select"] span[data-baseweb="tag"] span {{ color: #ffffff !important; }}
div[data-baseweb="popover"] ul {{ background-color: #222222 !important; color: #ffffff !important; }}
div[data-baseweb="popover"] li:hover {{ background-color: #444444 !important; }}
div[data-testid="stTextInput"] div[data-baseweb="input"] {{ background-color: #222222 !important; border-color: #444444 !important; }}
div[data-testid="stTextInput"] div[data-baseweb="input"] > div {{ background-color: transparent !important; }}
div[data-testid="stTextInput"] div[data-baseweb="input"] input {{ color: #ffffff !important; background-color: transparent !important; -webkit-text-fill-color: #ffffff !important; caret-color: #ffffff !important; }}
div[data-testid="stButton"] button, div[data-testid="stFormSubmitButton"] button, div[data-testid="stDownloadButton"] button {{
    background-color: #222222 !important; border: 1px solid #444444 !important; color: #ffffff !important;
}}
div[data-testid="stButton"] button p, div[data-testid="stFormSubmitButton"] button p, div[data-testid="stDownloadButton"] button p {{ color: #ffffff !important; }}
div[data-testid="stButton"] button:hover, div[data-testid="stFormSubmitButton"] button:hover, div[data-testid="stDownloadButton"] button:hover {{
    background-color: #ffffff !important; border-color: #ffffff !important;
}}
div[data-testid="stButton"] button:hover p, div[data-testid="stFormSubmitButton"] button:hover p, div[data-testid="stDownloadButton"] button:hover p {{ color: #000000 !important; }}
div[data-testid="stButton"] button:hover svg, div[data-testid="stFormSubmitButton"] button:hover svg, div[data-testid="stDownloadButton"] button:hover svg {{ fill: #000000 !important; color: #000000 !important; }}
div[data-testid="stToast"] {{ background-color: #222222 !important; border-color: #444444 !important; }}
div[data-testid="stToast"] span, div[data-testid="stToast"] div {{ color: #ffffff !important; }}
.sidebar-section-header {{
    font-size: 0.65rem !important; font-weight: 800 !important; letter-spacing: 1.5px !important;
    text-transform: uppercase !important; color: {accent_color} !important;
    border-top: 1px solid {card_border}; padding-top: 12px; margin-top: 4px; margin-bottom: 8px;
}}
div[data-testid="stTooltipIcon"] svg {{ stroke: {accent_color} !important; fill: transparent !important; }}
div[data-testid="stTooltipHoverTarget"] {{ color: {accent_color} !important; }}
div[data-testid="stTooltipContent"] {{ background-color: #222222 !important; border: 1px solid {accent_color} !important; border-radius: 4px !important; }}
div[data-testid="stTooltipContent"] * {{ color: #ffffff !important; font-size: 0.8rem !important; }}
.card-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }}
.econ-card {{
    background: {card_bg}; border-radius: 6px; padding: 12px;
    border-top: 4px solid var(--card-accent); border-left: 1px solid {card_border};
    border-right: 1px solid {card_border}; border-bottom: 1px solid {card_border};
    display: flex; flex-direction: column; gap: 6px;
}}
.econ-card .headline {{ font-size: 1.1rem; font-weight: 800; color: {accent_color}; text-align: center; padding: 4px 0; }}
.econ-card .kv {{ display: flex; justify-content: space-between; font-size: 0.65rem; }}
.econ-card .kv .k {{ color: {text_muted}; }}
.econ-card .kv .v {{ font-weight: 700; color: {card_title}; }}
.econ-card .kv .v-accent {{ font-weight: 700; color: {accent_color}; }}
@media (max-width: 900px) {{
    div[data-testid="stHorizontalBlock"] {{ flex-direction: column !important; }}
    div[data-testid="stColumn"] {{ width: 100% !important; max-width: 100% !important; }}
}}
@media print {{
    section[data-testid="stSidebar"], header[data-testid="stHeader"], .stSlider, button, div[data-testid="stToolbar"] {{ display: none !important; }}
    * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }}
    .block-container, .stApp, .main, div {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; margin: 0 !important; overflow: visible !important; height: auto !important; }}
    div[data-testid="stHorizontalBlock"] {{ display: block !important; width: 100% !important; }}
    div[data-testid="stColumn"] {{ width: 100% !important; max-width: 100% !important; flex: 0 0 100% !important; display: block !important; margin-bottom: 20px !important; }}
    .js-plotly-plot, .plot-container {{ width: 100% !important; page-break-inside: avoid !important; margin-bottom: 30px !important; }}
}}
"""

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;700&family=Manrope:wght@400;600;700&display=swap');
{theme_css}
.stRadio label p, .stMultiSelect label p, .stSlider label p, .stToggle label p, .stCheckbox label p {{
    font-weight: 600 !important; font-size: 0.85rem !important;
}}
div[role="radiogroup"] {{ gap: 0.5rem !important; }}
</style>
""", unsafe_allow_html=True)

components.html("""
<script>
window.addEventListener('beforeunload', function(e) {
    if (window._brincHasData) {
        e.preventDefault();
        e.returnValue = 'You have an active session. Download your .brinc scenario first to save your work.';
    }
});
</script>
""", height=0)

try:
    st.sidebar.image("logo.png", use_container_width=True)
except FileNotFoundError:
    st.sidebar.markdown(f"<div style='font-size:1.4rem;font-weight:900;letter-spacing:3px;color:{accent_color};padding:10px 0;'>BRINC</div>", unsafe_allow_html=True)

SHAPEFILE_DIR = "jurisdiction_data"
if not os.path.exists(SHAPEFILE_DIR):
    os.makedirs(SHAPEFILE_DIR)

# ============================================================
# CACHED DATA FUNCTIONS
# ============================================================
@st.cache_data
def reverse_geocode_state(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10&addressdetails=1"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            address = data.get('address', {})
            state = address.get('state', '')
            city = address.get('city', address.get('town', address.get('village', address.get('county', 'Unknown City'))))
            return state, city
    except Exception:
        return None, None

@st.cache_data
def fetch_census_population(state_fips, place_name):
    url = f"https://api.census.gov/data/2020/dec/pl?get=P1_001N,NAME&for=place:*&in=state:{state_fips}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            search_name = place_name.lower().strip()
            for row in data[1:]:
                place_full = row[1].lower().split(',')[0].strip()
                if place_full == search_name or place_full.startswith(search_name + " "):
                    return int(row[0])
    except Exception:
        pass
    return None

@st.cache_data
def fetch_tiger_city_shapefile(state_fips, city_name, output_dir):
    url = f"https://www2.census.gov/geo/tiger/TIGER2023/PLACE/tl_2023_{state_fips}_place.zip"
    try:
        req = urllib.request.urlopen(url, timeout=20)
        zip_file = zipfile.ZipFile(io.BytesIO(req.read()))
        temp_dir = os.path.join(output_dir, f"temp_tiger_{state_fips}")
        os.makedirs(temp_dir, exist_ok=True)
        zip_file.extractall(temp_dir)
        shp_path = glob.glob(os.path.join(temp_dir, "*.shp"))[0]
        gdf = gpd.read_file(shp_path)
        search_name = city_name.lower().strip()
        exact_mask = gdf['NAME'].str.lower().str.strip() == search_name
        if exact_mask.any():
            city_gdf = gdf[exact_mask]
        else:
            city_gdf = gdf[gdf['NAME'].str.lower().str.contains(search_name, case=False, na=False)]
        if not city_gdf.empty:
            city_gdf = city_gdf.dissolve(by='NAME').reset_index()
            save_path = os.path.join(output_dir, f"{city_name.replace(' ', '_')}_{state_fips}.shp")
            city_gdf.to_file(save_path)
            return True, city_gdf
    except Exception as e:
        print(f"TIGER fetch error: {e}")
        return False, None
    return False, None

def generate_mock_faa_grid(minx, miny, maxx, maxy):
    features = []
    x_steps = np.linspace(minx, maxx, 20)
    y_steps = np.linspace(miny, maxy, 20)
    mock_airports = [
        {"lon": minx + 0.3 * (maxx - minx), "lat": miny + 0.3 * (maxy - miny), "radius": 0.15, "name": "Mock Intl (MCK)"},
        {"lon": minx + 0.7 * (maxx - minx), "lat": miny + 0.6 * (maxy - miny), "radius": 0.10, "name": "Mock Regional (MRG)"},
    ]
    for i in range(len(x_steps) - 1):
        for j in range(len(y_steps) - 1):
            cell_poly = [
                [x_steps[i], y_steps[j]], [x_steps[i+1], y_steps[j]],
                [x_steps[i+1], y_steps[j+1]], [x_steps[i], y_steps[j+1]],
                [x_steps[i], y_steps[j]]
            ]
            cell_center = Point((x_steps[i] + x_steps[i+1]) / 2, (y_steps[j] + y_steps[j+1]) / 2)
            ceiling, arpt_name = None, ""
            for ap in mock_airports:
                dist_ratio = cell_center.distance(Point(ap["lon"], ap["lat"])) / ap["radius"]
                if dist_ratio < 1.0:
                    if   dist_ratio < 0.15: ceiling, arpt_name = 0,   ap["name"]
                    elif dist_ratio < 0.35: ceiling, arpt_name = 50,  ap["name"]
                    elif dist_ratio < 0.55: ceiling, arpt_name = 100, ap["name"]
                    elif dist_ratio < 0.75: ceiling, arpt_name = 200, ap["name"]
                    else:                   ceiling, arpt_name = 300, ap["name"]
                    break
            if ceiling is not None:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [cell_poly]},
                    "properties": {"CEILING": ceiling, "ARPT_Name": arpt_name}
                })
    return {"type": "FeatureCollection", "features": features}

@st.cache_data
def load_faa_parquet(minx, miny, maxx, maxy):
    if not os.path.exists("faa_uasfm.parquet"):
        return generate_mock_faa_grid(minx, miny, maxx, maxy)
    try:
        gdf = gpd.read_parquet("faa_uasfm.parquet")
        pad = 0.05
        filtered = gdf.cx[minx-pad:maxx+pad, miny-pad:maxy+pad]
        if filtered.empty:
            return {"type": "FeatureCollection", "features": []}
        return json.loads(filtered.to_json())
    except Exception as e:
        print(f"FAA Parquet error: {e}")
        return generate_mock_faa_grid(minx, miny, maxx, maxy)

def add_faa_laanc_layer_to_plotly(fig, faa_geojson, is_dark=True):
    if not faa_geojson or not faa_geojson.get("features"):
        return
    text_lons, text_lats, text_strings, text_hovers = [], [], [], []
    for feature in faa_geojson.get("features", []):
        geom = feature.get("geometry")
        props = feature.get("properties", {})
        ceiling = props.get("CEILING")
        arpt = props.get("ARPT_Name") or props.get("ARPT_NAME") or "Unknown Airport"
        if ceiling is None or geom is None or geom.get("type") != "Polygon":
            continue
        snapped = min(FAA_CEILING_COLORS.keys(), key=lambda v: abs(v - ceiling))
        colors = FAA_CEILING_COLORS.get(snapped, FAA_DEFAULT_COLOR)
        coords = geom["coordinates"][0]
        bx, by = zip(*coords)
        fig.add_trace(go.Scattermapbox(
            mode="lines", lon=list(bx), lat=list(by),
            fill="toself", fillcolor=colors["fill"],
            line=dict(color=colors["line"], width=1.5),
            hoverinfo="text", text=f"<b>{ceiling} ft AGL</b><br>{arpt}",
            name=f"LAANC {ceiling}ft", showlegend=False
        ))
        try:
            centroid = shape(geom).centroid
            text_lons.append(centroid.x)
            text_lats.append(centroid.y)
            text_strings.append(str(ceiling))
            text_hovers.append(f"{ceiling} ft — {arpt}")
        except Exception:
            pass
    if text_lons:
        fig.add_trace(go.Scattermapbox(
            mode="text", lon=text_lons, lat=text_lats, text=text_strings,
            hovertext=text_hovers, hoverinfo="text",
            textfont=dict(size=10, color="#ffffff" if is_dark else "#000000"),
            showlegend=False, name="LAANC Labels"
        ))

def get_station_faa_ceiling(lat, lon, faa_geojson):
    if not faa_geojson or 'features' not in faa_geojson:
        return "400 ft (Class G)"
    pt = Point(lon, lat)
    for feature in faa_geojson['features']:
        if 'geometry' in feature and feature['geometry']:
            try:
                s = shape(feature['geometry'])
                if s.contains(pt):
                    val = feature['properties'].get('CEILING')
                    if val is not None:
                        return f"{val} ft (Controlled)"
            except Exception:
                pass
    return "400 ft (Class G)"

@st.cache_data
def fetch_airfields(minx, miny, maxx, maxy):
    pad = 0.2
    query = f"""[out:json];(
      node["aeroway"~"aerodrome|heliport"]({miny-pad},{minx-pad},{maxy+pad},{maxx+pad});
      way["aeroway"~"aerodrome|heliport"]({miny-pad},{minx-pad},{maxy+pad},{maxx+pad});
    );out center;"""
    try:
        req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                     data=query.encode('utf-8'), headers={'User-Agent': 'BRINC_Optimizer'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            airfields = []
            for el in data.get('elements', []):
                lat = el.get('lat') or el.get('center', {}).get('lat')
                lon = el.get('lon') or el.get('center', {}).get('lon')
                name = el.get('tags', {}).get('name', 'Unknown Airfield')
                if lat and lon:
                    airfields.append({'name': name, 'lat': lat, 'lon': lon})
            return airfields
    except Exception:
        return []

def get_nearest_airfield(lat, lon, airfields):
    if not airfields:
        return "No data"
    min_dist = float('inf')
    best = None
    for af in airfields:
        lat1, lon1, lat2, lon2 = map(math.radians, [lat, lon, af['lat'], af['lon']])
        a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
        dist = 3958.8 * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        if dist < min_dist:
            y = math.sin(lon2-lon1)*math.cos(lat2)
            x = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(lon2-lon1)
            bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
            dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW']
            min_dist = dist
            best = (af['name'], dist, dirs[int((bearing+11.25)/22.5) % 16])
    if best:
        n = best[0][:18] + ("..." if len(best[0]) > 18 else "")
        return f"{best[1]:.1f}mi {best[2]} ({n})"
    return "No data"

def generate_random_points_in_polygon(polygon, num_points):
    points = []
    minx, miny, maxx, maxy = polygon.bounds
    while len(points) < num_points:
        x_coords = np.random.uniform(minx, maxx, 1000)
        y_coords = np.random.uniform(miny, maxy, 1000)
        for x, y in zip(x_coords, y_coords):
            if len(points) >= num_points:
                break
            if polygon.contains(Point(x, y)):
                points.append((y, x))
    return points

def generate_clustered_calls(polygon, num_points):
    points = []
    minx, miny, maxx, maxy = polygon.bounds
    hotspots = []
    while len(hotspots) < random.randint(5, 15):
        hx, hy = random.uniform(minx, maxx), random.uniform(miny, maxy)
        if polygon.contains(Point(hx, hy)):
            hotspots.append((hx, hy))
    target_clustered = int(num_points * 0.75)
    while len(points) < target_clustered:
        hx, hy = random.choice(hotspots)
        px, py = np.random.normal(hx, 0.02), np.random.normal(hy, 0.02)
        if polygon.contains(Point(px, py)):
            points.append((py, px))
    while len(points) < num_points:
        px, py = random.uniform(minx, maxx), random.uniform(miny, maxy)
        if polygon.contains(Point(px, py)):
            points.append((py, px))
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

def format_3_lines(name_str):
    match = re.search(r'\s(\d{1,5}\s+[A-Za-z])', name_str)
    if match:
        idx = match.start()
        line1 = name_str[:idx].strip()
        rest = name_str[idx:].strip()
        if ',' in rest:
            parts = rest.split(',', 1)
            return f"{line1}<br>{parts[0].strip()},<br>{parts[1].strip()}"
        return f"{line1}<br>{rest}"
    if ',' in name_str:
        parts = name_str.split(',')
        if len(parts) >= 3:
            return f"{parts[0].strip()},<br>{parts[1].strip()},<br>{','.join(parts[2:]).strip()}"
    return name_str

def to_kml_color(hex_str):
    h = hex_str.lstrip('#')
    return f"ff{h[4:6]}{h[2:4]}{h[0:2]}" if len(h) == 6 else "ff0000ff"

def calculate_zoom(min_lon, max_lon, min_lat, max_lat):
    lon_diff = max_lon - min_lon
    lat_diff = max_lat - min_lat
    if lon_diff <= 0 or lat_diff <= 0: return 12
    return min(max(min(np.log2(360/lon_diff), np.log2(180/lat_diff)) + 1.6, 5), 18)

def generate_kml(active_gdf, active_drones, calls_gdf):
    kml = simplekml.Kml()
    fol_bounds = kml.newfolder(name="Jurisdictions")
    for _, row in active_gdf.iterrows():
        geoms = [row.geometry] if isinstance(row.geometry, Polygon) else row.geometry.geoms
        for geom in geoms:
            pol = fol_bounds.newpolygon(name=row.get('DISPLAY_NAME', 'Boundary'))
            pol.outerboundaryis = list(geom.exterior.coords)
            pol.style.linestyle.color = simplekml.Color.red
            pol.style.linestyle.width = 3
            pol.style.polystyle.color = simplekml.Color.changealphaint(30, simplekml.Color.red)
    fol_stations = kml.newfolder(name="Station Points")
    fol_rings = kml.newfolder(name="Coverage Rings")
    for d in active_drones:
        kml_c = to_kml_color(d['color'])
        pnt = fol_stations.newpoint(name=f"[{d['type'][:3]}] {d['name']}")
        pnt.coords = [(d['lon'], d['lat'])]
        pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/paddle/blu-blank.png'
        lats, lons = get_circle_coords(d['lat'], d['lon'], r_mi=d['radius_m']/1609.34)
        ring_coords = list(zip(lons, lats))
        ring_coords.append(ring_coords[0])
        pol = fol_rings.newpolygon(name=f"Range: {d['name']}")
        pol.outerboundaryis = ring_coords
        pol.style.linestyle.color = kml_c
        pol.style.linestyle.width = 2
        pol.style.polystyle.color = simplekml.Color.changealphaint(60, kml_c)
    fol_calls = kml.newfolder(name="Incident Data (Sample)")
    calls_export = calls_gdf.to_crs(epsg=4326)
    if len(calls_export) > 2000:
        calls_export = calls_export.sample(2000, random_state=42)
    for _, row in calls_export.iterrows():
        pnt = fol_calls.newpoint()
        pnt.coords = [(row.geometry.x, row.geometry.y)]
        pnt.style.iconstyle.scale = 0.5
        pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
    return kml.kml()

@st.cache_data
def find_relevant_jurisdictions(calls_df, stations_df, shapefile_dir):
    points_list = []
    if calls_df is not None: points_list.append(calls_df[['lat', 'lon']])
    if stations_df is not None: points_list.append(stations_df[['lat', 'lon']])
    if not points_list: return None
    full_points = pd.concat(points_list)
    full_points = full_points[(full_points.lat.abs() > 1) & (full_points.lon.abs() > 1)]
    scan_points = full_points.sample(50000, random_state=42) if len(full_points) > 50000 else full_points
    points_gdf = gpd.GeoDataFrame(scan_points, geometry=gpd.points_from_xy(scan_points.lon, scan_points.lat), crs="EPSG:4326")
    total_bounds = points_gdf.total_bounds
    shp_files = glob.glob(os.path.join(shapefile_dir, "*.shp"))
    relevant_polys = []
    for shp_path in shp_files:
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
        except Exception:
            continue
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

@st.cache_resource
def precompute_spatial_data(df_calls, df_stations_all, _city_m, epsg_code, resp_radius_mi, guard_radius_mi, center_lat, center_lon, bounds_hash):
    gdf_calls = gpd.GeoDataFrame(df_calls, geometry=gpd.points_from_xy(df_calls.lon, df_calls.lat), crs="EPSG:4326")
    gdf_calls_utm = gdf_calls.to_crs(epsg=int(epsg_code))
    try:
        calls_in_city = gdf_calls_utm[gdf_calls_utm.within(_city_m)]
    except Exception:
        calls_in_city = gdf_calls_utm
    radius_resp_m = resp_radius_mi * 1609.34
    radius_guard_m = guard_radius_mi * 1609.34
    station_metadata = []
    total_calls = len(calls_in_city)
    n = len(df_stations_all)
    resp_matrix = np.zeros((n, total_calls), dtype=bool)
    guard_matrix = np.zeros((n, total_calls), dtype=bool)
    dist_matrix_r = np.zeros((n, total_calls))
    dist_matrix_g = np.zeros((n, total_calls))
    display_calls = calls_in_city.sample(min(5000, total_calls), random_state=42).to_crs(epsg=4326) if not calls_in_city.empty else gpd.GeoDataFrame()
    max_dist = max(((row['lon']-center_lon)**2 + (row['lat']-center_lat)**2)**0.5 for _, row in df_stations_all.iterrows()) or 1.0
    if not calls_in_city.empty:
        calls_array = np.array(list(zip(calls_in_city.geometry.x, calls_in_city.geometry.y)))
        for idx_pos, (i, row) in enumerate(df_stations_all.iterrows()):
            s_pt_m = gpd.GeoSeries([Point(row['lon'], row['lat'])], crs="EPSG:4326").to_crs(epsg=int(epsg_code)).iloc[0]
            dists = np.sqrt((calls_array[:,0]-s_pt_m.x)**2 + (calls_array[:,1]-s_pt_m.y)**2)
            dists_mi = dists / 1609.34
            mask_r = dists <= radius_resp_m
            mask_g = dists <= radius_guard_m
            resp_matrix[idx_pos, :] = mask_r
            guard_matrix[idx_pos, :] = mask_g
            dist_matrix_r[idx_pos, :] = dists_mi
            dist_matrix_g[idx_pos, :] = dists_mi
            full_buf_2m = s_pt_m.buffer(radius_resp_m)
            try: clipped_2m = full_buf_2m.intersection(_city_m)
            except: clipped_2m = full_buf_2m
            full_buf_guard = s_pt_m.buffer(radius_guard_m)
            try: clipped_guard = full_buf_guard.intersection(_city_m)
            except: clipped_guard = full_buf_guard
            dist_c = ((row['lon']-center_lon)**2 + (row['lat']-center_lat)**2)**0.5
            station_metadata.append({
                'name': row['name'], 'lat': row['lat'], 'lon': row['lon'],
                'clipped_2m': clipped_2m, 'clipped_guard': clipped_guard,
                'avg_dist_r': dists_mi[mask_r].mean() if mask_r.any() else resp_radius_mi*(2/3),
                'avg_dist_g': dists_mi[mask_g].mean() if mask_g.any() else guard_radius_mi*(2/3),
                'centrality': 1.0 - (dist_c / max_dist)
            })
    return calls_in_city, display_calls, resp_matrix, guard_matrix, dist_matrix_r, dist_matrix_g, station_metadata, total_calls

def solve_mclp(resp_matrix, guard_matrix, dist_r, dist_g, num_resp, num_guard, allow_redundancy, incremental=True):
    n_stations, n_calls = resp_matrix.shape
    if n_calls == 0 or (num_resp == 0 and num_guard == 0):
        return [], [], [], []
    df_profiles = pd.DataFrame(resp_matrix.T).astype(int).astype(str)
    df_profiles['g'] = pd.DataFrame(guard_matrix.T).astype(int).astype(str).agg(''.join, axis=1)
    df_profiles['r'] = df_profiles.drop(columns='g').agg(''.join, axis=1)
    grouped = df_profiles.groupby(['r', 'g'], sort=False)
    weights = grouped.size().values
    unique_idx = grouped.head(1).index
    u_resp = resp_matrix[:, unique_idx]
    u_guard = guard_matrix[:, unique_idx]
    u_dist_r = dist_r[:, unique_idx]
    u_dist_g = dist_g[:, unique_idx]
    n_u = len(weights)

    def run_lp(target_r, target_g, locked_r, locked_g):
        model = pulp.LpProblem("DroneCoverage", pulp.LpMaximize)
        x_r = pulp.LpVariable.dicts("r_st", range(n_stations), 0, 1, pulp.LpBinary)
        x_g = pulp.LpVariable.dicts("g_st", range(n_stations), 0, 1, pulp.LpBinary)
        model += pulp.lpSum(x_r[i] for i in range(n_stations)) == target_r
        model += pulp.lpSum(x_g[i] for i in range(n_stations)) == target_g
        for r in locked_r: model += x_r[r] == 1
        for g in locked_g: model += x_g[g] == 1
        if not allow_redundancy:
            for s in range(n_stations): model += x_r[s] + x_g[s] <= 1
        y = pulp.LpVariable.dicts("cl", range(n_u), 0, 1, pulp.LpBinary)
        penalty = 0.00001
        model += pulp.lpSum(y[i]*weights[i] for i in range(n_u)) - pulp.lpSum(
            x_r[s]*np.sum(u_dist_r[s,:])*penalty + x_g[s]*np.sum(u_dist_g[s,:])*penalty
            for s in range(n_stations))
        for i in range(n_u):
            cover = [x_r[s] for s in range(n_stations) if u_resp[s,i]] + [x_g[s] for s in range(n_stations) if u_guard[s,i]]
            if cover: model += y[i] <= pulp.lpSum(cover)
            else: model += y[i] == 0
        model.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=10, gapRel=0.0))
        # FIX #10: use > 0.5 instead of == 1 to handle float solver outputs
        return (
            [i for i in range(n_stations) if (pulp.value(x_r[i]) or 0) > 0.5],
            [i for i in range(n_stations) if (pulp.value(x_g[i]) or 0) > 0.5]
        )

    if not incremental:
        res_r, res_g = run_lp(num_resp, num_guard, [], [])
        return res_r, res_g, res_r, res_g
    curr_r, curr_g = [], []
    chrono_r, chrono_g = [], []
    for tg in range(1, num_guard+1):
        next_r, next_g = run_lp(0, tg, curr_r, curr_g)
        chrono_g.extend([x for x in next_g if x not in curr_g])
        curr_r, curr_g = next_r, next_g
    for tr in range(1, num_resp+1):
        next_r, next_g = run_lp(tr, num_guard, curr_r, curr_g)
        chrono_r.extend([x for x in next_r if x not in curr_r])
        curr_r, curr_g = next_r, next_g
    return curr_r, curr_g, chrono_r, chrono_g

@st.cache_resource
def compute_all_elbow_curves(n_calls, _resp_matrix, _guard_matrix, _geos_r, _geos_g, total_area, _bounds_hash, max_stations=30):
    n_st_calls = min(_resp_matrix.shape[0], max_stations)
    n_st_area  = min(_resp_matrix.shape[0], max_stations * 2)

    def greedy_calls(matrix):
        uncovered = np.ones(n_calls, dtype=bool)
        curve = [0.0]
        cov_count = 0
        import heapq as hq
        pq = [(-matrix[i].sum(), i) for i in range(n_st_calls)]
        hq.heapify(pq)
        for _ in range(n_st_calls):
            if not pq: break
            best_s, best_cov = -1, -1
            while pq:
                neg_gain, idx = hq.heappop(pq)
                actual_gain = (matrix[idx] & uncovered).sum()
                if not pq or actual_gain >= -pq[0][0]:
                    best_s, best_cov = idx, actual_gain
                    break
                else:
                    hq.heappush(pq, (-actual_gain, idx))
            if best_s != -1 and best_cov / max(1, n_calls) >= 0.005:
                uncovered = uncovered & ~matrix[best_s]
                cov_count += best_cov
                curve.append((cov_count / max(1, n_calls)) * 100)
                if cov_count == n_calls: break
            else:
                break
        return curve

    def greedy_area(geos):
        if total_area <= 0: return [0.0]
        current_union = Polygon()
        curve = [0.0]
        import heapq as hq
        geos_sub = geos[:n_st_area]
        
        # Calculate initial areas
        pq = [(-geos_sub[i].area, i) for i in range(len(geos_sub))]
        hq.heapify(pq)
        
        for _ in range(len(geos_sub)):
            if not pq: break
            best_s, best_gain = -1, -1
            
            # Recalculate true overlap gain dynamically (Lazy Greedy)
            while pq:
                neg_gain, idx = hq.heappop(pq)
                try:
                    actual_gain = current_union.union(geos_sub[idx]).area - current_union.area
                except Exception:
                    actual_gain = 0
                    
                if not pq or actual_gain >= -pq[0][0]:
                    best_s, best_gain = idx, actual_gain
                    break
                else:
                    hq.heappush(pq, (-actual_gain, idx))
                    
            if best_s != -1 and best_gain > 0:
                try:
                    current_union = current_union.union(geos_sub[best_s])
                    curve.append((current_union.area / total_area) * 100)
                except Exception:
                    pass
            else:
                break
        return curve

    with ThreadPoolExecutor() as executor:
        f_cr = executor.submit(greedy_calls, _resp_matrix[:n_st_calls])
        f_cg = executor.submit(greedy_calls, _guard_matrix[:n_st_calls])
        f_ar = executor.submit(greedy_area, _geos_r)
        f_ag = executor.submit(greedy_area, _geos_g)
        c_r, c_g, a_r, a_g = f_cr.result(), f_cg.result(), f_ar.result(), f_ag.result()

    max_len = max(len(c_r), len(c_g), len(a_r), len(a_g))
    def pad(c):
        r = list(c)
        while len(r) < max_len: r.append(np.nan)
        return r
    return pd.DataFrame({
        'Drones': range(max_len),
        'Responder (Calls)': pad(c_r),
        'Responder (Area)':  pad(a_r),
        'Guardian (Calls)':  pad(c_g),
        'Guardian (Area)':   pad(a_g)
    })


# ============================================================
# SCENARIO LOADER (sidebar, pre-map)
# ============================================================
if not st.session_state['csvs_ready']:
    with st.sidebar.expander("💾 Load Saved Scenario", expanded=False):
        uploaded_scenario = st.file_uploader("Load .brinc file", type=['brinc','json'], label_visibility="collapsed")
        if uploaded_scenario is not None and st.session_state.get('last_loaded_scenario') != uploaded_scenario.file_id:
            try:
                scenario_data = json.loads(uploaded_scenario.getvalue().decode("utf-8"))
                for k in ['active_city','active_state','k_resp','k_guard','r_resp','r_guard','dfr_rate','deflect_rate']:
                    if k in scenario_data: st.session_state[k] = scenario_data[k]
                calls_data = scenario_data.get('calls_data')
                stations_data = scenario_data.get('stations_data')
                st.session_state['last_loaded_scenario'] = uploaded_scenario.file_id
                if calls_data and stations_data:
                    st.session_state['df_calls'] = pd.DataFrame(calls_data)
                    st.session_state['df_stations'] = pd.DataFrame(stations_data)
                    st.session_state['total_original_calls'] = len(calls_data)
                    st.session_state['csvs_ready'] = True
                    st.toast(f"✅ Loaded scenario for {st.session_state['active_city']}!")
                    st.rerun()
                else:
                    st.session_state['trigger_sim'] = True
                    st.toast(f"✅ Loaded synthetic scenario for {st.session_state['active_city']}!")
                    st.rerun()
            except Exception:
                st.error("Failed to load file — it may be corrupted or incorrectly formatted.")
                st.session_state['last_loaded_scenario'] = uploaded_scenario.file_id

# ============================================================
# ONBOARDING / LANDING PAGE
# ============================================================
if not st.session_state['csvs_ready']:

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
    code.inline {{
        background:#151515; border-radius:3px;
        padding:1px 5px; font-size:0.68rem; color:#aaa;
    }}
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

    <div class="brinc-hero">
        <div class="brinc-eyebrow">BRINC Drones · DFR Platform</div>
        <div class="brinc-h1">
            Coverage. Operations.<br><em>Savings.</em>
        </div>
        <div class="brinc-tagline">
            Optimize drone-as-first-responder deployments for any US jurisdiction.
            Model coverage, forecast ROI, and generate grant-ready proposals in minutes.
        </div>
        <div class="brinc-badges">
            <div class="brinc-badge pulse">🛰 3D Swarm Simulation</div>
            <div class="brinc-badge">🗺 Census Boundaries</div>
            <div class="brinc-badge">📄 Grant Narrative Export</div>
            <div class="brinc-badge">✈️ FAA LAANC Overlay</div>
            <div class="brinc-badge">⚡ MCLP Optimizer</div>
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

        for i in range(st.session_state.city_count):
            c1, c2 = st.columns([3, 1])
            c_val = st.session_state['target_cities'][i]['city'] if i < len(st.session_state['target_cities']) else ""
            s_val = st.session_state['target_cities'][i]['state'] if i < len(st.session_state['target_cities']) else "FL"
            c_name = c1.text_input(
                f"City / Town {i+1}", value=c_val, key=f"c_{i}",
                placeholder="e.g. Orlando",
                help="Official municipality name used to fetch the Census boundary."
            )
            state_idx = list(STATE_FIPS.keys()).index(s_val) if s_val in STATE_FIPS else 8
            s_name = c2.selectbox(
                f"State {i+1}", list(STATE_FIPS.keys()), index=state_idx,
                key=f"s_{i}",
                label_visibility="collapsed" if i > 0 else "visible"
            )
            if i < len(st.session_state['target_cities']):
                st.session_state['target_cities'][i] = {"city": c_name, "state": s_name}
            else:
                st.session_state['target_cities'].append({"city": c_name, "state": s_name})

        col_add, col_run = st.columns([1, 1])
        if st.session_state.city_count < 10:
            if col_add.button("＋ City", use_container_width=True, key="add_city_btn"):
                st.session_state.city_count += 1
                st.rerun()
        submit_demo = col_run.button("▶ Run", use_container_width=True, key="run_sim_btn",
                                     help="Fetch boundaries and launch the simulation.")

    with path_upload_col:
        st.markdown(f"""
        <div class="path-card" style="--accent:#39FF14;">
            <span class="pc-icon">📂</span>
            <div class="pc-tag">Path 02</div>
            <div class="pc-title">Upload<br>Real CAD Data</div>
            <div class="pc-desc">
                Drop your own <code class="inline">calls.csv</code> and
                <code class="inline">stations.csv</code> — both need
                <code class="inline">lat</code> and <code class="inline">lon</code>
                columns. Jurisdiction auto-detected from coordinates.
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        uploaded_files = st.file_uploader(
            "Drop calls.csv & stations.csv",
            accept_multiple_files=True,
            label_visibility="collapsed",
            help="Upload both files together. The uploader accepts multiple files at once."
        )

        st.markdown("""
        <div class="field-footnote">
            <b style='color:#555;'>calls.csv</b> — lat, lon, priority (optional)<br>
            <b style='color:#555;'>stations.csv</b> — lat, lon, name, type (optional)<br>
            Max 25,000 calls · 100 stations
        </div>
        """, unsafe_allow_html=True)

        call_file, station_file = None, None
        if uploaded_files:
            for f in uploaded_files:
                fname = f.name.lower()
                if fname == "calls.csv":    call_file = f
                elif fname == "stations.csv": station_file = f

            if call_file and station_file:
                df_c = pd.read_csv(call_file)
                df_c.columns = [str(c).lower().strip() for c in df_c.columns]
                df_c = df_c.rename(columns={'latitude': 'lat', 'longitude': 'lon'})
                if 'lat' not in df_c.columns or 'lon' not in df_c.columns:
                    st.error(f"❌ calls.csv must have lat/lon columns. Found: {', '.join(df_c.columns)}")
                    st.stop()
                keep_c = ['lat', 'lon'] + (['priority'] if 'priority' in df_c.columns else [])
                df_c = df_c[keep_c].dropna(subset=['lat', 'lon']).reset_index(drop=True)
                st.session_state['total_original_calls'] = len(df_c)
                if len(df_c) > 25000:
                    df_c = df_c.sample(25000, random_state=42).reset_index(drop=True)
                    st.toast("⚠️ Sampled to 25,000 calls for performance.")
                st.session_state['df_calls'] = df_c
                df_s = pd.read_csv(station_file)
                df_s.columns = [str(c).lower().strip() for c in df_s.columns]
                df_s = df_s.rename(columns={'latitude': 'lat', 'longitude': 'lon'})
                if 'lat' not in df_s.columns or 'lon' not in df_s.columns:
                    st.error(f"❌ stations.csv must have lat/lon columns. Found: {', '.join(df_s.columns)}")
                    st.stop()
                keep_s = ['lat', 'lon'] + [c for c in ['name', 'type'] if c in df_s.columns]
                df_s = df_s[keep_s].dropna(subset=['lat', 'lon']).reset_index(drop=True)
                if 'name' not in df_s.columns:
                    df_s['name'] = [f"Station {i+1}" for i in range(len(df_s))]
                if len(df_s) > 100:
                    df_s = df_s.sample(100, random_state=42).reset_index(drop=True)
                st.session_state['df_stations'] = df_s

                # --- NEW OUTLIER FILTER ---
                # Find the bounding box of the actual stations
                lat_min, lat_max = df_s['lat'].min(), df_s['lat'].max()
                lon_min, lon_max = df_s['lon'].min(), df_s['lon'].max()
                
                # Filter out any calls that are more than ~35 miles (0.5 degrees) from the station cluster
                df_c = df_c[
                    (df_c['lat'] >= lat_min - 0.5) & (df_c['lat'] <= lat_max + 0.5) &
                    (df_c['lon'] >= lon_min - 0.5) & (df_c['lon'] <= lon_max + 0.5)
                ]
                
                # Re-save the newly cleaned calls to the session state
                st.session_state['df_calls'] = df_c
                st.session_state['total_original_calls'] = len(df_c)
                # --------------------------
                
                with st.spinner(get_jurisdiction_message()):
                    detected_state_full, detected_city = reverse_geocode_state(
                        df_c['lat'].iloc[0], df_c['lon'].iloc[0]
                    )
                    if detected_state_full and detected_state_full in US_STATES_ABBR:
                        st.session_state['active_state'] = US_STATES_ABBR[detected_state_full]
                        if detected_city and detected_city != 'Unknown City':
                            st.session_state['active_city'] = detected_city
                        st.toast(f"📍 Detected: {st.session_state['active_city']}, {st.session_state['active_state']}")
                st.session_state['csvs_ready'] = True
                st.rerun()
            elif call_file or station_file:
                missing = "stations.csv" if call_file else "calls.csv"
                st.warning(f"⚠️ Also upload **{missing}** to continue.")

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

        if st.button("⚡ Launch Random Demo City", use_container_width=True, key="demo_btn"):
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
            <span>✓</span>Full optimization &amp; export
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="text-align:center; margin-top:8px; font-size:0.63rem; color:#2a2a2a;">
        BRINC Drones, Inc. · <a href="https://brincdrones.com" target="_blank"
        style="color:#333; text-decoration:none;">brincdrones.com</a>
        · All coverage estimates are for planning purposes only.
    </div>
    """, unsafe_allow_html=True)

    if submit_demo or st.session_state.get('trigger_sim', False):
        if st.session_state.get('trigger_sim', False):
            st.session_state['trigger_sim'] = False

        active_targets = [loc for loc in st.session_state['target_cities'] if loc['city'].strip()]
        if not active_targets:
            st.error("Please enter at least one valid city name.")
            st.stop()

        if len(active_targets) == 1:
            st.session_state['active_city']  = active_targets[0]['city']
            st.session_state['active_state'] = active_targets[0]['state']
        else:
            st.session_state['active_city']  = f"{active_targets[0]['city']} & {len(active_targets)-1} others"
            st.session_state['active_state'] = active_targets[0]['state']

        prog = st.progress(0, text="🫡 Preparing tools worthy of those who serve…")
        all_gdfs = []
        total_estimated_pop = 0

        for i, loc in enumerate(active_targets):
            c_name = loc['city'].strip()
            s_name = loc['state']
            prog.progress(10 + int((i / len(active_targets)) * 20),
                          text=f"🗺️ Mapping {c_name}, {s_name} — because every block they patrol matters…")
            success, temp_gdf = fetch_tiger_city_shapefile(STATE_FIPS[s_name], c_name, SHAPEFILE_DIR)
            if success:
                all_gdfs.append(temp_gdf)
                pop = fetch_census_population(STATE_FIPS[s_name], c_name)
                if pop:
                    total_estimated_pop += pop
                    st.toast(f"✅ {c_name} population verified: {pop:,}")
                else:
                    gdf_proj   = temp_gdf.to_crs(epsg=3857)
                    area_sq_mi = gdf_proj.geometry.area.sum() / 2589988.11
                    est = KNOWN_POPULATIONS.get(c_name, int(area_sq_mi * 3500))
                    total_estimated_pop += est
                    st.toast(f"⚠️ {c_name} population estimated: {est:,}")
            else:
                st.warning(f"⚠️ Could not find a boundary for {c_name}, {s_name}. Try another city.")
                if st.session_state.get('_last_demo_city') == c_name:
                    random.seed(datetime.datetime.now().microsecond + os.getpid())
                    candidates = [c for c in DEMO_CITIES if c[0] != c_name]
                    rcity, rstate = random.choice(candidates)
                    st.session_state['_last_demo_city'] = rcity
                    st.session_state['target_cities'] = [{"city": rcity, "state": rstate}]
                    for i in range(10):
                        st.session_state.pop(f"c_{i}", None)
                        st.session_state.pop(f"s_{i}", None)
                    st.rerun()

        if not all_gdfs:
            prog.empty()
            st.error("❌ Could not find Census boundaries for any of the entered locations. Check spelling.")
            st.stop()

        prog.progress(35, text="💙 Boundaries loaded — honoring the officers who know every street…")
        active_city_gdf = pd.concat(all_gdfs, ignore_index=True)
        city_poly = active_city_gdf.geometry.union_all()
        st.session_state['estimated_pop'] = total_estimated_pop

        annual_cfs = int(total_estimated_pop * 0.6)
        st.session_state['total_original_calls'] = annual_cfs
        simulated_points_count = min(int(annual_cfs / 12), 25000)

        prog.progress(55, text="🚔 Modeling 911 calls — every one represents someone who needed help…")
        np.random.seed(42)
        call_points = generate_clustered_calls(city_poly, simulated_points_count)
        st.session_state['df_calls'] = pd.DataFrame({
            'lat':      [p[0] for p in call_points],
            'lon':      [p[1] for p in call_points],
            'priority': np.random.choice(['High', 'Medium', 'Low'], simulated_points_count)
        })

        prog.progress(80, text="🏅 Placing stations — giving officers the best possible backup…")
        station_points = generate_random_points_in_polygon(city_poly, 100)
        types = ['Police', 'Fire', 'EMS'] * 34
        st.session_state['df_stations'] = pd.DataFrame({
            'name': [f'Station {i+1}' for i in range(len(station_points))],
            'lat':  [p[0] for p in station_points],
            'lon':  [p[1] for p in station_points],
            'type': types[:len(station_points)]
        })

        prog.progress(100, text="✅ Ready — built for the communities they protect and serve.")
        st.session_state['inferred_daily_calls_override'] = int(annual_cfs / 365)
        st.session_state['csvs_ready'] = True
        st.rerun()

# ============================================================
# MAIN MAP INTERFACE
# ============================================================
if st.session_state['csvs_ready']:
    components.html("<script>window._brincHasData = true;</script>", height=0)

    df_calls = st.session_state['df_calls'].copy()
    df_stations_all = st.session_state['df_stations'].copy()

    with st.spinner(get_jurisdiction_message()):
        master_gdf = find_relevant_jurisdictions(df_calls, df_stations_all, SHAPEFILE_DIR)

    if master_gdf is None or master_gdf.empty:
        min_lon, min_lat = df_calls['lon'].min(), df_calls['lat'].min()
        max_lon, max_lat = df_calls['lon'].max(), df_calls['lat'].max()
        lon_pad = (max_lon - min_lon) * 0.1
        lat_pad = (max_lat - min_lat) * 0.1
        poly = box(min_lon-lon_pad, min_lat-lat_pad, max_lon+lon_pad, max_lat+lat_pad)
        master_gdf = gpd.GeoDataFrame({'DISPLAY_NAME':['Auto-Generated Boundary'],'data_count':[len(df_calls)]}, geometry=[poly], crs="EPSG:4326")

    st.sidebar.markdown('<div class="sidebar-section-header">① Configure</div>', unsafe_allow_html=True)

    total_pts = master_gdf['data_count'].sum()
    master_gdf['LABEL'] = master_gdf['DISPLAY_NAME'] + " (" + (master_gdf['data_count']/total_pts*100).round(1).astype(str) + "%)"
    options_map = dict(zip(master_gdf['LABEL'], master_gdf['DISPLAY_NAME']))
    all_options = master_gdf['LABEL'].tolist()
    # Only pre-select the first item (the one with the highest call volume)
    default_selection = [all_options[0]] if all_options else []

    selected_labels = st.sidebar.multiselect("Jurisdictions", options=all_options, default=default_selection,
                                         help="Select which geographic areas to include in coverage analysis.")

    if not selected_labels:
        st.warning("Please select at least one jurisdiction from the sidebar.")
        st.stop()
    selected_names = [options_map[l] for l in selected_labels]
    active_gdf = master_gdf[master_gdf['DISPLAY_NAME'].isin(selected_names)]
    if selected_names and st.session_state.get('active_city') == "Orlando":
        st.session_state['active_city'] = selected_names[0]

    filter_expander = st.sidebar.expander("⚙️ Data Filters", expanded=False)
    with filter_expander:
        if 'type' in df_stations_all.columns:
            all_types = sorted(df_stations_all['type'].dropna().astype(str).unique().tolist())
            if all_types:
                selected_types = st.multiselect("Facility Type", options=all_types, default=all_types,
                                                help="Filter which station types are eligible for drone deployment.")
                if not selected_types:
                    st.warning("Select at least one facility type.")
                    st.stop()
                df_stations_all = df_stations_all[df_stations_all['type'].astype(str).isin(selected_types)].copy().reset_index(drop=True)
                df_stations_all['name'] = "[" + df_stations_all['type'].astype(str) + "] " + df_stations_all['name'].astype(str)
        if 'priority' in df_calls.columns:
            all_priorities = sorted(df_calls['priority'].dropna().unique().tolist())
            if all_priorities:
                selected_priorities = st.multiselect("Incident Priority", options=all_priorities, default=all_priorities,
                                                     help="Filter which call priorities to include in coverage scoring.")
                if not selected_priorities:
                    st.warning("Select at least one priority level.")
                    st.stop()
                df_calls = df_calls[df_calls['priority'].isin(selected_priorities)].copy().reset_index(drop=True)

    if len(df_stations_all) == 0:
        st.error("No stations match the selected filters."); st.stop()
    if len(df_calls) == 0:
        st.error("No calls match the selected filters."); st.stop()

    disp_expander = st.sidebar.expander("👁️ Display Options", expanded=False)
    with disp_expander:
        show_boundaries = st.toggle("Jurisdiction Boundaries", value=True)
        show_heatmap    = st.toggle("911 Call Heatmap", value=False)
        show_health     = st.toggle("Health Score", value=False)
        show_satellite  = st.toggle("Satellite Imagery", value=False)
        show_cards      = st.toggle("Unit Economics Cards", value=True)
        show_faa        = st.toggle("FAA LAANC Airspace", value=False)
        simulate_traffic = st.toggle("Simulate Ground Traffic", value=False)
        traffic_level   = st.slider("Traffic Congestion", 0, 100, 40) if simulate_traffic else 40

    strat_expander = st.sidebar.expander("⚙️ Deployment Strategy", expanded=False)
    with strat_expander:
        incremental_build = st.toggle("Phased Rollout", value=True)
        allow_redundancy  = st.toggle("Allow Coverage Overlap", value=True)

    st.sidebar.markdown('<div class="sidebar-section-header">② Optimize Fleet</div>', unsafe_allow_html=True)

    opt_strategy_raw = st.sidebar.radio("Optimization Goal", ("Call Coverage", "Land Coverage"), horizontal=True)
    opt_strategy = "Maximize Call Coverage" if opt_strategy_raw == "Call Coverage" else "Maximize Land Coverage"

    minx, miny, maxx, maxy = active_gdf.to_crs(epsg=4326).total_bounds
    center_lon = (minx + maxx) / 2
    center_lat = (miny + maxy) / 2
    dynamic_zoom = calculate_zoom(minx, maxx, miny, maxy)
    utm_zone = int((center_lon + 180) / 6) + 1
    # FIX #6: epsg_code must be int for geopandas
    epsg_code = int(f"326{utm_zone}") if center_lat > 0 else int(f"327{utm_zone}")

    city_m = None
    city_boundary_geom = None
    try:
        active_utm = active_gdf.to_crs(epsg=epsg_code)
        full_boundary_utm = (active_utm.geometry.union_all() if hasattr(active_utm.geometry, 'union_all')
                             else active_utm.geometry.unary_union).buffer(0.1)
        full_boundary_utm = full_boundary_utm.buffer(-0.1)
        city_m = full_boundary_utm
        city_boundary_geom = gpd.GeoSeries([full_boundary_utm], crs=epsg_code).to_crs(epsg=4326).iloc[0]
    except Exception as e:
        st.error(f"Geometry Error: {e}"); st.stop()

    n = len(df_stations_all)

    # FIX #7: define bounds_hash ONCE after all slider values are known, then call precompute only once
    k_responder = st.sidebar.slider("🚁 Responder Count", 0, max(1, n), min(st.session_state.get('k_resp', 0), n),
                                    help="Short-range tactical drones (2-3mi radius).")
    k_guardian  = st.sidebar.slider("🦅 Guardian Count",  0, max(1, n), min(st.session_state.get('k_guard', 0), n),
                                    help="Long-range heavy-lift drones (up to 8mi radius).")
    resp_radius_mi  = st.sidebar.slider("🚁 Responder Range (mi)", 2.0, 3.0, st.session_state.get('r_resp', 2.0), step=0.5)
    guard_radius_mi = st.sidebar.slider("🦅 Guardian Range (mi)", 1, 8, int(st.session_state.get('r_guard', 8)))
    st.session_state.update({'k_resp': k_responder, 'k_guard': k_guardian, 'r_resp': resp_radius_mi, 'r_guard': guard_radius_mi})

    # Single bounds_hash including radii — used for both precompute and elbow curves
    bounds_hash = f"{minx}_{miny}_{maxx}_{maxy}_{n}_{resp_radius_mi}_{guard_radius_mi}"

    prog2 = st.sidebar.empty()
    prog2.caption(get_spatial_message())
    calls_in_city, display_calls, resp_matrix, guard_matrix, dist_matrix_r, dist_matrix_g, station_metadata, total_calls = precompute_spatial_data(
        df_calls, df_stations_all, city_m, epsg_code, resp_radius_mi, guard_radius_mi, center_lat, center_lon, bounds_hash
    )
    df_curve = compute_all_elbow_curves(
        total_calls, resp_matrix, guard_matrix,
        [s['clipped_2m'] for s in station_metadata],
        [s['clipped_guard'] for s in station_metadata],
        city_m.area if city_m else 1.0, bounds_hash,
        max_stations=30
    )
    prog2.empty()

    def get_max_drones(col_name):
        series = df_curve[col_name].dropna()
        if len(series) == 0: return 1
        idx_99 = series[series >= 99.0].first_valid_index()
        fallback = series.index[-1]
        return int(df_curve.loc[idx_99 if idx_99 is not None else fallback, 'Drones'])

    # Clamp slider maxes now that we have curve data
    max_r = min(max(1, get_max_drones('Responder (Calls)') + 4), n)
    max_g = min(max(1, get_max_drones('Guardian (Calls)') + 4), n)

    with st.spinner(get_faa_message()):
        faa_geojson = load_faa_parquet(minx, miny, maxx, maxy)
    with st.spinner(get_airfield_message()):
        airfields = fetch_airfields(minx, miny, maxx, maxy)

    st.sidebar.markdown('<div class="sidebar-section-header">③ Budget & Export</div>', unsafe_allow_html=True)

    inferred_daily = st.session_state.get('inferred_daily_calls_override', max(1, int(total_calls/365)))
    calls_per_day = st.sidebar.slider("Total Daily Calls (citywide)", 1, max(100, inferred_daily*3), inferred_daily)

    st.sidebar.markdown(f"<div style='font-size:0.72rem; color:{text_muted}; margin-top:8px; margin-bottom:2px;'>DFR Dispatch Rate (%)</div>", unsafe_allow_html=True)
    st.sidebar.markdown(f"<div style='font-size:0.65rem; color:#666; margin-bottom:4px;'>What % of in-range calls will the drone be sent to?</div>", unsafe_allow_html=True)
    dfr_dispatch_rate = st.sidebar.slider("DFR Dispatch Rate", 1, 100, st.session_state.get('dfr_rate',25), label_visibility="collapsed") / 100.0

    st.sidebar.markdown(f"<div style='font-size:0.72rem; color:{text_muted}; margin-top:8px; margin-bottom:2px;'>Calls Resolved Without Officer Dispatch (%)</div>", unsafe_allow_html=True)
    st.sidebar.markdown(f"<div style='font-size:0.65rem; color:#666; margin-bottom:4px;'>Of drone-attended calls, what % close without a patrol car?</div>", unsafe_allow_html=True)
    deflection_rate = st.sidebar.slider("Resolution Rate", 0, 100, st.session_state.get('deflect_rate',30), label_visibility="collapsed") / 100.0

    st.session_state['dfr_rate']    = int(dfr_dispatch_rate * 100)
    st.session_state['deflect_rate'] = int(deflection_rate * 100)

    # ── OPTIMIZATION ──────────────────────────────────────────────────
    active_resp_names, active_guard_names = [], []
    chrono_r, chrono_g = [], []
    best_combo = None

    opt_cache_key = f"{k_responder}_{k_guardian}_{resp_radius_mi}_{guard_radius_mi}_{opt_strategy}_{allow_redundancy}_{incremental_build}_{bounds_hash}"

    if k_responder + k_guardian > n:
        st.error("⚠️ Over-Deployment: Total drones exceed available stations.")
        active_resp_names, active_guard_names = [], []
        chrono_r, chrono_g = [], []
        best_combo = None
    elif k_responder == 0 and k_guardian == 0:
        active_resp_names, active_guard_names = [], []
        chrono_r, chrono_g = [], []
        best_combo = None
    else:
        if st.session_state.get('_opt_cache_key') != opt_cache_key:
            if opt_strategy == "Maximize Call Coverage":
                stage_bar = st.empty()
                stage_bar.info("🧠 Optimizing coverage — because smarter deployment means safer streets…")
                r_best, g_best, chrono_r, chrono_g = solve_mclp(
                    resp_matrix, guard_matrix, dist_matrix_r, dist_matrix_g,
                    k_responder, k_guardian, allow_redundancy, incremental=incremental_build
                )
                best_combo = (tuple(r_best), tuple(g_best))
                stage_bar.empty()
                st.toast("✅ Optimization complete — your officers just got powerful new backup!", icon="✅")
            else:
                def evaluate_combo(rg_combo):
                    r_combo, g_combo = rg_combo
                    if allow_redundancy:
                        score_area = (unary_union([station_metadata[i]['clipped_2m'] for i in r_combo]).area if r_combo else 0.0) + \
                                     (unary_union([station_metadata[i]['clipped_guard'] for i in g_combo]).area if g_combo else 0.0)
                    else:
                        geos = [station_metadata[i]['clipped_2m'] for i in r_combo] + [station_metadata[i]['clipped_guard'] for i in g_combo]
                        score_area = unary_union(geos).area if geos else 0.0
                    cov_r = resp_matrix[list(r_combo)].any(axis=0) if r_combo else np.zeros(total_calls, bool)
                    cov_g = guard_matrix[list(g_combo)].any(axis=0) if g_combo else np.zeros(total_calls, bool)
                    score_calls = np.logical_or(cov_r, cov_g).sum() if total_calls > 0 else 0
                    score_cent  = sum(station_metadata[i]['centrality'] for i in list(r_combo)+list(g_combo))
                    return (score_area, score_calls, score_cent, rg_combo)

                stage_bar = st.empty()
                stage_bar.info("🗺️ Maximizing land coverage — no neighborhood left behind…")
                if incremental_build:
                    locked_r, locked_g = (), ()
                    chrono_r, chrono_g = [], []
                    for _ in range(k_guardian):
                        best_pick = max(
                            [s for s in range(n) if s not in locked_g and (allow_redundancy or s not in locked_r)],
                            key=lambda s: evaluate_combo((locked_r, tuple(sorted(list(locked_g)+[s])))),
                            default=None
                        )
                        if best_pick is not None:
                            locked_g = tuple(sorted(list(locked_g)+[best_pick]))
                            chrono_g.append(best_pick)
                    for _ in range(k_responder):
                        best_pick = max(
                            [s for s in range(n) if s not in locked_r and (allow_redundancy or s not in locked_g)],
                            key=lambda s: evaluate_combo((tuple(sorted(list(locked_r)+[s])), locked_g)),
                            default=None
                        )
                        if best_pick is not None:
                            locked_r = tuple(sorted(list(locked_r)+[best_pick]))
                            chrono_r.append(best_pick)
                    best_combo = (locked_r, locked_g)
                else:
                    total_possible = math.comb(n, k_responder) * (math.comb(n-k_responder, k_guardian) if n >= k_responder else 1)
                    if total_possible > 3000:
                        combos = list(set(
                            (tuple(sorted(c[:k_responder])), tuple(sorted(c[k_responder:])))
                            for c in [np.random.choice(range(n), k_responder+k_guardian, replace=False) for _ in range(3000)]
                        ))
                    else:
                        combos = [(r_c, g_c) for r_c in itertools.combinations(range(n), k_responder)
                                  for g_c in (itertools.combinations([x for x in range(n) if x not in r_c], k_guardian) if k_guardian > 0 else [()])]
                    with ThreadPoolExecutor() as ex:
                        results = list(ex.map(evaluate_combo, combos))
                    best_combo = max(results, key=lambda x: x[:3])[3]
                    chrono_r, chrono_g = list(best_combo[0]), list(best_combo[1])
                stage_bar.empty()
                st.toast("✅ Coverage optimized — every corner of the city now has aerial support!", icon="✅")

            st.session_state['_opt_cache_key']  = opt_cache_key
            st.session_state['_opt_best_combo'] = best_combo
            st.session_state['_opt_chrono_r']   = chrono_r
            st.session_state['_opt_chrono_g']   = chrono_g
        else:
            best_combo = st.session_state.get('_opt_best_combo')
            chrono_r   = st.session_state.get('_opt_chrono_r', [])
            chrono_g   = st.session_state.get('_opt_chrono_g', [])

        if best_combo is not None:
            r_best, g_best = best_combo
            active_resp_names  = [station_metadata[i]['name'] for i in r_best]
            active_guard_names = [station_metadata[i]['name'] for i in g_best]
        else:
            active_resp_names, active_guard_names = [], []

    # ── METRICS ───────────────────────────────────────────────────────
    area_covered_perc = overlap_perc = calls_covered_perc = 0.0
    active_resp_idx  = [i for i,s in enumerate(station_metadata) if s['name'] in active_resp_names]
    active_guard_idx = [i for i,s in enumerate(station_metadata) if s['name'] in active_guard_names]

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
        key = f"{station_metadata[idx]['name']}_{d_type}"
        if key not in active_color_map:
            active_color_map[key] = STATION_COLORS[c_idx % len(STATION_COLORS)]
            c_idx += 1

    active_geos = [station_metadata[i]['clipped_2m'] for i in active_resp_idx] + \
                  [station_metadata[i]['clipped_guard'] for i in active_guard_idx]

    if active_geos and not city_m.is_empty:
        area_covered_perc = (unary_union(active_geos).area / city_m.area) * 100
    if active_geos and total_calls > 0:
        cov_r = resp_matrix[active_resp_idx].any(axis=0) if active_resp_idx else np.zeros(total_calls, bool)
        cov_g = guard_matrix[active_guard_idx].any(axis=0) if active_guard_idx else np.zeros(total_calls, bool)
        calls_covered_perc = (np.logical_or(cov_r, cov_g).sum() / total_calls) * 100
    if active_geos:
        inters = [active_geos[i].intersection(active_geos[j])
                  for i in range(len(active_geos)) for j in range(i+1, len(active_geos))
                  if not active_geos[i].intersection(active_geos[j]).is_empty]
        if inters and not city_m.is_empty:
            overlap_perc = (unary_union(inters).area / city_m.area) * 100

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

    if fleet_capex > 0:
        st.sidebar.markdown(f"""
        <div style="background:{budget_box_bg}; border:1px solid {budget_box_border}; padding:12px; border-radius:4px;
             text-align:center; margin:8px 0 12px 0; box-shadow:0 2px 5px {budget_box_shadow};">
            <div style="font-size:0.7rem; color:{text_muted}; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Annual Capacity Value</div>
            <div style="font-size:1.8rem; font-weight:900; color:{budget_box_border}; font-family:monospace;">${annual_savings:,.0f}</div>
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
    else:
        st.sidebar.info("👈 Set Responder/Guardian counts above to calculate budget impact.")

    # ── BUILD DRONE OBJECTS ───────────────────────────────────────────
    active_drones = []
    cumulative_mask = np.zeros(total_calls, dtype=bool) if total_calls > 0 else None
    step = 1
    for idx, d_type in ordered_deployments_raw:
        if d_type == 'RESPONDER':
            cov_array = resp_matrix[idx]; cost = CONFIG["RESPONDER_COST"]
            speed_mph = CONFIG["RESPONDER_SPEED"]; avg_dist = station_metadata[idx]['avg_dist_r']
            radius_m  = resp_radius_mi * 1609.34
        else:
            cov_array = guard_matrix[idx]; cost = CONFIG["GUARDIAN_COST"]
            speed_mph = CONFIG["GUARDIAN_SPEED"]; avg_dist = station_metadata[idx]['avg_dist_g']
            radius_m  = guard_radius_mi * 1609.34
        map_color    = active_color_map[f"{station_metadata[idx]['name']}_{d_type}"]
        avg_time_min = (avg_dist / speed_mph) * 60
        d_lat = station_metadata[idx]['lat']; d_lon = station_metadata[idx]['lon']

        d = {
            'idx': idx, 'name': station_metadata[idx]['name'],
            'lat': d_lat, 'lon': d_lon, 'type': d_type, 'cost': cost,
            'cov_array': cov_array, 'color': map_color,
            'deploy_step': step if (idx in chrono_r or idx in chrono_g) else "MANUAL",
            'avg_time_min': avg_time_min, 'speed_mph': speed_mph, 'radius_m': radius_m,
            'faa_ceiling': get_station_faa_ceiling(d_lat, d_lon, faa_geojson),
            'nearest_airport': get_nearest_airfield(d_lat, d_lon, airfields)
        }

        if total_calls > 0 and cumulative_mask is not None:
            marginal_mask    = cov_array & ~cumulative_mask
            marginal_historic = np.sum(marginal_mask)
            d['assigned_indices'] = np.where(marginal_mask)[0]
            cumulative_mask  = cumulative_mask | cov_array
            d['marginal_perc'] = marginal_historic / total_calls
            marginal_daily   = calls_per_day * d['marginal_perc']
            d['marginal_flights']   = marginal_daily * dfr_dispatch_rate
            d['marginal_deflected'] = d['marginal_flights'] * deflection_rate
            all_cov = np.vstack([resp_matrix[i] for i in active_resp_idx] + [guard_matrix[i] for i in active_guard_idx]) if (active_resp_idx or active_guard_idx) else np.zeros((1, total_calls), dtype=bool)
            shared_mask = d['cov_array'] & (all_cov.sum(axis=0) > 1)
            d['shared_flights']  = (np.sum(shared_mask) / total_calls) * calls_per_day * dfr_dispatch_rate
            d['monthly_savings'] = (CONFIG["OFFICER_COST_PER_CALL"] - CONFIG["DRONE_COST_PER_CALL"]) * d['marginal_deflected'] * 30.4
            d['annual_savings']  = d['monthly_savings'] * 12
            d['be_text'] = f"{d['cost']/d['monthly_savings']:.1f} MO" if d['monthly_savings'] > 0 else "N/A"
        else:
            d.update({'assigned_indices':[],'annual_savings':0,'marginal_flights':0,
                      'marginal_deflected':0,'shared_flights':0,'be_text':"N/A"})
        active_drones.append(d)
        step += 1

    # ── EXPORT BUTTONS ────────────────────────────────────────────────
    if fleet_capex > 0:
        st.sidebar.markdown("---")
        col_n, col_e = st.sidebar.columns(2)
        prop_name  = col_n.text_input("Your Name",  value=st.session_state.get('user_name', 'John Doe'), key='user_name')
        prop_email = col_e.text_input("Your Email", value=st.session_state.get('user_email', 'john.doe@example.com'), key='user_email')
        st.sidebar.caption("*(Press **Enter** after typing to apply changes to your document)*")

        prop_city  = st.session_state.get('active_city', 'City')
        prop_state = st.session_state.get('active_state', 'FL')
        pop_metric = st.session_state.get('estimated_pop', 250000)
        current_time_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_city = prop_city.replace(" ","_").replace("/","_")

        export_dict = {
            "city": prop_city, "state": prop_state,
            "k_resp": k_responder, "k_guard": k_guardian,
            "r_resp": resp_radius_mi, "r_guard": guard_radius_mi,
            "dfr_rate": int(dfr_dispatch_rate*100), "deflect_rate": int(deflection_rate*100),
            "calls_data": json.loads(st.session_state['df_calls'].replace({np.nan:None}).to_json(orient='records')) if st.session_state.get('df_calls') is not None else None,
            "stations_data": json.loads(st.session_state['df_stations'].replace({np.nan:None}).to_json(orient='records')) if st.session_state.get('df_stations') is not None else None,
            "faa_geojson": faa_geojson
        }

        avg_resp_time  = sum(d['avg_time_min'] for d in active_drones)/len(active_drones) if active_drones else 0.0
        avg_ground_speed = CONFIG["DEFAULT_TRAFFIC_SPEED"] * (1 - traffic_level/100)
        avg_time_saved = ((sum((d['radius_m']/1609.34*1.4/avg_ground_speed)*60 for d in active_drones)/len(active_drones)) - avg_resp_time) if active_drones and avg_ground_speed > 0 else 0.0

        fig_for_export = go.Figure()
        for d in active_drones:
            clats, clons = get_circle_coords(d['lat'], d['lon'], r_mi=d['radius_m']/1609.34)
            fig_for_export.add_trace(go.Scattermapbox(
                lat=list(clats)+[None,d['lat']], lon=list(clons)+[None,d['lon']],
                mode='lines+markers', line=dict(color=d['color'], width=3),
                marker=dict(size=[0]*len(clats)+[0,16], color=d['color']),
                fill='toself', fillcolor='rgba(0,0,0,0)', name=d['name'][:30]
            ))
        fig_for_export.update_layout(
            mapbox=dict(center=dict(lat=center_lat, lon=center_lon), zoom=dynamic_zoom, style="carto-darkmatter"),
            margin=dict(l=0,r=0,t=0,b=0), height=500, showlegend=True,
            legend=dict(bgcolor=legend_bg, font=dict(color=legend_text, size=11))
        )
        map_html_str = fig_for_export.to_html(full_html=False, include_plotlyjs='cdn', default_height='500px', default_width='100%')
        station_rows = "".join(f"<tr><td>{d['name']}</td><td>{d['type']}</td><td>{d['avg_time_min']:.1f} min</td><td>{d['faa_ceiling']}</td><td>${d['cost']:,}</td></tr>" for d in active_drones)

        logo_b64 = get_base64_of_bin_file("logo.png")
        logo_html_str = f'<img src="data:image/png;base64,{logo_b64}" style="height:40px;">' if logo_b64 else '<div style="font-size:28px;font-weight:900;letter-spacing:3px;color:#111;">BRINC</div>'

        # ── GRANT NARRATIVE VARIABLES ─────────────────────────────────────
        jurisdiction_list = ", ".join(selected_names) if selected_names else prop_city
        # FIX #1 (original): Guard 'type' column access throughout
        all_station_types = df_stations_all['type'].dropna().unique().tolist() if 'type' in df_stations_all.columns else []
        police_dept_names = [d['name'] for d in active_drones if '[Police]' in d['name']]
        fire_dept_names   = [d['name'] for d in active_drones if '[Fire]' in d['name']]
        ems_dept_names    = [d['name'] for d in active_drones if '[EMS]' in d['name']]

        # FIX #1 (original): safe access with column existence guard
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
        area_sq_mi_est = int((maxx - minx) * (maxy - miny) * 3280)

        export_html = f"""<html><head><title>BRINC DFR Proposal — {prop_city}</title>
        <style>
        body{{font-family:'Helvetica Neue',Arial,sans-serif;color:#333;margin:0;padding:40px;background:#f4f6f9;}}
        .page{{max-width:1000px;margin:0 auto;background:#fff;padding:50px;border-radius:8px;box-shadow:0 4px 15px rgba(0,0,0,0.05);}}
        .header{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #00D2FF;padding-bottom:15px;margin-bottom:30px;}}
        h1{{color:#000;margin:0;font-size:24px;}} h2{{color:#444;margin-top:30px;font-size:18px;border-bottom:1px solid #ddd;padding-bottom:5px;}}
        table{{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px;}}
        th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #ddd;}}
        th{{background:#f1f1f1;font-size:12px;text-transform:uppercase;color:#555;}}
        .map-container{{border:1px solid #ddd;border-radius:8px;overflow:hidden;margin-top:10px;}}
        .footer{{margin-top:40px;padding-top:20px;border-top:2px solid #eee;text-align:center;font-size:13px;color:#555;line-height:1.6;}}
        .footer a{{color:#00D2FF;text-decoration:none;font-weight:bold;}}
        .kpi-grid{{display:flex;gap:20px;margin-bottom:30px;}}
        .kpi-box{{flex:1;border:1px solid #eaeaea;border-radius:8px;padding:20px;background:#fafafa;}}
        .kpi-box h2{{margin-top:0;}}
        .kpi-val{{font-size:22px;font-weight:bold;color:#00D2FF;}}
        .kpi-lbl{{font-size:11px;font-weight:bold;color:#888;text-transform:uppercase;}}
        .disclaimer{{background:#fff3cd;border-left:4px solid #ffeeba;padding:12px;margin-bottom:16px;font-size:12px;color:#856404;}}
        </style></head><body><div class="page">
        <div class="header"><div>{logo_html_str}</div>
        <div style="text-align:right;"><h1>DFR Deployment Proposal</h1>
        <div style="font-size:14px;color:#666;margin-top:5px;">For: {prop_city}, {prop_state} | Pop: {pop_metric:,}</div>
        <div style="font-size:14px;color:#666;margin-top:3px;">By: {prop_name} | {prop_email}</div></div></div>
        <div class="kpi-grid">
        <div class="kpi-box"><h2>Financial</h2>
          <div class="kpi-lbl">Fleet CapEx</div><div class="kpi-val">${fleet_capex:,.0f}</div>
          <div class="kpi-lbl" style="margin-top:12px;">Annual Savings Capacity</div><div class="kpi-val">${annual_savings:,.0f}</div>
          <div class="kpi-lbl" style="margin-top:12px;">Break-Even</div><div class="kpi-val">{break_even_text}</div>
        </div>
        <div class="kpi-box"><h2>Operational</h2>
          <div class="kpi-lbl">911 Call Coverage</div><div class="kpi-val">{calls_covered_perc:.1f}%</div>
          <div class="kpi-lbl" style="margin-top:12px;">Avg Response Time</div><div class="kpi-val">{avg_resp_time:.1f} min</div>
          <div class="kpi-lbl" style="margin-top:12px;">Time Saved vs Patrol</div><div class="kpi-val">{avg_time_saved:.1f} min</div>
        </div></div>
        <h2>Proposed Fleet</h2>
        <table><tr><th>Type</th><th>Qty</th><th>Range</th><th>Unit Cost</th></tr>
        <tr><td>BRINC Responder</td><td>{actual_k_responder}</td><td>{resp_radius_mi} mi</td><td>${CONFIG['RESPONDER_COST']:,}</td></tr>
        <tr><td>BRINC Guardian</td><td>{actual_k_guardian}</td><td>{guard_radius_mi} mi</td><td>${CONFIG['GUARDIAN_COST']:,}</td></tr></table>
        <h2>Coverage Map</h2>
        <div class="map-container">{map_html_str}</div>
        <h2>Deployment Locations</h2>
        <table><tr><th>Station</th><th>Type</th><th>Avg Response</th><th>FAA Ceiling</th><th>CapEx</th></tr>{station_rows}</table>
        <h2>Grant Narrative (AI Draft)</h2>
        <div class="disclaimer"><strong>DISCLAIMER:</strong> AI-generated draft. Must be reviewed, localized, and fact-checked by your grants administrator before submission. All statistics are model estimates.</div>

        <p><strong>Project Title:</strong> BRINC Drones Drone as a First Responder (DFR) Program — {jurisdiction_list}</p>

        <p><strong>Executive Summary:</strong> The {jurisdiction_list} respectfully submits this application requesting funding to establish a BRINC Drones-powered Drone as a First Responder (DFR) program. This initiative will deploy a fleet of {total_fleet} purpose-built BRINC Drones aerial systems — comprising {actual_k_responder} BRINC Responder and {actual_k_guardian} BRINC Guardian units — across {dept_summary} serving a combined population of {pop_metric:,} residents across approximately {area_sq_mi_est:,} square miles in {prop_city}, {prop_state}.</p>

        <p><strong>Statement of Need:</strong> The {jurisdiction_list} currently serves a population of {pop_metric:,} residents and responds to an estimated {st.session_state.get('total_original_calls', total_calls):,} calls for service annually. Ground-based patrol response times are constrained by traffic, geography, and unit availability. This proposal addresses a critical public safety gap: the need for immediate aerial situational awareness that arrives before ground units, enabling smarter, safer, and faster emergency response. BRINC Drones, the world leader in purpose-built DFR technology, provides the only fully integrated hardware, software, and operational support platform purpose-designed for law enforcement DFR deployment.</p>

        <p><strong>Geographic Scope &amp; Participating Agencies:</strong> The proposed DFR network covers the jurisdictions of <strong>{jurisdiction_list}</strong> ({prop_state}). Drone stations will be hosted at {dept_summary}, including facilities operated by: <em>{police_names_str}</em>. The deployment area encompasses an estimated {area_sq_mi_est:,} square miles of mixed urban and suburban terrain, with BRINC Drones units positioned to achieve {calls_covered_perc:.1f}% coverage of historical incident locations and {area_covered_perc:.1f}% geographic area coverage.</p>

        <p><strong>Program Design:</strong> The proposed fleet consists of {actual_k_responder} <strong>BRINC Responder</strong> units (short-range tactical response, {resp_radius_mi}-mile operational radius) and {actual_k_guardian} <strong>BRINC Guardian</strong> units (long-range heavy-lift, {guard_radius_mi}-mile operational radius). All deployment sites have been pre-screened against FAA LAANC UAS Facility Maps. The BRINC Drones platform provides automated launch-on-dispatch, live-streaming HD/thermal video to dispatch and responding officers, and full chain-of-custody flight logging. Average aerial response time under this configuration is projected at <strong>{avg_resp_time:.1f} minutes</strong> — approximately <strong>{avg_time_saved:.1f} minutes faster</strong> than current vehicular patrol response for equivalent distances.</p>

        <p><strong>Fiscal Impact &amp; Return on Investment:</strong> Total program capital expenditure is <strong>${fleet_capex:,.0f}</strong>. Based on a {int(dfr_dispatch_rate*100)}% DFR dispatch rate and {int(deflection_rate*100)}% call resolution rate, the program is projected to generate <strong>${annual_savings:,.0f} in annual operational savings</strong> through reduced officer dispatch on drone-resolved incidents, reaching full cost recovery in <strong>{break_even_text.lower()}</strong>. At ${CONFIG["DRONE_COST_PER_CALL"]}/drone response versus ${CONFIG["OFFICER_COST_PER_CALL"]}/officer dispatch, the BRINC Drones platform delivers a demonstrated cost-per-response reduction of over {int((1 - CONFIG["DRONE_COST_PER_CALL"]/CONFIG["OFFICER_COST_PER_CALL"])*100)}%.</p>

        <p><strong>About BRINC Drones:</strong> BRINC Drones, Inc. is the global leader in purpose-built Drone as a First Responder technology, with deployments across hundreds of law enforcement agencies in the United States. BRINC Drones designs, manufactures, and supports the only DFR platform built from the ground up for public safety — including the BRINC Responder for rapid tactical response and the BRINC Guardian for extended-range operations. BRINC provides full agency onboarding, FAA coordination support, pilot training, and ongoing operational guidance. Learn more at <a href="https://brincdrones.com" target="_blank">brincdrones.com</a>.</p>

        <p><strong>Potential Grant Funding Sources:</strong>
          <a href="https://bja.ojp.gov/program/jag/overview" target="_blank">DOJ Byrne JAG</a> — UAS and technology procurement eligible &nbsp;•&nbsp;
          <a href="https://www.fema.gov/grants/preparedness/homeland-security" target="_blank">FEMA HSGP</a> — CapEx offset for tactical deployments &nbsp;•&nbsp;
          <a href="https://cops.usdoj.gov/grants" target="_blank">DOJ COPS Office</a> — Law enforcement technology grants &nbsp;•&nbsp;
          <a href="https://www.transportation.gov/grants" target="_blank">DOT RAISE</a> — Regional infrastructure and safety
        </p>
        <div class="footer">
          <div style="font-size:20px;font-weight:900;letter-spacing:2px;color:#111;margin-bottom:4px;">BRINC</div>
          <div style="font-weight:bold;margin-bottom:4px;">BRINC Drones, Inc.</div>
          <div style="margin-bottom:8px;">Leading the world in purpose-built Drone as a First Responder technology.</div>
          <div style="margin-bottom:8px;font-weight:bold;">Prepared by: {prop_name} | <a href="mailto:{prop_email}">{prop_email}</a></div>
          <div style="margin-bottom:8px;">
            <a href="https://brincdrones.com" target="_blank">brincdrones.com</a> | <a href="mailto:sales@brincdrones.com">sales@brincdrones.com</a> | +1 (855) 950-0226
          </div>
          <div>
            <a href="https://www.linkedin.com/company/brincdrones" target="_blank">LinkedIn</a> •
            <a href="https://twitter.com/brincdrones" target="_blank">Twitter / X</a> •
            <a href="https://www.youtube.com/c/brincdrones" target="_blank">YouTube</a>
          </div>
        </div></div></body></html>"""

        if st.sidebar.download_button("💾 Save Deployment Plan", data=json.dumps(export_dict),
                                      file_name=f"Brinc_{safe_city}_{current_time_str}.brinc",
                                      mime="application/json", use_container_width=True):
            _notify_email(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                          "BRINC", k_responder, k_guardian, calls_covered_perc,
                          st.session_state.get('user_name',''), st.session_state.get('user_email',''))
            _log_to_sheets(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                           "BRINC", k_responder, k_guardian, calls_covered_perc,
                           st.session_state.get('user_name',''), st.session_state.get('user_email',''))

        if st.sidebar.download_button("📄 Executive Summary (HTML)", data=export_html,
                                      file_name=f"Brinc_{safe_city}_Proposal_{current_time_str}.html",
                                      mime="text/html", use_container_width=True):
            _notify_email(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                          "HTML", k_responder, k_guardian, calls_covered_perc,
                          st.session_state.get('user_name',''), st.session_state.get('user_email',''))
            _log_to_sheets(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                           "HTML", k_responder, k_guardian, calls_covered_perc,
                           st.session_state.get('user_name',''), st.session_state.get('user_email',''))

        if active_drones:
            if st.sidebar.download_button("🌏 Google Earth Briefing File", data=generate_kml(active_gdf, active_drones, calls_in_city),
                                          file_name="drone_deployment.kml", mime="application/vnd.google-earth.kml+xml",
                                          use_container_width=True):
                _notify_email(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                              "KML", k_responder, k_guardian, calls_covered_perc,
                              st.session_state.get('user_name',''), st.session_state.get('user_email',''))
                _log_to_sheets(st.session_state.get('active_city',''), st.session_state.get('active_state',''),
                               "KML", k_responder, k_guardian, calls_covered_perc,
                               st.session_state.get('user_name',''), st.session_state.get('user_email',''))

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

    if simulate_traffic:
        avg_ground_speed = CONFIG["DEFAULT_TRAFFIC_SPEED"] * (1 - traffic_level/100)
        eval_dist  = guard_radius_mi if active_guard_names else resp_radius_mi
        eval_speed = CONFIG["GUARDIAN_SPEED"] if active_guard_names else CONFIG["RESPONDER_SPEED"]
        if (active_resp_names or active_guard_names) and avg_ground_speed > 0:
            time_saved = ((eval_dist*1.4/avg_ground_speed) - (eval_dist/eval_speed)) * 60
            gain_val = f"{time_saved:.1f} min"
        else:
            gain_val = "N/A"
    else:
        gain_val = None

    kpi_html = f"""
    <div style="display:flex; justify-content:space-around; background:{card_bg}; border:1px solid {card_border}; border-radius:8px; padding:15px; margin-bottom:15px; flex-wrap:wrap; gap:10px;">
        <div style="text-align:center;"><div style="font-size:0.75rem; color:{text_muted}; text-transform:uppercase;">Total Incidents</div><div style="font-size:1.6rem; font-weight:800; color:{accent_color}; font-family:'IBM Plex Mono', monospace;">{st.session_state.get('total_original_calls',total_calls):,}</div></div>
        <div style="text-align:center;"><div style="font-size:0.75rem; color:{text_muted}; text-transform:uppercase;">Response Capacity</div><div style="font-size:1.6rem; font-weight:800; color:{accent_color}; font-family:'IBM Plex Mono', monospace;">{calls_covered_perc:.1f}%</div></div>
        <div style="text-align:center;"><div style="font-size:0.75rem; color:{text_muted}; text-transform:uppercase;">Land Covered</div><div style="font-size:1.6rem; font-weight:800; color:{accent_color}; font-family:'IBM Plex Mono', monospace;">{area_covered_perc:.1f}%</div></div>
        <div style="text-align:center;"><div style="font-size:0.75rem; color:{text_muted}; text-transform:uppercase;">Overlap</div><div style="font-size:1.6rem; font-weight:800; color:{accent_color}; font-family:'IBM Plex Mono', monospace;">{overlap_perc:.1f}%</div></div>
    """
    if gain_val is not None:
        kpi_html += f"""<div style="text-align:center;"><div style="font-size:0.75rem; color:{text_muted}; text-transform:uppercase;">Time Saved ({eval_dist:.0f}mi)</div><div style="font-size:1.6rem; font-weight:800; color:{accent_color}; font-family:'IBM Plex Mono', monospace;">{gain_val}</div></div>"""
    kpi_html += "</div>"
    st.markdown(kpi_html, unsafe_allow_html=True)
    st.markdown(f"<div style='font-size:0.65rem;color:gray;margin-top:-12px;margin-bottom:12px;text-align:center;'>(Optimized via {total_calls:,} representative sample)</div>", unsafe_allow_html=True)

    map_col, stats_col = st.columns([4.2, 1.8])

    with map_col:
        fig = go.Figure()

        if show_boundaries and city_boundary_geom is not None and not city_boundary_geom.is_empty:
            geoms_to_draw = [city_boundary_geom] if isinstance(city_boundary_geom, Polygon) else list(city_boundary_geom.geoms)
            for gi, geom in enumerate(geoms_to_draw):
                bx, by = geom.exterior.coords.xy
                fig.add_trace(go.Scattermapbox(mode="lines", lon=list(bx), lat=list(by),
                    line=dict(color=map_boundary_color, width=2), name="Jurisdiction Boundary",
                    hoverinfo='skip', showlegend=(gi==0)))

        if show_heatmap and not display_calls.empty:
            fig.add_trace(go.Densitymapbox(lat=display_calls.geometry.y, lon=display_calls.geometry.x,
                z=np.ones(len(display_calls)), radius=12, colorscale='Inferno', opacity=0.6,
                showscale=False, name="Heatmap", hoverinfo='skip'))

        if not display_calls.empty:
            fig.add_trace(go.Scattermapbox(lat=display_calls.geometry.y, lon=display_calls.geometry.x,
                mode='markers', marker=dict(size=4, color=map_incident_color, opacity=0.4),
                name="Incident Data", hoverinfo='skip'))

        if show_faa and faa_geojson:
            add_faa_laanc_layer_to_plotly(fig, faa_geojson, is_dark=not show_satellite)

        for d in active_drones:
            clats, clons = get_circle_coords(d['lat'], d['lon'], r_mi=d['radius_m']/1609.34)
            lbl = f"{d['name'].split(',')[0]} ({'Resp' if d['type']=='RESPONDER' else 'Guard'})"
            fig.add_trace(go.Scattermapbox(
                lat=list(clats)+[None,d['lat']], lon=list(clons)+[None,d['lon']],
                mode='lines+markers',
                marker=dict(size=[0]*len(clats)+[0,20], color=d['color']),
                line=dict(color=d['color'], width=4.5),
                fill='toself', fillcolor='rgba(0,0,0,0)', name=lbl, hoverinfo='name'))

            # Guardian 5-mile rapid response focus ring
            if d['type'] == 'GUARDIAN' and d['radius_m']/1609.34 > 5.0:
                f_lats, f_lons = get_circle_coords(d['lat'], d['lon'], r_mi=5.0)
                fig.add_trace(go.Scattermapbox(
                    lat=list(f_lats), lon=list(f_lons),
                    mode='lines',
                    line=dict(color=d['color'], width=1.5),
                    opacity=0.5,
                    fill='toself',
                    fillcolor=f"rgba({int(d['color'][1:3],16)},{int(d['color'][3:5],16)},{int(d['color'][5:7],16)},0.06)",
                    name=f"Focus Zone 5mi · {d['name'].split(',')[0]}",
                    hoverinfo='text',
                    text=f"⚡ Rapid Response Focus Zone — 5mi<br>{d['name'].split(',')[0]}",
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
                    fig.add_trace(go.Scattermapbox(
                        lat=list(d['lat']+(gr_mi/69.172)*np.sin(ga)),
                        lon=list(d['lon']+(gr_mi/(69.172*np.cos(np.radians(d['lat']))))*np.cos(ga)),
                        mode='lines', line=dict(color=t_color, width=2.5),
                        fill='toself', fillcolor=t_fill,
                        name=f"Ground ({t_label})", hoverinfo='skip'))

        mapbox_cfg = dict(center=dict(lat=center_lat, lon=center_lon), zoom=dynamic_zoom, style=map_style)
        if show_satellite:
            mapbox_cfg["style"] = "carto-positron"
            mapbox_cfg["layers"] = [{"below":"traces","sourcetype":"raster",
                "sourceattribution":"Esri, Maxar, Earthstar Geographics",
                "source":["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"]}]

        fig.update_layout(uirevision="LOCKED_MAP", mapbox=mapbox_cfg,
            margin=dict(l=0,r=0,t=0,b=0), height=800, font=dict(size=18),
            showlegend=True,
            legend=dict(yanchor="top", y=0.98, xanchor="left", x=0.02,
                        bgcolor=legend_bg, bordercolor=accent_color, borderwidth=1,
                        font=dict(size=12, color=legend_text), itemclick="toggle"))

        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})

    with stats_col:
        st.markdown(f"<h4 style='margin-top:0; border-bottom:1px solid {card_border}; padding-bottom:8px; color:{text_main};'>Coverage Curve</h4>", unsafe_allow_html=True)

        if not df_curve.empty:
            fig_curve = go.Figure()
            for col, color, dash in [('Responder (Calls)',accent_color,'solid'),('Guardian (Calls)','#FFD700','solid'),
                                      ('Responder (Area)',accent_color,'dash'),('Guardian (Area)','#FFD700','dash')]:
                y_data = df_curve[col].dropna()
                x_data = df_curve.loc[y_data.index,'Drones']
                if not y_data.empty:
                    fig_curve.add_trace(go.Scatter(x=x_data, y=y_data, mode='lines+markers', name=col,
                        line=dict(color=color,width=2,dash=dash), marker=dict(size=4)))
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
                margin=dict(l=10,r=10,t=20,b=10), height=260,
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig_curve, use_container_width=True, config={'displayModeBar':False})

        if show_cards:
            st.markdown(f"<h4 style='margin-top:8px; border-bottom:1px solid {card_border}; padding-bottom:8px; color:{text_main};'>Unit Economics</h4>", unsafe_allow_html=True)
            if not active_drones:
                st.markdown(f"""
                <div style="background:{card_bg}; border:1px dashed {card_border}; border-radius:6px;
                     padding:24px; text-align:center; margin-top:10px;">
                    <div style="font-size:2rem; margin-bottom:8px;">🚁</div>
                    <div style="font-weight:700; color:{text_main}; margin-bottom:6px;">No drones deployed yet</div>
                    <div style="font-size:0.8rem; color:{text_muted};">
                        👈 Use the <b>Responder / Guardian Count</b> sliders in the <b>② Optimize Fleet</b> sidebar section to deploy drones and see per-unit economics here.
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                for i in range(0, len(active_drones), 2):
                    cols = st.columns(2)
                    for j in range(2):
                        if i + j < len(active_drones):
                            d = active_drones[i + j]
                            short_name  = format_3_lines(d['name'])
                            d_color     = d['color']
                            d_type      = d['type']
                            d_step      = d['deploy_step']
                            d_savings   = d['annual_savings']
                            d_flights   = d['marginal_flights']
                            d_shared    = d['shared_flights']
                            d_deflected = d['marginal_deflected']
                            d_time      = d['avg_time_min']
                            d_faa       = d['faa_ceiling']
                            d_airport   = d['nearest_airport']
                            d_cost      = d['cost']
                            d_be        = d['be_text']
                            cols[j].markdown(f"""
<div style="background:{card_bg}; border-top:4px solid {d_color};
     border-left:1px solid {card_border}; border-right:1px solid {card_border};
     border-bottom:1px solid {card_border};
     border-radius:4px; padding:12px; margin-bottom:12px;">
    <div style="font-weight:700; font-size:0.73rem; color:{card_title}; margin-bottom:2px;">{short_name}</div>
    <div style="font-size:0.58rem; color:#888; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px;">{d_type} · Phase #{d_step}</div>
    <div style="background:rgba(0,210,255,0.07); border-radius:4px; padding:8px; text-align:center; margin-bottom:8px;">
        <div style="font-size:0.6rem; color:{text_muted}; text-transform:uppercase; letter-spacing:0.5px;">Annual Capacity Value</div>
        <div style="font-size:1.25rem; font-weight:900; color:{accent_color};">${d_savings:,.0f}</div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px; font-size:0.62rem;">
        <div style="color:{text_muted};">Net Flights/day</div>
        <div style="text-align:right; font-weight:700; color:{accent_color};">{d_flights:.1f}</div>
        <div style="color:{text_muted};">Shared Flights/day</div>
        <div style="text-align:right; font-weight:700; color:{card_title};">{d_shared:.1f}</div>
        <div style="color:{text_muted};">Resolved/day</div>
        <div style="text-align:right; font-weight:700; color:{card_title};">{d_deflected:.1f}</div>
        <div style="color:{text_muted};">Avg Response</div>
        <div style="text-align:right; font-weight:700; color:{card_title};">{d_time:.1f} min</div>
        <div style="color:{text_muted};">FAA Ceiling</div>
        <div style="text-align:right; font-weight:700; color:{card_title};">{d_faa}</div>
        <div style="color:{text_muted};">Nearest Airfield</div>
        <div style="text-align:right; font-weight:700; color:{card_title}; font-size:0.55rem;">{d_airport}</div>
    </div>
    <div style="border-top:1px dashed {card_border}; margin-top:8px; padding-top:6px;
         display:grid; grid-template-columns:1fr 1fr; gap:4px; font-size:0.62rem;">
        <div style="color:{text_muted};">CapEx</div>
        <div style="text-align:right; font-weight:700; color:{card_title};">${d_cost:,.0f}</div>
        <div style="color:{text_muted};">ROI</div>
        <div style="text-align:right; font-weight:800; color:{accent_color};">{d_be}</div>
    </div>
</div>
""", unsafe_allow_html=True)

    # ── 3D SWARM SIMULATION ───────────────────────────────────────────
    if fleet_capex > 0:
        st.markdown("---")
        st.markdown(f"<h3 style='color:{text_main};'>🚁 3D Swarm Simulation</h3>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:0.82rem; color:{text_muted}; margin-bottom:10px;'>Animated deck.gl simulation of all DFR flights over a compressed 24-hour day. Use the speed slider to accelerate or slow the simulation. Great for council presentations.</div>", unsafe_allow_html=True)

        show_sim = st.toggle("🎬 Enable 3D Simulation", value=False)
        if show_sim:
            # FIX #4: use .geometry.x/.y instead of ['lon']/['lat'] on GeoDataFrame
            calls_coords = np.column_stack((calls_in_city.geometry.x, calls_in_city.geometry.y))

            # Project calls back to lon/lat for simulation (calls_in_city is in UTM)
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

                # FIX #13: guard against empty pool before random.choices
                if not pool:
                    sim_calls = []
                elif monthly_for_drone > len(pool):
                    sim_calls = random.choices(pool, k=monthly_for_drone)
                else:
                    sim_calls = random.sample(pool, monthly_for_drone)

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
                        "path": [
                            [lon0, lat0, 0],
                            [mx1,  my1,  arc_h*0.75],
                            [mx2,  my2,  arc_h],
                            [mx3,  my3,  arc_h],
                            [mx4,  my4,  arc_h*0.75],
                            [lon1, lat1, 0]
                        ],
                        "timestamps": [t0, t1, t2, t3, t4, t5],
                        "color": rgb
                    })

            warn_html_sim = ""
            if len(flights_json) > 3000:
                flights_json = random.sample(flights_json, 3000)
                warn_html_sim = f'<div style="background:#440000;border:1px solid #ff4b4b;color:#ffbbbb;padding:5px;font-size:10px;border-radius:4px;margin-bottom:8px;">⚠️ Capped at 3,000 flights for performance (actual: {total_sim_flights:,})</div>'

            drone_svg = "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'%3E%3Cpath d='M18 6a2 2 0 100-4 2 2 0 000 4zm-12 0a2 2 0 100-4 2 2 0 000 4zm12 12a2 2 0 100-4 2 2 0 000 4zm-12 0a2 2 0 100-4 2 2 0 000 4z'/%3E%3Cpath stroke='white' stroke-width='2' stroke-linecap='round' d='M8.5 8.5l7 7m0-7l-7 7'/%3E%3Ccircle cx='12' cy='12' r='2' fill='white'/%3E%3C/svg%3E"

            sim_html = f"""<!DOCTYPE html><html><head>
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

            components.html(sim_html, height=700)
