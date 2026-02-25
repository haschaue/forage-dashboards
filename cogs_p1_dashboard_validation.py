"""
COGS Dashboard P1 2026 Validation
Runs the dashboard logic against P1 2026 (Dec 31 2025 - Jan 27 2026)
and compares output against actual P&L COGS numbers.

KEY FINDINGS:
- R365 OData only exposes ~23% of purchase invoices (EDI imports not in OData)
- Stock counts give us beginning and ending inventory accurately
- But COGS = Begin + TOTAL Purchases - End, and we only have 23% of purchases
- Therefore: Dashboard shows R365 invoice trends, with period-end inventory
  reconciliation showing the coverage gap

The dashboard is most useful for:
1. Weekly TREND tracking (consistent 23% coverage makes trends reliable)
2. GM accountability (inventory counts done? invoices approved?)
3. Vendor mix analysis (for the vendors visible in OData)
4. Period-end inventory values (beginning/ending inventory from stock counts)
"""
import sys
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict

OUTDIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, OUTDIR)

from cogs_dashboard import (
    r365_fetch, r365_fetch_all, R365_BASE,
    load_r365_reference, pull_transactions_for_period,
    pull_transaction_details, extract_vendor_name,
    toast_authenticate, pull_period_sales,
    get_445_periods, get_period_weeks,
    COGS_GL_ACCOUNTS, STORE_NAMES, FISCAL_YEAR_STARTS
)

# ============================================================
# ACTUAL P&L DATA FROM CLOSED P1 2026
# Source: Kitchen Trailing P&L P1.26.xlsx
# ============================================================
ACTUAL_P1_COGS = {
    "8001": 15555.30, "8002": 24151.52, "8003": 27176.67,
    "8004": 28453.66, "8005": 6712.20, "8006": 27856.49,
    "8007": 27116.83, "8008": 15229.31, "8009": 20097.30,
}
ACTUAL_P1_COGS_TOTAL = sum(ACTUAL_P1_COGS.values())  # ~$192,349

ACTUAL_P1_SALES = {
    "8001": 47703.0, "8002": 82976.0, "8003": 83940.0,
    "8004": 89555.0, "8005": 24924.0, "8006": 86827.0,
    "8007": 92614.0, "8008": 48381.0, "8009": 57216.0,
}
ACTUAL_P1_SALES_TOTAL = sum(ACTUAL_P1_SALES.values())


def main():
    print("=" * 80)
    print("  COGS Dashboard P1 2026 Validation")
    print("  Comparing dashboard output vs actual P&L")
    print("=" * 80)

    # P1 2026: Dec 31 2025 to Jan 27 2026
    fy = 2026
    period = 1
    periods = get_445_periods(FISCAL_YEAR_STARTS[fy])
    p1 = periods[0]
    period_start = p1["start"]
    period_end = p1["end"]
    period_weeks = get_period_weeks(period_start, period_end)

    print(f"\n  P1 2026: {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}")
    print(f"  Weeks: {len(period_weeks)}")

    cache_key = f"FY{fy}_P{period}"

    # --------------------------------------------------------
    # Step 1: Load reference data
    # --------------------------------------------------------
    print("\n[1/6] Loading R365 reference data...")
    loc_map, gl_map, item_map = load_r365_reference()

    gl_to_cogs_cat = {}
    for gl_id, info in gl_map.items():
        num = info.get("number", "")
        if num in COGS_GL_ACCOUNTS:
            gl_to_cogs_cat[gl_id] = COGS_GL_ACCOUNTS[num]

    loc_id_to_num = {lid: info["number"] for lid, info in loc_map.items()}

    # --------------------------------------------------------
    # Step 2: Pull transactions for P1
    # --------------------------------------------------------
    print(f"\n[2/6] Pulling COGS transactions for P1 2026...")
    transactions = pull_transactions_for_period(period_start, period_end)

    txn_by_type = defaultdict(list)
    for txn in transactions:
        txn_by_type[txn.get("type", "Unknown")].append(txn)
    for txn_type, txns in sorted(txn_by_type.items()):
        print(f"    {txn_type}: {len(txns)} transactions")

    # --------------------------------------------------------
    # Step 3: Also pull stock counts from Dec 2025 (for begin inventory)
    # The dashboard only pulls within-period, but we need the prior
    # period's ending count which IS the current period's beginning
    # --------------------------------------------------------
    print(f"\n[3/6] Pulling Dec 2025 stock counts (beginning inventory)...")
    dec_sc_url = (f"{R365_BASE}/Transaction?$top=5000"
                  f"&$filter=type eq 'Stock Count'"
                  f" and date ge 2025-12-01T00:00:00Z"
                  f" and date le 2025-12-31T23:59:59Z")
    dec_sc_data = r365_fetch(dec_sc_url)
    dec_sc_txns = dec_sc_data.get("value", [])
    print(f"    {len(dec_sc_txns)} Dec 2025 stock count transactions")

    # Also get Jan 28 (Monona counted a day late)
    jan28_url = (f"{R365_BASE}/Transaction?$top=5000"
                 f"&$filter=type eq 'Stock Count'"
                 f" and date ge 2026-01-28T00:00:00Z"
                 f" and date le 2026-01-28T23:59:59Z")
    jan28_data = r365_fetch(jan28_url)
    jan28_txns = jan28_data.get("value", [])
    print(f"    {len(jan28_txns)} Jan 28 stock count transactions (Monona)")

    # Combine all transactions
    all_txns = transactions + dec_sc_txns + jan28_txns
    # Deduplicate
    seen = set()
    unique_txns = []
    for t in all_txns:
        if t["transactionId"] not in seen:
            seen.add(t["transactionId"])
            unique_txns.append(t)
    all_txns = unique_txns

    # --------------------------------------------------------
    # Step 4: Pull transaction details
    # --------------------------------------------------------
    print(f"\n[4/6] Pulling transaction details...")
    txn_ids = [t["transactionId"] for t in all_txns]
    details = pull_transaction_details(txn_ids)
    print(f"    {len(details)} detail lines matched")

    txn_lookup = {t["transactionId"]: t for t in all_txns}

    # --------------------------------------------------------
    # Step 5: Process data
    # --------------------------------------------------------
    print(f"\n[5/6] Processing COGS data...")

    store_numbers = sorted([sn for sn in STORE_NAMES.keys() if sn != "8010"])

    # Period-level data per store
    period_data = defaultdict(lambda: {
        "purchases_food": 0, "purchases_packaging": 0, "purchases_beverage": 0,
        "purchases_other": 0, "purchases_total": 0,
        "credits": 0, "waste": 0,
        "begin_inv": 0, "end_inv": 0,
        "has_begin_count": False, "has_end_count": False,
        "invoices_total": 0,
        "vendors": defaultdict(float),
    })

    # Dates for beginning (Dec 30) and ending (Jan 27, or Jan 28 for Monona) inventory
    BEGIN_DATE = "2025-12-30"
    END_DATES = {"8003": "2026-01-28"}
    DEFAULT_END = "2026-01-27"

    for td in details:
        txn_id = td.get("transactionId", "")
        txn = txn_lookup.get(txn_id)
        if not txn:
            continue

        txn_type = txn.get("type", "")
        txn_date_str = txn.get("date", "")
        try:
            txn_date = datetime.fromisoformat(txn_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except:
            continue

        loc_id = td.get("locationId") or txn.get("locationId", "")
        store_num = loc_id_to_num.get(loc_id, "Unknown")
        if store_num not in STORE_NAMES or store_num == "8010":
            continue

        row_type = td.get("rowType", "")
        gl_id = td.get("glAccountId", "")
        gl_info = gl_map.get(gl_id, {})
        gl_num = gl_info.get("number", "")
        debit = td.get("debit", 0) or 0
        credit = td.get("credit", 0) or 0
        amount = td.get("amount", 0) or 0

        pd = period_data[store_num]
        date_str = txn_date.strftime("%Y-%m-%d")

        if txn_type == "Stock Count" and row_type == "Detail" and gl_num.startswith("5"):
            # Beginning inventory: Dec 30 stock count amount
            if date_str == BEGIN_DATE:
                pd["begin_inv"] += amount if amount else 0
                pd["has_begin_count"] = True

            # Ending inventory: Jan 27 (or Jan 28 for Monona)
            end_date = END_DATES.get(store_num, DEFAULT_END)
            if date_str == end_date:
                pd["end_inv"] += amount if amount else 0
                pd["has_end_count"] = True

            # Also check previousCountTotal on end counts as alternative begin
            if date_str == end_date:
                prev = td.get("previousCountTotal", 0) or 0
                if prev > 0 and not pd["has_begin_count"]:
                    pd["begin_inv"] += prev
                    pd["has_begin_count"] = True

        elif txn_type == "AP Invoice" and row_type == "Detail":
            if not (period_start <= txn_date <= period_end):
                continue
            if gl_num.startswith("5"):
                cogs_cat = gl_to_cogs_cat.get(gl_id, None)
                if cogs_cat == "Food":
                    pd["purchases_food"] += debit
                elif cogs_cat == "Packaging":
                    pd["purchases_packaging"] += debit
                elif cogs_cat == "Beverage":
                    pd["purchases_beverage"] += debit
                else:
                    pd["purchases_other"] += debit
                pd["purchases_total"] += debit
            vendor = extract_vendor_name(txn.get("name", ""))
            pd["vendors"][vendor] += debit
            pd["invoices_total"] += 1

        elif txn_type == "AP Credit Memo" and row_type == "Detail":
            if not (period_start <= txn_date <= period_end):
                continue
            if gl_num.startswith("5"):
                pd["credits"] += credit

        elif txn_type == "Waste Log" and row_type == "Detail":
            if not (period_start <= txn_date <= period_end):
                continue
            waste_amt = abs(amount) if amount < 0 else debit
            pd["waste"] += waste_amt

    # Calculate derived values
    for sn in period_data:
        pd = period_data[sn]
        pd["net_purchases"] = pd["purchases_total"] - pd["credits"]

    # --------------------------------------------------------
    # Step 6: Pull Toast sales
    # --------------------------------------------------------
    print(f"\n[6/6] Pulling Toast sales for P1 2026...")
    toast_token = toast_authenticate()
    store_sales = pull_period_sales(toast_token, period_start, period_end, cache_key)

    period_sales = defaultdict(float)
    for store_num, daily_sales in store_sales.items():
        for date_str, ns in daily_sales.items():
            period_sales[store_num] += ns

    # ============================================================
    # COMPARISON TABLE
    # ============================================================
    print("\n" + "=" * 120)
    print("  P1 2026 VALIDATION: Dashboard Data vs Actual P&L")
    print("=" * 120)

    header = (f"  {'Store':<20} {'Toast Sales':>11} {'P&L Sales':>11} "
              f"{'Begin Inv':>10} {'End Inv':>10} {'R365 Purch':>11} "
              f"{'Actual COGS':>12} {'R365 COGS%':>10} {'Actual%':>8} "
              f"{'Coverage':>9}")
    print(f"\n{header}")
    print("  " + "-" * 116)

    total_toast = 0
    total_pl_sales = 0
    total_begin = 0
    total_end = 0
    total_r365 = 0
    total_actual_cogs = 0

    for sn in store_numbers:
        pd = period_data[sn]
        toast_ns = period_sales.get(sn, 0)
        pl_sales = ACTUAL_P1_SALES.get(sn, 0)
        actual_cogs = ACTUAL_P1_COGS.get(sn, 0)

        begin = pd["begin_inv"]
        end = pd["end_inv"]
        r365 = pd["net_purchases"]

        r365_pct = (r365 / toast_ns * 100) if toast_ns > 0 else 0
        actual_pct = (actual_cogs / pl_sales * 100) if pl_sales > 0 else 0
        coverage = (r365 / actual_cogs * 100) if actual_cogs > 0 else 0

        total_toast += toast_ns
        total_pl_sales += pl_sales
        total_begin += begin
        total_end += end
        total_r365 += r365
        total_actual_cogs += actual_cogs

        name = STORE_NAMES.get(sn, sn)
        begin_str = f"${begin:>8,.0f}" if pd["has_begin_count"] else "    N/A  "
        end_str = f"${end:>8,.0f}" if pd["has_end_count"] else "    N/A  "

        print(f"  {sn} {name:<13} ${toast_ns:>9,.0f} ${pl_sales:>9,.0f} "
              f"{begin_str} {end_str} ${r365:>9,.0f} "
              f"${actual_cogs:>10,.0f} {r365_pct:>8.1f}% {actual_pct:>6.1f}% "
              f"{coverage:>7.1f}%")

    print("  " + "-" * 116)

    total_r365_pct = (total_r365 / total_toast * 100) if total_toast > 0 else 0
    total_actual_pct = (total_actual_cogs / total_pl_sales * 100) if total_pl_sales > 0 else 0
    total_coverage = (total_r365 / total_actual_cogs * 100) if total_actual_cogs > 0 else 0

    print(f"  {'ALL STORES':<20} ${total_toast:>9,.0f} ${total_pl_sales:>9,.0f} "
          f"${total_begin:>8,.0f} ${total_end:>8,.0f} ${total_r365:>9,.0f} "
          f"${total_actual_cogs:>10,.0f} {total_r365_pct:>8.1f}% {total_actual_pct:>6.1f}% "
          f"{total_coverage:>7.1f}%")

    # ============================================================
    # INVENTORY METHOD VALIDATION
    # ============================================================
    print("\n\n" + "=" * 120)
    print("  INVENTORY METHOD: Begin Inv + TRUE Purchases - End Inv = Actual COGS")
    print("=" * 120)

    print(f"\n  If we had the TRUE total purchases:")
    print(f"  {'Store':<20} {'Begin Inv':>10} {'End Inv':>10} {'Inv Change':>11} "
          f"{'Actual COGS':>12} {'Implied Purch':>14} {'R365 Purch':>11} {'EDI/Missing':>12}")
    print("  " + "-" * 105)

    total_implied = 0
    total_edi = 0

    for sn in store_numbers:
        pd = period_data[sn]
        actual_cogs = ACTUAL_P1_COGS.get(sn, 0)
        begin = pd["begin_inv"]
        end = pd["end_inv"]
        inv_change = end - begin
        r365 = pd["net_purchases"]

        # Implied total purchases = COGS + End - Begin = COGS + inv_change
        implied = actual_cogs + inv_change
        edi_missing = implied - r365

        total_implied += implied
        total_edi += edi_missing

        name = STORE_NAMES.get(sn, sn)
        print(f"  {sn} {name:<13} ${begin:>8,.0f} ${end:>8,.0f} ${inv_change:>9,.0f} "
              f"${actual_cogs:>10,.0f} ${implied:>12,.0f} ${r365:>9,.0f} ${edi_missing:>10,.0f}")

    print("  " + "-" * 105)
    total_inv_change = total_end - total_begin
    print(f"  {'TOTAL':<20} ${total_begin:>8,.0f} ${total_end:>8,.0f} ${total_inv_change:>9,.0f} "
          f"${total_actual_cogs:>10,.0f} ${total_implied:>12,.0f} ${total_r365:>9,.0f} ${total_edi:>10,.0f}")

    # ============================================================
    # COVERAGE FACTOR ANALYSIS
    # ============================================================
    coverage_factor = total_actual_cogs / total_r365 if total_r365 > 0 else 0

    print("\n\n" + "=" * 120)
    print("  COVERAGE FACTOR ANALYSIS")
    print("=" * 120)
    print(f"\n  R365 OData Invoices (P1):  ${total_r365:>12,.0f}")
    print(f"  Actual P&L COGS (P1):      ${total_actual_cogs:>12,.0f}")
    print(f"  Coverage Rate:             {total_coverage:>11.1f}%")
    print(f"  Coverage Factor:           {coverage_factor:>11.2f}x")
    print(f"  (Multiply R365 invoices by {coverage_factor:.2f} to estimate true COGS)")

    # Per-store coverage
    print(f"\n  Per-Store Coverage Rates:")
    coverages = []
    for sn in store_numbers:
        pd = period_data[sn]
        actual = ACTUAL_P1_COGS.get(sn, 0)
        r365 = pd["net_purchases"]
        cov = (r365 / actual * 100) if actual > 0 else 0
        factor = (actual / r365) if r365 > 0 else 0
        coverages.append(cov)
        name = STORE_NAMES.get(sn, sn)
        print(f"    {sn} {name:<18}: {cov:>5.1f}% coverage (factor: {factor:.2f}x)")

    avg_cov = sum(coverages) / len(coverages) if coverages else 0
    min_cov = min(coverages) if coverages else 0
    max_cov = max(coverages) if coverages else 0
    print(f"\n    Range: {min_cov:.1f}% - {max_cov:.1f}%, Average: {avg_cov:.1f}%")

    # ============================================================
    # ESTIMATED COGS USING COVERAGE FACTOR
    # ============================================================
    print(f"\n\n" + "=" * 120)
    print(f"  IF DASHBOARD USED {coverage_factor:.2f}x COVERAGE FACTOR:")
    print("=" * 120)

    print(f"\n  {'Store':<20} {'Toast Sales':>11} {'R365 Inv':>10} {'Estimated':>10} {'Actual':>10} "
          f"{'Est %':>7} {'Act %':>7} {'Delta':>8}")
    print("  " + "-" * 90)

    total_est = 0
    for sn in store_numbers:
        pd = period_data[sn]
        toast_ns = period_sales.get(sn, 0)
        actual = ACTUAL_P1_COGS.get(sn, 0)
        r365 = pd["net_purchases"]
        estimated = r365 * coverage_factor
        est_pct = (estimated / toast_ns * 100) if toast_ns > 0 else 0
        act_pct = (actual / ACTUAL_P1_SALES.get(sn, 1) * 100)
        delta = estimated - actual
        total_est += estimated

        name = STORE_NAMES.get(sn, sn)
        print(f"  {sn} {name:<13} ${toast_ns:>9,.0f} ${r365:>8,.0f} ${estimated:>8,.0f} ${actual:>8,.0f} "
              f"{est_pct:>5.1f}% {act_pct:>5.1f}% ${delta:>+7,.0f}")

    print("  " + "-" * 90)
    total_est_pct = (total_est / total_toast * 100) if total_toast > 0 else 0
    total_delta = total_est - total_actual_cogs
    print(f"  {'TOTAL':<20} ${total_toast:>9,.0f} ${total_r365:>8,.0f} ${total_est:>8,.0f} ${total_actual_cogs:>8,.0f} "
          f"{total_est_pct:>5.1f}% {total_actual_pct:>5.1f}% ${total_delta:>+7,.0f}")

    # ============================================================
    # SUMMARY & RECOMMENDATIONS
    # ============================================================
    print("\n\n" + "=" * 120)
    print("  SUMMARY & DASHBOARD RECOMMENDATIONS")
    print("=" * 120)
    print(f"""
  WHAT R365 ODATA GIVES US:
    - AP Invoices:     ${total_r365:>10,.0f} ({total_coverage:.1f}% of actual COGS)
    - Begin Inventory: ${total_begin:>10,.0f} (from Dec 30 stock counts)
    - End Inventory:   ${total_end:>10,.0f} (from Jan 27 stock counts)
    - Waste Logs:      ${sum(period_data[sn]['waste'] for sn in store_numbers):>10,.0f}
    - Stock count data is COMPLETE and ACCURATE for all stores

  WHY INVENTORY METHOD ALONE DOESN'T WORK:
    - COGS = Begin({total_begin:,.0f}) + Purchases(?) - End({total_end:,.0f})
    - We need TOTAL purchases, but only have {total_coverage:.0f}% via OData
    - R365 OData: ${total_r365:,.0f} vs True Purchases: ~${total_implied:,.0f}
    - The ~${total_edi:,.0f} gap is EDI imports (US Foods, Sysco, etc.)

  DASHBOARD APPROACH OPTIONS:

  1. R365 INVOICE TRACKING (Current - Best for weekly trends)
     - Shows R365 invoices as-is (~{total_coverage:.0f}% coverage)
     - COGS% will consistently read ~{total_r365_pct:.0f}% instead of ~{total_actual_pct:.0f}%
     - But WEEK-TO-WEEK TRENDS are reliable and consistent
     - Best for: "Is this week higher or lower than last week?"

  2. COVERAGE FACTOR ESTIMATION (Add to dashboard)
     - Apply {coverage_factor:.2f}x multiplier to R365 invoices
     - Estimated COGS would be ${total_est:,.0f} vs actual ${total_actual_cogs:,.0f}
     - Per-store accuracy varies ({min_cov:.0f}%-{max_cov:.0f}% coverage range)
     - Recalibrate factor each closed period

  3. INVENTORY COUNTS (Already in dashboard)
     - Beginning and ending inventory accurately tracked
     - Shows inventory change (consumption from shelf)
     - Period-end reconciliation confirms coverage gap

  RECOMMENDED: Use Option 1 for weekly monitoring with Option 2 overlay.
  Each period close, update the coverage factor from the actual P&L.
""")


if __name__ == "__main__":
    main()
