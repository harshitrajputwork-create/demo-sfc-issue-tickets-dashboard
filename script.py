#!/usr/bin/env python3
"""
Custom Report Script
Purpose: Issue Tickets Dashboard -- SLA, TAT, Overdue, and Status Analytics
Tenant:  SFC (Southern Franchise Company LLC)
"""
import io
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from datetime import timedelta

# -- Constants ----------------------------------------------------------------
SUBDOMAIN           = "sfc"
BASE_URL            = f"https://{SUBDOMAIN}.taqtics.co"
DEFAULT_OUTPUT_FILE = "output.html"
DATE_FMT            = "%d %B %Y  %I:%M %p"

# All due dates in the Taqtics CSV are in Dubai / UAE Standard Time (UTC+4).
# Using UTC+4 here ensures our overdue checks match the Taqtics portal exactly
# regardless of which timezone the machine running this script is in.
NOW_UTC = datetime.now(timezone.utc).replace(tzinfo=None)   # UTC, no tz-info
NOW     = NOW_UTC + timedelta(hours=4)                       # Dubai / UAE Standard Time (UTC+4)

STATUS_LABELS = {
    "open":       "Open",
    "inProgress": "In Progress",
    "completed":  "Completed",
    "closed":     "Closed",
    "onHold":     "On Hold",
    "rejected":   "Rejected",
}
PRIORITY_LABELS = {
    "highest": "Highest",
    "high":    "High",
    "medium":  "Medium",
    "low":     "Low",
    "lowest":  "Lowest",
}
BRAND_LABELS = {
    "India_Palace":      "India Palace",
    "sfc_Plus":          "SFC Plus",
    "Golden_Dragon":     "Golden Dragon",
    "Sfcs":              "SFCS",
    "Sthan":             "Sthan",
    "Mikhnan":           "Miknan",
    "49ers_SteakHouse":  "49ers Steakhouse",
    "Catering_Division": "Catering Division",
}
CITY_FIX = {
    "ABU DHABI": "Abu Dhabi",
    "DUBAI":     "Dubai",
}


# -- .env loader --------------------------------------------------------------
def load_dotenv(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        return
    with env_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"(\w+)\s*=\s*(.*)", line)
            if not m:
                continue
            key, value = m.group(1), m.group(2)
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if key not in os.environ:
                os.environ[key] = value


def initialize_environment():
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def resolve_output_path():
    output_file = os.environ.get("OUTPUT_FILE")
    if output_file:
        return Path(output_file)
    workspace = Path(os.environ.get("WORKSPACE_PATH") or Path.cwd())
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace / DEFAULT_OUTPUT_FILE


# -- Data Fetching -- Pattern C -----------------------------------------------
def authenticate():
    email    = os.environ.get("TAQTICS_EMAIL")
    password = os.environ.get("TAQTICS_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "TAQTICS_EMAIL and TAQTICS_PASSWORD must be set (e.g. via .env). "
            "NOTE: the copy of this script uploaded to the Taqtics Custom "
            "Reports portal has these hardcoded, since that platform does "
            "not support supplying a separate .env file."
        )
    resp = requests.post(
        f"{BASE_URL}/api/v1/internal/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "token" not in data:
        raise RuntimeError(f"Auth failed: {data.get('message', str(data))}")
    print("Authenticated successfully")
    return data["token"], data["userId"]


def fetch_source_dataframe():
    token, user_id = authenticate()
    headers = {
        "access-token": token,
        "userId":       user_id,
        "subdomain":    SUBDOMAIN,
        "timeZone":     "Asia/Dubai",
        "workspace":    SUBDOMAIN,
        "Content-Type": "application/json",
    }
    body = {
        "status":          "total",
        "tenantRole":      "Admin",
        "dateRange":       {
            "from": "2026-01-01T00:00:00Z",
            "to":   NOW_UTC.strftime("%Y-%m-%dT%H:%M:%SZ"),   # API expects UTC
        },
        "filter":          False,
        "selectedFilters": {},
    }
    resp = requests.post(
        f"{BASE_URL}/api/v1/internal/ticket/csv/download",
        json=body,
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    print(f"Fetched {len(df)} ticket records")
    return df


# -- Data Processing ----------------------------------------------------------
def _parse_dt(s):
    if pd.isna(s) or str(s).strip() in ("--", ""):
        return pd.NaT
    s = re.sub(r"\s+", " ", str(s)).strip()
    for fmt in (DATE_FMT, "%d %B %Y %I:%M %p"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return pd.NaT


def _fmt_dt(d):
    return "--" if pd.isna(d) else d.strftime("%d %b %Y %I:%M %p")


def prepare_dataframe(df):
    df = df.copy()

    df["status"] = df["Status"].map(STATUS_LABELS).fillna(
        df["Status"].fillna("Open")
    )
    df["priority"] = df["Priority"].map(PRIORITY_LABELS).fillna(
        df["Priority"].fillna("Medium").str.capitalize()
    )
    df["brand"] = df["Brand"].map(BRAND_LABELS).fillna(
        df["Brand"].fillna("").str.replace("_", " ").str.strip()
    )
    df["city"] = df["City"].apply(
        lambda c: CITY_FIX.get(str(c).strip(), str(c).strip()) if pd.notna(c) else ""
    )

    for raw_col, out_col in [
        ("Created At",   "created_dt"),
        ("Due Date",     "due_dt"),
        ("Claimed At",   "claimed_dt"),
        ("Completed At", "completed_dt"),
        ("Closed At",    "closed_dt"),
    ]:
        df[out_col] = df[raw_col].apply(_parse_dt)

    df["month"] = df["created_dt"].apply(
        lambda d: d.strftime("%b%Y") if pd.notna(d) else ""
    )
    df["closed_month"] = df["closed_dt"].apply(
        lambda d: d.strftime("%b%Y") if pd.notna(d) else ""
    )
    df["completed_month"] = df["completed_dt"].apply(
        lambda d: d.strftime("%b%Y") if pd.notna(d) else ""
    )
    df["__sort"] = df["created_dt"].apply(
        lambda d: d.strftime("%Y%m") if pd.notna(d) else ""
    )

    # TAT in hours (CSV stores minutes)
    df["sla_hr"]            = (df["SLA (Min)"]           / 60).round(2)
    df["response_tat_hr"]   = (df["Response TAT (Min)"]  / 60).round(2)
    df["onhold_tat_hr"]     = (df["OnHold TAT (Min)"]    / 60).round(2)
    df["completion_tat_hr"] = (df["Completed TAT (Min)"] / 60).round(2)
    df["closure_tat_hr"]    = (df["Closed TAT (Min)"]    / 60).round(2)

    def _overdue(row):
        raw = str(row.get("Status", "")).lower()
        if raw == "closed":
            c, s = row["closure_tat_hr"], row["sla_hr"]
            return bool(pd.notna(c) and pd.notna(s) and s > 0 and c > s)
        elif raw == "completed":
            c, s = row["completion_tat_hr"], row["sla_hr"]
            return bool(pd.notna(c) and pd.notna(s) and s > 0 and c > s)
        elif raw in ("open", "inprogress", "onhold"):
            due = row["due_dt"]
            return bool(pd.notna(due) and due < NOW)
        return False  # rejected

    df["is_overdue"] = df.apply(_overdue, axis=1)

    def _days_overdue(row):
        """Days the ticket has been overdue (0 if not overdue)."""
        if not row["is_overdue"]:
            return 0.0
        raw = str(row.get("Status", "")).lower()
        if raw == "closed":
            c, s = row["closure_tat_hr"], row["sla_hr"]
            return max(0.0, (c - s) / 24) if (pd.notna(c) and pd.notna(s)) else 0.0
        elif raw == "completed":
            c, s = row["completion_tat_hr"], row["sla_hr"]
            return max(0.0, (c - s) / 24) if (pd.notna(c) and pd.notna(s)) else 0.0
        else:
            due = row["due_dt"]
            if pd.isna(due):
                return 0.0
            return max(0.0, (NOW - due).total_seconds() / 86400)

    df["days_overdue"] = df.apply(_days_overdue, axis=1)

    df["created_at_fmt"]   = df["created_dt"].apply(_fmt_dt)
    df["due_date_fmt"]     = df["due_dt"].apply(_fmt_dt)
    df["claimed_at_fmt"]   = df["claimed_dt"].apply(_fmt_dt)
    df["completed_at_fmt"] = df["completed_dt"].apply(_fmt_dt)
    df["closed_at_fmt"]    = df["closed_dt"].apply(_fmt_dt)

    return df


def build_table_rows(df):
    def _v(x):
        return None if pd.isna(x) else float(x)

    def _ts(d):
        """Unix timestamp in ms for JS date comparisons."""
        return int(d.timestamp() * 1000) if pd.notna(d) else None

    def _clean_events(s):
        if pd.isna(s) or not str(s).strip():
            return ""
        return str(s).strip()

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "ticket_id":          str(r.get("Ticket Id", "") or ""),
            "title":              str(r.get("Title", "") or ""),
            "store":              str(r.get("Store", "") or ""),
            "brand":              str(r["brand"]),
            "category":           str(r.get("Category", "") or ""),
            "sub_category":       str(r.get("Sub Category 1", "") or ""),
            "status":             str(r["status"]),
            "priority":           str(r["priority"]),
            "city":               str(r["city"]),
            "area":               str(r.get("Area", "") or ""),
            "created_by":         str(r.get("Created By", "") or ""),
            "claimed_by":         (lambda v: "Not Claimed" if (pd.isna(v) or str(v).strip() in ("","nan")) else str(v).strip())(r.get("Claimed By","")),
            "closure_assignees":  str(r.get("Closure Assignees", "") or ""),
            "escalated":          str(r.get("Escalated", "No") or "No"),
            "reopen":             str(r.get("Reopen", "No") or "No"),
            "month":              str(r["month"]),
            "closed_month":       str(r["closed_month"]),
            "completed_month":    str(r["completed_month"]),
            "__sort":             str(r["__sort"]),
            "sla_hr":             _v(r["sla_hr"]),
            "response_tat_hr":    _v(r["response_tat_hr"]),
            "completion_tat_hr":  _v(r["completion_tat_hr"]),
            "closure_tat_hr":     _v(r["closure_tat_hr"]),
            "onhold_tat_hr":      _v(r["onhold_tat_hr"]),
            "is_overdue":         bool(r["is_overdue"]),
            "days_overdue":       round(float(r["days_overdue"]), 2),
            "cost":               _v(r.get("Cost")),
            "created_ts":         _ts(r["created_dt"]),
            "created_at":         str(r["created_at_fmt"]),
            "due_date":           str(r["due_date_fmt"]),
            "claimed_at":         str(r["claimed_at_fmt"]),
            "completed_at":       str(r["completed_at_fmt"]),
            "closed_at":          str(r["closed_at_fmt"]),
            "events_trigger":     _clean_events(r.get("Events Trigger")),
        })
    return rows


# -- CSS ----------------------------------------------------------------------
def _build_css():
    return """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: Arial, "Segoe UI", sans-serif;
    font-size: 14px;
    background: #f1f5f9;
    color: #1e293b;
    min-height: 100vh;
}

/* ── Header ── */
.header {
    background: linear-gradient(135deg, #6B0000 0%, #C62828 55%, #8B1A1A 100%);
    color: #fff;
    padding: 14px 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
    border-bottom: 3px solid #D4A017;
}
.header-logo {
    height: 52px; width: auto; border-radius: 6px;
    background: #fff; padding: 4px; object-fit: contain;
    display: none;   /* shown via JS if file exists */
}
.header-logo.loaded { display: block; }
.header-left { display: flex; align-items: center; gap: 14px; }
.header-left h1 { font-size: 19px; font-weight: 700; letter-spacing: -0.3px; }
.header-left p  { font-size: 12px; opacity: 0.80; margin-top: 3px; }
.header-right   { font-size: 11px; opacity: 0.80; text-align: right; line-height: 1.7; }

/* ── Count / Overdue toggle ── */
.view-toggle {
    display: flex;
    gap: 0;
    background: rgba(0,0,0,0.25);
    border-radius: 8px;
    padding: 3px;
    border: 1px solid rgba(212,160,23,0.4);
}
.view-toggle button {
    padding: 7px 22px;
    border: none;
    border-radius: 5px;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    background: transparent;
    color: rgba(255,255,255,0.75);
    transition: all 0.15s;
    letter-spacing: 0.3px;
}
.view-toggle button.active {
    background: #fff;
    color: #C62828;
    box-shadow: 0 1px 4px rgba(0,0,0,.30);
}
.view-toggle button.active.btn-overdue { color: #ef4444; }

/* ── Overdue mode banner ── */
.overdue-banner {
    display: none;
    background: #fef2f2;
    border-bottom: 2px solid #fecaca;
    padding: 8px 28px;
    font-size: 13px;
    font-weight: 600;
    color: #991b1b;
    align-items: center;
    gap: 8px;
}
.overdue-banner.visible { display: flex; }

/* ── Filter bar ── */
.filter-bar {
    position: sticky;
    top: 0;
    z-index: 100;
    background: #fff;
    border-bottom: 1px solid #e2e8f0;
    padding: 10px 28px;
    display: flex;
    align-items: flex-end;
    gap: 16px;
    flex-wrap: wrap;
    box-shadow: 0 2px 8px rgba(0,0,0,.10);
}
.filter-group { display: flex; flex-direction: column; gap: 3px; }
.filter-group label {
    font-size: 10px; font-weight: 700; color: #64748b;
    text-transform: uppercase; letter-spacing: 0.6px;
}
.filter-group select {
    font-size: 13px; padding: 5px 10px;
    border: 1px solid #cbd5e1; border-radius: 5px;
    background: #fff; min-width: 130px; cursor: pointer; color: #1e293b;
}
.filter-group select:focus { outline: none; border-color: #1a73e8; box-shadow: 0 0 0 2px #1a73e820; }
.reset-btn {
    padding: 6px 16px; background: transparent; border: 1px solid #94a3b8;
    border-radius: 5px; cursor: pointer; font-size: 13px; color: #64748b;
    margin-bottom: 1px; transition: all 0.15s;
}
.reset-btn:hover { background: #f1f5f9; border-color: #64748b; color: #334155; }

/* ── KPI strip ── */
.kpi-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
    gap: 14px;
    padding: 20px 28px 8px;
}
.kpi-card {
    background: #fff; border-radius: 10px; border-top: 3px solid;
    padding: 16px 18px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
}
.kpi-label {
    font-size: 10px; font-weight: 700; color: #64748b;
    text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 8px;
}
.kpi-value {
    font-size: 30px; font-weight: 800;
    font-variant-numeric: tabular-nums; line-height: 1;
}
.kpi-sub { font-size: 11px; color: #94a3b8; margin-top: 5px; line-height: 1.5; }
.kpi-ageing { font-size: 11px; color: #64748b; margin-top: 5px; line-height: 1.8; }
.kpi-ageing span { display: inline-block; margin-right: 6px; }
.kpi-status-badges { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.kpi-status-row {
    display: flex; align-items: center; justify-content: space-between;
    font-size: 12px;
}
.kpi-status-row .badge { font-size: 10px; padding: 2px 8px; }
.kpi-status-row .cnt { font-weight: 700; font-variant-numeric: tabular-nums; }

/* ── Charts ── */
.charts-row { display: flex; gap: 14px; margin: 14px 28px 0; }
.chart-panel {
    background: #fff; border-radius: 10px;
    box-shadow: 0 1px 3px rgba(0,0,0,.08); min-width: 0;
    /* overflow: visible so i-button tooltips are not clipped */
}
.chart-panel.wide   { flex: 3; }
.chart-panel.narrow { flex: 2; }
.chart-panel.half   { flex: 1; }
.panel-hdr {
    padding: 12px 16px; border-bottom: 1px solid #f1f5f9;
    font-weight: 700; font-size: 13px; color: #334155;
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.panel-hdr .overdue-label { color: #ef4444; font-size: 11px; font-weight: 600; }
.toggle-grp { display: flex; gap: 14px; }
.toggle-grp label {
    font-size: 12px; font-weight: 400; cursor: pointer; color: #64748b;
    display: flex; align-items: center; gap: 4px;
}
.toggle-grp input[type="radio"] { cursor: pointer; accent-color: #1a73e8; }

/* ── Sections (tables) ── */
.section {
    margin: 14px 28px 0; background: #fff; border-radius: 10px;
    box-shadow: 0 1px 3px rgba(0,0,0,.08); overflow: hidden;
}
.section:last-child { margin-bottom: 28px; }
.section-hdr {
    padding: 14px 18px 12px; font-weight: 700; font-size: 14px; color: #1e293b;
    border-bottom: 1px solid #f1f5f9; display: flex; align-items: center;
    justify-content: space-between; gap: 8px;
}
.section-hdr .overdue-label { color: #ef4444; font-size: 12px; font-weight: 600; }
.section-count {
    font-size: 12px; font-weight: 600; color: #64748b;
    background: #f1f5f9; border-radius: 20px; padding: 2px 10px;
}
.search-box {
    display: block; margin: 10px 18px;
    padding: 7px 12px; border: 1px solid #e2e8f0; border-radius: 5px;
    font-size: 13px; width: calc(100% - 36px); color: #1e293b;
}
.search-box:focus { outline: none; border-color: #1a73e8; box-shadow: 0 0 0 2px #1a73e820; }
.table-wrap { overflow-x: auto; }

/* ── Data tables ── */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th {
    background: #1e293b; color: #fff; font-weight: 700; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.4px;
    padding: 9px 12px; text-align: left;
    border-bottom: 2px solid #0f172a; white-space: nowrap;
    user-select: none; cursor: pointer;
}
.data-table th:hover { background: #334155; color: #fff; }
.data-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
.data-table tr:last-child td { border-bottom: none; }
.data-table tbody tr:hover td { background: #f8fafc; }
.overdue-row td { background: #fff5f5 !important; }
.sort-icon { font-size: 10px; margin-left: 3px; color: rgba(255,255,255,0.35); }
.sort-icon.active { color: #60a5fa; }

/* ── Summary table color cells ── */
.cell-l1  { background: #f0fdf4; color: #166534; font-weight: 600; text-align: right; }
.cell-l2  { background: #fefce8; color: #854d0e; font-weight: 600; text-align: right; }
.cell-l3  { background: #fff7ed; color: #9a3412; font-weight: 600; text-align: right; }
.cell-l4  { background: #fef2f2; color: #991b1b; font-weight: 700; text-align: right; }
.cell-zero { color: #94a3b8; text-align: right; }
.cell-overdue { background: #fef2f2; color: #dc2626; font-weight: 700; text-align: right; }

/* ── Detail table cells ── */
.sid-cell  { font-size: 11px; color: #94a3b8; font-family: monospace; white-space: nowrap; }
.date-cell { font-size: 12px; white-space: nowrap; color: #475569; }
.num       { text-align: right; font-variant-numeric: tabular-nums; font-size: 13px; }
.title-cell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Badges ── */
.badge {
    display: inline-block; padding: 2px 9px; border-radius: 12px;
    font-size: 11px; font-weight: 700; color: #fff; white-space: nowrap;
}
.tag-overdue { color: #ef4444; font-weight: 700; font-size: 12px; }
.tag-ok      { color: #10b981; font-size: 12px; }

/* ── Pagination ── */
.pagination {
    padding: 12px 18px; display: flex; align-items: center;
    justify-content: space-between; border-top: 1px solid #f1f5f9;
    flex-wrap: wrap; gap: 8px;
}
.page-info { font-size: 13px; color: #64748b; }
.page-btns { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.page-btns button {
    padding: 4px 10px; border: 1px solid #e2e8f0; border-radius: 4px;
    background: #fff; font-size: 12px; cursor: pointer; color: #334155;
    transition: background 0.1s;
}
.page-btns button:disabled { opacity: 0.4; cursor: not-allowed; }
.page-btns button.active   { background: #1a73e8; color: #fff; border-color: #1a73e8; }
.page-btns button:hover:not(:disabled):not(.active) { background: #f1f5f9; }
.ellipsis { padding: 4px 6px; font-size: 12px; color: #94a3b8; }

.empty-state {
    padding: 40px; text-align: center; color: #94a3b8; font-size: 14px;
}

/* ── Info button (panel headers, white background) ── */
.info-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 15px; height: 15px; border-radius: 50%;
    background: #e2e8f0; color: #64748b; font-size: 9px; font-weight: 800;
    cursor: help; margin-left: 5px; vertical-align: middle;
    border: none; font-style: italic; font-family: serif; flex-shrink: 0;
}

/* ── Info button variant for dark table headers ── */
.info-btn-hdr {
    display: inline-flex; align-items: center; justify-content: center;
    width: 13px; height: 13px; border-radius: 50%;
    background: rgba(255,255,255,0.18); color: rgba(255,255,255,0.9);
    font-size: 9px; font-weight: 800; cursor: help; margin-left: 4px;
    vertical-align: middle; border: none; font-style: italic; font-family: serif;
    flex-shrink: 0; text-transform: none; letter-spacing: 0;
}

/* ── Global floating tooltip — JS-positioned, works inside overflow:hidden ── */
#global-tip {
    position: fixed; background: #1e293b; color: #fff;
    font-size: 12px; font-weight: 400; padding: 9px 13px; border-radius: 8px;
    max-width: 320px; line-height: 1.6; pointer-events: none;
    z-index: 9999; box-shadow: 0 6px 20px rgba(0,0,0,.35);
    display: none; white-space: pre-line;
    font-style: normal; font-family: Arial, "Segoe UI", sans-serif;
}

/* ── Info banner (Count vs Overdue) ── */
.info-banner {
    display: none; background: #eff6ff; border-left: 4px solid #3b82f6;
    padding: 14px 18px; margin: 0 28px 12px; border-radius: 6px;
    font-size: 13px; color: #1e293b; line-height: 1.7;
}
.info-banner.visible { display: block; }
.info-banner-close {
    float: right; background: none; border: none; cursor: pointer;
    font-size: 18px; color: #94a3b8; padding: 0; margin: -2px 0 0 0;
}
.info-banner-close:hover { color: #1e293b; }
.info-banner-title { font-weight: 700; margin-bottom: 8px; display: flex; justify-content: space-between; }
.info-banner-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.info-banner-col h4 { font-weight: 700; font-size: 12px; color: #475569; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.4px; }
.info-banner-col ul { list-style: none; padding: 0; margin: 0; }
.info-banner-col li { padding: 3px 0; color: #475569; }
.info-banner-col li:before { content: "• "; color: #3b82f6; font-weight: 700; margin-right: 6px; }

/* ── Activity modal ── */
.modal-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,.45); z-index: 500;
    align-items: center; justify-content: center;
}
.modal-overlay.visible { display: flex; }
.modal-box {
    background: #fff; border-radius: 12px; padding: 24px;
    max-width: 600px; width: 92%; max-height: 80vh; overflow-y: auto;
    box-shadow: 0 20px 60px rgba(0,0,0,.3);
}
.modal-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 16px; gap: 12px;
}
.modal-tid   { font-size: 12px; font-family: monospace; color: #94a3b8; }
.modal-title { font-size: 14px; font-weight: 700; color: #1e293b; margin-top: 2px; }
.modal-close {
    background: none; border: none; font-size: 22px; cursor: pointer;
    color: #94a3b8; line-height: 1; padding: 0; flex-shrink: 0;
}
.modal-close:hover { color: #1e293b; }
.event-line {
    padding: 8px 0; border-bottom: 1px solid #f1f5f9;
    font-size: 13px; color: #334155; line-height: 1.5;
    display: flex; gap: 8px; align-items: flex-start;
}
.event-line:last-child { border-bottom: none; }
.event-dot {
    width: 7px; height: 7px; border-radius: 50%; background: #1a73e8;
    margin-top: 5px; flex-shrink: 0;
}
.activity-btn {
    background: none; border: 1px solid #e2e8f0; border-radius: 4px;
    padding: 2px 8px; font-size: 11px; color: #64748b; cursor: pointer;
    white-space: nowrap;
}
.activity-btn:hover { background: #f1f5f9; color: #1e293b; }

/* ── Date range inputs ── */
.filter-group input[type=date] {
    font-size: 13px; padding: 5px 8px;
    border: 1px solid #cbd5e1; border-radius: 5px;
    background: #fff; color: #1e293b; cursor: pointer;
    min-width: 130px;
}
.filter-group input[type=date]:focus {
    outline: none; border-color: #1a73e8; box-shadow: 0 0 0 2px #1a73e820;
}

/* ── TAT radio toggle inside chart ── */
.tat-options { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.tat-options label {
    font-size: 12px; color: #64748b; cursor: pointer;
    display: flex; align-items: center; gap: 3px;
}
.tat-options input[type=radio] { accent-color: #1a73e8; cursor: pointer; }
"""


def _build_js():
    return r"""
const STATUS_COLORS = {
    'Open':        '#3b82f6',
    'In Progress': '#f59e0b',
    'On Hold':     '#94a3b8',
    'Completed':   '#10b981',
    'Closed':      '#475569',
    'Rejected':    '#ef4444'
};
const PRIORITY_COLORS = {
    'Highest': '#7f1d1d',
    'High':    '#ef4444',
    'Medium':  '#f59e0b',
    'Low':     '#10b981',
    'Lowest':  '#3b82f6'
};
const STATUS_ORDER   = ['Open','In Progress','On Hold','Completed','Closed','Rejected'];
const PRIORITY_ORDER = ['Highest','High','Medium','Low','Lowest'];
const ACTIVE_STATUS  = ['Open','In Progress','On Hold'];

// TAT column definitions — reused across all table headers
const TAT_TIPS = {
    sla_hr:
        'SLA — Allowed Time (Hr)\n' +
        'The total time allowed between ticket creation and its due date.\n' +
        'Formula: Due Date − Created At',
    response_tat_hr:
        'Response TAT (Hr)\n' +
        'Time taken to claim or first respond to the ticket.\n' +
        'Formula: Claimed At − Created At',
    onhold_tat_hr:
        'OnHold TAT (Hr)\n' +
        'Total time the ticket was paused in On-Hold status.\n' +
        'Formula: Sum of all On-Hold durations',
    completion_tat_hr:
        'Completion TAT (Hr)\n' +
        'Time to complete the ticket, excluding On-Hold pauses.\n' +
        'Formula: Completed At − Created At − On-Hold duration',
    closure_tat_hr:
        'Closure TAT (Hr)\n' +
        'Time to formally close the ticket, excluding On-Hold pauses.\n' +
        'Formula: Closed At − Created At − On-Hold duration',
};

// ── Global floating tooltip (works through overflow:hidden) ───────────────────
(function () {
    let tipEl;
    function gt() { return tipEl || (tipEl = document.getElementById('global-tip')); }
    document.addEventListener('mouseover', function (e) {
        const el = e.target.closest('[data-tip]');
        const t  = gt();
        if (!el) { t.style.display = 'none'; return; }
        t.textContent    = el.getAttribute('data-tip');
        t.style.display  = 'block';
    });
    document.addEventListener('mousemove', function (e) {
        const t = gt();
        if (t.style.display === 'none') return;
        let x = e.clientX + 18, y = e.clientY + 14;
        const tw = t.offsetWidth, th = t.offsetHeight;
        if (x + tw > window.innerWidth  - 8) x = e.clientX - tw - 18;
        if (y + th > window.innerHeight - 8) y = e.clientY - th - 14;
        t.style.left = x + 'px';
        t.style.top  = y + 'px';
    });
    document.addEventListener('mouseout', function (e) {
        if (!e.target.closest('[data-tip]')) return;
        if (!e.relatedTarget || !e.relatedTarget.closest('[data-tip]')) {
            gt().style.display = 'none';
        }
    });
})();

// ── Global state ─────────────────────────────────────────────────────────────
let overdueMode   = false;
let state         = { month: 'all', brand: 'all', category: 'all', status: 'all', priority: 'all', city: 'all', dateFrom: null, dateTo: null };
let summarySort   = { col: 'total', dir: -1 };
let detailSort    = { col: '__sort', dir: -1 };
let assigneeSort  = { col: 'tickets', dir: -1 };
let detailPage    = 1;
let summaryPage   = 1;
let assigneePage  = 1;
let detailSearch  = '';
let summarySearch = '';
let tatGroupBy       = 'brand';
let tatView          = 'completion';
let trendBarMode     = 'stack';
let recurringGroupBy = 'category';
let costGroupBy      = 'category';
let userBarMetric    = 'tickets';
let userSearch       = '';
const PER_PAGE    = 50;

// ── View mode toggle ──────────────────────────────────────────────────────────
function setViewMode(mode) {
    overdueMode = (mode === 'overdue');
    document.getElementById('btn-count').classList.toggle('active', !overdueMode);
    document.getElementById('btn-overdue').classList.toggle('active', overdueMode);
    const banner = document.getElementById('overdue-banner');
    banner.classList.toggle('visible', overdueMode);
    refresh();
}

function toggleViewInfo() {
    const infoBanner = document.getElementById('view-info-banner');
    infoBanner.classList.toggle('visible');
}

function closeViewInfo() {
    document.getElementById('view-info-banner').classList.remove('visible');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function sortArrow(col, s) {
    if (s.col !== col) return '<span class="sort-icon">&#8645;</span>';
    return s.dir === 1
        ? '<span class="sort-icon active">&#9650;</span>'
        : '<span class="sort-icon active">&#9660;</span>';
}

function sortData(arr, col, dir) {
    return [...arr].sort((a, b) => {
        const va = a[col], vb = b[col];
        if (va === null || va === undefined) return 1;
        if (vb === null || vb === undefined) return -1;
        if (typeof va === 'boolean') return dir * (Number(va) - Number(vb));
        if (typeof va === 'number')  return dir * (va - vb);
        return dir * String(va).localeCompare(String(vb));
    });
}

function avg(arr) {
    return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
}

function fmtHr(v) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    return v.toFixed(1);
}

function renderPagination(id, totalPages, currentPage, setFn, totalItems) {
    const el = document.getElementById(id);
    if (!el) return;
    if (totalItems === 0) { el.innerHTML = ''; return; }
    const start = (currentPage - 1) * PER_PAGE + 1;
    const end   = Math.min(currentPage * PER_PAGE, totalItems);
    let html = `<span class="page-info">Showing ${start}–${end} of ${totalItems}</span>`;
    if (totalPages > 1) {
        html += '<div class="page-btns">';
        html += `<button onclick="${setFn}(${currentPage-1})" ${currentPage===1?'disabled':''}>Prev</button>`;
        let prev = 0;
        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || (i >= currentPage-2 && i <= currentPage+2)) {
                if (prev && i-prev > 1) html += '<span class="ellipsis">...</span>';
                html += `<button onclick="${setFn}(${i})" class="${i===currentPage?'active':''}">${i}</button>`;
                prev = i;
            }
        }
        html += `<button onclick="${setFn}(${currentPage+1})" ${currentPage===totalPages?'disabled':''}>Next</button>`;
        html += '</div>';
    }
    el.innerHTML = html;
}

// ── Filtering ─────────────────────────────────────────────────────────────────
function getFilteredRows() {
    return TABLE_DATA.filter(row => {
        if (overdueMode && !row.is_overdue)                          return false;
        if (state.month !== 'all' && row.month !== state.month) return false;
        if (state.brand    !== 'all' && row.brand    !== state.brand)    return false;
        if (state.category !== 'all' && row.category !== state.category) return false;
        if (state.status   !== 'all' && row.status   !== state.status)   return false;
        if (state.priority !== 'all' && row.priority !== state.priority) return false;
        if (state.city     !== 'all' && row.city     !== state.city)     return false;
        if (state.dateFrom && row.created_ts && row.created_ts < state.dateFrom) return false;
        if (state.dateTo   && row.created_ts && row.created_ts > state.dateTo)   return false;
        return true;
    });
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function computeStats(rows) {
    const total     = rows.length;
    const open      = rows.filter(r => r.status === 'Open').length;
    const inProg    = rows.filter(r => r.status === 'In Progress').length;
    const onHold    = rows.filter(r => r.status === 'On Hold').length;
    const completed = rows.filter(r => r.status === 'Completed').length;
    const closed    = rows.filter(r => r.status === 'Closed').length;
    const rejected  = rows.filter(r => r.status === 'Rejected').length;
    const overdue   = rows.filter(r => r.is_overdue).length;
    const escalated = rows.filter(r => r.escalated === 'Yes').length;
    const reopened  = rows.filter(r => r.reopen === 'Yes').length;
    const notCompleted = open + inProg + onHold;   // active (not resolved)

    // Overdue ageing buckets:
    // Count mode  → active overdue only (actionable, still open past due date)
    // Overdue mode → all overdue (full picture incl. closed/completed SLA breaches)
    const allOverdueRows = rows.filter(r => r.is_overdue);
    const kpiOverdueRows = overdueMode
        ? allOverdueRows
        : allOverdueRows.filter(r => ACTIVE_STATUS.includes(r.status));
    const activeOverdue = kpiOverdueRows.length;
    const ag1 = kpiOverdueRows.filter(r => r.days_overdue <= 7).length;
    const ag2 = kpiOverdueRows.filter(r => r.days_overdue > 7  && r.days_overdue <= 15).length;
    const ag3 = kpiOverdueRows.filter(r => r.days_overdue > 15 && r.days_overdue <= 30).length;
    const ag4 = kpiOverdueRows.filter(r => r.days_overdue > 30).length;

    const rTATs  = rows.filter(r => r.response_tat_hr !== null).map(r => r.response_tat_hr);
    const cTATs  = rows.filter(r => r.completion_tat_hr !== null).map(r => r.completion_tat_hr);
    const avgResp = avg(rTATs);
    const avgComp = avg(cTATs);
    const slaPct  = total > 0 ? ((total - overdue) / total * 100) : 0;

    const costRows  = rows.filter(r => r.cost !== null && r.cost !== undefined);
    const totalCost = costRows.reduce((s, r) => s + r.cost, 0);
    const avgCost   = costRows.length ? totalCost / costRows.length : 0;
    const costCount = costRows.length;

    return {
        total, open, inProg, onHold, completed, closed, rejected,
        overdue, escalated, reopened, notCompleted,
        activeOverdue, ag1, ag2, ag3, ag4,
        avgResp, avgComp, slaPct,
        totalCost, avgCost, costCount
    };
}

// ── KPIs ──────────────────────────────────────────────────────────────────────
function renderKpis(stats) {
    const overdueSubHtml = `
        <div class="kpi-ageing">
            <span>0-7d: <strong>${stats.ag1}</strong></span>
            <span>8-15d: <strong>${stats.ag2}</strong></span>
            <span>16-30d: <strong>${stats.ag3}</strong></span>
            <span>30+d: <strong>${stats.ag4}</strong></span>
        </div>`;

    const statusBadgesHtml = `
        <div class="kpi-status-badges">
            ${ACTIVE_STATUS.map(s => {
                const cnt = TABLE_DATA.filter(r =>
                    r.status === s &&
                    (state.month === 'all' || r.month === state.month)
                ).length;
                return `<div class="kpi-status-row">
                    <span class="badge" style="background:${STATUS_COLORS[s]}">${s}</span>
                    <span class="cnt">${cnt}</span>
                </div>`;
            }).join('')}
        </div>`;

    const kpis = [
        {
            label: 'Total Tickets', value: stats.total, accent: '#1a73e8',
            sub: `Active (not resolved): ${stats.notCompleted}`
        },
        {
            label: 'Open', value: stats.open, accent: '#3b82f6',
            sub: `In Progress: ${stats.inProg} | On Hold: ${stats.onHold}`
        },
        {
            label: 'Completed', value: stats.completed, accent: '#10b981',
            sub: `Closed: ${stats.closed} | Rejected: ${stats.rejected}`
        },
        {
            label: overdueMode ? 'Overdue Tickets' : 'Active Overdue',
            value: stats.activeOverdue,
            accent: '#ef4444',
            warn: stats.activeOverdue > 0,
            sub: overdueMode ? null : `Closed/Completed breach: ${stats.overdue - stats.activeOverdue}`,
            extra: overdueSubHtml
        },
        {
            label: 'SLA Compliance', value: stats.slaPct.toFixed(1) + '%', accent: '#8b5cf6',
            sub: `Avg Resp: ${fmtHr(stats.avgResp)} hr | Avg Comp: ${fmtHr(stats.avgComp)} hr`
        },
        {
            label: 'Escalated', value: stats.escalated, accent: '#f97316',
            sub: `Reopened: ${stats.reopened}`
        },
        {
            label: 'Status (Active)', value: '', accent: '#64748b',
            extra: statusBadgesHtml
        },
        ...(stats.costCount > 0 ? [{
            label: 'Cost Recorded', value: stats.totalCost.toFixed(0), accent: '#0891b2',
            sub: `${stats.costCount} tickets | Avg: ${stats.avgCost.toFixed(0)}`
        }] : []),
    ];

    document.getElementById('kpi-strip').innerHTML = kpis.map(k => `
        <div class="kpi-card" style="border-top-color:${k.accent}">
            <div class="kpi-label">${k.label}</div>
            ${k.value !== '' ? `<div class="kpi-value" style="color:${k.warn?'#ef4444':k.accent}">${k.value}</div>` : ''}
            ${k.sub   ? `<div class="kpi-sub">${k.sub}</div>` : ''}
            ${k.extra ? k.extra : ''}
        </div>`).join('');
}

// ── Chart helpers ─────────────────────────────────────────────────────────────
const CHART_CFG = { responsive: true, displayModeBar: false };
const BASE_LAYOUT = {
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    font: { family: 'Arial, Segoe UI, sans-serif', size: 12, color: '#334155' },
    margin: { l: 50, r: 20, t: 36, b: 50 },
};

function accentColor() {
    return overdueMode ? '#ef4444' : '#1a73e8';
}

function overdueLabel(title) {
    return overdueMode ? `${title} <span class="overdue-label">(Overdue Only)</span>` : title;
}

// ── Chart renders ─────────────────────────────────────────────────────────────
function renderTrendChart(rows) {
    const monthMap = {};
    rows.forEach(r => {
        if (!r.month) return;
        if (!monthMap[r.month]) {
            monthMap[r.month] = {};
            STATUS_ORDER.forEach(s => { monthMap[r.month][s] = 0; });
        }
        if (monthMap[r.month][r.status] !== undefined) monthMap[r.month][r.status]++;
    });
    const months  = META.months.filter(m => monthMap[m]);
    const xLabels = months.map(m => META.month_labels[m] || m);

    let traces;
    if (overdueMode) {
        traces = [{
            name: 'Overdue', x: xLabels,
            y: months.map(m => {
                const v = monthMap[m] || {};
                return STATUS_ORDER.reduce((s, k) => s + (v[k] || 0), 0);
            }),
            type: 'bar',
            marker: { color: '#ef4444' },
            hovertemplate: '%{y} overdue<extra></extra>',
        }];
    } else {
        traces = STATUS_ORDER.map(s => ({
            name: s, x: xLabels,
            y: months.map(m => (monthMap[m] || {})[s] || 0),
            type: 'bar',
            marker: { color: STATUS_COLORS[s] },
            hovertemplate: '%{y} tickets<extra>' + s + '</extra>',
        }));
    }

    Plotly.react('chart-trend', traces, {
        ...BASE_LAYOUT,
        barmode: trendBarMode,
        xaxis: { title: '', tickfont: { size: 11 } },
        yaxis: { title: 'Tickets' },
        legend: { orientation: 'h', y: -0.22, font: { size: 11 } },
        margin: { l: 45, r: 16, t: 16, b: 80 },
        height: 310,
    }, CHART_CFG);

    document.getElementById('trend-title').innerHTML = overdueLabel('Monthly Ticket Trend');
}

function renderStatusChart(rows) {
    const counts = {};
    rows.forEach(r => { counts[r.status] = (counts[r.status] || 0) + 1; });
    const labels = STATUS_ORDER.filter(s => counts[s]);
    if (!labels.length) { Plotly.react('chart-status', [], { ...BASE_LAYOUT, height: 280 }, CHART_CFG); return; }

    const colors = overdueMode
        ? labels.map(() => '#ef4444')
        : labels.map(s => STATUS_COLORS[s] || '#999');

    Plotly.react('chart-status', [{
        labels, values: labels.map(s => counts[s]),
        type: 'pie', hole: 0.52,
        marker: { colors },
        textinfo: 'percent', hoverinfo: 'label+value+percent',
        textfont: { size: 11 },
    }], {
        ...BASE_LAYOUT,
        margin: { l: 10, r: 10, t: 16, b: 10 },
        legend: { orientation: 'v', font: { size: 11 } },
        height: 310,
    }, CHART_CFG);

    document.getElementById('status-title').innerHTML = overdueLabel('Status Distribution');
}

function renderBrandChart(rows) {
    const counts = {};
    rows.forEach(r => { if (r.brand) counts[r.brand] = (counts[r.brand] || 0) + 1; });
    const brands = Object.keys(counts).sort((a, b) => counts[a] - counts[b]);
    Plotly.react('chart-brand', [{
        x: brands.map(b => counts[b]), y: brands,
        type: 'bar', orientation: 'h',
        marker: { color: accentColor() },
        text: brands.map(b => counts[b]), textposition: 'outside',
        hovertemplate: '%{y}: %{x} tickets<extra></extra>',
    }], {
        ...BASE_LAYOUT,
        xaxis: { title: 'Tickets' },
        margin: { l: 140, r: 50, t: 16, b: 40 },
        height: 310,
    }, CHART_CFG);

    document.getElementById('brand-title').innerHTML = overdueLabel('Tickets by Brand');
}

// Priority x Status stacked bar (replaces plain priority donut)
function renderPriorityStatusChart(rows) {
    // Show all tickets for the P×S chart (not just active) so it's useful in both modes
    const data = {};
    PRIORITY_ORDER.forEach(p => {
        data[p] = {};
        STATUS_ORDER.forEach(s => { data[p][s] = 0; });
    });
    rows.forEach(r => {
        if (data[r.priority] && data[r.priority][r.status] !== undefined) {
            data[r.priority][r.status]++;
        }
    });
    const activePriorities = PRIORITY_ORDER.filter(p =>
        STATUS_ORDER.some(s => data[p][s] > 0)
    );

    const statusesToShow = overdueMode
        ? STATUS_ORDER.filter(s => activePriorities.some(p => data[p][s] > 0))
        : ACTIVE_STATUS;

    const colors = overdueMode
        ? statusesToShow.map(() => '#ef4444')
        : statusesToShow.map(s => STATUS_COLORS[s]);

    const traces = statusesToShow.map((s, i) => ({
        name: s,
        x: activePriorities,
        y: activePriorities.map(p => data[p][s] || 0),
        type: 'bar',
        marker: { color: overdueMode
            ? ['#fca5a5','#f87171','#ef4444','#dc2626','#b91c1c'][i % 5]
            : STATUS_COLORS[s] },
        hovertemplate: s + ' – %{y} tickets (%{x})<extra></extra>',
    }));

    Plotly.react('chart-priority-status', traces, {
        ...BASE_LAYOUT,
        barmode: 'stack',
        xaxis: { title: 'Priority', tickfont: { size: 11 } },
        yaxis: { title: 'Tickets' },
        legend: { orientation: 'h', y: -0.26, font: { size: 11 } },
        margin: { l: 45, r: 16, t: 16, b: 80 },
        height: 310,
    }, CHART_CFG);

    document.getElementById('priority-status-title').innerHTML =
        overdueLabel('Priority x Status Distribution');
}

function renderCategoryChart(rows) {
    const counts = {};
    rows.forEach(r => { if (r.category) counts[r.category] = (counts[r.category] || 0) + 1; });
    let cats = Object.keys(counts).sort((a, b) => counts[b] - counts[a]).slice(0, 12);
    cats = cats.reverse();
    Plotly.react('chart-category', [{
        x: cats.map(c => counts[c]), y: cats,
        type: 'bar', orientation: 'h',
        marker: { color: overdueMode ? '#ef4444' : '#10b981' },
        text: cats.map(c => counts[c]), textposition: 'outside',
        hovertemplate: '%{y}: %{x} tickets<extra></extra>',
    }], {
        ...BASE_LAYOUT,
        xaxis: { title: 'Tickets' },
        margin: { l: 200, r: 50, t: 16, b: 40 },
        height: 360,
    }, CHART_CFG);

    document.getElementById('category-title').innerHTML = overdueLabel('Top Categories');
}

function renderTATChart(rows) {
    const TAT_META = {
        completion: { field: 'comp', label: 'Completion TAT', color: '#10b981',
                      tip: 'Time from creation to completion, excluding on-hold pauses (hours). Actual working time to resolve.' },
        closure:    { field: 'clos', label: 'Closure TAT',    color: '#475569',
                      tip: 'Time from creation to formal closure, excluding on-hold pauses (hours). Final sign-off timeline.' },
    };
    const groups = {};
    rows.forEach(r => {
        const key = r[tatGroupBy] || '(Unknown)';
        if (!groups[key]) groups[key] = { resp: [], comp: [], clos: [] };
        if (r.response_tat_hr   !== null) groups[key].resp.push(r.response_tat_hr);
        if (r.completion_tat_hr !== null) groups[key].comp.push(r.completion_tat_hr);
        if (r.closure_tat_hr    !== null) groups[key].clos.push(r.closure_tat_hr);
    });
    const m    = TAT_META[tatView] || TAT_META.completion;
    const keys = Object.keys(groups).sort((a, b) => avg(groups[a][m.field]) - avg(groups[b][m.field]));
    const trace = {
        name: m.label, type: 'bar', orientation: 'h',
        x: keys.map(k => parseFloat(avg(groups[k][m.field]).toFixed(1))),
        y: keys,
        marker: { color: overdueMode ? '#ef4444' : m.color },
        text: keys.map(k => avg(groups[k][m.field]).toFixed(1) + ' hr'),
        textposition: 'outside',
        hovertemplate: '%{y} — %{x} hr avg<extra>' + m.label + '</extra>',
    };
    const lMargin = tatGroupBy === 'category' ? 200 : 140;
    Plotly.react('chart-tat', [trace], {
        ...BASE_LAYOUT,
        xaxis: { title: 'Avg Hours' },
        margin: { l: lMargin, r: 70, t: 16, b: 40 },
        height: 360,
    }, CHART_CFG);
    // sync i-button tooltip
    const ibtn = document.getElementById('tat-info-btn');
    if (ibtn) ibtn.setAttribute('data-tip', m.tip);
}

// ── Escalation by Category ────────────────────────────────────────────────────
function renderEscalationCatChart(rows) {
    const counts = {};
    rows.filter(r => r.escalated === 'Yes').forEach(r => {
        if (r.category) counts[r.category] = (counts[r.category] || 0) + 1;
    });
    let cats = Object.keys(counts).sort((a, b) => counts[a] - counts[b]).slice(-12);
    if (!cats.length) {
        Plotly.react('chart-escalation-cat', [], { ...BASE_LAYOUT, height: 320 }, CHART_CFG);
        return;
    }
    Plotly.react('chart-escalation-cat', [{
        x: cats.map(c => counts[c]), y: cats,
        type: 'bar', orientation: 'h',
        marker: { color: overdueMode ? '#ef4444' : '#f97316' },
        text: cats.map(c => counts[c]), textposition: 'outside',
        hovertemplate: '%{y}: %{x} escalated<extra></extra>',
    }], {
        ...BASE_LAYOUT,
        xaxis: { title: 'Escalated Tickets' },
        margin: { l: 200, r: 50, t: 16, b: 40 },
        height: 320,
    }, CHART_CFG);
}

// ── Department Risk Chart ─────────────────────────────────────────────────────
function renderRiskChart(rows) {
    const data = {};
    rows.filter(r => ['Open','In Progress','On Hold'].includes(r.status)).forEach(r => {
        if (!r.category) return;
        if (!data[r.category]) data[r.category] = { high: 0, esc: 0 };
        if (r.priority === 'Highest' || r.priority === 'High') data[r.category].high++;
        if (r.escalated === 'Yes') data[r.category].esc++;
    });
    const entries = Object.entries(data)
        .map(([cat, d]) => ({ cat, high: d.high, esc: d.esc }))
        .filter(e => e.high + e.esc > 0)
        .sort((a, b) => (a.high + a.esc) - (b.high + b.esc))
        .slice(-12);
    if (!entries.length) {
        Plotly.react('chart-risk', [], { ...BASE_LAYOUT, height: 320 }, CHART_CFG);
        return;
    }
    Plotly.react('chart-risk', [
        {
            name: 'High / Highest Priority',
            x: entries.map(e => e.high), y: entries.map(e => e.cat),
            type: 'bar', orientation: 'h',
            marker: { color: '#ef4444' },
            hovertemplate: '%{y}: %{x} high-priority open tickets<extra></extra>',
        },
        {
            name: 'Escalated',
            x: entries.map(e => e.esc), y: entries.map(e => e.cat),
            type: 'bar', orientation: 'h',
            marker: { color: '#f97316' },
            hovertemplate: '%{y}: %{x} escalated open tickets<extra></extra>',
        },
    ], {
        ...BASE_LAYOUT,
        barmode: 'stack',
        legend: { orientation: 'h', y: -0.22, font: { size: 11 } },
        xaxis: { title: 'Pending Tickets' },
        margin: { l: 200, r: 50, t: 16, b: 60 },
        height: 320,
    }, CHART_CFG);
}

// ── Recurring Issues — Month-over-Month Comparison ────────────────────────────
// Shows which categories/stores raised tickets in BOTH the current and previous
// month, making it easy to spot persistent/recurring problem areas.
function renderRecurringChart(allFilteredRows) {
    const months = META.months;  // sorted e.g. ['Jan2026','Feb2026',...]

    // Determine "current" month: if user has a month selected use that, else latest
    const currentMonth = (state.month !== 'all') ? state.month : months[months.length - 1];
    const currentIdx   = months.indexOf(currentMonth);
    const prevMonth    = currentIdx > 0 ? months[currentIdx - 1] : null;

    // Re-filter TABLE_DATA ignoring month/date-range (so we can compare months freely).
    const baseRows = TABLE_DATA.filter(row => {
        if (overdueMode && !row.is_overdue)                              return false;
        if (state.brand    !== 'all' && row.brand    !== state.brand)    return false;
        if (state.category !== 'all' && row.category !== state.category) return false;
        if (state.status   !== 'all' && row.status   !== state.status)   return false;
        if (state.priority !== 'all' && row.priority !== state.priority) return false;
        if (state.city     !== 'all' && row.city     !== state.city)     return false;
        return true;
    });

    const grpKey = recurringGroupBy;  // 'category' or 'store'
    const currCounts = {}, prevCounts = {};

    baseRows.filter(r => r.month === currentMonth).forEach(r => {
        const k = r[grpKey]; if (k) currCounts[k] = (currCounts[k] || 0) + 1;
    });
    if (prevMonth) {
        baseRows.filter(r => r.month === prevMonth).forEach(r => {
            const k = r[grpKey]; if (k) prevCounts[k] = (prevCounts[k] || 0) + 1;
        });
    }

    // Show only keys that appear in the current month (top 12 by count); grey bar
    // shows previous month volume for easy comparison.
    const allKeys = Object.keys(currCounts).sort((a, b) => currCounts[b] - currCounts[a]).slice(0, 12).reverse();

    if (!allKeys.length) {
        Plotly.react('chart-recurring', [], { ...BASE_LAYOUT, height: 340 }, CHART_CFG);
        return;
    }

    const currLabel = META.month_labels[currentMonth] || currentMonth;
    const prevLabel = prevMonth ? (META.month_labels[prevMonth] || prevMonth) : null;

    const traces = [];
    if (prevLabel) {
        traces.push({
            name: prevLabel + ' (prev)',
            x: allKeys.map(k => prevCounts[k] || 0), y: allKeys,
            type: 'bar', orientation: 'h',
            marker: { color: '#cbd5e1' },
            hovertemplate: '%{y}: %{x} tickets — ' + prevLabel + '<extra></extra>',
        });
    }
    traces.push({
        name: currLabel + ' (current)',
        x: allKeys.map(k => currCounts[k] || 0), y: allKeys,
        type: 'bar', orientation: 'h',
        marker: { color: overdueMode ? '#ef4444' : '#8b5cf6' },
        text: allKeys.map(k => currCounts[k] || 0), textposition: 'outside',
        hovertemplate: '%{y}: %{x} tickets — ' + currLabel + '<extra></extra>',
    });

    const lMargin = grpKey === 'category' ? 200 : 180;
    Plotly.react('chart-recurring', traces, {
        ...BASE_LAYOUT,
        barmode: 'group',
        legend: { orientation: 'h', y: -0.22, font: { size: 11 } },
        xaxis: { title: 'Tickets Raised' },
        margin: { l: lMargin, r: 60, t: 16, b: 60 },
        height: 340,
    }, CHART_CFG);

    // Update i-button
    const ibtn = document.getElementById('recurring-info-btn');
    if (ibtn) {
        const tip = prevLabel
            ? `Compares tickets raised in ${prevLabel} (grey) vs ${currLabel} (purple) by ${grpKey}. Issues appearing in both months are recurring. Change the month filter to compare different periods.`
            : `Ticket counts for ${currLabel} by ${grpKey}. Select a month filter to enable month-over-month comparison.`;
        ibtn.setAttribute('data-tip', tip);
    }
}

// ── Summary Table ─────────────────────────────────────────────────────────────
function numCell(val, type) {
    if (!val) return `<td class="cell-zero">—</td>`;
    if (type === 'overdue') return `<td class="cell-overdue">${val}</td>`;
    if (val >= 15) return `<td class="cell-l4">${val}</td>`;
    if (val >= 8)  return `<td class="cell-l3">${val}</td>`;
    if (val >= 4)  return `<td class="cell-l2">${val}</td>`;
    return             `<td class="cell-l1">${val}</td>`;
}

function getSummaryRows(rows) {
    const groups = {};
    rows.forEach(r => {
        const key = r.store + '||' + r.brand;
        if (!groups[key]) {
            groups[key] = {
                store: r.store, brand: r.brand, total: 0,
                open: 0, inProg: 0, completed: 0, closed: 0, rejected: 0, onHold: 0,
                overdue: 0, escalated: 0, respTATs: []
            };
        }
        const g = groups[key];
        g.total++;
        if (r.status === 'Open')        g.open++;
        if (r.status === 'In Progress') g.inProg++;
        if (r.status === 'Completed')   g.completed++;
        if (r.status === 'Closed')      g.closed++;
        if (r.status === 'Rejected')    g.rejected++;
        if (r.status === 'On Hold')     g.onHold++;
        if (r.is_overdue)               g.overdue++;
        if (r.escalated === 'Yes')      g.escalated++;
        if (r.response_tat_hr !== null) g.respTATs.push(r.response_tat_hr);
    });
    return Object.values(groups).map(g => ({
        ...g,
        avg_resp_tat: g.respTATs.length ? avg(g.respTATs) : null,
    }));
}

function renderSummaryTable(rows) {
    let data = getSummaryRows(rows);
    const hdrSuffix = overdueMode ? '<span class="overdue-label"> (Overdue Only)</span>' : '';
    document.getElementById('summary-hdr-label').innerHTML = 'Store Performance Summary' + hdrSuffix;
    document.getElementById('summary-count').textContent = data.length + ' stores';

    if (summarySearch) {
        const q = summarySearch.toLowerCase();
        data = data.filter(r =>
            r.store.toLowerCase().includes(q) || r.brand.toLowerCase().includes(q)
        );
    }
    data = sortData(data, summarySort.col, summarySort.dir);

    const COLS = [
        { key: 'store',        label: 'Store' },
        { key: 'brand',        label: 'Brand' },
        { key: 'total',        label: 'Total' },
        { key: 'open',         label: 'Open' },
        { key: 'inProg',       label: 'In Progress' },
        { key: 'onHold',       label: 'On Hold' },
        { key: 'completed',    label: 'Completed' },
        { key: 'closed',       label: 'Closed' },
        { key: 'overdue',      label: 'Overdue' },
        { key: 'escalated',    label: 'Escalated' },
        { key: 'avg_resp_tat', label: 'Avg Resp TAT (Hr)', tip: TAT_TIPS.response_tat_hr },
    ];

    const thead = '<tr>' + COLS.map(c => {
        const ibtn = c.tip
            ? `<button class="info-btn-hdr" data-tip="${c.tip.replace(/"/g,'&quot;')}" onclick="event.stopPropagation()">i</button>`
            : '';
        return `<th onclick="setSummarySort('${c.key}')">${c.label}${ibtn}${sortArrow(c.key, summarySort)}</th>`;
    }).join('') + '</tr>';

    const total = data.length;
    const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    if (summaryPage > totalPages) summaryPage = 1;
    const page = data.slice((summaryPage-1)*PER_PAGE, summaryPage*PER_PAGE);

    const tbody = page.length
        ? page.map(r => `<tr>
            <td>${r.store}</td>
            <td>${r.brand}</td>
            <td class="num"><strong>${r.total}</strong></td>
            ${numCell(r.open,      'open')}
            ${numCell(r.inProg,    'inProg')}
            ${numCell(r.onHold,    'onHold')}
            ${numCell(r.completed, 'completed')}
            ${numCell(r.closed,    'closed')}
            ${numCell(r.overdue,   'overdue')}
            ${numCell(r.escalated, 'escalated')}
            <td class="num">${r.avg_resp_tat !== null ? r.avg_resp_tat.toFixed(1) : '—'}</td>
        </tr>`).join('')
        : '<tr><td colspan="11" class="empty-state">No data for current filters</td></tr>';

    document.getElementById('summary-table').innerHTML = `<thead>${thead}</thead><tbody>${tbody}</tbody>`;
    renderPagination('summary-pagination', totalPages, summaryPage, 'setSummaryPage', total);
}

function setSummarySort(col) {
    summarySort.dir = (summarySort.col === col) ? -summarySort.dir : -1;
    summarySort.col = col;
    summaryPage = 1;
    renderSummaryTable(getFilteredRows());
}
function setSummaryPage(p) { summaryPage = p; renderSummaryTable(getFilteredRows()); }

// ── Detail Table ──────────────────────────────────────────────────────────────
function statusBadge(s) {
    return `<span class="badge" style="background:${STATUS_COLORS[s]||'#999'}">${s}</span>`;
}
function priorityBadge(p) {
    return `<span class="badge" style="background:${PRIORITY_COLORS[p]||'#999'}">${p}</span>`;
}

function renderDetailTable(rows) {
    let data = [...rows];
    const hdrSuffix = overdueMode ? '<span class="overdue-label"> (Overdue Only)</span>' : '';
    document.getElementById('detail-hdr-label').innerHTML = 'Ticket Details' + hdrSuffix;

    if (detailSearch) {
        const q = detailSearch.toLowerCase();
        data = data.filter(r =>
            r.ticket_id.toLowerCase().includes(q) ||
            r.title.toLowerCase().includes(q) ||
            r.store.toLowerCase().includes(q) ||
            r.category.toLowerCase().includes(q) ||
            r.created_by.toLowerCase().includes(q) ||
            r.claimed_by.toLowerCase().includes(q)
        );
    }
    data = sortData(data, detailSort.col, detailSort.dir);
    document.getElementById('detail-count').textContent = data.length + ' tickets';

    const total      = data.length;
    const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    if (detailPage > totalPages) detailPage = 1;
    const page = data.slice((detailPage-1)*PER_PAGE, detailPage*PER_PAGE);

    const COLS = [
        { key: 'ticket_id',         label: 'Ticket ID' },
        { key: 'title',             label: 'Title' },
        { key: 'store',             label: 'Store' },
        { key: 'brand',             label: 'Brand' },
        { key: 'category',          label: 'Category' },
        { key: 'sub_category',      label: 'Sub Category' },
        { key: 'status',            label: 'Status' },
        { key: 'priority',          label: 'Priority' },
        { key: 'created_at',        label: 'Created' },
        { key: 'due_date',          label: 'Due Date' },
        { key: 'sla_hr',            label: 'SLA (Hr)',        tip: TAT_TIPS.sla_hr },
        { key: 'response_tat_hr',   label: 'Resp TAT (Hr)',   tip: TAT_TIPS.response_tat_hr },
        { key: 'completion_tat_hr', label: 'Comp TAT (Hr)',   tip: TAT_TIPS.completion_tat_hr },
        { key: 'closure_tat_hr',    label: 'Clos TAT (Hr)',   tip: TAT_TIPS.closure_tat_hr },
        { key: 'days_overdue',      label: 'Days Overdue',
          tip: 'Number of days the ticket has been overdue.\nClosed/Completed: (TAT − SLA) ÷ 24\nActive (Open/In Progress/On Hold): Today − Due Date' },
        { key: 'escalated',         label: 'Escalated' },
        { key: 'is_overdue',        label: 'Overdue' },
        { key: 'city',              label: 'City' },
        { key: 'claimed_by',        label: 'Claimed By' },
        { key: 'events_trigger',    label: 'Activity' },
    ];

    const thead = '<tr>' + COLS.map(c => {
        const ibtn = c.tip
            ? `<button class="info-btn-hdr" data-tip="${c.tip.replace(/"/g,'&quot;')}" onclick="event.stopPropagation()">i</button>`
            : '';
        return `<th onclick="setDetailSort('${c.key}')">${c.label}${ibtn}${sortArrow(c.key, detailSort)}</th>`;
    }).join('') + '</tr>';

    const tbody = page.length
        ? page.map(r => {
            const ttl = r.title.length > 45 ? r.title.slice(0,45)+'...' : r.title;
            const daysOd = r.is_overdue && r.days_overdue > 0
                ? `<span style="color:#ef4444;font-weight:600">${r.days_overdue.toFixed(1)}d</span>`
                : '—';
            const evEnc  = encodeURIComponent(r.events_trigger || '');
            const ttlEnc = encodeURIComponent(r.title || '');
            const actBtn = r.events_trigger
                ? `<button class="activity-btn" onclick="showActivity('${r.ticket_id}','${evEnc}','${ttlEnc}')">Log</button>`
                : '<span style="color:#cbd5e1;font-size:11px">—</span>';
            return `<tr${r.is_overdue ? ' class="overdue-row"' : ''}>
                <td class="sid-cell">${r.ticket_id}</td>
                <td class="title-cell" title="${r.title.replace(/"/g,'&quot;')}">${ttl}</td>
                <td>${r.store}</td>
                <td>${r.brand}</td>
                <td>${r.category}</td>
                <td>${r.sub_category}</td>
                <td>${statusBadge(r.status)}</td>
                <td>${priorityBadge(r.priority)}</td>
                <td class="date-cell">${r.created_at}</td>
                <td class="date-cell">${r.due_date}</td>
                <td class="num">${fmtHr(r.sla_hr)}</td>
                <td class="num">${fmtHr(r.response_tat_hr)}</td>
                <td class="num">${fmtHr(r.completion_tat_hr)}</td>
                <td class="num">${fmtHr(r.closure_tat_hr)}</td>
                <td class="num">${daysOd}</td>
                <td style="text-align:center">${r.escalated==='Yes'?'<span class="badge" style="background:#f97316">Yes</span>':''}</td>
                <td style="text-align:center">${r.is_overdue?'<span class="tag-overdue">Yes</span>':'<span class="tag-ok">No</span>'}</td>
                <td>${r.city}</td>
                <td>${r.claimed_by}</td>
                <td style="text-align:center">${actBtn}</td>
            </tr>`;
        }).join('')
        : '<tr><td colspan="20" class="empty-state">No tickets match current filters</td></tr>';

    document.getElementById('detail-table').innerHTML = `<thead>${thead}</thead><tbody>${tbody}</tbody>`;
    renderPagination('detail-pagination', totalPages, detailPage, 'setDetailPage', total);
}

function setDetailSort(col) {
    detailSort.dir = (detailSort.col === col) ? -detailSort.dir : -1;
    detailSort.col = col;
    detailPage = 1;
    renderDetailTable(getFilteredRows());
}
function setDetailPage(p) { detailPage = p; renderDetailTable(getFilteredRows()); }

// ── Cost by Category / Sub-Category ──────────────────────────────────────────
function renderCostChart(rows) {
    const costRows = rows.filter(r => r.cost !== null && r.cost !== undefined && r.cost > 0);
    if (!costRows.length) {
        Plotly.react('chart-cost', [], {
            ...BASE_LAYOUT,
            annotations: [{ text: 'No cost data for current filters', showarrow: false,
                            font: { size: 14, color: '#94a3b8' }, xref: 'paper', yref: 'paper',
                            x: 0.5, y: 0.5 }],
            height: 340,
        }, CHART_CFG);
        return;
    }

    const grpKey = costGroupBy === 'sub_category' ? 'sub_category' : 'category';
    const totals = {}, counts = {};
    costRows.forEach(r => {
        const k = r[grpKey] || '(Not Set)';
        totals[k] = (totals[k] || 0) + r.cost;
        counts[k] = (counts[k] || 0) + 1;
    });

    // Sort by total cost descending, top 15
    const keys = Object.keys(totals)
        .sort((a, b) => totals[b] - totals[a])
        .slice(0, 15)
        .reverse();   // reverse for horizontal bar (highest at top)

    const grandTotal = costRows.reduce((s, r) => s + r.cost, 0);

    Plotly.react('chart-cost', [{
        x: keys.map(k => parseFloat(totals[k].toFixed(0))),
        y: keys,
        type: 'bar', orientation: 'h',
        marker: { color: overdueMode ? '#ef4444' : '#0891b2' },
        text: keys.map(k => totals[k].toFixed(0)),
        textposition: 'outside',
        hovertemplate: '%{y}<br>Total Cost: %{x}<br>Tickets: ' +
            keys.map(k => counts[k]).join('|') +   // placeholder, won't render — use customdata
            '<extra></extra>',
        customdata: keys.map(k => counts[k]),
        hovertemplate: '%{y}<br>Total Cost: %{x}<br>Tickets with cost: %{customdata}<extra></extra>',
    }], {
        ...BASE_LAYOUT,
        xaxis: { title: 'Total Cost' },
        margin: { l: 200, r: 80, t: 16, b: 40 },
        height: 340,
    }, CHART_CFG);

    // update the sub-total in panel header
    const el = document.getElementById('cost-total-label');
    if (el) el.textContent = `Grand Total: ${grandTotal.toFixed(0)}  |  ${costRows.length} tickets with cost recorded`;
}

// ── User Performance ──────────────────────────────────────────────────────────
const USER_BAR_META = {
    tickets:  { label: 'No. of Tickets',       color: '#C62828', yTitle: 'Tickets' },
    avg_comp: { label: 'Avg Completion TAT (Hr)', color: '#10b981', yTitle: 'Hours',
                tip: TAT_TIPS.completion_tat_hr },
    esc_rate: { label: 'Escalation Rate (%)',   color: '#f97316', yTitle: 'Percent (%)' },
    reopen_rate: { label: 'Reopen Rate (%)',    color: '#8b5cf6', yTitle: 'Percent (%)' },
};

function renderUserBarChart(rows) {
    let data = getAssigneeRows(rows);
    const m  = USER_BAR_META[userBarMetric] || USER_BAR_META.tickets;

    // Sort descending by selected metric, take top 20
    data = data
        .filter(d => d[userBarMetric] !== null && d[userBarMetric] !== undefined)
        .sort((a, b) => (b[userBarMetric] || 0) - (a[userBarMetric] || 0))
        .slice(0, 20);

    if (!data.length) {
        Plotly.react('chart-user-bar', [], { ...BASE_LAYOUT, height: 320 }, CHART_CFG);
        return;
    }

    const vals = data.map(d => {
        const v = d[userBarMetric];
        return v === null ? 0 : parseFloat(typeof v === 'number' ? v.toFixed(1) : v);
    });

    Plotly.react('chart-user-bar', [{
        x: data.map(d => d.name),
        y: vals,
        type: 'bar',
        marker: { color: m.color },
        text: vals.map(v => userBarMetric.includes('rate') ? v.toFixed(1) + '%' : v.toFixed(userBarMetric === 'tickets' ? 0 : 1)),
        textposition: 'outside',
        hovertemplate: '%{x}: %{y}<extra>' + m.label + '</extra>',
    }], {
        ...BASE_LAYOUT,
        xaxis: { tickangle: -35, tickfont: { size: 11 } },
        yaxis: { title: m.yTitle },
        margin: { l: 50, r: 20, t: 20, b: 100 },
        height: 320,
    }, CHART_CFG);

    // sync i-button
    const ibtn = document.getElementById('user-bar-info-btn');
    if (ibtn) ibtn.setAttribute('data-tip', m.tip || m.label);
}

function getAssigneeRows(rows) {
    const data = {};
    rows.forEach(r => {
        const name = r.claimed_by || 'Not Claimed';
        if (!data[name]) data[name] = {
            name, tickets: 0, respTATs: [], compTATs: [],
            escalated: 0, reopened: 0,
            s_open: 0, s_inprog: 0, s_onhold: 0,
            s_completed: 0, s_closed: 0, s_rejected: 0
        };
        const d = data[name];
        d.tickets++;
        if (r.response_tat_hr   !== null) d.respTATs.push(r.response_tat_hr);
        if (r.completion_tat_hr !== null) d.compTATs.push(r.completion_tat_hr);
        if (r.escalated === 'Yes') d.escalated++;
        if (r.reopen    === 'Yes') d.reopened++;
        if (r.status === 'Open')        d.s_open++;
        if (r.status === 'In Progress') d.s_inprog++;
        if (r.status === 'On Hold')     d.s_onhold++;
        if (r.status === 'Completed')   d.s_completed++;
        if (r.status === 'Closed')      d.s_closed++;
        if (r.status === 'Rejected')    d.s_rejected++;
    });
    return Object.values(data).map(d => ({
        name:        d.name,
        tickets:     d.tickets,
        avg_resp:    d.respTATs.length ? avg(d.respTATs) : null,
        avg_comp:    d.compTATs.length ? avg(d.compTATs) : null,
        esc_rate:    d.tickets > 0 ? (d.escalated / d.tickets * 100) : 0,
        reopen_rate: d.tickets > 0 ? (d.reopened  / d.tickets * 100) : 0,
        s_open:      d.s_open,      s_inprog:    d.s_inprog,
        s_onhold:    d.s_onhold,    s_completed: d.s_completed,
        s_closed:    d.s_closed,    s_rejected:  d.s_rejected,
    }));
}

function renderAssigneeTable(rows) {
    let data = getAssigneeRows(rows);
    // Apply user search filter
    if (userSearch) {
        const q = userSearch.toLowerCase();
        data = data.filter(d => d.name.toLowerCase().includes(q));
    }
    data = sortData(data, assigneeSort.col, assigneeSort.dir);
    document.getElementById('assignee-count').textContent = data.length + ' people';

    const COLS = [
        { key: 'name',        label: 'Claimed By' },
        { key: 'tickets',     label: 'Tickets' },
        { key: 'breakdown',   label: 'Status Breakdown',
          tip: 'Count of claimed tickets by current status.\nOpen | In Progress | On Hold | Completed | Closed | Rejected' },
        { key: 'avg_resp',    label: 'Avg Resp TAT (Hr)',  tip: TAT_TIPS.response_tat_hr },
        { key: 'avg_comp',    label: 'Avg Comp TAT (Hr)',  tip: TAT_TIPS.completion_tat_hr },
        { key: 'esc_rate',    label: 'Escalation Rate',
          tip: 'Percentage of this person\'s assigned tickets that were escalated.\nFormula: Escalated count ÷ Total tickets × 100' },
        { key: 'reopen_rate', label: 'Reopen Rate',
          tip: 'Percentage of this person\'s assigned tickets that were reopened (sent back for rework).\nFormula: Reopened count ÷ Total tickets × 100' },
    ];
    const thead = '<tr>' + COLS.map(c => {
        const ibtn = c.tip
            ? `<button class="info-btn-hdr" data-tip="${c.tip.replace(/"/g,'&quot;')}" onclick="event.stopPropagation()">i</button>`
            : '';
        const sortable = c.key !== 'breakdown';
        return sortable
            ? `<th onclick="setAssigneeSort('${c.key}')">${c.label}${ibtn}${sortArrow(c.key, assigneeSort)}</th>`
            : `<th>${c.label}${ibtn}</th>`;
    }).join('') + '</tr>';

    const total      = data.length;
    const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    if (assigneePage > totalPages) assigneePage = 1;
    const page = data.slice((assigneePage-1)*PER_PAGE, assigneePage*PER_PAGE);

    function bkCell(r) {
        const parts = [
            r.s_open      ? `<span style="color:#3b82f6;font-weight:600">${r.s_open} Open</span>`        : '',
            r.s_inprog    ? `<span style="color:#f59e0b;font-weight:600">${r.s_inprog} In&nbsp;Prog</span>` : '',
            r.s_onhold    ? `<span style="color:#94a3b8;font-weight:600">${r.s_onhold} On&nbsp;Hold</span>` : '',
            r.s_completed ? `<span style="color:#10b981;font-weight:600">${r.s_completed} Done</span>`     : '',
            r.s_closed    ? `<span style="color:#475569;font-weight:600">${r.s_closed} Closed</span>`      : '',
            r.s_rejected  ? `<span style="color:#ef4444;font-weight:600">${r.s_rejected} Rej</span>`       : '',
        ].filter(Boolean);
        return `<td style="font-size:12px;white-space:nowrap">${parts.join('<span style="color:#cbd5e1;margin:0 4px">|</span>')}</td>`;
    }

    const tbody = page.length
        ? page.map(r => `<tr>
            <td>${r.name}</td>
            <td class="num"><strong>${r.tickets}</strong></td>
            ${bkCell(r)}
            <td class="num">${r.avg_resp !== null ? r.avg_resp.toFixed(1) : '—'}</td>
            <td class="num">${r.avg_comp !== null ? r.avg_comp.toFixed(1) : '—'}</td>
            <td class="num">${r.esc_rate.toFixed(1)}%</td>
            <td class="num">${r.reopen_rate.toFixed(1)}%</td>
        </tr>`).join('')
        : '<tr><td colspan="7" class="empty-state">No data for current filters</td></tr>';

    document.getElementById('assignee-table').innerHTML = `<thead>${thead}</thead><tbody>${tbody}</tbody>`;
    renderPagination('assignee-pagination', totalPages, assigneePage, 'setAssigneePage', total);
}
function setAssigneeSort(col) {
    assigneeSort.dir = (assigneeSort.col === col) ? -assigneeSort.dir : -1;
    assigneeSort.col = col;
    assigneePage = 1;
    renderAssigneeTable(getFilteredRows());
}
function setAssigneePage(p) { assigneePage = p; renderAssigneeTable(getFilteredRows()); }

// ── Activity Modal ────────────────────────────────────────────────────────────
function showActivity(ticketId, eventsEncoded, titleEncoded) {
    const events = decodeURIComponent(eventsEncoded);
    const title  = decodeURIComponent(titleEncoded);
    document.getElementById('modal-tid').textContent   = ticketId;
    document.getElementById('modal-title').textContent = title;
    const lines = events.split(/[\n;|]+/).map(s => s.trim()).filter(Boolean);
    const body  = document.getElementById('modal-body');
    if (!lines.length) {
        body.innerHTML = '<div class="event-line" style="color:#94a3b8;padding:12px 0">No activity log recorded for this ticket.</div>';
    } else {
        body.innerHTML = lines.map(l =>
            `<div class="event-line"><div class="event-dot"></div><div>${l}</div></div>`
        ).join('');
    }
    document.getElementById('activity-modal').classList.add('visible');
}
function closeModal() {
    document.getElementById('activity-modal').classList.remove('visible');
}

// ── Central Refresh ───────────────────────────────────────────────────────────
function refresh() {
    const rows  = getFilteredRows();
    const stats = computeStats(rows);
    renderKpis(stats);
    renderTrendChart(rows);
    renderStatusChart(rows);
    renderBrandChart(rows);
    renderPriorityStatusChart(rows);
    renderCategoryChart(rows);
    renderTATChart(rows);
    renderEscalationCatChart(rows);
    renderRiskChart(rows);
    renderRecurringChart(rows);
    renderCostChart(rows);
    summaryPage  = 1;
    detailPage   = 1;
    assigneePage = 1;
    renderUserBarChart(rows);
    renderSummaryTable(rows);
    renderDetailTable(rows);
    renderAssigneeTable(rows);
}

function resetFilters() {
    state = { month: 'all', brand: 'all', category: 'all', status: 'all', priority: 'all', city: 'all', dateFrom: null, dateTo: null };
    ['sel-month','sel-brand','sel-category','sel-status','sel-priority','sel-city'].forEach(id => {
        document.getElementById(id).value = 'all';
    });
    const df = document.getElementById('date-from');
    const dt = document.getElementById('date-to');
    if (df) df.value = '';
    if (dt) dt.value = '';
    userSearch = '';
    const us = document.getElementById('user-search');
    if (us) us.value = '';
    refresh();
}

// ── UI Initialization ─────────────────────────────────────────────────────────
function buildUI() {
    // Month dropdown
    const mc = document.getElementById('sel-month');
    mc.innerHTML = '<option value="all">All Months</option>';
    // Note: month filter matches tickets created, completed, OR closed in that month
    META.months.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m; opt.textContent = META.month_labels[m] || m;
        mc.appendChild(opt);
    });
    const latestMonth = META.months[META.months.length - 1];
    if (latestMonth) { mc.value = latestMonth; state.month = latestMonth; }

    // Brand dropdown
    const brands = [...new Set(TABLE_DATA.map(r => r.brand).filter(Boolean))].sort();
    const bc = document.getElementById('sel-brand');
    bc.innerHTML = '<option value="all">All Brands</option>';
    brands.forEach(b => { const o=document.createElement('option'); o.value=b; o.textContent=b; bc.appendChild(o); });

    // Category dropdown
    const cats = [...new Set(TABLE_DATA.map(r => r.category).filter(Boolean))].sort();
    const cc = document.getElementById('sel-category');
    cc.innerHTML = '<option value="all">All Categories</option>';
    cats.forEach(c => { const o=document.createElement('option'); o.value=c; o.textContent=c; cc.appendChild(o); });

    // Status dropdown
    const sc = document.getElementById('sel-status');
    sc.innerHTML = '<option value="all">All Statuses</option>';
    STATUS_ORDER.forEach(s => { const o=document.createElement('option'); o.value=s; o.textContent=s; sc.appendChild(o); });

    // Priority dropdown
    const pc = document.getElementById('sel-priority');
    pc.innerHTML = '<option value="all">All Priorities</option>';
    PRIORITY_ORDER.forEach(p => { const o=document.createElement('option'); o.value=p; o.textContent=p; pc.appendChild(o); });

    // City dropdown
    const cities = [...new Set(TABLE_DATA.map(r => r.city).filter(Boolean))].sort();
    const citc = document.getElementById('sel-city');
    citc.innerHTML = '<option value="all">All Cities</option>';
    cities.forEach(c => { const o=document.createElement('option'); o.value=c; o.textContent=c; citc.appendChild(o); });

    // Wire filter listeners
    mc.addEventListener('change',   e => { state.month    = e.target.value; refresh(); });
    bc.addEventListener('change',   e => { state.brand    = e.target.value; refresh(); });
    cc.addEventListener('change',   e => { state.category = e.target.value; refresh(); });
    sc.addEventListener('change',   e => { state.status   = e.target.value; refresh(); });
    pc.addEventListener('change',   e => { state.priority = e.target.value; refresh(); });
    citc.addEventListener('change', e => { state.city     = e.target.value; refresh(); });

    // Search boxes
    document.getElementById('summary-search').addEventListener('input', e => {
        summarySearch = e.target.value.trim();
        summaryPage = 1;
        renderSummaryTable(getFilteredRows());
    });
    document.getElementById('detail-search').addEventListener('input', e => {
        detailSearch = e.target.value.trim();
        detailPage = 1;
        renderDetailTable(getFilteredRows());
    });

    // Trend mode toggle
    document.querySelectorAll('input[name="trend-mode"]').forEach(rb => {
        rb.addEventListener('change', e => {
            trendBarMode = e.target.value;
            renderTrendChart(getFilteredRows());
        });
    });

    // TAT group toggle (by brand / by category)
    document.querySelectorAll('input[name="tat-group"]').forEach(rb => {
        rb.addEventListener('change', e => {
            tatGroupBy = e.target.value;
            renderTATChart(getFilteredRows());
        });
    });

    // User bar metric radio
    document.querySelectorAll('input[name="user-bar-metric"]').forEach(rb => {
        rb.addEventListener('change', e => {
            userBarMetric = e.target.value;
            renderUserBarChart(getFilteredRows());
        });
    });

    // User search
    const usEl = document.getElementById('user-search');
    if (usEl) usEl.addEventListener('input', e => {
        userSearch = e.target.value.trim();
        assigneePage = 1;
        renderAssigneeTable(getFilteredRows());
    });

    // Cost group radio (category / sub_category)
    document.querySelectorAll('input[name="cost-group"]').forEach(rb => {
        rb.addEventListener('change', e => {
            costGroupBy = e.target.value;
            renderCostChart(getFilteredRows());
        });
    });

    // Recurring group radio (category / store)
    document.querySelectorAll('input[name="recurring-group"]').forEach(rb => {
        rb.addEventListener('change', e => {
            recurringGroupBy = e.target.value;
            renderRecurringChart(getFilteredRows());
        });
    });

    // TAT view radio (response / completion / closure)
    document.querySelectorAll('input[name="tat-view"]').forEach(rb => {
        rb.addEventListener('change', e => {
            tatView = e.target.value;
            renderTATChart(getFilteredRows());
        });
    });

    // Date range filter
    const dfEl = document.getElementById('date-from');
    const dtEl = document.getElementById('date-to');
    if (dfEl) dfEl.addEventListener('change', e => {
        state.dateFrom = e.target.value ? new Date(e.target.value + 'T00:00:00').getTime() : null;
        refresh();
    });
    if (dtEl) dtEl.addEventListener('change', e => {
        state.dateTo = e.target.value ? new Date(e.target.value + 'T23:59:59').getTime() : null;
        refresh();
    });

    // Close activity modal on backdrop click
    document.getElementById('activity-modal').addEventListener('click', function(e) {
        if (e.target === this) closeModal();
    });

    refresh();
}

document.addEventListener('DOMContentLoaded', buildUI);
"""


def build_html(table_json, meta_json, generated_at, total_records, date_range):
    css = _build_css()
    js  = _build_js()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SFC — Issue Tickets Dashboard</title>
  <script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
  <style>{css}</style>
</head>
<body>

<script>
  const TABLE_DATA = {table_json};
  const META       = {meta_json};
</script>

<div id="report-root">

  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <img id="sfc-logo" class="header-logo" src="sfc-logo.png" alt="SFC"
           onload="this.classList.add('loaded')" onerror="this.style.display='none'">
      <div>
        <h1>SFC — Issue Tickets Dashboard</h1>
        <p>Southern Franchise Company LLC &nbsp;|&nbsp; {date_range} &nbsp;|&nbsp; {total_records} tickets</p>
      </div>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <div class="view-toggle">
        <button id="btn-count" class="active" onclick="setViewMode('count')">Count</button>
        <button id="btn-overdue" class="btn-overdue" onclick="setViewMode('overdue')">Overdue</button>
      </div>
      <button class="info-btn" onclick="toggleViewInfo()" data-tip="Click to understand what each dashboard shows">i</button>
    </div>
    <div class="header-right">
      Generated: {generated_at}<br>
      Overdue: closed/completed TAT &gt; SLA | active tickets past due date
    </div>
  </div>

  <!-- Overdue mode banner -->
  <div id="overdue-banner" class="overdue-banner">
    Overdue View Active — all metrics, charts and tables show overdue tickets only
  </div>

  <!-- View Info Banner -->
  <div id="view-info-banner" class="info-banner">
    <div class="info-banner-title">
      <span>Understanding the Two Dashboard Views</span>
      <button class="info-banner-close" onclick="closeViewInfo()">×</button>
    </div>
    <div class="info-banner-cols">
      <div class="info-banner-col">
        <h4>Count View</h4>
        <ul>
          <li>All tickets with their current status</li>
          <li>Active overdue: Open/In Progress/On Hold tickets past their due date</li>
          <li>Use to: Monitor overall ticket volume and workflow progress</li>
        </ul>
      </div>
      <div class="info-banner-col">
        <h4>Overdue View</h4>
        <ul>
          <li>Only overdue tickets (active + resolved)</li>
          <li>Active: past due date | Closed/Completed: exceeded their SLA</li>
          <li>Use to: Focus on tickets needing immediate attention</li>
        </ul>
      </div>
    </div>
  </div>

  <!-- Filter Bar -->
  <div class="filter-bar">
    <div class="filter-group">
      <label>Month</label>
      <select id="sel-month"></select>
    </div>
    <div class="filter-group">
      <label>Brand</label>
      <select id="sel-brand"></select>
    </div>
    <div class="filter-group">
      <label>Category</label>
      <select id="sel-category"></select>
    </div>
    <div class="filter-group">
      <label>Status</label>
      <select id="sel-status"></select>
    </div>
    <div class="filter-group">
      <label>Priority</label>
      <select id="sel-priority"></select>
    </div>
    <div class="filter-group">
      <label>City</label>
      <select id="sel-city"></select>
    </div>
    <div class="filter-group">
      <label>From</label>
      <input type="date" id="date-from">
    </div>
    <div class="filter-group">
      <label>To</label>
      <input type="date" id="date-to">
    </div>
    <button class="reset-btn" onclick="resetFilters()">Reset</button>
  </div>

  <!-- KPI Strip -->
  <div id="kpi-strip" class="kpi-strip"></div>

  <!-- Charts Row 1: Trend + Status -->
  <div class="charts-row">
    <div class="chart-panel wide">
      <div class="panel-hdr">
        <span id="trend-title">Monthly Ticket Trend</span>
        <div style="display:flex;align-items:center;gap:8px">
          <div class="toggle-grp">
            <label><input type="radio" name="trend-mode" value="stack" checked> Stacked</label>
            <label><input type="radio" name="trend-mode" value="group"> Grouped</label>
          </div>
          <button class="info-btn" data-tip="Stacked: bars show total ticket volume per month, colour-coded by status. Grouped: each status bar sits side by side, easier to compare individual statuses across months.">i</button>
        </div>
      </div>
      <div id="chart-trend"></div>
    </div>
    <div class="chart-panel narrow">
      <div class="panel-hdr"><span id="status-title">Status Distribution</span></div>
      <div id="chart-status"></div>
    </div>
  </div>

  <!-- Charts Row 2: Brand + Priority x Status -->
  <div class="charts-row">
    <div class="chart-panel wide">
      <div class="panel-hdr"><span id="brand-title">Tickets by Brand</span></div>
      <div id="chart-brand"></div>
    </div>
    <div class="chart-panel narrow">
      <div class="panel-hdr"><span id="priority-status-title">Priority x Status Distribution</span></div>
      <div id="chart-priority-status"></div>
    </div>
  </div>

  <!-- Charts Row 3: Category + TAT -->
  <div class="charts-row">
    <div class="chart-panel half">
      <div class="panel-hdr"><span id="category-title">Top Categories</span></div>
      <div id="chart-category"></div>
    </div>
    <div class="chart-panel half">
      <div class="panel-hdr" style="flex-wrap:wrap;gap:8px">
        <span style="display:flex;align-items:center">
          Average TAT (Hours)
          <button class="info-btn" id="tat-info-btn" data-tip="Time from creation to completion, excluding on-hold pauses (hours). Actual working time to resolve.">i</button>
        </span>
        <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
          <div class="tat-options">
            <label><input type="radio" name="tat-view" value="completion" checked> Completion</label>
            <label><input type="radio" name="tat-view" value="closure"> Closure</label>
          </div>
          <div class="toggle-grp">
            <label><input type="radio" name="tat-group" value="brand" checked> By Brand</label>
            <label><input type="radio" name="tat-group" value="category"> By Category</label>
            <button class="info-btn" data-tip="Switch the breakdown axis: By Brand compares response/completion speed across restaurant brands. By Category compares across issue types (e.g. HR, IT, Repairs).">i</button>
          </div>
        </div>
      </div>
      <div id="chart-tat"></div>
    </div>
  </div>

  <!-- Charts Row 4: Escalation by Category + Department Risk -->
  <div class="charts-row">
    <div class="chart-panel half">
      <div class="panel-hdr">
        <span style="display:flex;align-items:center">
          Escalation by Category
          <button class="info-btn" data-tip="Count of tickets that were escalated, grouped by category. High numbers indicate systemic gaps or unclear accountability in that area.">i</button>
        </span>
      </div>
      <div id="chart-escalation-cat"></div>
    </div>
    <div class="chart-panel half">
      <div class="panel-hdr">
        <span style="display:flex;align-items:center">
          Department Attention Needed
          <button class="info-btn" data-tip="Looks only at pending tickets (Open / In Progress / On Hold). Red = High or Highest priority count, Orange = Escalated count. Categories with the most combined red+orange bars need immediate attention.">i</button>
        </span>
      </div>
      <div id="chart-risk"></div>
    </div>
  </div>

  <!-- Charts Row 5: Recurring Issues — month-over-month -->
  <div class="charts-row">
    <div class="chart-panel" style="flex:1">
      <div class="panel-hdr">
        <span style="display:flex;align-items:center">
          Recurring Issues — Month Comparison
          <button class="info-btn" id="recurring-info-btn" data-tip="Compares ticket counts for the selected month vs the previous month. Issues appearing in both months are recurring. Use the month filter to explore different periods.">i</button>
        </span>
        <div class="toggle-grp">
          <label><input type="radio" name="recurring-group" value="category" checked> By Category</label>
          <label><input type="radio" name="recurring-group" value="store"> By Store</label>
        </div>
      </div>
      <div id="chart-recurring"></div>
    </div>
  </div>

  <!-- Charts Row 6: Cost Analysis -->
  <div class="charts-row">
    <div class="chart-panel" style="flex:1">
      <div class="panel-hdr" style="flex-wrap:wrap;gap:8px">
        <div>
          <span style="display:flex;align-items:center">
            Cost by Category
            <button class="info-btn" data-tip="Shows total cost recorded on tickets, broken down by category or sub-category. Only tickets where cost data was entered are included. Switch the radio to drill down into sub-categories.">i</button>
          </span>
          <div id="cost-total-label" style="font-size:11px;color:#64748b;font-weight:400;margin-top:2px"></div>
        </div>
        <div class="toggle-grp">
          <label><input type="radio" name="cost-group" value="category" checked> By Category</label>
          <label><input type="radio" name="cost-group" value="sub_category"> By Sub-Category</label>
        </div>
      </div>
      <div id="chart-cost"></div>
    </div>
  </div>

  <!-- User Performance Bar Chart -->
  <div class="charts-row">
    <div class="chart-panel" style="flex:1">
      <div class="panel-hdr" style="flex-wrap:wrap;gap:8px">
        <span style="display:flex;align-items:center">
          User Performance
          <button class="info-btn" id="user-bar-info-btn" data-tip="Shows top 20 users by selected metric. Switch the radio to compare ticket volume, completion speed, escalation rate, or reopen rate.">i</button>
        </span>
        <div class="tat-options">
          <label><input type="radio" name="user-bar-metric" value="tickets" checked> No. of Tickets</label>
          <label><input type="radio" name="user-bar-metric" value="avg_comp"> Avg Comp TAT</label>
          <label><input type="radio" name="user-bar-metric" value="esc_rate"> Escalation Rate</label>
          <label><input type="radio" name="user-bar-metric" value="reopen_rate"> Reopen Rate</label>
        </div>
      </div>
      <div id="chart-user-bar"></div>
    </div>
  </div>

  <!-- User Performance Grid -->
  <div class="section">
    <div class="section-hdr">
      <span>User Performance</span>
      <span class="section-count" id="assignee-count"></span>
    </div>
    <input class="search-box" id="user-search" placeholder="Search by user name...">
    <div class="table-wrap">
      <table id="assignee-table" class="data-table"></table>
    </div>
    <div id="assignee-pagination" class="pagination"></div>
  </div>

  <!-- Store Summary Table -->
  <div class="section">
    <div class="section-hdr">
      <span id="summary-hdr-label">Store Performance Summary</span>
      <span class="section-count" id="summary-count"></span>
    </div>
    <input class="search-box" id="summary-search" placeholder="Search stores or brands...">
    <div class="table-wrap">
      <table id="summary-table" class="data-table"></table>
    </div>
    <div id="summary-pagination" class="pagination"></div>
  </div>

  <!-- Detail Table -->
  <div class="section">
    <div class="section-hdr">
      <span id="detail-hdr-label">Ticket Details</span>
      <span class="section-count" id="detail-count"></span>
    </div>
    <input class="search-box" id="detail-search"
           placeholder="Search ticket ID, title, store, category, created by...">
    <div class="table-wrap">
      <table id="detail-table" class="data-table"></table>
    </div>
    <div id="detail-pagination" class="pagination"></div>
  </div>

</div>

<!-- Global tooltip -->
<div id="global-tip"></div>

<!-- Activity Log Modal -->
<div id="activity-modal" class="modal-overlay">
  <div class="modal-box">
    <div class="modal-header">
      <div>
        <div class="modal-tid" id="modal-tid"></div>
        <div class="modal-title" id="modal-title"></div>
      </div>
      <button class="modal-close" onclick="closeModal()">&#215;</button>
    </div>
    <div id="modal-body"></div>
  </div>
</div>

<script>{js}</script>
</body>
</html>"""


# -- Entry point --------------------------------------------------------------
def main():
    try:
        initialize_environment()
        output_file = resolve_output_path()

        df = fetch_source_dataframe()
        df = prepare_dataframe(df)

        months_raw    = [m for m in df["month"].unique().tolist() if m]
        months_sorted = sorted(months_raw, key=lambda m: datetime.strptime(m, "%b%Y"))
        month_labels  = {
            m: datetime.strptime(m, "%b%Y").strftime("%B %Y")
            for m in months_sorted
        }

        table_rows = build_table_rows(df)
        table_json = json.dumps(table_rows, ensure_ascii=False)
        meta_json  = json.dumps({
            "months":       months_sorted,
            "month_labels": month_labels,
        }, ensure_ascii=False)

        m0 = datetime.strptime(months_sorted[0],  "%b%Y").strftime("%b %Y") if months_sorted else "N/A"
        m1 = datetime.strptime(months_sorted[-1], "%b%Y").strftime("%b %Y") if months_sorted else "N/A"
        date_range   = f"{m0} - {m1}"
        generated_at = NOW.strftime("%d %b %Y %H:%M")

        html = build_html(table_json, meta_json, generated_at, len(df), date_range)

        with output_file.open("w", encoding="utf-8") as f:
            f.write(html)

        print(f"Report written: {output_file}  ({len(html)//1024} KB)")
        sys.exit(0)

    except Exception as exc:
        print(str(exc), file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
