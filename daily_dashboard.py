"""
Forage Kitchen - Daily Sales Report Dashboard
Pulls live data from Toast POS API and generates an interactive HTML dashboard.

Usage: python daily_dashboard.py
       Then open daily_dashboard.html in your browser.

Features:
  - Daily net sales by store (current period)
  - Labor % by store (from Toast time entries)
  - Same Store Sales growth (YoY)
  - Guest counts and check averages
  - Store leaderboard
  - Budget vs Actual (when budget file is provided)
  - Local cache: only pulls new/missing days from Toast (fast refreshes)
  - Completed-day comparison: SSS only compares full days (through yesterday)
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
OUTDIR = "C:/Users/ascha/OneDrive/Desktop/forage-data"
CACHE_DIR = os.path.join(OUTDIR, "cache")

# Import configs
import sys
sys.path.insert(0, OUTDIR)
from r365_config import SSS_CONFIG, FISCAL_YEAR_STARTS
from toast_config import (
    TOAST_CLIENT_ID, TOAST_CLIENT_SECRET,
    TOAST_AUTH_URL, TOAST_API_BASE, TOAST_RESTAURANTS
)

SSL_CTX = ssl.create_default_context()


# ============================================================
# TOAST API HELPERS
# ============================================================
def toast_authenticate():
    """Authenticate with Toast API and return bearer token."""
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
    """Make authenticated GET request to Toast API with retry on 429."""
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
                wait = (attempt + 1) * 5  # 5s, 10s, 15s backoff
                print(f"\n      Rate limited (429), waiting {wait}s...", end="", flush=True)
                time.sleep(wait)
            else:
                raise


# ============================================================
# LOCAL CACHE
# ============================================================
def get_cache_path(cache_key):
    """Get file path for a cache key. Cache key format: 'FY2026_P2_current' or 'FY2025_P2_prior'."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def load_cache(cache_key):
    """Load cached data. Returns dict or empty dict if no cache."""
    path = get_cache_path(cache_key)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache_key, data):
    """Save data to cache."""
    path = get_cache_path(cache_key)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ============================================================
# 4-4-5 FISCAL CALENDAR
# ============================================================
def get_445_periods(fy_start_str):
    fy_start = datetime.strptime(fy_start_str, "%Y-%m-%d")
    periods = []
    current = fy_start
    pattern = [4, 4, 5, 4, 4, 5, 4, 4, 5, 4, 4, 5]
    for i, weeks in enumerate(pattern):
        period_start = current
        period_end = current + timedelta(weeks=weeks) - timedelta(days=1)
        periods.append({
            "period": i + 1,
            "start": period_start,
            "end": period_end,
            "weeks": weeks
        })
        current = period_end + timedelta(days=1)
    return periods


def get_current_period():
    """Determine which fiscal year and period today falls in."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for fy_year in sorted(FISCAL_YEAR_STARTS.keys(), reverse=True):
        periods = get_445_periods(FISCAL_YEAR_STARTS[fy_year])
        for p in periods:
            if p["start"] <= today <= p["end"]:
                return fy_year, p["period"], p["start"], p["end"]
    return None, None, None, None


def get_prior_year_dates(current_start, current_end, current_fy):
    """Get the equivalent prior year period dates."""
    prior_fy = current_fy - 1
    if prior_fy in FISCAL_YEAR_STARTS:
        prior_periods = get_445_periods(FISCAL_YEAR_STARTS[prior_fy])
        current_periods = get_445_periods(FISCAL_YEAR_STARTS[current_fy])
        for cp in current_periods:
            if cp["start"] == current_start:
                period_num = cp["period"]
                for pp in prior_periods:
                    if pp["period"] == period_num:
                        return pp["start"], pp["end"]
    return None, None


# ============================================================
# DATA PULL FUNCTIONS (TOAST)
# ============================================================
def pull_toast_orders_day(token, guid, date):
    """Pull orders from Toast for a single day.
    Returns dict: {net_sales, tax, tips, checks, guests}
    """
    biz_date = date.strftime("%Y%m%d")
    day_totals = {"net_sales": 0, "tax": 0, "tips": 0, "checks": 0, "guests": 0}

    page = 1
    while True:
        url = (f"{TOAST_API_BASE}/orders/v2/ordersBulk"
               f"?businessDate={biz_date}&pageSize=100&page={page}")
        orders = toast_get(url, token, guid)

        for order in orders:
            if order.get("voided"):
                continue
            for check in order.get("checks", []):
                if check.get("voided"):
                    continue
                day_totals["checks"] += 1
                day_totals["net_sales"] += (check.get("amount") or 0)
                day_totals["tax"] += (check.get("taxAmount") or 0)
                day_totals["guests"] += 1
                for p in check.get("payments", []):
                    day_totals["tips"] += (p.get("tipAmount") or 0)

        if len(orders) < 100:
            break
        page += 1

    return day_totals


def pull_toast_labor(token, store_num, guid, start_date, end_date):
    """Pull labor time entries from Toast for a store and date range.
    Returns dict: {date_str: {labor_cost, labor_hours}}
    """
    daily = defaultdict(lambda: {"labor_cost": 0, "labor_hours": 0})

    start_iso = start_date.strftime("%Y-%m-%dT00:00:00.000+0000")
    end_iso = end_date.strftime("%Y-%m-%dT23:59:59.000+0000")

    try:
        from urllib.parse import quote
        url = (f"{TOAST_API_BASE}/labor/v1/timeEntries"
               f"?startDate={quote(start_iso)}&endDate={quote(end_iso)}")
        entries = toast_get(url, token, guid)

        for entry in entries:
            biz_date = entry.get("businessDate", "")
            if not biz_date:
                continue
            # Format: "20250217" -> "2025-02-17"
            if len(str(biz_date)) == 8:
                biz_date = str(biz_date)
                date_str = f"{biz_date[:4]}-{biz_date[4:6]}-{biz_date[6:8]}"
            else:
                date_str = str(biz_date)

            hours = (entry.get("regularHours") or 0) + (entry.get("overtimeHours") or 0)
            wage = entry.get("hourlyWage") or 0
            cost = hours * wage

            daily[date_str]["labor_cost"] += cost
            daily[date_str]["labor_hours"] += hours

    except Exception as e:
        print(f"      Labor error {store_num}: {e}")

    return dict(daily)


# ============================================================
# CACHED DATA PULL WITH INCREMENTAL UPDATES
# ============================================================
def pull_sales_cached(token, store_num, guid, start_date, end_date, cache_key, yesterday):
    """Pull sales data, using cache for completed days and only fetching missing days from Toast.
    - Completed days (before yesterday) are cached and never re-fetched.
    - Yesterday is always re-fetched (to get final numbers).
    - Today is excluded entirely.
    Returns dict: {date_str: {net_sales, tax, tips, checks, guests}}
    """
    cache = load_cache(f"{cache_key}_sales_{store_num}")
    daily = {}
    days_from_cache = 0
    days_from_api = 0

    current = start_date
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")

        if date_str in cache and current < yesterday:
            # Completed day already cached — use it
            daily[date_str] = cache[date_str]
            days_from_cache += 1
        else:
            # Need to fetch from Toast (missing day, or yesterday needing refresh)
            try:
                day_totals = pull_toast_orders_day(token, guid, current)
                if day_totals["checks"] > 0:
                    daily[date_str] = day_totals
                days_from_api += 1
                time.sleep(0.1)
            except Exception as e:
                print(f"      Orders error {store_num} {date_str}: {e}")

        current += timedelta(days=1)

    # Save updated cache (all completed days)
    for date_str, data in daily.items():
        cache[date_str] = data
    save_cache(f"{cache_key}_sales_{store_num}", cache)

    return daily, days_from_cache, days_from_api


def pull_labor_cached(token, store_num, guid, start_date, end_date, cache_key, yesterday):
    """Pull labor data, using cache for completed days.
    Labor is pulled as a batch for only the uncached date range.
    Returns dict: {date_str: {labor_cost, labor_hours}}
    """
    cache = load_cache(f"{cache_key}_labor_{store_num}")
    daily = {}
    yesterday_str = yesterday.strftime("%Y-%m-%d")

    # Figure out which days we already have cached (and are completed)
    uncached_start = None
    current = start_date
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        if date_str in cache and current < yesterday:
            daily[date_str] = cache[date_str]
        else:
            if uncached_start is None:
                uncached_start = current
        current += timedelta(days=1)

    # If there are uncached days, fetch them in one batch
    if uncached_start is not None:
        new_labor = pull_toast_labor(token, store_num, guid, uncached_start, end_date)
        # Only merge data for dates in the uncached range (Toast can return partial
        # entries for earlier dates due to shifts crossing midnight)
        for date_str, data in new_labor.items():
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if dt >= uncached_start:
                daily[date_str] = data

    # Save updated cache (skip suspiciously low labor — likely incomplete Toast data)
    for date_str, data in daily.items():
        if data["labor_cost"] >= 50 or date_str not in cache:
            cache[date_str] = data
    save_cache(f"{cache_key}_labor_{store_num}", cache)

    return daily


# ============================================================
# BUDGET LOADER
# ============================================================
def load_budget():
    """Load budget data from budget_2026.json (generated by parse_budget.py)."""
    budget_json = os.path.join(OUTDIR, "budget_2026.json")

    if not os.path.exists(budget_json):
        budget_xlsx = None
        for f in os.listdir(OUTDIR):
            if "budget" in f.lower() and f.endswith(".xlsx"):
                budget_xlsx = os.path.join(OUTDIR, f)
                break

        if not budget_xlsx:
            print("  No budget file found")
            return None

        print(f"  Found budget Excel: {budget_xlsx}")
        print("  Run parse_budget.py first to generate budget_2026.json")
        return None

    with open(budget_json, "r") as f:
        budget = json.load(f)
    print(f"  Loaded budget for {len(budget)} stores")
    return budget


# ============================================================
# BUILD PERIOD DATA (reusable for multi-period support)
# ============================================================
def build_period_data(token, fy, period, period_start, period_end, today, yesterday, budget):
    """Build complete dashboard data dict for a single fiscal period.
    Uses cached data for completed days — fast for past periods.
    """
    data_end = min(yesterday, period_end)
    days_completed = (data_end - period_start).days + 1

    # Prior year equivalent period
    py_start, py_end = get_prior_year_dates(period_start, period_end, fy)
    py_compare_end = None
    if py_start:
        py_compare_end = min(py_start + timedelta(days=days_completed - 1), py_end)

    current_cache_key = f"FY{fy}_P{period}_current"
    prior_cache_key = f"FY{fy}_P{period}_prior"
    store_numbers = sorted(TOAST_RESTAURANTS.keys())

    # Pull current period sales (with caching)
    print(f"  Sales (P{period})...")
    current_sales = {}
    for store_num in store_numbers:
        restaurant = TOAST_RESTAURANTS[store_num]
        print(f"    {store_num} {restaurant['name']}...", end=" ", flush=True)
        store_sales, from_cache, from_api = pull_sales_cached(
            token, store_num, restaurant["guid"],
            period_start, data_end, current_cache_key, yesterday
        )
        current_sales[store_num] = store_sales
        total_ns = sum(d["net_sales"] for d in store_sales.values())
        print(f"{len(store_sales)} days (cached: {from_cache}, pulled: {from_api}), ${total_ns:,.0f}")

    # Pull current period labor (with caching)
    print(f"  Labor (P{period})...")
    current_labor = {}
    for store_num in store_numbers:
        restaurant = TOAST_RESTAURANTS[store_num]
        print(f"    {store_num} {restaurant['name']}...", end=" ", flush=True)
        store_labor = pull_labor_cached(
            token, store_num, restaurant["guid"],
            period_start, data_end, current_cache_key, yesterday
        )
        current_labor[store_num] = store_labor
        total_lc = sum(d["labor_cost"] for d in store_labor.values())
        total_hrs = sum(d["labor_hours"] for d in store_labor.values())
        print(f"{len(store_labor)} days, {total_hrs:,.0f} hrs, ${total_lc:,.0f} cost")

    # Pull prior year sales (with caching)
    prior_sales = {}
    if py_start:
        print(f"  Prior year sales (P{period})...")
        for store_num in store_numbers:
            restaurant = TOAST_RESTAURANTS[store_num]
            print(f"    {store_num} {restaurant['name']}...", end=" ", flush=True)
            store_py_sales, from_cache, from_api = pull_sales_cached(
                token, store_num, restaurant["guid"],
                py_start, py_compare_end, prior_cache_key, yesterday
            )
            prior_sales[store_num] = store_py_sales
            total_ns = sum(d["net_sales"] for d in store_py_sales.values())
            print(f"{len(store_py_sales)} days (cached: {from_cache}, pulled: {from_api}), ${total_ns:,.0f}")

    # Build store totals
    store_totals = {}
    for store_num in store_numbers:
        store_name = SSS_CONFIG.get(store_num, {}).get("name", TOAST_RESTAURANTS[store_num]["name"])
        totals = {
            "name": store_name,
            "net_sales": 0, "gross_sales": 0, "guests": 0, "checks": 0,
            "labor_cost": 0, "labor_hours": 0,
            "py_net_sales": 0, "py_guests": 0,
            "daily": []
        }

        store_dates = sorted(current_sales.get(store_num, {}).keys())
        for date_str in store_dates:
            day_sales = current_sales[store_num].get(date_str, {})
            day_labor = current_labor.get(store_num, {}).get(date_str, {})
            ns = day_sales.get("net_sales", 0)
            lc = day_labor.get("labor_cost", 0)
            totals["net_sales"] += ns
            totals["gross_sales"] += ns + day_sales.get("tax", 0)
            totals["guests"] += day_sales.get("guests", 0)
            totals["checks"] += day_sales.get("checks", 0)
            totals["labor_cost"] += lc
            totals["labor_hours"] += day_labor.get("labor_hours", 0)
            totals["daily"].append({
                "date": date_str,
                "net_sales": round(ns, 2),
                "labor_cost": round(lc, 2),
                "labor_pct": round(lc / ns * 100, 1) if ns > 0 else 0,
                "guests": day_sales.get("guests", 0),
                "checks": day_sales.get("checks", 0),
            })

        # Prior year totals
        store_py = prior_sales.get(store_num, {})
        for date_str in sorted(store_py.keys()):
            day_sales = store_py[date_str]
            totals["py_net_sales"] += day_sales.get("net_sales", 0)
            totals["py_guests"] += day_sales.get("guests", 0)

        # Match PY daily data by day-of-period
        py_dates = sorted(store_py.keys())
        for i, entry in enumerate(totals["daily"]):
            if i < len(py_dates):
                py_day_sales = store_py.get(py_dates[i], {})
                entry["py_net_sales"] = round(py_day_sales.get("net_sales", 0), 2)
            else:
                entry["py_net_sales"] = 0

        # Summary metrics
        ns = totals["net_sales"]
        totals["labor_pct"] = round(totals["labor_cost"] / ns * 100, 1) if ns > 0 else 0
        totals["avg_check"] = round(ns / totals["checks"], 2) if totals["checks"] > 0 else 0
        totals["sss_growth"] = None
        sss_cfg = SSS_CONFIG.get(store_num, {})
        sss_start = sss_cfg.get("sss_start_period")
        if sss_start and period >= sss_start and totals["py_net_sales"] > 0:
            totals["sss_growth"] = round(
                (totals["net_sales"] - totals["py_net_sales"]) / totals["py_net_sales"] * 100, 1
            )

        # Budget data
        if budget and store_num in budget:
            period_str = str(period)
            store_budget = budget[store_num].get(period_str, {})
            totals["budget_sales"] = store_budget.get("sales", 0)
            totals["budget_cogs_pct"] = store_budget.get("cogs_pct", 0)
            totals["budget_payroll_pct"] = store_budget.get("payroll_pct", 0)
            totals["budget_crew_wages_pct"] = store_budget.get("crew_wages_pct", 0)
            total_period_days = (period_end - period_start).days + 1
            prorate = days_completed / total_period_days
            totals["budget_sales_prorated"] = round(totals["budget_sales"] * prorate, 2)
            totals["budget_variance"] = round(
                (totals["net_sales"] - totals["budget_sales_prorated"]) / totals["budget_sales_prorated"] * 100, 1
            ) if totals["budget_sales_prorated"] > 0 else None
        else:
            totals["budget_sales"] = 0
            totals["budget_sales_prorated"] = 0
            totals["budget_variance"] = None
            totals["budget_cogs_pct"] = 0
            totals["budget_payroll_pct"] = 0
            totals["budget_crew_wages_pct"] = 0

        store_totals[store_num] = totals

    # All stores combined
    all_stores = {
        "name": "All Stores",
        "net_sales": sum(s["net_sales"] for s in store_totals.values()),
        "gross_sales": sum(s["gross_sales"] for s in store_totals.values()),
        "guests": sum(s["guests"] for s in store_totals.values()),
        "checks": sum(s["checks"] for s in store_totals.values()),
        "labor_cost": sum(s["labor_cost"] for s in store_totals.values()),
        "labor_hours": sum(s["labor_hours"] for s in store_totals.values()),
        "py_net_sales": sum(s["py_net_sales"] for s in store_totals.values()),
    }
    ns = all_stores["net_sales"]
    all_stores["labor_pct"] = round(all_stores["labor_cost"] / ns * 100, 1) if ns > 0 else 0
    all_stores["avg_check"] = round(ns / all_stores["checks"], 2) if all_stores["checks"] > 0 else 0

    # SSS for all eligible stores
    sss_current = sum(
        s["net_sales"] for num, s in store_totals.items()
        if SSS_CONFIG.get(num, {}).get("sss_start_period") and
           period >= SSS_CONFIG[num]["sss_start_period"]
    )
    sss_prior = sum(
        s["py_net_sales"] for num, s in store_totals.items()
        if SSS_CONFIG.get(num, {}).get("sss_start_period") and
           period >= SSS_CONFIG[num]["sss_start_period"]
    )
    all_stores["sss_growth"] = round((sss_current - sss_prior) / sss_prior * 100, 1) if sss_prior > 0 else None

    # Budget for all stores
    if budget and "ALL" in budget:
        all_budget = budget["ALL"].get(str(period), {})
        all_stores["budget_sales"] = all_budget.get("sales", 0)
        all_stores["budget_cogs_pct"] = all_budget.get("cogs_pct", 0)
        all_stores["budget_payroll_pct"] = all_budget.get("payroll_pct", 0)
        all_stores["budget_crew_wages_pct"] = all_budget.get("crew_wages_pct", 0)
        total_period_days = (period_end - period_start).days + 1
        prorate = days_completed / total_period_days
        all_stores["budget_sales_prorated"] = round(all_stores["budget_sales"] * prorate, 2)
        all_stores["budget_variance"] = round(
            (all_stores["net_sales"] - all_stores["budget_sales_prorated"]) / all_stores["budget_sales_prorated"] * 100, 1
        ) if all_stores["budget_sales_prorated"] > 0 else None
    else:
        all_stores["budget_sales"] = 0
        all_stores["budget_sales_prorated"] = 0
        all_stores["budget_variance"] = None
        all_stores["budget_cogs_pct"] = 0
        all_stores["budget_payroll_pct"] = 0
        all_stores["budget_crew_wages_pct"] = 0

    # Daily totals for all stores
    all_dates = sorted(set(
        date_str
        for store_data in current_sales.values()
        for date_str in store_data.keys()
    ))
    all_stores["daily"] = []
    py_all_dates = sorted(set(
        date_str
        for store_data in prior_sales.values()
        for date_str in store_data.keys()
    ))
    for i, date_str in enumerate(all_dates):
        day_ns = sum(
            current_sales.get(sn, {}).get(date_str, {}).get("net_sales", 0)
            for sn in store_numbers
        )
        day_lc = sum(
            current_labor.get(sn, {}).get(date_str, {}).get("labor_cost", 0)
            for sn in store_numbers
        )
        day_guests = sum(
            current_sales.get(sn, {}).get(date_str, {}).get("guests", 0)
            for sn in store_numbers
        )
        day_checks = sum(
            current_sales.get(sn, {}).get(date_str, {}).get("checks", 0)
            for sn in store_numbers
        )
        py_day_ns = 0
        if i < len(py_all_dates):
            py_date = py_all_dates[i]
            py_day_ns = sum(
                prior_sales.get(sn, {}).get(py_date, {}).get("net_sales", 0)
                for sn in store_numbers
            )
        all_stores["daily"].append({
            "date": date_str,
            "net_sales": round(day_ns, 2),
            "labor_cost": round(day_lc, 2),
            "labor_pct": round(day_lc / day_ns * 100, 1) if day_ns > 0 else 0,
            "guests": day_guests,
            "checks": day_checks,
            "py_net_sales": round(py_day_ns, 2),
        })

    return {
        "generated": datetime.now().isoformat(),
        "fiscal_year": fy,
        "period": period,
        "period_start": period_start.strftime("%Y-%m-%d"),
        "period_end": period_end.strftime("%Y-%m-%d"),
        "data_through": data_end.strftime("%Y-%m-%d"),
        "today": today.strftime("%Y-%m-%d"),
        "days_completed": days_completed,
        "stores": store_totals,
        "all_stores": all_stores,
        "store_order": store_numbers,
        "has_budget": budget is not None,
        "data_source": "Toast POS",
    }


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("  Forage Kitchen - Daily Sales Dashboard Builder")
    print("  Powered by Toast POS API")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    # Determine current period
    fy, period, period_start, period_end = get_current_period()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    # If first day of new period, default to previous completed period
    display_period = period
    display_start = period_start
    display_end = period_end
    if today == period_start:
        print(f"\n  First day of FY{fy} P{period} -- showing completed P{period - 1} instead")
        all_periods = get_445_periods(FISCAL_YEAR_STARTS[fy])
        prev = all_periods[period - 2]
        display_period = prev["period"]
        display_start = prev["start"]
        display_end = prev["end"]

    print(f"\n  Default: FY{fy} Period {display_period}")
    print(f"  Period:  {display_start.strftime('%Y-%m-%d')} to {display_end.strftime('%Y-%m-%d')}")

    # Authenticate
    print("\nAuthenticating with Toast API...")
    token = toast_authenticate()
    print("  Authenticated successfully")

    # Load budget
    print("\nChecking for budget data...")
    budget = load_budget()

    # Build data for display period
    print(f"\n--- FY{fy} P{display_period} ---")
    display_data = build_period_data(token, fy, display_period, display_start, display_end, today, yesterday, budget)

    # Build data for previous period (fully cached, fast)
    all_periods_list = get_445_periods(FISCAL_YEAR_STARTS[fy])
    prev_period_num = display_period - 1
    periods = {}
    period_options = []

    periods[f"P{display_period}"] = display_data
    period_options.append({
        "key": f"P{display_period}",
        "label": f"P{display_period} ({display_start.strftime('%m/%d')} - {display_end.strftime('%m/%d')})"
    })

    if prev_period_num >= 1:
        prev_p = all_periods_list[prev_period_num - 1]
        print(f"\n--- FY{fy} P{prev_period_num} [cached] ---")
        prev_data = build_period_data(token, fy, prev_period_num, prev_p["start"], prev_p["end"], today, yesterday, budget)
        periods[f"P{prev_period_num}"] = prev_data
        period_options.append({
            "key": f"P{prev_period_num}",
            "label": f"P{prev_period_num} ({prev_p['start'].strftime('%m/%d')} - {prev_p['end'].strftime('%m/%d')})"
        })

    # Sort options by period number
    period_options.sort(key=lambda x: int(x["key"][1:]))

    # Round all floats
    def round_dict(d):
        if isinstance(d, dict):
            return {k: round_dict(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [round_dict(v) for v in d]
        elif isinstance(d, float):
            return round(d, 2)
        return d

    periods = round_dict(periods)

    multi_data = {
        "periods": periods,
        "default": f"P{display_period}",
        "period_options": period_options,
    }

    # Generate HTML
    print("\nGenerating HTML dashboard...")
    data_json = json.dumps(multi_data)
    html = generate_html(data_json)

    outpath = os.path.join(OUTDIR, "daily_dashboard.html")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(html)

    data_end = min(yesterday, display_end)
    days_completed = (data_end - display_start).days + 1
    print(f"\n{'='*60}")
    print(f"  Dashboard saved to: {outpath}")
    print(f"  Default period: P{display_period} ({days_completed} completed days)")
    if prev_period_num >= 1:
        print(f"  Also includes: P{prev_period_num}")
    print(f"  Open in your browser to view!")
    print(f"{'='*60}")


def generate_html(data_json):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forage Kitchen - Daily Sales Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}

  .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 20px 30px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 24px; font-weight: 700; color: #f8fafc; }}
  .header h1 span {{ color: #22c55e; }}
  .header .meta {{ text-align: right; font-size: 13px; color: #94a3b8; }}
  .header .meta .period {{ font-size: 16px; color: #f8fafc; font-weight: 600; }}
  .header .meta .source {{ font-size: 11px; color: #f59e0b; text-transform: uppercase; letter-spacing: 1px; }}

  #periodSelect {{ background: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 6px 12px; font-size: 16px; font-weight: 600; cursor: pointer; outline: none; font-family: inherit; }}
  #periodSelect:hover {{ border-color: #22c55e; }}
  #periodSelect:focus {{ border-color: #22c55e; box-shadow: 0 0 0 2px rgba(34,197,94,0.2); }}

  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}

  /* KPI Cards */
  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .kpi-card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .kpi-card .label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; margin-bottom: 8px; }}
  .kpi-card .value {{ font-size: 28px; font-weight: 700; color: #f8fafc; }}
  .kpi-card .sub {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
  .kpi-card .change {{ font-size: 14px; font-weight: 600; margin-top: 4px; }}
  .kpi-card .change.positive {{ color: #22c55e; }}
  .kpi-card .change.negative {{ color: #ef4444; }}

  /* Section headers */
  .section-header {{ font-size: 18px; font-weight: 600; color: #f8fafc; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #334155; }}

  /* Charts row */
  .charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .chart-card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .chart-card h3 {{ font-size: 14px; color: #94a3b8; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}

  /* Store Table */
  .store-table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
  .store-table th {{ background: #334155; padding: 12px 16px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; font-weight: 600; }}
  .store-table th.right, .store-table td.right {{ text-align: right; }}
  .store-table td {{ padding: 12px 16px; border-bottom: 1px solid #1e293b; font-size: 14px; }}
  .store-table tr:nth-child(even) {{ background: #1e293b; }}
  .store-table tr:nth-child(odd) {{ background: #172033; }}
  .store-table tr:hover {{ background: #253352; }}
  .store-table tr.total-row {{ background: #334155 !important; font-weight: 700; }}
  .store-table tr.total-row td {{ border-top: 2px solid #4a5568; }}
  .positive {{ color: #22c55e; }}
  .negative {{ color: #ef4444; }}
  .neutral {{ color: #94a3b8; }}

  /* Daily detail table */
  .daily-table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; margin-top: 16px; }}
  .daily-table th {{ background: #334155; padding: 10px 12px; text-align: right; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #94a3b8; }}
  .daily-table th:first-child {{ text-align: left; }}
  .daily-table td {{ padding: 8px 12px; text-align: right; font-size: 13px; border-bottom: 1px solid #253352; }}
  .daily-table td:first-child {{ text-align: left; color: #94a3b8; }}
  .daily-table tr:hover {{ background: #253352; }}
  .daily-table .day-name {{ color: #f8fafc; font-weight: 500; }}

  /* Tabs for store detail */
  .tab-bar {{ display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }}
  .tab-btn {{ padding: 8px 16px; background: #1e293b; border: 1px solid #334155; border-radius: 8px; color: #94a3b8; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.2s; }}
  .tab-btn:hover {{ background: #253352; color: #f8fafc; }}
  .tab-btn.active {{ background: #22c55e; color: #0f172a; border-color: #22c55e; font-weight: 700; }}

  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  /* Refresh notice */
  .refresh-notice {{ text-align: center; padding: 12px; color: #64748b; font-size: 12px; margin-top: 20px; }}

  @media (max-width: 768px) {{
    .charts-row {{ grid-template-columns: 1fr; }}
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
    .header {{ flex-direction: column; gap: 10px; }}
    .header .meta {{ text-align: left; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Forage <span>Kitchen</span> &mdash; Daily Sales</h1>
  <div class="meta">
    <select id="periodSelect"></select>
    <div id="dateRange"></div>
    <div id="lastUpdated"></div>
    <div class="source" id="dataSource"></div>
  </div>
</div>

<div class="container">
  <!-- KPI Cards -->
  <div class="kpi-row" id="kpiRow"></div>

  <!-- Charts -->
  <div class="charts-row">
    <div class="chart-card">
      <h3>Daily Net Sales (Current vs Prior Year)</h3>
      <canvas id="salesChart" height="200"></canvas>
    </div>
    <div class="chart-card">
      <h3>Daily Labor %</h3>
      <canvas id="laborChart" height="200"></canvas>
    </div>
  </div>

  <!-- Store Scoreboard -->
  <div class="section-header">Store Scoreboard &mdash; Period to Date</div>
  <table class="store-table" id="storeTable"></table>

  <!-- Daily Detail by Store -->
  <div class="section-header">Daily Detail</div>
  <div class="tab-bar" id="tabBar"></div>
  <div id="tabContents"></div>

  <div class="refresh-notice">
    To refresh data, run <code>python daily_dashboard.py</code> &bull; Data through <span id="dataThrough"></span> &bull; Generated <span id="refreshTime"></span>
  </div>
</div>

<script>
const ALLDATA = {data_json};
const PERIODS = ALLDATA.periods;
let D = PERIODS[ALLDATA.default];

const dayNames = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const fmt = (n) => n == null ? '\u2014' : '$' + Number(n).toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
const fmtPct = (n) => n == null ? '\u2014' : n.toFixed(1) + '%';
const fmtChange = (n) => {{
  if (n == null) return '<span class="neutral">N/A</span>';
  const cls = n >= 0 ? 'positive' : 'negative';
  const sign = n >= 0 ? '+' : '';
  return `<span class="${{cls}}">${{sign}}${{n.toFixed(1)}}%</span>`;
}};

// Populate period selector
const periodSelect = document.getElementById('periodSelect');
ALLDATA.period_options.forEach(opt => {{
  const o = document.createElement('option');
  o.value = opt.key;
  o.textContent = 'FY' + PERIODS[opt.key].fiscal_year + ' ' + opt.label;
  if (opt.key === ALLDATA.default) o.selected = true;
  periodSelect.appendChild(o);
}});
periodSelect.addEventListener('change', function() {{ switchPeriod(this.value); }});

let salesChartInstance = null;
let laborChartInstance = null;

function buildDailyTable(daily) {{
  let html = `<table class="daily-table"><thead><tr>
    <th style="text-align:left">Date</th>
    <th>Net Sales</th>
    <th>Prior Year</th>
    <th>YoY Change</th>
    <th>Labor $</th>
    <th>Labor %</th>
    <th>Guests</th>
  </tr></thead><tbody>`;

  let totalNS = 0, totalPY = 0, totalLC = 0, totalGuests = 0;
  daily.forEach(d => {{
    const dt = new Date(d.date + 'T12:00:00');
    const dayName = dayNames[dt.getDay()];
    const yoyPct = d.py_net_sales > 0 ? ((d.net_sales - d.py_net_sales) / d.py_net_sales * 100) : null;
    const laborCls = d.labor_pct > 35 ? 'negative' : d.labor_pct > 30 ? 'neutral' : 'positive';

    totalNS += d.net_sales;
    totalPY += d.py_net_sales;
    totalLC += d.labor_cost;
    totalGuests += d.guests || 0;

    html += `<tr>
      <td><span class="day-name">${{dayName}}</span> ${{d.date}}</td>
      <td>${{fmt(d.net_sales)}}</td>
      <td style="color:#64748b">${{fmt(d.py_net_sales)}}</td>
      <td>${{yoyPct != null ? fmtChange(yoyPct) : '<span class="neutral">\u2014</span>'}}</td>
      <td>${{fmt(d.labor_cost)}}</td>
      <td><span class="${{laborCls}}">${{fmtPct(d.labor_pct)}}</span></td>
      <td>${{(d.guests || 0).toLocaleString()}}</td>
    </tr>`;
  }});

  // Totals row
  const totalLaborPct = totalNS > 0 ? totalLC / totalNS * 100 : 0;
  const totalYoy = totalPY > 0 ? ((totalNS - totalPY) / totalPY * 100) : null;
  const totalLaborCls = totalLaborPct > 35 ? 'negative' : totalLaborPct > 30 ? 'neutral' : 'positive';
  html += `<tr style="background:#334155;font-weight:700">
    <td>TOTAL</td>
    <td>${{fmt(totalNS)}}</td>
    <td style="color:#64748b">${{fmt(totalPY)}}</td>
    <td>${{totalYoy != null ? fmtChange(totalYoy) : '<span class="neutral">\u2014</span>'}}</td>
    <td>${{fmt(totalLC)}}</td>
    <td><span class="${{totalLaborCls}}">${{fmtPct(totalLaborPct)}}</span></td>
    <td>${{totalGuests.toLocaleString()}}</td>
  </tr>`;

  html += '</tbody></table>';
  return html;
}}

function renderDashboard(D) {{
  // Header info
  document.getElementById('dateRange').textContent = D.period_start + ' to ' + D.period_end + ' (' + D.days_completed + ' completed days)';
  document.getElementById('lastUpdated').textContent = 'Updated: ' + new Date(D.generated).toLocaleString();
  document.getElementById('refreshTime').textContent = new Date(D.generated).toLocaleString();
  document.getElementById('dataThrough').textContent = D.data_through;
  document.getElementById('dataSource').textContent = 'Data source: ' + (D.data_source || 'Toast POS');

  // KPI Cards
  const a = D.all_stores;
  const kpis = [
    {{ label: 'Period Net Sales', value: fmt(a.net_sales), sub: 'Budget: ' + fmt(a.budget_sales_prorated) + ' (prorated)', change: a.budget_variance, changeLabel: 'vs Budget' }},
    {{ label: 'SSS Growth', value: a.sss_growth != null ? (a.sss_growth >= 0 ? '+' : '') + a.sss_growth + '%' : 'N/A', sub: 'Same store sales YoY (' + D.days_completed + ' days)', change: null, highlight: a.sss_growth }},
    {{ label: 'Labor %', value: fmtPct(a.labor_pct), sub: 'Bgt Crew Wages: ' + fmtPct(a.budget_crew_wages_pct), change: a.budget_crew_wages_pct > 0 ? -(a.labor_pct - a.budget_crew_wages_pct) : null, changeLabel: 'vs Budget' }},
    {{ label: 'Avg Check', value: fmt(a.avg_check), sub: a.checks.toLocaleString() + ' checks', change: null }},
    {{ label: 'Guest Count', value: a.guests.toLocaleString(), sub: 'Period to date', change: null }},
    {{ label: 'Full Period Budget', value: fmt(a.budget_sales), sub: 'Pace: ' + (a.budget_sales > 0 ? (a.net_sales / a.budget_sales_prorated * 100).toFixed(0) + '% of prorated' : 'N/A'), change: null, highlight: a.budget_variance }},
  ];

  const kpiRow = document.getElementById('kpiRow');
  kpiRow.innerHTML = '';
  kpis.forEach(k => {{
    const card = document.createElement('div');
    card.className = 'kpi-card';
    let changeHtml = '';
    if (k.change != null) {{
      const cls = k.change >= 0 ? 'positive' : 'negative';
      const sign = k.change >= 0 ? '+' : '';
      changeHtml = `<div class="change ${{cls}}">${{sign}}${{k.change.toFixed(1)}}% ${{k.changeLabel || ''}}</div>`;
    }}
    let valueColor = '';
    if (k.highlight != null) {{
      valueColor = k.highlight >= 0 ? 'color:#22c55e' : 'color:#ef4444';
    }}
    card.innerHTML = `<div class="label">${{k.label}}</div><div class="value" style="${{valueColor}}">${{k.value}}</div><div class="sub">${{k.sub}}</div>${{changeHtml}}`;
    kpiRow.appendChild(card);
  }});

  // Sales Chart
  const dailyData = a.daily || [];
  const labels = dailyData.map(d => {{
    const dt = new Date(d.date + 'T12:00:00');
    return dayNames[dt.getDay()] + ' ' + (dt.getMonth()+1) + '/' + dt.getDate();
  }});

  if (salesChartInstance) salesChartInstance.destroy();
  salesChartInstance = new Chart(document.getElementById('salesChart'), {{
    type: 'bar',
    data: {{
      labels: labels,
      datasets: [
        {{ label: 'Current Year', data: dailyData.map(d => d.net_sales), backgroundColor: '#22c55e88', borderColor: '#22c55e', borderWidth: 1 }},
        {{ label: 'Prior Year', data: dailyData.map(d => d.py_net_sales), backgroundColor: '#64748b44', borderColor: '#64748b', borderWidth: 1 }},
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, grid: {{ color: '#1e293b' }} }},
        y: {{ ticks: {{ color: '#64748b', callback: v => '$' + (v/1000).toFixed(0) + 'k' }}, grid: {{ color: '#1e293b44' }} }}
      }}
    }}
  }});

  // Labor Chart
  const budgetCrewPct = a.budget_crew_wages_pct || 0;
  const budgetCrewLine = budgetCrewPct > 0 ? dailyData.map(() => budgetCrewPct) : [];
  const laborDatasets = [
    {{ label: 'Labor %', data: dailyData.map(d => d.labor_pct), borderColor: '#f59e0b', backgroundColor: '#f59e0b22', fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: '#f59e0b' }},
  ];
  if (budgetCrewLine.length > 0) {{
    laborDatasets.push({{ label: 'Bgt Crew Wages %', data: budgetCrewLine, borderColor: '#ef444488', borderDash: [6, 4], borderWidth: 2, pointRadius: 0, fill: false }});
  }}
  if (laborChartInstance) laborChartInstance.destroy();
  laborChartInstance = new Chart(document.getElementById('laborChart'), {{
    type: 'line',
    data: {{
      labels: labels,
      datasets: laborDatasets,
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, grid: {{ color: '#1e293b' }} }},
        y: {{ ticks: {{ color: '#64748b', callback: v => v + '%' }}, grid: {{ color: '#1e293b44' }}, suggestedMin: 15, suggestedMax: 45 }}
      }}
    }}
  }});

  // Store Scoreboard Table
  const storeTable = document.getElementById('storeTable');
  let tableHtml = `<thead><tr>
    <th>Store</th>
    <th class="right">Net Sales</th>
    <th class="right">Budget (pro)</th>
    <th class="right">vs Budget</th>
    <th class="right">Prior Year</th>
    <th class="right">SSS Growth</th>
    <th class="right">Labor %</th>
    <th class="right">Bgt Crew %</th>
    <th class="right">Guests</th>
    <th class="right">Avg Check</th>
  </tr></thead><tbody>`;

  D.store_order.forEach(num => {{
    const s = D.stores[num];
    if (!s) return;
    const sssHtml = s.sss_growth != null ? fmtChange(s.sss_growth) : '<span class="neutral">N/A</span>';
    const budgetVarHtml = s.budget_variance != null ? fmtChange(s.budget_variance) : '<span class="neutral">\u2014</span>';
    const laborCls = s.labor_pct > 35 ? 'negative' : s.labor_pct > 30 ? 'neutral' : 'positive';
    tableHtml += `<tr>
      <td><strong>${{num}}</strong> ${{s.name}}</td>
      <td class="right">${{fmt(s.net_sales)}}</td>
      <td class="right" style="color:#94a3b8">${{fmt(s.budget_sales_prorated)}}</td>
      <td class="right">${{budgetVarHtml}}</td>
      <td class="right" style="color:#94a3b8">${{fmt(s.py_net_sales)}}</td>
      <td class="right">${{sssHtml}}</td>
      <td class="right"><span class="${{laborCls}}">${{fmtPct(s.labor_pct)}}</span></td>
      <td class="right" style="color:#94a3b8">${{fmtPct(s.budget_crew_wages_pct)}}</td>
      <td class="right">${{s.guests.toLocaleString()}}</td>
      <td class="right">${{fmt(s.avg_check)}}</td>
    </tr>`;
  }});

  // Total row
  const aBudgetVarHtml = a.budget_variance != null ? fmtChange(a.budget_variance) : '<span class="neutral">\u2014</span>';
  tableHtml += `<tr class="total-row">
    <td><strong>ALL STORES</strong></td>
    <td class="right">${{fmt(a.net_sales)}}</td>
    <td class="right" style="color:#94a3b8">${{fmt(a.budget_sales_prorated)}}</td>
    <td class="right">${{aBudgetVarHtml}}</td>
    <td class="right" style="color:#94a3b8">${{fmt(a.py_net_sales)}}</td>
    <td class="right">${{a.sss_growth != null ? fmtChange(a.sss_growth) : '<span class="neutral">N/A</span>'}}</td>
    <td class="right">${{fmtPct(a.labor_pct)}}</td>
    <td class="right" style="color:#94a3b8">${{fmtPct(a.budget_crew_wages_pct)}}</td>
    <td class="right">${{a.guests.toLocaleString()}}</td>
    <td class="right">${{fmt(a.avg_check)}}</td>
  </tr>`;
  tableHtml += '</tbody>';
  storeTable.innerHTML = tableHtml;

  // Daily Detail Tabs
  const tabBar = document.getElementById('tabBar');
  const tabContents = document.getElementById('tabContents');
  tabBar.innerHTML = '';
  tabContents.innerHTML = '';

  // Add "All Stores" tab first
  const allBtn = document.createElement('div');
  allBtn.className = 'tab-btn active';
  allBtn.textContent = 'All Stores';
  allBtn.onclick = function() {{ switchTab('all', this); }};
  tabBar.appendChild(allBtn);

  D.store_order.forEach(num => {{
    const s = D.stores[num];
    if (!s) return;
    const btn = document.createElement('div');
    btn.className = 'tab-btn';
    btn.textContent = num + ' ' + s.name;
    btn.onclick = function() {{ switchTab(num, this); }};
    tabBar.appendChild(btn);
  }});

  // Build tab content for all stores
  const allDiv = document.createElement('div');
  allDiv.className = 'tab-content active';
  allDiv.id = 'tab-all';
  allDiv.innerHTML = buildDailyTable(a.daily || []);
  tabContents.appendChild(allDiv);

  D.store_order.forEach(num => {{
    const s = D.stores[num];
    if (!s) return;
    const div = document.createElement('div');
    div.className = 'tab-content';
    div.id = 'tab-' + num;
    div.innerHTML = buildDailyTable(s.daily || []);
    tabContents.appendChild(div);
  }});
}}

function switchTab(id, btn) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + id).classList.add('active');
}}

function switchPeriod(key) {{
  D = PERIODS[key];
  renderDashboard(D);
}}

// Initial render
renderDashboard(D);
</script>
</body>
</html>'''


if __name__ == "__main__":
    main()
