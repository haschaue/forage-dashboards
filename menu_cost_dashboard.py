"""
Forage Kitchen - Menu Cost Dashboard (Menu Engineering)
Joins Toast PMIX data with R365 recipe costs for quadrant analysis.

Usage: python menu_cost_dashboard.py [period] [--recipe-csv PATH]
  period: P9 (default: most recent completed period)
  --recipe-csv: path to R365 recipe export CSV (default: latest in Downloads)

Data flow:
  - Product mix (items sold, quantities, revenue) from cached Toast data
  - Recipe costs (per-portion ingredient cost) from R365 CSV export
  - Output: menu_cost_dashboard.html
"""
import csv
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta
from collections import Counter, defaultdict

# ============================================================
# CONFIG
# ============================================================
OUTDIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(OUTDIR, "cache")

sys.path.insert(0, OUTDIR)
from r365_config import SSS_CONFIG, FISCAL_YEAR_STARTS
from toast_config import (TOAST_CLIENT_ID, TOAST_CLIENT_SECRET,
                          TOAST_AUTH_URL, TOAST_API_BASE, TOAST_RESTAURANTS)

SSL_CTX = ssl.create_default_context()

STORE_NAMES = {k: v["name"] for k, v in SSS_CONFIG.items()}
STORE_NUMBERS = sorted(STORE_NAMES.keys())

# Toast categories to INCLUDE as menu items
FOOD_CATEGORIES = {
    "Grain Bowls", "Greens & Grains", "Wraps", "Salads", "Grains",
    "Make Your Own", "Make Your Own In Store",
    "Value Menu", "Kids Menu (12 and Under)",
    "Featured",
    "À La Carte Sides",  # À La Carte Sides
}

# Exclude these sales_category values
EXCLUDED_SALES_CATEGORIES = {"NA Beverage", "Catering"}

# ============================================================
# HARDCODED TOAST → R365 NAME MAPPINGS
# ============================================================
TOAST_TO_R365 = {
    "Power Bowl": "BOWL- POWER BOWL",
    "Avocado Crunch": "BOWL- AVOCADO CRUNCH",
    "Thai Bowl": "BOWL- THAI BOWL",
    "Fiesta Bowl": "BOWL- FIESTA BOWL",
    "Chicken Bacon Caesar Wrap": "WRAP- CHICKEN BACON CAESAR 12.25",
    "Santa Fe Wrap": "WRAP- SANTA FE WRAP",
    "Make Your Own": "BOWL-MAKE YOUR OWN 10.2025",
    "Make Your Own In Store": "BOWL-MAKE YOUR OWN 10.2025",
    "Tuna Poke Bowl": "BOWL POKE",
    "Chicken Caesar": "BOWL- CHICKEN CAESAR",
    "Asian BBQ Bowl": "BOWLS- ASIAN BBQ BOWL",
    "Cultured Cobb": "BOWL- CULTURED COBB",
    "Cashew Bowl": "BOWL- CASHEW",
    "Club Med Bowl": "BOWL- CLUB MED SPRING 26",
    "Southwest Ranch": "BOWL- SOUTHWEST RANCH",
    "Local Roots": "BOWL- LOCAL ROOTS 2026",
    "Chicken Chopped Salad": "BOWL- CHOPPED SALAD 2026",
    "Mediterranean Wrap": "WRAP- MED WRAP SPRING 26",
    "Small Power Bowl": "BOWL- VALUE POWER BOWL",
    "Kids MYO": "BOWL- KIDS MAKE YOUR OWN",
    "Small Thai Bowl": "BOWL- VALUE THAI BOWL",
    "Small Cultured Cobb": "BOWL- VALUE CULTURED COBB",
    "Kids Power Bowl": "BOWL KIDS POWER BOWL",
    "Mole Bowl": "BOWL MOLE 2026",
    "Berry Good Salad": "BOWLS- BERRY GOOD SALAD",
    "Curry Plate": "BOWLS- CURRY PLATE",
    "Golden Greek Protein Plate": "BOWLS- GOLDEN GREEK PROTEIN PLATE",
    "Asian BBQ Protein Plate": "BOWLS- ASIAN BBQ PROTEIN PLATE",
    "Batatas": "BOWL- BATATAS RANCHEROS",
    "Batatas Rancheros": "BOWL- BATATAS RANCHEROS",
    "Poke Wrap": "WRAPS- POKE WRAP 2026",
    # Duplicate Toast names with trailing dots
    "Power Bowl..": "BOWL- POWER BOWL",
    "Fiesta Bowl..": "BOWL- FIESTA BOWL",
}

# Default protein add-ons: items where the base recipe doesn't include
# the protein because customers can swap it. The theoretical food cost
# = base recipe AvgCost + default protein AvgCost.
DEFAULT_PROTEIN = {
    "Avocado Crunch": "ADD ON- SMOKED SALMON",
    "Tuna Poke Bowl": "ADD ON- TUNA POKE",
    "Chicken Caesar": "ADD ON- ROASTED PULLED CHICKEN",
    "Chicken Bacon Caesar Wrap": "ADD ON- ROASTED PULLED CHICKEN",
    "Santa Fe Wrap": "ADD ON- DICED CHICKEN THIGH",
    "Southwest Ranch": "ADD ON- DICED CHICKEN THIGH",
    "Chicken Chopped Salad": "ADD ON- DICED CHICKEN THIGH",
}

# Protein add-ons tracked separately for pricing analysis
# {display_name: {r365: R365 recipe name, sell_price: menu board upcharge}}
PROTEIN_ITEMS = {
    "Roasted Pulled Chicken": {"r365": "ADD ON- ROASTED PULLED CHICKEN", "sell_price": 3.50},
    "Diced Chicken Thigh":    {"r365": "ADD ON- DICED CHICKEN THIGH",    "sell_price": 3.50},
    "Tuna Poke":              {"r365": "ADD ON- TUNA POKE",              "sell_price": 3.50},
    "Smoked Salmon":          {"r365": "ADD ON- SMOKED SALMON",          "sell_price": 7.00},
    "Meatballs":              {"r365": "ADD ON - MEATBALLS (2)",         "sell_price": 3.50},
    "Tofu":                   {"r365": "ADD ON- TOFU",                   "sell_price": 3.50},
}


# ============================================================
# PULL MENU BOARD PRICES FROM TOAST ORDERS
# ============================================================
def pull_menu_prices(period_end):
    """Pull base menu prices from Toast orders.
    Uses a sample of recent orders to determine each item's menu board price
    by computing: base_price = selection.price - sum(modifier.prices)
    and taking the mode (most common non-zero value).
    """
    cache_file = os.path.join(CACHE_DIR, "menu_prices.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            cached = json.load(f)
        cached_date = datetime.strptime(cached["pulled_date"], "%Y-%m-%d")
        if (datetime.now() - cached_date).days < 14:
            print(f"  Using cached menu prices (pulled {cached['pulled_date']})")
            return cached["prices"]

    print("  Pulling menu prices from Toast orders...")
    auth_data = json.dumps({
        "clientId": TOAST_CLIENT_ID,
        "clientSecret": TOAST_CLIENT_SECRET,
        "userAccessType": "TOAST_MACHINE_CLIENT"
    }).encode()
    req = urllib.request.Request(TOAST_AUTH_URL, data=auth_data,
                                headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, context=SSL_CTX) as resp:
        token = json.loads(resp.read())["token"]["accessToken"]

    biz_date = period_end.strftime("%Y%m%d")
    all_prices = {}

    for store_num in TOAST_RESTAURANTS.keys():
        guid = TOAST_RESTAURANTS[store_num]["guid"]
        headers = {"Authorization": f"Bearer {token}",
                   "Toast-Restaurant-External-ID": guid}
        url = f"{TOAST_API_BASE}/orders/v2/orders?businessDate={biz_date}&pageSize=100"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=60) as resp:
                order_guids = json.loads(resp.read())
        except Exception:
            continue

        for og in order_guids[:25]:
            url2 = f"{TOAST_API_BASE}/orders/v2/orders/{og}"
            req2 = urllib.request.Request(url2, headers=headers)
            try:
                with urllib.request.urlopen(req2, context=SSL_CTX, timeout=15) as resp2:
                    order = json.loads(resp2.read())
            except Exception:
                continue

            for check in order.get("checks", []):
                for sel in check.get("selections", []):
                    name = sel.get("displayName", "")
                    total_price = sel.get("price", 0)
                    mods = sel.get("modifiers", [])
                    mod_total = sum(m.get("price", 0) for m in mods)
                    base_price = round(total_price - mod_total, 2)
                    if base_price > 0 and name:
                        if name not in all_prices:
                            all_prices[name] = Counter()
                        all_prices[name][base_price] += 1

    prices = {}
    for name, counter in all_prices.items():
        mode_price, count = counter.most_common(1)[0]
        total = sum(counter.values())
        if count >= max(2, total * 0.3):
            prices[name] = mode_price

    with open(cache_file, "w") as f:
        json.dump({"pulled_date": datetime.now().strftime("%Y-%m-%d"),
                   "prices": prices}, f, indent=2)

    print(f"  Found menu prices for {len(prices)} items")
    return prices


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


def get_current_or_recent_period():
    """Return (fy, period) for the most recently completed period, or current if none."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    last_completed = None
    current = None
    for fy_year in sorted(FISCAL_YEAR_STARTS.keys()):
        for p in get_445_periods(FISCAL_YEAR_STARTS[fy_year]):
            if p["end"] < today:
                last_completed = (fy_year, p["period"])
            elif p["start"] <= today <= p["end"]:
                current = (fy_year, p["period"])
    # Prefer the most recently completed period (need closed data for cost analysis)
    # Fall back to current if no completed periods exist
    return last_completed if last_completed else current


def resolve_period_arg(arg):
    """Parse 'P9' or 'P9 FY2026' style args. Returns (fy, period)."""
    arg = arg.strip().upper()
    m = re.match(r'P(\d+)(?:\s+FY(\d+))?', arg)
    if not m:
        print(f"  Error: Can't parse period '{arg}'. Use P9 or P9 FY2026.")
        sys.exit(1)
    period = int(m.group(1))
    if m.group(2):
        fy = int(m.group(2))
    else:
        # Assume current FY
        today = datetime.now()
        fy = max(FISCAL_YEAR_STARTS.keys())
    return fy, period


# ============================================================
# LOAD PMIX CACHE DATA
# ============================================================
def load_pmix_data(fy, period):
    """Load cached PMIX data for all stores for a given period.
    Returns {store_num: [{item, qty, revenue, category, sales_category}, ...]}
    aggregated across all days.
    """
    cache_key_prefix = f"FY{fy}_P{period}_pmix_"
    all_store_data = {}

    for sn in STORE_NUMBERS:
        cache_file = os.path.join(CACHE_DIR, f"{cache_key_prefix}{sn}.json")
        if not os.path.exists(cache_file):
            print(f"  Warning: No PMIX cache for store {sn} ({STORE_NAMES.get(sn, sn)})")
            continue

        with open(cache_file, "r") as f:
            daily_data = json.load(f)

        # Aggregate across days
        items = defaultdict(lambda: {"qty": 0, "revenue": 0, "category": "", "sales_category": ""})
        for date_str, day_items in daily_data.items():
            for it in day_items:
                name = it["item"]
                items[name]["qty"] += it.get("qty", 0)
                items[name]["revenue"] += it.get("revenue", 0)
                items[name]["category"] = it.get("category", "")
                items[name]["sales_category"] = it.get("sales_category", "")

        store_items = []
        for name, data in items.items():
            if data["qty"] > 0 and data["revenue"] > 0:
                store_items.append({
                    "item": name,
                    "qty": data["qty"],
                    "revenue": data["revenue"],
                    "category": data["category"],
                    "sales_category": data["sales_category"],
                })
        all_store_data[sn] = store_items

    return all_store_data


def filter_menu_items(store_data):
    """Filter to only actual food menu items based on category/sales_category."""
    filtered = {}
    for sn, items in store_data.items():
        filtered[sn] = [
            it for it in items
            if (it["category"] in FOOD_CATEGORIES
                and it["sales_category"] not in EXCLUDED_SALES_CATEGORIES
                and it["item"] not in (
                    "A la Carte Side",  # generic ring-up, no recipe
                ))
        ]
    return filtered


# ============================================================
# LOAD R365 RECIPE COSTS
# ============================================================
def find_recipe_csv(explicit_path=None):
    """Find the R365 recipe export CSV."""
    if explicit_path:
        if os.path.exists(explicit_path):
            return explicit_path
        print(f"  Error: Recipe CSV not found at {explicit_path}")
        sys.exit(1)

    # Look in Downloads for the latest export_*.csv
    downloads = os.path.expanduser("~/Downloads")
    candidates = []
    for f in os.listdir(downloads):
        if f.startswith("export_") and f.endswith(".csv"):
            full = os.path.join(downloads, f)
            candidates.append((os.path.getmtime(full), full))

    if not candidates:
        print("  Error: No export_*.csv found in Downloads. Use --recipe-csv PATH.")
        sys.exit(1)

    candidates.sort(reverse=True)
    return candidates[0][1]


def load_recipe_costs(csv_path):
    """Load R365 recipe costs from CSV export.
    Returns {recipe_name_upper: {name, avg_cost, min_cost, max_cost, active, portions}}
    """
    recipes = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("RecipeName", "").strip()
            if not name:
                continue
            try:
                avg_cost = float(row.get("AvgCost", 0) or 0)
            except (ValueError, TypeError):
                avg_cost = 0
            try:
                min_cost = float(row.get("MinCost", 0) or 0)
            except (ValueError, TypeError):
                min_cost = 0
            try:
                max_cost = float(row.get("MaxCost", 0) or 0)
            except (ValueError, TypeError):
                max_cost = 0

            active = row.get("Active", "").strip().lower() == "yes"
            portions = row.get("NumberofPortions", "1")
            try:
                portions = float(portions)
            except (ValueError, TypeError):
                portions = 1

            recipes[name.upper()] = {
                "name": name,
                "avg_cost": avg_cost,
                "min_cost": min_cost,
                "max_cost": max_cost,
                "active": active,
                "portions": portions,
            }

    return recipes


# ============================================================
# NAME MATCHING (Toast → R365)
# ============================================================
def normalize_for_fuzzy(name):
    """Strip R365 prefixes, date suffixes, and normalize for comparison."""
    n = name.upper().strip()
    # Strip common prefixes
    for prefix in ["BOWL- ", "BOWLS- ", "BOWL-", "BOWLS-", "WRAP- ", "WRAPS- ",
                    "WRAP-", "WRAPS-", "ADD ON- ", "ADD ON-", "ZZZ-", "ZZZ"]:
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    # Strip date suffixes
    n = re.sub(r'\s*(10\.2025|12\.25|2025|2026|SPRING\s*26|FALL\s*26|SUMMER\s*26)\s*$', '', n)
    # Normalize whitespace
    n = re.sub(r'\s+', ' ', n).strip()
    # Remove trailing dots
    n = n.rstrip('.')
    return n


def match_toast_to_r365(toast_name, recipes):
    """Try to match a Toast item name to an R365 recipe.
    Returns (r365_key, avg_cost) or (None, None).
    """
    # 1. Hardcoded mapping
    if toast_name in TOAST_TO_R365:
        r365_name = TOAST_TO_R365[toast_name].upper()
        if r365_name in recipes:
            return r365_name, recipes[r365_name]["avg_cost"]
        # Try without the exact match (case variations in CSV)
        for key in recipes:
            if key == r365_name:
                return key, recipes[key]["avg_cost"]

    # 2. Direct name match (Toast name appears in R365 as-is)
    toast_upper = toast_name.upper().strip()
    if toast_upper in recipes:
        return toast_upper, recipes[toast_upper]["avg_cost"]

    # 3. Fuzzy matching: normalize both sides and compare
    toast_normalized = normalize_for_fuzzy(toast_name)
    if not toast_normalized:
        return None, None

    best_match = None
    best_score = 0

    for r365_key, r365_data in recipes.items():
        r365_normalized = normalize_for_fuzzy(r365_key)
        if not r365_normalized:
            continue

        # Exact normalized match
        if toast_normalized == r365_normalized:
            # Prefer active recipes
            score = 2 if r365_data["active"] else 1
            if score > best_score:
                best_score = score
                best_match = r365_key

        # Check if one contains the other
        elif toast_normalized in r365_normalized or r365_normalized in toast_normalized:
            score = 1 if r365_data["active"] else 0.5
            if score > best_score:
                best_score = score
                best_match = r365_key

    if best_match:
        return best_match, recipes[best_match]["avg_cost"]

    return None, None


# ============================================================
# MENU ENGINEERING ANALYSIS
# ============================================================
def calculate_menu_engineering(store_data, recipes, menu_prices):
    """Run menu engineering analysis.
    Returns (items_list, unmatched_list, match_stats).
    """
    all_items = defaultdict(lambda: {
        "qty": 0, "revenue": 0, "category": "",
        "store_breakdown": defaultdict(lambda: {"qty": 0, "revenue": 0})
    })

    for sn, items in store_data.items():
        for it in items:
            name = it["item"]
            all_items[name]["qty"] += it["qty"]
            all_items[name]["revenue"] += it["revenue"]
            all_items[name]["category"] = it["category"]
            all_items[name]["store_breakdown"][sn]["qty"] += it["qty"]
            all_items[name]["store_breakdown"][sn]["revenue"] += it["revenue"]

    matched = []
    unmatched = []
    match_count = 0
    unmatched_count = 0
    no_price_count = 0

    for toast_name, data in sorted(all_items.items(), key=lambda x: -x[1]["qty"]):
        r365_key, avg_cost = match_toast_to_r365(toast_name, recipes)

        menu_price = menu_prices.get(toast_name, 0)
        avg_check = round(data["revenue"] / data["qty"], 2) if data["qty"] > 0 else 0
        if menu_price <= 0:
            menu_price = avg_check
            no_price_count += 1

        item_data = {
            "item": toast_name,
            "qty": data["qty"],
            "revenue": round(data["revenue"], 2),
            "category": data["category"],
            "menu_price": menu_price,
            "store_breakdown": {
                sn: {"qty": sb["qty"], "revenue": round(sb["revenue"], 2)}
                for sn, sb in data["store_breakdown"].items()
            },
        }

        if r365_key and avg_cost is not None and avg_cost > 0:
            protein_cost = 0
            protein_name = None
            if toast_name in DEFAULT_PROTEIN:
                protein_r365 = DEFAULT_PROTEIN[toast_name].upper()
                if protein_r365 in recipes:
                    protein_cost = recipes[protein_r365]["avg_cost"]
                    protein_name = recipes[protein_r365]["name"]

            total_cost = avg_cost + protein_cost
            item_data["r365_recipe"] = recipes[r365_key]["name"]
            item_data["recipe_cost"] = round(total_cost, 4)
            item_data["base_cost"] = round(avg_cost, 4)
            item_data["protein_cost"] = round(protein_cost, 4)
            item_data["protein_name"] = protein_name
            item_data["food_cost_pct"] = round(total_cost / menu_price * 100, 1) if menu_price > 0 else 0
            item_data["item_cogs"] = round(total_cost * data["qty"], 2)
            matched.append(item_data)
            match_count += 1
        else:
            item_data["r365_recipe"] = recipes[r365_key]["name"] if r365_key else None
            item_data["recipe_cost"] = avg_cost if avg_cost else 0
            unmatched.append(item_data)
            unmatched_count += 1

    total_qty = sum(it["qty"] for it in matched)
    total_cogs = sum(it["item_cogs"] for it in matched)
    total_theo_rev = sum(it["menu_price"] * it["qty"] for it in matched)

    for it in matched:
        it["mix_pct"] = round(it["qty"] / total_qty * 100, 2) if total_qty > 0 else 0
        it["cogs_contribution"] = round(it["item_cogs"] / total_cogs * 100, 2) if total_cogs > 0 else 0

    if matched:
        food_costs = sorted([it["food_cost_pct"] for it in matched])
        mix_pcts = sorted([it["mix_pct"] for it in matched])
        median_fc = food_costs[len(food_costs) // 2]
        median_mix = mix_pcts[len(mix_pcts) // 2]
    else:
        median_fc = 0
        median_mix = 0

    for it in matched:
        high_pop = it["mix_pct"] >= median_mix
        high_cost = it["food_cost_pct"] >= median_fc
        if high_pop and not high_cost:
            it["quadrant"] = "Star"
        elif high_pop and high_cost:
            it["quadrant"] = "Plowhorse"
        elif not high_pop and not high_cost:
            it["quadrant"] = "Puzzle"
        else:
            it["quadrant"] = "Dog"

    match_stats = {
        "matched": match_count,
        "unmatched": unmatched_count,
        "total": match_count + unmatched_count,
        "matched_revenue": sum(it["revenue"] for it in matched),
        "unmatched_revenue": sum(it["revenue"] for it in unmatched),
        "total_revenue": sum(it["revenue"] for it in matched) + sum(it["revenue"] for it in unmatched),
        "total_qty": total_qty + sum(it["qty"] for it in unmatched),
        "matched_qty": total_qty,
        "total_cogs": total_cogs,
        "total_theo_revenue": round(total_theo_rev, 2),
        "blended_fc_pct": round(total_cogs / total_theo_rev * 100, 1) if total_theo_rev > 0 else 0,
        "median_fc": median_fc,
        "median_mix": median_mix,
        "no_price_count": no_price_count,
    }

    return matched, unmatched, match_stats


def build_protein_data(recipes):
    """Build protein add-on pricing from R365 recipe costs."""
    proteins = []
    for display_name, info in PROTEIN_ITEMS.items():
        r365_key = info["r365"].upper()
        sell_price = info["sell_price"]
        recipe_cost = 0
        if r365_key in recipes:
            recipe_cost = recipes[r365_key]["avg_cost"]
        food_cost_pct = round(recipe_cost / sell_price * 100, 1) if sell_price > 0 else 0
        proteins.append({
            "name": display_name,
            "sell_price": sell_price,
            "recipe_cost": round(recipe_cost, 4),
            "food_cost_pct": food_cost_pct,
            "r365_recipe": recipes[r365_key]["name"] if r365_key in recipes else info["r365"],
        })
    return proteins


# ============================================================
# HTML DASHBOARD GENERATION
# ============================================================
def generate_html(matched, unmatched, match_stats, fy, period, period_start, period_end, proteins=None):
    """Generate the menu cost dashboard HTML."""

    # Prepare data for JSON embedding
    dashboard_data = {
        "fiscal_year": fy,
        "period": period,
        "period_start": period_start.strftime("%Y-%m-%d"),
        "period_end": period_end.strftime("%Y-%m-%d"),
        "generated": datetime.now().isoformat(),
        "store_names": STORE_NAMES,
        "store_numbers": STORE_NUMBERS,
        "matched_items": matched,
        "unmatched_items": unmatched,
        "stats": match_stats,
        "proteins": proteins or [],
    }

    data_json = json.dumps(dashboard_data, default=str)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forage Kitchen - Menu Cost Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}

  .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 20px 30px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
  .header h1 {{ font-size: 24px; font-weight: 700; color: #f8fafc; }}
  .header h1 span {{ color: #22c55e; }}
  .header .meta {{ text-align: right; font-size: 13px; color: #94a3b8; }}
  .header .meta .period {{ font-size: 16px; color: #f8fafc; font-weight: 600; }}
  .header .meta .source {{ font-size: 11px; color: #22c55e; text-transform: uppercase; letter-spacing: 1px; }}

  .container {{ max-width: 1600px; margin: 0 auto; padding: 20px; }}

  /* KPI Cards */
  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .kpi-card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  .kpi-card .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; margin-bottom: 8px; }}
  .kpi-card .value {{ font-size: 26px; font-weight: 700; color: #f8fafc; }}
  .kpi-card .sub {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
  .positive {{ color: #22c55e; }}
  .negative {{ color: #ef4444; }}
  .neutral {{ color: #94a3b8; }}
  .warning {{ color: #f59e0b; }}

  /* Section headers */
  .section-header {{ font-size: 18px; font-weight: 600; color: #f8fafc; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #334155; }}
  .section-sub {{ font-size: 13px; color: #94a3b8; font-weight: 400; margin-left: 8px; }}

  /* Store filter */
  .filter-row {{ display: flex; gap: 12px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }}
  .filter-row label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
  .filter-select {{ background: #334155; color: #f8fafc; border: 1px solid #475569; border-radius: 6px; padding: 6px 28px 6px 10px; font-size: 13px; font-weight: 500; cursor: pointer; appearance: none; -webkit-appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 5l3 3 3-3' stroke='%2394a3b8' stroke-width='1.5' fill='none'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 8px center; }}
  .filter-select:hover {{ border-color: #3b82f6; }}
  .filter-select:focus {{ outline: none; border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,0.3); }}
  .search-box {{ padding: 8px 14px; background: #334155; border: 1px solid #475569; border-radius: 8px; color: #f8fafc; font-size: 13px; width: 280px; }}
  .search-box::placeholder {{ color: #64748b; }}
  .search-box:focus {{ outline: none; border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,0.3); }}

  /* Quadrant cards */
  .quadrant-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }}
  .q-card {{ border-radius: 10px; padding: 16px; border: 1px solid; }}
  .q-star {{ background: #22c55e11; border-color: #22c55e44; }}
  .q-star .q-icon {{ color: #22c55e; }}
  .q-plowhorse {{ background: #f59e0b11; border-color: #f59e0b44; }}
  .q-plowhorse .q-icon {{ color: #f59e0b; }}
  .q-puzzle {{ background: #3b82f611; border-color: #3b82f644; }}
  .q-puzzle .q-icon {{ color: #3b82f6; }}
  .q-dog {{ background: #ef444411; border-color: #ef444444; }}
  .q-dog .q-icon {{ color: #ef4444; }}
  .q-card .q-title {{ font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }}
  .q-card .q-count {{ font-size: 24px; font-weight: 700; color: #f8fafc; }}
  .q-card .q-detail {{ font-size: 12px; color: #94a3b8; margin-top: 4px; }}
  .q-card .q-advice {{ font-size: 11px; color: #64748b; margin-top: 8px; font-style: italic; }}

  /* Chart */
  .chart-container {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; margin-bottom: 24px; }}
  .chart-container h3 {{ font-size: 14px; color: #94a3b8; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .chart-wrap {{ position: relative; height: 500px; }}

  /* Tables */
  .table-wrap {{ overflow-x: auto; border-radius: 12px; border: 1px solid #334155; margin-bottom: 24px; }}
  .data-table {{ width: 100%; border-collapse: collapse; background: #1e293b; min-width: 1100px; }}
  .data-table th {{ background: #334155; padding: 10px 12px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; color: #94a3b8; font-weight: 600; cursor: pointer; white-space: nowrap; user-select: none; position: sticky; top: 0; z-index: 1; }}
  .data-table th:hover {{ background: #3d4f6e; color: #f8fafc; }}
  .data-table th .sort-arrow {{ margin-left: 4px; font-size: 10px; }}
  .data-table th.right, .data-table td.right {{ text-align: right; }}
  .data-table td {{ padding: 8px 12px; border-bottom: 1px solid #253352; font-size: 13px; white-space: nowrap; }}
  .data-table tr:nth-child(even) {{ background: #1e293b; }}
  .data-table tr:nth-child(odd) {{ background: #172033; }}
  .data-table tr:hover {{ background: #253352; }}

  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; letter-spacing: 0.3px; }}
  .badge-star {{ background: #22c55e22; color: #22c55e; border: 1px solid #22c55e44; }}
  .badge-plowhorse {{ background: #f59e0b22; color: #f59e0b; border: 1px solid #f59e0b44; }}
  .badge-puzzle {{ background: #3b82f622; color: #3b82f6; border: 1px solid #3b82f644; }}
  .badge-dog {{ background: #ef444422; color: #ef4444; border: 1px solid #ef444444; }}

  /* Unmatched section */
  .unmatched-table {{ width: 100%; border-collapse: collapse; background: #1e293b; }}
  .unmatched-table th {{ background: #334155; padding: 10px 12px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; color: #94a3b8; font-weight: 600; }}
  .unmatched-table th.right, .unmatched-table td.right {{ text-align: right; }}
  .unmatched-table td {{ padding: 8px 12px; border-bottom: 1px solid #253352; font-size: 13px; }}
  .unmatched-table tr:nth-child(even) {{ background: #1e293b; }}
  .unmatched-table tr:nth-child(odd) {{ background: #172033; }}

  .refresh-notice {{ text-align: center; padding: 12px; color: #64748b; font-size: 12px; margin-top: 20px; }}
  .refresh-notice code {{ background: #334155; padding: 2px 8px; border-radius: 4px; color: #94a3b8; }}

  @media (max-width: 768px) {{
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
    .quadrant-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .header {{ flex-direction: column; gap: 10px; }}
    .header .meta {{ text-align: left; }}
    .chart-wrap {{ height: 350px; }}
  }}
</style>
</head>
<body>
<script src="nav.js"></script>

<div class="header">
  <h1>Forage <span>Kitchen</span> &mdash; Menu Cost Dashboard</h1>
  <div class="meta">
    <div class="period" id="periodLabel"></div>
    <div id="dateRange"></div>
    <div id="lastUpdated"></div>
    <div class="source">Data: Toast PMIX + R365 Recipe Costs</div>
  </div>
</div>

<div class="container">
  <!-- Filter Row -->
  <div class="filter-row">
    <label>Store:</label>
    <select id="storeFilter" class="filter-select" onchange="applyFilters()">
      <option value="all">All Stores Combined</option>
    </select>
    <input type="text" id="searchBox" class="search-box" placeholder="Search menu items..." oninput="applyFilters()">
  </div>

  <!-- KPI Cards -->
  <div class="kpi-row" id="kpiRow"></div>

  <!-- Quadrant Summary -->
  <div class="section-header">Menu Engineering Quadrants</div>
  <div class="quadrant-grid" id="quadrantGrid"></div>

  <!-- Scatter Chart -->
  <div class="chart-container">
    <h3>Menu Engineering Matrix &mdash; Popularity vs. Food Cost %</h3>
    <div class="chart-wrap">
      <canvas id="quadrantChart"></canvas>
    </div>
  </div>

  <!-- Data Table -->
  <div class="section-header">Item Detail<span class="section-sub" id="itemCount"></span></div>
  <div class="table-wrap">
    <table class="data-table" id="itemTable">
      <thead>
        <tr>
          <th data-col="item">Menu Item <span class="sort-arrow"></span></th>
          <th data-col="qty" class="right">Qty Sold <span class="sort-arrow"></span></th>
          <th data-col="menu_price" class="right">Menu Price <span class="sort-arrow"></span></th>
          <th data-col="recipe_cost" class="right">Recipe Cost <span class="sort-arrow"></span></th>
          <th data-col="food_cost_pct" class="right">Food Cost % <span class="sort-arrow"></span></th>
          <th data-col="revenue" class="right">Sales <span class="sort-arrow"></span></th>
          <th data-col="item_cogs" class="right">Item COGS <span class="sort-arrow"></span></th>
          <th data-col="cogs_contribution" class="right">COGS Contrib <span class="sort-arrow"></span></th>
          <th data-col="mix_pct" class="right">Mix % <span class="sort-arrow"></span></th>
          <th data-col="quadrant">Quadrant <span class="sort-arrow"></span></th>
        </tr>
      </thead>
      <tbody id="itemTableBody"></tbody>
    </table>
  </div>

  <!-- Protein Add-Ons -->
  <div class="section-header">Protein Add-Ons</div>
  <div class="table-wrap" id="proteinWrap">
    <table class="data-table" id="proteinTable">
      <thead>
        <tr>
          <th>Protein</th>
          <th class="right">Sell Price</th>
          <th class="right">Recipe Cost</th>
          <th class="right">Food Cost %</th>
          <th>R365 Recipe</th>
        </tr>
      </thead>
      <tbody id="proteinBody"></tbody>
    </table>
  </div>

  <!-- Unmatched Items -->
  <div class="section-header" id="unmatchedHeader">Unmatched Items<span class="section-sub" id="unmatchedCount"></span></div>
  <div class="table-wrap" id="unmatchedWrap">
    <table class="unmatched-table">
      <thead>
        <tr>
          <th>Toast Item</th>
          <th>Category</th>
          <th class="right">Qty Sold</th>
          <th class="right">Revenue</th>
          <th class="right">Avg Price</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody id="unmatchedBody"></tbody>
    </table>
  </div>

  <div class="refresh-notice">
    Run <code>py menu_cost_dashboard.py</code> to refresh &bull;
    Run <code>py menu_cost_dashboard.py P8</code> for a specific period &bull;
    Generated <span id="refreshTime"></span>
  </div>
</div>

<script>
const D = {data_json};

const fmt = (n) => n == null ? '\\u2014' : '$' + Number(n).toLocaleString('en-US', {{minimumFractionDigits: 0, maximumFractionDigits: 0}});
const fmt2 = (n) => n == null ? '\\u2014' : '$' + Number(n).toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
const fmtPct = (n) => n == null ? '\\u2014' : n.toFixed(1) + '%';
const fmtN = (n) => n == null ? '\\u2014' : Number(n).toLocaleString('en-US', {{maximumFractionDigits: 0}});

// Header
document.getElementById('periodLabel').textContent = `FY${{D.fiscal_year}} Period ${{D.period}}`;
document.getElementById('dateRange').textContent = `${{D.period_start}} to ${{D.period_end}}`;
document.getElementById('lastUpdated').textContent = `Updated: ${{new Date(D.generated).toLocaleString()}}`;
document.getElementById('refreshTime').textContent = new Date(D.generated).toLocaleString();

// Store filter dropdown
const storeFilter = document.getElementById('storeFilter');
D.store_numbers.forEach(sn => {{
  const opt = document.createElement('option');
  opt.value = sn;
  opt.textContent = D.store_names[sn];
  storeFilter.appendChild(opt);
}});

// Quadrant colors
const Q_COLORS = {{
  Star: {{ bg: '#22c55e', border: '#16a34a', badge: 'badge-star' }},
  Plowhorse: {{ bg: '#f59e0b', border: '#d97706', badge: 'badge-plowhorse' }},
  Puzzle: {{ bg: '#3b82f6', border: '#2563eb', badge: 'badge-puzzle' }},
  Dog: {{ bg: '#ef4444', border: '#dc2626', badge: 'badge-dog' }}
}};

const Q_META = {{
  Star: {{ icon: '★', css: 'q-star', advice: 'High popularity, low food cost. Protect these items.' }},
  Plowhorse: {{ icon: '\U0001F434', css: 'q-plowhorse', advice: 'Popular but costly. Reduce portion/cost or raise price.' }},
  Puzzle: {{ icon: '\U0001F9E9', css: 'q-puzzle', advice: 'Profitable but underordered. Promote or reposition.' }},
  Dog: {{ icon: '\U0001F6A9', css: 'q-dog', advice: 'Low popularity, high cost. Consider removing or reworking.' }}
}};

let currentSort = {{ col: 'revenue', dir: -1 }};
let chartInstance = null;

function getFilteredData() {{
  const store = storeFilter.value;
  const search = document.getElementById('searchBox').value.toLowerCase();

  let items;
  if (store === 'all') {{
    items = D.matched_items.map(it => ({{ ...it }}));
  }} else {{
    items = [];
    D.matched_items.forEach(it => {{
      const sb = it.store_breakdown[store];
      if (sb && sb.qty > 0 && sb.revenue > 0) {{
        items.push({{
          ...it,
          qty: sb.qty,
          revenue: sb.revenue,
          item_cogs: +(it.recipe_cost * sb.qty).toFixed(2),
          food_cost_pct: it.menu_price > 0 ? +((it.recipe_cost / it.menu_price) * 100).toFixed(1) : 0,
        }});
      }}
    }});

    // Recalculate mix% and cogs contribution
    const totalQty = items.reduce((s, it) => s + it.qty, 0);
    const totalCogs = items.reduce((s, it) => s + it.item_cogs, 0);
    items.forEach(it => {{
      it.mix_pct = totalQty > 0 ? +((it.qty / totalQty) * 100).toFixed(2) : 0;
      it.cogs_contribution = totalCogs > 0 ? +((it.item_cogs / totalCogs) * 100).toFixed(2) : 0;
    }});

    // Recalculate quadrants for this store
    const fcArr = items.map(it => it.food_cost_pct).sort((a, b) => a - b);
    const mixArr = items.map(it => it.mix_pct).sort((a, b) => a - b);
    const medFC = fcArr.length > 0 ? fcArr[Math.floor(fcArr.length / 2)] : 0;
    const medMix = mixArr.length > 0 ? mixArr[Math.floor(mixArr.length / 2)] : 0;
    items.forEach(it => {{
      const highPop = it.mix_pct >= medMix;
      const highCost = it.food_cost_pct >= medFC;
      if (highPop && !highCost) it.quadrant = 'Star';
      else if (highPop && highCost) it.quadrant = 'Plowhorse';
      else if (!highPop && !highCost) it.quadrant = 'Puzzle';
      else it.quadrant = 'Dog';
    }});
  }}

  if (search) {{
    items = items.filter(it => it.item.toLowerCase().includes(search));
  }}

  return items;
}}

function getMedians(items) {{
  if (items.length === 0) return {{ fc: 0, mix: 0 }};
  const fcArr = items.map(it => it.food_cost_pct).sort((a, b) => a - b);
  const mixArr = items.map(it => it.mix_pct).sort((a, b) => a - b);
  return {{
    fc: fcArr[Math.floor(fcArr.length / 2)],
    mix: mixArr[Math.floor(mixArr.length / 2)]
  }};
}}

function renderKPIs(items) {{
  const totalQty = items.reduce((s, it) => s + it.qty, 0);
  const totalRev = items.reduce((s, it) => s + it.revenue, 0);
  const totalCogs = items.reduce((s, it) => s + it.item_cogs, 0);
  const totalTheoRev = items.reduce((s, it) => s + (it.menu_price * it.qty), 0);
  const blendedFC = totalTheoRev > 0 ? (totalCogs / totalTheoRev * 100) : 0;

  const kpiRow = document.getElementById('kpiRow');
  kpiRow.innerHTML = `
    <div class="kpi-card">
      <div class="label">Items Sold</div>
      <div class="value">${{fmtN(totalQty)}}</div>
      <div class="sub">${{items.length}} menu items</div>
    </div>
    <div class="kpi-card">
      <div class="label">Total Revenue</div>
      <div class="value">${{fmt(totalRev)}}</div>
      <div class="sub">Matched items only</div>
    </div>
    <div class="kpi-card">
      <div class="label">Blended Food Cost</div>
      <div class="value ${{blendedFC > 30 ? 'warning' : blendedFC > 25 ? 'neutral' : 'positive'}}">${{fmtPct(blendedFC)}}</div>
      <div class="sub">Recipe cost / menu price</div>
    </div>
    <div class="kpi-card">
      <div class="label">Total Recipe COGS</div>
      <div class="value">${{fmt(totalCogs)}}</div>
      <div class="sub">Based on R365 AvgCost</div>
    </div>
    <div class="kpi-card">
      <div class="label">Items Matched</div>
      <div class="value">${{D.stats.matched}} / ${{D.stats.total}}</div>
      <div class="sub">${{D.stats.unmatched}} unmatched</div>
    </div>
  `;
}}

function renderQuadrants(items) {{
  const grid = document.getElementById('quadrantGrid');
  const quads = {{ Star: [], Plowhorse: [], Puzzle: [], Dog: [] }};
  items.forEach(it => {{ if (quads[it.quadrant]) quads[it.quadrant].push(it); }});

  grid.innerHTML = ['Star', 'Plowhorse', 'Puzzle', 'Dog'].map(q => {{
    const qItems = quads[q];
    const rev = qItems.reduce((s, it) => s + it.revenue, 0);
    const meta = Q_META[q];
    return `<div class="q-card ${{meta.css}}">
      <div class="q-title q-icon">${{meta.icon}} ${{q}}</div>
      <div class="q-count">${{qItems.length}} items</div>
      <div class="q-detail">${{fmt(rev)}} revenue &middot; ${{fmtPct(items.length > 0 ? qItems.length / items.length * 100 : 0)}} of menu</div>
      <div class="q-advice">${{meta.advice}}</div>
    </div>`;
  }}).join('');
}}

function renderChart(items) {{
  const medians = getMedians(items);
  const canvas = document.getElementById('quadrantChart');

  if (chartInstance) chartInstance.destroy();

  const datasets = ['Star', 'Plowhorse', 'Puzzle', 'Dog'].map(q => {{
    const qItems = items.filter(it => it.quadrant === q);
    return {{
      label: q,
      data: qItems.map(it => ({{
        x: it.mix_pct,
        y: it.food_cost_pct,
        r: Math.max(4, Math.min(25, Math.sqrt(it.revenue) / 8)),
        item: it.item,
        qty: it.qty,
        revenue: it.revenue,
        recipe_cost: it.recipe_cost,
        base_cost: it.base_cost || it.recipe_cost,
        protein_cost: it.protein_cost || 0,
        protein_name: it.protein_name || null,
        menu_price: it.menu_price,
      }})),
      backgroundColor: Q_COLORS[q].bg + '99',
      borderColor: Q_COLORS[q].border,
      borderWidth: 1,
    }};
  }});

  chartInstance = new Chart(canvas, {{
    type: 'bubble',
    data: {{ datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        tooltip: {{
          callbacks: {{
            label: function(ctx) {{
              const d = ctx.raw;
              const lines = [
                d.item,
                `Mix: ${{d.x.toFixed(2)}}%  |  Food Cost: ${{d.y.toFixed(1)}}%`,
                `Menu Price: ${{fmt2(d.menu_price)}}  |  Recipe: ${{fmt2(d.recipe_cost)}}`,
              ];
              if (d.protein_cost > 0) {{
                lines.push(`  Base: ${{fmt2(d.base_cost)}} + Protein: ${{fmt2(d.protein_cost)}}`);
              }}
              lines.push(`Qty: ${{fmtN(d.qty)}}  |  Revenue: ${{fmt(d.revenue)}}`);
              return lines;
            }}
          }}
        }},
        legend: {{
          labels: {{ color: '#94a3b8', font: {{ size: 12 }} }}
        }}
      }},
      scales: {{
        x: {{
          title: {{ display: true, text: 'Mix % (Popularity)', color: '#94a3b8', font: {{ size: 13 }} }},
          ticks: {{ color: '#94a3b8', callback: v => v.toFixed(1) + '%' }},
          grid: {{ color: '#33415544' }}
        }},
        y: {{
          title: {{ display: true, text: 'Food Cost % (lower = more profitable)', color: '#94a3b8', font: {{ size: 13 }} }},
          ticks: {{ color: '#94a3b8', callback: v => v.toFixed(0) + '%' }},
          grid: {{ color: '#33415544' }}
        }}
      }},
      // Draw median lines
      animation: {{
        onComplete: function() {{
          const chart = this;
          const ctx = chart.ctx;
          const xScale = chart.scales.x;
          const yScale = chart.scales.y;

          // Vertical median line (mix%)
          const xPixel = xScale.getPixelForValue(medians.mix);
          ctx.save();
          ctx.setLineDash([6, 4]);
          ctx.strokeStyle = '#64748b';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(xPixel, yScale.top);
          ctx.lineTo(xPixel, yScale.bottom);
          ctx.stroke();

          // Horizontal median line (food cost%)
          const yPixel = yScale.getPixelForValue(medians.fc);
          ctx.beginPath();
          ctx.moveTo(xScale.left, yPixel);
          ctx.lineTo(xScale.right, yPixel);
          ctx.stroke();

          // Labels
          ctx.fillStyle = '#64748b';
          ctx.font = '11px sans-serif';
          ctx.setLineDash([]);
          ctx.fillText('Median Mix: ' + medians.mix.toFixed(2) + '%', xPixel + 4, yScale.top + 14);
          ctx.fillText('Median FC: ' + medians.fc.toFixed(1) + '%', xScale.left + 4, yPixel - 6);
          ctx.restore();
        }}
      }}
    }}
  }});
}}

function renderTable(items) {{
  // Sort
  const sorted = [...items].sort((a, b) => {{
    let av = a[currentSort.col], bv = b[currentSort.col];
    if (typeof av === 'string') return currentSort.dir * av.localeCompare(bv);
    return currentSort.dir * ((av || 0) - (bv || 0));
  }});

  const tbody = document.getElementById('itemTableBody');
  tbody.innerHTML = sorted.map(it => {{
    const badgeCls = Q_COLORS[it.quadrant]?.badge || '';
    return `<tr>
      <td>${{it.item}}</td>
      <td class="right">${{fmtN(it.qty)}}</td>
      <td class="right">${{fmt2(it.menu_price)}}</td>
      <td class="right" ${{it.protein_cost > 0 ? 'title="Base: $' + it.base_cost.toFixed(2) + ' + Protein: $' + it.protein_cost.toFixed(2) + '"' : ''}}>${{fmt2(it.recipe_cost)}}${{it.protein_cost > 0 ? ' *' : ''}}</td>
      <td class="right" style="color:${{it.food_cost_pct > 30 ? '#ef4444' : it.food_cost_pct > 25 ? '#f59e0b' : '#22c55e'}}">${{fmtPct(it.food_cost_pct)}}</td>
      <td class="right">${{fmt(it.revenue)}}</td>
      <td class="right">${{fmt(it.item_cogs)}}</td>
      <td class="right">${{fmtPct(it.cogs_contribution)}}</td>
      <td class="right">${{fmtPct(it.mix_pct)}}</td>
      <td><span class="badge ${{badgeCls}}">${{it.quadrant}}</span></td>
    </tr>`;
  }}).join('');

  document.getElementById('itemCount').textContent = `(${{sorted.length}} items)`;

  // Update sort arrows
  document.querySelectorAll('#itemTable th').forEach(th => {{
    const col = th.dataset.col;
    const arrow = th.querySelector('.sort-arrow');
    if (col === currentSort.col) {{
      arrow.textContent = currentSort.dir === 1 ? ' \\u25B2' : ' \\u25BC';
    }} else {{
      arrow.textContent = '';
    }}
  }});
}}

function renderProteins() {{
  const tbody = document.getElementById('proteinBody');
  tbody.innerHTML = D.proteins.map(p => {{
    const fcColor = p.food_cost_pct > 30 ? '#ef4444' : p.food_cost_pct > 25 ? '#f59e0b' : '#22c55e';
    return `<tr>
      <td style="font-weight:600">${{p.name}}</td>
      <td class="right">${{fmt2(p.sell_price)}}</td>
      <td class="right">${{fmt2(p.recipe_cost)}}</td>
      <td class="right" style="color:${{fcColor}}">${{fmtPct(p.food_cost_pct)}}</td>
      <td style="color:#64748b;font-size:12px">${{p.r365_recipe}}</td>
    </tr>`;
  }}).join('');
}}

function renderUnmatched() {{
  const store = storeFilter.value;
  let items = D.unmatched_items;

  if (store !== 'all') {{
    items = items.filter(it => {{
      const sb = it.store_breakdown[store];
      return sb && sb.qty > 0;
    }}).map(it => {{
      const sb = it.store_breakdown[store];
      return {{ ...it, qty: sb.qty, revenue: sb.revenue, menu_price: it.menu_price || (sb.qty > 0 ? +(sb.revenue / sb.qty).toFixed(2) : 0) }};
    }});
  }}

  const search = document.getElementById('searchBox').value.toLowerCase();
  if (search) {{
    items = items.filter(it => it.item.toLowerCase().includes(search));
  }}

  items.sort((a, b) => b.revenue - a.revenue);

  document.getElementById('unmatchedCount').textContent = `(${{items.length}} items, ${{fmt(items.reduce((s,it) => s + it.revenue, 0))}} revenue)`;

  document.getElementById('unmatchedBody').innerHTML = items.map(it => {{
    const note = it.recipe_cost === 0 && it.r365_recipe ? 'Matched but $0 cost' : 'No R365 recipe found';
    return `<tr>
      <td>${{it.item}}</td>
      <td>${{it.category}}</td>
      <td class="right">${{fmtN(it.qty)}}</td>
      <td class="right">${{fmt(it.revenue)}}</td>
      <td class="right">${{fmt2(it.menu_price)}}</td>
      <td style="color:#64748b">${{note}}</td>
    </tr>`;
  }}).join('');

  // Hide section if empty
  const wrap = document.getElementById('unmatchedWrap');
  const header = document.getElementById('unmatchedHeader');
  if (items.length === 0) {{
    wrap.style.display = 'none';
    header.style.display = 'none';
  }} else {{
    wrap.style.display = '';
    header.style.display = '';
  }}
}}

function applyFilters() {{
  const items = getFilteredData();
  renderKPIs(items);
  renderQuadrants(items);
  renderChart(items);
  renderTable(items);
  renderProteins();
  renderUnmatched();
}}

// Column sorting
document.querySelectorAll('#itemTable th').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.col;
    if (!col) return;
    if (currentSort.col === col) {{
      currentSort.dir *= -1;
    }} else {{
      currentSort.col = col;
      currentSort.dir = col === 'item' || col === 'quadrant' ? 1 : -1;
    }}
    const items = getFilteredData();
    renderTable(items);
  }});
}});

// Initial render
applyFilters();
</script>
</body>
</html>'''


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("  Forage Kitchen - Menu Cost Dashboard")
    print("=" * 60)

    # Parse args
    period_arg = None
    recipe_csv_path = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--recipe-csv" and i + 1 < len(args):
            recipe_csv_path = args[i + 1]
            i += 2
        elif args[i].upper().startswith("P"):
            period_arg = args[i]
            i += 1
        else:
            i += 1

    # Determine period
    if period_arg:
        fy, period = resolve_period_arg(period_arg)
    else:
        result = get_current_or_recent_period()
        if not result:
            print("  Error: Could not determine current period.")
            sys.exit(1)
        fy, period = result

    period_start, period_end = get_period_dates(fy, period)
    print(f"\n  Period: P{period} FY{fy}")
    print(f"  Dates:  {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}")

    # Load PMIX data
    print(f"\n  Loading Toast PMIX cache...")
    cache_key = f"FY{fy}_P{period}"
    store_data = load_pmix_data(fy, period)
    total_stores = len(store_data)
    print(f"  Loaded {total_stores} stores")

    if not store_data:
        print("  Error: No PMIX data found. Run product_mix_analysis.py first.")
        sys.exit(1)

    # Filter to menu items
    filtered = filter_menu_items(store_data)
    total_items = sum(len(items) for items in filtered.values())
    total_raw = sum(len(items) for items in store_data.values())
    print(f"  Filtered to {total_items} food item rows (from {total_raw} total)")

    # Load R365 recipe costs
    csv_path = find_recipe_csv(recipe_csv_path)
    print(f"\n  Loading R365 recipe costs from: {os.path.basename(csv_path)}")
    recipes = load_recipe_costs(csv_path)
    print(f"  Loaded {len(recipes)} recipes")

    # Pull menu prices from Toast orders
    print(f"\n  Loading menu board prices...")
    menu_prices = pull_menu_prices(period_end)

    # Run menu engineering
    print(f"\n  Running menu engineering analysis...")
    matched, unmatched, stats = calculate_menu_engineering(filtered, recipes, menu_prices)

    # Print summary
    print(f"\n  {'=' * 50}")
    print(f"  MATCH RESULTS")
    print(f"  {'=' * 50}")
    print(f"  Matched:   {stats['matched']:>3} items  ({fmt_money(stats['matched_revenue'])} revenue)")
    print(f"  Unmatched: {stats['unmatched']:>3} items  ({fmt_money(stats['unmatched_revenue'])} revenue)")
    print(f"  Total:     {stats['total']:>3} items  ({fmt_money(stats['total_revenue'])} revenue)")
    print(f"  Blended food cost: {stats['blended_fc_pct']:.1f}%")
    print(f"  Median food cost:  {stats['median_fc']:.1f}%")
    print(f"  Median mix %:      {stats['median_mix']:.2f}%")

    # Quadrant summary
    quads = defaultdict(list)
    for it in matched:
        quads[it["quadrant"]].append(it)
    print(f"\n  QUADRANT BREAKDOWN:")
    for q in ["Star", "Plowhorse", "Puzzle", "Dog"]:
        qitems = quads.get(q, [])
        qrev = sum(it["revenue"] for it in qitems)
        print(f"    {q:>10}: {len(qitems):>3} items, {fmt_money(qrev)} revenue")

    # Print unmatched
    if unmatched:
        print(f"\n  UNMATCHED ITEMS (top 15 by revenue):")
        for it in sorted(unmatched, key=lambda x: -x["revenue"])[:15]:
            print(f"    {it['item']:<35} qty={it['qty']:>5}  rev={fmt_money(it['revenue'])}")

    # Build protein pricing
    proteins = build_protein_data(recipes)
    print(f"\n  PROTEIN ADD-ONS:")
    for p in proteins:
        print(f"    {p['name']:<30} sell=${p['sell_price']:.2f}  cost=${p['recipe_cost']:.4f}  FC={p['food_cost_pct']:.1f}%")

    # Generate HTML
    print(f"\n  Generating dashboard...")
    html = generate_html(matched, unmatched, stats, fy, period, period_start, period_end, proteins)

    out_path = os.path.join(OUTDIR, "menu_cost_dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Written to: {out_path}")
    print(f"\n  Done! Open menu_cost_dashboard.html in your browser.")


def fmt_money(n):
    """Format as $X,XXX for console output."""
    return f"${n:,.0f}"


if __name__ == "__main__":
    main()
