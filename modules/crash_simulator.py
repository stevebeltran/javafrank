"""
Drone Crash/Incident Simulator — comprehensive scenario modeling with AVSS PRS physics.

Provides:
- Realistic crash scenarios (bird strike, motor failure, battery failure, operator error, etc.)
- AVSS parachute recovery system (PRS) physics and deployment modeling
- FAA reporting requirement calculations (14 CFR § 107.9)
- Telemetry analysis framework for malfunction vs. operator error discrimination
- Customer-facing reports with compliance checklist and next-steps guidance
"""

import streamlit as st
import json
import math
import random
import uuid
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from modules.config import (
    AVSS_CMFA_FT, AVSS_MIN_DEPLOY_FT, AVSS_MAX_IMPACT_ENERGY_FTLBS,
    DRONE_WEIGHTS, NTSB_REPORT_WEIGHT_LBS, CSM_TERRITORY, get_csm_for_state,
    BRINC_SUPPORT_HOTLINE, BRINC_SUPPORT_MENU, BRINC_SUPPORT_EMERGENCY,
    BRINC_SUPPORT_PORTAL, BRINC_SUPPORT_EMAIL, CRASH_SCENARIOS
)
from modules.data_models import CrashEvent, FlightTelemetrySnapshot


# ─── PHYSICS MODELS ───────────────────────────────────────────────────────

def compute_impact_energy(drone_weight_lbs: float, impact_velocity_mph: float) -> float:
    """
    Compute kinetic energy at impact.
    KE = 0.5 * m * v^2, converted to ft-lbs
    """
    v_fps = impact_velocity_mph * 1.467  # mph → ft/s
    ke_ftlbs = 0.5 * (drone_weight_lbs / 32.174) * v_fps ** 2
    return ke_ftlbs


def compute_parachute_descent_velocity(
    drone_weight_lbs: float,
    parachute_cd: float = 1.5,
    canopy_area_sqft: float = 4.0
) -> float:
    """
    Compute terminal velocity under parachute (no forward motion).
    v = sqrt((2 * m * g) / (Cd * rho * A))
    Returns velocity in mph.
    """
    g_fts2 = 32.174
    rho_slugs = 0.002377  # air density at sea level (slugs/ft³)
    m_slugs = drone_weight_lbs / 32.174  # mass in slugs

    v_fts = math.sqrt((2 * m_slugs * g_fts2) / (parachute_cd * rho_slugs * canopy_area_sqft))
    return v_fts * 0.6818  # ft/s → mph


def compute_parachute_drift(
    altitude_ft: float,
    wind_speed_mph: float,
    descent_velocity_mph: float
) -> float:
    """
    Compute horizontal drift distance during parachute descent.
    Returns drift in feet.
    """
    descent_time_sec = (altitude_ft / (descent_velocity_mph * 1.467))  # mph → ft/s
    drift_ft = descent_time_sec * (wind_speed_mph * 1.467)
    return drift_ft


def parachute_outcome(
    altitude_ft: float,
    armed: bool,
    deployed: bool
) -> Tuple[str, bool, float]:
    """
    Determine parachute deployment outcome given altitude and state.
    Returns (outcome_str, success_bool, impact_velocity_mph)
    """
    if not armed:
        return ("Not Armed", False, 45.0)  # Uncontrolled freefall
    if not deployed:
        return ("Deployment Failed", False, 45.0)
    if altitude_ft >= AVSS_CMFA_FT:
        return ("Full Deploy — Safe", True, 12.0)  # ~12 mph at descent with chute
    elif altitude_ft >= AVSS_MIN_DEPLOY_FT:
        return ("Partial Deploy — Reduced Impact", True, 18.0)  # Partial inflation
    else:
        return ("Below Deploy Floor — Hard Landing", False, 35.0)  # Too low to deploy


def compute_debris_radius(
    impact_velocity_mph: float,
    drone_weight_lbs: float,
    wind_speed_mph: float
) -> float:
    """
    Estimate debris scatter radius in feet based on impact energy and wind.
    Higher velocity and weight = larger debris field.
    """
    impact_energy = compute_impact_energy(drone_weight_lbs, impact_velocity_mph)
    # Energy-based scatter: ~1 ft per ft-lb of impact energy (conservative)
    base_radius = math.sqrt(impact_energy) * 2
    # Wind adds to drift
    wind_effect = wind_speed_mph * 5
    return min(base_radius + wind_effect, 200.0)  # Cap at 200 ft


# ─── SCENARIO GENERATORS ───────────────────────────────────────────────────

def simulate_bird_strike(
    lat: float,
    lon: float,
    drone_model: str,
    altitude_ft: float,
    wind_speed_mph: float = 8.0
) -> Tuple[CrashEvent, FlightTelemetrySnapshot]:
    """Generate realistic bird strike telemetry."""
    event_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow()
    drone_weight = DRONE_WEIGHTS[drone_model]

    # Bird strikes: sudden impact + asymmetric motor failure
    impact_g = random.uniform(8, 20)
    motor_variance = random.uniform(40, 90)  # High asymmetry

    parachute_armed = altitude_ft >= AVSS_MIN_DEPLOY_FT
    parachute_deploy_time = 150 if parachute_armed else 999

    outcome_str, parachute_success, impact_vel = parachute_outcome(
        altitude_ft, parachute_armed, parachute_armed
    )

    # Injury probability (bird strike hits operating drone — usually no injury to public)
    injuries = 0
    injury_severity = "none"
    property_damage = random.uniform(500, 8000)  # Drone loss + possible property

    impact_energy = compute_impact_energy(drone_weight, impact_vel)
    faa_report_required = property_damage > 500 or injuries >= 1
    ntsb_report_required = drone_weight > NTSB_REPORT_WEIGHT_LBS

    debris_radius = compute_debris_radius(impact_vel, drone_weight, wind_speed_mph)

    telemetry = FlightTelemetrySnapshot(
        pre_battery_pct=random.uniform(50, 95),
        pre_gps_sats=random.randint(8, 14),
        pre_wind_speed_mph=wind_speed_mph,
        pre_motor_rpm_variance_pct=5.0,  # Smooth before event
        impact_g_force=impact_g,
        altitude_loss_rate_fts=altitude_ft / 3.0,  # 3 seconds to ground
        control_link_active=True,
        parachute_armed=parachute_armed,
        parachute_deploy_time_ms=parachute_deploy_time,
        final_altitude_ft=0.0,
        impact_velocity_mph=impact_vel,
        landing_zone_impact_radius_ft=debris_radius,
    )

    crash_event = CrashEvent(
        event_id=event_id,
        event_type="bird_strike",
        drone_model=drone_model,
        lat=lat,
        lon=lon,
        altitude_ft=altitude_ft,
        airspeed_mph=random.uniform(25, 45),
        timestamp=timestamp,
        parachute_deployed=parachute_armed,
        parachute_success=parachute_success,
        landing_zone_type=random.choice(["open", "road"]),
        property_damage_usd=property_damage,
        injuries=injuries,
        injury_severity=injury_severity,
        faa_report_required=faa_report_required,
        ntsb_report_required=ntsb_report_required,
        cause_classification="environmental",
        telemetry=telemetry,
    )

    return crash_event, telemetry


def simulate_motor_failure(
    lat: float,
    lon: float,
    drone_model: str,
    altitude_ft: float,
    wind_speed_mph: float = 8.0
) -> Tuple[CrashEvent, FlightTelemetrySnapshot]:
    """Generate motor failure scenario."""
    event_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow()
    drone_weight = DRONE_WEIGHTS[drone_model]

    # Motor failure: asymmetric power loss + slow spiral descent
    motor_variance = random.uniform(70, 100)  # Very asymmetric
    impact_g = random.uniform(2, 6)

    parachute_armed = altitude_ft >= AVSS_MIN_DEPLOY_FT
    parachute_deploy_time = 200 if parachute_armed else 999

    outcome_str, parachute_success, impact_vel = parachute_outcome(
        altitude_ft, parachute_armed, parachute_armed
    )

    injuries = 0
    injury_severity = "none"
    property_damage = random.uniform(8000, 160000)  # Total loss

    debris_radius = compute_debris_radius(impact_vel, drone_weight, wind_speed_mph)

    telemetry = FlightTelemetrySnapshot(
        pre_battery_pct=random.uniform(60, 98),
        pre_gps_sats=random.randint(7, 14),
        pre_wind_speed_mph=wind_speed_mph,
        pre_motor_rpm_variance_pct=3.0,
        impact_g_force=impact_g,
        altitude_loss_rate_fts=altitude_ft / 8.0,
        control_link_active=True,
        parachute_armed=parachute_armed,
        parachute_deploy_time_ms=parachute_deploy_time,
        final_altitude_ft=0.0,
        impact_velocity_mph=impact_vel,
        landing_zone_impact_radius_ft=debris_radius,
    )

    crash_event = CrashEvent(
        event_id=event_id,
        event_type="motor_failure",
        drone_model=drone_model,
        lat=lat,
        lon=lon,
        altitude_ft=altitude_ft,
        airspeed_mph=random.uniform(10, 30),
        timestamp=timestamp,
        parachute_deployed=parachute_armed,
        parachute_success=parachute_success,
        landing_zone_type=random.choice(["open", "residential", "commercial"]),
        property_damage_usd=property_damage,
        injuries=injuries,
        injury_severity=injury_severity,
        faa_report_required=property_damage > 500,
        ntsb_report_required=drone_weight > NTSB_REPORT_WEIGHT_LBS,
        cause_classification="malfunction",
        telemetry=telemetry,
    )

    return crash_event, telemetry


def simulate_battery_failure(
    lat: float,
    lon: float,
    drone_model: str,
    altitude_ft: float,
    wind_speed_mph: float = 8.0
) -> Tuple[CrashEvent, FlightTelemetrySnapshot]:
    """Generate battery failure scenario — sudden power loss."""
    event_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow()
    drone_weight = DRONE_WEIGHTS[drone_model]

    motor_variance = random.uniform(60, 95)  # All motors fail simultaneously
    impact_g = random.uniform(1, 4)

    parachute_armed = altitude_ft >= AVSS_MIN_DEPLOY_FT
    parachute_deploy_time = 180 if parachute_armed else 999

    outcome_str, parachute_success, impact_vel = parachute_outcome(
        altitude_ft, parachute_armed, parachute_armed
    )

    injuries = 0
    injury_severity = "none"
    property_damage = random.uniform(8000, 160000)

    debris_radius = compute_debris_radius(impact_vel, drone_weight, wind_speed_mph)

    telemetry = FlightTelemetrySnapshot(
        pre_battery_pct=random.uniform(40, 80),  # Battery was degraded
        pre_gps_sats=random.randint(7, 14),
        pre_wind_speed_mph=wind_speed_mph,
        pre_motor_rpm_variance_pct=2.0,
        impact_g_force=impact_g,
        altitude_loss_rate_fts=altitude_ft / 5.0,  # Free fall
        control_link_active=True,
        parachute_armed=parachute_armed,
        parachute_deploy_time_ms=parachute_deploy_time,
        final_altitude_ft=0.0,
        impact_velocity_mph=impact_vel,
        landing_zone_impact_radius_ft=debris_radius,
    )

    crash_event = CrashEvent(
        event_id=event_id,
        event_type="battery_failure",
        drone_model=drone_model,
        lat=lat,
        lon=lon,
        altitude_ft=altitude_ft,
        airspeed_mph=0.0,  # No power
        timestamp=timestamp,
        parachute_deployed=parachute_armed,
        parachute_success=parachute_success,
        landing_zone_type=random.choice(["open", "water"]),
        property_damage_usd=property_damage,
        injuries=injuries,
        injury_severity=injury_severity,
        faa_report_required=property_damage > 500,
        ntsb_report_required=drone_weight > NTSB_REPORT_WEIGHT_LBS,
        cause_classification="malfunction",
        telemetry=telemetry,
    )

    return crash_event, telemetry


def simulate_operator_error(
    lat: float,
    lon: float,
    drone_model: str,
    altitude_ft: float,
    wind_speed_mph: float = 8.0
) -> Tuple[CrashEvent, FlightTelemetrySnapshot]:
    """Generate operator error scenario — erratic control inputs."""
    event_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow()
    drone_weight = DRONE_WEIGHTS[drone_model]

    motor_variance = random.uniform(20, 50)  # Responds to pilot input
    impact_g = random.uniform(3, 12)

    # Operator may have panicked — parachute not armed or control link lost
    parachute_armed = random.choice([False, False, True])  # 2/3 chance not armed
    parachute_deploy_time = 999

    outcome_str, parachute_success, impact_vel = parachute_outcome(
        altitude_ft, parachute_armed, False  # Operator error: didn't deploy
    )

    injuries = 0
    injury_severity = "none"
    property_damage = random.uniform(8000, 80000)

    debris_radius = compute_debris_radius(impact_vel, drone_weight, wind_speed_mph)

    telemetry = FlightTelemetrySnapshot(
        pre_battery_pct=random.uniform(50, 95),
        pre_gps_sats=random.randint(6, 14),
        pre_wind_speed_mph=wind_speed_mph,
        pre_motor_rpm_variance_pct=15.0,  # Erratic
        impact_g_force=impact_g,
        altitude_loss_rate_fts=altitude_ft / 4.0,
        control_link_active=random.choice([False, False, True]),  # 2/3 chance lost
        parachute_armed=parachute_armed,
        parachute_deploy_time_ms=parachute_deploy_time,
        final_altitude_ft=0.0,
        impact_velocity_mph=impact_vel,
        landing_zone_impact_radius_ft=debris_radius,
    )

    crash_event = CrashEvent(
        event_id=event_id,
        event_type="operator_error",
        drone_model=drone_model,
        lat=lat,
        lon=lon,
        altitude_ft=altitude_ft,
        airspeed_mph=random.uniform(5, 35),
        timestamp=timestamp,
        parachute_deployed=parachute_armed,
        parachute_success=parachute_success,
        landing_zone_type=random.choice(["residential", "commercial", "road"]),
        property_damage_usd=property_damage,
        injuries=0,
        injury_severity="none",
        faa_report_required=property_damage > 500,
        ntsb_report_required=drone_weight > NTSB_REPORT_WEIGHT_LBS,
        cause_classification="operator_error",
        telemetry=telemetry,
    )

    return crash_event, telemetry


def simulate_weather_event(
    lat: float,
    lon: float,
    drone_model: str,
    altitude_ft: float,
    wind_speed_mph: float = 25.0  # High wind
) -> Tuple[CrashEvent, FlightTelemetrySnapshot]:
    """Generate weather event scenario."""
    event_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow()
    drone_weight = DRONE_WEIGHTS[drone_model]

    motor_variance = random.uniform(30, 70)  # Wind-induced
    impact_g = random.uniform(2, 8)

    parachute_armed = altitude_ft >= AVSS_MIN_DEPLOY_FT
    parachute_deploy_time = 160 if parachute_armed else 999

    outcome_str, parachute_success, impact_vel = parachute_outcome(
        altitude_ft, parachute_armed, parachute_armed
    )

    injuries = 0
    injury_severity = "none"
    property_damage = random.uniform(3000, 80000)

    debris_radius = compute_debris_radius(impact_vel, drone_weight, wind_speed_mph)

    telemetry = FlightTelemetrySnapshot(
        pre_battery_pct=random.uniform(50, 95),
        pre_gps_sats=random.randint(5, 12),  # Wind affects GPS
        pre_wind_speed_mph=wind_speed_mph,
        pre_motor_rpm_variance_pct=25.0,  # Wind-induced variance
        impact_g_force=impact_g,
        altitude_loss_rate_fts=altitude_ft / 6.0,
        control_link_active=True,
        parachute_armed=parachute_armed,
        parachute_deploy_time_ms=parachute_deploy_time,
        final_altitude_ft=0.0,
        impact_velocity_mph=impact_vel,
        landing_zone_impact_radius_ft=debris_radius,
    )

    crash_event = CrashEvent(
        event_id=event_id,
        event_type="weather_event",
        drone_model=drone_model,
        lat=lat,
        lon=lon,
        altitude_ft=altitude_ft,
        airspeed_mph=random.uniform(15, 40),
        timestamp=timestamp,
        parachute_deployed=parachute_armed,
        parachute_success=parachute_success,
        landing_zone_type=random.choice(["open", "water"]),
        property_damage_usd=property_damage,
        injuries=0,
        injury_severity="none",
        faa_report_required=property_damage > 500,
        ntsb_report_required=drone_weight > NTSB_REPORT_WEIGHT_LBS,
        cause_classification="environmental",
        telemetry=telemetry,
    )

    return crash_event, telemetry


# ─── MAIN UI RENDER ───────────────────────────────────────────────────────

def render_crash_simulator(
    city: str,
    state: str,
    center_lat: float,
    center_lon: float,
    active_drones: List[Dict],
    text_main: str,
    text_muted: str,
    accent_color: str,
    card_bg: str,
):
    """
    Main crash simulator UI — render scenario selector, simulation map,
    and 4-panel report (customer report, FAA checklist, telemetry, parachute).
    """
    st.markdown("---")

    # ─ Controls ─
    col1, col2, col3 = st.columns([1, 1, 0.5])
    with col1:
        scenario_key = st.selectbox(
            "Scenario",
            list(CRASH_SCENARIOS.keys()),
            format_func=lambda k: f"{CRASH_SCENARIOS[k]['icon']} {CRASH_SCENARIOS[k]['name']}",
            key="crash_scenario_type"
        )
    with col2:
        drone_model = st.selectbox(
            "Drone Model",
            ["RESPONDER", "GUARDIAN"],
            key="crash_drone_model"
        )
    with col3:
        wind_mph = st.number_input(
            "Wind (mph)",
            min_value=0, max_value=50, value=8,
            key="crash_wind_speed"
        )

    col4, col5 = st.columns([1, 1])
    with col4:
        altitude_ft = st.number_input(
            "Altitude (ft AGL)",
            min_value=30, max_value=400, value=150,
            key="crash_altitude"
        )
    with col5:
        if st.button("🎬 SIMULATE CRASH", use_container_width=True):
            st.session_state['crash_sim_run'] = True

    # ─ Run simulation if requested ─
    if st.session_state.get('crash_sim_run', False):
        # Pick random point near city center
        crash_lat = center_lat + random.uniform(-0.05, 0.05)
        crash_lon = center_lon + random.uniform(-0.05, 0.05)

        # Generate scenario
        scenario_generators = {
            "bird_strike": simulate_bird_strike,
            "motor_failure": simulate_motor_failure,
            "battery_failure": simulate_battery_failure,
            "operator_error": simulate_operator_error,
            "weather_event": simulate_weather_event,
            "parachute_failure": simulate_bird_strike,  # Use bird strike as template
            "signal_loss": simulate_motor_failure,  # Use motor failure as template
        }

        generator = scenario_generators.get(scenario_key, simulate_bird_strike)
        crash_event, telemetry = generator(
            lat=crash_lat,
            lon=crash_lon,
            drone_model=drone_model,
            altitude_ft=altitude_ft,
            wind_speed_mph=wind_mph
        )

        # Store in session state
        st.session_state['last_crash_event'] = crash_event
        st.session_state['last_crash_telemetry'] = telemetry

        st.success(f"✓ Simulation complete: Event ID `{crash_event.event_id}`")

    # ─ Display results if available ─
    if st.session_state.get('last_crash_event'):
        crash_event = st.session_state['last_crash_event']
        telemetry = st.session_state['last_crash_telemetry']

        # 4-panel report
        tab1, tab2, tab3, tab4 = st.tabs([
            "📋 Customer Report",
            "📋 FAA Compliance",
            "🔍 Telemetry Analysis",
            "🪂 Parachute Performance"
        ])

        csm = get_csm_for_state(state)

        with tab1:
            render_customer_report(crash_event, csm, city, state)

        with tab2:
            render_faa_compliance(crash_event)

        with tab3:
            render_telemetry_analysis(crash_event, telemetry)

        with tab4:
            render_parachute_performance(crash_event, telemetry)


def render_customer_report(
    crash_event: CrashEvent,
    csm: Dict,
    city: str,
    state: str
):
    """Customer report panel."""
    html = f"""
    <div style="font-size:0.9rem; color:#ccc;">

    <h4 style="color:#00ffcc;">Incident Summary</h4>
    <table style="width:100%; border-collapse:collapse;">
        <tr><td style="padding:5px;"><b>Incident ID:</b></td><td>{crash_event.event_id}</td></tr>
        <tr><td style="padding:5px;"><b>Date/Time (UTC):</b></td><td>{crash_event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
        <tr><td style="padding:5px;"><b>Drone Model:</b></td><td>{crash_event.drone_model}</td></tr>
        <tr><td style="padding:5px;"><b>Scenario:</b></td><td>{CRASH_SCENARIOS.get(crash_event.event_type, {}).get('name', crash_event.event_type)}</td></tr>
        <tr><td style="padding:5px;"><b>Location:</b></td><td>{city}, {state} ({crash_event.lat:.4f}, {crash_event.lon:.4f})</td></tr>
        <tr><td style="padding:5px;"><b>Altitude AGL:</b></td><td>{crash_event.altitude_ft:.0f} ft</td></tr>
    </table>

    <h4 style="color:#00ffcc; margin-top:15px;">Parachute Status</h4>
    <table style="width:100%; border-collapse:collapse;">
        <tr><td style="padding:5px;"><b>Parachute Deployed:</b></td><td>{"✓ Yes" if crash_event.parachute_deployed else "✗ No"}</td></tr>
        <tr><td style="padding:5px;"><b>Deployment Success:</b></td><td>{"✓ Yes" if crash_event.parachute_success else "✗ No"}</td></tr>
        <tr><td style="padding:5px;"><b>Impact Zone Type:</b></td><td>{crash_event.landing_zone_type.title()}</td></tr>
    </table>

    <h4 style="color:#00ffcc; margin-top:15px;">Impact Assessment</h4>
    <table style="width:100%; border-collapse:collapse;">
        <tr><td style="padding:5px;"><b>Property Damage:</b></td><td>${crash_event.property_damage_usd:,.0f}</td></tr>
        <tr><td style="padding:5px;"><b>Injuries:</b></td><td>{crash_event.injuries} (Severity: {crash_event.injury_severity.title()})</td></tr>
        <tr><td style="padding:5px;"><b>Drone Status:</b></td><td>{"Recoverable" if crash_event.property_damage_usd < 50000 else "Total Loss"}</td></tr>
    </table>

    <h4 style="color:#00ffcc; margin-top:15px;">Reporting Requirements</h4>
    <table style="width:100%; border-collapse:collapse;">
        <tr><td style="padding:5px;"><b>FAA Report Required:</b></td><td>{"⚠️ YES - within 10 days" if crash_event.faa_report_required else "✓ No"}</td></tr>
        <tr><td style="padding:5px;"><b>NTSB Report Required:</b></td><td>{"⚠️ YES" if crash_event.ntsb_report_required else "✓ No"}</td></tr>
    </table>

    <h4 style="color:#00ffcc; margin-top:15px;">Preliminary Cause</h4>
    <p><b>{crash_event.cause_classification.title()}</b></p>

    <h4 style="color:#00ffcc; margin-top:15px;">Next Steps</h4>
    <ol style="font-size:0.85rem;">
        <li><b>Immediate (0–2 hrs):</b> Secure crash site, preserve evidence, photograph debris field</li>
        <li><b>Within 24 hrs:</b> Notify {csm.get('name', 'BRINC Customer Success')} — {csm.get('email', 'cs@brincdrones.com')}</li>
        <li><b>Within 48 hrs:</b> Contact insurance carrier, notify legal team</li>
        <li><b>Within 10 days:</b> Submit FAA report (if required) via DrCASS</li>
        <li><b>Recovery:</b> Open support ticket at {BRINC_SUPPORT_PORTAL}</li>
    </ol>

    <h4 style="color:#00ffcc; margin-top:15px;">BRINC Support</h4>
    <p style="font-size:0.85rem;">
        <b>24/7 Hotline:</b> {BRINC_SUPPORT_HOTLINE} ({BRINC_SUPPORT_MENU})<br>
        <b>Emergency:</b> {BRINC_SUPPORT_EMERGENCY}<br>
        <b>Support Portal:</b> {BRINC_SUPPORT_PORTAL}<br>
        <b>Email:</b> {BRINC_SUPPORT_EMAIL}
    </p>

    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_faa_compliance(crash_event: CrashEvent):
    """FAA compliance checklist panel."""
    faa_html = f"""
    <div style="font-size:0.85rem; color:#ccc;">

    <h4 style="color:#ffaa00;">FAA 14 CFR § 107.9 Reporting Requirements</h4>

    <p><b>Reporting Threshold Check:</b></p>
    <ul>
        <li>Property Damage > $500: {"✓ YES" if crash_event.property_damage_usd > 500 else "✗ No"}</li>
        <li>Serious Injury (AIS ≥ Level 3): {"✓ YES" if crash_event.injury_severity == "serious" else "✗ No"}</li>
        <li>Loss of Consciousness: {"✓ YES" if crash_event.injuries > 0 else "✗ No"}</li>
    </ul>

    <p><b>Result:</b> {"⚠️ MANDATORY FAA REPORT REQUIRED" if crash_event.faa_report_required else "✓ No FAA report required"}</p>

    <h4 style="color:#ffaa00; margin-top:15px;">Action Checklist</h4>
    <ul style="list-style:none; padding:0;">
        <li>☐ <b>Preserve all flight data:</b> Onboard SD card, cloud telemetry, GCS logs</li>
        <li>☐ <b>Document the scene:</b> Photographs of debris, parachute condition, impact zone</li>
        <li>☐ <b>Secure the site:</b> Isolate crash area, preserve evidence for analysis</li>
        <li>☐ <b>Notify local ATC:</b> If event occurred in controlled airspace</li>
        <li>☐ <b>Contact your insurance:</b> File claim within 24–48 hours</li>
        <li>☐ <b>Gather documentation:</b> Remote pilot cert, LAANC authorization, weather data (METAR)</li>
        <li>☐ <b>Submit FAA DrCASS Report:</b> Within 10 calendar days (if required)</li>
        <li>☐ <b>NTSB Notification:</b> {"If aircraft weight > 55 lbs (separate process)" if crash_event.ntsb_report_required else "Not required for BRINC drones"}</li>
    </ul>

    <h4 style="color:#ffaa00; margin-top:15px;">FAA DrCASS Submission</h4>
    <p style="font-size:0.8rem;">
        <b>URL:</b> faa.gov/uas/resources<br>
        <b>Deadline:</b> {"" + crash_event.timestamp.strftime("%Y-%m-%d") if crash_event.faa_report_required else "N/A"}<br>
        <b>Requires:</b> Incident summary, flight logs, photos, preliminary cause assessment
    </p>

    </div>
    """
    st.markdown(faa_html, unsafe_allow_html=True)


def render_telemetry_analysis(
    crash_event: CrashEvent,
    telemetry: FlightTelemetrySnapshot
):
    """Telemetry analysis panel for malfunction vs. operator error."""

    # Evidence scoring
    evidence_scores = {
        "Motor RPM asymmetry": {
            "value": f"{telemetry.pre_motor_rpm_variance_pct:.1f}%",
            "weight": "HIGH",
            "indicator": "malfunction" if telemetry.pre_motor_rpm_variance_pct > 50 else "operator",
        },
        "IMU shock spike": {
            "value": f"{telemetry.impact_g_force:.1f}g",
            "weight": "HIGH",
            "indicator": "malfunction" if telemetry.impact_g_force > 10 else "operator",
        },
        "Control link": {
            "value": "Active" if telemetry.control_link_active else "Lost",
            "weight": "HIGH",
            "indicator": "operator" if not telemetry.control_link_active else "other",
        },
        "Parachute armed": {
            "value": "Yes" if crash_event.parachute_deployed else "No",
            "weight": "HIGH",
            "indicator": "operator" if not crash_event.parachute_deployed else "other",
        },
        "GPS satellites": {
            "value": f"{telemetry.pre_gps_sats} sats",
            "weight": "MEDIUM",
            "indicator": "environmental" if telemetry.pre_gps_sats < 6 else "other",
        },
        "Wind speed": {
            "value": f"{telemetry.pre_wind_speed_mph:.1f} mph",
            "weight": "MEDIUM",
            "indicator": "environmental" if telemetry.pre_wind_speed_mph > 20 else "other",
        },
    }

    # Compute verdict
    malfunction_points = sum(1 for v in evidence_scores.values() if v["indicator"] == "malfunction")
    operator_points = sum(1 for v in evidence_scores.values() if v["indicator"] == "operator")
    environmental_points = sum(1 for v in evidence_scores.values() if v["indicator"] == "environmental")

    total_points = malfunction_points + operator_points + environmental_points or 1
    malfunction_pct = (malfunction_points / total_points) * 100
    operator_pct = (operator_points / total_points) * 100
    environmental_pct = (environmental_points / total_points) * 100

    html = """<div style="font-size:0.85rem; color:#ccc;">
<h4 style="color:#00ff99;">Evidence Weight Board</h4>
<table style="width:100%; border-collapse:collapse; border:1px solid #333;">
<tr style="background:#222;">
<th style="padding:8px; border:1px solid #333; text-align:left;">Signal</th>
<th style="padding:8px; border:1px solid #333;">Value</th>
<th style="padding:8px; border:1px solid #333;">Weight</th>
</tr>"""

    for signal, data in evidence_scores.items():
        html += f"""<tr>
<td style="padding:8px; border:1px solid #333;">{signal}</td>
<td style="padding:8px; border:1px solid #333;">{data['value']}</td>
<td style="padding:8px; border:1px solid #333;"><span style="background:#aa3333; padding:2px 6px; border-radius:3px;">{data['weight']}</span></td>
</tr>"""

    html += """</table>"""

    # Verdict
    if malfunction_pct >= 60:
        verdict = f"Probable Malfunction ({malfunction_pct:.0f}% confidence)"
        verdict_color = "#ff4444"
    elif operator_pct >= 60:
        verdict = f"Probable Operator Error ({operator_pct:.0f}% confidence)"
        verdict_color = "#ffaa00"
    else:
        verdict = f"Environmental / Mixed Factors"
        verdict_color = "#0099ff"

    html += f"""<div style="margin-top:15px; padding:12px; background:#1a1a1a; border:2px solid {verdict_color}; border-radius:6px;">
<h4 style="color:{verdict_color}; margin:0 0 8px 0;">VERDICT</h4>
<p style="font-size:1.1rem; color:{verdict_color}; margin:0;">{verdict}</p>
<div style="margin-top:8px; height:20px; background:#333; border-radius:3px; overflow:hidden; display:flex;">
<div style="width:{malfunction_pct}%; background:#ff4444;"></div>
<div style="width:{operator_pct}%; background:#ffaa00;"></div>
<div style="width:{environmental_pct}%; background:#0099ff;"></div>
</div>
<div style="font-size:0.8rem; margin-top:6px;">
Malfunction: {malfunction_pct:.0f}% | Operator: {operator_pct:.0f}% | Environmental: {environmental_pct:.0f}%
</div>
</div>
</div>"""

    st.markdown(html, unsafe_allow_html=True)


def render_parachute_performance(
    crash_event: CrashEvent,
    telemetry: FlightTelemetrySnapshot
):
    """Parachute performance panel — AVSS PRS specific."""

    drone_weight = DRONE_WEIGHTS.get(crash_event.drone_model, 15.0)
    descent_vel = compute_parachute_descent_velocity(drone_weight)
    impact_energy = compute_impact_energy(drone_weight, telemetry.impact_velocity_mph)

    html = f"""
    <div style="font-size:0.85rem; color:#ccc;">

    <h4 style="color:#00ffff;">AVSS Parachute Recovery System (PRS) Performance</h4>

    <table style="width:100%; border-collapse:collapse;">
        <tr style="background:#1a1a1a;">
            <th style="padding:8px; text-align:left;">Metric</th>
            <th style="padding:8px; text-align:left;">Value</th>
            <th style="padding:8px; text-align:left;">Status</th>
        </tr>
        <tr>
            <td style="padding:8px;"><b>Armed at event</b></td>
            <td style="padding:8px;">{"✓ Yes" if crash_event.parachute_deployed else "✗ No"}</td>
            <td style="padding:8px;">{"🟢 OK" if crash_event.parachute_deployed else "🔴 NOT ARMED"}</td>
        </tr>
        <tr style="background:#0a0a0a;">
            <td style="padding:8px;"><b>Deployment triggered</b></td>
            <td style="padding:8px;">{"✓ Yes" if crash_event.parachute_success else "✗ No"}</td>
            <td style="padding:8px;">{"🟢 OK" if crash_event.parachute_success else "🔴 FAILED"}</td>
        </tr>
        <tr>
            <td style="padding:8px;"><b>Deploy time</b></td>
            <td style="padding:8px;">{telemetry.parachute_deploy_time_ms:.0f} ms</td>
            <td style="padding:8px;">{"🟢 OK (< 270ms)" if telemetry.parachute_deploy_time_ms < 270 else "🟡 Slow (> 270ms)"}</td>
        </tr>
        <tr style="background:#0a0a0a;">
            <td style="padding:8px;"><b>Altitude AGL at deploy</b></td>
            <td style="padding:8px;">{crash_event.altitude_ft:.0f} ft</td>
            <td style="padding:8px;">{"🟢 Above CMFA (116.8 ft)" if crash_event.altitude_ft >= AVSS_CMFA_FT else "🟡 Below CMFA" if crash_event.altitude_ft >= AVSS_MIN_DEPLOY_FT else "🔴 Below deploy floor"}</td>
        </tr>
        <tr>
            <td style="padding:8px;"><b>Impact velocity</b></td>
            <td style="padding:8px;">{telemetry.impact_velocity_mph:.1f} mph</td>
            <td style="padding:8px;">{"🟢 Safe (< 15 mph)" if telemetry.impact_velocity_mph < 15 else "🟡 Acceptable (< 25 mph)" if telemetry.impact_velocity_mph < 25 else "🔴 High (> 25 mph)"}</td>
        </tr>
        <tr style="background:#0a0a0a;">
            <td style="padding:8px;"><b>Impact energy</b></td>
            <td style="padding:8px;">{impact_energy:.1f} ft-lbs</td>
            <td style="padding:8px;">{"🟢 Category 3 compliant (< 25 ft-lbs)" if impact_energy < AVSS_MAX_IMPACT_ENERGY_FTLBS else "🔴 Exceeds limit (> 25 ft-lbs)"}</td>
        </tr>
        <tr>
            <td style="padding:8px;"><b>Drift distance</b></td>
            <td style="padding:8px;">{telemetry.landing_zone_impact_radius_ft:.0f} ft</td>
            <td style="padding:8px;">{"🟢 Minimal (< 50 ft)" if telemetry.landing_zone_impact_radius_ft < 50 else "🟡 Moderate (50-150 ft)" if telemetry.landing_zone_impact_radius_ft < 150 else "🟡 High (> 150 ft)"}</td>
        </tr>
    </table>

    <h4 style="color:#00ffff; margin-top:15px;">AVSS PRS Specifications</h4>
    <ul style="font-size:0.8rem;">
        <li><b>System Weight:</b> 200 grams</li>
        <li><b>CMFA (Certified Min Flight Alt):</b> 116.8 ft AGL (35.6 m)</li>
        <li><b>Min Deploy Altitude:</b> 32.8 ft AGL (10 m)</li>
        <li><b>Category 3 Limit:</b> < 25 ft-lbs impact energy</li>
        <li><b>Standard:</b> ASTM F3322 certified</li>
        <li><b>Deployment Modes:</b> Auto (erratic airframe) + Manual emergency</li>
    </ul>

    <h4 style="color:#00ffff; margin-top:15px;">Outcome</h4>
    <p style="font-size:1.1rem; color:#00ffff;">
        {
            "✓ Parachute deployment successful — impact energy within Category 3 limits" if crash_event.parachute_success and impact_energy < AVSS_MAX_IMPACT_ENERGY_FTLBS else
            "⚠ Parachute deployed but impact energy elevated" if crash_event.parachute_success else
            "✗ Parachute deployment failed — full impact energy absorbed"
        }
    </p>

    </div>
    """

    st.markdown(html, unsafe_allow_html=True)
