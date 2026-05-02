"""HTML report generation, KML export, and dashboard rendering."""

import streamlit as st

import pandas as pd

import numpy as np

import json, re, io, math, datetime, base64

import simplekml

from shapely.geometry import Polygon

from modules.config import CONFIG, GUARDIAN_FLIGHT_HOURS_PER_DAY, STATION_COLORS, SIMULATOR_DISCLAIMER_SHORT

from modules.geospatial import get_address_from_latlon

from modules.cad_parser import _get_annualized_calls

from modules.faa_rf import get_circle_coords


def _parse_datetime_series(series, formats=None):

    """Parse a datetime-like series without falling straight to dateutil inference."""

    if series is None:

        return None

    parsed = None

    for fmt in (formats or []):

        try:

            trial = pd.to_datetime(series, format=fmt, errors='coerce')

            if trial.notna().sum() > 0:

                parsed = trial

                break

        except Exception:

            continue

    if parsed is None:

        try:

            parsed = pd.to_datetime(series, format='mixed', errors='coerce')

        except Exception:

            return None

    return parsed


def _detect_datetime_series_for_labels(df):

    """Return a best-effort parsed datetime series from common CAD field patterns."""

    if df is None or len(df) == 0:

        return None

    try:

        if 'date' in df.columns and 'time' in df.columns:

            s = _parse_datetime_series(
                df['date'].astype(str).fillna('') + ' ' + df['time'].astype(str).fillna(''),
                formats=['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M', '%m/%d/%Y %I:%M %p'],
            )

            if s.notna().sum() > 0:

                return s

        if 'date' in df.columns:

            s = _parse_datetime_series(
                df['date'],
                formats=['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d', '%d/%m/%Y'],
            )

            if s.notna().sum() > 0:

                return s

        candidates = [

            'createdtime_central', 'created time', 'createdtime', 'call datetime', 'calldatetime',

            'timestamp', 'datetime', 'incident datetime', 'received time', 'time received',

            'dispatch datetime', 'event time', 'event datetime'

        ]

        col_map = {str(c).strip().lower(): c for c in df.columns}

        for cand in candidates:

            col = cand if cand in df.columns else col_map.get(cand)

            if col is not None:

                s = _parse_datetime_series(
                    df[col],
                    formats=['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M', '%m/%d/%Y %I:%M %p'],
                )

                if s.notna().sum() > 0:

                    return s

    except Exception:

        return None

    return None











def estimate_high_activity_overtime(df_calls_full, state_abbr, calls_covered_perc, dfr_dispatch_rate, deflection_rate):

    """Estimate high-activity monthly staffing pressure and officer overtime replacement cost."""

    if df_calls_full is None or len(df_calls_full) == 0:

        return None

    try:

        dt = _detect_datetime_series_for_labels(df_calls_full)

        if dt is None:

            return None

        work = df_calls_full.copy()

        work['_dt'] = pd.to_datetime(dt, errors='coerce')

        work = work.dropna(subset=['_dt'])

        if work.empty:

            return None



        work['_month'] = work['_dt'].dt.to_period('M').astype(str)

        work['_hour_key'] = work['_dt'].dt.floor('h')

        hourly = work.groupby('_hour_key').size().rename('calls').reset_index()

        hourly['_month'] = hourly['_hour_key'].dt.to_period('M').astype(str)



        monthly_rows = []

        for month, grp in hourly.groupby('_month'):

            if grp.empty:

                continue

            threshold = grp['calls'].quantile(0.75)

            busy = grp[grp['calls'] >= threshold].copy()

            if busy.empty:

                busy = grp.nlargest(max(1, int(len(grp) * 0.25)), 'calls')

            total_busy_calls = float(busy['calls'].sum())

            busy_hours = int(busy['_hour_key'].nunique())

            if busy_hours <= 0:

                continue



            officer_hourly, wage_source = CONFIG['OFFICER_HOURLY_WAGE'], 'estimate'

            overtime_hourly = officer_hourly * 1.5



            drone_relief_share = (calls_covered_perc / 100.0) * dfr_dispatch_rate * deflection_rate

            residual_busy_calls = total_busy_calls * max(0.0, 1.0 - drone_relief_share)

            overtime_cost = residual_busy_calls * CONFIG['OFFICER_COST_PER_CALL']

            overtime_hours = overtime_cost / overtime_hourly if overtime_hourly > 0 else 0.0



            monthly_rows.append({

                'month': month,

                'busy_hours': busy_hours,

                'busy_calls': total_busy_calls,

                'residual_calls': residual_busy_calls,

                'ot_hourly': overtime_hourly,

                'ot_cost': overtime_cost,

                'ot_hours': overtime_hours,

                'wage_source': wage_source,

            })



        if not monthly_rows:

            return None

        monthly_df = pd.DataFrame(monthly_rows).sort_values('month')

        return {

            'monthly': monthly_df,

            'avg_busy_hours': float(monthly_df['busy_hours'].mean()),

            'avg_ot_hours': float(monthly_df['ot_hours'].mean()),

            'avg_ot_cost': float(monthly_df['ot_cost'].mean()),

            'ot_hourly': float(monthly_df['ot_hourly'].median()),

            'wage_source': monthly_df['wage_source'].iloc[0],

            'peak_month': monthly_df.loc[monthly_df['ot_cost'].idxmax(), 'month'],

            'peak_ot_cost': float(monthly_df['ot_cost'].max()),

        }

    except Exception:

        return None











def estimate_specialty_response_savings(df_calls_full, total_calls_annual, calls_covered_perc=100.0):

    """Estimate additional annual savings from thermal-enabled search efficiency and avoided K-9 deployments.



    The model intentionally stays conservative:

    - Thermal value is applied to a subset of addressable calls that often benefit from search / locate / perimeter support.

    - K-9 value is applied to a smaller subset of addressable calls that are likely to require tracking or perimeter work.

    - If CAD call types are available, the function uses them; otherwise it falls back to conservative defaults.

    """

    addressable_calls = max(0.0, float(total_calls_annual or 0) * max(0.0, min(1.0, float(calls_covered_perc or 0) / 100.0)))

    out = {

        'addressable_calls_annual': addressable_calls,

        'thermal_rate': float(CONFIG["THERMAL_DEFAULT_APPLICABLE_RATE"]),

        'k9_rate': float(CONFIG["K9_DEFAULT_APPLICABLE_RATE"]),

        'fire_rate': float(CONFIG["FIRE_DEFAULT_APPLICABLE_RATE"]),

        'thermal_calls_annual': 0.0,

        'k9_calls_annual': 0.0,

        'fire_calls_annual': 0.0,

        'thermal_savings': 0.0,

        'k9_savings': 0.0,

        'fire_savings': 0.0,

        'additional_savings_total': 0.0,

        'source': 'default_model',

    }

    if addressable_calls <= 0:

        return out



    call_type_col = None

    if df_calls_full is not None and len(df_calls_full) > 0:

        for c in ['call_type_desc','agencyeventtypecodedesc','calldesc','description','nature','event_desc']:

            if c in df_calls_full.columns and df_calls_full[c].dropna().shape[0] > 0:

                call_type_col = c

                break



    if call_type_col is not None:

        s = df_calls_full[call_type_col].fillna('').astype(str).str.lower().str.strip()

        if not s.empty:

            thermal_pattern = (

                r'suspicious|prowler|alarm|burglar|robbery|theft|assault|shots|gun|weapon|person search|search|perimeter|'

                r'missing|welfare|suicid|disturbance|fight|domestic|trespass|subject check|unknown trouble|wanted'

            )

            k9_pattern = (

                r'k-?9|canine|track|tracking|perimeter|search|search warrant|manhunt|flee|fled|foot pursuit|'

                r'missing|burglary|robbery|woods|field|suspect search'

            )

            thermal_rate_raw = float(s.str.contains(thermal_pattern, regex=True, na=False).mean())

            k9_rate_raw = float(s.str.contains(k9_pattern, regex=True, na=False).mean())

            fire_pattern = (

                r'fire|structure fire|building fire|fire alarm|alarm fire|brush fire|grass fire|'

                r'wildfire|vegetation fire|vehicle fire|dumpster fire|smoke|smoke investigation|'

                r'odor of smoke|fire investigation|carbon monoxide|co alarm|gas leak|hazmat'

            )

            fire_rate_raw = float(s.str.contains(fire_pattern, regex=True, na=False).mean())

            out['thermal_rate'] = min(0.25, max(CONFIG["THERMAL_DEFAULT_APPLICABLE_RATE"] * 0.5, thermal_rate_raw if thermal_rate_raw > 0 else CONFIG["THERMAL_DEFAULT_APPLICABLE_RATE"]))

            out['k9_rate'] = min(0.08, max(CONFIG["K9_DEFAULT_APPLICABLE_RATE"] * 0.5, k9_rate_raw if k9_rate_raw > 0 else CONFIG["K9_DEFAULT_APPLICABLE_RATE"]))

            out['fire_rate'] = min(0.20, max(CONFIG["FIRE_DEFAULT_APPLICABLE_RATE"] * 0.5, fire_rate_raw if fire_rate_raw > 0 else CONFIG["FIRE_DEFAULT_APPLICABLE_RATE"]))

            out['source'] = f'cad_call_types:{call_type_col}'



    out['thermal_calls_annual'] = addressable_calls * out['thermal_rate']

    out['k9_calls_annual'] = addressable_calls * out['k9_rate']

    out['fire_calls_annual'] = addressable_calls * out['fire_rate']

    out['thermal_savings'] = out['thermal_calls_annual'] * float(CONFIG["THERMAL_SAVINGS_PER_CALL"])

    out['k9_savings'] = out['k9_calls_annual'] * float(CONFIG["K9_SAVINGS_PER_CALL"])

    out['fire_savings'] = out['fire_calls_annual'] * float(CONFIG["FIRE_SAVINGS_PER_CALL"])

    out['additional_savings_total'] = out['thermal_savings'] + out['k9_savings'] + out['fire_savings']

    return out







def build_high_activity_staffing_html(overtime_stats, dark=True, compact=False):

    """Return an HTML block for the High-Activity Staffing Pressure section."""

    if overtime_stats is None:

        return ""

    bg = "#06060a" if dark else "#ffffff"

    card = "#0c0c12" if dark else "#ffffff"

    border = "#1a1a26" if dark else "#e5e7eb"

    text_main = "#e8e8f2" if dark else "#111118"

    text_muted = "#7777a0" if dark else "#6b7280"

    accent = "#00D2FF"

    title_size = "13px" if compact else "0.95rem"

    body_size = "11px" if compact else "0.72rem"

    metric_size = "24px" if compact else "1.45rem"

    monthly_rows_html = "".join([

        f"<tr><td style='padding:6px 8px; border-top:1px solid {border}; color:{text_main};'>{row.month}</td>"

        f"<td style='padding:6px 8px; border-top:1px solid {border}; text-align:right; color:{text_main};'>{int(row.busy_hours):,}</td>"

        f"<td style='padding:6px 8px; border-top:1px solid {border}; text-align:right; color:{text_main};'>{row.ot_hours:,.0f}</td>"

        f"<td style='padding:6px 8px; border-top:1px solid {border}; text-align:right; color:{accent};'>${row.ot_cost:,.0f}</td></tr>"

        for row in overtime_stats['monthly'].itertuples(index=False)

    ])

    return f"""

    <div style="background:{bg}; border:1px solid {border}; border-radius:8px; padding:16px 18px; margin:14px 0 14px 0;">

        <div style="display:flex; justify-content:space-between; align-items:flex-end; gap:12px; flex-wrap:wrap; margin-bottom:10px;">

            <div>

                <div style="font-size:10px; color:{text_muted}; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px;">High-Activity Staffing Pressure</div>

                <div style="font-size:{title_size}; color:{text_main}; font-weight:800;">Estimated officer overtime needed to cover residual peak demand</div>

            </div>

            <div style="font-size:10px; color:{text_muted};">Officer wage basis: <span style="color:{text_main};">{overtime_stats['wage_source']}</span></div>

        </div>

        <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:12px;">

            <div style="background:{card}; border:1px solid {border}; border-radius:6px; padding:10px; text-align:center;">

                <div style="font-size:10px; color:{text_muted}; text-transform:uppercase;">Avg High-Activity Hours / Mo</div>

                <div style="font-size:{metric_size}; font-weight:800; color:{text_main}; font-family:'IBM Plex Mono', monospace;">{overtime_stats['avg_busy_hours']:.0f}</div>

            </div>

            <div style="background:{card}; border:1px solid {border}; border-radius:6px; padding:10px; text-align:center;">

                <div style="font-size:10px; color:{text_muted}; text-transform:uppercase;">Avg OT Hours Needed / Mo</div>

                <div style="font-size:{metric_size}; font-weight:800; color:{text_main}; font-family:'IBM Plex Mono', monospace;">{overtime_stats['avg_ot_hours']:.0f}</div>

            </div>

            <div style="background:{card}; border:1px solid {border}; border-radius:6px; padding:10px; text-align:center;">

                <div style="font-size:10px; color:{text_muted}; text-transform:uppercase;">Avg OT Cost / Mo</div>

                <div style="font-size:{metric_size}; font-weight:800; color:{accent}; font-family:'IBM Plex Mono', monospace;">${overtime_stats['avg_ot_cost']:,.0f}</div>

            </div>

            <div style="background:{card}; border:1px solid {border}; border-radius:6px; padding:10px; text-align:center;">

                <div style="font-size:10px; color:{text_muted}; text-transform:uppercase;">Avg OT Hourly Rate</div>

                <div style="font-size:{metric_size}; font-weight:800; color:{text_main}; font-family:'IBM Plex Mono', monospace;">${overtime_stats['ot_hourly']:.2f}</div>

            </div>

        </div>

        <div style="font-size:{body_size}; color:{text_muted}; margin-bottom:10px;">Peak month: <span style="color:{text_main}; font-weight:700;">{overtime_stats['peak_month']}</span> · estimated OT spend <span style="color:{accent}; font-weight:700;">${overtime_stats['peak_ot_cost']:,.0f}</span></div>

        <div style="overflow-x:auto;">

            <table style="width:100%; border-collapse:collapse; font-size:{body_size};">

                <thead>

                    <tr>

                        <th style="text-align:left; padding:6px 8px; color:{text_muted}; font-weight:700; border-bottom:1px solid {border};">Month</th>

                        <th style="text-align:right; padding:6px 8px; color:{text_muted}; font-weight:700; border-bottom:1px solid {border};">High-Activity Hours</th>

                        <th style="text-align:right; padding:6px 8px; color:{text_muted}; font-weight:700; border-bottom:1px solid {border};">OT Hours</th>

                        <th style="text-align:right; padding:6px 8px; color:{text_muted}; font-weight:700; border-bottom:1px solid {border};">OT Cost</th>

                    </tr>

                </thead>

                <tbody>{monthly_rows_html}</tbody>

            </table>

        </div>

    </div>

    """







def generate_command_center_html(df, total_orig_calls, export_mode=False):

    """Generates the full Command Center visual suite with interactive Javascript filtering."""

    if df is None or df.empty:

        return "<div style='color:gray; padding:20px;'>Analytics unavailable. No incident records loaded.</div>"



    import calendar as _cal

    import json



    df_ana = df.copy()



    dt_obj = None

    if 'date' in df_ana.columns:

        _date_str = df_ana['date'].astype(str).fillna('')

        if 'time' in df_ana.columns:

            _time_str = df_ana['time'].astype(str).fillna('')

            _combined = _date_str + ' ' + _time_str

        else:

            _combined = _date_str

        # Try ISO format first (what our parser stores), then fall back

        for _fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:

            try:

                _trial = pd.to_datetime(_combined, format=_fmt, errors='coerce')

                if _trial.notna().sum() > len(df_ana) * 0.5:

                    dt_obj = _trial

                    break

            except Exception:

                continue

        if dt_obj is None or dt_obj.dropna().empty:

            dt_obj = _parse_datetime_series(
                _combined,
                formats=['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M', '%m/%d/%Y %I:%M %p'],
            )



    if dt_obj is None or dt_obj.dropna().empty:

        dt_candidates = [

            'createdtime_central', 'created time', 'createdtime', 'call datetime', 'calldatetime',

            'timestamp', 'datetime', 'incident datetime', 'received time', 'time received',

            'dispatch datetime', 'event time', 'event datetime'

        ]

        for cand in dt_candidates:

            if cand in df_ana.columns:

                trial = _parse_datetime_series(
                    df_ana[cand],
                    formats=['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M', '%m/%d/%Y %I:%M %p'],
                )

                if trial.dropna().shape[0] > 0:

                    dt_obj = trial

                    break



    if dt_obj is None or dt_obj.dropna().empty:

        col_map = {str(c).strip().lower(): c for c in df_ana.columns}

        for cand in [

            'createdtime_central', 'created time', 'createdtime', 'call datetime', 'calldatetime',

            'timestamp', 'datetime', 'incident datetime', 'received time', 'time received',

            'dispatch datetime', 'event time', 'event datetime'

        ]:

            if cand in col_map:

                _col_real = col_map[cand]

                _fmt_try = ['%m/%d/%Y %I:%M %p','%m/%d/%Y %H:%M:%S','%Y-%m-%d %H:%M:%S',

                            '%Y-%m-%dT%H:%M:%S','%m/%d/%Y %H:%M','%Y-%m-%d %H:%M']

                for _fmt in _fmt_try:

                    try:

                        trial = pd.to_datetime(df_ana[_col_real], format=_fmt, errors='coerce')

                        if trial.notna().sum() > 0:

                            dt_obj = trial

                            break

                    except Exception:

                        continue

                if dt_obj is not None and dt_obj.dropna().shape[0] > 0:

                    break

                # Last resort: dateutil inference

                if dt_obj is None or dt_obj.dropna().empty:

                    trial = _parse_datetime_series(
                        df_ana[_col_real],
                        formats=['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M', '%m/%d/%Y %I:%M %p'],
                    )

                    if trial.dropna().shape[0] > 0:

                        dt_obj = trial

                        break



    # Universal scan: try every object column as a datetime source

    if dt_obj is None or dt_obj.dropna().empty:

        for _col in df_ana.select_dtypes(include='object').columns:

            try:

                _samp = df_ana[_col].dropna().head(20)

                _trial = pd.to_datetime(_samp, format='mixed', errors='coerce')

                if _trial.notna().sum() >= 10 and _trial.dt.year.between(2000, 2035).mean() > 0.8:

                    dt_obj = pd.to_datetime(df_ana[_col], format='mixed', errors='coerce')

                    break

            except Exception:

                continue



    if dt_obj is None or dt_obj.dropna().empty:

        return "<div style='color:gray; padding:20px;'>Analytics unavailable. Missing date/time fields.</div>"



    df_ana['dt_obj'] = dt_obj

    df_ana = df_ana.dropna(subset=['dt_obj'])

    if df_ana.empty: return "<div>No valid dates found in data.</div>"



    # 1. Parse dates and build a lightweight records array for JavaScript

    records = []

    for _, r in df_ana.iterrows():

        dt = r['dt_obj']

        p_val = str(r['priority']).upper().strip() if 'priority' in r else 'UNKNOWN'

        if p_val == 'NAN' or not p_val: p_val = 'UNKNOWN'

        records.append({

            'd': dt.strftime('%Y-%m-%d'),

            'h': dt.hour,

            'dow': dt.dayofweek, # Mon=0, Sun=6

            'p': p_val

        })

        

    # 2. Dynamically identify all priority types

    unique_pris = sorted(list(set(r['p'] for r in records)))

    options_html = '<option value="ALL">ALL PRIORITIES</option>'

    for p in unique_pris:

        # Clean up the display name slightly

        display_p = f"PRIORITY {p}" if len(p) <= 2 else p

        options_html += f'<option value="{p}">{display_p}</option>'



    # 3. Build the initial HTML shell (JS will populate the numbers)

    month_keys = sorted(list(set(r['d'][:7] for r in records)))

    cal_html = "<div style='display:grid; grid-template-columns:repeat(auto-fill, minmax(250px, 1fr)); gap:15px; margin-top:20px;'>"

    

    for mk in month_keys[:12]:

        yr, mo = int(mk.split('-')[0]), int(mk.split('-')[1])

        cal_html += f"<div style='background:#0c0c12; border:1px solid #1a1a26; border-radius:6px; padding:12px;'>"

        cal_html += f"<div style='display:flex; justify-content:space-between; align-items:baseline; border-bottom:1px solid #252535; padding-bottom:6px; margin-bottom:8px;'><span style='color:#00D2FF; font-weight:800; font-size:12px; text-transform:uppercase; letter-spacing:1px;'>{_cal.month_name[mo]} {yr}</span><span id='month-total-{mk}' style='color:#7777a0; font-size:10px; font-family:monospace;'>0 calls</span></div>"

        

        cal_html += "<div style='display:grid; grid-template-columns:repeat(7, 1fr); gap:2px; margin-bottom:4px;'>"

        for i, dname in enumerate(['Su','Mo','Tu','We','Th','Fr','Sa']):

            c = ['#FF6B6B','#4ECDC4','#45B7D1','#F0B429','#96CEB4','#DDA0DD','#FF9A8B'][i]

            cal_html += f"<div style='font-size:9px; text-align:center; color:{c}; font-weight:600;'>{dname}</div>"

        cal_html += "</div>"

        

        cal_html += "<div style='display:grid; grid-template-columns:repeat(7, 1fr); gap:2px;'>"

        first_dow_sun = (_cal.weekday(yr, mo, 1) + 1) % 7

        last_day = _cal.monthrange(yr, mo)[1]

        

        for _ in range(first_dow_sun): cal_html += "<div></div>"

            

        for d in range(1, last_day + 1):

            dk = f"{yr}-{mo:02d}-{d:02d}"

            dow_idx = (_cal.weekday(yr, mo, d) + 1) % 7 

            cal_html += f"<div class='day-cell' data-date='{dk}' data-mkey='{mk}' data-month='{_cal.month_name[mo]}' data-d='{d}' data-y='{yr}' data-dow='{dow_idx}' style='aspect-ratio:1; border-radius:2px; display:flex; flex-direction:column; align-items:center; justify-content:center; position:relative; font-family:monospace; cursor:default; border:1px solid transparent; transition:transform 0.1s;' onmouseover='showTooltip(this, event)' onmouseout='hideTooltip()'></div>"

            

        cal_html += "</div></div>"

    cal_html += "</div>"



    controls_html = f"""

    <div style="display:flex; gap:20px; align-items:center; background:#0c0c12; border:1px solid #1a1a26; padding:12px 18px; border-radius:6px; margin-bottom:20px;">

        <div style="display:flex; align-items:center; gap:10px;">

            <span style="font-size:10px; color:#7777a0; font-weight:bold; letter-spacing:1px; text-transform:uppercase;">Priority Filter:</span>

            <select id="pri-select" onchange="currentPri=this.value; updateDashboard();" style="background:#1a1a26; color:#00D2FF; border:1px solid #252535; padding:6px 12px; border-radius:4px; font-weight:bold; cursor:pointer;">

                {options_html}

            </select>

        </div>

        <div style="display:flex; align-items:center; gap:10px;">

            <span style="font-size:10px; color:#7777a0; font-weight:bold; letter-spacing:1px; text-transform:uppercase;">Shift Length:</span>

            <select id="shift-select" onchange="currentShift=parseInt(this.value); updateDashboard();" style="background:#1a1a26; color:#00D2FF; border:1px solid #252535; padding:6px 12px; border-radius:4px; font-weight:bold; cursor:pointer;">

                <option value="8" selected>8 HOURS</option>

                <option value="10">10 HOURS</option>

                <option value="12">12 HOURS</option>

            </select>

        </div>

    </div>

    """



    full_html = f"""

    <div style="background:#000; color:#e8e8f2; font-family: 'Barlow', sans-serif; padding:15px; border-radius:8px;">

        <style>

            .day-cell:hover {{ transform: scale(1.15); z-index: 10; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }}

            .day-peak {{ border-color: #cc0000 !important; font-weight: 700; }}

            #dfr-tooltip {{ position: fixed; z-index: 9999; background: #09090f; border: 1px solid #252535; border-radius: 6px; padding: 12px 16px; font-family: monospace; font-size: 11px; color: #e8e8f2; pointer-events: none; box-shadow: 0 6px 24px rgba(0,0,0,0.8); display: none; min-width: 220px; }}

        </style>

        

        <div id="dfr-tooltip"></div>

        <div style="color:#00D2FF; font-weight:900; letter-spacing:3px; font-size:14px; text-transform:uppercase; margin-bottom:20px; border-bottom:1px solid #1a1a26; padding-bottom:10px;">Data Ingestion Analytics</div>

        

        {controls_html}

        

        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px; margin-bottom:20px;">

            <div style="background:#0c0c12; border-left:4px solid #00D2FF; padding:15px; border-radius:4px; border-top:1px solid #1a1a26; border-right:1px solid #1a1a26; border-bottom:1px solid #1a1a26;">

                <div style="color:#00D2FF; font-size:26px; font-weight:900; font-family:monospace;" id="kpi-total-val">0</div>

                <div style="color:#7777a0; font-size:10px; text-transform:uppercase; letter-spacing:1px; margin-top:4px;">Displayed Incidents</div>

            </div>

            <div style="background:#0c0c12; border-left:4px solid #F0B429; padding:15px; border-radius:4px; border-top:1px solid #1a1a26; border-right:1px solid #1a1a26; border-bottom:1px solid #1a1a26;">

                <div style="color:#F0B429; font-size:26px; font-weight:900; font-family:monospace;" id="kpi-peak-val">0:00</div>

                <div style="color:#7777a0; font-size:10px; text-transform:uppercase; letter-spacing:1px; margin-top:4px;">Peak Activity Hour</div>

            </div>

        </div>

        

        <div style="display:grid; grid-template-columns: 3fr 2fr; gap:15px; margin-bottom:25px;">

            <div style="background:#06060a; border:1px solid #1a1a26; border-radius:6px; padding:15px;">

                <div style="margin-bottom:12px; font-size:10px; color:#7777a0; text-transform:uppercase; letter-spacing:1px; font-weight:bold;">Optimized DFR Shift Windows</div>

                <div id="shift-container"></div>

            </div>

            <div style="background:#06060a; border:1px solid #1a1a26; border-radius:6px; padding:15px; display:flex; flex-direction:column;">

                <div style="margin-bottom:12px; font-size:10px; color:#7777a0; text-transform:uppercase; letter-spacing:1px; font-weight:bold;">Call Volume by Day of Week</div>

                <div style="display:flex; justify-content:space-between; align-items:flex-end; flex-grow:1; padding:10px 5px 0;" id="dow-container"></div>

            </div>

        </div>

        

        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:5px; padding-top:15px; border-top:1px solid #1a1a26;">

            <div style="font-size:14px; font-weight:800; color:#fff; letter-spacing:1px; text-transform:uppercase;">DFR Deployment Calendar</div>

            <div style="display:flex; gap:12px; font-family:monospace; font-size:9px; color:#8d93b8; flex-wrap:wrap;">

                <div style="display:flex; align-items:center; gap:5px;"><div style="width:9px; height:9px; background:#59B7FF; border:1px solid #1E5D91; border-radius:2px; box-shadow:0 0 6px rgba(89,183,255,0.18);"></div>VERY LOW</div>

                <div style="display:flex; align-items:center; gap:5px;"><div style="width:9px; height:9px; background:#45E28A; border:1px solid #1D7D49; border-radius:2px; box-shadow:0 0 6px rgba(69,226,138,0.18);"></div>LOW</div>

                <div style="display:flex; align-items:center; gap:5px;"><div style="width:9px; height:9px; background:#FFD84D; border:1px solid #8A6F00; border-radius:2px; box-shadow:0 0 6px rgba(255,216,77,0.18);"></div>MEDIUM</div>

                <div style="display:flex; align-items:center; gap:5px;"><div style="width:9px; height:9px; background:#FF9F43; border:1px solid #9A4F00; border-radius:2px; box-shadow:0 0 6px rgba(255,159,67,0.18);"></div>HIGH</div>

                <div style="display:flex; align-items:center; gap:5px;"><div style="width:9px; height:9px; background:#FF5B6E; border:1px solid #A51F2D; border-radius:2px; box-shadow:0 0 8px rgba(255,91,110,0.24);"></div>PEAK</div>

            </div>

        </div>

        

        {cal_html}

        

        <script>

            const rawData = {json.dumps(records)};

            const totalOrigCalls = {int(total_orig_calls) if total_orig_calls else len(records)};

            let currentShift = 8;

            let currentPri = 'ALL';

            window.dateHourly = {{}};

            const dowNames = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

            const dowColors = ['#4ECDC4','#45B7D1','#F0B429','#96CEB4','#DDA0DD','#FF9A8B','#FF6B6B'];

            const stripeColors = ['#FF6B6B','#4ECDC4','#45B7D1','#F0B429','#96CEB4','#DDA0DD','#FF9A8B'];



            function updateDashboard() {{

                let filtered = rawData;

                if(currentPri !== 'ALL') {{

                    filtered = rawData.filter(d => String(d.p) === currentPri);

                }}



                let total = filtered.length;

                if(currentPri === 'ALL') {{ total = totalOrigCalls; }}

                document.getElementById('kpi-total-val').innerHTML = total.toLocaleString();



                let hourly = new Array(24).fill(0);

                let daily = {{}};

                let dowCounts = new Array(7).fill(0);

                window.dateHourly = {{}};

                let mTotal = {{}};

                let mMax = {{}};



                filtered.forEach(r => {{

                    hourly[r.h]++;

                    daily[r.d] = (daily[r.d] || 0) + 1;

                    dowCounts[r.dow]++;

                    

                    if(!window.dateHourly[r.d]) window.dateHourly[r.d] = new Array(24).fill(0);

                    window.dateHourly[r.d][r.h]++;

                    

                    let m = r.d.substring(0,7);

                    mTotal[m] = (mTotal[m] || 0) + 1;

                    if(!mMax[m] || daily[r.d] > mMax[m]) mMax[m] = daily[r.d];

                }});



                // Peak Hour

                let peakHr = hourly.indexOf(Math.max(...hourly));

                if(total === 0) peakHr = 0;

                document.getElementById('kpi-peak-val').innerText = peakHr + ':00';



                // Shifts

                let shiftHtml = "";

                [8, 10, 12].forEach(win => {{

                    let bestV = 0, bestS = 0;

                    for(let s=0; s<24; s++) {{

                        let v = 0;

                        for(let h=0; h<win; h++) v += hourly[(s+h)%24];

                        if(v > bestV) {{ bestV = v; bestS = s; }}

                    }}

                    let pct = total > 0 ? (bestV/total)*100 : 0;

                    let isActive = (win === currentShift);

                    let bgColor = isActive ? "rgba(0,210,255,0.08)" : "#0c0c12";

                    let brColor = isActive ? "#00D2FF" : "#252535";

                    let badge = isActive ? "<div style='font-size:8px; color:#00D2FF; margin-left:10px; border:1px solid #00D2FF; padding:1px 4px; border-radius:2px;'>SELECTED</div>" : "";

                    let eHr = (bestS + win) % 24;

                    let pS = String(bestS).padStart(2,'0');

                    let pE = String(eHr).padStart(2,'0');

                    

                    let shiftSegments = '';

                    if (bestS + win <= 24) {{

                        shiftSegments = `<div style="position:absolute; left:${{(bestS/24)*100}}%; width:${{(win/24)*100}}%; background:#00D2FF; height:100%; border-radius:4px; opacity:0.6;"></div>`;

                    }} else {{

                        const firstWidth = ((24 - bestS) / 24) * 100;

                        const secondWidth = (((bestS + win) % 24) / 24) * 100;

                        shiftSegments = `

                            <div style="position:absolute; left:${{(bestS/24)*100}}%; width:${{firstWidth}}%; background:#00D2FF; height:100%; border-radius:4px; opacity:0.6;"></div>

                            <div style="position:absolute; left:0%; width:${{secondWidth}}%; background:#00D2FF; height:100%; border-radius:4px; opacity:0.6;"></div>`;

                    }}

                    shiftHtml += `<div style="display:flex; align-items:center; background:${{bgColor}}; border:1px solid ${{brColor}}; padding:8px; margin-bottom:5px; border-radius:4px; transition:all 0.2s;">

                        <div style="width:50px; font-weight:800; color:#fff; font-size:13px;">${{win}}hr</div>

                        <div style="width:110px; font-family:monospace; color:#00D2FF; font-size:12px;">${{pS}}:00 - ${{pE}}:00</div>

                        <div style="flex-grow:1; background:#1a1a26; height:8px; border-radius:4px; margin:0 15px; position:relative; overflow:hidden;">

                            ${{shiftSegments}}

                        </div>

                        <div style="width:50px; text-align:right; font-family:monospace; color:#00D2FF; font-size:13px;">${{pct.toFixed(1)}}%</div>

                        ${{badge}}

                    </div>`;

                }});

                document.getElementById('shift-container').innerHTML = shiftHtml;



                // DOW

                let maxDow = Math.max(...dowCounts, 1);

                let dowHtml = "";

                for(let i=0; i<7; i++) {{

                    let hPct = (dowCounts[i]/maxDow)*100;

                    dowHtml += `<div style="flex:1; display:flex; flex-direction:column; align-items:center;">

                        <div style="background:#1a1a26; width:22px; height:80px; position:relative; border-radius:2px;">

                            <div style="position:absolute; bottom:0; width:100%; height:${{hPct}}%; background:${{dowColors[i]}}; border-radius:2px; transition:height 0.3s;"></div>

                        </div>

                        <span style="font-size:10px; color:#7777a0; margin-top:6px; font-family:monospace;">${{dowNames[i]}}</span>

                    </div>`;

                }}

                document.getElementById('dow-container').innerHTML = dowHtml;



                // Month Headers

                document.querySelectorAll('[id^="month-total-"]').forEach(el => {{

                    let m = el.id.replace('month-total-','');

                    let cnt = mTotal[m] || 0;

                    el.innerText = cnt.toLocaleString() + ' calls';

                }});



                // Calendar Cells

                document.querySelectorAll('.day-cell').forEach(cell => {{

                    if(!cell.hasAttribute('data-date')) return;

                    let d = cell.getAttribute('data-date');

                    let mkey = cell.getAttribute('data-mkey');

                    let cnt = daily[d] || 0;

                    let max = mMax[mkey] || 1;

                    let ratio = max > 0 ? cnt / max : 0;

                    

                    let bg, fc, cls;

                    if (cnt === 0) {{ bg='#08080f'; fc='#333'; cls='day-zero'; }}

                    else if (ratio >= 0.85) {{ bg='#3d0a0a'; fc='#ff4444'; cls='day-peak'; }}

                    else if (ratio >= 0.55) {{ bg='#3d1a00'; fc='#ff8c00'; cls='day-high'; }}

                    else if (ratio >= 0.25) {{ bg='#2d2d00'; fc='#d4c000'; cls='day-med'; }}

                    else {{ bg='#0d3320'; fc='#2ecc71'; cls='day-low'; }}



                    cell.className = 'day-cell ' + cls;

                    cell.style.background = bg;

                    cell.style.color = fc;

                    cell.setAttribute('data-count', cnt);

                    cell.setAttribute('data-ratio', ratio);

                    

                    let domD = cell.getAttribute('data-d');

                    let html = `<span style='font-size:11px; z-index:1; font-weight:bold;'>${{domD}}</span>`;

                    if(cnt > 0) {{

                        html += `<span style='font-size:8px; opacity:0.7; margin-top:1px;'>${{cnt}}</span>`;

                        let dowIdx = parseInt(cell.getAttribute('data-dow'));

                        html += `<div style='position:absolute; bottom:0; left:0; right:0; height:2px; background:${{stripeColors[dowIdx]}}; opacity:0.7; border-radius:0 0 2px 2px;'></div>`;

                    }}

                    cell.innerHTML = html;

                }});

            }}



            function showTooltip(el, ev) {{

                const cnt = parseInt(el.getAttribute('data-count'));

                if (cnt === 0) return;

                

                const dk = el.getAttribute('data-date');

                const ratio = parseFloat(el.getAttribute('data-ratio'));

                const mName = el.getAttribute('data-month');

                const d = el.getAttribute('data-d');

                const y = el.getAttribute('data-y');

                const dow = parseInt(el.getAttribute('data-dow'));

                

                let loadText = '';

                if (ratio >= 0.85) loadText = '<span style="color:#FF5B6E">■ PEAK</span> — Full crew';

                else if (ratio >= 0.65) loadText = '<span style="color:#FF9F43">■ HIGH</span> — Priority deploy';

                else if (ratio >= 0.45) loadText = '<span style="color:#FFD84D">■ MEDIUM</span> — Standard ops';

                else if (ratio >= 0.25) loadText = '<span style="color:#45E28A">■ LOW</span> — Light staffing';

                else loadText = '<span style="color:#59B7FF">■ VERY LOW</span> — Opportunistic coverage';

                

                const hrArr = window.dateHourly[dk] || Array(24).fill(0);

                let bestV = 0, bestS = 0;

                for (let s=0; s<24; s++) {{

                    let v = 0;

                    for (let h=0; h<currentShift; h++) v += hrArr[(s+h)%24];

                    if (v > bestV) {{ bestV = v; bestS = s; }}

                }}

                const dayPct = cnt > 0 ? Math.round((bestV / cnt) * 100) : 0;

                const eHr = (bestS + currentShift) % 24;

                const fmt = (h) => (h%12 || 12) + (h<12 ? 'AM' : 'PM');

                

                const tt = document.getElementById('dfr-tooltip');

                tt.innerHTML = `

                    <div style="color:#00D2FF; margin-bottom:6px; font-size:12px; font-weight:bold; border-bottom:1px solid #252535; padding-bottom:4px;">${{mName}} ${{d}}, ${{y}} · ${{dowNames[dow]}}</div>

                    <div style="margin-bottom:8px; font-size:13px;">Calls: <span style="color:#fff; font-weight:bold;">${{cnt}}</span>  ·  ${{loadText}}</div>

                    <div style="background:#1a1a26; padding:8px; border-radius:4px;">

                        <div style="color:#7777a0; font-size:9px; letter-spacing:1px; text-transform:uppercase; margin-bottom:4px;">Best ${{currentShift}}hr Shift</div>

                        <div style="color:#00D2FF; font-size:14px; font-weight:bold; margin-bottom:2px;">${{fmt(bestS)}} – ${{fmt(eHr)}}</div>

                        <div style="color:#aaa; font-size:10px;">Covers <span style="color:#fff;">${{dayPct}}%</span> of daily volume</div>

                    </div>

                `;

                

                tt.style.display = 'block';

                

                let left = ev.clientX + 15;

                let top = ev.clientY - 20;

                if (left + 220 > window.innerWidth) left = ev.clientX - 235;

                if (top + 100 > window.innerHeight) top = ev.clientY - 110;

                

                tt.style.left = left + 'px';

                tt.style.top = top + 'px';

            }}

            

            function hideTooltip() {{

                document.getElementById('dfr-tooltip').style.display = 'none';

            }}



            // Run once to populate the dashboard on load

            updateDashboard();

        </script>

    </div>

    """

    return full_html







def _build_cad_charts_html(df_calls):

    """Generate a self-contained HTML block for the PDF/HTML export.

    Includes the Drone Apprehension Impact Value table and the Top Call Types chart.

    Returns an empty string if no real CAD data is available."""

    if df_calls is None or df_calls.empty:

        return ""

    try:

        total_calls = len(df_calls)



        # ── Apprehension metric calculations ─────────────────────────────────

        import streamlit as _st

        dfr_rate        = float(_st.session_state.get('dfr_rate', 25)) / 100.0

        pursuit_rate    = 0.18

        pursuit_calls   = round(total_calls * pursuit_rate)

        dfr_pursuit     = round(pursuit_calls * dfr_rate)

        arr_lift        = 0.20   # +20 pp

        additional_arr  = round(dfr_pursuit * arr_lift)

        coverage_pct    = float(_st.session_state.get('calls_covered_perc', 70) or 70)

        time_saved      = float(_st.session_state.get('avg_time_saved_min', 6) or 6)

        score = round(

            0.40 * min(coverage_pct, 100) +

            0.35 * min(time_saved / 10.0 * 100, 100) +

            0.25 * min(dfr_rate * 100 / 30.0 * 100, 100)

        )

        score = max(0, min(score, 100))

        if score >= 75:

            score_label = "HIGH"

            score_color = "#008060"

        elif score >= 50:

            score_label = "MODERATE"

            score_color = "#b06000"

        else:

            score_label = "LOW"

            score_color = "#b00020"



        rows = [

            ("Average officer response time",          "8 – 12 min",             "2 – 4 min (DFR first on scene)",    "BRINC field deployments"),

            ("Suspect located before officer arrival", "~18% of pursuits",        "~62% of pursuits",                  "Aerial ID + thermal"),

            ("Apprehension rate per pursuit incident", "34%",                     "54%  (+20 pp)",                     "Perimeter intel, real-time relay"),

            ("Additional arrests per 100 calls",       "—",                       "+20 apprehensions",                 "Net lift on DFR-covered incidents"),

            ("Thermal imaging (nighttime pursuits)",   "Unavailable",             "100% of flight hours",              "Eliminates blind foot searches"),

            ("Perimeter containment",                  "4 – 6 officers required", "Drone in < 90 sec",                 "Officers freed for contact"),

            ("DFR-dispatched pursuit calls / year",    "—",                       f"{dfr_pursuit:,}",                  f"{int(dfr_rate*100)}% DFR × {pursuit_calls:,} pursuit calls"),

            ("Est. additional arrests / year",         "—",                       f"+ {additional_arr:,} arrests",     "DFR pursuit calls × +20 pp lift"),

        ]



        rows_html = ""

        for i, (factor, base, drone, source) in enumerate(rows):

            bg = "#f9fafb" if i % 2 == 0 else "#ffffff"

            rows_html += f"""

  <tr style="background:{bg};">

    <td style="padding:9px 12px; font-size:13px; color:#333; border-bottom:1px solid #e5e7eb; width:34%;">{factor}</td>

    <td style="padding:9px 12px; font-size:13px; color:#666; border-bottom:1px solid #e5e7eb; width:20%; text-align:right;">{base}</td>

    <td style="padding:9px 12px; font-size:13px; color:#00695c; font-weight:700; border-bottom:1px solid #e5e7eb; width:20%; text-align:right;">{drone}</td>

    <td style="padding:9px 12px; font-size:11px; color:#888; border-bottom:1px solid #e5e7eb; width:26%;">{source}</td>

  </tr>"""



        # ── Top event types ───────────────────────────────────────────────────

        type_labels, type_vals = [], []

        for _c in ['call_type_desc','agencyeventtypecodedesc','eventdesc','calldesc','description','nature','event_desc']:

            if _c in df_calls.columns and df_calls[_c].dropna().nunique() > 2:

                tc = df_calls[_c].dropna().str.strip().value_counts().head(10)

                type_labels = tc.index.tolist()

                type_vals   = tc.values.tolist()

                break



        import json

        type_labels_js = json.dumps(type_labels)

        type_vals_js   = json.dumps(type_vals)

        has_types      = "true" if type_vals else "false"

        bar_height     = max(260, len(type_labels) * 28 + 60) if type_labels else 260



        return f"""

<h2 style="color:#111; font-size:22px; font-weight:800; margin-top:40px; margin-bottom:20px;

           padding-bottom:10px; border-bottom:2px solid #eee;">Incident Data Analysis</h2>

<p style="font-size:13px; color:#666; margin-bottom:20px;">

  Summary of <strong>{total_calls:,}</strong> calls for service used to optimise drone placement.

</p>



<p style="font-size:12px; font-weight:700; color:#333; text-transform:uppercase;

          letter-spacing:0.6px; margin:0 0 8px;">🎯 Drone Apprehension Impact Value</p>

<p style="font-size:12px; color:#666; margin:0 0 12px 0;">

  How drone deployment improves suspect apprehension — derived from your call volume and DFR

  dispatch rate. Baseline figures from national law enforcement benchmarks.

</p>

<div style="overflow-x:auto; border-radius:8px; border:1px solid #e5e7eb; margin-bottom:10px;">

<table style="width:100%; border-collapse:collapse; font-family:inherit;">

  <thead>

    <tr style="background:#f0faf8;">

      <th style="padding:10px 12px; font-size:11px; font-weight:700; text-transform:uppercase;

                 letter-spacing:0.6px; color:#555; border-bottom:1px solid #d1d5db; text-align:left;">Factor</th>

      <th style="padding:10px 12px; font-size:11px; font-weight:700; text-transform:uppercase;

                 letter-spacing:0.6px; color:#555; border-bottom:1px solid #d1d5db; text-align:right;">Without Drone</th>

      <th style="padding:10px 12px; font-size:11px; font-weight:700; text-transform:uppercase;

                 letter-spacing:0.6px; color:#555; border-bottom:1px solid #d1d5db; text-align:right;">With Drone</th>

      <th style="padding:10px 12px; font-size:11px; font-weight:700; text-transform:uppercase;

                 letter-spacing:0.6px; color:#555; border-bottom:1px solid #d1d5db; text-align:left;">Basis</th>

    </tr>

  </thead>

  <tbody>

{rows_html}

    <tr style="background:#e6f4f1;">

      <td style="padding:10px 12px; font-size:14px; font-weight:700; color:#111; border-bottom:1px solid #d1d5db;">

        Apprehension Value Score

      </td>

      <td style="padding:10px 12px; color:#888; border-bottom:1px solid #d1d5db; text-align:right;">—</td>

      <td colspan="2" style="padding:10px 12px; font-size:18px; font-weight:800;

          color:{score_color}; border-bottom:1px solid #d1d5db;">

        {score_label} &nbsp;<span style="font-size:12px; font-weight:400; color:#888;">({score}/100 composite)</span>

      </td>

    </tr>

  </tbody>

</table>

</div>

<p style="font-size:10px; color:#aaa; margin:4px 0 28px 0;">

  Score weighted: 40% geographic coverage · 35% time saved vs patrol · 25% DFR dispatch rate.

  Arrest estimates are model projections; actual results vary by deployment, terrain, and incident type.

</p>



<p style="font-size:12px; font-weight:700; color:#555; text-transform:uppercase;

          letter-spacing:0.5px; margin:0 0 8px;">Top Call Types</p>

<div style="position:relative; height:{bar_height}px; margin-bottom:24px;">

  <canvas id="expTypeChart"></canvas>

</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>

<script>

(function(){{

  var typL={type_labels_js}, typV={type_vals_js};

  var hasTypes={has_types};

  if(hasTypes && typL.length) {{

    new Chart(document.getElementById('expTypeChart'), {{

      type:'bar',

      data:{{

        labels:typL,

        datasets:[{{data:typV,backgroundColor:'#00D2FF',borderRadius:3,borderSkipped:false}}]

      }},

      options:{{responsive:true,maintainAspectRatio:false,indexAxis:'y',

        plugins:{{legend:{{display:false}}}},

        scales:{{

          x:{{ticks:{{callback:function(v){{return v>=1000?Math.round(v/1000)+'k':v}}}}}},

          y:{{ticks:{{font:{{size:11}}}}}}

        }}

      }}

    }});

  }}

}})();

</script>

"""

    except Exception as e:

        print(f"[BRINC] _build_cad_charts_html failed: {e}\n{traceback.format_exc()}")

        return "<div style='color:#888;padding:20px;text-align:center;font-size:13px;'>Chart unavailable — data could not be rendered.</div>"









def _build_apprehension_table(df_calls, text_main, text_muted, card_bg, card_border, accent_color):

    """Compute and render the Drone Apprehension Impact Value table.



    Derived metrics use call volume, DFR dispatch rate, and coverage percentage

    stored in session state — no static placeholders.

    """

    if df_calls is None or df_calls.empty:

        return



    # ── Pull session values ───────────────────────────────────────────────────

    total_calls      = int(st.session_state.get('total_original_calls', len(df_calls)) or len(df_calls))

    dfr_rate         = float(st.session_state.get('dfr_rate', 25)) / 100.0   # fraction dispatched by drone

    calls_per_year   = _get_annualized_calls(total_calls)



    # Pursuit-eligible calls: incidents where a suspect is potentially fleeing

    # — conservatively 18% of all calls (PERF national average for patrol pursuits)

    pursuit_rate     = 0.18

    pursuit_calls    = round(calls_per_year * pursuit_rate)



    # Apprehension lift: drone raises locate-before-arrival from 18 % → 62 %

    # (+20 pp net apprehension rate lift per BRINC field deployments)

    baseline_arr_rate  = 0.34   # officer-only apprehension rate per pursuit incident

    drone_arr_rate     = 0.54   # with drone aerial ID + perimeter intel

    arr_lift_pp        = round((drone_arr_rate - baseline_arr_rate) * 100, 0)



    # Annual additional arrests from DFR-dispatched pursuit calls

    dfr_pursuit_calls   = round(pursuit_calls * dfr_rate)

    additional_arrests  = round(dfr_pursuit_calls * (drone_arr_rate - baseline_arr_rate))



    # Apprehension Value Score: composite of speed + coverage + thermal (0–100)

    coverage_pct  = float(st.session_state.get('calls_covered_perc', 70) or 70)

    time_saved    = float(st.session_state.get('avg_time_saved_min', 6) or 6)

    # Weighted: 40% coverage, 35% time saved (normalized to 10-min max), 25% DFR rate

    score = round(

        0.40 * min(coverage_pct, 100) +

        0.35 * min(time_saved / 10.0 * 100, 100) +

        0.25 * min(dfr_rate * 100 / 30.0 * 100, 100)

    )

    score = max(0, min(score, 100))

    if score >= 75:

        score_label = "🟢 HIGH"

        score_color = "#00D2FF"

    elif score >= 50:

        score_label = "🟡 MODERATE"

        score_color = "#EF9F27"

    else:

        score_label = "🔴 LOW"

        score_color = "#E24B4A"



    # ── HTML table ────────────────────────────────────────────────────────────

    row_style_a = f"background:{card_bg};"

    row_style_b = f"background:rgba(0,210,255,0.04);"

    th_style    = (f"padding:10px 14px; text-align:left; font-size:11px; font-weight:700; "

                   f"text-transform:uppercase; letter-spacing:0.6px; color:{text_muted}; "

                   f"border-bottom:1px solid {card_border};")

    td_l_style  = (f"padding:10px 14px; font-size:13px; color:{text_muted}; "

                   f"border-bottom:1px solid {card_border}; width:36%;")

    td_b_style  = (f"padding:10px 14px; font-size:13px; color:{text_main}; "

                   f"border-bottom:1px solid {card_border}; width:19%; text-align:right;")

    td_d_style  = (f"padding:10px 14px; font-size:13px; color:{accent_color}; font-weight:700; "

                   f"border-bottom:1px solid {card_border}; width:19%; text-align:right;")

    td_s_style  = (f"padding:10px 14px; font-size:11px; color:{text_muted}; "

                   f"border-bottom:1px solid {card_border}; width:26%;")



    rows = [

        ("row_a", "Average officer response time",

         "8 – 12 min", "2 – 4 min (DFR first on scene)",

         "BRINC field deployments; avg aerial ETA"),

        ("row_b", "Suspect located before officer arrival",

         "~18% of pursuits", "~62% of pursuits",

         "Drone situational awareness + thermal"),

        ("row_a", "Apprehension rate per pursuit incident",

         f"{int(baseline_arr_rate*100)}%", f"{int(drone_arr_rate*100)}%  (+{int(arr_lift_pp)} pp)",

         "Aerial ID, perimeter intel, real-time relay"),

        ("row_b", "Additional arrests per 100 pursuit calls",

         "—", f"+{int(arr_lift_pp)} apprehensions",

         "Net lift applied to DFR-covered incidents"),

        ("row_a", "Thermal imaging (nighttime pursuits)",

         "Unavailable", "100% of flight hours",

         "Eliminates blind foot searches in darkness"),

        ("row_b", "Perimeter containment established",

         "4 – 6 officers required", "Drone in < 90 sec",

         "Officers freed for contact; drone holds perimeter"),

        ("row_a", "DFR-dispatched pursuit calls / year",

         "—", f"{dfr_pursuit_calls:,}",

         f"{int(dfr_rate*100)}% DFR rate × {pursuit_calls:,} pursuit-eligible calls"),

        ("row_b", "Est. additional arrests / year",

         "—", f"+ {additional_arrests:,} arrests",

         "DFR pursuit calls × +20 pp apprehension lift"),

    ]



    table_html = f"""

<div style="margin-top:4px; margin-bottom:20px;">

  <p style="font-size:13px; font-weight:700; color:{text_main}; text-transform:uppercase;

            letter-spacing:0.6px; margin:0 0 10px 0;">🎯 Drone Apprehension Impact Value</p>

  <p style="font-size:12px; color:{text_muted}; margin:0 0 14px 0;">

    How drone deployment improves suspect apprehension — derived from your call volume,

    DFR dispatch rate, and coverage. Baseline figures from national law enforcement benchmarks.

  </p>

  <div style="overflow-x:auto; border-radius:8px; border:1px solid {card_border};">

  <table style="width:100%; border-collapse:collapse; font-family:inherit;">

    <thead>

      <tr style="background:rgba(0,210,255,0.08);">

        <th style="{th_style}">Factor</th>

        <th style="{th_style} text-align:right;">Without Drone</th>

        <th style="{th_style} text-align:right;">With Drone</th>

        <th style="{th_style}">Basis</th>

      </tr>

    </thead>

    <tbody>

"""

    for i, (variant, factor, base, drone, source) in enumerate(rows):

        bg = row_style_b if i % 2 else row_style_a

        table_html += f"""

      <tr style="{bg}">

        <td style="{td_l_style}">{factor}</td>

        <td style="{td_b_style}">{base}</td>

        <td style="{td_d_style}">{drone}</td>

        <td style="{td_s_style}">{source}</td>

      </tr>"""



    # Final composite score row

    table_html += f"""

      <tr style="background:rgba(0,210,255,0.10);">

        <td style="{td_l_style} font-weight:700; color:{text_main}; font-size:14px;">

          Apprehension Value Score

        </td>

        <td style="{td_b_style}">—</td>

        <td colspan="2" style="padding:10px 14px; font-size:16px; font-weight:800;

            color:{score_color}; border-bottom:1px solid {card_border};">

          {score_label} &nbsp;<span style="font-size:12px; font-weight:400;

          color:{text_muted};">({score}/100 composite)</span>

        </td>

      </tr>

    </tbody>

  </table>

  </div>

  <p style="font-size:10px; color:{text_muted}; margin:6px 0 0 0;">

    Score weighted: 40% geographic coverage · 35% time saved vs patrol · 25% DFR dispatch rate.

    Arrest estimates are model projections — actual results depend on deployment, terrain, and incident type.

  </p>

</div>

"""

    # Wrap in a full HTML document so components.html renders the table faithfully.

    # st.markdown strips <table> tags in recent Streamlit versions.

    full_html = f"""<!DOCTYPE html>

<html>

<head>

<meta charset="utf-8">

<style>

  body {{

    margin: 0; padding: 0;

    background: transparent;

    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

  }}

</style>

</head>

<body>

{table_html}

</body>

</html>"""

    # Height: header ~60px + description ~40px + 9 rows × 44px + score row 54px + footnote 30px

    _table_height = 60 + 40 + (len(rows) * 44) + 54 + 44 + 30

    import streamlit.components.v1 as _comp

    _comp.html(full_html, height=_table_height, scrolling=False)









def _build_cad_charts(df_calls, text_main, text_muted, card_bg, card_border, accent_color):

    """Render apprehension impact table + top call types chart."""

    import plotly.graph_objects as go



    if df_calls is None or df_calls.empty:

        return



    layout_base = dict(

        paper_bgcolor='rgba(0,0,0,0)',

        plot_bgcolor='rgba(0,0,0,0)',

        font=dict(color=text_muted, size=11),

        margin=dict(l=10, r=10, t=32, b=10),

        hoverlabel=dict(bgcolor=card_bg, font_size=12, font_color=text_main, bordercolor=accent_color),

    )

    grid_color = card_border



    # ── Apprehension Impact Value table (replaces priority donut + density curve) ──

    _build_apprehension_table(df_calls, text_main, text_muted, card_bg, card_border, accent_color)



    # ── Top event types (horizontal bar) ──────────────────────────────────────

    desc_col = None

    for _c in ['call_type_desc','agencyeventtypecodedesc','eventdesc','calldesc','description','nature','event_desc']:

        if _c in df_calls.columns and df_calls[_c].dropna().nunique() > 2:

            desc_col = _c

            break



    if desc_col:

        top_types = df_calls[desc_col].dropna().str.strip().value_counts().head(12)

        if not top_types.empty:

            fig_types = go.Figure(go.Bar(

                x=top_types.values, y=top_types.index,

                orientation='h',

                marker_color=accent_color,

                text=[f'{v:,}' for v in top_types.values],

                textposition='outside',

                hovertemplate='<b>%{y}</b><br>%{x:,} calls<extra></extra>',

            ))

            fig_types.update_layout(**layout_base,

                height=max(280, len(top_types) * 30 + 60),

                title=dict(text='Top Call Types', font=dict(size=13, color=text_main), x=0),

                xaxis=dict(showgrid=True, gridcolor=grid_color, title='Calls'),

                yaxis=dict(showgrid=False, autorange='reversed'),

                showlegend=False,

            )

            _state_slug = st.session_state.get('active_state', '') if hasattr(st, 'session_state') else ''
            _report_chart_key = (
                f"report_top_call_types_{_state_slug}_{len(top_types)}_{int(top_types.sum())}"
                if len(top_types) > 0
                else f"report_top_call_types_{_state_slug}_empty"
            )
            st.plotly_chart(
                fig_types,
                width="stretch",
                config={'displayModeBar': False},
                key=_report_chart_key,
            )











def _safe_df_to_records(df):

    """Safely serialize a DataFrame to a JSON-safe list of records.

    Returns an empty list if df is None, empty, or serialization fails."""

    if df is None:

        return []

    try:

        if hasattr(df, 'empty') and df.empty:

            return []

        return json.loads(df.replace({float('nan'): None}).to_json(orient='records'))

    except Exception:

        try:

            return json.loads(df.fillna('').to_json(orient='records'))

        except Exception:

            return []









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







def _build_unit_cards_html(active_drones, text_main, text_muted, card_bg, card_border, card_title, accent_color, columns_per_row=2, simple=False, deflection_rate=0.25, dfr_dispatch_rate=0.12, show_financials=True):

    if not active_drones:

        return ""

    # Per-type daily airtime budgets derived from CONFIG duty cycles:

    #   Guardian: 60 min flight + 3 min swap → (24*60/63)*60 = 1371.4 min = 22.86 hr

    #   Responder: 30 min flight + 30 min recharge → 720 min = 12.0 hr

    _GUARDIAN_DAILY_MINS  = CONFIG["GUARDIAN_DAILY_FLIGHT_MIN"]   # ~1371.4

    _GUARDIAN_DAILY_HOURS = CONFIG["GUARDIAN_PATROL_HOURS"]        # ~22.86

    _RESPONDER_DAILY_MINS  = CONFIG["RESPONDER_DAILY_FLIGHT_MIN"]  # 720

    _RESPONDER_DAILY_HOURS = CONFIG["RESPONDER_PATROL_HOURS"]      # 12.0

    columns_per_row = max(1, int(columns_per_row))



    # Specialty-response values are independent from Annual Capacity Value.

    # They are modeled per station from that station's own calls-in-range and

    # resulting drone flights, not allocated as a share of fleet totals.

    _THERMAL_RATE = float(CONFIG.get("THERMAL_DEFAULT_APPLICABLE_RATE", 0.12) or 0)

    _THERMAL_PER_CALL = float(CONFIG.get("THERMAL_SAVINGS_PER_CALL", 38) or 0)

    _K9_RATE = float(CONFIG.get("K9_DEFAULT_APPLICABLE_RATE", 0.03) or 0)

    _K9_PER_CALL = float(CONFIG.get("K9_SAVINGS_PER_CALL", 155) or 0)

    _FIRE_RATE = float(CONFIG.get("FIRE_DEFAULT_APPLICABLE_RATE", 0.05) or 0)

    _FIRE_PER_CALL = float(CONFIG.get("FIRE_SAVINGS_PER_CALL", 450) or 0)



    cards_html = []

    for d in active_drones:

        short_name  = format_3_lines(d["name"])

        d_color     = d["color"]

        d_type      = d["type"]

        d_step      = d["deploy_step"]

        d_savings   = d["annual_savings"]

        d_flights   = d["marginal_flights"]

        d_shared    = d["shared_flights"]

        # Resolved/day = total station flights (exclusive + shared) × deflection rate.

        d_deflected  = (d_flights + d_shared) * deflection_rate

        d_time      = d["avg_time_min"]

        d_faa       = d["faa_ceiling"]

        d_airport   = d["nearest_airport"]

        d_cost      = d["cost"]

        d_be        = d["be_text"]

        d_lat       = d["lat"]

        d_lon       = d["lon"]

        d_address   = get_address_from_latlon(d_lat, d_lon)
        gmaps_url   = f"https://www.google.com/maps/search/?api=1&query={d_lat},{d_lon}"
        coord_label = f"{d_lat:.5f}, {d_lon:.5f}"


        # Pick duty-cycle values for this drone type

        is_guardian = (d_type == "GUARDIAN")

        max_patrol_mins  = _GUARDIAN_DAILY_MINS  if is_guardian else _RESPONDER_DAILY_MINS

        max_patrol_hours = _GUARDIAN_DAILY_HOURS if is_guardian else _RESPONDER_DAILY_HOURS
        max_single_flight = CONFIG["GUARDIAN_FLIGHT_MIN"] if is_guardian else CONFIG["RESPONDER_FLIGHT_MIN"]
        d_alt_time = float(d.get("alt_avg_time_min", 0) or 0)
        guardian_time = d_time if is_guardian else d_alt_time
        responder_time = d_alt_time if is_guardian else d_time
        travel_delta_min = abs(guardian_time - responder_time)
        if guardian_time > 0 and responder_time > 0 and travel_delta_min > 0.05:
            if guardian_time <= responder_time:
                travel_compare_text = f"Guardian faster by {travel_delta_min:.1f} min"
                travel_color = "#2ecc71"
            else:
                travel_compare_text = f"Responder faster by {travel_delta_min:.1f} min"
                travel_color = "#F0B429"
            travel_detail_text = f"Guardian {guardian_time:.1f} min vs Responder {responder_time:.1f} min"
        else:
            travel_compare_text = "Arrival time"
            travel_detail_text = f"Guardian {guardian_time:.1f} min vs Responder {responder_time:.1f} min"
            travel_color = "#00D2FF"



        # Uptime tooltip: show the duty-cycle breakdown for Guardians

        if is_guardian:

            _g_fl  = CONFIG["GUARDIAN_FLIGHT_MIN"]

            _g_ch  = CONFIG["GUARDIAN_CHARGE_MIN"]

            _g_cyc = _g_fl + _g_ch

            _cycles_per_day = (24 * 60) / _g_cyc

            uptime_tooltip = (

                f"{_g_fl}min flight + {_g_ch}min charge = {_g_cyc}min cycle · "

                f"{_cycles_per_day:.1f} cycles/day · "

                f"{max_patrol_hours:.2f}hr airtime"

            )

        else:

            uptime_tooltip = f"{max_patrol_hours}hr patrol shift"



        total_daily_flights = d_flights + d_shared

        d_zone_calls = float(d.get("zone_calls_annual", 0) or 0)

        d_calls_in_range_yr = float(d.get("calls_in_range_yr", d_zone_calls) or 0)
        d_calls_in_range_day = float(d.get("calls_in_range_day", d_calls_in_range_yr / 365.0) or 0)

        d_dispatchable_calls_yr = float(d.get("dispatchable_calls_yr", 0) or 0)

        d_weighted_dispatchable_calls_yr = float(d.get("weighted_dispatchable_calls_yr", d_dispatchable_calls_yr) or 0)

        d_calls_handle_yr = float(d.get("handled_calls_yr", d.get("calls_handle_yr", 0)) or 0)

        d_calls_unanswered_yr = float(d.get("calls_unanswered_yr", 0) or 0)

        d_assigned_calls_day = float(d.get('assigned_calls_day', 0) or 0)

        d_assigned_flights_day = float(d.get('assigned_flights_day', d_flights) or 0)

        d_assigned_flights_annual = float(d.get('assigned_flights_yr', d_assigned_flights_day * 365.0) or 0)

        d_zone_flights_day = float(d.get('zone_flights', d_flights + d_shared) or 0)

        d_zone_flights_annual = float(d.get("zone_flights_annual", d_zone_flights_day * 365.0) or 0)

        # Cap thermal/K9 base to physically serviceable flights (max_flights_cap * 365)

        # zone_flights_annual is raw DEMANDED flights — thermal/K9 assists can only

        # happen on flights actually flown within the 10-min scene-floor capacity.

        _serviceable_annual = float(d.get("max_flights_cap", 0) or 0) * 365.0

        _flight_base = min(d_zone_flights_annual, _serviceable_annual) if _serviceable_annual > 0 else d_zone_flights_annual

        # Further cap: assists cannot exceed total zone calls in range

        _flight_base = min(_flight_base, d_zone_calls) if d_zone_calls > 0 else _flight_base

        d_thermal_calls = _flight_base * _THERMAL_RATE

        d_k9_calls      = _flight_base * _K9_RATE

        d_fire_calls    = _flight_base * _FIRE_RATE

        d_thermal = d_thermal_calls * _THERMAL_PER_CALL

        d_k9      = d_k9_calls      * _K9_PER_CALL

        d_fire    = d_fire_calls    * _FIRE_PER_CALL



        # Concurrency / value breakdown

        d_util         = d.get('utilization', 0)

        d_true_util    = d.get('true_util', d_util)

        d_on_scene     = d.get('on_scene_min', 99.0)

        d_max_cap      = float(d.get('max_flights_cap', 0) or 0)

        d_has_deficit  = d.get('has_deficit', False)

        d_deficit_f    = d.get('deficit_flights', 0)

        d_unserv_day   = d.get('unserv_calls_day', 0)

        d_unserv_yr    = d.get('unserv_calls_yr', 0)

        d_total_flights_possible_yr = max(0.0, d_max_cap * 365.0)

        d_total_uncovered_flights_yr = max(0.0, float(d_zone_flights_annual or 0) - d_total_flights_possible_yr)

        d_extra_same   = d.get('extra_same', 0)

        d_extra_alt    = d.get('extra_alt', 0)

        d_extra_same_capex = d.get('extra_same_capex', 0)

        d_extra_alt_capex  = d.get('extra_alt_capex', 0)

        d_same_lbl     = d.get('same_type_label', d_type.title())

        d_alt_lbl      = d.get('alt_type_label', 'Guardian' if d_type == 'RESPONDER' else 'Responder')

        d_blocked      = float(d.get('blocked_per_day', 0) or 0)

        d_base_annual  = d.get('base_annual', d_savings)

        d_conc_annual  = d.get('concurrent_annual', 0)

        d_best         = d.get('best_case_annual', d_savings)

        d_best_be      = d.get('best_be_text', d_be)

        d_display_annual = float(d.get('annual_savings', d_best) or 0)

        d_display_monthly = d_display_annual / 12.0

        d_display_be = f"{d_cost/d_display_monthly:.1f} MO" if d_display_monthly > 0 else "N/A"

        d_serviceable_day = min(d_assigned_flights_day, d_max_cap) if d_max_cap > 0 else d_assigned_flights_day

        d_actual_resolved_day = float(d.get('handled_calls_day', 0) or 0) * deflection_rate

        d_capacity_limited = bool(

            d_has_deficit

            or d_true_util >= 0.999

            or d_on_scene <= 10.01

            or (d_max_cap > 0 and d_assigned_flights_day > d_max_cap + 0.01)

        )

        util_pct = "100%" if d_capacity_limited else f"{d_true_util*100:.1f}%"

        util_color = "#F0B429" if d_capacity_limited else "#dc3545" if d_true_util > 0.75 else "#F0B429" if d_true_util > 0.4 else "#2ecc71"

        # On-scene time color coding

        if d_capacity_limited or d_on_scene < 10.0:

            scene_color = "#F0B429" if d_capacity_limited else "#dc3545"

        elif d_on_scene < 20.0:

            scene_color = "#F0B429"

        else:

            scene_color = "#2ecc71"



        _display_flights_day = d_max_cap if d_max_cap > 0 else d_zone_flights_day

        _display_flights_annual = d_total_flights_possible_yr if d_total_flights_possible_yr > 0 else d_zone_flights_annual

        _display_flights_label = "calls/day capacity" if d_max_cap > 0 else "zone flights/day"

        patrol_time_line = ""

        if _display_flights_day > 0:

            raw_mins_per_flight = max_patrol_mins / max(_display_flights_day, 0.001)

            mins_per_flight = min(raw_mins_per_flight, max_single_flight)

            capped = raw_mins_per_flight > max_single_flight

            if d_capacity_limited:

                patrol_color = "#F0B429"

                flights_label = f"{d_max_cap:.1f} max flights/day"

                annual_label = f"({d_total_flights_possible_yr:,.0f}/yr)"

                mins_label = "10.0 min minimum on-scene"

            else:

                patrol_color = "#F0B429" if mins_per_flight < 15 else "#2ecc71" if mins_per_flight >= max_single_flight * 0.9 else "#00D2FF"

                flights_label = f"{_display_flights_day:.1f} {_display_flights_label}"

                annual_label = f"({_display_flights_annual:,.0f}/yr)"

                cap_note = f" (max {max_single_flight}min)" if capped else ""

                mins_label = f"{mins_per_flight:.1f} min/flight{cap_note}"

            patrol_time_line = (

                f'<div style="font-size:0.65rem; color:{text_muted}; text-align:right; line-height:1.2;" '

                f'title="{uptime_tooltip}">'

                f'<span style="font-weight:800; color:{patrol_color};">{flights_label}</span> '

                f'<span style="font-weight:400; color:{text_muted}; font-size:0.60rem;">{annual_label}</span><br>'

                f'<span style="font-weight:600; color:{patrol_color};">{mins_label}</span></div>'

            )
            patrol_time_line += (
                f'<div style="margin-top:4px;padding-top:4px;border-top:1px dashed rgba(255,255,255,0.08);">'
                f'<div style="font-size:0.58rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;text-align:right;">Arrival advantage'
                f'<span class="tip" data-tip="Average station-to-call travel time compared between Guardian and Responder at the same station. The faster unit arrives first.">?</span></div>'
                f'<div style="font-size:0.78rem;font-weight:800;color:{travel_color};text-align:right;line-height:1.1;">{travel_compare_text}</div>'
                f'<div style="font-size:0.58rem;color:{text_muted};text-align:right;margin-top:1px;">{travel_detail_text}</div>'
                f'</div>'
            )

        if d_calls_unanswered_yr > 0.1:

            status_text = "Capacity"

            status_bg = "rgba(240,180,41,0.12)"

            status_border = "rgba(240,180,41,0.40)"

            status_color = "#F0B429"

        else:

            status_text = "Within Capacity"

            status_bg = "rgba(46,204,113,0.10)"

            status_border = "rgba(46,204,113,0.30)"

            status_color = "#2ecc71"

        has_concurrent = d_shared > 0.1 and d_conc_annual > 0

        if has_concurrent:

            _excl_str = f"${d_base_annual:,.0f} exclusive"

            _conc_str = f"+ ${d_conc_annual:,.0f} concurrent"

        else:

            _excl_str = "exclusive zone coverage"

            _conc_str = ""



        # ── DEFICIT FOOTER (compact strip at card bottom) ─────────────────────────────

        _sc_fmt = f"${d_extra_same_capex:,}" if d_capacity_limited else ""

        _ac_fmt = f"${d_extra_alt_capex:,}" if d_capacity_limited else ""



        # ── Pre-build financial HTML blocks (conditionally included) ─────────

        _specialty_total = d_thermal + d_k9 + d_fire



        # Simple card financial blocks

        _sim_fin_hero = (

            f'<div style="display:grid;grid-template-columns:1fr;gap:6px;margin-bottom:6px;">'

            f'  <div style="background:rgba(0,210,255,0.07);border:1px solid rgba(0,210,255,0.25);border-radius:6px;padding:8px 10px;">'

            f'    <div style="font-size:0.58rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;margin-bottom:3px;">Annual Capacity Value<span class="tip" data-tip="Estimated annual savings from calls this drone resolves without sending a ground unit. Capped at physical flight capacity.">?</span></div>'

            f'    <div style="font-size:1.55rem;font-weight:900;color:{accent_color};line-height:1.05;">${d_display_annual:,.0f}</div>'

            f'    <div style="font-size:0.60rem;color:{text_muted};margin-top:3px;">handled-call annual value</div>'

            f'  </div>'

            f'  <div style="background:{status_bg};border:1px solid {status_border};border-radius:6px;padding:8px 10px;">'

            f'    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap;">'

            f'      <div>'

            f'        <div style="font-size:0.58rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;margin-bottom:3px;">Attributed Dispatchable Calls<span class="tip" data-tip="Overlap-shared annual dispatchable demand credited to this unit. This is the demand share used for utilization and value calculations.">?</span></div>'

            f'        <div style="font-size:1.30rem;font-weight:900;color:{card_title};line-height:1.05;">{int(d_weighted_dispatchable_calls_yr):,}</div>'

            f'      </div>'

            f'      <div style="min-width:138px;">'

            f'        <div style="background:rgba(255,255,255,0.04);border:1px solid {card_border};border-radius:6px;padding:6px 8px;">'

            f'          <div style="font-size:0.56rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;margin-bottom:3px;">Capacity<span class="tip" data-tip="This unit is at its modeled call-handling ceiling for the current profile.">?</span></div>'

            f'          <div style="font-size:0.70rem;color:{text_muted};margin-top:2px;">{d_max_cap:.1f} calls/day capacity ({int(d_total_flights_possible_yr):,}/yr)</div>'

            f'          <div style="font-size:0.70rem;color:{text_muted};margin-top:2px;">{mins_per_flight:.1f} min/flight</div>'

            f'        </div>'

            f'        <div style="background:rgba(255,255,255,0.04);border:1px solid {card_border};border-radius:6px;padding:6px 8px;margin-top:6px;">'

            f'          <div style="font-size:0.56rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;margin-bottom:3px;">Arrival advantage<span class="tip" data-tip="Average station-to-call travel time compared between Guardian and Responder at the same station. The faster unit arrives first.">?</span></div>'

            f'          <div style="font-size:0.82rem;font-weight:900;color:{travel_color};line-height:1.1;">{travel_compare_text}</div>'

            f'          <div style="font-size:0.56rem;color:{text_muted};margin-top:2px;">{travel_detail_text}</div>'

            f'        </div>'

            f'      </div>'

            f'    </div>'

            f'  </div>'

            f'</div>'

        ) if show_financials else ''



        _sim_fin_breakeven_cell = (

            f'<div style="background:rgba(0,210,255,0.07);border:1px solid rgba(0,210,255,0.18);border-radius:5px;padding:6px 8px;text-align:center;">'

            f'<div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Break-Even<span class="tip" data-tip="Months to recover the unit CapEx from annual capacity savings at current DFR and deflection rates.">?</span></div>'

            f'<div style="font-size:0.95rem;font-weight:900;color:{accent_color};">{d_display_be}</div>'

            f'</div>'

        ) if show_financials else (

            f'<div style="background:rgba(255,255,255,0.04);border:1px solid {card_border};border-radius:5px;padding:6px 8px;text-align:center;">'

            f'<div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Utilization<span class="tip" data-tip="Attributed dispatchable demand as a percent of this unit''s practical call-handling capacity. A value near 100% means the drone is effectively maxed out.">?</span></div>'

            f'<div style="font-size:0.95rem;font-weight:900;color:{util_color};">{util_pct}</div>'

            f'</div>'

        )



        _sim_fin_specialty = (

            f'<div style="background:rgba(251,191,36,0.06);border:1px solid rgba(251,191,36,0.18);border-radius:5px;padding:5px 10px;display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'

            f'<span style="font-size:0.60rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">🔥🐕🚒 Specialty Value<span class="tip" data-tip="Combined value from thermal imaging assists (12% of flights), K-9 replacement (3% of flights), and fire scene support (5% of flights). Separate from Annual Capacity Value.">?</span></span>'

            f'<span style="font-size:0.85rem;font-weight:800;color:#fbbf24;">${_specialty_total:,.0f}/yr</span>'

            f'</div>'

        ) if show_financials else ''



        _sim_fin_capex = (

            f'<div style="display:flex;justify-content:space-between;align-items:center;padding-top:5px;border-top:1px solid {card_border};font-size:0.65rem;">'

            f'<span style="color:{text_muted};">CapEx<span class="tip" data-tip="One-time hardware cost for this unit. Responder: ${CONFIG["RESPONDER_COST"]:,}. Guardian: ${CONFIG["GUARDIAN_COST"]:,}.">?</span></span>'

            f'<span style="font-weight:700;color:{card_title};">${d_cost:,.0f}</span>'

            f'</div>'

        ) if show_financials else ''



        # Full card financial blocks

        _full_fin_annual_cap = (

            f'<div style="display:grid;grid-template-columns:1fr;gap:6px;margin-bottom:6px;">'

            f'  <div style="background:rgba(0,210,255,0.07); border:1px solid rgba(0,210,255,0.20); border-radius:6px; padding:8px 10px;">'

            f'    <div style="font-size:0.68rem; color:{text_muted}; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:2px;">Annual Capacity Value<span class="tip" data-tip="Estimated annual savings from calls this drone resolves without sending a ground unit. Capped at physical flight capacity.">?</span></div>'

            f'    <div style="font-size:1.45rem; font-weight:900; color:{accent_color}; line-height:1.05;">${d_display_annual:,.0f}</div>'

            f'    <div style="font-size:0.61rem; color:{text_muted}; margin-top:3px;">handled-call annual value</div>'

            f'    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:7px;">'

            f'      <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:6px; padding:6px 8px;">'

            f'        <div style="font-size:0.58rem; color:{text_muted}; text-transform:uppercase; letter-spacing:0.35px;">Exclusive Value<span class="tip" data-tip="Annual value from calls only this unit is credited with handling on its own, excluding shared overlap upside.">?</span></div>'

            f'        <div style="font-size:0.85rem; font-weight:800; color:{accent_color};">${d_base_annual:,.0f}</div>'

            f'      </div>'

            f'      <div style="background:rgba(57,255,20,0.05); border:1px solid rgba(57,255,20,0.16); border-radius:6px; padding:6px 8px;">'

            f'        <div style="font-size:0.58rem; color:{text_muted}; text-transform:uppercase; letter-spacing:0.35px;">Concurrent Value<span class="tip" data-tip="Additional annual value from shared overlap coverage when this unit contributes beyond its exclusive zone.">?</span></div>'

            f'        <div style="font-size:0.85rem; font-weight:800; color:#39FF14;">${d_conc_annual:,.0f}</div>'

            f'      </div>'

            f'    </div>'

            f'  </div>'

            f'  <div style="background:{status_bg}; border:1px solid {status_border}; border-radius:6px; padding:8px 10px;">'

            f'    <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px; flex-wrap:wrap;">'

            f'      <div>'

            f'        <div style="font-size:0.68rem; color:{text_muted}; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:2px;">Attributed Dispatchable Calls<span class="tip" data-tip="Overlap-shared annual dispatchable demand credited to this unit. This is the demand share used for utilization and value calculations.">?</span></div>'

            f'        <div style="font-size:1.35rem; font-weight:900; color:{card_title}; line-height:1.05;">{int(d_weighted_dispatchable_calls_yr):,}</div>'

            f'      </div>'

            f'      <div style="min-width:138px;">'

            f'        <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:6px; padding:6px 8px;">'

            f'          <div style="font-size:0.56rem; color:{text_muted}; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:3px;">Capacity<span class="tip" data-tip="This unit is at its modeled call-handling ceiling for the current profile.">?</span></div>'

            f'          <div style="font-size:0.72rem; font-weight:800; color:{card_title}; line-height:1.2; margin-top:3px;">{int(d_calls_unanswered_yr):,} calls unanswered</div>'

            f'          <div style="font-size:0.70rem; color:{text_muted}; margin-top:2px;">{d_max_cap:.1f} calls/day capacity ({int(d_total_flights_possible_yr):,}/yr)</div>'

            f'          <div style="font-size:0.70rem; color:{text_muted}; margin-top:2px;">{mins_per_flight:.1f} min/flight</div>'

            f'        </div>'

            f'        <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:6px; padding:6px 8px; margin-top:6px;">'

            f'          <div style="font-size:0.56rem; color:{text_muted}; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:3px;">Arrival advantage<span class="tip" data-tip="Average station-to-call travel time compared between Guardian and Responder at the same station. The faster unit arrives first.">?</span></div>'

            f'          <div style="font-size:0.82rem; font-weight:900; color:{travel_color}; line-height:1.1;">{travel_compare_text}</div>'

            f'          <div style="font-size:0.56rem; color:{text_muted}; margin-top:2px;">{travel_detail_text}</div>'

            f'        </div>'

            f'      </div>'

            f'    </div>'

            f'  </div>'

            f'</div>'

        ) if show_financials else ''



        _full_fin_value_breakdown = (

            f'<div style="border:1px solid rgba(57,255,20,0.18); border-radius:6px; padding:6px 10px; margin-bottom:8px; background:rgba(57,255,20,0.04);">'

            f'  <div style="font-size:0.60rem; color:{text_muted}; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:4px;">Value Breakdown<span class="tip" data-tip="EXCLUSIVE: savings from calls only this drone can reach. CONCURRENT: savings from shared-zone calls captured only when the partner drone is busy.">?</span></div>'

            f'  <div style="display:grid; grid-template-columns:1fr auto 1fr; gap:4px; align-items:center; margin-bottom:4px;">'

            f'    <div style="text-align:center;">'

            f'      <div style="color:{accent_color}; font-weight:700; font-size:0.78rem;">${d_base_annual:,.0f}</div>'

            f'      <div style="color:{text_muted}; font-size:0.63rem;">exclusive<span class="tip" data-tip="Savings credited only to this unit''s non-shared zone coverage.">?</span></div>'

            f'    </div>'

            f'    <div style="color:{text_muted}; font-size:0.75rem; opacity:0.5; text-align:center;">+</div>'

            f'    <div style="text-align:center;">'

            f'      <div style="color:#39FF14; font-weight:700; font-size:0.78rem;">${d_conc_annual:,.0f}</div>'

            f'      <div style="color:{text_muted}; font-size:0.63rem;">concurrent<span class="tip" data-tip="Savings from overlap coverage attributed to this unit when shared demand is reconciled across active drones.">?</span></div>'

            f'    </div>'

            f'  </div>'

            f'  <div style="font-size:0.65rem; color:{text_muted}; opacity:0.8; border-top:1px dashed rgba(255,255,255,0.1); padding-top:4px; text-align:center;">{util_pct} utilization{"  ·  ⚠️ maxed capacity" if d_capacity_limited else ""} · ROI {d_best_be}</div>'

            f'</div>'

        ) if show_financials else ''



        _full_fin_capex_roi = (

            f'<div style="border-top:1px solid {card_border}; padding-top:6px; display:grid; grid-template-columns:1fr 1fr; gap:4px 8px; font-size:0.68rem; margin-bottom:8px;">'

            f'  <div style="color:{text_muted};">CapEx<span class="tip" data-tip="One-time hardware cost for this unit. Responder: ${CONFIG["RESPONDER_COST"]:,}. Guardian: ${CONFIG["GUARDIAN_COST"]:,}.">?</span></div>'

            f'  <div style="text-align:right; font-weight:700; color:{card_title};">${d_cost:,.0f}</div>'

            f'  <div style="color:{text_muted};">Base ROI<span class="tip" data-tip="Months to recover unit CapEx from exclusive-zone savings alone at current DFR and deflection rates.">?</span></div>'

            f'  <div style="text-align:right; font-weight:800; color:{accent_color};">{d_be}</div>'

            f'</div>'

        ) if show_financials else ''



        # ── SIMPLE CARD (toggled from Display Options) ───────────────────────

        if simple:

            _pin_badge = (

                f'<span style="font-size:0.55rem;background:rgba(255,215,0,0.15);color:#FFD700;border:1px solid rgba(255,215,0,0.4);border-radius:3px;padding:1px 5px;margin-left:4px;">🔒 Guardian</span>'

                if (d.get("pinned") and d_type == "GUARDIAN") else

                f'<span style="font-size:0.55rem;background:rgba(0,210,255,0.15);color:#00D2FF;border:1px solid rgba(0,210,255,0.4);border-radius:3px;padding:1px 5px;margin-left:4px;">🔒 Responder</span>'

                if (d.get("pinned") and d_type == "RESPONDER") else ""

            )

            _cap_strip = (

                f'<div style="display:flex;align-items:center;gap:5px;margin-top:6px;padding-top:5px;border-top:1px solid rgba(220,53,69,0.3);">'

                f'<span style="font-size:0.60rem;color:#F0B429;font-weight:700;">⚠️ Maxed capacity</span>'

                f'<span style="font-size:0.59rem;color:{text_muted};">· {d_unserv_day:.0f} calls/day unserviceable</span></div>'

                if d_capacity_limited else

                f'<div style="display:flex;align-items:center;gap:5px;margin-top:6px;padding-top:5px;border-top:1px solid rgba(34,197,94,0.2);">'

                f'<span style="font-size:0.60rem;color:#2ecc71;font-weight:700;">✓ Within capacity</span>'

                f'<span style="font-size:0.59rem;color:{text_muted};">· {d_on_scene:.1f} min on-scene</span></div>'

            )

            cards_html.append(f'''
<div class="unit-card" style="background:{card_bg};border:1px solid {"#F0B429" if d_capacity_limited else card_border};border-top:3px solid {d_color};border-radius:8px;padding:10px 12px;box-sizing:border-box;">
  <div style="display:flex; align-items:baseline; gap:5px; overflow:hidden;">
    <span style="font-weight:700; font-size:0.78rem; color:{card_title}; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1; min-width:0;">{"🔒 " if d.get("pinned") else ""}{d["name"]}</span>
    <span style="font-size:0.58rem; color:#666; text-transform:uppercase; letter-spacing:0.3px; white-space:nowrap; flex-shrink:0;">{d_type} · #{d_step}</span><span style="font-size:0.56rem;color:{status_color};background:{status_bg};border:1px solid {status_border};border-radius:999px;padding:2px 7px;font-weight:700;white-space:nowrap;">{status_text}</span>
  </div>
  <div style="font-size:0.65rem; margin-top:1px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
    <a href="{gmaps_url}" target="_blank" style="color:{accent_color}; text-decoration:none; font-weight:500; opacity:0.85;">{coord_label} ↗</a>
  </div>
  {_sim_fin_hero}
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:6px;">
    <div style="background:rgba(255,255,255,0.04);border:1px solid {card_border};border-radius:5px;padding:6px 8px;text-align:center;">
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Raw Calls In Range<span class="tip" data-tip="Total annual calls inside this station's coverage area before dispatch-rate filtering.">?</span></div>
      <div style="font-size:0.88rem;font-weight:800;color:{card_title};">{int(d_calls_in_range_yr):,}</div>
    </div>
    <div style="background:rgba(255,255,255,0.04);border:1px solid {card_border};border-radius:5px;padding:6px 8px;text-align:center;">
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Dispatchable Calls<span class="tip" data-tip="Raw calls in range multiplied by the drone dispatch rate. This is total drone demand inside the unit's physical coverage area before overlap sharing.">?</span></div>
      <div style="font-size:0.88rem;font-weight:800;color:{card_title};">{int(d_dispatchable_calls_yr):,}</div>
    </div>
    <div style="background:{"rgba(220,53,69,0.08)" if d_calls_unanswered_yr > 0.1 else "rgba(255,255,255,0.04)"};border:1px solid {"#dc3545" if d_calls_unanswered_yr > 0.1 else card_border};border-radius:5px;padding:6px 8px;text-align:center;">
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Calls Unanswered<span class="tip" data-tip="Raw in-range calls that remain unhandled after the station's physical time limit is applied.">?</span></div>
      <div style="font-size:0.88rem;font-weight:800;color:{"#dc3545" if d_calls_unanswered_yr > 0.1 else card_title};">{int(d_calls_unanswered_yr):,}</div>
    </div>
    <div style="background:{"rgba(240,180,41,0.08)" if d_capacity_limited else "rgba(255,255,255,0.04)"};border:1px solid {"#F0B429" if d_capacity_limited else card_border};border-radius:5px;padding:6px 8px;text-align:center;">
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Utilization<span class="tip" data-tip="Dispatchable calls in range as a percent of this unit's daily call-handling capacity using the 10-minute on-scene floor model. If any dispatchable calls are unanswered, utilization is shown as 100%.">?</span></div>
      <div style="font-size:0.88rem;font-weight:800;color:{util_color};">{util_pct}</div>
    </div>
    <div style="background:rgba(255,255,255,0.05);border:1px solid {card_border};border-radius:5px;padding:6px 8px;text-align:center;">
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Avg Travel<span class="tip" data-tip="Average travel time from this station to incidents in its zone.">?</span></div>
      <div style="font-size:0.95rem;font-weight:900;color:{card_title};">{d_time:.1f} min</div>
    </div>
    <div style="background:rgba(255,255,255,0.04);border:1px solid {card_border};border-radius:5px;padding:6px 8px;text-align:center;">
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Attributed Dispatchable Calls<span class="tip" data-tip="Overlap-shared annual dispatchable demand credited to this unit.">?</span></div>
      <div style="font-size:0.88rem;font-weight:800;color:{card_title};">{int(d_weighted_dispatchable_calls_yr):,}</div>
    </div>
    <div style="background:rgba(255,255,255,0.04);border:1px solid {card_border};border-radius:5px;padding:6px 8px;text-align:center;">
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Dispatches Avoided/day<span class="tip" data-tip="Calls per day closed without dispatching an officer: drone-handled calls times the deflection rate.">?</span></div>
      <div style="font-size:0.88rem;font-weight:800;color:{card_title};">{d_actual_resolved_day:.1f}</div>
    </div>
    {_sim_fin_breakeven_cell}
  </div>
  <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;margin-bottom:6px;padding:6px 8px;background:rgba(255,255,255,0.03);border:1px solid {card_border};border-radius:5px;">
    <div>
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Arrival advantage<span class="tip" data-tip="Average station-to-call travel time compared between Guardian and Responder at the same station. The faster unit arrives first.">?</span></div>
      <div style="font-size:0.88rem;font-weight:800;color:{travel_color};">{travel_compare_text}</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:0.57rem;color:{text_muted};text-transform:uppercase;letter-spacing:0.3px;">Same station</div>
      <div style="font-size:0.72rem;font-weight:700;color:{text_muted};line-height:1.2;">{travel_detail_text}</div>
    </div>
  </div>
  {_sim_fin_specialty}
  {_sim_fin_capex}
  {_cap_strip}
</div>''')

            continue



        cards_html.append(f'''
<div class="unit-card" style="background:{card_bg}; border:1px solid {"#F0B429" if d_capacity_limited else card_border}; border-top:3px solid {d_color}; border-radius:8px; padding:10px 12px; display:flex; flex-direction:column; box-sizing:border-box;">
  <!-- Header: single compact row -->
  <div style="margin-bottom:5px; flex-shrink:0;">
    <div style="display:flex; align-items:baseline; gap:5px; overflow:hidden;">
      <span style="font-weight:700; font-size:0.78rem; color:{card_title}; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1; min-width:0;">{"🔒 " if d.get("pinned") else ""}{d["name"]}</span>
      <span style="font-size:0.58rem; color:#666; text-transform:uppercase; letter-spacing:0.3px; white-space:nowrap; flex-shrink:0;">{d_type} · #{d_step}</span><span style="font-size:0.56rem;color:{status_color};background:{status_bg};border:1px solid {status_border};border-radius:999px;padding:2px 7px;font-weight:700;white-space:nowrap;">{status_text}</span>
    </div>
    <div style="font-size:0.65rem; margin-top:1px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
      <a href="{gmaps_url}" target="_blank" style="color:{accent_color}; text-decoration:none; font-weight:500; opacity:0.85;">{coord_label} ↗</a>
    </div>
  </div>
  {_full_fin_annual_cap}
  {_full_fin_value_breakdown}
  <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px; font-size:0.68rem; flex:1; margin-bottom:8px; align-content:start;">
    <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:5px; padding:5px 7px;">
      <div style="color:{text_muted}; font-size:0.60rem; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:1px;">Raw Calls In Range<span class="tip" data-tip="Total annual calls inside this station's coverage area before dispatch-rate filtering.">?</span></div>
      <div style="font-weight:800; color:{accent_color}; font-size:0.82rem;">{int(d_calls_in_range_yr):,}</div>
      <div style="font-size:0.59rem; color:{text_muted};">{d_calls_in_range_day:.1f}/day</div>
    </div>
    <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:5px; padding:5px 7px;">
      <div style="color:{text_muted}; font-size:0.60rem; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:1px;">Dispatchable Calls<span class="tip" data-tip="Raw calls in range multiplied by the drone dispatch rate. This is total drone demand inside the unit's physical coverage area before overlap sharing.">?</span></div>
      <div style="font-weight:800; color:{"#F0B429" if d_capacity_limited else "#2ecc71"}; font-size:0.82rem;">{int(d_dispatchable_calls_yr):,}</div>
      <div style="font-size:0.59rem; color:{text_muted};">{(d_dispatchable_calls_yr / 365.0):.1f}/day</div>
    </div>
    <div style="background:{"rgba(240,180,41,0.08)" if d_capacity_limited else "rgba(255,255,255,0.04)"}; border:1px solid {"#F0B429" if d_capacity_limited else card_border}; border-radius:5px; padding:5px 7px;">
      <div style="color:{text_muted}; font-size:0.60rem; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:1px;">Utilization<span class="tip" data-tip="Dispatchable calls in range as a percent of this unit's daily call-handling capacity using the 10-minute on-scene floor model. If any dispatchable calls are unanswered, utilization is shown as 100%.">?</span></div>
      <div style="font-weight:800; color:{util_color}; font-size:0.82rem;">{util_pct}</div>
    </div>
    <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:5px; padding:5px 7px;">
      <div style="color:{text_muted}; font-size:0.60rem; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:1px;">Avg Travel<span class="tip" data-tip="Pure travel time from this station to incidents in its zone.">?</span></div>
      <div style="font-weight:800; color:{card_title}; font-size:0.82rem;">{d_time:.1f} min</div>
    </div>
    <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:5px; padding:5px 7px;">
      <div style="color:{text_muted}; font-size:0.60rem; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:1px;">Attributed Dispatchable Calls<span class="tip" data-tip="Overlap-shared annual dispatchable demand credited to this unit.">?</span></div>
      <div style="font-weight:800; color:{card_title}; font-size:0.82rem;">{int(d_weighted_dispatchable_calls_yr):,}</div>
    </div>
    <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:5px; padding:5px 7px;">
      <div style="color:{text_muted}; font-size:0.60rem; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:1px;">Dispatches Avoided/day<span class="tip" data-tip="Calls per day closed without dispatching an officer: drone-handled calls times the deflection rate.">?</span></div>
      <div style="font-weight:800; color:{card_title}; font-size:0.82rem;">{d_actual_resolved_day:.1f}</div>
    </div>
    <div style="background:rgba(255,255,255,0.04); border:1px solid {card_border}; border-radius:5px; padding:5px 7px; text-align:center;">
      <div style="color:{text_muted}; font-size:0.60rem; text-transform:uppercase; letter-spacing:0.3px; margin-bottom:1px;">Break-Even<span class="tip" data-tip="Months to recover the unit CapEx from annual capacity savings at current DFR and deflection rates.">?</span></div>
      <div style="font-weight:800; color:{accent_color}; font-size:0.82rem;">{d_best_be}</div>
    </div>
  </div>
  {_full_fin_capex_roi}
   { (f'<div style="border-top:1px solid rgba(240,180,41,0.35);margin-top:4px;padding-top:5px;">'  
      f'<div style="font-size:0.62rem;font-weight:800;color:#F0B429;margin-bottom:3px;">⚠️ MAXED CAPACITY<span class="tip" data-tip="This unit''s attributed demand exceeds its modeled physical capacity under the current mission profile and on-scene time assumption.">?</span> · {min(d_on_scene, 10.0):.1f} min on-scene floor<span class="tip" data-tip="Capacity is modeled with at least this many minutes spent on scene per dispatch before the drone can clear and recharge.">?</span></div>'  
       f'<div style="font-size:0.59rem;color:{text_muted};margin-bottom:4px;">{d_unserv_day:.0f} calls/day unserviceable · {d_unserv_yr:,.0f}/yr</div>'  
       f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-bottom:4px;">'  
        f'<div style="background:rgba(240,180,41,0.08);border:1px solid rgba(240,180,41,0.2);border-radius:4px;padding:3px 6px;font-size:0.59rem;">'  
      f'<div style="color:{text_muted};">Total Flights Possible<span class="tip" data-tip="Maximum annual dispatches this unit can physically fly under the modeled duty cycle, recharge time, and on-scene floor.">?</span></div>'  
       f'<div style="font-weight:700;color:{card_title};">{d_total_flights_possible_yr:,.0f}/yr</div></div>'  
        f'<div style="background:rgba(240,180,41,0.08);border:1px solid rgba(240,180,41,0.2);border-radius:4px;padding:3px 6px;font-size:0.59rem;">'  
      f'<div style="color:{text_muted};">Uncovered Flights<span class="tip" data-tip="Annual dispatch demand in this unit''s zone that remains unserved because it exceeds physical capacity.">?</span></div>'  
       f'<div style="font-weight:700;color:#F0B429;">{d_total_uncovered_flights_yr:,.0f}/yr</div></div>'  
       f'</div>'  
       f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:3px;">'  
        f'<div style="background:rgba(240,180,41,0.08);border:1px solid rgba(240,180,41,0.2);border-radius:4px;padding:3px 6px;font-size:0.59rem;">'  
      f'<div style="color:{text_muted};">+{d_extra_same} {d_same_lbl}<span class="tip" data-tip="Estimated number of additional same-type drones needed to absorb this unit''s excess demand under the current model.">?</span></div>'  
       f'<div style="font-weight:700;color:#F0B429;">{_sc_fmt}</div></div>'  
        f'<div style="background:rgba(240,180,41,0.08);border:1px solid rgba(240,180,41,0.2);border-radius:4px;padding:3px 6px;font-size:0.59rem;">'  
      f'<div style="color:{text_muted};">+{d_extra_alt} {d_alt_lbl}<span class="tip" data-tip="Estimated number of additional alternate-type drones needed to absorb this unit''s excess demand under the current model.">?</span></div>'  
       f'<div style="font-weight:700;color:#F0B429;">{_ac_fmt}</div></div>'  
       f'</div></div>')  
    if d_capacity_limited else  
    (f'<div style="border-top:1px solid rgba(34,197,94,0.2);margin-top:4px;padding-top:4px;display:flex;align-items:center;gap:5px;">'  
     f'<span style="font-size:0.60rem;color:#2ecc71;font-weight:700;">✓ WITHIN CAPACITY<span class="tip" data-tip="This unit''s attributed annual demand stays within its modeled physical capacity.">?</span></span>'  
     f'<span style="font-size:0.60rem;color:{scene_color};font-weight:600;">· {d_on_scene:.1f} min on-scene<span class="tip" data-tip="Assumed average on-scene time per dispatch used in the capacity model for this unit.">?</span></span>'  
     f'</div>') }
  <!-- Inline lock status indicators -->
  <div style="display:grid; grid-template-columns:1fr 1fr; gap:3px; margin-top:auto; padding-top:4px; flex-shrink:0;">
    <div style="{"background:rgba(255,215,0,0.15);border:1px solid rgba(255,215,0,0.5);" if (d.get("pinned") and d_type=="GUARDIAN") else "background:rgba(255,255,255,0.03);border:1px dashed rgba(255,215,0,0.18);"} border-radius:4px; padding:3px 6px; font-size:0.57rem; color:{"#FFD700" if (d.get("pinned") and d_type=="GUARDIAN") else "rgba(255,215,0,0.35)"}; text-align:center; line-height:1.5; white-space:nowrap;">{"🔒 Guardian" if (d.get("pinned") and d_type=="GUARDIAN") else "🦅 lock guard"}</div>
    <div style="{"background:rgba(0,210,255,0.15);border:1px solid rgba(0,210,255,0.5);" if (d.get("pinned") and d_type=="RESPONDER") else "background:rgba(255,255,255,0.03);border:1px dashed rgba(0,210,255,0.18);"} border-radius:4px; padding:3px 6px; font-size:0.57rem; color:{"#00D2FF" if (d.get("pinned") and d_type=="RESPONDER") else "rgba(0,210,255,0.35)"}; text-align:center; line-height:1.5; white-space:nowrap;">{"🔒 Responder" if (d.get("pinned") and d_type=="RESPONDER") else "🚁 lock resp"}</div>
  </div>
</div>''')



    grid = (

        '<div style="display:grid; grid-template-columns:repeat(' + str(columns_per_row) + ', minmax(0, 1fr));'

        ' gap:10px; align-items:start; margin-bottom:12px; width:100%; box-sizing:border-box;">'

        + "".join(cards_html)

        + '</div>'

    )

    # Wrap in a style-scoped div to prevent Streamlit container from collapsing width.

    # overflow:visible is required so the 1.5x hover scale isn't clipped by the grid container.

    grid_id = f"ucg_{abs(hash(str([d.get('name') for d in active_drones]))) % 100000}"

    return (

        '<style>'

        '.unit-card-grid { display:grid; gap:10px; width:100%; box-sizing:border-box; overflow:visible; }'

        '.unit-card-grid > .unit-card { min-width:0; box-sizing:border-box; overflow:visible; }'

        '.tip { display:inline-flex; align-items:center; justify-content:center; width:11px; height:11px; border-radius:50%; background:rgba(255,255,255,0.12); color:#888; font-size:8px; font-weight:700; cursor:default; margin-left:3px; vertical-align:middle; position:relative; flex-shrink:0; }'

        '.tip:hover::after { content:attr(data-tip); position:absolute; bottom:130%; left:50%; transform:translateX(-50%); background:#1a1a2e; color:#e0e0e0; font-size:10px; font-weight:400; padding:5px 8px; border-radius:5px; white-space:normal; width:200px; line-height:1.4; z-index:9999; border:1px solid #333; box-shadow:0 4px 12px rgba(0,0,0,0.5); pointer-events:none; text-transform:none; letter-spacing:normal; }'

        '</style>'

        f'<div id="{grid_id}" class="unit-card-grid" style="grid-template-columns:repeat({columns_per_row}, minmax(0,1fr)); overflow:visible;">'

        + "".join(cards_html)

        + '</div>'

        f'<script>'

        f'(function(){{'

        f'  function eq(){{'

        f'    var g=document.getElementById("{grid_id}");'

        f'    if(!g)return;'

        f'    var cards=g.querySelectorAll(".unit-card");'

        f'    if(!cards.length)return;'

        f'    cards.forEach(function(c){{c.style.height="auto";}});'

        f'    var maxH=0;'

        f'    cards.forEach(function(c){{maxH=Math.max(maxH,c.getBoundingClientRect().height);}});'

        f'    cards.forEach(function(c){{c.style.height=maxH+"px";}});'

        f'  }}'

        f'  if(document.readyState==="complete"){{eq();}}else{{window.addEventListener("load",eq);}}'

        f'  setTimeout(eq,150);'

        f'  setTimeout(eq,600);'

        f'}})();'

        f'</script>'

    )







def to_kml_color(hex_str):

    h = hex_str.lstrip('#')

    return f"ff{h[4:6]}{h[2:4]}{h[0:2]}" if len(h) == 6 else "ff0000ff"







def generate_kml(active_gdf, active_drones, calls_gdf):

    kml = simplekml.Kml()

    kml.document.name = "BRINC DFR Deployment Plan"

    kml.document.description = (

        "SIMULATOR DISCLAIMER: This file was generated by the BRINC Drones Coverage Optimization Simulator. "

        "All coverage zones, station locations, and incident data are model estimates based on user-provided inputs. "

        "Real-world results will vary. This file does not constitute a legal recommendation, binding proposal, "

        "contract, or guarantee of any product, service, or financial outcome. "

        "All deployments require FAA authorization, local ordinances review, and formal procurement."

    )

    def _as_wgs84(gdf):

        if gdf is None or not hasattr(gdf, "empty") or gdf.empty:

            return None

        try:

            if getattr(gdf, "crs", None) is None:

                return gdf.set_crs(epsg=4326, allow_override=True)

            return gdf.to_crs(epsg=4326)

        except Exception:

            return gdf

    def _iter_polygons(geom):

        if geom is None or getattr(geom, "is_empty", True):

            return []

        geom_type = getattr(geom, "geom_type", "")

        if geom_type == "Polygon":

            return [geom]

        if geom_type == "MultiPolygon":

            return [g for g in geom.geoms if not getattr(g, "is_empty", True)]

        if hasattr(geom, "geoms"):

            polys = []

            for sub_geom in geom.geoms:

                polys.extend(_iter_polygons(sub_geom))

            return polys

        return []

    fol_bounds = kml.newfolder(name="Jurisdictions")

    active_export = _as_wgs84(active_gdf)

    if active_export is not None:

        for _, row in active_export.iterrows():

            for geom in _iter_polygons(getattr(row, "geometry", None)):

                coords = list(geom.exterior.coords)

                if len(coords) < 4:

                    continue

                pol = fol_bounds.newpolygon(name=row.get('DISPLAY_NAME', 'Boundary'))

                pol.outerboundaryis = coords

                pol.style.linestyle.color = simplekml.Color.red

                pol.style.linestyle.width = 3

                pol.style.polystyle.color = simplekml.Color.changealphaint(30, simplekml.Color.red)

    fol_stations = kml.newfolder(name="Station Points")

    fol_rings = kml.newfolder(name="Coverage Rings")

    for d in active_drones or []:

        try:

            lat = float(d.get('lat'))

            lon = float(d.get('lon'))

        except Exception:

            continue

        if not (math.isfinite(lat) and math.isfinite(lon)):

            continue

        drone_type = str(d.get('type', 'DRONE') or 'DRONE')

        drone_name = str(d.get('name', 'Station') or 'Station')

        kml_c = to_kml_color(str(d.get('color', '#00D2FF') or '#00D2FF'))

        pnt = fol_stations.newpoint(name=f"[{drone_type[:3]}] {drone_name}")

        pnt.coords = [(lon, lat)]

        pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/paddle/blu-blank.png'

        try:

            radius_m = float(d.get('radius_m', 0) or 0)

            lats, lons = get_circle_coords(lat, lon, r_mi=max(radius_m, 0.0) / 1609.34)

            ring_coords = list(zip(lons, lats))

        except Exception:

            ring_coords = []

        if len(ring_coords) >= 3:

            ring_coords.append(ring_coords[0])

            pol = fol_rings.newpolygon(name=f"Range: {drone_name}")

            pol.outerboundaryis = ring_coords

            pol.style.linestyle.color = kml_c

            pol.style.linestyle.width = 2

            pol.style.polystyle.color = simplekml.Color.changealphaint(60, kml_c)

    fol_calls = kml.newfolder(name="Incident Data (Sample)")

    calls_export = _as_wgs84(calls_gdf)

    if calls_export is not None:

        if len(calls_export) > 2000:

            calls_export = calls_export.sample(2000, random_state=42)

        for _, row in calls_export.iterrows():

            geom = getattr(row, "geometry", None)

            if geom is None or getattr(geom, "is_empty", True) or getattr(geom, "geom_type", "") != "Point":

                continue

            pnt = fol_calls.newpoint()

            pnt.coords = [(geom.x, geom.y)]

            pnt.style.iconstyle.scale = 0.5

            pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'

    return kml.kml()



@st.cache_data





def generate_community_impact_dashboard_html(

    city, state, population,

    total_calls, calls_covered_perc, area_covered_perc,

    avg_resp_time_min, avg_time_saved_min,

    fleet_capex, annual_savings, break_even_text,

    actual_k_responder, actual_k_guardian,

    dfr_dispatch_rate, deflection_rate,

    daily_dfr_responses, daily_drone_only_calls,

    active_drones,

    df_calls_full,

    theme='dark',

    facility_counts=None,

):

    """

    Generate a Community Impact Dashboard HTML string.

    theme='dark'  -- black background, for in-app Streamlit embed.

    theme='light' -- white/off-white background, for HTML export / print.

    """

    import json as _json



    # ── Derived metrics ──────────────────────────────────────────────────────

    daily_flights   = max(0.0, float(daily_dfr_responses or 0))

    annual_flights  = daily_flights * 365



    # Guardian uptime hours per day from CONFIG

    g_count  = max(0, int(actual_k_guardian or 0))

    r_count  = max(0, int(actual_k_responder or 0))

    g_daily_hrs = g_count * GUARDIAN_FLIGHT_HOURS_PER_DAY

    r_daily_hrs = r_count * CONFIG["RESPONDER_PATROL_HOURS"]          # Responder patrol hours

    total_daily_flight_hrs = g_daily_hrs + r_daily_hrs

    annual_flight_hrs = total_daily_flight_hrs * 365



    # Response time advantage

    drone_min  = float(avg_resp_time_min or 0)

    saved_min  = float(avg_time_saved_min or 0)

    ground_min = drone_min + saved_min

    drone_wins_pct = min(99, max(CONFIG['DRONE_WINS_FLOOR'], round(calls_covered_perc * CONFIG['DRONE_WINS_MULTIPLIER']))) if calls_covered_perc > 0 else 0



    # Per-type response time breakdown for the bar chart

    _RESP_SPEED   = float(CONFIG.get('RESPONDER_SPEED', 42.0))

    _GUARD_SPEED  = float(CONFIG.get('GUARDIAN_SPEED', 60.0))

    _GROUND_SPEED = float(CONFIG.get('DEFAULT_TRAFFIC_SPEED', 35.0))

    _resp_drones  = [d for d in active_drones if d.get('type') == 'RESPONDER']

    _guard_drones = [d for d in active_drones if d.get('type') == 'GUARDIAN']

    resp_drone_min  = (sum(d['avg_time_min'] for d in _resp_drones)  / len(_resp_drones))  if _resp_drones  else None

    guard_drone_min = (sum(d['avg_time_min'] for d in _guard_drones) / len(_guard_drones)) if _guard_drones else None

    # Ground time uses the corrected formula: avg_dist × 1.4 / ground_speed

    # avg_dist = avg_time_min × drone_speed / 60  →  ground_time = avg_time_min × drone_speed × 1.4 / ground_speed

    resp_ground_min  = (resp_drone_min  * _RESP_SPEED  * 1.4 / _GROUND_SPEED) if resp_drone_min  is not None else None

    guard_ground_min = (guard_drone_min * _GUARD_SPEED * 1.4 / _GROUND_SPEED) if guard_drone_min is not None else None

    # Reference ground time for the chart = best available single ground estimate

    _chart_ground_min = ground_min if ground_min > 0 else max(

        (resp_ground_min or 0), (guard_ground_min or 0)

    )

    _chart_max = max(_chart_ground_min, resp_drone_min or 0, guard_drone_min or 0, 0.1)



    # Pre-build per-type bar HTML so we avoid nested f-strings in the template

    if resp_drone_min is not None:

        _resp_bar_h = min(100, resp_drone_min / _chart_max * 100)

        _resp_bar_html = (

            '<div class="rt-bar-wrap">'

            '<div class="rt-bar-outer">'

            f'<div class="rt-bar-fill" style="height:{_resp_bar_h:.0f}%;background:linear-gradient(180deg,var(--accent-blue),#3b82f6);"></div>'

            '</div>'

            '<div class="rt-bar-label">&#x1F681; Responder '

            '<span class="tip-cid" data-tip="Avg flight time for Responder drones (45 mph airspeed, 2-mile zone). Direct line-of-sight flight — no traffic, no turns.">?</span></div>'

            f'<div class="rt-bar-value" style="color:var(--accent-blue);">{resp_drone_min:.1f} min</div>'

            '</div>'

        )

    else:

        _resp_bar_html = ''



    if guard_drone_min is not None:

        _guard_bar_h = min(100, guard_drone_min / _chart_max * 100)

        _guard_bar_html = (

            '<div class="rt-bar-wrap">'

            '<div class="rt-bar-outer">'

            f'<div class="rt-bar-fill" style="height:{_guard_bar_h:.0f}%;background:linear-gradient(180deg,var(--accent-gold),#ca8a04);"></div>'

            '</div>'

            '<div class="rt-bar-label">&#x1F985; Guardian '

            '<span class="tip-cid" data-tip="Avg flight time for Guardian drones (60 mph airspeed, up to 8-mile zone). Longer range means slightly longer avg flight, still far faster than road travel over that distance.">?</span></div>'

            f'<div class="rt-bar-value" style="color:var(--accent-gold);">{guard_drone_min:.1f} min</div>'

            '</div>'

        )

    else:

        _guard_bar_html = ''



    _ground_bar_h = min(100, _chart_ground_min / _chart_max * 100)

    _ground_bar_html = (

        '<div class="rt-bar-wrap">'

        '<div class="rt-bar-outer">'

        f'<div class="rt-bar-fill" style="height:{_ground_bar_h:.0f}%;background:linear-gradient(180deg,#f59e0b,#d97706);"></div>'

        '</div>'

        f'<div class="rt-bar-label">&#x1F694; Ground Unit (est.) '

        f'<span class="tip-cid" data-tip="Patrol car travel time over the same avg incident distance at {_GROUND_SPEED:.0f} mph road speed with a 1.4\u00d7 tortuosity factor. Actual response varies by unit availability.">?</span></div>'

        f'<div class="rt-bar-value" style="color:#f59e0b;">{_chart_ground_min:.1f} min</div>'

        '</div>'

    )



    # Outcomes counter (modeled estimates)

    total_annual_dfr = int(annual_flights * float(dfr_dispatch_rate or 0.30))

    arrests_est      = int(total_annual_dfr * CONFIG['OUTCOME_ARREST_RATE'])

    rescues_est      = int(total_annual_dfr * CONFIG['OUTCOME_RESCUE_RATE'])

    deescalation_est = int(total_annual_dfr * CONFIG['OUTCOME_DEESCALATION_RATE'])

    missing_est      = int(total_annual_dfr * CONFIG['OUTCOME_MISSING_RATE'])



    # ROI

    roi_multiple = round(float(annual_savings or 0) / max(float(fleet_capex or 1), 1), 2)

    cost_per_call_drone   = CONFIG['DRONE_COST_PER_CALL']

    cost_per_call_officer = CONFIG['OFFICER_COST_PER_CALL']

    cost_saved_per_resolved = cost_per_call_officer - cost_per_call_drone

    total_resolved_annually = int(float(daily_drone_only_calls or 0) * 365)



    # Fire department impact (NFPA / IAFC DFR benchmark estimates)

    _fire_pct            = 0.15   # 15% of DFR deployments are fire/rescue (NFPA 2022 Fire Loss Report)

    _false_alarm_rate    = 0.23   # 23% of fire calls are false alarms (NFPA)

    _false_alarm_detect  = 0.68   # 68% of false alarms identifiable by drone pre-arrival (IAFC DFR pilots)

    _engine_cost         = 895    # Avg cost per engine response (NFPA 2023)

    _recon_value_per     = 185    # Scene size-up labor savings per fire DFR response (IAAI DFR White Paper 2023)

    _annual_fire_dfr     = int(total_annual_dfr * _fire_pct)

    _false_alarms_avoided = int(_annual_fire_dfr * _false_alarm_rate * _false_alarm_detect)

    _false_alarm_savings = _false_alarms_avoided * _engine_cost

    _fire_recon_value    = _annual_fire_dfr * _recon_value_per

    _total_fire_value    = _false_alarm_savings + _fire_recon_value



    # Call type breakdown from df_calls_full

    call_type_data = {}

    _type_col = None

    if df_calls_full is not None and not df_calls_full.empty:

        for _tc in ['call_type_desc','agencyeventtypecodedesc','calldesc','description','nature','type']:

            if _tc in df_calls_full.columns:

                _type_col = _tc

                break

    if _type_col:

        try:

            _vc = df_calls_full[_type_col].dropna().astype(str).str.strip().str.title().value_counts().head(8)

            _total = _vc.sum()

            for k, v in _vc.items():

                call_type_data[str(k)[:32]] = int(v)

        except Exception:

            pass



    if not call_type_data:

        # Reasonable DFR-program defaults — use a floor of 500 so bars are always visible

        _ct_base = max(int(total_annual_dfr), 500)

        call_type_data = {

            "Shots Fired / Weapon": int(_ct_base * 0.12),

            "Suspicious Person": int(_ct_base * 0.19),

            "Burglary / Theft": int(_ct_base * 0.17),

            "Traffic Accident": int(_ct_base * 0.11),

            "Welfare Check": int(_ct_base * 0.20),

            "Domestic Disturbance": int(_ct_base * 0.09),

            "Missing Person": int(_ct_base * 0.05),

            "Other": int(_ct_base * 0.07),

        }



    ct_total   = max(1, sum(call_type_data.values()))

    ct_items_js = _json.dumps([

        {"label": k, "count": v, "pct": round(v / ct_total * 100, 1)}

        for k, v in call_type_data.items()

    ])



    # Equity / geographic note: district coverage from active_drones

    drone_names_js = _json.dumps([

        {"name": d["name"].split(",")[0][:28], "type": d["type"]}

        for d in active_drones

    ] if active_drones else [])



    # Facility type counts for the Protected Facilities section

    _fac_icon_map = {

        "Police": "🚔", "Fire": "🚒", "EMS": "🚑", "School": "🏫",

        "Hospital": "🏥", "University": "🎓", "Transit": "🚌",

        "Community": "🏛️", "Courthouse": "⚖️", "Social Services": "🤝",

        "Government": "🏛️", "Library": "📚",

        "Power Station": "⚡", "Water Treatment": "💧",

    }

    _fac_src_map = {

        "Police":          "DHS HIFLD Law Enforcement Locations · OpenStreetMap (amenity=police, ODbL)",

        "Fire":            "DHS HIFLD Fire Stations (public domain) · OpenStreetMap (amenity=fire_station)",

        "EMS":             "OpenStreetMap (amenity=ambulance_station) · NEMSIS National EMS Database (nemsis.org)",

        "School":          "OpenStreetMap (amenity=school) · NCES Common Core of Data (nces.ed.gov)",

        "Hospital":        "OpenStreetMap (amenity=hospital) · CMS Hospital Compare (cms.gov)",

        "University":      "OpenStreetMap (amenity=university/college) · IPEDS (nces.ed.gov/ipeds)",

        "Transit":         "OpenStreetMap (amenity=bus_station · railway=station) · NTD (transit.dot.gov)",

        "Community":       "OpenStreetMap (amenity=community_centre) · IMLS Public Libraries Survey",

        "Courthouse":      "OpenStreetMap (amenity=courthouse) · US Courts PACER (uscourts.gov)",

        "Social Services": "OpenStreetMap (amenity=social_facility) · HUD Location Affordability Index",

        "Government":      "OpenStreetMap (building=government) · Census TIGER/Line (census.gov)",

        "Library":         "OpenStreetMap (amenity=library) · IMLS Public Libraries Survey (imls.gov)",

        "Power Station":   "OpenStreetMap (power=station) · US Energy Information Administration (eia.gov)",

        "Water Treatment": "OpenStreetMap (man_made=water_treatment) · EPA Enviromapper · US Water Infrastructure Database",

    }

    _fac_color_map = {

        "Police": "#00D2FF", "Fire": "#ef4444", "EMS": "#f97316",

        "School": "#eab308", "Hospital": "#22c55e", "University": "#3b82f6",

        "Transit": "#10b981", "Community": "#f59e0b", "Courthouse": "#8b5cf6",

        "Social Services": "#ec4899", "Government": "#a78bfa", "Library": "#fb923c",

        "Power Station": "#f59e0b", "Water Treatment": "#0ea5e9",

    }

    _total_facilities = sum((facility_counts or {}).values())

    _fac_cards_html = ""

    if facility_counts:

        for _ft, _fcnt in sorted(facility_counts.items(), key=lambda x: -x[1]):

            _fi = _fac_icon_map.get(_ft, "🏢")

            _fc = _fac_color_map.get(_ft, "#888")

            _fs = _fac_src_map.get(_ft, "OpenStreetMap contributors (ODbL)")

            _fac_cards_html += (

                f'<div style="background:var(--bg-card);border:1px solid var(--rule);border-top:3px solid {_fc};'

                f'border-radius:8px;padding:12px 14px;text-align:center;">'

                f'<div style="font-size:22px;margin-bottom:4px;">{_fi}</div>'

                f'<div style="font-size:20px;font-weight:900;color:{_fc};font-family:\'DM Mono\',monospace;">{_fcnt}</div>'

                f'<div style="font-size:10px;font-weight:700;color:var(--ink-light);text-transform:uppercase;'

                f'letter-spacing:0.6px;margin-top:2px;">{_ft}</div>'

                f'<div style="font-size:9px;color:var(--ink-light);margin-top:4px;font-style:italic;" '

                f'title="Source: {_fs}">ⓘ {_fs[:38]}{"…" if len(_fs)>38 else ""}</div>'

                f'</div>'

            )

    if not _fac_cards_html:

        _fac_cards_html = '<p style="color:var(--ink-light);font-size:12px;">No facility data available.</p>'



    # Privacy policy data-retention badge values

    retention_days   = 30   # industry standard shown in transparency portals

    no_proactive     = True

    no_facial_recog  = True

    warrant_transit  = True  # camera forward-facing in transit



    # ── Theme CSS variables ──────────────────────────────────────────────────

    if theme == 'dark':

        _css_vars = """

    --bg-page:      #000000;

    --bg-card:      #111111;

    --bg-inset:     #0a0a0a;

    --ink:          #f0f0f0;

    --ink-mid:      #bbbbbb;

    --ink-light:    #888888;

    --rule:         #2a2a2a;

    --accent-blue:  #00D2FF;

    --accent-blue-lt: rgba(0,210,255,0.12);

    --accent-green: #39FF14;

    --accent-green-lt: rgba(57,255,20,0.10);

    --accent-gold:  #FFD700;

    --accent-gold-lt: rgba(255,215,0,0.10);

    --accent-red:   #ff4b4b;

    --accent-red-lt: rgba(255,75,75,0.12);

    --accent-slate: #888888;

    --shadow-sm: 0 1px 4px rgba(0,0,0,0.6);

    --shadow-md: 0 4px 16px rgba(0,210,255,0.10), 0 2px 6px rgba(0,0,0,0.5);

    --header-border: 2px solid #333333;

    --card-hover-shadow: 0 0 0 1px #00D2FF44, 0 8px 24px rgba(0,210,255,0.12);

"""

        _body_bg = '#000000'

        _body_color = '#f0f0f0'

    else:

        _css_vars = """

    --bg-page:      #f8f7f4;

    --bg-card:      #ffffff;

    --bg-inset:     #f8f7f4;

    --ink:          #1a1a2e;

    --ink-mid:      #3d3d5c;

    --ink-light:    #6b6b8a;

    --rule:         #e2e0da;

    --accent-blue:  #1a56db;

    --accent-blue-lt: #dbeafe;

    --accent-green: #0d9e6e;

    --accent-green-lt: #d1fae5;

    --accent-gold:  #b45309;

    --accent-gold-lt: #fef3c7;

    --accent-red:   #be123c;

    --accent-red-lt: #ffe4e6;

    --accent-slate: #475569;

    --shadow-sm: 0 1px 3px rgba(26,22,46,0.06), 0 1px 2px rgba(26,22,46,0.04);

    --shadow-md: 0 4px 12px rgba(26,22,46,0.08), 0 2px 4px rgba(26,22,46,0.04);

    --header-border: 2px solid #1a1a2e;

    --card-hover-shadow: var(--shadow-md);

"""

        _body_bg = '#f8f7f4'

        _body_color = '#1a1a2e'



    # Build HTML ─────────────────────────────────────────────────────────────

    html = f"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport" content="width=device-width, initial-scale=1.0">

<link rel="preconnect" href="https://fonts.googleapis.com">

<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">

<style>

  :root {{{_css_vars}  }}

  html, body {{ background: transparent; margin: 0; padding: 0; }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{

    font-family: 'DM Sans', sans-serif;

    color: {_body_color};

    font-size: 14px;

    line-height: 1.55;

  }}

  .dash-wrap {{

    background: {_body_bg};

    padding: 28px 24px 40px;

  }}



  /* ── Page header ── */

  .dash-header {{

    display: flex;

    align-items: flex-start;

    justify-content: space-between;

    border-bottom: var(--header-border);

    padding-bottom: 14px;

    margin-bottom: 28px;

    gap: 16px;

    flex-wrap: wrap;

  }}

  .dash-title {{

    font-family: 'Libre Baskerville', Georgia, serif;

    font-size: 22px;

    font-weight: 700;

    color: var(--ink);

    letter-spacing: -0.3px;

  }}

  .dash-subtitle {{

    font-size: 12.5px;

    color: var(--ink-light);

    margin-top: 3px;

    font-weight: 400;

  }}

  .dash-meta {{

    text-align: right;

    font-size: 11.5px;

    color: var(--ink-light);

    line-height: 1.7;

  }}

  .dash-meta strong {{ color: var(--ink); font-weight: 600; }}



  /* ── Section label ── */

  .section-label {{

    font-size: 10px;

    font-weight: 700;

    letter-spacing: 1.6px;

    text-transform: uppercase;

    color: var(--ink-light);

    margin-bottom: 10px;

    padding-bottom: 5px;

    border-bottom: 1px solid var(--rule);

  }}



  /* ── Grid layouts ── */

  .grid-3 {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 14px; margin-bottom: 20px; }}

  .grid-2 {{ display: grid; grid-template-columns: repeat(2,1fr); gap: 14px; margin-bottom: 20px; }}

  .grid-4 {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; margin-bottom: 20px; }}

  @media(max-width:700px) {{

    .grid-3,.grid-4 {{ grid-template-columns:1fr 1fr; }}

    .grid-2 {{ grid-template-columns:1fr; }}

  }}



  /* ── Stat card ── */

  .stat-card {{

    background: var(--bg-card);

    border: 1px solid var(--rule);

    border-radius: 10px;

    padding: 18px 20px 16px;

    box-shadow: var(--shadow-sm);

    position: relative;

    overflow: hidden;

    transition: box-shadow 0.2s;

  }}

  .stat-card:hover {{ box-shadow: var(--card-hover-shadow); }}

  .stat-card .accent-bar {{

    position: absolute;

    top: 0; left: 0; right: 0;

    height: 3px;

    border-radius: 10px 10px 0 0;

  }}

  .stat-card .card-label {{

    font-size: 10.5px;

    font-weight: 600;

    letter-spacing: 0.8px;

    text-transform: uppercase;

    color: var(--ink-light);

    margin-bottom: 6px;

  }}

  .stat-card .card-value {{

    font-family: 'DM Mono', monospace;

    font-size: 26px;

    font-weight: 500;

    color: var(--ink);

    line-height: 1.1;

  }}

  .stat-card .card-sub {{

    font-size: 11px;

    color: var(--ink-light);

    margin-top: 5px;

  }}

  .stat-card .card-badge {{

    display: inline-block;

    font-size: 10px;

    font-weight: 600;

    padding: 2px 7px;

    border-radius: 99px;

    margin-top: 6px;

  }}



  /* ── Progress bar ── */

  .prog-row {{ margin-bottom: 10px; }}

  .prog-meta {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }}

  .prog-label {{ font-size: 12px; color: var(--ink-mid); font-weight: 500; }}

  .prog-val {{ font-family: 'DM Mono', monospace; font-size: 12px; color: var(--ink); font-weight: 500; }}

  .prog-track {{

    height: 8px;

    background: var(--rule);

    border-radius: 99px;

    overflow: hidden;

  }}

  .prog-fill {{

    height: 100%;

    border-radius: 99px;

    animation: growBar 1.2s cubic-bezier(0.22,1,0.36,1) both;

  }}

  @keyframes growBar {{ from {{ width:0 }} }}



  /* ── Animated counter ── */

  .counter {{ display: inline-block; }}



  /* ── Response time comparison ── */

  .rt-compare {{

    background: var(--bg-card);

    border: 1px solid var(--rule);

    border-radius: 10px;

    padding: 20px;

    box-shadow: var(--shadow-sm);

    margin-bottom: 20px;

  }}

  .rt-bars {{ display: flex; gap: 28px; align-items: flex-end; margin-top: 14px; }}

  .rt-bar-wrap {{ flex: 1; text-align: center; }}

  .rt-bar-outer {{

    background: var(--rule);

    border-radius: 6px 6px 0 0;

    position: relative;

    overflow: hidden;

    display: flex;

    align-items: flex-end;

    height: 120px;

  }}

  .rt-bar-fill {{

    width: 100%;

    border-radius: 6px 6px 0 0;

    animation: growUp 1.4s cubic-bezier(0.22,1,0.36,1) both;

    position: relative;

  }}

  @keyframes growUp {{ from {{ height: 0 }} }}

  .rt-bar-label {{ margin-top: 8px; font-size: 11.5px; font-weight: 600; color: var(--ink-mid); }}

  .rt-bar-value {{ font-family: 'DM Mono', monospace; font-size: 17px; font-weight: 500; margin-top: 3px; }}

  .rt-wins-badge {{

    display: inline-block;

    background: var(--accent-green-lt);

    color: var(--accent-green);

    font-size: 11px;

    font-weight: 700;

    padding: 4px 12px;

    border-radius: 99px;

    margin-top: 14px;

  }}



  /* ── 4th Amendment panel ── */

  .amend-panel {{

    background: var(--bg-card);

    border: 1px solid var(--rule);

    border-left: 4px solid var(--accent-blue);

    border-radius: 10px;

    padding: 20px 22px;

    box-shadow: var(--shadow-sm);

    margin-bottom: 20px;

  }}

  .amend-title {{

    font-family: 'Libre Baskerville', serif;

    font-size: 15px;

    font-weight: 700;

    color: var(--ink);

    margin-bottom: 12px;

    display: flex;

    align-items: center;

    gap: 8px;

  }}

  .amend-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 14px; }}

  @media(max-width:700px) {{ .amend-grid {{ grid-template-columns: 1fr 1fr; }} }}

  .amend-item {{

    background: var(--bg-inset);

    border-radius: 8px;

    padding: 12px 14px;

    display: flex;

    align-items: flex-start;

    gap: 10px;

  }}

  .amend-icon {{ font-size: 18px; flex-shrink: 0; line-height: 1; margin-top: 1px; }}

  .amend-item-title {{ font-size: 11.5px; font-weight: 700; color: var(--ink); margin-bottom: 2px; }}

  .amend-item-desc {{ font-size: 10.5px; color: var(--ink-light); line-height: 1.45; }}

  .amend-disclaimer {{

    margin-top: 12px;

    font-size: 10.5px;

    color: var(--ink-light);

    background: var(--accent-blue-lt);

    border-radius: 6px;

    padding: 8px 12px;

    line-height: 1.5;

  }}



  /* ── Outcomes counters ── */

  .outcome-card {{

    background: var(--bg-card);

    border: 1px solid var(--rule);

    border-radius: 10px;

    padding: 18px 16px 14px;

    text-align: center;

    box-shadow: var(--shadow-sm);

    animation: fadeUp 0.6s ease both;

  }}

  @keyframes fadeUp {{ from {{ opacity:0; transform:translateY(12px) }} }}

  .outcome-icon {{ font-size: 26px; margin-bottom: 8px; display: block; }}

  .outcome-val {{

    font-family: 'DM Mono', monospace;

    font-size: 28px;

    font-weight: 500;

    color: var(--ink);

    line-height: 1;

  }}

  .outcome-label {{ font-size: 11px; color: var(--ink-light); font-weight: 500; margin-top: 5px; text-transform: uppercase; letter-spacing: 0.5px; }}

  .outcome-note {{ font-size: 10px; color: var(--ink-light); margin-top: 4px; font-style: italic; }}



  /* ── ROI meter ── */

  .roi-panel {{

    background: var(--bg-card);

    border: 1px solid var(--rule);

    border-radius: 10px;

    padding: 20px 22px;

    box-shadow: var(--shadow-sm);

    margin-bottom: 20px;

  }}

  .roi-row {{ display: flex; gap: 20px; align-items: stretch; flex-wrap: wrap; }}

  .roi-big {{ flex: 1; min-width: 160px; }}

  .roi-big-val {{

    font-family: 'DM Mono', monospace;

    font-size: 38px;

    font-weight: 500;

    color: var(--accent-green);

    line-height: 1;

    animation: fadeUp 0.8s ease both;

  }}

  .roi-big-label {{ font-size: 11px; color: var(--ink-light); font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; margin-top: 5px; }}

  .roi-details {{ flex: 2; min-width: 220px; }}

  .roi-line {{ display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid var(--rule); font-size: 12.5px; }}

  .roi-line:last-child {{ border-bottom: none; }}

  .roi-line-label {{ color: var(--ink-mid); }}

  .roi-line-val {{ font-family: 'DM Mono', monospace; font-weight: 500; color: var(--ink); }}



  /* ── Call type bars ── */

  .ct-panel {{

    background: var(--bg-card);

    border: 1px solid var(--rule);

    border-radius: 10px;

    padding: 20px 22px;

    box-shadow: var(--shadow-sm);

    margin-bottom: 20px;

  }}



  /* ── Uptime donut placeholder ── */

  canvas {{ display: block; }}



  /* ── Disclaimer footer ── */

  .dash-footer {{

    margin-top: 24px;

    padding-top: 14px;

    border-top: 1px solid var(--rule);

    font-size: 10px;

    color: var(--ink-light);

    line-height: 1.6;

  }}

  .dash-footer strong {{ color: var(--ink-mid); }}



  /* ── Pulse dot ── */

  @keyframes pulse {{

    0%,100% {{ opacity: 1; transform: scale(1); }}

    50% {{ opacity: 0.5; transform: scale(1.4); }}

  }}

  .live-dot {{

    display: inline-block;

    width: 7px; height: 7px;

    background: var(--accent-green);

    border-radius: 50%;

    margin-right: 5px;

    animation: pulse 2s ease-in-out infinite;

    vertical-align: middle;

  }}



  /* ── Tooltip badges ── */

  .tip-cid {{

    display: inline-flex;

    align-items: center;

    justify-content: center;

    width: 13px; height: 13px;

    border-radius: 50%;

    background: rgba(128,128,128,0.18);

    color: #888;

    font-size: 8px;

    font-weight: 700;

    cursor: default;

    margin-left: 4px;

    vertical-align: middle;

    position: relative;

    flex-shrink: 0;

    font-style: normal;

    line-height: 1;

  }}

  .tip-cid:hover::after {{

    content: attr(data-tip);

    position: absolute;

    bottom: 130%;

    left: 50%;

    transform: translateX(-50%);

    background: #0d0d1a;

    color: #e0e0f0;

    font-size: 11px;

    font-weight: 400;

    padding: 7px 11px;

    border-radius: 7px;

    white-space: normal;

    width: 240px;

    line-height: 1.5;

    z-index: 9999;

    border: 1px solid #333355;

    box-shadow: 0 4px 16px rgba(0,0,0,0.6);

    pointer-events: none;

    text-transform: none;

    letter-spacing: normal;

    font-family: 'DM Sans', sans-serif;

  }}

</style>

</head>

<body>

<div class="dash-wrap">



<!-- ══════════════════════════════════════════════════════════════════

     HEADER

══════════════════════════════════════════════════════════════════ -->

<div class="dash-header">

  <div>

    <div class="dash-title">Community Impact Dashboard</div>

    <div class="dash-subtitle">{city}, {state} &nbsp;·&nbsp; DFR Program Transparency &amp; Public Accountability Report</div>

  </div>

  <div class="dash-meta">

    <strong>{city} Police Department</strong><br>

    Population served: {population:,}<br>

    Fleet: {actual_k_responder} Responder · {actual_k_guardian} Guardian<br>

    <span class="live-dot"></span>Simulation data

  </div>

</div>





<!-- ══════════════════════════════════════════════════════════════════

     SECTION 1 — FLIGHT HOURS & UPTIME

══════════════════════════════════════════════════════════════════ -->

<div class="section-label">01 &nbsp;·&nbsp; Flight Hours &amp; Uptime <span class="tip-cid" data-tip="Total daily airtime, annual flight hours, and dispatch frequency for the deployed drone fleet. Based on Guardian and Responder duty cycles.">?</span></div>

<div class="grid-3">



  <div class="stat-card">

    <div class="accent-bar" style="background:var(--accent-blue);"></div>

    <div class="card-label">Daily Airtime (Fleet) <span class="tip-cid" data-tip="Total hours all drones are airborne per day. Guardians run a 60-min flight / 3-min swap cycle (~22.9 hrs/day). Responders run a 30-min flight / 30-min recharge cycle (12.0 hrs/day).">?</span></div>

    <div class="card-value"><span class="counter" data-target="{total_daily_flight_hrs:.1f}">{total_daily_flight_hrs:.1f}</span> hrs</div>

    <div class="card-sub">{g_count} Guardian × {GUARDIAN_FLIGHT_HOURS_PER_DAY:.1f}h &nbsp;+&nbsp; {r_count} Responder × {CONFIG["RESPONDER_PATROL_HOURS"]:.1f}h</div>

    <span class="card-badge" style="background:var(--accent-blue-lt);color:var(--accent-blue);">Modeled duty cycle</span>

  </div>



  <div class="stat-card">

    <div class="accent-bar" style="background:var(--accent-blue);"></div>

    <div class="card-label">Annual Flight Hours <span class="tip-cid" data-tip="Daily fleet airtime × 365 days. Represents the total drone capacity available across the full year for incident response.">?</span></div>

    <div class="card-value"><span class="counter" data-target="{annual_flight_hrs:,.0f}">{annual_flight_hrs:,.0f}</span></div>

    <div class="card-sub">Across full fleet, 365 days</div>

    <span class="card-badge" style="background:var(--accent-blue-lt);color:var(--accent-blue);">Fleet total</span>

  </div>



  <div class="stat-card">

    <div class="accent-bar" style="background:var(--accent-blue);"></div>

    <div class="card-label">DFR Flights / Day <span class="tip-cid" data-tip="Drone-First-Response dispatches per day. Calculated as: calls in coverage zone × DFR dispatch rate. The DFR rate is the fraction of 911 calls where a drone launches before a patrol car.">?</span></div>

    <div class="card-value"><span class="counter" data-target="{daily_flights:.1f}">{daily_flights:.1f}</span></div>

    <div class="card-sub">At {int(dfr_dispatch_rate*100)}% dispatch rate · {int(calls_covered_perc)}% call coverage</div>

    <span class="card-badge" style="background:var(--accent-blue-lt);color:var(--accent-blue);">{annual_flights:,.0f}/yr projected</span>

  </div>



</div>



<!-- Uptime progress bars -->

<div class="stat-card" style="margin-bottom:20px;">

  <div class="accent-bar" style="background:var(--accent-slate);"></div>

  <div class="card-label" style="margin-bottom:14px;">Guardian Fleet — Daily Uptime Breakdown <span class="tip-cid" data-tip="Shows how each Guardian drone splits its 24 hours between active flying and auto-recharging. The rapid 3-min charge cycle enables near-continuous availability.">?</span></div>

  <div class="prog-row">

    <div class="prog-meta"><span class="prog-label">Airborne (flight) <span class="tip-cid" data-tip="Hours per day each Guardian is actively flying. The 60-min flight / 3-min charge cycle yields ~22.9 hrs of airtime per Guardian per day.">?</span></span><span class="prog-val">{GUARDIAN_FLIGHT_HOURS_PER_DAY:.1f} hrs / 24 hrs</span></div>

    <div class="prog-track"><div class="prog-fill" style="width:{GUARDIAN_FLIGHT_HOURS_PER_DAY/24*100:.1f}%;background:var(--accent-blue);"></div></div>

  </div>

  <div class="prog-row">

    <div class="prog-meta"><span class="prog-label">Charging / Docked <span class="tip-cid" data-tip="Time spent in the automated recharging dock between sorties. The 3-minute recharge gap between 60-min flights is the only downtime — drone is available for re-dispatch within seconds of landing.">?</span></span><span class="prog-val">{24-GUARDIAN_FLIGHT_HOURS_PER_DAY:.1f} hrs / 24 hrs</span></div>

    <div class="prog-track"><div class="prog-fill" style="width:{(24-GUARDIAN_FLIGHT_HOURS_PER_DAY)/24*100:.1f}%;background:var(--rule);"></div></div>

  </div>

  <div class="card-sub" style="margin-top:6px;">Guardian duty cycle: {CONFIG['GUARDIAN_FLIGHT_MIN']} min flight → {CONFIG['GUARDIAN_CHARGE_MIN']} min battery swap → repeat</div>

</div>





<!-- ══════════════════════════════════════════════════════════════════

     SECTION 2 — RESPONSE TIME VS GROUND UNITS

══════════════════════════════════════════════════════════════════ -->

<div class="section-label">02 &nbsp;·&nbsp; Response Time vs. Ground Units <span class="tip-cid" data-tip="Compares estimated drone arrival time to typical ground unit response for incidents within the coverage zone. Drone speed, direct flight path, and instant launch give a systematic time advantage.">?</span></div>

<div class="rt-compare">

  <div class="card-label" style="margin-bottom:0;">Estimated Average Response to In-Range Incidents <span class="tip-cid" data-tip="Average distance from each station to incidents in its zone ÷ drone airspeed = flight time. Ground unit uses the same average distance but at road speed with a 1.4× road-tortuosity factor. Both are model averages.">?</span></div>

  <div class="rt-bars">

    {_resp_bar_html}

    {_guard_bar_html}

    {_ground_bar_html}

    <div class="rt-bar-wrap" style="display:flex;flex-direction:column;align-items:center;justify-content:flex-end;padding-bottom:28px;">

      <div style="font-family:'DM Mono',monospace;font-size:32px;font-weight:500;color:var(--accent-green);">−{saved_min:.1f}m</div>

      <div style="font-size:11px;color:var(--ink-light);text-align:center;margin-top:4px;">avg time saved<br>per call</div>

    </div>

  </div>

  <div>

    <span class="rt-wins-badge">✓ Drone arrives first in an estimated <strong>{drone_wins_pct}%</strong> of in-range calls</span>

    &nbsp;

    <span style="font-size:11px;color:var(--ink-light);">Based on geographic coverage ({calls_covered_perc:.1f}% call coverage) and speed advantage</span>

  </div>

</div>



<!-- Response time detail cards -->

<div class="grid-3" style="margin-bottom:20px;">

  <div class="stat-card">

    <div class="accent-bar" style="background:var(--accent-green);"></div>

    <div class="card-label">Minutes Saved / Call <span class="tip-cid" data-tip="Difference between estimated ground unit response time and drone response time for incidents in the coverage zone. Faster first eyes on scene can reduce harm, improve officer safety, and increase apprehension rates.">?</span></div>

    <div class="card-value" style="color:var(--accent-green);">{saved_min:.1f} min</div>

    <div class="card-sub">vs. estimated ground response</div>

  </div>

  <div class="stat-card">

    <div class="accent-bar" style="background:var(--accent-gold);"></div>

    <div class="card-label">Geographic Coverage <span class="tip-cid" data-tip="Percentage of the total jurisdiction area that falls within at least one drone's operational radius. Reflects spatial reach — a high percentage means most of the city has drone access, not just the dense call-volume areas.">?</span></div>

    <div class="card-value" style="color:var(--accent-gold);">{area_covered_perc:.1f}%</div>

    <div class="card-sub">of jurisdiction area within drone range</div>

  </div>

  <div class="stat-card">

    <div class="accent-bar" style="background:var(--accent-blue);"></div>

    <div class="card-label">Call Coverage <span class="tip-cid" data-tip="Percentage of historical 911 incidents (from uploaded CAD data) that fall within at least one drone's coverage zone. Higher than geographic coverage because stations are positioned near call-volume hotspots.">?</span></div>

    <div class="card-value" style="color:var(--accent-blue);">{calls_covered_perc:.1f}%</div>

    <div class="card-sub">of historical incidents in coverage zones</div>

  </div>

</div>





<!-- ══════════════════════════════════════════════════════════════════

     SECTION 3 — 4TH AMENDMENT SAFEGUARDS

══════════════════════════════════════════════════════════════════ -->

<div class="section-label">03 &nbsp;·&nbsp; Fourth Amendment &amp; Civil Liberties Safeguards <span class="tip-cid" data-tip="Plain-language summary of constitutional and policy guardrails governing every flight. These policies align the program with the 4th Amendment's protections against unreasonable search and the Baltimore Circuit ruling on mass surveillance.">?</span></div>

<div class="amend-panel">

  <div class="amend-title">

    <span>🔒</span>

    Your Rights Are Built Into This Program

  </div>

  <p style="font-size:12.5px;color:var(--ink-mid);line-height:1.6;">

    The {city} DFR program is designed in full compliance with the U.S. Constitution's Fourth Amendment and applicable state law.

    Below is a plain-language summary of the policies that govern every flight. Citizens can request program records under applicable

    open-records laws.

  </p>

  <div class="amend-grid">

    <div class="amend-item">

      <div class="amend-icon">🎯</div>

      <div>

        <div class="amend-item-title">Reactive Dispatch Only <span class="tip-cid" data-tip="Drones only launch in response to active 911 calls or officer requests. No loitering, no speculative patrol, no geofenced monitoring of specific addresses.">?</span></div>

        <div class="amend-item-desc">Drones launch in response to 911 calls and officer requests — never for proactive surveillance or random patrol.</div>

      </div>

    </div>

    <div class="amend-item">

      <div class="amend-icon">📷</div>

      <div>

        <div class="amend-item-title">In-Transit Camera Policy <span class="tip-cid" data-tip="Camera gimbal is locked forward-facing during flight to the scene. Recording and active observation only begin once the drone is confirmed on-station at the incident location — preventing incidental surveillance of bystanders en route.">?</span></div>

        <div class="amend-item-desc">Cameras remain forward-facing during transit and only orient toward a scene upon confirmed arrival at the incident location.</div>

      </div>

    </div>

    <div class="amend-item">

      <div class="amend-icon">🗑️</div>

      <div>

        <div class="amend-item-title">{retention_days}-Day Data Retention <span class="tip-cid" data-tip="All footage is automatically purged after {retention_days} days unless flagged for an active investigation. This prevents the accumulation of persistent video libraries that courts have found to constitute mass surveillance.">?</span></div>

        <div class="amend-item-desc">Footage is retained for a maximum of {retention_days} days absent evidentiary hold. No indefinite video libraries are maintained.</div>

      </div>

    </div>

    <div class="amend-item">

      <div class="amend-icon">🚫</div>

      <div>

        <div class="amend-item-title">No Facial Recognition <span class="tip-cid" data-tip="Drone video is not processed through facial recognition AI. Officers review footage manually. This avoids the bias, error rates, and warrant issues associated with automated biometric identification from aerial imagery.">?</span></div>

        <div class="amend-item-desc">This program does not integrate facial recognition technology with drone footage. Identification is performed by responding officers, not AI.</div>

      </div>

    </div>

    <div class="amend-item">

      <div class="amend-icon">⚖️</div>

      <div>

        <div class="amend-item-title">No 1st Amendment Targeting <span class="tip-cid" data-tip="Drones are prohibited from being dispatched to protests, rallies, or free-speech gatherings. Dispatch logs are auditable and would show any violation of this policy as a policy breach reviewable by the oversight board.">?</span></div>

        <div class="amend-item-desc">Drones will not be dispatched to monitor, document, or surveil lawful protest, assembly, or free-speech activities.</div>

      </div>

    </div>

    <div class="amend-item">

      <div class="amend-icon">📋</div>

      <div>

        <div class="amend-item-title">Public Flight Logs <span class="tip-cid" data-tip="Every sortie is logged: call type, GPS location, duration, and pilot/operator. Records are available to any resident under applicable public records law — providing a transparency trail that deters misuse.">?</span></div>

        <div class="amend-item-desc">Every sortie is logged with call type, location, duration, and purpose. Logs are published and available to any resident on request.</div>

      </div>

    </div>

  </div>

  <div class="amend-disclaimer">

    <strong>Legal Context:</strong> The Fourth Circuit's ruling in <em>Leaders of a Beautiful Struggle v. Baltimore</em> established that mass aerial surveillance violates the Fourth Amendment.

    This program is expressly designed to avoid that pattern: reactive dispatch only, no persistent coverage, strict data retention limits.

    Aerial observations from public navigable airspace are consistent with established Supreme Court doctrine (<em>California v. Ciraolo</em>, 1986) when conducted reactively and without advanced technology directed at private spaces.

  </div>

</div>





<!-- ══════════════════════════════════════════════════════════════════

     SECTION 4 — LIVES SAVED / OUTCOMES

══════════════════════════════════════════════════════════════════ -->

<div class="section-label">04 &nbsp;·&nbsp; Estimated Annual Community Outcomes <span class="tip-cid" data-tip="Model-based projections of public-safety outcomes derived from national DFR program benchmarks applied to this deployment's projected annual flight count. Not guarantees — actual results depend on staffing, call types, and policy.">?</span></div>

<div class="grid-4" style="margin-bottom:4px;">

  <div class="outcome-card" style="animation-delay:0.0s;">

    <span class="outcome-icon">🚔</span>

    <div class="outcome-val"><span class="counter" data-target="{arrests_est}">{arrests_est:,}</span></div>

    <div class="outcome-label">Arrest Assists <span class="tip-cid" data-tip="Estimated arrests aided by live aerial reconnaissance — suspect tracking, real-time officer guidance, perimeter confirmation. Modeled at ~4.3% of annual DFR flights per national benchmark data.">?</span></div>

    <div class="outcome-note">Aerial intel aiding officer apprehension</div>

  </div>

  <div class="outcome-card" style="animation-delay:0.1s;">

    <span class="outcome-icon">🆘</span>

    <div class="outcome-val"><span class="counter" data-target="{rescues_est}">{rescues_est:,}</span></div>

    <div class="outcome-label">Active Rescues <span class="tip-cid" data-tip="Estimated searches or medical emergencies where drone overhead view or thermal imaging directly enabled a successful rescue. Modeled at ~2.1% of annual DFR flights.">?</span></div>

    <div class="outcome-note">Missing persons, medical, extrication</div>

  </div>

  <div class="outcome-card" style="animation-delay:0.2s;">

    <span class="outcome-icon">🕊️</span>

    <div class="outcome-val"><span class="counter" data-target="{deescalation_est}">{deescalation_est:,}</span></div>

    <div class="outcome-label">De-escalations <span class="tip-cid" data-tip="Estimated incidents where real-time aerial awareness allowed officers to approach with better situational intel, reducing the likelihood of a use-of-force incident. Modeled at ~11% of annual DFR flights.">?</span></div>

    <div class="outcome-note">Drone intel prevented use-of-force</div>

  </div>

  <div class="outcome-card" style="animation-delay:0.3s;">

    <span class="outcome-icon">🔍</span>

    <div class="outcome-val"><span class="counter" data-target="{missing_est}">{missing_est:,}</span></div>

    <div class="outcome-label">Missing Person Locates <span class="tip-cid" data-tip="Estimated successful locate events using thermal imaging or wide-area overhead search. Thermal signatures allow drones to find people in the dark or in obscured terrain. Modeled at ~1.7% of annual DFR flights.">?</span></div>

    <div class="outcome-note">Thermal / overhead search assist</div>

  </div>

</div>

<p style="font-size:10.5px;color:var(--ink-light);margin-bottom:20px;font-style:italic;">

  ⚠️ Outcomes are model estimates derived from national DFR program benchmarks (arrest-assist rate ~4.3%, rescue rate ~2.1%, de-escalation rate ~11%) applied to projected annual DFR flights of {total_annual_dfr:,}.

  These are not guarantees of real-world results. Actual outcomes depend on staffing, deployment configuration, policy, and incident types.

</p>





<!-- ══════════════════════════════════════════════════════════════════

     SECTION 5 — CALL TYPE BREAKDOWN

══════════════════════════════════════════════════════════════════ -->

<div class="section-label">05 &nbsp;·&nbsp; Call Type Distribution <span class="tip-cid" data-tip="Distribution of 911 call types from your uploaded CAD data, or national DFR benchmark estimates if no data is loaded. Shows the incident mix the program will most commonly respond to.">?</span></div>

<div class="ct-panel">

  <div class="card-label" style="margin-bottom:14px;">Incident Categories in Coverage Zone <span class="tip-cid" data-tip="Each bar shows the count and share of incidents by type within the drone coverage zones. Bar width is proportional to the highest-volume category. Actual CAD data is used when uploaded; defaults to national DFR benchmarks otherwise.">?</span></div>

  <div id="callTypeBars"></div>

</div>





<!-- ══════════════════════════════════════════════════════════════════

     SECTION 6 — EQUITY NOTE

══════════════════════════════════════════════════════════════════ -->

<div class="section-label">06 &nbsp;·&nbsp; Geographic Equity &amp; Deployment Distribution <span class="tip-cid" data-tip="Documents where drones are deployed and the policy commitments that prevent disproportionate targeting of specific communities. Station locations are determined solely by call-volume density, not demographic data.">?</span></div>

<div class="amend-panel" style="border-left-color:var(--accent-gold);">

  <div class="amend-title"><span>⚖️</span> Equitable Deployment Commitment</div>

  <p style="font-size:12.5px;color:var(--ink-mid);line-height:1.6;margin-bottom:12px;">

    Research has documented that aerial surveillance can be deployed disproportionately in communities of color even when controlling for income.

    The {city} DFR program explicitly tracks deployment patterns by district to ensure equitable coverage.

  </p>

  <div style="display:flex;gap:8px;flex-wrap:wrap;">

    <div style="flex:1;min-width:160px;background:var(--bg-inset);border-radius:6px;padding:8px 10px;">

      <div style="font-size:10px;font-weight:700;color:var(--accent-gold);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:4px;">Deployed Stations <span class="tip-cid" data-tip="The drone stations currently active in this deployment plan. Responder (🚁) covers a 2-mile radius; Guardian (🦅) covers up to 8 miles. Station positions are optimized for maximum call coverage.">?</span></div>

      <div id="stationList" style="font-size:10.5px;color:var(--ink-mid);line-height:1.6;"></div>

    </div>

    <div style="flex:2;min-width:180px;background:var(--bg-inset);border-radius:6px;padding:8px 10px;">

      <div style="font-size:10px;font-weight:700;color:var(--accent-gold);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:4px;">Equity Safeguards <span class="tip-cid" data-tip="Policy commitments that prevent demographic bias in drone deployment. Placement is data-driven (call volume), not population-profile-driven. Audit results and complaint data are published annually.">?</span></div>

      <ul style="font-size:10.5px;color:var(--ink-mid);padding-left:14px;line-height:1.7;margin:0;">

        <li>Coverage zones set by call-volume density, not demographic profile</li>

        <li>Annual deployment audit published in program transparency report</li>

        <li>No algorithmic profiling: dispatch triggered solely by 911 call</li>

        <li>Bias complaints reviewed quarterly by community oversight board</li>

      </ul>

    </div>

  </div>

</div>





<!-- ══════════════════════════════════════════════════════════════════

     SECTION 7 — TAXPAYER ROI

══════════════════════════════════════════════════════════════════ -->

<div class="section-label">07 &nbsp;·&nbsp; Taxpayer Return on Investment <span class="tip-cid" data-tip="Compares the one-time fleet hardware cost to the annual operational savings from drone-handled calls. ROI reflects savings from reduced patrol-car dispatches only — does not include specialty response, apprehension impact, or injury prevention value.">?</span></div>

<div class="roi-panel">

  <div class="roi-row">

    <div class="roi-big">

      <div class="roi-big-val">{roi_multiple:.1f}×</div>

      <div class="roi-big-label">Annual ROI multiple <span class="tip-cid" data-tip="Annual operational savings ÷ total fleet hardware cost. A 2.5× multiple means the program saves $2.50 in recurring operational costs for every $1 of one-time capital investment.">?</span></div>

      <div style="margin-top:10px;font-size:11px;color:var(--ink-light);">For every $1 invested in fleet CapEx, the program generates <strong>${roi_multiple:.2f}</strong> in annual operational savings.</div>

    </div>

    <div class="roi-details">

      <div class="roi-line">

        <span class="roi-line-label">Total Fleet CapEx <span class="tip-cid" data-tip="One-time hardware acquisition cost — Responder (${CONFIG['RESPONDER_COST']:,} each) + Guardian (${CONFIG['GUARDIAN_COST']:,} each). Does not include subscription, maintenance, insurance, or training costs.">?</span></span>

        <span class="roi-line-val">${fleet_capex:,.0f}</span>

      </div>

      <div class="roi-line">

        <span class="roi-line-label">Annual Operational Savings <span class="tip-cid" data-tip="Savings from calls resolved without a patrol car dispatch. Formula: (daily drone-only resolved calls) × ($82 officer cost − $6 drone cost) × 365 days.">?</span></span>

        <span class="roi-line-val" style="color:var(--accent-green);">${annual_savings:,.0f}</span>

      </div>

      <div class="roi-line">

        <span class="roi-line-label">Break-Even Timeline <span class="tip-cid" data-tip="Months until cumulative operational savings fully offset the initial fleet hardware investment. Calculated as fleet CapEx ÷ monthly savings.">?</span></span>

        <span class="roi-line-val">{break_even_text}</span>

      </div>

      <div class="roi-line">

        <span class="roi-line-label">Cost per Drone Response <span class="tip-cid" data-tip="Direct per-dispatch cost comparison. Drone: ~$6 (power, maintenance amortized). Patrol officer: ~$82 (salary, vehicle, fuel, overhead). The $76 difference per resolved call drives the annual savings figure.">?</span></span>

        <span class="roi-line-val">${cost_per_call_drone} vs ${cost_per_call_officer} (patrol)</span>

      </div>

      <div class="roi-line">

        <span class="roi-line-label">Annual Calls Resolved Without Patrol Car <span class="tip-cid" data-tip="Calls where drone assessment was sufficient — no officer dispatch needed. Formula: DFR flights/day × deflection rate (% of drone-handled calls that don't escalate) × 365 days.">?</span></span>

        <span class="roi-line-val">{total_resolved_annually:,}</span>

      </div>

      <div class="roi-line">

        <span class="roi-line-label">Savings Per Resolved Call <span class="tip-cid" data-tip="Net cost delta for each call resolved by drone without a patrol car: $82 (officer dispatch) − $6 (drone dispatch) = $76 saved per resolved call.">?</span></span>

        <span class="roi-line-val" style="color:var(--accent-green);">${cost_saved_per_resolved}</span>

      </div>

      <div class="roi-line" style="border-top:1px solid rgba(239,68,68,0.25);margin-top:8px;padding-top:8px;">

        <span class="roi-line-label" style="color:#ef4444;font-weight:600;">🔥 Est. Annual Fire DFR Responses <span class="tip-cid" data-tip="Fire and rescue calls as a share of total DFR deployments. National average: 15% of DFR flights are fire/rescue-related (NFPA 2022 Fire Loss Report). Formula: total annual DFR × 15%.">?</span></span>

        <span class="roi-line-val">{_annual_fire_dfr:,}</span>

      </div>

      <div class="roi-line">

        <span class="roi-line-label" style="color:#ef4444;">🔥 False Alarm Avoidance Savings <span class="tip-cid" data-tip="Drone arrives first and identifies non-fire events before an engine rolls. False alarm rate: 23% of fire calls (NFPA). Detection rate: 68% of false alarms identified before dispatch (IAFC DFR pilots). Engine response cost: $895/run (NFPA 2023). Formula: fire DFR responses × 23% × 68% × $895.">?</span></span>

        <span class="roi-line-val" style="color:#ef4444;">${_false_alarm_savings:,.0f}/yr</span>

      </div>

      <div class="roi-line">

        <span class="roi-line-label" style="color:#ef4444;">🔥 Pre-Arrival Recon Value <span class="tip-cid" data-tip="Drone streams live video to incoming crew before arrival, enabling faster tactic decisions and reducing LODD risk. Value: $185/incident (IAAI DFR White Paper 2023). Formula: annual fire DFR responses × $185.">?</span></span>

        <span class="roi-line-val" style="color:#ef4444;">${_fire_recon_value:,.0f}/yr</span>

      </div>

      <div class="roi-line" style="border-bottom:none;">

        <span class="roi-line-label" style="font-weight:700;color:#ef4444;">🔥 Total Fire Dept Impact <span class="tip-cid" data-tip="Combined fire department value: false alarm avoidance + pre-arrival scene recon. Does not include hazmat standby, search assist, or equipment-protection value — all additive.">?</span></span>

        <span class="roi-line-val" style="font-weight:700;color:#ef4444;">${_total_fire_value:,.0f}/yr</span>

      </div>

    </div>

  </div>

</div>





<!-- ══════════════════════════════════════════════════════════════════

     FOOTER

══════════════════════════════════════════════════════════════════ -->

<div class="dash-footer">

  <strong>Simulation Disclaimer:</strong> All figures are model estimates based on user-configured deployment parameters, national DFR benchmark rates, and uploaded CAD data.

  Response times, ROI, and outcomes are projections — not guarantees. Actual program results depend on staffing, policy, FAA authorization, and operational execution.

  This dashboard is intended for planning and community transparency purposes only. &nbsp;·&nbsp; Generated by BRINC COS Drone Optimizer.

</div>





<!-- ══════════════════════════════════════════════════════════════════

     SCRIPTS

══════════════════════════════════════════════════════════════════ -->

<script>

// ── Animated counters ──────────────────────────────────────────────────────

function animateCounter(el) {{

  const target = parseFloat(el.dataset.target.replace(/,/g,''));

  const isFloat = el.dataset.target.includes('.');

  const decimals = isFloat ? (el.dataset.target.split('.')[1] || '').length : 0;

  const duration = 1200;

  const start = performance.now();

  function tick(now) {{

    const elapsed = now - start;

    const progress = Math.min(elapsed / duration, 1);

    const ease = 1 - Math.pow(1 - progress, 3);

    const val = target * ease;

    el.textContent = isFloat

      ? val.toLocaleString('en-US', {{minimumFractionDigits:decimals, maximumFractionDigits:decimals}})

      : Math.round(val).toLocaleString('en-US');

    if (progress < 1) requestAnimationFrame(tick);

  }}

  requestAnimationFrame(tick);

}}



const obs = new IntersectionObserver(entries => {{

  entries.forEach(e => {{

    if (e.isIntersecting) {{

      animateCounter(e.target);

      obs.unobserve(e.target);

    }}

  }});

}}, {{threshold: 0.3}});

document.querySelectorAll('.counter').forEach(el => obs.observe(el));



// ── Call type horizontal bars ──────────────────────────────────────────────

const ctData = {ct_items_js};

const ctColors = [

  '#1a56db','#0d9e6e','#b45309','#be123c',

  '#7c3aed','#0369a1','#065f46','#92400e'

];

const ctContainer = document.getElementById('callTypeBars');

const maxPct = Math.max(...ctData.map(d => d.pct));

ctData.forEach((item, i) => {{

  const row = document.createElement('div');

  row.className = 'prog-row';

  row.innerHTML = `

    <div class="prog-meta">

      <span class="prog-label">${{item.label}}</span>

      <span class="prog-val">${{item.count.toLocaleString()}} &nbsp;<span style="color:#94a3b8">(${{item.pct}}%)</span></span>

    </div>

    <div class="prog-track">

      <div class="prog-fill" style="width:${{(item.pct/maxPct*100).toFixed(1)}}%;background:${{ctColors[i%ctColors.length]}};animation-delay:${{i*0.08}}s;"></div>

    </div>`;

  ctContainer.appendChild(row);

}});



// ── Station list ───────────────────────────────────────────────────────────

const stations = {drone_names_js};

const sl = document.getElementById('stationList');

if (stations.length === 0) {{

  sl.innerHTML = '<em style="color:#94a3b8;">No drones deployed yet</em>';

}} else {{

  stations.forEach(s => {{

    const icon = s.type === 'GUARDIAN' ? '🦅' : '🚁';

    const color = s.type === 'GUARDIAN' ? '#FFD700' : '#00D2FF';

    sl.innerHTML += `<div>${{icon}} <span style="color:${{color}};font-weight:600;">${{s.type.charAt(0)+s.type.slice(1).toLowerCase()}}</span> — ${{s.name}}</div>`;

  }});

}}



// ── Auto-resize iframe to actual content height ────────────────────────────

(function() {{

  function reportHeight() {{

    const h = Math.max(

      document.body.scrollHeight,

      document.body.offsetHeight,

      document.documentElement.scrollHeight,

      document.documentElement.offsetHeight

    ) + 40;

    window.parent.postMessage({{isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: h}}, '*');

  }}

  if (document.readyState === 'loading') {{

    document.addEventListener('DOMContentLoaded', reportHeight);

  }} else {{

    reportHeight();

  }}

  window.addEventListener('load', reportHeight);

  [50, 150, 350, 700, 1200, 2000, 3500].forEach(function(t) {{ setTimeout(reportHeight, t); }});

}})();

</script>

</div>

</body>

</html>"""

    return html














