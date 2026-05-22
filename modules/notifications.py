"""
Email and Google Sheets notification system for BRINC app.
"""

import datetime
import json
import smtplib
import html
import re
from pathlib import Path
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials

from modules.versioning import (
    __version__,
    __build_revision__,
    __build_datetime__,
    __build_line_count__,
)


EXPORT_HEADERS = [
    "Source App",
    "Timestamp",
    "Session ID",
    "Session Start",
    "Session Duration (min)",
    "Data Source",
    "BRINC Rep Name",
    "BRINC Rep Email",
    "City",
    "State",
    "Population",
    "Area (sq mi)",
    "Total Annual Calls",
]

SESSION_HEADERS = [
    "Source App",
    "Timestamp",
    "Session ID",
    "Session Start",
    "BRINC Rep Name",
    "BRINC Rep Email",
    "City",
    "State",
    "Population",
    "Total Annual Calls",
    "Data Source",
    "Sim or Upload",
]

PUBLIC_REPORT_HEADERS = [
    "Report ID",
    "Updated At",
    "Source App",
    "Department",
    "City",
    "State",
    "Rep Name",
    "Rep Email",
    "Fleet CapEx",
    "Annual Savings",
    "Call Coverage",
    "Fleet Summary",
    "Stations JSON",
    "Public HTML",
]


def _split_recipients(value):
    """Return a cleaned list of email recipients from a string or iterable."""
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = str(value).replace(";", ",").split(",")
    recipients = []
    for item in raw_items:
        addr = str(item or "").strip()
        if addr:
            recipients.append(addr)
    return recipients


def _sheet_col_label(index):
    """Convert a 1-based column index to an A1-style column label."""
    label = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _build_details_html(details):
    """Shared HTML block for deployment details used in email notifications."""
    if not details:
        return ""
    drone_list = "".join([
        f"<li><b>{d['name']}</b> ({d['type']}) @ {d['lat']:.4f}, {d['lon']:.4f}</li>"
        for d in details.get('active_drones', [])
    ])
    pop   = details.get('population', 0)
    calls = details.get('total_calls', 0)
    daily = details.get('daily_calls', 0)
    area  = details.get('area_sq_mi', 0)
    be    = details.get('break_even', 'N/A')
    src   = details.get('data_source', '—')
    sid   = details.get('session_id', '—')
    stime = details.get('session_start', '—')
    dur   = details.get('session_duration_min', '—')
    avg_t = details.get('avg_response_min', 0)
    time_saved = details.get('avg_time_saved_min', 0)
    area_cov = details.get('area_covered_pct', 0)
    return f"""
    <div style="margin-top:20px; padding-top:20px; border-top:1px solid #f0f0f0;">
        <h4 style="color:#555; margin-bottom:10px;">Session Info</h4>
        <table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:15px;">
            <tr><td style="padding:4px; color:#888; width:50%;">Session ID</td><td style="padding:4px;">{sid}</td></tr>
            <tr><td style="padding:4px; color:#888;">Session Start</td><td style="padding:4px;">{stime}</td></tr>
            <tr><td style="padding:4px; color:#888;">Session Duration</td><td style="padding:4px;">{dur} min</td></tr>
            <tr><td style="padding:4px; color:#888;">Data Source</td><td style="padding:4px;">{src}</td></tr>
        </table>
        <h4 style="color:#555; margin-bottom:10px;">Jurisdiction</h4>
        <table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:15px;">
            <tr><td style="padding:4px; color:#888; width:50%;">Population</td><td style="padding:4px;">{pop:,}</td></tr>
            <tr><td style="padding:4px; color:#888;">Total Annual Calls</td><td style="padding:4px;">{calls:,}</td></tr>
            <tr><td style="padding:4px; color:#888;">Daily Calls</td><td style="padding:4px;">{daily:,}</td></tr>
            <tr><td style="padding:4px; color:#888;">Coverage Area</td><td style="padding:4px;">{area:,} sq mi</td></tr>
        </table>
        <h4 style="color:#555; margin-bottom:10px;">Deployment Settings</h4>
        <table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:15px;">
            <tr><td style="padding:4px; color:#888; width:50%;">Strategy</td><td style="padding:4px;">{details.get('opt_strategy', '')}</td></tr>
            <tr><td style="padding:4px; color:#888;">Incremental Build</td><td style="padding:4px;">{details.get('incremental_build', False)}</td></tr>
            <tr><td style="padding:4px; color:#888;">Allow Overlap</td><td style="padding:4px;">{details.get('allow_redundancy', False)}</td></tr>
            <tr><td style="padding:4px; color:#888;">DFR Dispatch Rate</td><td style="padding:4px;">{details.get('dfr_rate', 0)}%</td></tr>
            <tr><td style="padding:4px; color:#888;">Deflection Rate</td><td style="padding:4px;">{details.get('deflect_rate', 0)}%</td></tr>
            <tr><td style="padding:4px; color:#888;">Total CapEx</td><td style="padding:4px;">${details.get('fleet_capex', 0):,.0f}</td></tr>
            <tr><td style="padding:4px; color:#888;">Annual Savings</td><td style="padding:4px;">${details.get('annual_savings', 0):,.0f}</td></tr>
            <tr><td style="padding:4px; color:#888;">Thermal Upside</td><td style="padding:4px;">${details.get('thermal_savings', 0):,.0f}</td></tr>
            <tr><td style="padding:4px; color:#888;">K-9 Upside</td><td style="padding:4px;">${details.get('k9_savings', 0):,.0f}</td></tr>
            <tr><td style="padding:4px; color:#888;">Break-Even</td><td style="padding:4px;">{be}</td></tr>
            <tr><td style="padding:4px; color:#888;">Avg Response Time</td><td style="padding:4px;">{avg_t:.1f} min</td></tr>
            <tr><td style="padding:4px; color:#888;">Time Saved vs Patrol</td><td style="padding:4px;">{time_saved:.1f} min</td></tr>
            <tr><td style="padding:4px; color:#888;">Geographic Coverage</td><td style="padding:4px;">{area_cov:.1f}%</td></tr>
        </table>
        <h4 style="color:#555; margin-bottom:10px;">Active Drones Placed</h4>
        <ul style="font-size:12px; color:#444; padding-left:20px;">{drone_list}</ul>
    </div>
    """


def _build_sheets_row(city, state, event_type, k_resp, k_guard, coverage, name, email, details=None):
    """Build the flat list of values for a Google Sheets row — single source of truth."""
    d = details or {}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_start = d.get('session_start', now)
    dur = d.get('session_duration_min', '')
    try:
        if dur == '':
            start_dt = datetime.datetime.strptime(session_start, "%Y-%m-%d %H:%M:%S")
            dur = round((datetime.datetime.now() - start_dt).total_seconds() / 60, 1)
    except Exception:
        dur = ''
    try:
        source_app = st.secrets.get("SOURCE_APP", "") or Path(__file__).resolve().parent.parent.name
    except Exception:
        source_app = ""
    return [
        source_app,
        now,
        d.get('session_id', ''),
        session_start,
        dur,
        d.get('data_source', ''),
        name,
        email,
        city,
        state,
        d.get('population', ''),
        d.get('area_sq_mi', ''),
        d.get('total_calls', ''),
    ]


def _notify_email(city, state, file_type, k_resp, k_guard, coverage, name, email, details=None):
    """Send email notification via Gmail."""
    try:
        gmail_address  = st.secrets.get("GMAIL_ADDRESS", "")
        app_password   = st.secrets.get("GMAIL_APP_PASSWORD", "")
        notify_address = st.secrets.get("NOTIFY_EMAIL", gmail_address)
        sms_address = st.secrets.get("NOTIFY_SMS_EMAIL", "")
        recipients = _split_recipients([notify_address, sms_address])
        if not gmail_address or not app_password:
            return
        if not recipients:
            return
        emoji = {"HTML": "📄", "KML": "🌏", "BRINC": "💾", "MAP_BUILD": "🗺️"}.get(file_type, "📥")
        label = {"HTML": "Executive Summary", "KML": "Google Earth Briefing", "BRINC": "BRINC File", "MAP_BUILD": "Map Build"}.get(file_type, file_type.replace('_', ' ').title())
        subject = f"{emoji} BRINC {label} — {city}, {state}"
        details_html = _build_details_html(details)
        d = details or {}
        pop  = d.get('population', 0)
        plain_body = (
            f"BRINC {label} Notification\n"
            f"Event: {label}\n"
            f"Jurisdiction: {city}, {state}\n"
            f"Population: {pop:,}\n"
            f"Fleet: {k_resp} Responder / {k_guard} Guardian\n"
            f"Call Coverage: {coverage:.1f}%\n"
            f"BRINC Rep: {name if name else '—'}\n"
            f"Rep Email: {email if email else '—'}\n"
        )
        body = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;padding:20px;">
        <div style="max-width:560px;margin:0 auto;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
            <div style="background:#000;padding:16px 20px;border-bottom:3px solid #00D2FF;">
                <span style="color:#00D2FF;font-size:18px;font-weight:900;letter-spacing:2px;">BRINC</span>
                <span style="color:#888;font-size:12px;margin-left:8px;">{label} Notification</span>
            </div>
            <div style="padding:20px;">
                <table style="width:100%;border-collapse:collapse;font-size:14px;">
                    <tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:8px 4px;color:#888;width:40%;">Event</td><td style="padding:8px 4px;font-weight:bold;">{emoji} {label}</td></tr>
                    <tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:8px 4px;color:#888;">Jurisdiction</td><td style="padding:8px 4px;font-weight:bold;">{city}, {state}</td></tr>
                    <tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:8px 4px;color:#888;">Population</td><td style="padding:8px 4px;">{pop:,}</td></tr>
                    <tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:8px 4px;color:#888;">Fleet</td><td style="padding:8px 4px;">{k_resp} Responder · {k_guard} Guardian</td></tr>
                    <tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:8px 4px;color:#888;">Call Coverage</td><td style="padding:8px 4px;">{coverage:.1f}%</td></tr>
                    <tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:8px 4px;color:#888;">BRINC Rep</td><td style="padding:8px 4px;">{name if name else '—'}</td></tr>
                    <tr><td style="padding:8px 4px;color:#888;">Rep Email</td><td style="padding:8px 4px;">{f'<a href="mailto:{email}">{email}</a>' if email else '—'}</td></tr>
                </table>
                {details_html}
                <div style="margin-top:16px;font-size:11px;color:#bbb;">{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} UTC</div>
            </div>
        </div>
        <div class="doc-version">v {__version__}</div>
</body></html>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, gmail_address, recipients[0]
        if len(recipients) > 1:
            msg["Cc"] = ", ".join(recipients[1:])
        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as server:
            server.login(gmail_address, app_password)
            server.sendmail(gmail_address, recipients, msg.as_string())
    except:
        pass


def _notify_crash_email(step, error_message, traceback_text, details=None):
    """Send a crash alert email via Gmail."""
    try:
        gmail_address = st.secrets.get("GMAIL_ADDRESS", "")
        app_password = st.secrets.get("GMAIL_APP_PASSWORD", "")
        notify_address = st.secrets.get("NOTIFY_EMAIL", gmail_address)
        sms_address = st.secrets.get("NOTIFY_SMS_EMAIL", "")
        recipients = _split_recipients([notify_address, sms_address])
        if not gmail_address or not app_password or not recipients:
            return

        d = details or {}
        source_app = d.get("source_app", "") or Path(__file__).resolve().parent.parent.name
        session_id = d.get("session_id", "")
        upload_sig = d.get("upload_signature", "")
        user_email = d.get("user_email", "")
        city = d.get("city", "")
        state = d.get("state", "")
        file_count = d.get("file_count", "")
        upload_files = d.get("upload_files", [])
        file_html = ""
        if upload_files:
            file_html = "<ul style='margin:8px 0 0 18px;padding:0;'>" + "".join(
                f"<li>{html.escape(str(name))}</li>" for name in upload_files
            ) + "</ul>"

        subject = f"🚨 BRINC app crash at {step}"
        plain_body = (
            f"BRINC Crash Alert\n"
            f"Step: {step}\n"
            f"Source app: {source_app}\n"
            f"Session ID: {session_id or '-'}\n"
            f"User email: {user_email or '-'}\n"
            f"City/state: {city or '-'}, {state or '-'}\n"
            f"File count: {file_count or '-'}\n"
            f"Upload signature: {upload_sig or '-'}\n"
            f"Error: {error_message}\n"
        )
        body = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;padding:20px;">
        <div style="max-width:720px;margin:0 auto;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
            <div style="background:#7f1d1d;padding:16px 20px;border-bottom:3px solid #ff6b6b;">
                <span style="color:#fff;font-size:18px;font-weight:900;letter-spacing:1px;">BRINC Crash Alert</span>
            </div>
            <div style="padding:20px;">
                <p style="margin:0 0 12px;"><b>Step:</b> {html.escape(str(step))}</p>
                <p style="margin:0 0 12px;"><b>Source app:</b> {html.escape(str(source_app))}</p>
                <p style="margin:0 0 12px;"><b>Session ID:</b> {html.escape(str(session_id or '—'))}</p>
                <p style="margin:0 0 12px;"><b>User email:</b> {html.escape(str(user_email or '—'))}</p>
                <p style="margin:0 0 12px;"><b>City/state:</b> {html.escape(str(city or '—'))}, {html.escape(str(state or '—'))}</p>
                <p style="margin:0 0 12px;"><b>File count:</b> {html.escape(str(file_count or '—'))}</p>
                <p style="margin:0 0 12px;"><b>Upload signature:</b> {html.escape(str(upload_sig or '—'))}</p>
                <p style="margin:0 0 12px;"><b>Error:</b> {html.escape(str(error_message))}</p>
                <div style="margin:16px 0 8px;font-weight:bold;">Uploaded files</div>
                {file_html or "<div style='color:#666;'>None</div>"}
                <div style="margin:16px 0 8px;font-weight:bold;">Traceback</div>
                <pre style="white-space:pre-wrap;word-wrap:break-word;background:#f7f7f7;border:1px solid #eee;padding:12px;border-radius:6px;font-size:12px;line-height:1.45;">{html.escape(str(traceback_text))}</pre>
                <div style="margin-top:16px;font-size:11px;color:#888;">{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} UTC</div>
            </div>
        </div>
        </body></html>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, gmail_address, recipients[0]
        if len(recipients) > 1:
            msg["Cc"] = ", ".join(recipients[1:])
        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as server:
            server.login(gmail_address, app_password)
            server.sendmail(gmail_address, recipients, msg.as_string())
    except:
        pass


def _notify_crash_email_html_only_legacy(step, error_message, traceback_text, details=None):
    """Send a crash alert email via Gmail."""
    try:
        gmail_address = st.secrets.get("GMAIL_ADDRESS", "")
        app_password = st.secrets.get("GMAIL_APP_PASSWORD", "")
        notify_address = st.secrets.get("NOTIFY_EMAIL", gmail_address)
        sms_address = st.secrets.get("NOTIFY_SMS_EMAIL", "")
        recipients = _split_recipients([notify_address, sms_address])
        if not gmail_address or not app_password or not recipients:
            return

        d = details or {}
        source_app = d.get("source_app", "") or Path(__file__).resolve().parent.parent.name
        session_id = d.get("session_id", "")
        upload_sig = d.get("upload_signature", "")
        user_email = d.get("user_email", "")
        city = d.get("city", "")
        state = d.get("state", "")
        file_count = d.get("file_count", "")
        upload_files = d.get("upload_files", [])
        file_html = ""
        if upload_files:
            file_html = "<ul style='margin:8px 0 0 18px;padding:0;'>" + "".join(
                f"<li>{html.escape(str(name))}</li>" for name in upload_files
            ) + "</ul>"

        subject = f"🚨 BRINC app crash at {step}"
        body = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;padding:20px;">
        <div style="max-width:720px;margin:0 auto;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
            <div style="background:#7f1d1d;padding:16px 20px;border-bottom:3px solid #ff6b6b;">
                <span style="color:#fff;font-size:18px;font-weight:900;letter-spacing:1px;">BRINC Crash Alert</span>
            </div>
            <div style="padding:20px;">
                <p style="margin:0 0 12px;"><b>Step:</b> {html.escape(str(step))}</p>
                <p style="margin:0 0 12px;"><b>Source app:</b> {html.escape(str(source_app))}</p>
                <p style="margin:0 0 12px;"><b>Session ID:</b> {html.escape(str(session_id or '—'))}</p>
                <p style="margin:0 0 12px;"><b>User email:</b> {html.escape(str(user_email or '—'))}</p>
                <p style="margin:0 0 12px;"><b>City/state:</b> {html.escape(str(city or '—'))}, {html.escape(str(state or '—'))}</p>
                <p style="margin:0 0 12px;"><b>File count:</b> {html.escape(str(file_count or '—'))}</p>
                <p style="margin:0 0 12px;"><b>Upload signature:</b> {html.escape(str(upload_sig or '—'))}</p>
                <p style="margin:0 0 12px;"><b>Error:</b> {html.escape(str(error_message))}</p>
                <div style="margin:16px 0 8px;font-weight:bold;">Uploaded files</div>
                {file_html or "<div style='color:#666;'>None</div>"}
                <div style="margin:16px 0 8px;font-weight:bold;">Traceback</div>
                <pre style="white-space:pre-wrap;word-wrap:break-word;background:#f7f7f7;border:1px solid #eee;padding:12px;border-radius:6px;font-size:12px;line-height:1.45;">{html.escape(str(traceback_text))}</pre>
                <div style="margin-top:16px;font-size:11px;color:#888;">{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} UTC</div>
            </div>
        </div>
        </body></html>
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, gmail_address, recipients[0]
        if len(recipients) > 1:
            msg["Cc"] = ", ".join(recipients[1:])
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as server:
            server.login(gmail_address, app_password)
            server.sendmail(gmail_address, recipients, msg.as_string())
    except:
        pass


def _ensure_sheet_headers(sheet):
    """Best-effort header sync for the main export log worksheet."""
    try:
        first_row = sheet.row_values(1)
        current_headers = [value.strip() if isinstance(value, str) else value for value in first_row]
        desired_headers = EXPORT_HEADERS[:]
        if current_headers == desired_headers:
            return
        target_len = max(len(current_headers), len(desired_headers))
        padded_headers = desired_headers + [""] * (target_len - len(desired_headers))
        end_col = _sheet_col_label(target_len)
        sheet.update(f"A1:{end_col}1", [padded_headers])
    except Exception:
        pass


USER_HEADERS = [
    "Email",
    "Name",
    "First Seen",
    "Last Seen",
    "Total Logins",
    "Total Exports",
    "Cities Evaluated",
    "Largest Fleet CapEx ($)",
]


def _upsert_user(spreadsheet, email, name, *, increment_logins=False, increment_exports=False, city=None, fleet_capex=None):
    """Upsert a row in the Users sheet — one row per unique email."""
    try:
        try:
            sheet = spreadsheet.worksheet("Users")
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title="Users", rows=1000, cols=len(USER_HEADERS))
            sheet.append_row(USER_HEADERS)

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        all_values = sheet.get_all_values()
        if not all_values:
            sheet.append_row(USER_HEADERS)
            all_values = [USER_HEADERS]

        col = {h: i for i, h in enumerate(all_values[0])}

        user_row_idx = None
        for i, row in enumerate(all_values[1:], start=2):
            if row and len(row) > col.get("Email", 0) and row[col["Email"]] == email:
                user_row_idx = i
                break

        if user_row_idx is None:
            new_row = [""] * len(USER_HEADERS)
            new_row[col["Email"]] = email
            new_row[col["Name"]] = name
            new_row[col["First Seen"]] = now
            new_row[col["Last Seen"]] = now
            new_row[col["Total Logins"]] = 1 if increment_logins else 0
            new_row[col["Total Exports"]] = 1 if increment_exports else 0
            new_row[col["Cities Evaluated"]] = city or ""
            new_row[col["Largest Fleet CapEx ($)"]] = fleet_capex or ""
            sheet.append_row(new_row)
        else:
            row_data = list(all_values[user_row_idx - 1])
            while len(row_data) < len(USER_HEADERS):
                row_data.append("")

            row_data[col["Last Seen"]] = now
            if name:
                row_data[col["Name"]] = name

            if increment_logins:
                try:
                    row_data[col["Total Logins"]] = int(row_data[col["Total Logins"]] or 0) + 1
                except (ValueError, TypeError):
                    row_data[col["Total Logins"]] = 1

            if increment_exports:
                try:
                    row_data[col["Total Exports"]] = int(row_data[col["Total Exports"]] or 0) + 1
                except (ValueError, TypeError):
                    row_data[col["Total Exports"]] = 1

            if city:
                existing = row_data[col["Cities Evaluated"]] or ""
                cities = [c.strip() for c in existing.split(",") if c.strip()]
                if city not in cities:
                    cities.append(city)
                row_data[col["Cities Evaluated"]] = ", ".join(cities)

            if fleet_capex:
                try:
                    if float(fleet_capex) > float(row_data[col["Largest Fleet CapEx ($)"]] or 0):
                        row_data[col["Largest Fleet CapEx ($)"]] = fleet_capex
                except (ValueError, TypeError):
                    row_data[col["Largest Fleet CapEx ($)"]] = fleet_capex

            end_col = _sheet_col_label(len(USER_HEADERS))
            sheet.update(f"A{user_row_idx}:{end_col}{user_row_idx}", [row_data[:len(USER_HEADERS)]])
    except Exception:
        pass


def _log_to_sheets(city, state, file_type, k_resp, k_guard, coverage, name, email, details=None):
    """Log deployment to Google Sheets. MAP_BUILD events go to Sessions sheet; all others to sheet1."""
    try:
        sheet_id = st.secrets.get("GOOGLE_SHEET_ID", "")
        creds_dict = st.secrets.get("gcp_service_account", {})
        if not sheet_id or not creds_dict:
            return
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(dict(creds_dict), scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sheet_id)

        if file_type == 'MAP_BUILD':
            try:
                sessions_sheet = spreadsheet.worksheet("Sessions")
            except gspread.exceptions.WorksheetNotFound:
                sessions_sheet = spreadsheet.add_worksheet(title="Sessions", rows=1000, cols=len(SESSION_HEADERS))
                sessions_sheet.append_row(SESSION_HEADERS)
            d = details or {}
            try:
                source_app = st.secrets.get("SOURCE_APP", "") or Path(__file__).resolve().parent.parent.name
            except Exception:
                source_app = ""
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sessions_sheet.append_row([
                source_app,
                now,
                d.get('session_id', ''),
                d.get('session_start', now),
                name,
                email,
                city,
                state,
                d.get('population', ''),
                d.get('total_calls', ''),
                d.get('data_source', ''),
                d.get('sim_or_upload', ''),
            ])
            return

        sheet = spreadsheet.sheet1
        _ensure_sheet_headers(sheet)
        row = _build_sheets_row(city, state, file_type, k_resp, k_guard, coverage, name, email, details)
        sheet.append_row(row)
        d = details or {}
        _upsert_user(spreadsheet, email, name,
                     increment_exports=True,
                     city=city,
                     fleet_capex=d.get('fleet_capex'))
    except:
        pass


def _write_crash_report(step, error_message, traceback_text, details=None):
    """Write a local crash report and return the saved file path."""
    try:
        report_dir = Path(st.secrets.get("CRASH_REPORT_DIR", "") or Path(__file__).resolve().parent.parent / "crash_reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        safe_step = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(step or "crash")).strip("._-") or "crash"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"{safe_step}_{timestamp}.txt"
        d = details or {}
        lines = [
            f"Step: {step}",
            f"Error: {error_message}",
            f"Source app: {d.get('source_app', '')}",
            f"Session ID: {d.get('session_id', '')}",
            f"User email: {d.get('user_email', '')}",
            f"City: {d.get('city', '')}",
            f"State: {d.get('state', '')}",
            f"File count: {d.get('file_count', '')}",
            f"Upload signature: {d.get('upload_signature', '')}",
            "",
            "Traceback:",
            str(traceback_text or ""),
            "",
        ]
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return str(report_path)
    except Exception:
        return ""


def _log_login_to_sheets(email, name):
    """Log user login to Google Sheets (separate LOGIN sheet)."""
    try:
        sheet_id = st.secrets.get("GOOGLE_SHEET_ID", "")
        creds_dict = st.secrets.get("gcp_service_account", {})
        if not sheet_id or not creds_dict:
            return
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(dict(creds_dict), scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sheet_id)

        try:
            sheet = spreadsheet.worksheet("Logins")
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title="Logins", rows=1000, cols=10)
            sheet.append_row(["Timestamp", "Email", "Name", "Event"])

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, email, name, "LOGIN"])
        _upsert_user(spreadsheet, email, name, increment_logins=True)
    except:
        pass


def _log_qr_scan_to_sheets(report_id, city, state, rep_name, rep_email,
                           device="", user_agent="", language="", ip=""):
    """Log a QR code scan to a dedicated QR Scans sheet."""
    try:
        sheet_id = st.secrets.get("GOOGLE_SHEET_ID", "")
        creds_dict = st.secrets.get("gcp_service_account", {})
        if not sheet_id or not creds_dict:
            return
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(dict(creds_dict), scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sheet_id)

        try:
            sheet = spreadsheet.worksheet("QR Scans")
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title="QR Scans", rows=1000, cols=12)
            sheet.append_row([
                "Timestamp", "Source App", "Report ID",
                "City", "State", "Rep Name", "Rep Email",
                "Device", "Language", "IP Address", "User Agent",
            ])

        try:
            source_app = st.secrets.get("SOURCE_APP", "") or Path(__file__).resolve().parent.parent.name
        except Exception:
            source_app = ""

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([
            timestamp, source_app, report_id,
            city, state, rep_name, rep_email,
            device, language, ip, user_agent,
        ])
    except:
        pass


def _publish_public_report_to_sheets(report_id, department, city, state, rep_name, rep_email,
                                     fleet_capex, annual_savings, call_coverage,
                                     fleet_summary, stations_json, public_html):
    """Upsert one public-facing report row into a dedicated public spreadsheet."""
    try:
        sheet_id = st.secrets.get("PUBLIC_REPORTS_SHEET_ID", "")
        creds_dict = st.secrets.get("gcp_service_account", {})
        if not sheet_id or not creds_dict:
            return
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(dict(creds_dict), scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sheet_id)
        worksheet_name = str(st.secrets.get("PUBLIC_REPORTS_WORKSHEET", "Public Reports") or "Public Reports")

        try:
            sheet = spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=max(20, len(PUBLIC_REPORT_HEADERS)))
            sheet.append_row(PUBLIC_REPORT_HEADERS)

        first_row = sheet.row_values(1)
        if [str(v).strip() for v in first_row] != PUBLIC_REPORT_HEADERS:
            end_col = _sheet_col_label(len(PUBLIC_REPORT_HEADERS))
            sheet.update(f"A1:{end_col}1", [PUBLIC_REPORT_HEADERS])

        try:
            source_app = st.secrets.get("SOURCE_APP", "") or Path(__file__).resolve().parent.parent.name
        except Exception:
            source_app = ""

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            report_id,
            timestamp,
            source_app,
            department,
            city,
            state,
            rep_name,
            rep_email,
            fleet_capex,
            annual_savings,
            call_coverage,
            fleet_summary,
            stations_json,
            public_html,
        ]

        values = sheet.get_all_values()
        row_idx = None
        for i, existing in enumerate(values[1:], start=2):
            if existing and existing[0] == report_id:
                row_idx = i
                break

        end_col = _sheet_col_label(len(PUBLIC_REPORT_HEADERS))
        if row_idx is None:
            sheet.append_row(row)
        else:
            sheet.update(f"A{row_idx}:{end_col}{row_idx}", [row])
    except:
        pass
