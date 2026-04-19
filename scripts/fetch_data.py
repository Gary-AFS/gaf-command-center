#!/usr/bin/env python3
"""
GAF Command Center - Data Aggregation Script
Pulls from Shopify (GAF + Revel), GA4, HubSpot, Asana, and Google Sheets.
Writes a single data/dashboard.json file.
All credentials come from environment variables (designed for GitHub Actions).
"""

import json
import os
import sys
import base64
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    """Print timestamped log line for GitHub Actions visibility."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def utc_now():
    return datetime.now(timezone.utc)


def iso_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def days_ago(n: int) -> datetime:
    return utc_now() - timedelta(days=n)


# ---------------------------------------------------------------------------
# 1. Shopify
# ---------------------------------------------------------------------------

def shopify_get_token(store: str, client_id: str, client_secret: str) -> str:
    """Exchange client credentials for an access token."""
    url = f"https://{store}/admin/oauth/access_token"
    resp = requests.post(url, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def shopify_fetch_orders(store: str, token: str) -> list:
    """Fetch all orders from last 90 days, paginating via Link header."""
    api_version = "2024-01"
    since = days_ago(90).strftime("%Y-%m-%dT%H:%M:%S-00:00")
    url = f"https://{store}/admin/api/{api_version}/orders.json"
    params = {"status": "any", "created_at_min": since, "limit": 250}
    headers = {"X-Shopify-Access-Token": token}

    all_orders = []
    while url:
        resp = requests.get(url, params=params, headers=headers, timeout=60)
        resp.raise_for_status()
        orders = resp.json().get("orders", [])
        all_orders.extend(orders)
        log(f"  Fetched {len(orders)} orders (total: {len(all_orders)})")

        # Pagination via Link header
        url = None
        params = None  # params already encoded in next URL
        link = resp.headers.get("Link", "")
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
                break

    return all_orders


def shopify_aggregate(orders: list) -> dict:
    """Aggregate orders into revenue/orders/aov for today, 7d, 30d, 90d."""
    now = utc_now()
    buckets = {
        "today": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
    }
    revenue = {k: 0.0 for k in buckets}
    counts = {k: 0 for k in buckets}

    for order in orders:
        created = order.get("created_at", "")
        try:
            order_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        total = safe_float(order.get("total_price", 0))
        for label, delta in buckets.items():
            if now - order_dt <= delta:
                revenue[label] += total
                counts[label] += 1

    aov = {}
    for k in buckets:
        aov[k] = round(revenue[k] / counts[k], 2) if counts[k] > 0 else 0
        revenue[k] = round(revenue[k], 2)

    return {"revenue": revenue, "orders": counts, "aov": aov}


def fetch_shopify_brand(label: str, store: str, client_id_var: str, client_secret_var: str) -> dict:
    """Fetch and aggregate a single Shopify brand."""
    client_id = os.environ.get(client_id_var)
    client_secret = os.environ.get(client_secret_var)
    if not client_id or not client_secret:
        msg = f"Missing env vars {client_id_var} / {client_secret_var}"
        log(f"  SKIP {label}: {msg}")
        return {"error": msg}

    log(f"Shopify [{label}]: getting token for {store}")
    token = shopify_get_token(store, client_id, client_secret)
    log(f"Shopify [{label}]: fetching orders (last 90d)")
    orders = shopify_fetch_orders(store, token)
    log(f"Shopify [{label}]: {len(orders)} orders fetched, aggregating")
    return shopify_aggregate(orders)


# ---------------------------------------------------------------------------
# 2. GA4
# ---------------------------------------------------------------------------

def fetch_ga4() -> dict:
    """Fetch GA4 session/user/conversion data for 7d and 30d."""
    creds_b64 = os.environ.get("GA4_CREDENTIALS_JSON")
    if not creds_b64:
        return {"error": "Missing GA4_CREDENTIALS_JSON env var"}

    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric,
    )
    from google.oauth2 import service_account

    creds_json = json.loads(base64.b64decode(creds_b64))
    credentials = service_account.Credentials.from_service_account_info(
        creds_json, scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=credentials)
    property_id = "356833601"

    def run_report(start_date: str, end_date: str = "today"):
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="sessionDefaultChannelGroup")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="totalUsers"),
                Metric(name="conversions"),
            ],
        )
        return client.run_report(request)

    result = {}
    periods = {"7d": "7daysAgo", "30d": "30daysAgo"}
    all_channels = {}

    for label, start in periods.items():
        log(f"GA4: running report for {label}")
        report = run_report(start)
        total_sessions = 0
        total_users = 0
        total_conversions = 0
        for row in report.rows:
            channel = row.dimension_values[0].value
            sessions = safe_int(row.metric_values[0].value)
            users = safe_int(row.metric_values[1].value)
            conversions = safe_int(row.metric_values[2].value)
            total_sessions += sessions
            total_users += users
            total_conversions += conversions
            # Accumulate 30d channels for the channel breakdown
            if label == "30d":
                all_channels[channel] = {
                    "name": channel,
                    "sessions": sessions,
                    "users": users,
                    "conversions": conversions,
                }
        result[label] = {
            "sessions": total_sessions,
            "users": total_users,
            "conversions": total_conversions,
        }

    channels_list = sorted(all_channels.values(), key=lambda c: c["sessions"], reverse=True)
    return {"periods": result, "channels": channels_list}


# ---------------------------------------------------------------------------
# 3. HubSpot
# ---------------------------------------------------------------------------

def fetch_hubspot() -> dict:
    """Fetch recent marketing emails from HubSpot."""
    pat = os.environ.get("HUBSPOT_PAT")
    if not pat:
        return {"error": "Missing HUBSPOT_PAT env var"}

    url = "https://api.hubapi.com/marketing/v3/emails"
    headers = {"Authorization": f"Bearer {pat}"}
    params = {"limit": 20, "orderBy": "-updated"}

    log("HubSpot: fetching recent marketing emails")
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    cutoff = days_ago(90)
    emails = []
    for email in data.get("results", []):
        updated = email.get("updatedAt") or email.get("updated") or ""
        try:
            email_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            email_dt = utc_now()  # include if we cannot parse

        if email_dt < cutoff:
            continue

        stats = email.get("statistics", email.get("stats", {}))
        counters = stats.get("counters", stats)
        sends = safe_int(counters.get("sent", counters.get("sends", 0)))
        opens = safe_int(counters.get("open", counters.get("opens", 0)))
        clicks = safe_int(counters.get("click", counters.get("clicks", 0)))
        open_rate = round(opens / sends, 4) if sends > 0 else 0
        click_rate = round(clicks / sends, 4) if sends > 0 else 0

        emails.append({
            "name": email.get("name", ""),
            "subject": email.get("subject", ""),
            "status": email.get("state", email.get("status", "")),
            "sends": sends,
            "opens": opens,
            "clicks": clicks,
            "open_rate": open_rate,
            "click_rate": click_rate,
        })

    log(f"HubSpot: {len(emails)} emails within 90-day window")
    return {"recent_emails": emails}


# ---------------------------------------------------------------------------
# 4. Asana
# ---------------------------------------------------------------------------

def fetch_asana() -> dict:
    """Fetch upcoming, overdue, and Gary board tasks from Asana."""
    pat = os.environ.get("ASANA_PAT")
    if not pat:
        return {"error": "Missing ASANA_PAT env var"}

    headers = {"Authorization": f"Bearer {pat}"}
    workspace = "12600476210818"
    gary_project = "1213975931607389"
    base = "https://app.asana.com/api/1.0"
    opt_fields = "name,due_on,assignee.name,projects.name"

    today = iso_date(utc_now())
    week_out = iso_date(utc_now() + timedelta(days=7))

    def search_tasks(params: dict) -> list:
        url = f"{base}/workspaces/{workspace}/tasks/search"
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json().get("data", [])

    def format_tasks(tasks: list) -> list:
        result = []
        for t in tasks:
            assignee = t.get("assignee")
            projects = t.get("projects", [])
            result.append({
                "name": t.get("name", ""),
                "due_on": t.get("due_on", ""),
                "assignee": assignee.get("name", "") if assignee else "",
                "project": projects[0].get("name", "") if projects else "",
            })
        return result

    # Due this week
    log("Asana: searching tasks due this week")
    due_week = search_tasks({
        "due_on.after": today,
        "due_on.before": week_out,
        "completed": "false",
        "opt_fields": opt_fields,
    })

    # Overdue
    log("Asana: searching overdue tasks")
    yesterday = iso_date(days_ago(1))
    overdue = search_tasks({
        "due_on.before": today,
        "completed": "false",
        "opt_fields": opt_fields,
    })

    # Gary board
    log("Asana: fetching Gary board tasks")
    gary_url = f"{base}/projects/{gary_project}/tasks"
    gary_resp = requests.get(gary_url, headers=headers, params={
        "opt_fields": "name,completed,due_on,assignee.name",
    }, timeout=30)
    gary_resp.raise_for_status()
    gary_tasks = gary_resp.json().get("data", [])

    gary_board = []
    for t in gary_tasks:
        gary_board.append({
            "name": t.get("name", ""),
            "completed": t.get("completed", False),
            "due_on": t.get("due_on", ""),
        })

    log(f"Asana: {len(due_week)} due this week, {len(overdue)} overdue, {len(gary_board)} on Gary board")
    return {
        "due_this_week": format_tasks(due_week),
        "overdue": format_tasks(overdue),
        "gary_board": gary_board,
    }


# ---------------------------------------------------------------------------
# 5. Google Sheets (Profit Per X)
# ---------------------------------------------------------------------------

def fetch_sheets_cac() -> dict:
    """Read CAC/ROAS data from the Profit Per X spreadsheet."""
    creds_b64 = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if not creds_b64:
        return {"error": "Missing GOOGLE_SHEETS_CREDENTIALS_JSON env var"}

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_json = json.loads(base64.b64decode(creds_b64))
    credentials = service_account.Credentials.from_service_account_info(
        creds_json, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    service = build("sheets", "v4", credentials=credentials)
    spreadsheet_id = "10ZTj5iCaVEHq76ka3No6i7J9xp4MaoPppZkf3mxMyOk"
    range_name = "'Final Model'!A1:Z50"

    log("Sheets: reading Profit Per X data")
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_name
    ).execute()
    rows = result.get("values", [])
    log(f"Sheets: got {len(rows)} rows")

    if not rows:
        return {"segments": [], "platforms": []}

    # Parse the sheet data. The layout may vary, so we look for header rows
    # containing known keywords and extract structured data beneath them.
    segments = []
    platforms = []

    # Find header row indices
    header_row = rows[0] if rows else []

    # Strategy: scan for rows that look like segment or platform data.
    # A segment row typically has: name, CAC, orders, revenue
    # A platform row typically has: name, spend, orders, CAC, ROAS
    # We use a heuristic: find the header row, then read data rows below it.

    def find_header_index(keyword: str) -> int:
        """Find the first row index containing the keyword (case-insensitive)."""
        for i, row in enumerate(rows):
            for cell in row:
                if keyword.lower() in str(cell).lower():
                    return i
        return -1

    def col_index(header: list, keyword: str) -> int:
        """Find column index in a header row by keyword."""
        for i, cell in enumerate(header):
            if keyword.lower() in str(cell).lower():
                return i
        return -1

    # Try to find segment data
    seg_idx = find_header_index("segment")
    if seg_idx == -1:
        seg_idx = find_header_index("cac")

    if seg_idx >= 0:
        header = rows[seg_idx]
        name_col = 0
        cac_col = col_index(header, "cac")
        orders_col = col_index(header, "order")
        rev_col = col_index(header, "revenue")

        for row in rows[seg_idx + 1:]:
            if not row or not row[0] or row[0].strip() == "":
                break  # empty row signals end of section
            entry = {"name": str(row[0]).strip()}
            if cac_col >= 0 and cac_col < len(row):
                entry["cac"] = safe_float(str(row[cac_col]).replace("$", "").replace(",", ""))
            else:
                entry["cac"] = 0
            if orders_col >= 0 and orders_col < len(row):
                entry["orders"] = safe_int(str(row[orders_col]).replace(",", ""))
            else:
                entry["orders"] = 0
            if rev_col >= 0 and rev_col < len(row):
                entry["revenue"] = safe_float(str(row[rev_col]).replace("$", "").replace(",", ""))
            else:
                entry["revenue"] = 0
            segments.append(entry)

    # Try to find platform/ROAS data
    plat_idx = find_header_index("platform")
    if plat_idx == -1:
        plat_idx = find_header_index("roas")

    if plat_idx >= 0 and plat_idx != seg_idx:
        header = rows[plat_idx]
        name_col = 0
        spend_col = col_index(header, "spend")
        orders_col = col_index(header, "order")
        cac_col = col_index(header, "cac")
        roas_col = col_index(header, "roas")

        for row in rows[plat_idx + 1:]:
            if not row or not row[0] or row[0].strip() == "":
                break
            entry = {"name": str(row[0]).strip()}
            if spend_col >= 0 and spend_col < len(row):
                entry["spend"] = safe_float(str(row[spend_col]).replace("$", "").replace(",", ""))
            else:
                entry["spend"] = 0
            if orders_col >= 0 and orders_col < len(row):
                entry["orders"] = safe_int(str(row[orders_col]).replace(",", ""))
            else:
                entry["orders"] = 0
            if cac_col >= 0 and cac_col < len(row):
                entry["cac"] = safe_float(str(row[cac_col]).replace("$", "").replace(",", ""))
            else:
                entry["cac"] = 0
            if roas_col >= 0 and roas_col < len(row):
                entry["roas"] = safe_float(str(row[roas_col]).replace("$", "").replace(",", ""))
            else:
                entry["roas"] = 0
            platforms.append(entry)

    return {"segments": segments, "platforms": platforms}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("Starting data aggregation")

    dashboard = {
        "last_updated": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "brands": {},
        "ga4": {},
        "hubspot": {},
        "asana": {},
        "cac": {},
    }

    # --- Shopify GAF ---
    try:
        dashboard["brands"]["gaf"] = fetch_shopify_brand(
            "GAF",
            "gymandfitness-au.myshopify.com",
            "SHOPIFY_GAF_CLIENT_ID",
            "SHOPIFY_GAF_CLIENT_SECRET",
        )
    except Exception as e:
        log(f"ERROR (Shopify GAF): {e}")
        traceback.print_exc()
        dashboard["brands"]["gaf"] = {"error": str(e)}

    # --- Shopify Revel ---
    try:
        dashboard["brands"]["revel"] = fetch_shopify_brand(
            "Revel",
            "revel-saunas.myshopify.com",
            "SHOPIFY_REVEL_CLIENT_ID",
            "SHOPIFY_REVEL_CLIENT_SECRET",
        )
    except Exception as e:
        log(f"ERROR (Shopify Revel): {e}")
        traceback.print_exc()
        dashboard["brands"]["revel"] = {"error": str(e)}

    # --- GA4 ---
    try:
        dashboard["ga4"] = fetch_ga4()
    except Exception as e:
        log(f"ERROR (GA4): {e}")
        traceback.print_exc()
        dashboard["ga4"] = {"error": str(e)}

    # --- HubSpot ---
    try:
        dashboard["hubspot"] = fetch_hubspot()
    except Exception as e:
        log(f"ERROR (HubSpot): {e}")
        traceback.print_exc()
        dashboard["hubspot"] = {"error": str(e)}

    # --- Asana ---
    try:
        dashboard["asana"] = fetch_asana()
    except Exception as e:
        log(f"ERROR (Asana): {e}")
        traceback.print_exc()
        dashboard["asana"] = {"error": str(e)}

    # --- Google Sheets CAC ---
    try:
        dashboard["cac"] = fetch_sheets_cac()
    except Exception as e:
        log(f"ERROR (Sheets CAC): {e}")
        traceback.print_exc()
        dashboard["cac"] = {"error": str(e)}

    # --- Write output ---
    output_dir = Path(__file__).resolve().parent.parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "dashboard.json"

    with open(output_path, "w") as f:
        json.dump(dashboard, f, indent=2)

    log(f"Wrote {output_path} ({output_path.stat().st_size} bytes)")
    log("Done")


if __name__ == "__main__":
    main()
