"""
Forage Kitchen - Daily Labor Report Dashboard
Pulls sales and labor data from Toast POS API and generates an HTML dashboard
matching the Daily Labor Report Excel workbook.

Usage: python labor_dashboard.py
       Then open labor_dashboard.html in your browser.

Business week: Wednesday through Tuesday
- On Wednesday, the previous week's data is cleared and the new week begins.
- Each day, the script pulls data for all completed days in the current week.
- GM hours are capped at 8 (salaried).
- Front-of-house roles (Cashier, Register, Customer Service, Host, SB Trainer)
  are excluded from the labor hours total.
"""
import urllib.request
import json
import os
import ssl
import time
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# CONFIG
# ============================================================
OUTDIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(OUTDIR, "cache")

import sys
sys.path.insert(0, OUTDIR)
from toast_config import (
    TOAST_CLIENT_ID, TOAST_CLIENT_SECRET,
    TOAST_AUTH_URL, TOAST_API_BASE, TOAST_RESTAURANTS
)

SSL_CTX = ssl.create_default_context()

# Location display names (Toast config name -> Dashboard name)
LOCATION_DISPLAY_NAMES = {
    "State Street": "State St",
    "Old Sauk": "Middleton",
}

# Job titles excluded from labor hours (front-of-house / non-production)
EXCLUDED_JOB_TITLES = {
    "Cashier", "Register", "Customer Service", "Host", "SB Trainer"
}

# GM cap: General Managers are salaried, count as 8 hours max
GM_JOB_TITLE = "General Manager"
GM_HOURS_CAP = 8.0

# Day names for the Wed-Tue business week
WEEKDAY_NAMES = ["Wed", "Thu", "Fri", "Sat", "Sun", "Mon", "Tue"]

# ============================================================
# HOURS LOOKUP TABLE (from Excel 'hours lookup' sheet)
# Format: (daily_sales_threshold, total_ideal_hours)
# ============================================================
HOURS_LOOKUP = [
    (0, 0),
    (200, 31),
    (550, 31),
    (700, 33),
    (850, 35),
    (1000, 37),
    (1150, 38.07),
    (1300, 39.14),
    (1450, 40.20),
    (1600, 41.27),
    (1750, 42.34),
    (1900, 43.41),
    (2050, 44.48),
    (2200, 45.55),
    (2300, 46.61),
    (2450, 47.68),
    (2600, 48.75),
    (2750, 49.82),
    (2900, 50.89),
    (3050, 51.95),
    (3200, 53.02),
    (3300, 54.09),
    (3450, 55.16),
    (3600, 56.23),
    (3750, 57.29),
    (3900, 58.36),
    (4050, 59.43),
    (4200, 60.50),
    (4300, 61.57),
    (4450, 62.64),
    (4600, 63.70),
    (4750, 64.77),
    (4900, 65.84),
    (5050, 66.91),
    (5200, 67.98),
    (5300, 69.04),
    (5450, 70.11),
    (5600, 71.18),
    (5750, 72.25),
    (5900, 73.32),
    (6050, 74.38),
    (6200, 75.45),
    (6300, 76.52),
    (6450, 77.59),
    (6600, 78.66),
    (6750, 79.73),
    (6900, 80.79),
    (7050, 81.86),
    (7200, 82.93),
]

# Wage guidelines (for reference display on dashboard)
WAGE_GUIDELINES = {
    "SB": [10, 13, 15, 18],
    "Kitchen": [12, 15, 17, 20],
    "Shift Manager": [14, 17, 19, 22],
    "AGM": [17, 19, 22, 24],
}

VARIANCE_ALLOWANCES = {
    "Weekly": "14 Hours Over Ideal",
    "Period": "28 Hours Over Ideal",
    "Training": "120 Hours Per Quarter",
}


def lookup_ideal_hours(daily_sales):
    """Given daily net sales, return ideal total labor hours using LOOKUP logic."""
    if daily_sales <= 0:
        return 0
    result = 0
    for threshold, hours in HOURS_LOOKUP:
        if daily_sales >= threshold:
            result = hours
        else:
            break
    return result


# ============================================================
# TOAST API HELPERS (reused from daily_dashboard.py)
# ============================================================
def toast_authenticate():
    data = json.dumps({
        "clientId": TOAST_CLIENT_ID,
        "clientSecret": TOAST_CLIENT_SECRET,
        "userAccessType": "TOAST_MACHINE_CLIENT"
    }).encode()
    req = urllib.request.Request(TOAST_AUTH_URL, data=data,
                                headers={"Content-Type": "application/json"},
                                method="POST")
    with urllib.request.urlopen(req, context=SSL_CTX) as resp:
        result = json.loads(resp.read())
    return result["token"]["accessToken"]


def toast_get(url, token, restaurant_guid, retries=3):
    headers = {
        "Authorization": f"Bearer {token}",
        "Toast-Restaurant-External-ID": restaurant_guid
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = (attempt + 1) * 5
                print(f"\n      Rate limited (429), waiting {wait}s...", end="", flush=True)
                time.sleep(wait)
            else:
                raise


# ============================================================
# BUSINESS WEEK HELPERS
# ============================================================
def get_week_start(today=None):
    """Get the Wednesday that starts the current business week."""
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    days_since_wed = (today.weekday() - 2) % 7
    return today - timedelta(days=days_since_wed)


def get_week_dates(week_start):
    """Return list of 7 dates (Wed through Tue) for the business week."""
    return [week_start + timedelta(days=i) for i in range(7)]


# ============================================================
# CACHE
# ============================================================
def get_labor_cache_path(week_start):
    key = f"labor_week_{week_start.strftime('%Y-%m-%d')}"
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{key}.json")


def load_labor_cache(week_start):
    path = get_labor_cache_path(week_start)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_labor_cache(week_start, data):
    path = get_labor_cache_path(week_start)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ============================================================
# DATA PULL FUNCTIONS
# ============================================================
def pull_orders_day(token, guid, date):
    """Pull orders for a single day, return {net_sales, orders, guests}.

    Net Sales = check.amount - deferred selections (gift card sales).

    check.amount is Toast's pre-tax subtotal which equals:
      sum(selection.price) + non-gratuity service charges
    It already has item-level discounts applied (in selection.price).
    Check-level discounts (comps, loyalty, rounding) are tracked separately
    by Toast and do NOT reduce check.amount.

    Deferred selections (gift card purchases) are excluded since they are
    not food/bev revenue.

    Note: This formula matches Toast's Group Sales Overview exactly for most
    locations. A few locations may show a small variance (<1%) due to
    internal Toast reporting adjustments not exposed through the Orders API.
    """
    biz_date = date.strftime("%Y%m%d")
    totals = {"net_sales": 0, "orders": 0, "guests": 0}
    page = 1
    while True:
        url = (f"{TOAST_API_BASE}/orders/v2/ordersBulk"
               f"?businessDate={biz_date}&pageSize=100&page={page}")
        orders = toast_get(url, token, guid)
        for order in orders:
            if order.get("voided") or order.get("deleted"):
                continue
            for check in order.get("checks", []):
                if check.get("voided") or check.get("deleted"):
                    continue
                totals["orders"] += 1
                totals["guests"] += 1

                check_net = check.get("amount") or 0

                # Subtract deferred selections (gift card sales)
                for sel in check.get("selections", []):
                    if sel.get("deferred") and not sel.get("voided"):
                        check_net -= (sel.get("price") or 0)

                totals["net_sales"] += check_net
        if len(orders) < 100:
            break
        page += 1
    totals["net_sales"] = round(totals["net_sales"], 2)
    if totals["orders"] > 0:
        totals["avg_order"] = round(totals["net_sales"] / totals["orders"], 2)
        totals["avg_guest"] = round(totals["net_sales"] / totals["guests"], 2) if totals["guests"] > 0 else 0
    else:
        totals["avg_order"] = 0
        totals["avg_guest"] = 0
    return totals


def pull_jobs(token, guid):
    """Pull job definitions for a restaurant. Returns {job_guid: job_name}."""
    url = f"{TOAST_API_BASE}/labor/v1/jobs"
    try:
        jobs = toast_get(url, token, guid)
        return {j["guid"]: j.get("title", j.get("name", "Unknown")) for j in jobs}
    except Exception:
        return {}


def pull_employees(token, guid):
    """Pull employee list. Returns {employee_guid: {firstName, lastName}}."""
    url = f"{TOAST_API_BASE}/labor/v1/employees"
    try:
        employees = toast_get(url, token, guid)
        result = {}
        for emp in employees:
            result[emp["guid"]] = {
                "firstName": emp.get("firstName", ""),
                "lastName": emp.get("lastName", ""),
            }
        return result
    except Exception:
        return {}


def pull_labor_detail(token, guid, date, jobs_map, employees_map):
    """Pull time entries for a single business date with employee-level detail.
    Uses businessDate parameter (not startDate/endDate) for complete results.
    Returns list: [{"name", "job_title", "regular_hours", "overtime_hours",
                    "total_hours", "hourly_rate", "is_gm", "capped"}]
    """
    biz_date = date.strftime("%Y%m%d")
    url = f"{TOAST_API_BASE}/labor/v1/timeEntries?businessDate={biz_date}"

    try:
        entries = toast_get(url, token, guid)
    except Exception as e:
        print(f" labor error: {e}")
        return []

    result = []
    for entry in entries:
        # Resolve employee name
        emp_ref = entry.get("employeeReference", {})
        emp_guid = emp_ref.get("guid", "") if isinstance(emp_ref, dict) else ""
        emp_info = employees_map.get(emp_guid, {})
        first = emp_info.get("firstName", "")
        last = emp_info.get("lastName", "")
        name = f"{last}, {first}".strip(", ") if last or first else "Unknown"

        # Resolve job title
        job_ref = entry.get("jobReference", {})
        job_guid = job_ref.get("guid", "") if isinstance(job_ref, dict) else ""
        job_title = jobs_map.get(job_guid, "Unknown")

        reg_hours = entry.get("regularHours") or 0
        ot_hours = entry.get("overtimeHours") or 0
        total = reg_hours + ot_hours
        rate = entry.get("hourlyWage") or 0

        # GM cap
        is_gm = job_title == GM_JOB_TITLE
        capped = False
        if is_gm and total > GM_HOURS_CAP:
            total = GM_HOURS_CAP
            reg_hours = min(reg_hours, GM_HOURS_CAP)
            ot_hours = 0
            capped = True

        result.append({
            "name": name,
            "job_title": job_title,
            "regular_hours": round(reg_hours, 2),
            "overtime_hours": round(ot_hours, 2),
            "total_hours": round(total, 2),
            "hourly_rate": round(rate, 2),
            "is_gm": is_gm,
            "capped": capped,
        })

    return result


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("  Forage Kitchen - Daily Labor Report Dashboard")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_start = get_week_start(today)
    week_end = week_start + timedelta(days=6)
    week_dates = get_week_dates(week_start)

    # Data end: yesterday or week_end, whichever is earlier
    data_end = min(yesterday, week_end)

    # Days to pull: from week_start through data_end
    days_to_pull = []
    d = week_start
    while d <= data_end:
        days_to_pull.append(d)
        d += timedelta(days=1)

    print(f"\n  Business week: {week_start.strftime('%a %Y-%m-%d')} to {week_end.strftime('%a %Y-%m-%d')}")
    print(f"  Today: {today.strftime('%a %Y-%m-%d')}")
    print(f"  Data through: {data_end.strftime('%a %Y-%m-%d')} ({len(days_to_pull)} days)")

    # Load cache
    cache = load_labor_cache(week_start)

    # Authenticate
    print("\n[1/4] Authenticating with Toast API...")
    token = toast_authenticate()
    print("  OK")

    # Determine which stores to pull
    store_numbers = sorted(TOAST_RESTAURANTS.keys())

    # Pull jobs and employees for each location (cached per run)
    print("\n[2/4] Loading job titles and employee lists...")
    all_jobs = {}
    all_employees = {}
    for store_num in store_numbers:
        r = TOAST_RESTAURANTS[store_num]
        print(f"    {store_num} {r['name']}...", end=" ", flush=True)
        all_jobs[store_num] = pull_jobs(token, r["guid"])
        all_employees[store_num] = pull_employees(token, r["guid"])
        print(f"{len(all_jobs[store_num])} jobs, {len(all_employees[store_num])} employees")
        time.sleep(0.2)

    # Pull sales and labor for each store
    print(f"\n[3/4] Pulling sales & labor data...")
    all_data = cache.get("store_data", {})

    for store_num in store_numbers:
        r = TOAST_RESTAURANTS[store_num]
        display_name = LOCATION_DISPLAY_NAMES.get(r["name"], r["name"])
        print(f"\n  {store_num} {display_name}:")

        if store_num not in all_data:
            all_data[store_num] = {"days": {}}

        for day in days_to_pull:
            date_str = day.strftime("%Y-%m-%d")
            day_name = day.strftime("%a")

            # Check cache: use cached data for completed days before yesterday
            if date_str in all_data[store_num]["days"] and day < yesterday:
                cached = all_data[store_num]["days"][date_str]
                print(f"    {day_name} {date_str}: cached (${cached.get('net_sales', 0):,.0f})")
                continue

            print(f"    {day_name} {date_str}: pulling...", end=" ", flush=True)

            # Pull sales
            try:
                sales = pull_orders_day(token, r["guid"], day)
            except Exception as e:
                print(f"sales error: {e}")
                sales = {"net_sales": 0, "orders": 0, "guests": 0, "avg_order": 0, "avg_guest": 0}

            time.sleep(0.15)

            # Pull labor detail (using businessDate for complete results)
            day_labor = pull_labor_detail(
                token, r["guid"], day,
                all_jobs.get(store_num, {}),
                all_employees.get(store_num, {})
            )

            # Calculate actual hours (excluding front-of-house)
            actual_hours = 0
            for entry in day_labor:
                if entry["job_title"] not in EXCLUDED_JOB_TITLES:
                    actual_hours += entry["total_hours"]

            # Calculate ideal hours
            ideal_hours = lookup_ideal_hours(sales["net_sales"])

            all_data[store_num]["days"][date_str] = {
                "net_sales": sales["net_sales"],
                "orders": sales["orders"],
                "guests": sales["guests"],
                "avg_order": sales.get("avg_order", 0),
                "avg_guest": sales.get("avg_guest", 0),
                "ideal_hours": round(ideal_hours, 2),
                "actual_hours": round(actual_hours, 2),
                "variance": round(actual_hours - ideal_hours, 2),
                "labor_detail": day_labor,
            }
            ns = sales["net_sales"]
            print(f"${ns:,.0f} | ideal: {ideal_hours:.0f}h | actual: {actual_hours:.0f}h | var: {actual_hours - ideal_hours:+.0f}h")

            time.sleep(0.15)

    # Save cache
    cache["store_data"] = all_data
    cache["week_start"] = week_start.strftime("%Y-%m-%d")
    cache["last_updated"] = datetime.now().isoformat()
    save_labor_cache(week_start, cache)

    # Build dashboard
    print(f"\n[4/4] Generating HTML dashboard...")

    dashboard_data = build_dashboard_data(
        all_data, week_start, week_end, week_dates, days_to_pull, today
    )

    html = generate_html(json.dumps(dashboard_data))
    outpath = os.path.join(OUTDIR, "labor_dashboard.html")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n{'=' * 60}")
    print(f"  Dashboard saved to: {outpath}")
    print(f"  Week: {week_start.strftime('%a %m/%d')} - {week_end.strftime('%a %m/%d')}")
    print(f"  Data through: {data_end.strftime('%a %m/%d')}")
    print(f"  Open labor_dashboard.html in your browser!")
    print(f"{'=' * 60}")


def build_dashboard_data(all_data, week_start, week_end, week_dates, days_to_pull, today):
    """Structure data for the HTML dashboard."""
    locations = []
    for store_num in sorted(TOAST_RESTAURANTS.keys()):
        r = TOAST_RESTAURANTS[store_num]
        display_name = LOCATION_DISPLAY_NAMES.get(r["name"], r["name"])
        store_data = all_data.get(store_num, {}).get("days", {})

        days = []
        wtd_sales = 0
        wtd_ideal = 0
        wtd_actual = 0

        for wd in week_dates:
            date_str = wd.strftime("%Y-%m-%d")
            day_name = WEEKDAY_NAMES[week_dates.index(wd)]
            day_data = store_data.get(date_str, None)

            if day_data and wd <= min(today - timedelta(days=1), week_end):
                wtd_sales += day_data["net_sales"]
                wtd_ideal += day_data["ideal_hours"]
                wtd_actual += day_data["actual_hours"]
                days.append({
                    "day": day_name,
                    "date": date_str,
                    "sales": round(day_data["net_sales"], 0),
                    "ideal": round(day_data["ideal_hours"], 1),
                    "actual": round(day_data["actual_hours"], 1),
                    "variance": round(day_data["variance"], 1),
                    "labor_detail": day_data.get("labor_detail", []),
                    "has_data": True,
                })
            else:
                days.append({
                    "day": day_name,
                    "date": date_str,
                    "sales": 0,
                    "ideal": 0,
                    "actual": 0,
                    "variance": 0,
                    "labor_detail": [],
                    "has_data": False,
                })

        locations.append({
            "store_num": store_num,
            "name": display_name,
            "days": days,
            "wtd_sales": round(wtd_sales, 0),
            "wtd_ideal": round(wtd_ideal, 1),
            "wtd_actual": round(wtd_actual, 1),
            "wtd_variance": round(wtd_actual - wtd_ideal, 1),
        })

    return {
        "generated": datetime.now().isoformat(),
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": week_end.strftime("%Y-%m-%d"),
        "today": today.strftime("%Y-%m-%d"),
        "locations": locations,
        "wage_guidelines": WAGE_GUIDELINES,
        "variance_allowances": VARIANCE_ALLOWANCES,
        "excluded_roles": list(EXCLUDED_JOB_TITLES),
        "gm_cap": GM_HOURS_CAP,
    }


def generate_html(data_json):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forage Kitchen - Daily Labor Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}

  .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 20px 30px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 24px; font-weight: 700; color: #f8fafc; }}
  .header h1 span {{ color: #f59e0b; }}
  .header .meta {{ text-align: right; font-size: 13px; color: #94a3b8; }}
  .header .meta .week {{ font-size: 16px; color: #f8fafc; font-weight: 600; }}

  .container {{ max-width: 1500px; margin: 0 auto; padding: 20px; }}

  /* Location grid - 2 columns matching Excel Leadsheet layout */
  .location-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}

  .location-card {{ background: #1e293b; border-radius: 12px; border: 1px solid #334155; overflow: hidden; }}
  .location-card .loc-header {{ background: #334155; padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }}
  .location-card .loc-header h3 {{ font-size: 15px; font-weight: 700; color: #f8fafc; }}
  .location-card .loc-header .wtd-badge {{ font-size: 12px; padding: 4px 10px; border-radius: 20px; font-weight: 600; }}
  .wtd-over {{ background: #ef444422; color: #ef4444; }}
  .wtd-under {{ background: #22c55e22; color: #22c55e; }}
  .wtd-even {{ background: #64748b22; color: #94a3b8; }}

  .loc-table {{ width: 100%; border-collapse: collapse; }}
  .loc-table th {{ padding: 8px 12px; text-align: right; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b; background: #172033; }}
  .loc-table th:first-child {{ text-align: left; }}
  .loc-table td {{ padding: 7px 12px; text-align: right; font-size: 13px; border-bottom: 1px solid #0f172a; }}
  .loc-table td:first-child {{ text-align: left; color: #94a3b8; font-weight: 500; }}
  .loc-table tr.no-data td {{ color: #475569; font-style: italic; }}
  .loc-table tr.wtd-row {{ background: #334155; font-weight: 700; }}
  .loc-table tr.wtd-row td {{ border-top: 2px solid #475569; font-size: 14px; }}

  .var-positive {{ color: #ef4444; }} /* over ideal = bad */
  .var-negative {{ color: #22c55e; }} /* under ideal = good */
  .var-zero {{ color: #94a3b8; }}

  /* Employee detail modal / expandable */
  .detail-overlay {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 100; justify-content: center; align-items: flex-start; padding-top: 40px; overflow-y: auto; }}
  .detail-overlay.active {{ display: flex; }}
  .detail-panel {{ background: #1e293b; border-radius: 12px; border: 1px solid #334155; width: 90%; max-width: 900px; margin-bottom: 40px; }}
  .detail-panel .panel-header {{ display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; background: #334155; border-radius: 12px 12px 0 0; }}
  .detail-panel .panel-header h2 {{ font-size: 18px; color: #f8fafc; }}
  .detail-panel .close-btn {{ background: none; border: none; color: #94a3b8; font-size: 24px; cursor: pointer; padding: 4px 8px; }}
  .detail-panel .close-btn:hover {{ color: #f8fafc; }}

  .detail-tabs {{ display: flex; gap: 2px; padding: 8px 16px; background: #172033; flex-wrap: wrap; }}
  .detail-tab {{ padding: 6px 14px; font-size: 12px; background: transparent; border: 1px solid #334155; border-radius: 6px; color: #94a3b8; cursor: pointer; }}
  .detail-tab:hover {{ background: #253352; color: #f8fafc; }}
  .detail-tab.active {{ background: #f59e0b; color: #0f172a; border-color: #f59e0b; font-weight: 700; }}

  .detail-content {{ padding: 16px; }}
  .emp-table {{ width: 100%; border-collapse: collapse; }}
  .emp-table th {{ padding: 8px 10px; text-align: left; font-size: 11px; text-transform: uppercase; color: #64748b; background: #172033; }}
  .emp-table th.right {{ text-align: right; }}
  .emp-table td {{ padding: 6px 10px; font-size: 13px; border-bottom: 1px solid #253352; }}
  .emp-table td.right {{ text-align: right; }}
  .emp-table tr:hover {{ background: #253352; }}
  .emp-table .gm-row {{ background: #f59e0b11; }}
  .emp-table .gm-badge {{ font-size: 10px; background: #f59e0b33; color: #f59e0b; padding: 2px 6px; border-radius: 4px; margin-left: 6px; }}
  .emp-table .excluded-row {{ color: #475569; text-decoration: line-through; }}
  .emp-table tr.total-row {{ background: #334155; font-weight: 700; }}
  .emp-table tr.total-row td {{ border-top: 2px solid #475569; }}

  /* Reference section */
  .ref-section {{ margin-top: 24px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .ref-card {{ background: #1e293b; border-radius: 12px; border: 1px solid #334155; padding: 16px; }}
  .ref-card h3 {{ font-size: 14px; color: #f59e0b; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .ref-table {{ width: 100%; border-collapse: collapse; }}
  .ref-table th {{ padding: 6px 10px; text-align: left; font-size: 11px; color: #64748b; background: #172033; }}
  .ref-table td {{ padding: 5px 10px; font-size: 12px; border-bottom: 1px solid #253352; color: #94a3b8; }}

  .refresh-notice {{ text-align: center; padding: 16px; color: #475569; font-size: 12px; margin-top: 20px; }}
  .refresh-notice code {{ background: #334155; padding: 2px 8px; border-radius: 4px; color: #94a3b8; }}

  @media (max-width: 900px) {{
    .location-grid {{ grid-template-columns: 1fr; }}
    .ref-section {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Forage Kitchen &mdash; <span>Daily Labor Report</span></h1>
  <div class="meta">
    <div class="week" id="weekLabel"></div>
    <div id="dateInfo"></div>
    <div id="lastUpdated" style="margin-top:4px; font-size:11px; color:#64748b;"></div>
  </div>
</div>

<div class="container">
  <div class="location-grid" id="locationGrid"></div>

  <div class="ref-section">
    <div class="ref-card" id="wageRef"></div>
    <div class="ref-card" id="varianceRef"></div>
  </div>

  <div class="refresh-notice">
    Run <code>python labor_dashboard.py</code> or double-click <code>refresh_labor.bat</code> to update
    &bull; GM hours capped at 8 &bull; Excludes: Cashier, Register, Customer Service, Host, SB Trainer
  </div>
</div>

<!-- Detail overlay -->
<div class="detail-overlay" id="detailOverlay">
  <div class="detail-panel">
    <div class="panel-header">
      <h2 id="detailTitle"></h2>
      <button class="close-btn" onclick="closeDetail()">&times;</button>
    </div>
    <div class="detail-tabs" id="detailTabs"></div>
    <div class="detail-content" id="detailContent"></div>
  </div>
</div>

<script>
const D = {data_json};

const fmt = (n) => n == null || n === 0 ? '—' : '$' + Number(n).toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
const fmtHrs = (n) => n == null ? '—' : Number(n).toFixed(1);
const fmtVar = (n, hasData) => {{
  if (!hasData) return '<span class="var-zero">—</span>';
  if (n === 0) return '<span class="var-zero">0.0</span>';
  const cls = n > 0 ? 'var-positive' : 'var-negative';
  const sign = n > 0 ? '+' : '';
  return `<span class="${{cls}}">${{sign}}${{n.toFixed(1)}}</span>`;
}};

// Header
const ws = new Date(D.week_start + 'T12:00:00');
const we = new Date(D.week_end + 'T12:00:00');
const opts = {{ month: 'short', day: 'numeric' }};
document.getElementById('weekLabel').textContent = `Week: ${{ws.toLocaleDateString('en-US', opts)}} - ${{we.toLocaleDateString('en-US', opts)}}`;
document.getElementById('dateInfo').textContent = `Wed through Tue business week`;
document.getElementById('lastUpdated').textContent = `Updated: ${{new Date(D.generated).toLocaleString()}}`;

// Build location cards
const grid = document.getElementById('locationGrid');
D.locations.forEach((loc, idx) => {{
  const card = document.createElement('div');
  card.className = 'location-card';

  const varCls = loc.wtd_variance > 0 ? 'wtd-over' : loc.wtd_variance < 0 ? 'wtd-under' : 'wtd-even';
  const varSign = loc.wtd_variance > 0 ? '+' : '';

  let tableRows = '';
  loc.days.forEach(d => {{
    if (d.has_data) {{
      tableRows += `<tr>
        <td>${{d.day}}</td>
        <td>${{fmt(d.sales)}}</td>
        <td>${{fmtHrs(d.ideal)}}</td>
        <td>${{fmtHrs(d.actual)}}</td>
        <td>${{fmtVar(d.variance, true)}}</td>
      </tr>`;
    }} else {{
      tableRows += `<tr class="no-data">
        <td>${{d.day}}</td><td>—</td><td>—</td><td>—</td><td>—</td>
      </tr>`;
    }}
  }});

  card.innerHTML = `
    <div class="loc-header" onclick="openDetail(${{idx}})">
      <h3>${{loc.name}}</h3>
      <span class="wtd-badge ${{varCls}}">WTD: ${{varSign}}${{loc.wtd_variance.toFixed(1)}}h</span>
    </div>
    <table class="loc-table">
      <thead><tr><th>Day</th><th>Sales</th><th>Ideal Hrs</th><th>Actual Hrs</th><th>Variance</th></tr></thead>
      <tbody>
        ${{tableRows}}
        <tr class="wtd-row">
          <td>WTD</td>
          <td>${{fmt(loc.wtd_sales)}}</td>
          <td>${{fmtHrs(loc.wtd_ideal)}}</td>
          <td>${{fmtHrs(loc.wtd_actual)}}</td>
          <td>${{fmtVar(loc.wtd_variance, loc.wtd_sales > 0)}}</td>
        </tr>
      </tbody>
    </table>
  `;
  grid.appendChild(card);
}});

// Wage guidelines reference
const wageRef = document.getElementById('wageRef');
let wageHtml = '<h3>Wage Guidelines</h3><table class="ref-table"><thead><tr><th>Position</th><th>Base</th><th>Tier 2</th><th>Tier 3</th><th>Tier 4</th></tr></thead><tbody>';
Object.entries(D.wage_guidelines).forEach(([pos, rates]) => {{
  wageHtml += `<tr><td>${{pos}}</td>${{rates.map(r => `<td>$${{r}}</td>`).join('')}}</tr>`;
}});
wageHtml += '</tbody></table>';
wageRef.innerHTML = wageHtml;

// Variance allowances reference
const varRef = document.getElementById('varianceRef');
let varHtml = '<h3>Allowable Hours Variance</h3><table class="ref-table"><thead><tr><th>Timeframe</th><th>Allowance</th></tr></thead><tbody>';
Object.entries(D.variance_allowances).forEach(([k, v]) => {{
  varHtml += `<tr><td>${{k}}</td><td>${{v}}</td></tr>`;
}});
varHtml += `</tbody></table>
<div style="margin-top:10px; font-size:11px; color:#64748b;">
  <div>GM hours capped at ${{D.gm_cap}}h (salaried)</div>
  <div>Excluded roles: ${{D.excluded_roles.join(', ')}}</div>
</div>`;
varRef.innerHTML = varHtml;

// Detail overlay
let currentLocIdx = null;
let currentDayIdx = 0;

function openDetail(locIdx) {{
  currentLocIdx = locIdx;
  const loc = D.locations[locIdx];
  document.getElementById('detailTitle').textContent = loc.name + ' — Employee Detail';

  // Build day tabs
  const tabs = document.getElementById('detailTabs');
  tabs.innerHTML = '';
  loc.days.forEach((d, i) => {{
    const tab = document.createElement('div');
    tab.className = 'detail-tab' + (d.has_data ? '' : ' no-data') + (i === 0 ? ' active' : '');
    tab.textContent = d.day + ' ' + d.date.slice(5);
    tab.onclick = () => showDayDetail(locIdx, i);
    if (!d.has_data) tab.style.opacity = '0.4';
    tabs.appendChild(tab);
  }});

  showDayDetail(locIdx, findFirstDataDay(loc));
  document.getElementById('detailOverlay').classList.add('active');
}}

function findFirstDataDay(loc) {{
  for (let i = 0; i < loc.days.length; i++) {{
    if (loc.days[i].has_data) return i;
  }}
  return 0;
}}

function showDayDetail(locIdx, dayIdx) {{
  currentDayIdx = dayIdx;
  const loc = D.locations[locIdx];
  const day = loc.days[dayIdx];

  // Update active tab
  document.querySelectorAll('.detail-tab').forEach((t, i) => {{
    t.classList.toggle('active', i === dayIdx);
  }});

  const content = document.getElementById('detailContent');
  if (!day.has_data || day.labor_detail.length === 0) {{
    content.innerHTML = '<div style="padding:20px; color:#64748b; text-align:center;">No labor data for this day.</div>';
    return;
  }}

  // Separate included and excluded employees
  const excluded = {json.dumps(list(EXCLUDED_JOB_TITLES))};
  const included = day.labor_detail.filter(e => !excluded.includes(e.job_title));
  const excludedEntries = day.labor_detail.filter(e => excluded.includes(e.job_title));

  // Sort: GMs first, then by hours descending
  included.sort((a, b) => {{
    if (a.is_gm !== b.is_gm) return a.is_gm ? -1 : 1;
    return b.total_hours - a.total_hours;
  }});

  let html = `<div style="margin-bottom:8px; font-size:12px; color:#64748b;">
    ${{day.day}} ${{day.date}} &bull; Sales: ${{fmt(day.sales)}} &bull;
    Ideal: ${{fmtHrs(day.ideal)}}h &bull; Actual: ${{fmtHrs(day.actual)}}h &bull;
    Variance: ${{fmtVar(day.variance, true)}}h
  </div>`;

  html += `<table class="emp-table">
    <thead><tr>
      <th>Employee</th><th>Job Title</th><th class="right">Reg Hrs</th><th class="right">OT Hrs</th><th class="right">Total Hrs</th><th class="right">Rate</th>
    </tr></thead><tbody>`;

  let totalReg = 0, totalOT = 0, totalHrs = 0;
  included.forEach(e => {{
    totalReg += e.regular_hours;
    totalOT += e.overtime_hours;
    totalHrs += e.total_hours;
    const gmBadge = e.is_gm ? (e.capped ? '<span class="gm-badge">GM capped at 8h</span>' : '<span class="gm-badge">GM</span>') : '';
    const cls = e.is_gm ? 'gm-row' : '';
    html += `<tr class="${{cls}}">
      <td>${{e.name}}${{gmBadge}}</td>
      <td>${{e.job_title}}</td>
      <td class="right">${{e.regular_hours.toFixed(2)}}</td>
      <td class="right">${{e.overtime_hours > 0 ? e.overtime_hours.toFixed(2) : '—'}}</td>
      <td class="right">${{e.total_hours.toFixed(2)}}</td>
      <td class="right">${{e.hourly_rate > 0 ? '$' + e.hourly_rate.toFixed(2) : '—'}}</td>
    </tr>`;
  }});

  html += `<tr class="total-row">
    <td colspan="2">Total (counted)</td>
    <td class="right">${{totalReg.toFixed(2)}}</td>
    <td class="right">${{totalOT.toFixed(2)}}</td>
    <td class="right">${{totalHrs.toFixed(2)}}</td>
    <td></td>
  </tr>`;
  html += '</tbody></table>';

  // Show excluded employees if any
  if (excludedEntries.length > 0) {{
    html += `<div style="margin-top:16px; font-size:12px; color:#64748b;">Excluded from hours total (front-of-house):</div>`;
    html += `<table class="emp-table" style="margin-top:4px;"><tbody>`;
    excludedEntries.forEach(e => {{
      html += `<tr class="excluded-row">
        <td>${{e.name}}</td><td>${{e.job_title}}</td>
        <td class="right">${{e.regular_hours.toFixed(2)}}</td>
        <td class="right">${{e.overtime_hours > 0 ? e.overtime_hours.toFixed(2) : '—'}}</td>
        <td class="right">${{e.total_hours.toFixed(2)}}</td>
        <td class="right">${{e.hourly_rate > 0 ? '$' + e.hourly_rate.toFixed(2) : '—'}}</td>
      </tr>`;
    }});
    html += '</tbody></table>';
  }}

  content.innerHTML = html;
}}

function closeDetail() {{
  document.getElementById('detailOverlay').classList.remove('active');
}}

// Close on overlay click (not panel click)
document.getElementById('detailOverlay').addEventListener('click', (e) => {{
  if (e.target === document.getElementById('detailOverlay')) closeDetail();
}});

// Close on Escape
document.addEventListener('keydown', (e) => {{
  if (e.key === 'Escape') closeDetail();
}});
</script>
</body>
</html>'''


if __name__ == "__main__":
    main()
