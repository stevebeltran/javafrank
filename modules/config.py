"""
Global configuration, constants, and theme variables for BRINC Drone-First Response optimizer.
"""

import random

# --- BUILD & VERSION STRINGS ---
DAILY_OPERATION_MINUTES = 24 * 60

SIMULATOR_DISCLAIMER_SHORT = (
    "Simulation output only. Coverage, station placement, response time, and ROI figures are model estimates based on uploaded data and configuration settings. "
    "They are not guarantees of real-world performance, legal compliance, FAA approval, procurement outcome, or financial results."
)

# --- GLOBAL CONFIGURATION ---
CONFIG = {
    "RESPONDER_COST": 80000, "GUARDIAN_COST": 160000, "RESPONDER_RANGE_MI": 2.0,
    "OFFICER_COST_PER_CALL": 82, "DRONE_COST_PER_CALL": 6,
    # Specialty-response upside (conservative defaults; see helper below)
    "THERMAL_DEFAULT_APPLICABLE_RATE": 0.12,
    "THERMAL_SAVINGS_PER_CALL": 38,
    "K9_DEFAULT_APPLICABLE_RATE": 0.03,
    "K9_SAVINGS_PER_CALL": 155,
    # Fire department value: aerial recon/scene size-up + overhaul hotspot detection
    # ~5% of addressable calls are fire-related; blended savings $450/call assisted
    # (15% aerial ladder avoidance at $4,500/deploy + $90 overhaul crew time saved)
    "FIRE_DEFAULT_APPLICABLE_RATE": 0.05,
    "FIRE_SAVINGS_PER_CALL": 450,
    "DEFAULT_TRAFFIC_SPEED": 35.0, "RESPONDER_SPEED": 30.0, "GUARDIAN_SPEED": 60.0,
    # Guardian duty cycle: 60 min flight + 3 min charge = 63 min cycle
    # Daily airtime = (24*60) / 63 * 60 = 1371.4 min = 22.86 hrs
    "GUARDIAN_FLIGHT_MIN":  60,   # flight minutes per cycle
    "GUARDIAN_CHARGE_MIN":   3,   # charge minutes per cycle
    # Responder duty cycle: 30 min flight + 30 min recharge = 60 min cycle
    "RESPONDER_FLIGHT_MIN":   30,    # max flight minutes per sortie
    "RESPONDER_CHARGE_MIN":   30,    # recharge minutes per cycle
    "RESPONDER_PATROL_HOURS": 12.0,
    # Officer / drone cost model
    "OFFICER_HOURLY_WAGE": 37.0,     # baseline hourly wage for overtime estimates
    # Outcome rates (modeled estimates; adjust per-agency as needed)
    "OUTCOME_ARREST_RATE":      0.043,
    "OUTCOME_RESCUE_RATE":      0.021,
    "OUTCOME_DEESCALATION_RATE":0.11,
    "OUTCOME_MISSING_RATE":     0.008,
    # drone_wins_pct formula: pct = clamp(calls_covered * WINS_MULTIPLIER, WINS_FLOOR, 99)
    "DRONE_WINS_MULTIPLIER":    0.72,
    "DRONE_WINS_FLOOR":         60,
}

# Derived: compute daily airtime from duty cycle
CONFIG["GUARDIAN_DAILY_FLIGHT_MIN"] = (
    DAILY_OPERATION_MINUTES / (CONFIG["GUARDIAN_FLIGHT_MIN"] + CONFIG["GUARDIAN_CHARGE_MIN"])
) * CONFIG["GUARDIAN_FLIGHT_MIN"]
CONFIG["GUARDIAN_PATROL_HOURS"] = CONFIG["GUARDIAN_DAILY_FLIGHT_MIN"] / 60
CONFIG["RESPONDER_DAILY_FLIGHT_MIN"] = (
    DAILY_OPERATION_MINUTES / (CONFIG["RESPONDER_FLIGHT_MIN"] + CONFIG["RESPONDER_CHARGE_MIN"])
) * CONFIG["RESPONDER_FLIGHT_MIN"]
CONFIG["RESPONDER_PATROL_HOURS"] = CONFIG["RESPONDER_DAILY_FLIGHT_MIN"] / 60
GUARDIAN_FLIGHT_HOURS_PER_DAY = CONFIG["GUARDIAN_PATROL_HOURS"]


def calculate_max_flights_per_day(
    mission_minutes: float,
    *,
    flight_minutes: float,
    downtime_minutes: float,
    operation_minutes: float = DAILY_OPERATION_MINUTES,
) -> float:
    """Return max flights/day for a repeated mission profile under a duty cycle."""
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

# --- GEOGRAPHIC LOOKUPS ---
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
    "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20",
    "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36",
    "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
    "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56"
}

US_STATES_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"
}

KNOWN_POPULATIONS = {
    "Victoria": 65534, "New York": 8336817, "Los Angeles": 3822238, "Chicago": 2665039,
    "Houston": 1304379, "Phoenix": 1644409, "Philadelphia": 1567258, "San Antonio": 2302878,
    "San Diego": 1472530, "Dallas": 1299544, "San Jose": 1381162, "Austin": 974447,
    "Jacksonville": 971319, "Fort Worth": 956709, "Columbus": 907971, "Indianapolis": 880621,
    "Charlotte": 897720, "San Francisco": 971233, "Seattle": 749256, "Denver": 713252,
    "Washington": 678972, "Nashville": 683622, "Oklahoma City": 694800, "El Paso": 694553,
    "Boston": 650706, "Portland": 635067, "Las Vegas": 656274, "Detroit": 620376,
    "Memphis": 633104, "Louisville": 628594, "Baltimore": 620961, "Milwaukee": 620251,
    "Albuquerque": 677122, "Tucson": 564559, "Fresno": 677102, "Sacramento": 808418,
    "Kansas City": 697738, "Mesa": 504258, "Atlanta": 499127, "Omaha": 508901,
    "Colorado Springs": 483956, "Raleigh": 476587, "Miami": 449514, "Virginia Beach": 455369,
    "Oakland": 530763, "Minneapolis": 563332, "Tulsa": 547239, "Arlington": 398654,
    "New Orleans": 562503, "Wichita": 402263, "Cleveland": 900000, "Tampa": 449514,
    "Orlando": 316081, "Fayetteville": 208501, "Shreveport": 175698, "Montgomery": 198218,
    "Des Moines": 212031, "Modesto": 218464, "Baton Rouge": 225374, "Spokane": 228989,
    "Tacoma": 219346, "Aurora": 386261, "Anaheim": 346824, "Bakersfield": 380874,
    "Riverside": 319504, "Stockton": 322164, "Corpus Christi": 317863, "Lexington": 322570,
    "Henderson": 320189, "Saint Paul": 307695, "Anchorage": 291538, "Plano": 285494,
    "Lincoln": 289102, "Buffalo": 278349, "Fort Wayne": 270402, "Jersey City": 292449,
    "Chula Vista": 274492, "Chandler": 261165, "Laredo": 255473, "Madison": 269840,
    "Lubbock": 258862, "Gilbert": 267918, "Garland": 240280, "Glendale": 246709,
    "Hialeah": 223109, "Reno": 264165, "Boise": 235984, "Richmond": 226610,
    "Spokane Valley": 102976, "Fremont": 230504, "Irvine": 307670, "San Bernardino": 222101,
    "Birmingham": 212237, "Rochester": 211328, "Chesapeake": 244835, "Norfolk": 238005,
    "Scottsdale": 258069, "North Las Vegas": 262527, "Winston-Salem": 249545,
    "Greensboro": 301085, "Durham": 283506, "St. Petersburg": 261256, "Laredo": 255473,
    "Paradise": 193661, "Peoria": 190435, "Tempe": 192364
}

DEMO_CITIES = [
    ("Las Vegas", "NV"), ("Austin", "TX"), ("Seattle", "WA"), ("Denver", "CO"), ("Nashville", "TN"),
    ("Columbus", "OH"), ("Detroit", "MI"), ("San Diego", "CA"), ("Charlotte", "NC"), ("Portland", "OR"),
    ("Memphis", "TN"), ("Louisville", "KY"), ("Baltimore", "MD"), ("Milwaukee", "WI"), ("Albuquerque", "NM"),
    ("Tucson", "AZ"), ("Fresno", "CA"), ("Sacramento", "CA"), ("Kansas City", "MO"), ("Mesa", "AZ"),
    ("Atlanta", "GA"), ("Omaha", "NE"), ("Colorado Springs", "CO"), ("Raleigh", "NC"), ("Miami", "FL"),
    ("Minneapolis", "MN"), ("Tulsa", "OK"), ("Arlington", "TX"), ("Tampa", "FL"), ("New Orleans", "LA"),
    ("Wichita", "KS"), ("Cleveland", "OH"), ("Virginia Beach", "VA"), ("Oakland", "CA"), ("Indianapolis", "IN"),
    ("Jacksonville", "FL"), ("Fort Worth", "TX"), ("Boston", "MA"), ("El Paso", "TX"), ("Oklahoma City", "OK"),
    ("Boise", "ID"), ("Richmond", "VA"), ("Spokane", "WA"), ("Tacoma", "WA"), ("Aurora", "CO"),
    ("Anaheim", "CA"), ("Bakersfield", "CA"), ("Riverside", "CA"), ("Stockton", "CA"), ("Corpus Christi", "TX"),
    ("Lexington", "KY"), ("Henderson", "NV"), ("Saint Paul", "MN"), ("Anchorage", "AK"), ("Plano", "TX"),
    ("Lincoln", "NE"), ("Buffalo", "NY"), ("Fort Wayne", "IN"), ("Jersey City", "NJ"), ("Chula Vista", "CA"),
    ("Orlando", "FL"), ("St. Louis", "MO"), ("Madison", "WI"), ("Durham", "NC"), ("Lubbock", "TX"),
    ("Winston-Salem", "NC"), ("Garland", "TX"), ("Glendale", "AZ"), ("Hialeah", "FL"), ("Scottsdale", "AZ"),
    ("Irving", "TX"), ("Fremont", "CA"), ("Baton Rouge", "LA"), ("Birmingham", "AL"), ("Rochester", "NY"),
    ("Des Moines", "IA"), ("Montgomery", "AL"), ("Modesto", "CA"), ("Fayetteville", "NC"), ("Shreveport", "LA"),
    ("Akron", "OH"), ("Grand Rapids", "MI"), ("Huntington Beach", "CA"), ("Little Rock", "AR")
]

FAST_DEMO_CITIES = [
    ("Henderson", "NV"), ("Lincoln", "NE"), ("Boise", "ID"), ("Des Moines", "IA"), ("Madison", "WI"),
    ("Colorado Springs", "CO"), ("Richmond", "VA"), ("Raleigh", "NC"), ("Durham", "NC"), ("Fort Wayne", "IN"),
    ("Omaha", "NE"), ("Wichita", "KS"), ("Tulsa", "OK"), ("Spokane", "WA"), ("Tacoma", "WA"),
    ("Aurora", "CO"), ("Las Vegas", "NV"), ("Nashville", "TN"), ("Columbus", "OH"), ("Charlotte", "NC"),
    ("Louisville", "KY"), ("Indianapolis", "IN"), ("Memphis", "TN"), ("Detroit", "MI"), ("Milwaukee", "WI"),
    ("Minneapolis", "MN"), ("Seattle", "WA"), ("Denver", "CO"), ("Portland", "OR"), ("Austin", "TX")
]

# --- FAA & AIRSPACE ---
FAA_CEILING_COLORS = {
    0: {"line": "rgba(255,  20,  20, 0.95)", "fill": "rgba(255,  20,  20, 0.20)"},
    50: {"line": "rgba(255, 120,   0, 0.95)", "fill": "rgba(255, 120,   0, 0.18)"},
    100: {"line": "rgba(255, 210,   0, 0.95)", "fill": "rgba(255, 210,   0, 0.18)"},
    200: {"line": "rgba(180, 230,   0, 0.95)", "fill": "rgba(180, 230,   0, 0.16)"},
    300: {"line": "rgba( 80, 200,  50, 0.95)", "fill": "rgba( 80, 200,  50, 0.16)"},
    400: {"line": "rgba(  0, 180, 100, 0.95)", "fill": "rgba(  0, 180, 100, 0.15)"}
}

FAA_DEFAULT_COLOR = {"line": "rgba(150,150,150,0.8)", "fill": "rgba(150,150,150,0.10)"}

STATION_COLORS = [
    "#00D2FF", "#39FF14", "#FFD700", "#FF007F", "#FF4500",
    "#00FFCC", "#FF3333", "#7FFF00", "#00FFFF", "#FF9900"
]

# --- THEME VARIABLES (Dark Theme) ---
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

# --- LOADING MESSAGE LISTS ---
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

# --- MESSAGE GETTERS ---
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


# --- CRASH SIMULATOR CONFIGURATION ---
# AVSS Parachute Recovery System (PRS) specs for BRINC drones
AVSS_PRS_WEIGHT_G = 200
AVSS_CMFA_FT = 116.8  # Certified Minimum Flight Altitude (35.6 m) — must be above for full deploy
AVSS_MIN_DEPLOY_FT = 32.8  # 10m — absolute floor for any deployment
AVSS_MAX_IMPACT_ENERGY_FTLBS = 25.0  # Category 3 limit (33.9 joules)

# Drone weights (estimated)
DRONE_WEIGHTS = {
    "RESPONDER": 13.0,  # lbs
    "GUARDIAN": 18.0,   # lbs
}

# NTSB reporting threshold (unmanned aircraft > 55 lbs)
NTSB_REPORT_WEIGHT_LBS = 55.0

# Customer Success Manager territory mapping (by state abbreviation)
CSM_TERRITORY = {
    # East: Heath Beaudoin
    "CT": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "DE": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "FL": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "GA": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "IL": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "IN": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "KY": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "ME": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "MD": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "MA": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "MI": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "MS": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "NH": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "NJ": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "NY": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "NC": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "OH": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "PA": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "RI": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "SC": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "TN": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "VT": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "VA": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "WV": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    "WI": {"name": "Heath Beaudoin", "email": "heath.beaudoin@brincdrones.com", "region": "East"},
    # West: Peter Ferranti
    "AL": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "AK": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "AZ": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "AR": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "CA": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "CO": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "HI": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "ID": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "IA": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "KS": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "LA": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "MN": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "MO": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "MT": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "NE": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "NV": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "NM": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "ND": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "OK": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "OR": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "SD": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "TX": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "UT": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "WA": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
    "WY": {"name": "Peter Ferranti", "email": "peter.ferranti@brincdrones.com", "region": "West"},
}

def get_csm_for_state(state_abbr: str) -> dict:
    """Get CSM info for a given state abbreviation."""
    return CSM_TERRITORY.get(state_abbr.upper(), {
        "name": "BRINC Customer Success",
        "email": "cs@brincdrones.com",
        "region": "N/A"
    })

# BRINC Customer Support info
BRINC_SUPPORT_HOTLINE = "(866) 849-0282"
BRINC_SUPPORT_MENU = "Press '2' for support"
BRINC_SUPPORT_EMERGENCY = "Press '0' for active-operation emergency"
BRINC_SUPPORT_PORTAL = "https://liveops.brincdrones.com"
BRINC_SUPPORT_EMAIL = "cs@brincdrones.com"

# Crash simulator scenario types
CRASH_SCENARIOS = {
    "bird_strike": {
        "name": "Bird Strike",
        "description": "High-speed collision with bird during flight",
        "icon": "🐦",
    },
    "motor_failure": {
        "name": "Motor Failure",
        "description": "One or more ESC/motor failure — loss of thrust",
        "icon": "⚙️",
    },
    "battery_failure": {
        "name": "Battery Failure",
        "description": "Sudden loss of battery power or voltage collapse",
        "icon": "🔋",
    },
    "operator_error": {
        "name": "Operator Error",
        "description": "Erratic control inputs leading to loss of control",
        "icon": "👤",
    },
    "parachute_failure": {
        "name": "Parachute Failure",
        "description": "AVSS PRS deployment failure or malfunction",
        "icon": "🪂",
    },
    "weather_event": {
        "name": "Weather Event",
        "description": "High wind, turbulence, or environmental event",
        "icon": "⛈️",
    },
    "signal_loss": {
        "name": "Signal Loss",
        "description": "Loss of control link or GPS signal",
        "icon": "📡",
    },
}
