"""
Forage Kitchen - Weekly COGS Dashboard
Pulls AP Invoices, Credit Memos, Stock Counts, and Waste Logs from R365 OData API.
Generates an interactive HTML dashboard for weekly COGS tracking.

Usage: python cogs_dashboard.py
       Then open cogs_dashboard.html in your browser.

Data flow:
  - AP Invoices (purchases) from R365 Transaction/TransactionDetail
  - AP Credit Memos (vendor credits) from R365
  - Stock Counts (weekly inventory) from R365
  - Waste Logs from R365
  - Net Sales from Toast POS (for COGS % calculation)
  - Budget from budget_2026.json

GM Accountability:
  - GMs must complete inventory counts and approve invoices by Wednesday 8am
  - Dashboard flags missing counts and unapproved invoices per store
  - Business week: Wednesday through Tuesday (matches fiscal calendar)
"""
import base64
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
from r365_config import SSS_CONFIG, FISCAL_YEAR_STARTS
from toast_config import (
    TOAST_CLIENT_ID, TOAST_CLIENT_SECRET,
    TOAST_AUTH_URL, TOAST_API_BASE, TOAST_RESTAURANTS
)

# R365 Auth
R365_CRED = b'foragekitchen\x5chenry@foragekombucha.com:KingJames1!'
R365_AUTH = base64.b64encode(R365_CRED).decode()
R365_HEADERS = {"Authorization": "Basic " + R365_AUTH, "Accept": "application/json"}
R365_BASE = "https://odata.restaurant365.net/api/v2/views"

SSL_CTX = ssl.create_default_context()

# COGS GL account mapping
COGS_GL_ACCOUNTS = {
    "5110": "Food",
    "5210": "Packaging",
    "5310": "Beverage",
}

# Coverage Factor: R365 OData only exposes ~23% of actual COGS purchases.
# The bulk comes through EDI integrations (US Foods, Sysco, etc.) not in OData.
# This factor is calibrated from P1 2026 actuals: Actual COGS / R365 OData = 4.39x
# Recalibrate each closed period by comparing dashboard R365 invoices vs actual P&L COGS.
COGS_COVERAGE_FACTOR = 4.39  # Multiply R365 invoices by this to estimate true COGS
COGS_COVERAGE_SOURCE = "P1 2026"  # Period used to calibrate

# Transaction types we care about
COGS_TXN_TYPES = ["AP Invoice", "AP Credit Memo", "Stock Count", "Waste Log", "Item Transfer"]

# Store display names
STORE_NAMES = {k: v["name"] for k, v in SSS_CONFIG.items()}


# ============================================================
# R365 API HELPERS
# ============================================================
def r365_fetch(url, retries=3):
    """Make authenticated GET request to R365 OData API."""
    url = url.replace(" ", "%20")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=R365_HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 5
                print(f"      R365 error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                raise


def r365_fetch_all(url, max_records=50000):
    """Fetch all records from an R365 OData endpoint with pagination."""
    all_records = []
    skip = 0
    while True:
        page_url = f"{url}{'&' if '?' in url else '?'}$top=5000&$skip={skip}"
        data = r365_fetch(page_url)
        records = data.get("value", [])
        all_records.extend(records)
        if len(records) < 5000 or len(all_records) >= max_records:
            break
        skip += 5000
    return all_records


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
                wait = (attempt + 1) * 5
                print(f"\n      Rate limited (429), waiting {wait}s...", end="", flush=True)
                time.sleep(wait)
            else:
                raise


def pull_toast_sales_day(token, guid, date):
    """Pull net sales from Toast for a single day."""
    biz_date = date.strftime("%Y%m%d")
    net_sales = 0
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
                net_sales += (check.get("amount") or 0)
        if len(orders) < 100:
            break
        page += 1
    return round(net_sales, 2)


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
    today = datetime.now()
    for fy_year in sorted(FISCAL_YEAR_STARTS.keys(), reverse=True):
        periods = get_445_periods(FISCAL_YEAR_STARTS[fy_year])
        for p in periods:
            if p["start"] <= today <= p["end"]:
                return fy_year, p["period"], p["start"], p["end"]
    return None, None, None, None


def get_week_start(today=None):
    """Get the Wednesday that starts the current business week."""
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_since_wed = (today.weekday() - 2) % 7
    return today - timedelta(days=days_since_wed)


def get_period_weeks(period_start, period_end):
    """Break a fiscal period into Wed-Tue business weeks."""
    weeks = []
    current = period_start
    while current <= period_end:
        week_end = current + timedelta(days=6)
        if week_end > period_end:
            week_end = period_end
        weeks.append({"start": current, "end": week_end})
        current = week_end + timedelta(days=1)
    return weeks


# ============================================================
# CACHE
# ============================================================
def get_cache_path(cache_key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def load_cache(cache_key):
    path = get_cache_path(cache_key)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache_key, data):
    path = get_cache_path(cache_key)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ============================================================
# R365 DATA PULL
# ============================================================
def load_r365_reference():
    """Load locations and GL accounts from R365."""
    print("  Loading R365 locations...")
    locations = r365_fetch(R365_BASE + "/Location").get("value", [])
    loc_map = {}
    for loc in locations:
        loc_map[loc["locationId"]] = {
            "number": loc.get("locationNumber", ""),
            "name": loc.get("name", "")
        }
    print(f"    {len(loc_map)} locations")

    print("  Loading R365 GL accounts...")
    gl_accounts = r365_fetch(R365_BASE + "/GlAccount?$top=1000").get("value", [])
    gl_map = {}
    for acct in gl_accounts:
        gl_map[acct["glAccountId"]] = {
            "number": acct.get("glAccountNumber", ""),
            "name": acct.get("name", "")
        }
    print(f"    {len(gl_map)} GL accounts")

    print("  Loading R365 items...")
    items = r365_fetch_all(R365_BASE + "/Item")
    item_map = {}
    for item in items:
        item_map[item["itemId"]] = {
            "name": item.get("name", ""),
            "category1": item.get("category1", ""),
            "category2": item.get("category2", ""),
        }
    print(f"    {len(item_map)} items")

    return loc_map, gl_map, item_map


def pull_transactions_for_period(period_start, period_end):
    """Pull all COGS-related transactions for a fiscal period from R365.
    R365 requires date filters with max 31-day range, so we chunk by month.
    Stock Counts get +1 day grace period since GMs sometimes complete
    period-end counts on Wednesday morning (day after period close).
    """
    all_transactions = []
    current = period_start
    # Extend pull window by 1 day for stock counts entered morning after close
    pull_end = period_end + timedelta(days=1)

    while current <= pull_end:
        # Chunk end: up to 31 days or pull end
        chunk_end = min(current + timedelta(days=30), pull_end)
        start_str = current.strftime("%Y-%m-%dT00:00:00Z")
        end_str = chunk_end.strftime("%Y-%m-%dT23:59:59Z")

        for txn_type in COGS_TXN_TYPES:
            # Only extend the grace day for Stock Counts
            if txn_type != "Stock Count":
                txn_end = min(chunk_end, period_end)
                txn_end_str = txn_end.strftime("%Y-%m-%dT23:59:59Z")
            else:
                txn_end_str = end_str
            url = (f"{R365_BASE}/Transaction?$top=5000"
                   f"&$filter=type eq '{txn_type}'"
                   f" and date ge {start_str}"
                   f" and date le {txn_end_str}")
            try:
                data = r365_fetch(url)
                records = data.get("value", [])
                all_transactions.extend(records)
            except Exception as e:
                print(f"    Error pulling {txn_type} for {current.strftime('%Y-%m-%d')}-{chunk_end.strftime('%Y-%m-%d')}: {e}")

        current = chunk_end + timedelta(days=1)

    return all_transactions


def pull_transaction_details(transaction_ids):
    """Pull TransactionDetail rows for given transaction IDs.
    We pull all details and filter in memory since the API doesn't support
    filtering by transactionId directly.
    """
    all_details = r365_fetch_all(R365_BASE + "/TransactionDetail")
    txn_id_set = set(transaction_ids)
    return [td for td in all_details if td.get("transactionId", "") in txn_id_set]


def extract_vendor_name(txn_name):
    """Extract vendor name from transaction name.
    Format: 'AP Invoice - VENDOR NAME - INVOICE#'
    """
    if not txn_name:
        return "Unknown"
    parts = txn_name.split(" - ")
    if len(parts) >= 2:
        return parts[1].strip()
    return txn_name


# ============================================================
# SALES DATA (TOAST - CACHED)
# ============================================================
def pull_period_sales(token, period_start, period_end, cache_key):
    """Pull daily net sales from Toast for all stores in a period.
    Uses cache for completed days.
    Returns: {store_num: {date_str: net_sales}}
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    data_end = min(yesterday, period_end)

    store_sales = {}
    for store_num in sorted(TOAST_RESTAURANTS.keys()):
        restaurant = TOAST_RESTAURANTS[store_num]
        store_cache = load_cache(f"{cache_key}_cogs_sales_{store_num}")
        daily = {}
        from_cache = 0
        from_api = 0

        current = period_start
        while current <= data_end:
            date_str = current.strftime("%Y-%m-%d")
            if date_str in store_cache and current < yesterday:
                daily[date_str] = store_cache[date_str]
                from_cache += 1
            else:
                try:
                    ns = pull_toast_sales_day(token, restaurant["guid"], current)
                    daily[date_str] = ns
                    from_api += 1
                    time.sleep(0.1)
                except Exception as e:
                    print(f"      Sales error {store_num} {date_str}: {e}")
                    daily[date_str] = 0
            current += timedelta(days=1)

        # Save cache
        for ds, ns in daily.items():
            store_cache[ds] = ns
        save_cache(f"{cache_key}_cogs_sales_{store_num}", store_cache)

        store_sales[store_num] = daily
        total = sum(daily.values())
        print(f"    {store_num} {STORE_NAMES.get(store_num, '')}: "
              f"{len(daily)} days (cached: {from_cache}, pulled: {from_api}), ${total:,.0f}")

    return store_sales


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("  Forage Kitchen - Weekly COGS Dashboard Builder")
    print("  Data Source: R365 (Invoices/Inventory) + Toast (Sales)")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    # Support targeting a specific period: python cogs_dashboard.py P2
    # or: python cogs_dashboard.py 2  (just the number)
    target_period = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].upper().replace("P", "")
        try:
            target_period = int(arg)
        except ValueError:
            print(f"  Usage: python cogs_dashboard.py [P#]  e.g. P2")
            return

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if target_period:
        # Find the requested period in the current or recent fiscal year
        for fy_year in sorted(FISCAL_YEAR_STARTS.keys(), reverse=True):
            periods = get_445_periods(FISCAL_YEAR_STARTS[fy_year])
            if target_period <= len(periods):
                p = periods[target_period - 1]
                fy = fy_year
                period = target_period
                period_start = p["start"]
                period_end = p["end"]
                break
        else:
            print(f"  Error: Period {target_period} not found")
            return
        # For past periods, set "today" to period end so all data is included
        if period_end < today:
            today = period_end
    else:
        fy, period, period_start, period_end = get_current_period()

    yesterday = today - timedelta(days=1)
    current_week_start = get_week_start(today)
    current_week_end = current_week_start + timedelta(days=6)

    # All weeks in the period
    period_weeks = get_period_weeks(period_start, period_end)

    is_closed = period_end < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    status = "CLOSED" if is_closed else "Current"
    print(f"\n  {status}: FY{fy} Period {period}")
    print(f"  Period:  {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}")
    if not is_closed:
        print(f"  Current week: {current_week_start.strftime('%Y-%m-%d')} to {current_week_end.strftime('%Y-%m-%d')}")
    print(f"  Data through: {today.strftime('%Y-%m-%d')}")
    print(f"  Weeks in period: {len(period_weeks)}")

    cache_key = f"FY{fy}_P{period}"

    # --------------------------------------------------------
    # Step 1: Load R365 reference data
    # --------------------------------------------------------
    print("\n[1/5] Loading R365 reference data...")
    loc_map, gl_map, item_map = load_r365_reference()

    # Build GL ID -> COGS category lookup
    gl_to_cogs_cat = {}
    for gl_id, info in gl_map.items():
        num = info.get("number", "")
        if num in COGS_GL_ACCOUNTS:
            gl_to_cogs_cat[gl_id] = COGS_GL_ACCOUNTS[num]

    # Build location ID -> store number lookup
    loc_id_to_num = {lid: info["number"] for lid, info in loc_map.items()}

    # --------------------------------------------------------
    # Step 2: Pull COGS transactions from R365
    # --------------------------------------------------------
    print(f"\n[2/5] Pulling COGS transactions from R365 (FY{fy} P{period})...")
    transactions = pull_transactions_for_period(period_start, period_end)

    # Organize transactions by type
    txn_by_type = defaultdict(list)
    for txn in transactions:
        txn_by_type[txn.get("type", "Unknown")].append(txn)

    for txn_type, txns in sorted(txn_by_type.items()):
        print(f"    {txn_type}: {len(txns)} transactions")

    # Pull beginning inventory - stock counts from prior period end
    # GMs do period-end counts on the last day (Tue) or morning after (Wed)
    begin_inv_start = period_start - timedelta(days=3)
    begin_inv_end = period_start  # include period start for grace
    print(f"\n  Pulling beginning inventory counts "
          f"({begin_inv_start.strftime('%m/%d')} - {begin_inv_end.strftime('%m/%d')})...")
    begin_inv_url = (
        f"{R365_BASE}/Transaction?$top=5000"
        f"&$filter=type eq 'Stock Count'"
        f" and date ge {begin_inv_start.strftime('%Y-%m-%dT00:00:00Z')}"
        f" and date le {begin_inv_end.strftime('%Y-%m-%dT23:59:59Z')}"
    )
    try:
        begin_inv_data = r365_fetch(begin_inv_url)
        begin_inv_txns = begin_inv_data.get("value", [])
    except Exception as e:
        begin_inv_txns = []
        print(f"    Error: {e}")

    begin_inv_txn_ids = set(t["transactionId"] for t in begin_inv_txns)
    print(f"    {len(begin_inv_txns)} beginning inventory stock counts found")

    # Add beginning inventory txns to main list for detail pull
    existing_ids = {t["transactionId"] for t in transactions}
    for t in begin_inv_txns:
        if t["transactionId"] not in existing_ids:
            transactions.append(t)

    # --------------------------------------------------------
    # Step 3: Pull transaction details
    # --------------------------------------------------------
    print(f"\n[3/5] Pulling transaction details...")
    txn_ids = [t["transactionId"] for t in transactions]
    details = pull_transaction_details(txn_ids)
    print(f"    {len(details)} detail lines matched")

    # Build txn lookup
    txn_lookup = {t["transactionId"]: t for t in transactions}

    # --------------------------------------------------------
    # Process: Organize purchases, credits, waste, inventory by week and store
    # --------------------------------------------------------
    print(f"\n[4/5] Processing COGS data...")

    # Structure: {week_idx: {store_num: {metric: value}}}
    week_data = defaultdict(lambda: defaultdict(lambda: {
        "purchases_food": 0, "purchases_packaging": 0, "purchases_beverage": 0,
        "purchases_other": 0, "purchases_total": 0,
        "credits": 0,
        "waste": 0,
        "net_purchases": 0,
        "inventory_begin": 0, "inventory_end": 0, "inventory_adjustment": 0,
        "has_stock_count": False, "stock_count_date": None,
        "invoices_total": 0, "invoices_approved": 0, "invoices_unapproved": 0,
        "vendors": defaultdict(float),
        "waste_items": [],
    }))

    # Also track period-level totals
    period_data = defaultdict(lambda: {
        "purchases_food": 0, "purchases_packaging": 0, "purchases_beverage": 0,
        "purchases_other": 0, "purchases_total": 0,
        "credits": 0, "waste": 0, "net_purchases": 0,
        "inventory_begin": 0, "inventory_end": 0,
        "has_stock_count": False,
        "invoices_total": 0, "invoices_approved": 0,
        "vendors": defaultdict(float),
    })

    def date_to_week_idx(dt):
        """Map a date to the week index within the period."""
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00")).replace(tzinfo=None)
            except:
                return None
        for i, week in enumerate(period_weeks):
            if week["start"] <= dt <= week["end"]:
                return i
        return None

    # First pass: process beginning inventory stock counts (prior period end)
    begin_inventory = defaultdict(float)  # {store_num: total $}
    for td in details:
        txn_id = td.get("transactionId", "")
        if txn_id not in begin_inv_txn_ids:
            continue
        txn = txn_lookup.get(txn_id)
        if not txn:
            continue
        row_type = td.get("rowType", "")
        if row_type != "Detail":
            continue
        loc_id = td.get("locationId") or txn.get("locationId", "")
        store_num = loc_id_to_num.get(loc_id, "Unknown")
        if store_num == "Unknown" or store_num not in STORE_NAMES:
            continue
        gl_id = td.get("glAccountId", "")
        gl_info = gl_map.get(gl_id, {})
        gl_num = gl_info.get("number", "")
        if not gl_num.startswith("5"):
            continue
        amount = td.get("amount", 0) or 0
        begin_inventory[store_num] += amount

    if begin_inventory:
        print(f"\n  Beginning inventory (prior period-end counts):")
        for sn in sorted(begin_inventory.keys()):
            print(f"    {sn} {STORE_NAMES.get(sn, '')}: ${begin_inventory[sn]:,.2f}")
        print(f"    TOTAL: ${sum(begin_inventory.values()):,.2f}")
    else:
        print(f"\n  No beginning inventory counts found")

    # Second pass: process period transactions (skip beginning inventory)
    _grace_logged = set()  # Track which grace-period stock counts we've already logged
    for td in details:
        txn_id = td.get("transactionId", "")
        # Skip beginning inventory transactions
        if txn_id in begin_inv_txn_ids:
            continue
        txn = txn_lookup.get(txn_id)
        if not txn:
            continue

        txn_type = txn.get("type", "")
        txn_date_str = txn.get("date", "")
        txn_date = None
        try:
            txn_date = datetime.fromisoformat(txn_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except:
            continue

        week_idx = date_to_week_idx(txn_date)
        # Stock Counts get 1-day grace: if dated day after period end,
        # assign to last week (GMs sometimes complete counts Wed morning)
        if week_idx is None and txn_type == "Stock Count":
            grace_end = period_end + timedelta(days=1)
            if txn_date.date() == grace_end.date():
                week_idx = len(period_weeks) - 1
                if txn_id not in _grace_logged:
                    _grace_logged.add(txn_id)
                    print(f"    Note: Stock Count dated {txn_date_str[:10]} (day after period end) -> assigned to Week {week_idx + 1}")
        if week_idx is None:
            continue

        # Determine store
        loc_id = td.get("locationId") or txn.get("locationId", "")
        store_num = loc_id_to_num.get(loc_id, "Unknown")
        if store_num == "Unknown" or store_num not in STORE_NAMES:
            continue

        row_type = td.get("rowType", "")
        gl_id = td.get("glAccountId", "")
        gl_info = gl_map.get(gl_id, {})
        gl_num = gl_info.get("number", "")
        debit = td.get("debit", 0) or 0
        credit = td.get("credit", 0) or 0
        amount = td.get("amount", 0) or 0
        quantity = td.get("quantity", 0) or 0

        wd = week_data[week_idx][store_num]
        pd = period_data[store_num]

        if txn_type == "AP Invoice" and row_type == "Detail":
            # Categorize by GL account
            cogs_cat = gl_to_cogs_cat.get(gl_id, None)
            if gl_num.startswith("5"):
                if cogs_cat == "Food":
                    wd["purchases_food"] += debit
                    pd["purchases_food"] += debit
                elif cogs_cat == "Packaging":
                    wd["purchases_packaging"] += debit
                    pd["purchases_packaging"] += debit
                elif cogs_cat == "Beverage":
                    wd["purchases_beverage"] += debit
                    pd["purchases_beverage"] += debit
                else:
                    wd["purchases_other"] += debit
                    pd["purchases_other"] += debit
                wd["purchases_total"] += debit
                pd["purchases_total"] += debit

            # Track vendor
            vendor = extract_vendor_name(txn.get("name", ""))
            wd["vendors"][vendor] += debit
            pd["vendors"][vendor] += debit

            # Track invoice approval
            wd["invoices_total"] += 1
            pd["invoices_total"] += 1
            if txn.get("isApproved", False):
                wd["invoices_approved"] += 1
                pd["invoices_approved"] += 1
            else:
                wd["invoices_unapproved"] += 1

        elif txn_type == "AP Credit Memo" and row_type == "Detail":
            if gl_num.startswith("5"):
                wd["credits"] += credit
                pd["credits"] += credit

        elif txn_type == "Waste Log" and row_type == "Detail":
            waste_amt = abs(amount) if amount < 0 else debit
            wd["waste"] += waste_amt
            pd["waste"] += waste_amt
            # Track waste items
            item_info = item_map.get(td.get("itemId", ""), {})
            wd["waste_items"].append({
                "item": item_info.get("name", td.get("comment", "Unknown")),
                "qty": abs(quantity),
                "uom": td.get("unitOfMeasureName", ""),
                "amount": waste_amt,
            })

        elif txn_type == "Stock Count" and row_type == "Detail":
            if gl_num.startswith("5"):
                wd["has_stock_count"] = True
                wd["stock_count_date"] = txn_date_str[:10]
                pd["has_stock_count"] = True
                # Stock count: amount = ending inv value, previousCountTotal = beginning inv
                prev = td.get("previousCountTotal", 0) or 0
                adj = td.get("adjustment", 0) or 0
                wd["inventory_end"] += amount if amount else 0
                wd["inventory_begin"] += prev
                wd["inventory_adjustment"] += adj
                pd["inventory_end"] += amount if amount else 0
                pd["inventory_begin"] += prev

    # Calculate net purchases and inventory-method COGS per week/store
    for wi in week_data:
        for sn in week_data[wi]:
            wd = week_data[wi][sn]
            wd["net_purchases"] = wd["purchases_total"] - wd["credits"]
    # Use all known stores (not just period_data keys) so stores with beginning
    # inventory but no period transactions yet still get their BI assigned
    all_stores = set(period_data.keys()) | set(begin_inventory.keys()) | set(STORE_NAMES.keys())
    for sn in all_stores:
        pd_store = period_data[sn]  # defaultdict creates entry if needed
        pd_store["net_purchases"] = pd_store["purchases_total"] - pd_store["credits"]
        # Period COGS = Beginning Inventory + Net Purchases - Ending Inventory
        bi = begin_inventory.get(sn, 0)
        ei = pd_store["inventory_end"]  # from period-end stock counts
        np = pd_store["net_purchases"]
        pd_store["begin_inventory"] = bi
        if bi > 0 and ei > 0:
            pd_store["inv_cogs"] = bi + np - ei
        else:
            pd_store["inv_cogs"] = 0

    # Print COGS summary
    if any(period_data[sn].get("inv_cogs", 0) != 0 for sn in period_data):
        print(f"\n  COGS = Beginning Inv + Purchases - Ending Inv:")
        for sn in sorted(period_data.keys()):
            pd_store = period_data[sn]
            bi = pd_store.get("begin_inventory", 0)
            ei = pd_store.get("inventory_end", 0)
            np = pd_store.get("net_purchases", 0)
            cogs = pd_store.get("inv_cogs", 0)
            if bi > 0 or ei > 0:
                print(f"    {sn} {STORE_NAMES.get(sn, '')}: "
                      f"${bi:,.0f} + ${np:,.0f} - ${ei:,.0f} = ${cogs:,.0f}")

    # --------------------------------------------------------
    # Step 5: Pull Toast sales for COGS % calculation
    # --------------------------------------------------------
    print(f"\n[5/5] Pulling Toast sales for COGS % calculation...")
    toast_token = toast_authenticate()
    print("  Authenticated with Toast")
    store_sales = pull_period_sales(toast_token, period_start, period_end, cache_key)

    # Aggregate sales by week
    week_sales = defaultdict(lambda: defaultdict(float))
    period_sales = defaultdict(float)
    for store_num, daily_sales in store_sales.items():
        for date_str, ns in daily_sales.items():
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            wi = date_to_week_idx(dt)
            if wi is not None:
                week_sales[wi][store_num] += ns
            period_sales[store_num] += ns

    # --------------------------------------------------------
    # Load budget
    # --------------------------------------------------------
    budget = None
    budget_path = os.path.join(OUTDIR, "budget_2026.json")
    if os.path.exists(budget_path):
        with open(budget_path, "r") as f:
            budget = json.load(f)
        print(f"\n  Loaded budget data")

    # --------------------------------------------------------
    # Build dashboard data
    # --------------------------------------------------------
    print("\nBuilding dashboard data...")

    store_numbers = sorted(STORE_NAMES.keys())

    # Week summaries
    weeks_summary = []
    for wi, week in enumerate(period_weeks):
        week_stores = {}
        for sn in store_numbers:
            wd = week_data[wi][sn]
            ns = week_sales[wi].get(sn, 0)
            cogs_pct = round(wd["net_purchases"] / ns * 100, 1) if ns > 0 else 0

            # Convert vendors dict to serializable list
            top_vendors = sorted(wd["vendors"].items(), key=lambda x: -x[1])[:10]

            week_stores[sn] = {
                "name": STORE_NAMES.get(sn, sn),
                "net_sales": round(ns, 2),
                "purchases_food": round(wd["purchases_food"], 2),
                "purchases_packaging": round(wd["purchases_packaging"], 2),
                "purchases_beverage": round(wd["purchases_beverage"], 2),
                "purchases_other": round(wd["purchases_other"], 2),
                "purchases_total": round(wd["purchases_total"], 2),
                "credits": round(wd["credits"], 2),
                "waste": round(wd["waste"], 2),
                "net_purchases": round(wd["net_purchases"], 2),
                "cogs_pct": cogs_pct,
                "has_stock_count": wd["has_stock_count"],
                "stock_count_date": wd["stock_count_date"],
                "invoices_total": wd["invoices_total"],
                "invoices_approved": wd["invoices_approved"],
                "invoices_unapproved": wd["invoices_unapproved"],
                "top_vendors": [{"name": v, "amount": round(a, 2)} for v, a in top_vendors],
                "waste_items": sorted(wd["waste_items"], key=lambda x: -x["amount"])[:10],
            }

        # Week totals
        all_ns = sum(s["net_sales"] for s in week_stores.values())
        all_purchases = sum(s["purchases_total"] for s in week_stores.values())
        all_credits = sum(s["credits"] for s in week_stores.values())
        all_waste = sum(s["waste"] for s in week_stores.values())
        all_net = sum(s["net_purchases"] for s in week_stores.values())
        all_food = sum(s["purchases_food"] for s in week_stores.values())
        all_pkg = sum(s["purchases_packaging"] for s in week_stores.values())
        all_bev = sum(s["purchases_beverage"] for s in week_stores.values())

        is_current = week["start"] <= today <= week["end"] + timedelta(days=1)
        is_past = week["end"] < today

        weeks_summary.append({
            "week_num": wi + 1,
            "start": week["start"].strftime("%Y-%m-%d"),
            "end": week["end"].strftime("%Y-%m-%d"),
            "is_current": is_current,
            "is_past": is_past,
            "stores": week_stores,
            "totals": {
                "net_sales": round(all_ns, 2),
                "purchases_food": round(all_food, 2),
                "purchases_packaging": round(all_pkg, 2),
                "purchases_beverage": round(all_bev, 2),
                "purchases_total": round(all_purchases, 2),
                "credits": round(all_credits, 2),
                "waste": round(all_waste, 2),
                "net_purchases": round(all_net, 2),
                "cogs_pct": round(all_net / all_ns * 100, 1) if all_ns > 0 else 0,
            }
        })

    # Period totals by store
    period_store_data = {}
    for sn in store_numbers:
        pd = period_data[sn]
        ns = period_sales.get(sn, 0)
        cogs_pct = round(pd["net_purchases"] / ns * 100, 1) if ns > 0 else 0

        # Budget
        budget_cogs_pct = 0
        budget_cogs = 0
        if budget and sn in budget:
            sb = budget[sn].get(str(period), {})
            budget_cogs_pct = sb.get("cogs_pct", 0)
            budget_cogs = sb.get("cogs", 0)

        top_vendors = sorted(pd["vendors"].items(), key=lambda x: -x[1])[:10]

        bi = pd.get("begin_inventory", 0)
        ei = pd.get("inventory_end", 0)
        inv_cogs = pd.get("inv_cogs", 0)
        inv_cogs_pct = round(inv_cogs / ns * 100, 1) if ns > 0 and inv_cogs != 0 else 0

        period_store_data[sn] = {
            "name": STORE_NAMES.get(sn, sn),
            "net_sales": round(ns, 2),
            "purchases_food": round(pd["purchases_food"], 2),
            "purchases_packaging": round(pd["purchases_packaging"], 2),
            "purchases_beverage": round(pd["purchases_beverage"], 2),
            "purchases_other": round(pd.get("purchases_other", 0), 2),
            "purchases_total": round(pd["purchases_total"], 2),
            "credits": round(pd["credits"], 2),
            "waste": round(pd["waste"], 2),
            "net_purchases": round(pd["net_purchases"], 2),
            "cogs_pct": cogs_pct,
            "budget_cogs_pct": budget_cogs_pct,
            "budget_cogs": round(budget_cogs, 2),
            "has_stock_count": pd["has_stock_count"],
            "has_begin_inv": bi > 0,
            "invoices_total": pd["invoices_total"],
            "invoices_approved": pd["invoices_approved"],
            "top_vendors": [{"name": v, "amount": round(a, 2)} for v, a in top_vendors],
            "begin_inventory": round(bi, 2),
            "end_inventory": round(ei, 2),
            "inv_cogs": round(inv_cogs, 2),
            "inv_cogs_pct": inv_cogs_pct,
        }

    # All stores period totals
    all_period_ns = sum(s["net_sales"] for s in period_store_data.values())
    all_period_purchases = sum(s["purchases_total"] for s in period_store_data.values())
    all_period_credits = sum(s["credits"] for s in period_store_data.values())
    all_period_waste = sum(s["waste"] for s in period_store_data.values())
    all_period_net = sum(s["net_purchases"] for s in period_store_data.values())
    all_period_food = sum(s["purchases_food"] for s in period_store_data.values())
    all_period_pkg = sum(s["purchases_packaging"] for s in period_store_data.values())
    all_period_bev = sum(s["purchases_beverage"] for s in period_store_data.values())
    all_period_begin_inv = sum(s["begin_inventory"] for s in period_store_data.values())
    all_period_end_inv = sum(s["end_inventory"] for s in period_store_data.values())
    all_period_inv_cogs = sum(s["inv_cogs"] for s in period_store_data.values())

    # All stores budget
    all_budget_cogs_pct = 0
    if budget and "ALL" in budget:
        all_budget_cogs_pct = budget["ALL"].get(str(period), {}).get("cogs_pct", 0)

    # GM sign-off status: check which stores have stock counts for current week
    gm_status = {}
    current_week_idx = None
    for i, w in enumerate(period_weeks):
        if w["start"] <= today <= w["end"] + timedelta(days=1):
            current_week_idx = i
            break

    for sn in store_numbers:
        has_begin = begin_inventory.get(sn, 0) > 0
        if current_week_idx is not None:
            wd = week_data[current_week_idx][sn]
            gm_status[sn] = {
                "name": STORE_NAMES.get(sn, sn),
                "inventory_done": wd["has_stock_count"],
                "stock_count_date": wd["stock_count_date"],
                "begin_inv_done": has_begin,
                "invoices_total": wd["invoices_total"],
                "invoices_approved": wd["invoices_approved"],
                "invoices_unapproved": wd["invoices_unapproved"],
                "all_approved": wd["invoices_unapproved"] == 0 and wd["invoices_total"] > 0,
            }
        else:
            gm_status[sn] = {
                "name": STORE_NAMES.get(sn, sn),
                "inventory_done": False,
                "stock_count_date": None,
                "begin_inv_done": has_begin,
                "invoices_total": 0,
                "invoices_approved": 0,
                "invoices_unapproved": 0,
                "all_approved": False,
            }

    dashboard_data = {
        "generated": datetime.now().isoformat(),
        "fiscal_year": fy,
        "period": period,
        "period_start": period_start.strftime("%Y-%m-%d"),
        "period_end": period_end.strftime("%Y-%m-%d"),
        "today": today.strftime("%Y-%m-%d"),
        "current_week_start": current_week_start.strftime("%Y-%m-%d"),
        "current_week_end": current_week_end.strftime("%Y-%m-%d"),
        "weeks": weeks_summary,
        "period_stores": period_store_data,
        "period_totals": {
            "net_sales": round(all_period_ns, 2),
            "purchases_food": round(all_period_food, 2),
            "purchases_packaging": round(all_period_pkg, 2),
            "purchases_beverage": round(all_period_bev, 2),
            "purchases_total": round(all_period_purchases, 2),
            "credits": round(all_period_credits, 2),
            "waste": round(all_period_waste, 2),
            "net_purchases": round(all_period_net, 2),
            "cogs_pct": round(all_period_net / all_period_ns * 100, 1) if all_period_ns > 0 else 0,
            "budget_cogs_pct": all_budget_cogs_pct,
            "begin_inventory": round(all_period_begin_inv, 2),
            "end_inventory": round(all_period_end_inv, 2),
            "inv_cogs": round(all_period_inv_cogs, 2),
            "inv_cogs_pct": round(all_period_inv_cogs / all_period_ns * 100, 1) if all_period_ns > 0 and all_period_inv_cogs != 0 else 0,
        },
        "gm_status": gm_status,
        "store_order": store_numbers,
        "has_budget": budget is not None,
    }

    # --------------------------------------------------------
    # Scan for existing period dashboards to build period nav
    # --------------------------------------------------------
    import glob as _glob
    period_files = sorted(_glob.glob(os.path.join(OUTDIR, "cogs_P*_FY*.html")))
    available_periods = []
    for pf in period_files:
        fname = os.path.basename(pf)
        # Parse "cogs_P2_FY2026.html" -> period=2, fy=2026
        try:
            parts = fname.replace("cogs_P", "").replace(".html", "").split("_FY")
            p_num = int(parts[0])
            fy_num = int(parts[1])
            available_periods.append({"period": p_num, "fy": fy_num, "file": fname})
        except:
            continue

    # Add current period if not already in the list
    current_fname = f"cogs_P{period}_FY{fy}.html"
    if not any(ap["period"] == period and ap["fy"] == fy for ap in available_periods):
        available_periods.append({"period": period, "fy": fy, "file": current_fname})
    available_periods.sort(key=lambda x: (x["fy"], x["period"]))

    dashboard_data["available_periods"] = available_periods
    dashboard_data["current_file"] = current_fname

    # Generate HTML
    data_json = json.dumps(dashboard_data)
    html = generate_html(data_json)

    # Save period-specific file
    period_outpath = os.path.join(OUTDIR, current_fname)
    with open(period_outpath, "w", encoding="utf-8") as f:
        f.write(html)

    # Also save as main dashboard (always points to latest run)
    main_outpath = os.path.join(OUTDIR, "cogs_dashboard.html")
    with open(main_outpath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n{'=' * 60}")
    print(f"  COGS Dashboard saved to:")
    print(f"    {period_outpath}")
    print(f"    {main_outpath}")
    print(f"  FY{fy} Period {period}")
    print(f"  Period selector includes: {', '.join(f'P{ap['period']}' for ap in available_periods)}")
    print(f"{'=' * 60}")


def generate_html(data_json):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forage Kitchen - Weekly COGS Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}

  .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 20px 30px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 24px; font-weight: 700; color: #f8fafc; }}
  .header h1 span {{ color: #3b82f6; }}
  .header .meta {{ text-align: right; font-size: 13px; color: #94a3b8; }}
  .header .meta .period {{ font-size: 16px; color: #f8fafc; font-weight: 600; }}
  .header .meta .source {{ font-size: 11px; color: #3b82f6; text-transform: uppercase; letter-spacing: 1px; }}

  /* Period Selector */
  .period-nav {{ display: flex; align-items: center; gap: 8px; margin-top: 6px; justify-content: flex-end; }}
  .period-nav label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
  .period-select {{ background: #334155; color: #f8fafc; border: 1px solid #475569; border-radius: 6px; padding: 5px 28px 5px 10px; font-size: 13px; font-weight: 500; cursor: pointer; appearance: none; -webkit-appearance: none; -moz-appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 5l3 3 3-3' stroke='%2394a3b8' stroke-width='1.5' fill='none'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 8px center; }}
  .period-select:hover {{ border-color: #3b82f6; background-color: #3d4f6e; }}
  .period-select:focus {{ outline: none; border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,0.3); }}
  .period-select option {{ background: #1e293b; color: #f8fafc; }}
  .period-badge {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; letter-spacing: 0.5px; }}
  .period-badge.closed {{ background: #22c55e22; color: #22c55e; border: 1px solid #22c55e44; }}
  .period-badge.current {{ background: #3b82f622; color: #3b82f6; border: 1px solid #3b82f644; }}

  .container {{ max-width: 1500px; margin: 0 auto; padding: 20px; }}

  /* KPI Cards */
  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .kpi-card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .kpi-card .label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; margin-bottom: 8px; }}
  .kpi-card .value {{ font-size: 28px; font-weight: 700; color: #f8fafc; }}
  .kpi-card .sub {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
  .kpi-card .change {{ font-size: 14px; font-weight: 600; margin-top: 4px; }}
  .positive {{ color: #22c55e; }}
  .negative {{ color: #ef4444; }}
  .neutral {{ color: #94a3b8; }}
  .warning {{ color: #f59e0b; }}

  /* Section headers */
  .section-header {{ font-size: 18px; font-weight: 600; color: #f8fafc; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #334155; }}

  /* GM Status Grid */
  .gm-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .gm-card {{ background: #1e293b; border-radius: 10px; padding: 14px 16px; border: 1px solid #334155; }}
  .gm-card .store-name {{ font-size: 14px; font-weight: 700; color: #f8fafc; margin-bottom: 8px; }}
  .gm-card .check-row {{ display: flex; align-items: center; gap: 8px; font-size: 13px; margin: 4px 0; }}
  .gm-card .check-icon {{ width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; flex-shrink: 0; }}
  .check-done {{ background: #22c55e22; color: #22c55e; border: 1px solid #22c55e44; }}
  .check-missing {{ background: #ef444422; color: #ef4444; border: 1px solid #ef444444; }}
  .check-partial {{ background: #f59e0b22; color: #f59e0b; border: 1px solid #f59e0b44; }}

  /* Charts row */
  .charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .chart-card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .chart-card h3 {{ font-size: 14px; color: #94a3b8; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}

  /* Tables */
  .store-table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
  .store-table th {{ background: #334155; padding: 12px 16px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; font-weight: 600; }}
  .store-table th.right, .store-table td.right {{ text-align: right; }}
  .store-table td {{ padding: 12px 16px; border-bottom: 1px solid #1e293b; font-size: 14px; }}
  .store-table tr:nth-child(even) {{ background: #1e293b; }}
  .store-table tr:nth-child(odd) {{ background: #172033; }}
  .store-table tr:hover {{ background: #253352; }}
  .store-table tr.total-row {{ background: #334155 !important; font-weight: 700; }}
  .store-table tr.total-row td {{ border-top: 2px solid #4a5568; }}

  /* Week tabs */
  .tab-bar {{ display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }}
  .tab-btn {{ padding: 8px 16px; background: #1e293b; border: 1px solid #334155; border-radius: 8px; color: #94a3b8; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.2s; }}
  .tab-btn:hover {{ background: #253352; color: #f8fafc; }}
  .tab-btn.active {{ background: #3b82f6; color: #fff; border-color: #3b82f6; font-weight: 700; }}
  .tab-btn .current {{ font-size: 10px; display: block; color: #93c5fd; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  /* Vendor table */
  .vendor-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }}
  .vendor-card {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; }}
  .vendor-card h3 {{ font-size: 14px; color: #94a3b8; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .vendor-list {{ list-style: none; }}
  .vendor-list li {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #253352; font-size: 13px; }}
  .vendor-list li .v-name {{ color: #e2e8f0; }}
  .vendor-list li .v-amt {{ color: #94a3b8; font-weight: 500; }}

  .refresh-notice {{ text-align: center; padding: 12px; color: #64748b; font-size: 12px; margin-top: 20px; }}
  .refresh-notice code {{ background: #334155; padding: 2px 8px; border-radius: 4px; color: #94a3b8; }}

  @media (max-width: 768px) {{
    .charts-row {{ grid-template-columns: 1fr; }}
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
    .vendor-grid {{ grid-template-columns: 1fr; }}
    .header {{ flex-direction: column; gap: 10px; }}
    .header .meta {{ text-align: left; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Forage <span>Kitchen</span> &mdash; COGS Dashboard</h1>
  <div class="meta">
    <div class="period" id="periodLabel"></div>
    <div id="dateRange"></div>
    <div id="lastUpdated"></div>
    <div class="source">Data: R365 Inventory + Invoices + Toast Sales</div>
    <div class="period-nav">
      <label>Period:</label>
      <select id="periodSelect" class="period-select" onchange="switchPeriod(this.value)"></select>
      <span id="periodBadge" class="period-badge"></span>
    </div>
  </div>
</div>

<div class="container">
  <!-- KPI Cards -->
  <div class="kpi-row" id="kpiRow"></div>

  <!-- GM Sign-Off Status -->
  <div class="section-header">GM Weekly Sign-Off Status</div>
  <div class="gm-grid" id="gmGrid"></div>

  <!-- Charts -->
  <div class="charts-row">
    <div class="chart-card">
      <h3>Weekly R365 Purchases % vs Budget</h3>
      <canvas id="cogsPctChart" height="200"></canvas>
    </div>
    <div class="chart-card">
      <h3>R365 Invoice Breakdown (Period to Date)</h3>
      <canvas id="cogsBreakdownChart" height="200"></canvas>
    </div>
  </div>

  <!-- Store Scoreboard -->
  <div class="section-header">Store Scoreboard &mdash; Period to Date</div>
  <table class="store-table" id="storeTable"></table>

  <!-- Weekly Detail Tabs -->
  <div class="section-header">Weekly Detail</div>
  <div class="tab-bar" id="weekTabBar"></div>
  <div id="weekTabContents"></div>

  <!-- Top Vendors -->
  <div class="section-header">Top Vendors &mdash; Period to Date</div>
  <div class="vendor-grid" id="vendorGrid"></div>

  <div class="refresh-notice">
    Run <code>py cogs_dashboard.py</code> to update current period &bull;
    Run <code>py cogs_dashboard.py P2</code> for a specific period &bull;
    GMs: Inventory counts + invoice approval due by <strong>Wednesday 8am</strong> &bull;
    Generated <span id="refreshTime"></span>
  </div>
</div>

<script>
const D = {data_json};

const fmt = (n) => n == null ? '\\u2014' : '$' + Number(n).toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
const fmtPct = (n) => n == null ? '\\u2014' : n.toFixed(1) + '%';
const fmtChange = (n) => {{
  if (n == null) return '<span class="neutral">N/A</span>';
  const cls = n >= 0 ? 'positive' : 'negative';
  const sign = n >= 0 ? '+' : '';
  return `<span class="${{cls}}">${{sign}}${{n.toFixed(1)}}%</span>`;
}};
const dayNames = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const shortDate = (s) => {{
  const d = new Date(s + 'T12:00:00');
  return (d.getMonth()+1) + '/' + d.getDate();
}};

// Header
document.getElementById('periodLabel').textContent = `FY${{D.fiscal_year}} Period ${{D.period}}`;
document.getElementById('dateRange').textContent = `${{D.period_start}} to ${{D.period_end}}`;
document.getElementById('lastUpdated').textContent = `Updated: ${{new Date(D.generated).toLocaleString()}}`;
document.getElementById('refreshTime').textContent = new Date(D.generated).toLocaleString();

// Period Selector
const periodSelect = document.getElementById('periodSelect');
const periodBadge = document.getElementById('periodBadge');
const availablePeriods = D.available_periods || [];
const currentFile = D.current_file || '';

// Determine if current period is closed
const periodEndDate = new Date(D.period_end + 'T23:59:59');
const isClosed = periodEndDate < new Date();
periodBadge.textContent = isClosed ? 'CLOSED' : 'LIVE';
periodBadge.className = 'period-badge ' + (isClosed ? 'closed' : 'current');

availablePeriods.forEach(ap => {{
  const opt = document.createElement('option');
  opt.value = ap.file;
  opt.textContent = `P${{ap.period}} FY${{ap.fy}}`;
  if (ap.file === currentFile) opt.selected = true;
  periodSelect.appendChild(opt);
}});

function switchPeriod(file) {{
  if (file && file !== currentFile) {{
    window.location.href = file;
  }}
}}

// KPI Cards - Inventory method COGS
const pt = D.period_totals;
const hasInvCogs = pt.inv_cogs !== 0 && pt.begin_inventory > 0;
const invCogsPct = hasInvCogs ? pt.inv_cogs_pct : pt.cogs_pct;
const budgetVar = pt.budget_cogs_pct > 0 ? invCogsPct - pt.budget_cogs_pct : null;
const kpis = [
  {{ label: 'COGS $', value: hasInvCogs ? fmt(pt.inv_cogs) : fmt(pt.net_purchases), sub: hasInvCogs ? 'Begin Inv + Purchases - End Inv' : 'R365 Purchases (no inv counts yet)', change: null }},
  {{ label: 'COGS %', value: fmtPct(invCogsPct), sub: 'Budget: ' + fmtPct(pt.budget_cogs_pct), highlight: budgetVar != null ? -budgetVar : null, change: budgetVar != null ? -budgetVar : null, changeLabel: 'vs Budget' }},
  {{ label: 'Net Sales', value: fmt(pt.net_sales), sub: 'Toast POS', change: null }},
  {{ label: 'Begin Inventory', value: fmt(pt.begin_inventory), sub: 'Prior period-end count', change: null }},
  {{ label: 'End Inventory', value: fmt(pt.end_inventory), sub: 'Current period-end count', change: null }},
  {{ label: 'R365 Purchases', value: fmt(pt.net_purchases), sub: 'Invoices - Credits (R365 OData)', change: null }},
];

const kpiRow = document.getElementById('kpiRow');
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

// GM Sign-Off Status
const gmGrid = document.getElementById('gmGrid');
D.store_order.forEach(sn => {{
  const gm = D.gm_status[sn];
  if (!gm) return;
  const card = document.createElement('div');
  card.className = 'gm-card';

  const invIcon = gm.all_approved ? 'check-done' : (gm.invoices_approved > 0 ? 'check-partial' : 'check-missing');
  const invSymbol = gm.all_approved ? '\\u2713' : (gm.invoices_approved > 0 ? '!' : '\\u2717');
  const invText = gm.invoices_total > 0
    ? `${{gm.invoices_approved}}/${{gm.invoices_total}} approved` + (gm.invoices_unapproved > 0 ? ` (${{gm.invoices_unapproved}} pending)` : '')
    : 'No invoices this week';

  const beginIcon = gm.begin_inv_done ? 'check-done' : 'check-missing';
  const beginSymbol = gm.begin_inv_done ? '\\u2713' : '\\u2717';
  const beginText = gm.begin_inv_done ? 'Found' : 'Missing';

  const countIcon = gm.inventory_done ? 'check-done' : 'check-missing';
  const countSymbol = gm.inventory_done ? '\\u2713' : '\\u2717';
  const countText = gm.inventory_done
    ? `Completed ${{gm.stock_count_date || ''}}`
    : 'Not yet completed';

  card.innerHTML = `
    <div class="store-name">${{sn}} ${{gm.name}}</div>
    <div class="check-row">
      <div class="check-icon ${{beginIcon}}">${{beginSymbol}}</div>
      <div>Beginning Inv Count: ${{beginText}}</div>
    </div>
    <div class="check-row">
      <div class="check-icon ${{countIcon}}">${{countSymbol}}</div>
      <div>Ending Inv Count: ${{countText}}</div>
    </div>
    <div class="check-row">
      <div class="check-icon ${{invIcon}}">${{invSymbol}}</div>
      <div>Invoices: ${{invText}}</div>
    </div>
  `;
  gmGrid.appendChild(card);
}});

// COGS % by Week Chart
const weekLabels = D.weeks.map(w => 'Wk' + w.week_num + ' (' + shortDate(w.start) + ')');
const weekR365CogsPct = D.weeks.map(w => w.totals.cogs_pct);
const budgetLine = D.period_totals.budget_cogs_pct > 0 ? D.weeks.map(() => D.period_totals.budget_cogs_pct) : [];

const cogsPctDatasets = [
  {{ label: 'Weekly Purchases %', data: weekR365CogsPct, backgroundColor: '#3b82f688', borderColor: '#3b82f6', borderWidth: 2, type: 'bar' }},
];
if (budgetLine.length > 0) {{
  cogsPctDatasets.push({{ label: 'Budget COGS %', data: budgetLine, borderColor: '#ef444488', borderDash: [6,4], borderWidth: 2, pointRadius: 0, fill: false, type: 'line' }});
}}

new Chart(document.getElementById('cogsPctChart'), {{
  type: 'bar',
  data: {{ labels: weekLabels, datasets: cogsPctDatasets }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#64748b', callback: v => v + '%' }}, grid: {{ color: '#1e293b44' }}, suggestedMin: 20, suggestedMax: 40 }}
    }}
  }}
}});

// COGS Breakdown Donut - R365 invoice categories (what we can see)
new Chart(document.getElementById('cogsBreakdownChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Food', 'Packaging', 'Beverage', 'Waste'],
    datasets: [{{
      data: [pt.purchases_food, pt.purchases_packaging, pt.purchases_beverage, pt.waste],
      backgroundColor: ['#3b82f6', '#8b5cf6', '#22c55e', '#ef4444'],
      borderColor: '#0f172a',
      borderWidth: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ color: '#94a3b8', padding: 16 }} }},
    }}
  }}
}});

// Store Scoreboard Table - Inventory method COGS
const storeTable = document.getElementById('storeTable');
let tableHtml = `<thead><tr>
  <th>Store</th>
  <th class="right">Net Sales</th>
  <th class="right">Begin Inv</th>
  <th class="right">Purchases</th>
  <th class="right">End Inv</th>
  <th class="right">COGS $</th>
  <th class="right">COGS %</th>
  <th class="right">Budget %</th>
  <th class="right">Variance</th>
  <th class="right">Waste</th>
</tr></thead><tbody>`;

D.store_order.forEach(sn => {{
  const s = D.period_stores[sn];
  if (!s) return;
  // Use inv_cogs if available, otherwise fall back to net_purchases
  const hasCogs = s.has_begin_inv && s.has_stock_count;
  const cogsVal = hasCogs ? s.inv_cogs : s.net_purchases;
  const cogsPct = hasCogs ? s.inv_cogs_pct : s.cogs_pct;
  const bVar = s.budget_cogs_pct > 0 ? cogsPct - s.budget_cogs_pct : null;
  const varHtml = bVar != null
    ? `<span class="${{bVar <= 0 ? 'positive' : 'negative'}}">${{bVar > 0 ? '+' : ''}}${{bVar.toFixed(1)}}%</span>`
    : '<span class="neutral">\\u2014</span>';
  const cogsCls = cogsPct > 35 ? 'negative' : cogsPct > 32 ? 'warning' : 'positive';
  const biHtml = s.has_begin_inv ? fmt(s.begin_inventory) : '<span class="neutral">\\u2014</span>';
  const eiHtml = s.has_stock_count ? fmt(s.end_inventory) : '<span class="neutral">\\u2014</span>';

  tableHtml += `<tr>
    <td><strong>${{sn}}</strong> ${{s.name}}</td>
    <td class="right">${{fmt(s.net_sales)}}</td>
    <td class="right" style="color:#94a3b8">${{biHtml}}</td>
    <td class="right">${{fmt(s.net_purchases)}}</td>
    <td class="right" style="color:#94a3b8">${{eiHtml}}</td>
    <td class="right">${{fmt(cogsVal)}}</td>
    <td class="right"><span class="${{cogsCls}}">${{fmtPct(cogsPct)}}</span></td>
    <td class="right" style="color:#94a3b8">${{fmtPct(s.budget_cogs_pct)}}</td>
    <td class="right">${{varHtml}}</td>
    <td class="right" style="color:#f59e0b">${{fmt(s.waste)}}</td>
  </tr>`;
}});

// Total row
const totalCogsPct = hasInvCogs ? pt.inv_cogs_pct : pt.cogs_pct;
const totalBudgetVar = pt.budget_cogs_pct > 0 ? totalCogsPct - pt.budget_cogs_pct : null;
const totalVarHtml = totalBudgetVar != null
  ? `<span class="${{totalBudgetVar <= 0 ? 'positive' : 'negative'}}">${{totalBudgetVar > 0 ? '+' : ''}}${{totalBudgetVar.toFixed(1)}}%</span>`
  : '<span class="neutral">\\u2014</span>';
tableHtml += `<tr class="total-row">
  <td><strong>ALL STORES</strong></td>
  <td class="right">${{fmt(pt.net_sales)}}</td>
  <td class="right" style="color:#94a3b8">${{fmt(pt.begin_inventory)}}</td>
  <td class="right">${{fmt(pt.net_purchases)}}</td>
  <td class="right" style="color:#94a3b8">${{fmt(pt.end_inventory)}}</td>
  <td class="right">${{hasInvCogs ? fmt(pt.inv_cogs) : fmt(pt.net_purchases)}}</td>
  <td class="right">${{fmtPct(totalCogsPct)}}</td>
  <td class="right" style="color:#94a3b8">${{fmtPct(pt.budget_cogs_pct)}}</td>
  <td class="right">${{totalVarHtml}}</td>
  <td class="right" style="color:#f59e0b">${{fmt(pt.waste)}}</td>
</tr>`;
tableHtml += '</tbody>';
storeTable.innerHTML = tableHtml;

// Weekly Detail Tabs
const weekTabBar = document.getElementById('weekTabBar');
const weekTabContents = document.getElementById('weekTabContents');

D.weeks.forEach((w, i) => {{
  const btn = document.createElement('div');
  btn.className = 'tab-btn' + (w.is_current ? ' active' : '');
  btn.innerHTML = `Wk${{w.week_num}} (${{shortDate(w.start)}}-${{shortDate(w.end)}})${{w.is_current ? '<span class="current">Current</span>' : ''}}`;
  btn.onclick = (e) => switchWeekTab(i, e.target.closest('.tab-btn'));
  weekTabBar.appendChild(btn);

  const div = document.createElement('div');
  div.className = 'tab-content' + (w.is_current ? ' active' : '');
  div.id = 'week-tab-' + i;
  div.innerHTML = buildWeekTable(w);
  weekTabContents.appendChild(div);
}});

function buildWeekTable(w) {{
  let html = `<table class="store-table"><thead><tr>
    <th>Store</th>
    <th class="right">Net Sales</th>
    <th class="right">Food</th>
    <th class="right">Pkg</th>
    <th class="right">Bev</th>
    <th class="right">Purchases</th>
    <th class="right">Credits</th>
    <th class="right">Net COGS</th>
    <th class="right">COGS %</th>
    <th class="right">Waste</th>
    <th class="right">Inv Count</th>
  </tr></thead><tbody>`;

  D.store_order.forEach(sn => {{
    const s = w.stores[sn];
    if (!s) return;
    const cogsCls = s.cogs_pct > 35 ? 'negative' : s.cogs_pct > 32 ? 'warning' : 'positive';
    const countHtml = s.has_stock_count
      ? `<span class="positive">\\u2713 ${{s.stock_count_date ? s.stock_count_date.slice(5) : ''}}</span>`
      : '<span class="negative">\\u2717</span>';

    html += `<tr>
      <td><strong>${{sn}}</strong> ${{s.name}}</td>
      <td class="right">${{fmt(s.net_sales)}}</td>
      <td class="right">${{fmt(s.purchases_food)}}</td>
      <td class="right">${{fmt(s.purchases_packaging)}}</td>
      <td class="right">${{fmt(s.purchases_beverage)}}</td>
      <td class="right">${{fmt(s.purchases_total)}}</td>
      <td class="right" style="color:#94a3b8">${{fmt(s.credits)}}</td>
      <td class="right">${{fmt(s.net_purchases)}}</td>
      <td class="right"><span class="${{cogsCls}}">${{fmtPct(s.cogs_pct)}}</span></td>
      <td class="right" style="color:#f59e0b">${{fmt(s.waste)}}</td>
      <td class="right">${{countHtml}}</td>
    </tr>`;
  }});

  // Week total row
  const t = w.totals;
  html += `<tr class="total-row">
    <td><strong>TOTAL</strong></td>
    <td class="right">${{fmt(t.net_sales)}}</td>
    <td class="right">${{fmt(t.purchases_food)}}</td>
    <td class="right">${{fmt(t.purchases_packaging)}}</td>
    <td class="right">${{fmt(t.purchases_beverage)}}</td>
    <td class="right">${{fmt(t.purchases_total)}}</td>
    <td class="right" style="color:#94a3b8">${{fmt(t.credits)}}</td>
    <td class="right">${{fmt(t.net_purchases)}}</td>
    <td class="right">${{fmtPct(t.cogs_pct)}}</td>
    <td class="right" style="color:#f59e0b">${{fmt(t.waste)}}</td>
    <td class="right">\\u2014</td>
  </tr>`;

  html += '</tbody></table>';
  return html;
}}

function switchWeekTab(idx, btn) {{
  document.querySelectorAll('#weekTabBar .tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('#weekTabContents .tab-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('week-tab-' + idx).classList.add('active');
}}

// Top Vendors (period totals, split into two columns)
const vendorGrid = document.getElementById('vendorGrid');
const allVendors = {{}};
D.store_order.forEach(sn => {{
  const s = D.period_stores[sn];
  if (!s) return;
  s.top_vendors.forEach(v => {{
    allVendors[v.name] = (allVendors[v.name] || 0) + v.amount;
  }});
}});
const sortedVendors = Object.entries(allVendors).sort((a,b) => b[1] - a[1]);
const half = Math.ceil(sortedVendors.length / 2);
[sortedVendors.slice(0, half), sortedVendors.slice(half)].forEach((chunk, ci) => {{
  if (chunk.length === 0) return;
  const card = document.createElement('div');
  card.className = 'vendor-card';
  let html = `<h3>${{ci === 0 ? 'Top Vendors' : 'More Vendors'}}</h3><ul class="vendor-list">`;
  chunk.forEach(([name, amt]) => {{
    html += `<li><span class="v-name">${{name}}</span><span class="v-amt">${{fmt(amt)}}</span></li>`;
  }});
  html += '</ul>';
  card.innerHTML = html;
  vendorGrid.appendChild(card);
}});
</script>
</body>
</html>'''


if __name__ == "__main__":
    main()
