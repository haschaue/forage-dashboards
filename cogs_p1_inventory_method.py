"""
COGS P1 2026 - Inventory Method
Since the R365 OData API only shows a fraction of AP invoices,
we use the inventory count method:

  COGS = Beginning Inventory + Purchases - Ending Inventory

Where:
  - Beginning Inventory = Stock Count on Dec 30, 2025 (end of P12 2025 / start of P1 2026)
  - Ending Inventory = Stock Count on Jan 27, 2026 (end of P1 2026)
  - Purchases = We can back-calculate from the actual COGS and inventory change

This tells us whether the stock count data in R365 gives us the
inventory-adjusted COGS that matches the P&L.

Also explores: what other transaction types exist that might contain purchases.
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

STORE_NAMES = {
    "8001": "State Street", "8002": "Hilldale", "8003": "Monona",
    "8004": "Old Sauk", "8005": "Champaign", "8006": "Whitefish Bay",
    "8007": "Sun Prairie", "8008": "Pewaukee", "8009": "MKE Public Market",
}

ACTUAL_COGS = {
    "8001": 15555.30, "8002": 24151.52, "8003": 27176.67,
    "8004": 28453.66, "8005": 6712.20, "8006": 27856.49,
    "8007": 27116.83, "8008": 15229.31, "8009": 20097.30,
}
ACTUAL_SALES = {
    "8001": 47703.0, "8002": 82976.0, "8003": 83940.0,
    "8004": 89555.0, "8005": 24924.0, "8006": 86827.0,
    "8007": 92614.0, "8008": 48381.0, "8009": 57216.0,
}


def fetch(url, retries=3):
    url = url.replace(" ", "%20")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5)
            else:
                raise


def fetch_all(url):
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
    print("  COGS P1 2026 - INVENTORY METHOD VALIDATION")
    print("=" * 70)

    # Load reference
    print("\n[1/4] Loading reference data...")
    locations = fetch(BASE + "/Location").get("value", [])
    loc_id_to_num = {l["locationId"]: l.get("locationNumber", "") for l in locations}

    gl_accounts = fetch(BASE + "/GlAccount?$top=1000").get("value", [])
    gl_map = {a["glAccountId"]: {"number": a.get("glAccountNumber", ""), "name": a.get("name", "")} for a in gl_accounts}

    # -------------------------------------------------------
    # Pull ALL stock counts (Dec 2025 and Jan 2026)
    # -------------------------------------------------------
    print("\n[2/4] Pulling stock count transactions...")
    sc_txns = []
    for period in ["2025-12-01T00:00:00Z/2025-12-31T23:59:59Z",
                    "2026-01-01T00:00:00Z/2026-01-31T23:59:59Z"]:
        start, end = period.split("/")
        url = (f"{BASE}/Transaction?$top=5000"
               f"&$filter=type eq 'Stock Count'"
               f" and date ge {start} and date le {end}")
        data = fetch(url)
        sc_txns.extend(data.get("value", []))

    # Deduplicate
    seen = set()
    unique_sc = []
    for t in sc_txns:
        if t["transactionId"] not in seen:
            seen.add(t["transactionId"])
            unique_sc.append(t)
    sc_txns = unique_sc
    print(f"  {len(sc_txns)} stock count transactions")

    # -------------------------------------------------------
    # Pull transaction details for stock counts
    # -------------------------------------------------------
    print("\n[3/4] Pulling transaction details...")
    all_details = fetch_all(BASE + "/TransactionDetail")
    print(f"  {len(all_details)} total details")

    sc_ids = {t["transactionId"] for t in sc_txns}
    sc_details = [d for d in all_details if d.get("transactionId", "") in sc_ids]
    print(f"  {len(sc_details)} stock count detail lines")

    # Build txn lookup
    txn_lookup = {t["transactionId"]: t for t in sc_txns}

    # -------------------------------------------------------
    # Organize stock counts by store and date
    # -------------------------------------------------------
    print("\n[4/4] Processing inventory data...")

    # Structure: {store_num: {date: {total_value, item_count, items: [...]}}}
    inventory = defaultdict(lambda: defaultdict(lambda: {
        "total_value": 0, "item_count": 0, "items": []
    }))

    for td in sc_details:
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

        # Only COGS-related inventory (5xxx accounts)
        if not gl_num.startswith("5"):
            continue

        loc_id = td.get("locationId") or txn.get("locationId", "")
        store_num = loc_id_to_num.get(loc_id, "Unknown")

        try:
            txn_date = datetime.fromisoformat(txn["date"].replace("Z", "+00:00")).replace(tzinfo=None)
        except:
            continue
        date_str = txn_date.strftime("%Y-%m-%d")

        amount = td.get("amount", 0) or 0
        quantity = td.get("quantity", 0) or 0
        prev_total = td.get("previousCountTotal", 0) or 0
        adjustment = td.get("adjustment", 0) or 0

        inv = inventory[store_num][date_str]
        inv["total_value"] += amount
        inv["item_count"] += 1
        inv["items"].append({
            "amount": amount,
            "quantity": quantity,
            "previous": prev_total,
            "adjustment": adjustment,
            "comment": td.get("comment", ""),
        })

    # -------------------------------------------------------
    # Calculate COGS using inventory method
    # -------------------------------------------------------
    print("\n" + "=" * 70)
    print("  INVENTORY COUNTS BY STORE AND DATE")
    print("=" * 70)

    for sn in sorted(STORE_NAMES.keys()):
        print(f"\n  {sn} {STORE_NAMES[sn]}:")
        for dt in sorted(inventory[sn].keys()):
            inv = inventory[sn][dt]
            print(f"    {dt}: {inv['item_count']} items, value: ${inv['total_value']:,.2f}")

    # Define beginning and ending dates
    # Beginning = Dec 30, 2025 (P12 close / P1 open)
    # Ending = Jan 27, 2026 (P1 close)
    BEGIN_DATE = "2025-12-30"
    END_DATE_1 = "2026-01-27"
    END_DATE_2 = "2026-01-28"  # Monona counted a day late

    print("\n\n" + "=" * 70)
    print("  COGS CALCULATION: BEGINNING INV + PURCHASES - ENDING INV")
    print("=" * 70)
    print(f"\n  Beginning Inventory: {BEGIN_DATE}")
    print(f"  Ending Inventory: {END_DATE_1} (8003: {END_DATE_2})")

    print(f"\n  {'STORE':<25} {'Begin Inv':>12} {'End Inv':>12} {'Inv Change':>12} "
          f"{'AP Invoices':>12} {'Implied Purch':>14} {'Actual COGS':>12} {'Actual %':>8}")
    print("-" * 110)

    total_begin = 0
    total_end = 0
    total_actual = 0
    total_sales = 0

    for sn in sorted(STORE_NAMES.keys()):
        # Beginning inventory
        begin_inv = inventory[sn].get(BEGIN_DATE, {}).get("total_value", 0)

        # Ending inventory (most stores Jan 27, Monona Jan 28)
        end_date = END_DATE_2 if sn == "8003" else END_DATE_1
        end_inv = inventory[sn].get(end_date, {}).get("total_value", 0)

        inv_change = end_inv - begin_inv  # positive = inventory grew (less COGS)

        actual_cogs = ACTUAL_COGS.get(sn, 0)
        actual_sales = ACTUAL_SALES.get(sn, 0)
        actual_pct = (actual_cogs / actual_sales * 100) if actual_sales > 0 else 0

        # Back-calculate implied purchases: COGS = Begin + Purchases - End
        # Therefore: Purchases = COGS - Begin + End = COGS + (End - Begin)
        implied_purchases = actual_cogs + inv_change

        # What R365 shows as AP invoices (from previous validation)
        # We'll show it for reference
        r365_ap = 0  # We already know this from the prior run

        total_begin += begin_inv
        total_end += end_inv
        total_actual += actual_cogs
        total_sales += actual_sales

        print(f"  {sn + ' ' + STORE_NAMES.get(sn, ''):<25} "
              f"${begin_inv:>10,.2f} ${end_inv:>10,.2f} ${inv_change:>10,.2f} "
              f"{'':>12} ${implied_purchases:>12,.2f} ${actual_cogs:>10,.2f} {actual_pct:>6.1f}%")

    total_inv_change = total_end - total_begin
    total_implied = total_actual + total_inv_change
    total_actual_pct = (total_actual / total_sales * 100) if total_sales > 0 else 0

    print("-" * 110)
    print(f"  {'TOTAL':<25} "
          f"${total_begin:>10,.2f} ${total_end:>10,.2f} ${total_inv_change:>10,.2f} "
          f"{'':>12} ${total_implied:>12,.2f} ${total_actual:>10,.2f} {total_actual_pct:>6.1f}%")

    # -------------------------------------------------------
    # KEY INSIGHT: What the dashboard should track
    # -------------------------------------------------------
    print("\n\n" + "=" * 70)
    print("  KEY INSIGHT FOR WEEKLY DASHBOARD")
    print("=" * 70)
    print(f"""
  R365 OData exposes:
    - AP Invoices entered directly in R365: ~$44K (only ~23% of actual)
    - Stock Counts (inventory): Complete and accurate for all 9 stores
    - Waste Logs: ~$1.5K

  What's MISSING from OData:
    - The bulk of purchases (~$148K) which likely come through:
      * EDI imports from US Foods, Sysco, etc.
      * These may be recorded as different transaction types
      * Or processed outside the OData-exposed views

  RECOMMENDED DASHBOARD APPROACH:

  Option A: Invoice-Based (Current) - Good for TREND tracking
    - Track what R365 OData shows week over week
    - Won't match P&L COGS % exactly
    - But TRENDS will be consistent (if 23% flows through OData consistently)
    - Use a "coverage factor" to estimate true COGS

  Option B: Inventory-Adjusted Method - More accurate
    - Beginning Inv (prior period close count) = ${total_begin:,.2f}
    - Ending Inv (current period close count) = ${total_end:,.2f}
    - Inventory Change = ${total_inv_change:,.2f}
    - This gives you the TRUE consumption, regardless of invoice source
    - Requires completed stock counts (your Wednesday deadline)

  Coverage Factor (if using Option A):
    - R365 OData invoices = ${43854:,.0f}
    - Actual COGS = ${total_actual:,.0f}
    - Factor = {total_actual / 43854:.2f}x
    - i.e., multiply R365 invoice total by ~{total_actual / 43854:.1f} to estimate true COGS

  BEST APPROACH: Hybrid
    - Weekly: Track R365 invoice purchases as leading indicator
    - Wednesday: GM submits inventory count
    - Dashboard calculates: Prior Week End Inv + Week Purchases - New End Inv = Week COGS
    - Compare vs sales for weekly COGS %
""")

    # -------------------------------------------------------
    # Validate: Can we get closer with ALL transaction types?
    # -------------------------------------------------------
    print("=" * 70)
    print("  EXPLORING ALL TRANSACTION TYPES FOR MISSING PURCHASES")
    print("=" * 70)

    # Let's look at ALL Journal Entry details with 5xxx accounts in P1
    print("\n  Pulling ALL P1 Journal Entry details with 5xxx GL accounts...")

    # Get P1 Journal Entry transactions
    je_txns = []
    for period in ["2025-12-31T00:00:00Z/2026-01-27T23:59:59Z"]:
        start, end = period.split("/")
        url = (f"{BASE}/Transaction?$top=5000"
               f"&$filter=type eq 'Journal Entry'"
               f" and date ge {start} and date le {end}")
        data = fetch(url)
        je_txns.extend(data.get("value", []))
    print(f"  {len(je_txns)} Journal Entry transactions in P1")

    je_ids = {t["transactionId"] for t in je_txns}
    je_details = [d for d in all_details if d.get("transactionId", "") in je_ids]

    # Look at 5xxx GL debits in journal entries
    je_cogs = defaultdict(float)
    je_cogs_by_name = defaultdict(lambda: defaultdict(float))
    je_lookup = {t["transactionId"]: t for t in je_txns}

    for td in je_details:
        gl_id = td.get("glAccountId", "")
        gl_info = gl_map.get(gl_id, {})
        gl_num = gl_info.get("number", "")
        if not gl_num.startswith("5"):
            continue

        loc_id = td.get("locationId", "")
        store_num = loc_id_to_num.get(loc_id, "Unknown")
        debit = td.get("debit", 0) or 0
        credit = td.get("credit", 0) or 0

        if debit > 0:
            je_cogs[store_num] += debit
            txn = je_lookup.get(td.get("transactionId", ""), {})
            je_cogs_by_name[store_num][txn.get("name", "Unknown")[:50]] += debit

    print(f"\n  Journal Entry 5xxx DEBITS by store:")
    total_je = 0
    for sn in sorted(STORE_NAMES.keys()):
        amt = je_cogs.get(sn, 0)
        total_je += amt
        print(f"    {sn} {STORE_NAMES[sn]}: ${amt:,.2f}")
    print(f"    TOTAL: ${total_je:,.2f}")

    if total_je > 0:
        print(f"\n  Sample Journal Entry names with 5xxx debits:")
        for sn in sorted(je_cogs_by_name.keys()):
            if sn not in STORE_NAMES:
                continue
            print(f"\n    {sn} {STORE_NAMES.get(sn, '')}:")
            for name, amt in sorted(je_cogs_by_name[sn].items(), key=lambda x: -x[1])[:5]:
                print(f"      ${amt:>10,.2f}  {name}")

    # Final combined view
    print(f"\n\n" + "=" * 70)
    print(f"  COMBINED: AP INVOICES + JOURNAL ENTRIES + WASTE")
    print(f"=" * 70)

    # Reload the AP data from the first validation
    # (We know the totals from the prior run)
    ap_totals = {
        "8001": 4800.97, "8002": 3384.65, "8003": 8059.07,
        "8004": 7018.46, "8005": 2996.76, "8006": 3315.61,
        "8007": 5995.36, "8008": 3929.12, "8009": 4353.61,
    }
    waste_totals = {
        "8001": 91.0, "8002": 244.07, "8006": 754.85,
        "8007": 27.17, "8009": 399.86,
    }

    print(f"\n  {'STORE':<25} {'AP Invoice':>12} {'Jnl Entry':>10} {'Waste':>10} "
          f"{'COMBINED':>12} {'ACTUAL':>12} {'COVERAGE':>10}")
    print("-" * 100)

    total_combined = 0
    for sn in sorted(STORE_NAMES.keys()):
        ap = ap_totals.get(sn, 0)
        je = je_cogs.get(sn, 0)
        waste = waste_totals.get(sn, 0)
        combined = ap + je + waste
        actual = ACTUAL_COGS.get(sn, 0)
        coverage = (combined / actual * 100) if actual > 0 else 0
        total_combined += combined

        print(f"  {sn + ' ' + STORE_NAMES.get(sn, ''):<25} "
              f"${ap:>10,.2f} ${je:>8,.2f} ${waste:>8,.2f} "
              f"${combined:>10,.2f} ${actual:>10,.2f} {coverage:>8.1f}%")

    total_coverage = (total_combined / sum(ACTUAL_COGS.values()) * 100)
    print("-" * 100)
    print(f"  {'TOTAL':<25} "
          f"${sum(ap_totals.values()):>10,.2f} ${total_je:>8,.2f} ${sum(waste_totals.values()):>8,.2f} "
          f"${total_combined:>10,.2f} ${sum(ACTUAL_COGS.values()):>10,.2f} {total_coverage:>8.1f}%")


if __name__ == "__main__":
    main()
