"""
COGS P1 2026 Validation
Pulls all COGS-related data from R365 for FY2026 Period 1
and compares against the actual P&L ($192,618.18 consolidated).

Goal: Understand what R365 OData shows vs. actuals, so we can
calibrate the weekly COGS dashboard.

FY2026 P1: 2025-12-31 to 2026-01-27 (4 weeks, Wed-Tue)

COGS formula:
  Beginning Inventory + Purchases - Credits - Ending Inventory + Waste = COGS
"""
import base64
import urllib.request
import json
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict

OUTDIR = os.path.dirname(os.path.abspath(__file__))

# R365 Auth
cred = b'foragekitchen\x5chenry@foragekombucha.com:KingJames1!'
auth = base64.b64encode(cred).decode()
HEADERS = {"Authorization": "Basic " + auth, "Accept": "application/json"}
BASE = "https://odata.restaurant365.net/api/v2/views"

# Store names
STORE_NAMES = {
    "8001": "State Street", "8002": "Hilldale", "8003": "Monona",
    "8004": "Old Sauk", "8005": "Champaign", "8006": "Whitefish Bay",
    "8007": "Sun Prairie", "8008": "Pewaukee", "8009": "MKE Public Market",
    "8010": "Brookfield",
}

# Actual P&L COGS (from Kitchen Trailing P&L P1.26.xlsx)
ACTUAL_COGS = {
    "8001": 15555.30,
    "8002": 24151.52,
    "8003": 27176.67,
    "8004": 28453.66,
    "8005": 6712.20,
    "8006": 27856.49,
    "8007": 27116.83,
    "8008": 15229.31,
    "8009": 20097.30,
}
ACTUAL_TOTAL = 192618.18

# Actual Net Sales from P&L
ACTUAL_SALES = {
    "8001": 47703.0,
    "8002": 82976.0,
    "8003": 83940.0,
    "8004": 89555.0,
    "8005": 24924.0,
    "8006": 86827.0,
    "8007": 92614.0,
    "8008": 48381.0,
    "8009": 57216.0,
}

# P1 dates
P1_START = datetime(2025, 12, 31)
P1_END = datetime(2026, 1, 27)

# Also check the period just before P1 for beginning inventory
PRE_P1_START = datetime(2025, 12, 1)
PRE_P1_END = datetime(2025, 12, 30)


def fetch(url, retries=3):
    url = url.replace(" ", "%20")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                print(f"      Retry {attempt+1}: {e}")
                time.sleep(5)
            else:
                raise


def fetch_all_pages(url):
    all_records = []
    skip = 0
    while True:
        sep = '&' if '?' in url else '?'
        page_url = f"{url}{sep}$top=5000&$skip={skip}"
        data = fetch(page_url)
        records = data.get("value", [])
        all_records.extend(records)
        if len(records) < 5000:
            break
        skip += 5000
    return all_records


def main():
    print("=" * 70)
    print("  COGS P1 2026 VALIDATION")
    print("  Period: 2025-12-31 to 2026-01-27 (4 weeks)")
    print("  Comparing R365 data vs Actual P&L")
    print("=" * 70)

    # -------------------------------------------------------
    # Load reference data
    # -------------------------------------------------------
    print("\n[1/5] Loading reference data...")

    locations = fetch(BASE + "/Location").get("value", [])
    loc_id_to_num = {}
    for loc in locations:
        loc_id_to_num[loc["locationId"]] = loc.get("locationNumber", "")
    print(f"  {len(loc_id_to_num)} locations")

    gl_accounts = fetch(BASE + "/GlAccount?$top=1000").get("value", [])
    gl_map = {}
    for acct in gl_accounts:
        gl_map[acct["glAccountId"]] = {
            "number": acct.get("glAccountNumber", ""),
            "name": acct.get("name", ""),
        }
    print(f"  {len(gl_map)} GL accounts")

    items = fetch_all_pages(BASE + "/Item")
    item_map = {}
    for item in items:
        item_map[item["itemId"]] = {
            "name": item.get("name", ""),
            "cat1": item.get("category1", ""),
            "cat2": item.get("category2", ""),
        }
    print(f"  {len(item_map)} items")

    # -------------------------------------------------------
    # Pull ALL transactions for P1 + pre-P1 (for beginning inventory)
    # -------------------------------------------------------
    print("\n[2/5] Pulling transactions...")

    all_txn_types = ["AP Invoice", "AP Credit Memo", "Stock Count", "Waste Log",
                     "Item Transfer", "Journal Entry"]

    # We need Dec 2025 + Jan 2026 to cover P1 and pre-P1 stock counts
    all_txns = []
    for txn_type in all_txn_types:
        # Dec 2025
        url = (f"{BASE}/Transaction?$top=5000"
               f"&$filter=type eq '{txn_type}'"
               f" and date ge 2025-12-01T00:00:00Z"
               f" and date le 2025-12-31T23:59:59Z")
        data = fetch(url)
        records = data.get("value", [])
        all_txns.extend(records)

        # Jan 2026
        url2 = (f"{BASE}/Transaction?$top=5000"
                f"&$filter=type eq '{txn_type}'"
                f" and date ge 2026-01-01T00:00:00Z"
                f" and date le 2026-01-31T23:59:59Z")
        data2 = fetch(url2)
        records2 = data2.get("value", [])
        all_txns.extend(records2)

    # Deduplicate
    seen = set()
    unique_txns = []
    for t in all_txns:
        tid = t["transactionId"]
        if tid not in seen:
            seen.add(tid)
            unique_txns.append(t)
    all_txns = unique_txns

    # Group by type
    txn_by_type = defaultdict(list)
    for t in all_txns:
        txn_by_type[t.get("type", "")].append(t)

    print(f"  Total unique transactions (Dec 2025 + Jan 2026):")
    for ttype, txns in sorted(txn_by_type.items()):
        print(f"    {ttype}: {len(txns)}")

    # Filter to P1 date range for AP/Waste, but keep all stock counts
    p1_txns = []
    stock_count_txns = []
    for t in all_txns:
        try:
            dt = datetime.fromisoformat(t["date"].replace("Z", "+00:00")).replace(tzinfo=None)
        except:
            continue

        if t.get("type") == "Stock Count":
            stock_count_txns.append((t, dt))
        elif P1_START <= dt <= P1_END:
            p1_txns.append(t)

    print(f"\n  P1 transactions (excl stock counts): {len(p1_txns)}")
    p1_by_type = defaultdict(list)
    for t in p1_txns:
        p1_by_type[t.get("type", "")].append(t)
    for ttype, txns in sorted(p1_by_type.items()):
        print(f"    {ttype}: {len(txns)}")

    # Stock counts - find the ones closest to P1 boundaries
    print(f"\n  All Stock Counts found:")
    for sc, dt in sorted(stock_count_txns, key=lambda x: x[1]):
        loc_id = sc.get("locationId", "")
        store = loc_id_to_num.get(loc_id, "Unknown")
        print(f"    {dt.strftime('%Y-%m-%d')} | {store} | {sc.get('name', '')[:60]}")

    # -------------------------------------------------------
    # Pull ALL transaction details
    # -------------------------------------------------------
    print(f"\n[3/5] Pulling all transaction details...")
    all_details = fetch_all_pages(BASE + "/TransactionDetail")
    print(f"  {len(all_details)} total detail lines")

    # Build txn lookup
    txn_lookup = {t["transactionId"]: t for t in all_txns}

    # Filter details to our transactions
    txn_id_set = set(t["transactionId"] for t in p1_txns)
    sc_id_set = set(t["transactionId"] for t, _ in stock_count_txns)
    relevant_details = [d for d in all_details
                        if d.get("transactionId", "") in (txn_id_set | sc_id_set)]
    print(f"  {len(relevant_details)} relevant detail lines")

    # -------------------------------------------------------
    # Process: Calculate COGS components by store
    # -------------------------------------------------------
    print(f"\n[4/5] Processing COGS components...")

    store_data = defaultdict(lambda: {
        "purchases_5110": 0,  # Food
        "purchases_5210": 0,  # Packaging
        "purchases_5310": 0,  # Beverage
        "purchases_total": 0,
        "credits_total": 0,
        "waste_total": 0,
        "journal_cogs": 0,
        "all_5xxx_debits": 0,
        "all_5xxx_credits": 0,
        "stock_counts": [],
        "vendors": defaultdict(float),
        "ap_invoice_count": 0,
    })

    # Track all GL 5xxx activity regardless of type
    all_5xxx_activity = defaultdict(lambda: defaultdict(float))

    for td in relevant_details:
        txn_id = td.get("transactionId", "")
        txn = txn_lookup.get(txn_id)
        if not txn:
            continue

        txn_type = txn.get("type", "")
        row_type = td.get("rowType", "")
        gl_id = td.get("glAccountId", "")
        gl_info = gl_map.get(gl_id, {})
        gl_num = gl_info.get("number", "")

        loc_id = td.get("locationId") or txn.get("locationId", "")
        store_num = loc_id_to_num.get(loc_id, "Unknown")

        debit = td.get("debit", 0) or 0
        credit = td.get("credit", 0) or 0
        amount = td.get("amount", 0) or 0
        quantity = td.get("quantity", 0) or 0

        # Track ALL 5xxx GL activity
        if gl_num.startswith("5"):
            all_5xxx_activity[store_num][f"{txn_type}|{row_type}|debit"] += debit
            all_5xxx_activity[store_num][f"{txn_type}|{row_type}|credit"] += credit

        sd = store_data[store_num]

        # --- AP Invoices ---
        if txn_type == "AP Invoice" and row_type == "Detail":
            if gl_num.startswith("5"):
                sd["purchases_total"] += debit
                sd["all_5xxx_debits"] += debit
                if gl_num == "5110":
                    sd["purchases_5110"] += debit
                elif gl_num == "5210":
                    sd["purchases_5210"] += debit
                elif gl_num == "5310":
                    sd["purchases_5310"] += debit
                sd["ap_invoice_count"] += 1

                vendor = txn.get("name", "").split(" - ")
                if len(vendor) >= 2:
                    sd["vendors"][vendor[1].strip()] += debit

        # --- AP Credit Memos ---
        elif txn_type == "AP Credit Memo" and row_type == "Detail":
            if gl_num.startswith("5"):
                sd["credits_total"] += credit
                sd["all_5xxx_credits"] += credit

        # --- Waste Logs ---
        elif txn_type == "Waste Log" and row_type == "Detail":
            if gl_num.startswith("5"):
                waste_amt = debit if debit > 0 else abs(amount)
                sd["waste_total"] += waste_amt
                sd["all_5xxx_debits"] += waste_amt

        # --- Journal Entries (COGS postings) ---
        elif txn_type == "Journal Entry" and row_type == "Detail":
            if gl_num.startswith("5"):
                sd["journal_cogs"] += debit
                sd["all_5xxx_debits"] += debit
                sd["all_5xxx_credits"] += credit

        # --- Stock Counts ---
        elif txn_type == "Stock Count" and row_type == "Detail":
            try:
                txn_dt = datetime.fromisoformat(txn["date"].replace("Z", "+00:00")).replace(tzinfo=None)
            except:
                continue
            if gl_num.startswith("5"):
                sd["stock_counts"].append({
                    "date": txn_dt.strftime("%Y-%m-%d"),
                    "amount": amount,
                    "previous": td.get("previousCountTotal", 0) or 0,
                    "adjustment": td.get("adjustment", 0) or 0,
                    "quantity": quantity,
                    "item": item_map.get(td.get("itemId", ""), {}).get("name", ""),
                })

    # -------------------------------------------------------
    # Print Results
    # -------------------------------------------------------
    print(f"\n[5/5] RESULTS")
    print("=" * 70)

    # First show the raw 5xxx GL activity breakdown
    print("\n--- ALL 5xxx GL ACTIVITY BY TYPE (debits/credits) ---")
    for store_num in sorted(all_5xxx_activity.keys()):
        if store_num not in STORE_NAMES:
            continue
        print(f"\n  {store_num} {STORE_NAMES.get(store_num, '')}:")
        for key in sorted(all_5xxx_activity[store_num].keys()):
            val = all_5xxx_activity[store_num][key]
            if val > 0:
                print(f"    {key}: ${val:,.2f}")

    # Main comparison table
    print("\n\n" + "=" * 70)
    print(f"  {'STORE':<25} {'PURCHASES':>12} {'CREDITS':>10} {'WASTE':>10} "
          f"{'JNL ENTRY':>10} {'R365 COGS':>12} {'ACTUAL':>12} {'DIFF':>12} {'DIFF %':>8}")
    print("-" * 70)

    total_purchases = 0
    total_credits = 0
    total_waste = 0
    total_journal = 0
    total_r365 = 0

    for sn in sorted(STORE_NAMES.keys()):
        sd = store_data.get(sn, store_data["dummy"] if "dummy" in store_data else {
            "purchases_total": 0, "credits_total": 0, "waste_total": 0,
            "journal_cogs": 0, "all_5xxx_debits": 0, "all_5xxx_credits": 0,
        })
        if isinstance(sd, dict) and "purchases_total" not in sd:
            continue

        purchases = sd.get("purchases_total", 0)
        credits = sd.get("credits_total", 0)
        waste = sd.get("waste_total", 0)
        journal = sd.get("journal_cogs", 0)
        actual = ACTUAL_COGS.get(sn, 0)

        # Method 1: Purchases - Credits + Waste (pure invoice-based)
        r365_method1 = purchases - credits + waste

        # Method 2: All 5xxx debits - credits (captures journal entries too)
        r365_method2 = sd.get("all_5xxx_debits", 0) - sd.get("all_5xxx_credits", 0)

        diff1 = r365_method1 - actual
        diff_pct1 = (diff1 / actual * 100) if actual > 0 else 0

        total_purchases += purchases
        total_credits += credits
        total_waste += waste
        total_journal += journal
        total_r365 += r365_method1

        print(f"  {sn + ' ' + STORE_NAMES.get(sn, ''):<25} "
              f"${purchases:>10,.0f} ${credits:>8,.0f} ${waste:>8,.0f} "
              f"${journal:>8,.0f} ${r365_method1:>10,.0f} ${actual:>10,.0f} "
              f"${diff1:>10,.0f} {diff_pct1:>6.1f}%")

    print("-" * 70)
    total_diff = total_r365 - ACTUAL_TOTAL
    total_diff_pct = (total_diff / ACTUAL_TOTAL * 100) if ACTUAL_TOTAL > 0 else 0
    print(f"  {'TOTAL':<25} "
          f"${total_purchases:>10,.0f} ${total_credits:>8,.0f} ${total_waste:>8,.0f} "
          f"${total_journal:>8,.0f} ${total_r365:>10,.0f} ${ACTUAL_TOTAL:>10,.0f} "
          f"${total_diff:>10,.0f} {total_diff_pct:>6.1f}%")

    # Method 2 comparison
    print("\n\n--- METHOD 2: ALL 5xxx DEBITS - CREDITS (includes journal entries) ---")
    print(f"  {'STORE':<25} {'5xxx Debits':>12} {'5xxx Credits':>10} {'NET 5xxx':>12} {'ACTUAL':>12} {'DIFF':>12} {'DIFF %':>8}")
    print("-" * 70)

    total_m2 = 0
    for sn in sorted(STORE_NAMES.keys()):
        sd = store_data.get(sn, {})
        debits = sd.get("all_5xxx_debits", 0)
        credits = sd.get("all_5xxx_credits", 0)
        net = debits - credits
        actual = ACTUAL_COGS.get(sn, 0)
        diff = net - actual
        diff_pct = (diff / actual * 100) if actual > 0 else 0
        total_m2 += net
        print(f"  {sn + ' ' + STORE_NAMES.get(sn, ''):<25} "
              f"${debits:>10,.0f} ${credits:>8,.0f} ${net:>10,.0f} "
              f"${actual:>10,.0f} ${diff:>10,.0f} {diff_pct:>6.1f}%")

    total_m2_diff = total_m2 - ACTUAL_TOTAL
    total_m2_pct = (total_m2_diff / ACTUAL_TOTAL * 100) if ACTUAL_TOTAL > 0 else 0
    print("-" * 70)
    print(f"  {'TOTAL':<25} "
          f"{'':>12} {'':>10} ${total_m2:>10,.0f} "
          f"${ACTUAL_TOTAL:>10,.0f} ${total_m2_diff:>10,.0f} {total_m2_pct:>6.1f}%")

    # COGS % comparison
    print("\n\n--- COGS % COMPARISON ---")
    print(f"  {'STORE':<25} {'Net Sales':>12} {'R365 COGS%':>10} {'Actual COGS%':>12} {'Budget%':>8}")
    print("-" * 70)

    # Load budget
    budget = {}
    budget_path = os.path.join(OUTDIR, "budget_2026.json")
    if os.path.exists(budget_path):
        with open(budget_path) as f:
            budget = json.load(f)

    for sn in sorted(STORE_NAMES.keys()):
        sd = store_data.get(sn, {})
        purchases = sd.get("purchases_total", 0)
        credits = sd.get("credits_total", 0)
        waste = sd.get("waste_total", 0)
        r365_cogs = purchases - credits + waste

        actual_cogs = ACTUAL_COGS.get(sn, 0)
        actual_sales = ACTUAL_SALES.get(sn, 0)

        r365_pct = (r365_cogs / actual_sales * 100) if actual_sales > 0 else 0
        actual_pct = (actual_cogs / actual_sales * 100) if actual_sales > 0 else 0
        budget_pct = budget.get(sn, {}).get("1", {}).get("cogs_pct", 0)

        print(f"  {sn + ' ' + STORE_NAMES.get(sn, ''):<25} "
              f"${actual_sales:>10,.0f} {r365_pct:>9.1f}% {actual_pct:>11.1f}% {budget_pct:>7.1f}%")

    total_actual_sales = sum(ACTUAL_SALES.values())
    total_r365_pct = (total_r365 / total_actual_sales * 100) if total_actual_sales > 0 else 0
    total_actual_pct = (ACTUAL_TOTAL / total_actual_sales * 100) if total_actual_sales > 0 else 0
    all_budget_pct = budget.get("ALL", {}).get("1", {}).get("cogs_pct", 0)
    print("-" * 70)
    print(f"  {'TOTAL':<25} "
          f"${total_actual_sales:>10,.0f} {total_r365_pct:>9.1f}% {total_actual_pct:>11.1f}% {all_budget_pct:>7.1f}%")

    # Stock count detail
    print("\n\n--- STOCK COUNTS FOUND ---")
    for sn in sorted(STORE_NAMES.keys()):
        sd = store_data.get(sn, {})
        scs = sd.get("stock_counts", [])
        if scs:
            dates = set(sc["date"] for sc in scs)
            total_amt = sum(sc["amount"] for sc in scs)
            total_prev = sum(sc["previous"] for sc in scs)
            total_adj = sum(sc["adjustment"] for sc in scs)
            print(f"  {sn} {STORE_NAMES.get(sn, '')}:")
            print(f"    Dates: {', '.join(sorted(dates))}")
            print(f"    Items counted: {len(scs)}")
            print(f"    Current value: ${total_amt:,.2f}")
            print(f"    Previous value: ${total_prev:,.2f}")
            print(f"    Adjustment: ${total_adj:,.2f}")
        else:
            print(f"  {sn} {STORE_NAMES.get(sn, '')}: NO STOCK COUNTS FOUND")

    # Top vendors
    print("\n\n--- TOP VENDORS (P1 Consolidated) ---")
    all_vendors = defaultdict(float)
    for sn in STORE_NAMES:
        sd = store_data.get(sn, {})
        for v, a in sd.get("vendors", {}).items():
            all_vendors[v] += a
    for v, a in sorted(all_vendors.items(), key=lambda x: -x[1])[:20]:
        print(f"  ${a:>10,.2f}  {v}")

    print(f"\n\nTotal vendor purchases: ${sum(all_vendors.values()):,.2f}")
    print(f"Actual P&L COGS: ${ACTUAL_TOTAL:,.2f}")
    print(f"Gap: ${ACTUAL_TOTAL - sum(all_vendors.values()):,.2f}")
    print(f"\nThis gap likely represents:")
    print(f"  - Inventory adjustments (beginning - ending inventory change)")
    print(f"  - COGS journal entries from inventory counts")
    print(f"  - Any accrued or manual COGS entries")


if __name__ == "__main__":
    main()
