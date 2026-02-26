"""
Forage Kitchen - Product Mix Analysis: P1 vs P2 FY2026
Compares item-level sales from Toast and vendor pricing from R365
to explain COGS savings between periods.

Usage: python product_mix_analysis.py
       python product_mix_analysis.py --debug    (prints sample Toast selections)
       Then open product_mix_analysis.html in your browser.

Data flow:
  - Product mix (items sold, quantities, revenue) from Toast Orders API
  - Vendor pricing (AP Invoice line items, unit costs) from R365 OData API
  - Comparison: P1 vs P2 by item, by category, by vendor
"""
import base64
import urllib.request
import json
import os
import ssl
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# CONFIG
# ============================================================
OUTDIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(OUTDIR, "cache")

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

COGS_GL_PREFIXES = {"5110": "Food", "5210": "Packaging", "5310": "Beverage"}
STORE_NAMES = {k: v["name"] for k, v in SSS_CONFIG.items()}

DEBUG = "--debug" in sys.argv
_debug_printed_selection = False  # Only print one sample selection globally


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


# ============================================================
# LOCAL CACHE
# ============================================================
def get_cache_path(cache_key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def load_cache(cache_key):
    path = get_cache_path(cache_key)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"      Warning: Corrupted cache {cache_key}, re-pulling...")
            os.remove(path)
    return {}


def save_cache(cache_key, data):
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


def get_period_dates(fy, period):
    """Get (start, end) dates for a specific fiscal year and period number."""
    periods = get_445_periods(FISCAL_YEAR_STARTS[fy])
    p = periods[period - 1]
    return p["start"], p["end"]


# ============================================================
# TOAST MENU LOOKUPS
# ============================================================
def pull_toast_lookups(token, guid):
    """Pull sales categories and menu groups from Toast Config API.
    Returns (sales_cat_map, menu_group_map) — both guid -> name.
    """
    sales_cat_map = {}
    try:
        url = f"{TOAST_API_BASE}/config/v2/salesCategories"
        cats = toast_get(url, token, guid)
        for cat in cats:
            sales_cat_map[cat.get("guid", "")] = cat.get("name", "").lstrip("-").strip()
    except Exception as e:
        print(f"    Warning: Could not pull sales categories: {e}")

    menu_group_map = {}
    try:
        url = f"{TOAST_API_BASE}/config/v2/menuGroups"
        groups = toast_get(url, token, guid)
        for g in groups:
            name = g.get("name", "").rstrip(".").strip()
            menu_group_map[g.get("guid", "")] = name
    except Exception as e:
        print(f"    Warning: Could not pull menu groups: {e}")

    return sales_cat_map, menu_group_map


# ============================================================
# TOAST PRODUCT MIX PULL
# ============================================================
def pull_product_mix_day(token, guid, date, menu_group_map, sales_cat_map):
    """Pull item-level selections from Toast for a single business day.
    Returns list of dicts: [{item, qty, revenue, category, sales_category}, ...]
    """
    global _debug_printed_selection
    biz_date = date.strftime("%Y%m%d")
    items = []

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
                for sel in check.get("selections", []):
                    if sel.get("voided") or sel.get("deferred"):
                        continue

                    # Debug: print raw selection structure once
                    if DEBUG and not _debug_printed_selection:
                        print("\n  === DEBUG: Sample Toast Selection ===")
                        print(f"  displayName: {sel.get('displayName')}")
                        print(f"  quantity: {sel.get('quantity')}")
                        print(f"  price: {sel.get('price')}")
                        ig = sel.get('itemGroup', {})
                        ig_guid = ig.get('guid', '') if isinstance(ig, dict) else ''
                        print(f"  itemGroup: {menu_group_map.get(ig_guid, '?')} ({ig_guid[:12]}...)")
                        sc = sel.get('salesCategory', {})
                        sc_guid = sc.get('guid', '') if isinstance(sc, dict) else ''
                        print(f"  salesCategory: {sales_cat_map.get(sc_guid, '?')} ({sc_guid[:12]}...)")
                        print("  =====================================\n")
                        _debug_printed_selection = True

                    item_name = sel.get("displayName") or "Unknown Item"
                    quantity = sel.get("quantity") or 1
                    price = sel.get("price") or 0

                    # Resolve menu group (granular category)
                    ig = sel.get("itemGroup")
                    if isinstance(ig, dict):
                        ig_guid = ig.get("guid", "")
                        category = menu_group_map.get(ig_guid, "Uncategorized")
                    else:
                        category = "Uncategorized"

                    # Resolve sales category (high-level)
                    sc = sel.get("salesCategory")
                    if isinstance(sc, dict):
                        sc_guid = sc.get("guid", "")
                        sales_cat = sales_cat_map.get(sc_guid, "Other")
                    else:
                        sales_cat = "Other"

                    items.append({
                        "item": item_name,
                        "qty": quantity,
                        "revenue": price,
                        "category": category,
                        "sales_category": sales_cat,
                    })

        if len(orders) < 100:
            break
        page += 1

    return items


def pull_product_mix_period(token, store_num, guid, period_start, period_end, cache_key,
                            menu_group_map, sales_cat_map):
    """Pull product mix for one store for a full period, with per-day caching.
    Returns dict: {date_str: [{item, qty, revenue, category, sales_category}, ...]}
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    data_end = min(yesterday, period_end)

    store_cache_key = f"{cache_key}_pmix_{store_num}"
    store_cache = load_cache(store_cache_key)
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
                day_items = pull_product_mix_day(token, guid, current,
                                                menu_group_map, sales_cat_map)
                daily[date_str] = day_items
                from_api += 1
                time.sleep(0.1)
            except Exception as e:
                print(f"      Error {store_num} {date_str}: {e}")
                daily[date_str] = []
        current += timedelta(days=1)

    # Update cache
    store_cache.update(daily)
    save_cache(store_cache_key, store_cache)

    print(f"    {STORE_NAMES.get(store_num, store_num)}: {from_cache} cached + {from_api} pulled = {from_cache + from_api} days")
    return daily


def aggregate_product_mix(all_store_daily):
    """Aggregate daily item records across all stores into period summary.
    Input: {store_num: {date_str: [{item, qty, revenue, category}, ...]}}
    Returns: {by_item: {...}, by_category: {...}, total_revenue, total_qty}
    """
    by_item = defaultdict(lambda: {"qty": 0, "revenue": 0.0, "days_seen": set(), "category": ""})
    by_category = defaultdict(lambda: {"qty": 0, "revenue": 0.0, "items": set()})
    by_store = defaultdict(lambda: {"qty": 0, "revenue": 0.0})
    total_revenue = 0.0
    total_qty = 0

    for store_num, daily_data in all_store_daily.items():
        for date_str, day_items in daily_data.items():
            for rec in day_items:
                item = rec["item"]
                qty = rec["qty"]
                rev = rec["revenue"]
                cat = rec.get("category", "Uncategorized")

                by_item[item]["qty"] += qty
                by_item[item]["revenue"] += rev
                by_item[item]["days_seen"].add(date_str)
                by_item[item]["category"] = cat

                by_category[cat]["qty"] += qty
                by_category[cat]["revenue"] += rev
                by_category[cat]["items"].add(item)

                by_store[store_num]["qty"] += qty
                by_store[store_num]["revenue"] += rev

                total_revenue += rev
                total_qty += qty

    # Convert sets to counts for JSON serialization
    result_items = {}
    for item, data in by_item.items():
        result_items[item] = {
            "qty": data["qty"],
            "revenue": round(data["revenue"], 2),
            "days_sold": len(data["days_seen"]),
            "avg_price": round(data["revenue"] / data["qty"], 2) if data["qty"] > 0 else 0,
            "category": data["category"],
        }

    result_cats = {}
    for cat, data in by_category.items():
        result_cats[cat] = {
            "qty": data["qty"],
            "revenue": round(data["revenue"], 2),
            "unique_items": len(data["items"]),
        }

    result_stores = {}
    for store_num, data in by_store.items():
        result_stores[store_num] = {
            "qty": data["qty"],
            "revenue": round(data["revenue"], 2),
        }

    return {
        "by_item": result_items,
        "by_category": result_cats,
        "by_store": result_stores,
        "total_revenue": round(total_revenue, 2),
        "total_qty": total_qty,
    }


# ============================================================
# R365 VENDOR PRICING
# ============================================================
def load_r365_reference():
    """Load locations, GL accounts, and items from R365."""
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


def pull_ap_invoices_for_period(period_start, period_end):
    """Pull AP Invoice transaction headers for a period."""
    all_transactions = []
    current = period_start
    while current <= period_end:
        chunk_end = min(current + timedelta(days=30), period_end)
        start_str = current.strftime("%Y-%m-%dT00:00:00Z")
        end_str = chunk_end.strftime("%Y-%m-%dT23:59:59Z")

        url = (f"{R365_BASE}/Transaction?$top=5000"
               f"&$filter=type eq 'AP Invoice'"
               f" and date ge {start_str}"
               f" and date le {end_str}")
        try:
            data = r365_fetch(url)
            records = data.get("value", [])
            all_transactions.extend(records)
        except Exception as e:
            print(f"    Error pulling AP Invoices {current.strftime('%Y-%m-%d')}-{chunk_end.strftime('%Y-%m-%d')}: {e}")

        current = chunk_end + timedelta(days=1)

    return all_transactions


def pull_transaction_details(transaction_ids):
    """Pull TransactionDetail rows for given transaction IDs."""
    all_details = r365_fetch_all(R365_BASE + "/TransactionDetail")
    txn_id_set = set(transaction_ids)
    return [td for td in all_details if td.get("transactionId", "") in txn_id_set]


def extract_vendor_name(txn_name):
    """Extract vendor name from transaction name: 'AP Invoice - VENDOR - INV#'."""
    if not txn_name:
        return "Unknown"
    parts = txn_name.split(" - ")
    if len(parts) >= 2:
        return parts[1].strip()
    return txn_name


def build_vendor_pricing(transactions, details, item_map, gl_map, loc_map):
    """Build vendor+item pricing from AP Invoice detail lines.
    Returns: {vendor: {item: {total_cost, total_qty, unit_cost, uom, gl_category, line_count}}}
    """
    # Build transaction lookup
    txn_lookup = {}
    for txn in transactions:
        txn_lookup[txn.get("transactionId", "")] = txn

    pricing = defaultdict(lambda: defaultdict(lambda: {
        "total_cost": 0.0, "total_qty": 0.0, "uom": "", "gl_category": "",
        "line_count": 0, "stores": set()
    }))

    for td in details:
        txn_id = td.get("transactionId", "")
        txn = txn_lookup.get(txn_id)
        if not txn:
            continue

        row_type = td.get("rowType", "")
        if row_type != "Detail":
            continue

        gl_id = td.get("glAccountId", "")
        gl_info = gl_map.get(gl_id, {})
        gl_num = gl_info.get("number", "")

        # Only COGS GL accounts (5xxx)
        if not gl_num.startswith("5"):
            continue

        quantity = td.get("quantity") or 0
        debit = td.get("debit") or 0

        if quantity <= 0 or debit <= 0:
            continue

        vendor = extract_vendor_name(txn.get("name", ""))
        item_id = td.get("itemId", "")
        item_info = item_map.get(item_id, {})
        item_name = item_info.get("name") or td.get("comment") or "Unknown Item"
        uom = td.get("unitOfMeasureName", "")

        # Determine GL category
        gl_cat = "Other"
        for prefix, cat_name in COGS_GL_PREFIXES.items():
            if gl_num.startswith(prefix):
                gl_cat = cat_name
                break

        loc_id = td.get("locationId") or txn.get("locationId", "")
        loc_info = loc_map.get(loc_id, {})
        store_num = loc_info.get("number", "")

        entry = pricing[vendor][item_name]
        entry["total_cost"] += debit
        entry["total_qty"] += quantity
        entry["uom"] = uom or entry["uom"]
        entry["gl_category"] = gl_cat
        entry["line_count"] += 1
        if store_num:
            entry["stores"].add(store_num)

    # Convert sets and compute unit costs
    result = {}
    for vendor, items in pricing.items():
        result[vendor] = {}
        for item_name, data in items.items():
            result[vendor][item_name] = {
                "total_cost": round(data["total_cost"], 2),
                "total_qty": round(data["total_qty"], 4),
                "unit_cost": round(data["total_cost"] / data["total_qty"], 4) if data["total_qty"] > 0 else 0,
                "uom": data["uom"],
                "gl_category": data["gl_category"],
                "line_count": data["line_count"],
                "stores": sorted(data["stores"]),
            }
    return result


# ============================================================
# COMPARISON AND ANALYSIS
# ============================================================
def compare_product_mix(p1_agg, p2_agg):
    """Compare P1 vs P2 product mix. Returns list of item comparisons sorted by P2 revenue."""
    all_items = set(p1_agg["by_item"].keys()) | set(p2_agg["by_item"].keys())
    p1_total = p1_agg["total_revenue"] or 1
    p2_total = p2_agg["total_revenue"] or 1

    items = []
    for name in all_items:
        p1 = p1_agg["by_item"].get(name, {"qty": 0, "revenue": 0, "days_sold": 0, "avg_price": 0, "category": ""})
        p2 = p2_agg["by_item"].get(name, {"qty": 0, "revenue": 0, "days_sold": 0, "avg_price": 0, "category": ""})

        p1_pct = (p1["revenue"] / p1_total * 100) if p1_total else 0
        p2_pct = (p2["revenue"] / p2_total * 100) if p2_total else 0

        qty_change = ((p2["qty"] - p1["qty"]) / p1["qty"] * 100) if p1["qty"] > 0 else (100 if p2["qty"] > 0 else 0)
        rev_change = ((p2["revenue"] - p1["revenue"]) / p1["revenue"] * 100) if p1["revenue"] > 0 else (100 if p2["revenue"] > 0 else 0)

        items.append({
            "name": name,
            "category": p2.get("category") or p1.get("category", ""),
            "p1_qty": p1["qty"],
            "p1_revenue": p1["revenue"],
            "p1_pct": round(p1_pct, 2),
            "p1_avg_price": p1["avg_price"],
            "p2_qty": p2["qty"],
            "p2_revenue": p2["revenue"],
            "p2_pct": round(p2_pct, 2),
            "p2_avg_price": p2["avg_price"],
            "qty_change_pct": round(qty_change, 1),
            "revenue_change_pct": round(rev_change, 1),
            "mix_shift": round(p2_pct - p1_pct, 2),
            "p1_only": p1["qty"] > 0 and p2["qty"] == 0,
            "p2_only": p2["qty"] > 0 and p1["qty"] == 0,
        })

    items.sort(key=lambda x: x["p2_revenue"], reverse=True)
    return items


def compare_categories(p1_agg, p2_agg):
    """Compare P1 vs P2 by category."""
    all_cats = set(p1_agg["by_category"].keys()) | set(p2_agg["by_category"].keys())
    p1_total = p1_agg["total_revenue"] or 1
    p2_total = p2_agg["total_revenue"] or 1

    cats = []
    for cat in all_cats:
        p1 = p1_agg["by_category"].get(cat, {"qty": 0, "revenue": 0, "unique_items": 0})
        p2 = p2_agg["by_category"].get(cat, {"qty": 0, "revenue": 0, "unique_items": 0})

        rev_change = ((p2["revenue"] - p1["revenue"]) / p1["revenue"] * 100) if p1["revenue"] > 0 else 0

        cats.append({
            "category": cat,
            "p1_qty": p1["qty"],
            "p1_revenue": p1["revenue"],
            "p1_pct": round(p1["revenue"] / p1_total * 100, 2),
            "p2_qty": p2["qty"],
            "p2_revenue": p2["revenue"],
            "p2_pct": round(p2["revenue"] / p2_total * 100, 2),
            "revenue_change_pct": round(rev_change, 1),
        })

    cats.sort(key=lambda x: x["p2_revenue"], reverse=True)
    return cats


def compare_vendor_pricing(p1_pricing, p2_pricing):
    """Compare P1 vs P2 vendor unit costs.
    Returns list of items where cost changed, sorted by absolute cost change.
    """
    items = []
    all_vendors = set(p1_pricing.keys()) | set(p2_pricing.keys())

    for vendor in all_vendors:
        p1_items = p1_pricing.get(vendor, {})
        p2_items = p2_pricing.get(vendor, {})
        all_item_names = set(p1_items.keys()) | set(p2_items.keys())

        for item_name in all_item_names:
            p1 = p1_items.get(item_name)
            p2 = p2_items.get(item_name)

            if p1 and p2:
                cost_change_pct = ((p2["unit_cost"] - p1["unit_cost"]) / p1["unit_cost"] * 100) if p1["unit_cost"] > 0 else 0
                cost_change_abs = p2["unit_cost"] - p1["unit_cost"]
                # Estimate dollar impact: price change * P2 quantity
                dollar_impact = cost_change_abs * p2["total_qty"]
            elif p2 and not p1:
                cost_change_pct = 0
                cost_change_abs = 0
                dollar_impact = 0
            else:
                continue  # Only in P1 — not useful for P2 savings

            items.append({
                "vendor": vendor,
                "item": item_name,
                "p1_unit_cost": p1["unit_cost"] if p1 else None,
                "p2_unit_cost": p2["unit_cost"] if p2 else None,
                "cost_change_pct": round(cost_change_pct, 1),
                "cost_change_abs": round(cost_change_abs, 4),
                "dollar_impact": round(dollar_impact, 2),
                "p1_total": p1["total_cost"] if p1 else 0,
                "p2_total": p2["total_cost"] if p2 else 0,
                "p1_qty": p1["total_qty"] if p1 else 0,
                "p2_qty": p2["total_qty"] if p2 else 0,
                "uom": (p2 or p1)["uom"],
                "gl_category": (p2 or p1)["gl_category"],
            })

    items.sort(key=lambda x: abs(x["dollar_impact"]), reverse=True)

    # Summary stats
    with_change = [i for i in items if i["p1_unit_cost"] and i["p2_unit_cost"]]
    increased = sum(1 for i in with_change if i["cost_change_pct"] > 2)
    decreased = sum(1 for i in with_change if i["cost_change_pct"] < -2)
    flat = len(with_change) - increased - decreased
    total_dollar_impact = sum(i["dollar_impact"] for i in with_change)

    return {
        "items": items,
        "summary": {
            "items_with_data": len(with_change),
            "items_increased": increased,
            "items_decreased": decreased,
            "items_flat": flat,
            "total_dollar_impact": round(total_dollar_impact, 2),
        }
    }


# ============================================================
# HTML GENERATION
# ============================================================
def generate_html(data_json):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forage Kitchen - Product Mix Analysis</title>
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

  .container {{ max-width: 1500px; margin: 0 auto; padding: 20px; }}

  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .kpi-card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .kpi-card .label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; margin-bottom: 8px; }}
  .kpi-card .value {{ font-size: 28px; font-weight: 700; color: #f8fafc; }}
  .kpi-card .sub {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
  .kpi-card .change {{ font-size: 14px; font-weight: 600; margin-top: 4px; }}
  .positive {{ color: #22c55e; }}
  .negative {{ color: #ef4444; }}
  .neutral {{ color: #94a3b8; }}

  .section-header {{ font-size: 18px; font-weight: 600; color: #f8fafc; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #334155; }}

  .tab-bar {{ display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }}
  .tab-btn {{ padding: 8px 16px; background: #1e293b; border: 1px solid #334155; border-radius: 8px; color: #94a3b8; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.2s; }}
  .tab-btn:hover {{ background: #253352; color: #f8fafc; }}
  .tab-btn.active {{ background: #3b82f6; color: #fff; border-color: #3b82f6; font-weight: 700; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  .store-table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
  .store-table th {{ background: #334155; padding: 12px 16px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; font-weight: 600; cursor: pointer; user-select: none; white-space: nowrap; }}
  .store-table th:hover {{ color: #f8fafc; }}
  .store-table th.right, .store-table td.right {{ text-align: right; }}
  .store-table td {{ padding: 10px 16px; border-bottom: 1px solid #1e293b; font-size: 13px; }}
  .store-table tr:nth-child(even) {{ background: #1e293b; }}
  .store-table tr:nth-child(odd) {{ background: #172033; }}
  .store-table tr:hover {{ background: #253352; }}
  .store-table tr.total-row {{ background: #334155 !important; font-weight: 700; }}

  .charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .chart-card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .chart-card h3 {{ font-size: 14px; color: #94a3b8; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}

  .caveat {{ background: #1e293b; border: 1px solid #f59e0b44; border-radius: 10px; padding: 16px; margin: 16px 0; font-size: 13px; color: #f59e0b; }}
  .caveat strong {{ color: #fbbf24; }}

  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .badge-new {{ background: #3b82f622; color: #3b82f6; border: 1px solid #3b82f644; }}
  .badge-dropped {{ background: #ef444422; color: #ef4444; border: 1px solid #ef444444; }}

  .refresh-notice {{ text-align: center; padding: 12px; color: #64748b; font-size: 12px; margin-top: 20px; }}
  .refresh-notice code {{ background: #334155; padding: 2px 8px; border-radius: 4px; color: #94a3b8; }}

  .search-box {{ padding: 8px 14px; background: #334155; border: 1px solid #475569; border-radius: 8px; color: #f8fafc; font-size: 13px; width: 300px; margin-bottom: 12px; }}
  .search-box::placeholder {{ color: #64748b; }}

  @media (max-width: 768px) {{
    .charts-row {{ grid-template-columns: 1fr; }}
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
    .header {{ flex-direction: column; gap: 10px; }}
    .header .meta {{ text-align: left; }}
    .search-box {{ width: 100%; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Forage <span>Kitchen</span> &mdash; Product Mix Analysis</h1>
  <div class="meta">
    <div class="period" id="periodLabel"></div>
    <div id="dateRange"></div>
    <div id="lastUpdated"></div>
    <div class="source">Data: Toast POS (Product Mix) + R365 (Vendor Pricing)</div>
  </div>
</div>

<div class="container">
  <div class="kpi-row" id="kpiRow"></div>

  <div class="section-header">Product Mix Comparison</div>
  <div class="tab-bar" id="mixTabBar"></div>
  <div id="mixTabContents"></div>

  <div class="section-header">Category Breakdown</div>
  <div class="charts-row">
    <div class="chart-card">
      <h3>Revenue by Category: P1 vs P2</h3>
      <canvas id="categoryChart" height="250"></canvas>
    </div>
    <div class="chart-card">
      <h3>Mix Shift by Category (% of Revenue)</h3>
      <canvas id="mixShiftChart" height="250"></canvas>
    </div>
  </div>
  <table class="store-table" id="categoryTable"></table>

  <div class="section-header">Vendor Pricing Changes (R365 Data)</div>
  <div class="caveat" id="r365Caveat"></div>
  <table class="store-table" id="vendorTable"></table>

  <div class="section-header">Pricing Impact Summary</div>
  <div class="kpi-row" id="pricingKpiRow"></div>

  <div class="refresh-notice">
    Run <code>py product_mix_analysis.py</code> to regenerate &bull;
    Run <code>py product_mix_analysis.py --debug</code> for diagnostic output &bull;
    Generated <span id="refreshTime"></span>
  </div>
</div>

<script>
const D = {data_json};

const fmt = (n) => n == null ? '\\u2014' : '$' + Number(n).toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
const fmtDec = (n, d) => n == null ? '\\u2014' : '$' + Number(n).toLocaleString('en-US', {{minimumFractionDigits:d||2, maximumFractionDigits:d||2}});
const fmtPct = (n) => n == null ? '\\u2014' : n.toFixed(1) + '%';
const fmtNum = (n) => n == null ? '\\u2014' : Number(n).toLocaleString('en-US');
const fmtChange = (n) => {{
  if (n == null) return '<span class="neutral">N/A</span>';
  const cls = n >= 0 ? 'positive' : 'negative';
  const sign = n >= 0 ? '+' : '';
  return `<span class="${{cls}}">${{sign}}${{n.toFixed(1)}}%</span>`;
}};

// Header
document.getElementById('periodLabel').textContent = `P${{D.p1.period}} vs P${{D.p2.period}} \u2014 FY${{D.fiscal_year}}`;
document.getElementById('dateRange').textContent = `P${{D.p1.period}}: ${{D.p1.start}} to ${{D.p1.end}} | P${{D.p2.period}}: ${{D.p2.start}} to ${{D.p2.end}}`;
document.getElementById('lastUpdated').textContent = `Updated: ${{new Date(D.generated).toLocaleString()}}`;
document.getElementById('refreshTime').textContent = new Date(D.generated).toLocaleString();

// KPI Cards
const kpiRow = document.getElementById('kpiRow');
const pm = D.product_mix;
const revChange = pm.p1_total_revenue > 0 ? ((pm.p2_total_revenue - pm.p1_total_revenue) / pm.p1_total_revenue * 100) : 0;
const qtyChange = pm.p1_total_qty > 0 ? ((pm.p2_total_qty - pm.p1_total_qty) / pm.p1_total_qty * 100) : 0;

const kpis = [
  {{ label: 'P' + D.p1.period + ' Revenue', value: fmt(pm.p1_total_revenue), sub: fmtNum(pm.p1_total_qty) + ' items sold' }},
  {{ label: 'P' + D.p2.period + ' Revenue', value: fmt(pm.p2_total_revenue), sub: fmtNum(pm.p2_total_qty) + ' items sold' }},
  {{ label: 'Revenue Change', value: fmtChange(revChange), sub: fmt(pm.p2_total_revenue - pm.p1_total_revenue) + ' difference' }},
  {{ label: 'Volume Change', value: fmtChange(qtyChange), sub: fmtNum(pm.p2_total_qty - pm.p1_total_qty) + ' units' }},
  {{ label: 'Unique Items (P' + D.p1.period + ')', value: pm.p1_unique_items, sub: '' }},
  {{ label: 'Unique Items (P' + D.p2.period + ')', value: pm.p2_unique_items, sub: '' }},
];

kpis.forEach(k => {{
  const card = document.createElement('div');
  card.className = 'kpi-card';
  card.innerHTML = `<div class="label">${{k.label}}</div><div class="value">${{k.value}}</div><div class="sub">${{k.sub}}</div>`;
  kpiRow.appendChild(card);
}});

// Product Mix Tabs: Top Items, New/Dropped
const mixItems = pm.items || [];
const tabBar = document.getElementById('mixTabBar');
const tabContents = document.getElementById('mixTabContents');

const tabs = [
  {{ id: 'top', label: 'Top Items', items: mixItems.filter(i => !i.p1_only && !i.p2_only).slice(0, 50) }},
  {{ id: 'new', label: 'New in P' + D.p2.period, items: mixItems.filter(i => i.p2_only).slice(0, 30) }},
  {{ id: 'dropped', label: 'Dropped from P' + D.p1.period, items: mixItems.filter(i => i.p1_only).slice(0, 30) }},
  {{ id: 'all', label: 'All Items', items: mixItems }},
];

tabs.forEach((tab, idx) => {{
  const btn = document.createElement('div');
  btn.className = 'tab-btn' + (idx === 0 ? ' active' : '');
  btn.textContent = tab.label + ` (${{tab.items.length}})`;
  btn.onclick = () => {{
    document.querySelectorAll('#mixTabBar .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('#mixTabContents .tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('mixTab_' + tab.id).classList.add('active');
  }};
  tabBar.appendChild(btn);

  const content = document.createElement('div');
  content.id = 'mixTab_' + tab.id;
  content.className = 'tab-content' + (idx === 0 ? ' active' : '');

  // Search box for the tab
  const search = document.createElement('input');
  search.className = 'search-box';
  search.placeholder = 'Search items...';
  search.oninput = () => {{
    const q = search.value.toLowerCase();
    content.querySelectorAll('tbody tr').forEach(row => {{
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    }});
  }};
  content.appendChild(search);

  const table = document.createElement('table');
  table.className = 'store-table';

  let sortCol = -1, sortAsc = true;
  const cols = tab.id === 'dropped'
    ? ['Item', 'Category', 'P' + D.p1.period + ' Qty', 'P' + D.p1.period + ' Rev', 'P' + D.p1.period + ' % Rev', 'Avg Price']
    : ['Item', 'Category',
       'P' + D.p1.period + ' Qty', 'P' + D.p1.period + ' Rev', 'P' + D.p1.period + ' %',
       'P' + D.p2.period + ' Qty', 'P' + D.p2.period + ' Rev', 'P' + D.p2.period + ' %',
       'Qty \\u0394%', 'Mix Shift'];
  const rightCols = new Set(tab.id === 'dropped' ? [2,3,4,5] : [2,3,4,5,6,7,8,9]);

  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  cols.forEach((col, ci) => {{
    const th = document.createElement('th');
    th.textContent = col;
    if (rightCols.has(ci)) th.className = 'right';
    th.onclick = () => {{
      if (sortCol === ci) sortAsc = !sortAsc; else {{ sortCol = ci; sortAsc = ci < 2; }}
      sortTable(table, ci, sortAsc, rightCols.has(ci));
    }};
    headerRow.appendChild(th);
  }});
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  tab.items.forEach(item => {{
    const tr = document.createElement('tr');
    let cells;
    if (tab.id === 'dropped') {{
      cells = [
        item.name,
        item.category,
        fmtNum(item.p1_qty),
        fmt(item.p1_revenue),
        fmtPct(item.p1_pct),
        fmtDec(item.p1_avg_price),
      ];
    }} else {{
      cells = [
        item.name + (item.p2_only ? ' <span class="badge badge-new">NEW</span>' : ''),
        item.category,
        fmtNum(item.p1_qty),
        fmt(item.p1_revenue),
        fmtPct(item.p1_pct),
        fmtNum(item.p2_qty),
        fmt(item.p2_revenue),
        fmtPct(item.p2_pct),
        fmtChange(item.qty_change_pct),
        (item.mix_shift >= 0 ? '+' : '') + item.mix_shift.toFixed(2) + ' pp',
      ];
    }}
    cells.forEach((val, ci) => {{
      const td = document.createElement('td');
      td.innerHTML = val;
      if (rightCols.has(ci)) td.className = 'right';
      tr.appendChild(td);
    }});
    tbody.appendChild(tr);
  }});
  table.appendChild(tbody);
  content.appendChild(table);
  tabContents.appendChild(content);
}});

function sortTable(table, colIdx, asc, isNumeric) {{
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {{
    let av = a.children[colIdx]?.textContent?.replace(/[$,%,+,pp,\\u2014,\\s]/g, '') || '';
    let bv = b.children[colIdx]?.textContent?.replace(/[$,%,+,pp,\\u2014,\\s]/g, '') || '';
    if (isNumeric) {{
      av = parseFloat(av) || 0;
      bv = parseFloat(bv) || 0;
      return asc ? av - bv : bv - av;
    }}
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

// Category Table
const catTable = document.getElementById('categoryTable');
const cats = D.categories || [];
if (cats.length) {{
  let html = '<thead><tr><th>Category</th><th class="right">P' + D.p1.period + ' Rev</th><th class="right">P' + D.p1.period + ' %</th><th class="right">P' + D.p2.period + ' Rev</th><th class="right">P' + D.p2.period + ' %</th><th class="right">Rev \\u0394%</th></tr></thead><tbody>';
  cats.forEach(c => {{
    html += `<tr><td>${{c.category}}</td><td class="right">${{fmt(c.p1_revenue)}}</td><td class="right">${{fmtPct(c.p1_pct)}}</td><td class="right">${{fmt(c.p2_revenue)}}</td><td class="right">${{fmtPct(c.p2_pct)}}</td><td class="right">${{fmtChange(c.revenue_change_pct)}}</td></tr>`;
  }});
  html += '</tbody>';
  catTable.innerHTML = html;
}}

// Category Charts
const catLabels = cats.map(c => c.category);
const catP1 = cats.map(c => c.p1_revenue);
const catP2 = cats.map(c => c.p2_revenue);

if (catLabels.length) {{
  new Chart(document.getElementById('categoryChart'), {{
    type: 'bar',
    data: {{
      labels: catLabels,
      datasets: [
        {{ label: 'P' + D.p1.period, data: catP1, backgroundColor: '#64748b' }},
        {{ label: 'P' + D.p2.period, data: catP2, backgroundColor: '#3b82f6' }},
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
        y: {{ ticks: {{ color: '#94a3b8', callback: v => '$' + (v/1000).toFixed(0) + 'k' }}, grid: {{ color: '#334155' }} }}
      }}
    }}
  }});

  const mixP1 = cats.map(c => c.p1_pct);
  const mixP2 = cats.map(c => c.p2_pct);
  new Chart(document.getElementById('mixShiftChart'), {{
    type: 'bar',
    data: {{
      labels: catLabels,
      datasets: [
        {{ label: 'P' + D.p1.period + ' Mix %', data: mixP1, backgroundColor: '#64748b' }},
        {{ label: 'P' + D.p2.period + ' Mix %', data: mixP2, backgroundColor: '#3b82f6' }},
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
        y: {{ ticks: {{ color: '#94a3b8', callback: v => v.toFixed(0) + '%' }}, grid: {{ color: '#334155' }} }}
      }}
    }}
  }});
}}

// Vendor Pricing Table
const vp = D.vendor_pricing || {{}};
const vpItems = (vp.items || []).filter(i => i.p1_unit_cost && i.p2_unit_cost);
const vpSummary = vp.summary || {{}};

document.getElementById('r365Caveat').innerHTML = `<strong>Note:</strong> ${{D.r365_coverage_note}}. The pricing data below is directional — it shows trends for visible vendors only.`;

const vendorTable = document.getElementById('vendorTable');
if (vpItems.length) {{
  let html = '<thead><tr><th>Vendor</th><th>Item</th><th>Category</th><th class="right">P' + D.p1.period + ' Unit Cost</th><th class="right">P' + D.p2.period + ' Unit Cost</th><th class="right">\\u0394%</th><th>UOM</th><th class="right">$ Impact</th></tr></thead><tbody>';
  vpItems.slice(0, 50).forEach(item => {{
    const changeCls = item.cost_change_pct > 2 ? 'negative' : item.cost_change_pct < -2 ? 'positive' : 'neutral';
    const impactCls = item.dollar_impact > 0 ? 'negative' : item.dollar_impact < 0 ? 'positive' : 'neutral';
    html += `<tr>
      <td>${{item.vendor}}</td><td>${{item.item}}</td><td>${{item.gl_category}}</td>
      <td class="right">${{fmtDec(item.p1_unit_cost, 4)}}</td>
      <td class="right">${{fmtDec(item.p2_unit_cost, 4)}}</td>
      <td class="right"><span class="${{changeCls}}">${{item.cost_change_pct > 0 ? '+' : ''}}${{item.cost_change_pct.toFixed(1)}}%</span></td>
      <td>${{item.uom}}</td>
      <td class="right"><span class="${{impactCls}}">${{item.dollar_impact > 0 ? '+' : ''}}${{fmtDec(item.dollar_impact)}}</span></td>
    </tr>`;
  }});
  html += '</tbody>';
  vendorTable.innerHTML = html;
}}

// Pricing KPI
const pkRow = document.getElementById('pricingKpiRow');
const pkCards = [
  {{ label: 'R365 Items Tracked', value: vpSummary.items_with_data || 0, sub: 'Items with P1 + P2 data' }},
  {{ label: 'Price Increases (>2%)', value: vpSummary.items_increased || 0, sub: 'Items costing more' }},
  {{ label: 'Price Decreases (>2%)', value: vpSummary.items_decreased || 0, sub: 'Items costing less' }},
  {{ label: 'Net Pricing Impact', value: fmtDec(vpSummary.total_dollar_impact), sub: 'R365-visible vendors only (~23% of total)' }},
];
pkCards.forEach(k => {{
  const card = document.createElement('div');
  card.className = 'kpi-card';
  card.innerHTML = `<div class="label">${{k.label}}</div><div class="value">${{k.value}}</div><div class="sub">${{k.sub}}</div>`;
  pkRow.appendChild(card);
}});

</script>
</body>
</html>'''


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("  Forage Kitchen - Product Mix Analysis")
    print("  P1 vs P2 FY2026")
    print("=" * 60)

    fy = 2026
    p1_num = 1
    p2_num = 2

    p1_start, p1_end = get_period_dates(fy, p1_num)
    p2_start, p2_end = get_period_dates(fy, p2_num)

    print(f"\n  P{p1_num}: {p1_start.strftime('%Y-%m-%d')} to {p1_end.strftime('%Y-%m-%d')}")
    print(f"  P{p2_num}: {p2_start.strftime('%Y-%m-%d')} to {p2_end.strftime('%Y-%m-%d')}")
    if DEBUG:
        print("  ** DEBUG MODE: will print sample Toast selection data **")

    # ---- Toast Product Mix ----
    print(f"\n{'=' * 60}")
    print("  TOAST: Pulling product mix data...")
    print(f"{'=' * 60}")

    token = toast_authenticate()
    print("  Authenticated with Toast")

    # Pull menu lookups (use first store — categories are shared across locations)
    print("  Loading menu group + sales category lookups...")
    first_guid = TOAST_RESTAURANTS[sorted(TOAST_RESTAURANTS.keys())[0]]["guid"]
    # pull_toast_lookups returns (sales_cat_map, menu_group_map)
    sales_cat_map, menu_group_map = pull_toast_lookups(token, first_guid)
    print(f"    {len(sales_cat_map)} sales categories, {len(menu_group_map)} menu groups\n")

    # Pull P1
    print(f"  --- P{p1_num} Product Mix ---")
    p1_all_stores = {}
    for store_num in sorted(TOAST_RESTAURANTS.keys()):
        guid = TOAST_RESTAURANTS[store_num]["guid"]
        cache_key = f"FY{fy}_P{p1_num}"
        p1_all_stores[store_num] = pull_product_mix_period(
            token, store_num, guid, p1_start, p1_end, cache_key,
            menu_group_map, sales_cat_map)

    # Pull P2
    print(f"\n  --- P{p2_num} Product Mix ---")
    p2_all_stores = {}
    for store_num in sorted(TOAST_RESTAURANTS.keys()):
        guid = TOAST_RESTAURANTS[store_num]["guid"]
        cache_key = f"FY{fy}_P{p2_num}"
        p2_all_stores[store_num] = pull_product_mix_period(
            token, store_num, guid, p2_start, p2_end, cache_key,
            menu_group_map, sales_cat_map)

    # Aggregate
    print("\n  Aggregating product mix...")
    p1_agg = aggregate_product_mix(p1_all_stores)
    p2_agg = aggregate_product_mix(p2_all_stores)
    print(f"    P{p1_num}: {p1_agg['total_qty']:,} items, {len(p1_agg['by_item'])} unique, ${p1_agg['total_revenue']:,.0f} revenue")
    print(f"    P{p2_num}: {p2_agg['total_qty']:,} items, {len(p2_agg['by_item'])} unique, ${p2_agg['total_revenue']:,.0f} revenue")

    # Compare
    mix_comparison = compare_product_mix(p1_agg, p2_agg)
    cat_comparison = compare_categories(p1_agg, p2_agg)

    new_items = [i for i in mix_comparison if i["p2_only"]]
    dropped_items = [i for i in mix_comparison if i["p1_only"]]
    print(f"    New in P{p2_num}: {len(new_items)} items")
    print(f"    Dropped from P{p1_num}: {len(dropped_items)} items")

    # ---- R365 Vendor Pricing ----
    print(f"\n{'=' * 60}")
    print("  R365: Pulling vendor pricing data...")
    print(f"{'=' * 60}")

    try:
        loc_map, gl_map, item_map = load_r365_reference()

        print(f"\n  --- P{p1_num} AP Invoices ---")
        p1_invoices = pull_ap_invoices_for_period(p1_start, p1_end)
        print(f"    {len(p1_invoices)} AP Invoice transactions")

        print(f"\n  --- P{p2_num} AP Invoices ---")
        p2_invoices = pull_ap_invoices_for_period(p2_start, p2_end)
        print(f"    {len(p2_invoices)} AP Invoice transactions")

        # Pull all transaction details (one bulk pull for both periods)
        all_txn_ids = [t.get("transactionId", "") for t in p1_invoices + p2_invoices]
        print(f"\n  Pulling transaction details for {len(all_txn_ids)} transactions...")
        all_details = pull_transaction_details(all_txn_ids)
        print(f"    {len(all_details)} detail rows matched")

        # Split details by period
        p1_txn_ids = set(t.get("transactionId", "") for t in p1_invoices)
        p2_txn_ids = set(t.get("transactionId", "") for t in p2_invoices)
        p1_details = [d for d in all_details if d.get("transactionId", "") in p1_txn_ids]
        p2_details = [d for d in all_details if d.get("transactionId", "") in p2_txn_ids]

        print(f"\n  Building vendor pricing...")
        p1_vendor_pricing = build_vendor_pricing(p1_invoices, p1_details, item_map, gl_map, loc_map)
        p2_vendor_pricing = build_vendor_pricing(p2_invoices, p2_details, item_map, gl_map, loc_map)
        print(f"    P{p1_num}: {len(p1_vendor_pricing)} vendors")
        print(f"    P{p2_num}: {len(p2_vendor_pricing)} vendors")

        vendor_comparison = compare_vendor_pricing(p1_vendor_pricing, p2_vendor_pricing)
        vs = vendor_comparison["summary"]
        print(f"    Pricing changes: {vs['items_increased']} up, {vs['items_decreased']} down, {vs['items_flat']} flat")
        print(f"    Net pricing impact (R365-visible): ${vs['total_dollar_impact']:,.2f}")

    except Exception as e:
        print(f"\n  R365 ERROR: {e}")
        print("  Vendor pricing section will be empty.")
        vendor_comparison = {"items": [], "summary": {
            "items_with_data": 0, "items_increased": 0, "items_decreased": 0,
            "items_flat": 0, "total_dollar_impact": 0
        }}

    # ---- Build Dashboard ----
    print(f"\n{'=' * 60}")
    print("  Generating HTML dashboard...")
    print(f"{'=' * 60}")

    dashboard_data = {
        "generated": datetime.now().isoformat(),
        "fiscal_year": fy,
        "p1": {
            "period": p1_num,
            "start": p1_start.strftime("%Y-%m-%d"),
            "end": p1_end.strftime("%Y-%m-%d"),
        },
        "p2": {
            "period": p2_num,
            "start": p2_start.strftime("%Y-%m-%d"),
            "end": p2_end.strftime("%Y-%m-%d"),
        },
        "product_mix": {
            "items": mix_comparison,
            "p1_total_revenue": p1_agg["total_revenue"],
            "p2_total_revenue": p2_agg["total_revenue"],
            "p1_total_qty": p1_agg["total_qty"],
            "p2_total_qty": p2_agg["total_qty"],
            "p1_unique_items": len(p1_agg["by_item"]),
            "p2_unique_items": len(p2_agg["by_item"]),
        },
        "categories": cat_comparison,
        "vendor_pricing": vendor_comparison,
        "stores": sorted(TOAST_RESTAURANTS.keys()),
        "store_names": STORE_NAMES,
        "r365_coverage_note": "R365 OData covers ~23% of COGS vendors (EDI vendors like US Foods, Sysco are not visible)",
    }

    data_json = json.dumps(dashboard_data)
    html = generate_html(data_json)

    outpath = os.path.join(OUTDIR, "product_mix_analysis.html")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(html)

    period_outpath = os.path.join(OUTDIR, f"product_mix_P{p1_num}vP{p2_num}_FY{fy}.html")
    with open(period_outpath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  Dashboard saved to:")
    print(f"    {outpath}")
    print(f"    {period_outpath}")
    print(f"\n{'=' * 60}")

    # Print top movers summary
    print(f"\n  TOP 10 ITEMS BY P{p2_num} REVENUE:")
    print(f"  {'Item':<35} {'P1 Qty':>8} {'P2 Qty':>8} {'P1 Rev':>10} {'P2 Rev':>10} {'Qty Chg':>8}")
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")
    for item in mix_comparison[:10]:
        print(f"  {item['name'][:35]:<35} {item['p1_qty']:>8,} {item['p2_qty']:>8,} "
              f"${item['p1_revenue']:>9,.0f} ${item['p2_revenue']:>9,.0f} "
              f"{item['qty_change_pct']:>+7.1f}%")

    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
