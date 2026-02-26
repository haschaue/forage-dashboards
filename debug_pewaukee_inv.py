"""
Debug script: Investigate why store 8008 (Pewaukee) shows no inventory count
on the P2 COGS dashboard.

P2 2026: 2026-01-28 to 2026-02-24
"""
import base64
import urllib.request
import json
import ssl
import time
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# Setup - reuse the same auth / config as cogs_dashboard.py
# ============================================================
OUTDIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, OUTDIR)
from r365_config import SSS_CONFIG, FISCAL_YEAR_STARTS

R365_CRED = b'foragekitchen\x5chenry@foragekombucha.com:KingJames1!'
R365_AUTH = base64.b64encode(R365_CRED).decode()
R365_HEADERS = {"Authorization": "Basic " + R365_AUTH, "Accept": "application/json"}
R365_BASE = "https://odata.restaurant365.net/api/v2/views"
SSL_CTX = ssl.create_default_context()

STORE_NAMES = {k: v["name"] for k, v in SSS_CONFIG.items()}

# P2 date range
P2_START = "2026-01-28"
P2_END = "2026-02-24"
# Extended window to check for late/early counts
EXT_START = "2026-01-25"
EXT_END = "2026-02-27"


def r365_fetch(url, retries=3):
    url = url.replace(" ", "%20")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=R365_HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 5
                print(f"  [retry {attempt+1}] R365 error: {e}, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def r365_fetch_all(url, max_records=50000):
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


def main():
    print("=" * 70)
    print("  DEBUG: Pewaukee (8008) Missing Inventory - P2 2026")
    print("  P2 range: {} to {}".format(P2_START, P2_END))
    print("  Extended check: {} to {}".format(EXT_START, EXT_END))
    print("  Run time: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 70)

    # ----------------------------------------------------------
    # Step 1: Load Location reference data
    # ----------------------------------------------------------
    print("\n[1] Loading Location reference data...")
    loc_data = r365_fetch(R365_BASE + "/Location").get("value", [])
    loc_map = {}       # locationId -> {number, name}
    loc_by_num = {}    # locationNumber -> locationId
    for loc in loc_data:
        lid = loc["locationId"]
        num = loc.get("locationNumber", "")
        name = loc.get("name", "")
        loc_map[lid] = {"number": num, "name": name}
        if num:
            loc_by_num[num] = lid
    print(f"  Loaded {len(loc_map)} locations")

    # Show all locations that match our stores
    print("\n  Store -> Location mapping:")
    pewaukee_loc_id = None
    for store_num in sorted(STORE_NAMES.keys()):
        lid = loc_by_num.get(store_num, None)
        if lid:
            info = loc_map[lid]
            tag = " <<<< TARGET" if store_num == "8008" else ""
            print(f"    {store_num} ({STORE_NAMES[store_num]}): locationId={lid}, R365 name='{info['name']}'{tag}")
            if store_num == "8008":
                pewaukee_loc_id = lid
        else:
            print(f"    {store_num} ({STORE_NAMES[store_num]}): NOT FOUND in Location view!")

    if not pewaukee_loc_id:
        # Try fuzzy match
        print("\n  WARNING: No exact locationNumber match for '8008'. Searching by name...")
        for lid, info in loc_map.items():
            if "pewaukee" in info["name"].lower() or "8008" in info["number"]:
                print(f"    FOUND: locationId={lid}, number={info['number']}, name='{info['name']}'")
                pewaukee_loc_id = lid

    # ----------------------------------------------------------
    # Step 2: Load GL Account reference data
    # ----------------------------------------------------------
    print("\n[2] Loading GL Account reference data...")
    gl_data = r365_fetch(R365_BASE + "/GlAccount?$top=1000").get("value", [])
    gl_map = {}
    for acct in gl_data:
        gl_map[acct["glAccountId"]] = {
            "number": acct.get("glAccountNumber", ""),
            "name": acct.get("name", "")
        }
    print(f"  Loaded {len(gl_map)} GL accounts")

    # Show COGS-related GL accounts (5xxx)
    cogs_gl = {gid: info for gid, info in gl_map.items() if info["number"].startswith("5")}
    print(f"  COGS GL accounts (5xxx): {len(cogs_gl)}")
    for gid, info in sorted(cogs_gl.items(), key=lambda x: x[1]["number"]):
        print(f"    {info['number']}: {info['name']} (id={gid})")

    # ----------------------------------------------------------
    # Step 3: Pull ALL Stock Count transactions for EXTENDED date range
    # R365 OData has a max 31-day range, so we chunk requests
    # ----------------------------------------------------------
    print("\n[3] Pulling Stock Count transactions (extended range: {} to {})...".format(EXT_START, EXT_END))

    stock_counts = []
    ext_start_dt = datetime.strptime(EXT_START, "%Y-%m-%d")
    ext_end_dt = datetime.strptime(EXT_END, "%Y-%m-%d")
    current = ext_start_dt
    while current <= ext_end_dt:
        chunk_end = min(current + timedelta(days=30), ext_end_dt)
        start_str = current.strftime("%Y-%m-%dT00:00:00Z")
        end_str = chunk_end.strftime("%Y-%m-%dT23:59:59Z")

        url = (f"{R365_BASE}/Transaction?$top=5000"
               f"&$filter=type eq 'Stock Count'"
               f" and date ge {start_str}"
               f" and date le {end_str}")
        print(f"  Chunk: {current.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}")
        try:
            txn_data = r365_fetch(url)
            records = txn_data.get("value", [])
            stock_counts.extend(records)
            print(f"    Got {len(records)} records")
        except Exception as e:
            print(f"    ERROR: {e}")

        current = chunk_end + timedelta(days=1)

    print(f"  Total Stock Count transactions in extended range: {len(stock_counts)}")

    if not stock_counts:
        print("\n  *** NO STOCK COUNT TRANSACTIONS FOUND AT ALL ***")
        print("  This means R365 returned zero Stock Count records for the entire window.")
        print("  Possible causes:")
        print("    - Stock counts not yet entered")
        print("    - Transaction type name mismatch")
        print("    - Date filter issue")

        # Try broader search without date filter
        print("\n  Trying broader search (no date filter, just Stock Count type)...")
        url2 = f"{R365_BASE}/Transaction?$top=20&$filter=type eq 'Stock Count'&$orderby=date desc"
        try:
            data2 = r365_fetch(url2)
            recent = data2.get("value", [])
            print(f"  Found {len(recent)} recent Stock Count transactions (no date filter)")
            for t in recent[:10]:
                loc_id = t.get("locationId", "")
                store_info = loc_map.get(loc_id, {})
                store_num = store_info.get("number", "???")
                print(f"    {t.get('date','?')[:10]} | {t.get('name','')} | store={store_num} | id={t.get('transactionId','')[:20]}")
        except Exception as e:
            print(f"  Error: {e}")

    # ----------------------------------------------------------
    # Step 4: Analyze each Stock Count transaction
    # ----------------------------------------------------------
    print("\n[4] Analyzing Stock Count transactions...")

    # Group by store
    sc_by_store = defaultdict(list)
    sc_by_id = {}
    pewaukee_txn_ids = []

    for txn in stock_counts:
        txn_id = txn.get("transactionId", "")
        loc_id = txn.get("locationId", "")
        store_info = loc_map.get(loc_id, {})
        store_num = store_info.get("number", "???")
        txn_date = txn.get("date", "")[:10]
        txn_name = txn.get("name", "")

        in_p2 = P2_START <= txn_date <= P2_END
        tag = "[IN P2]" if in_p2 else "[OUTSIDE P2]"

        sc_by_store[store_num].append({
            "id": txn_id,
            "date": txn_date,
            "name": txn_name,
            "locationId": loc_id,
            "in_p2": in_p2,
            "type": txn.get("type", ""),
            "raw": txn,
        })
        sc_by_id[txn_id] = txn

        if store_num == "8008" or loc_id == pewaukee_loc_id:
            pewaukee_txn_ids.append(txn_id)

    print(f"\n  Stock Count transactions by store:")
    print(f"  {'Store':<8} {'Name':<20} {'In P2':>6} {'Outside':>8} {'Total':>6}")
    print(f"  {'-'*8} {'-'*20} {'-'*6} {'-'*8} {'-'*6}")
    for sn in sorted(sc_by_store.keys()):
        entries = sc_by_store[sn]
        in_p2 = sum(1 for e in entries if e["in_p2"])
        outside = sum(1 for e in entries if not e["in_p2"])
        name = STORE_NAMES.get(sn, "Unknown")
        marker = " <<<< TARGET" if sn == "8008" else ""
        print(f"  {sn:<8} {name:<20} {in_p2:>6} {outside:>8} {len(entries):>6}{marker}")

    # Also check for unmapped stores
    if "???" in sc_by_store:
        print(f"\n  WARNING: {len(sc_by_store['???'])} Stock Counts with UNKNOWN store mapping:")
        for e in sc_by_store["???"]:
            print(f"    date={e['date']}, name={e['name']}, locationId={e['locationId']}")

    # ----------------------------------------------------------
    # Step 5: Show ALL stock count details for every store
    # ----------------------------------------------------------
    print("\n[5] Listing every Stock Count transaction (all stores)...")
    for sn in sorted(sc_by_store.keys()):
        entries = sc_by_store[sn]
        name = STORE_NAMES.get(sn, "Unknown")
        print(f"\n  --- Store {sn} ({name}) ---")
        for e in sorted(entries, key=lambda x: x["date"]):
            tag = "IN P2" if e["in_p2"] else "OUTSIDE P2"
            print(f"    [{tag}] {e['date']} | {e['name']}")
            print(f"           txnId={e['id'][:30]}... | locationId={e['locationId']}")

    # ----------------------------------------------------------
    # Step 6: Pull TransactionDetail for all stock count txn IDs
    # ----------------------------------------------------------
    all_sc_ids = set(txn.get("transactionId", "") for txn in stock_counts)
    print(f"\n[6] Pulling TransactionDetail for {len(all_sc_ids)} stock count transactions...")
    print("  (This pulls all TransactionDetail rows and filters in memory - may take a moment)")

    all_details = r365_fetch_all(R365_BASE + "/TransactionDetail")
    print(f"  Total TransactionDetail rows: {len(all_details)}")

    sc_details = [td for td in all_details if td.get("transactionId", "") in all_sc_ids]
    print(f"  Stock Count detail rows: {len(sc_details)}")

    # Group details by transaction
    details_by_txn = defaultdict(list)
    for td in sc_details:
        details_by_txn[td.get("transactionId", "")].append(td)

    # ----------------------------------------------------------
    # Step 7: Show detail analysis per store
    # ----------------------------------------------------------
    print("\n[7] Stock Count detail analysis by store...")

    for sn in sorted(sc_by_store.keys()):
        entries = sc_by_store[sn]
        name = STORE_NAMES.get(sn, "Unknown")
        is_target = (sn == "8008")

        if is_target:
            print(f"\n{'='*70}")
            print(f"  >>>>> STORE {sn} ({name}) - TARGET STORE <<<<<")
            print(f"{'='*70}")
        else:
            print(f"\n  --- Store {sn} ({name}) ---")

        for e in sorted(entries, key=lambda x: x["date"]):
            tag = "IN P2" if e["in_p2"] else "OUTSIDE"
            print(f"\n    [{tag}] {e['date']} | {e['name']}")
            txn_id = e["id"]
            dets = details_by_txn.get(txn_id, [])
            print(f"    Detail rows: {len(dets)}")

            cogs_rows = 0
            total_amount = 0
            total_prev = 0
            total_adj = 0

            for td in dets:
                gl_id = td.get("glAccountId", "")
                gl_info = gl_map.get(gl_id, {})
                gl_num = gl_info.get("number", "???")
                gl_name = gl_info.get("name", "???")
                row_type = td.get("rowType", "")
                amount = td.get("amount", 0) or 0
                prev = td.get("previousCountTotal", 0) or 0
                adj = td.get("adjustment", 0) or 0
                debit = td.get("debit", 0) or 0
                credit = td.get("credit", 0) or 0
                det_loc_id = td.get("locationId", "")
                det_store = loc_map.get(det_loc_id, {}).get("number", "???") if det_loc_id else "N/A"

                # Only print detail for target store or summary for others
                if is_target or (sn == "???" and True):
                    print(f"      rowType={row_type:10s} | GL={gl_num:6s} ({gl_name[:25]:25s}) | "
                          f"amt={amount:>10.2f} | prev={prev:>10.2f} | adj={adj:>10.2f} | "
                          f"dr={debit:>10.2f} cr={credit:>10.2f} | detLoc={det_store}")

                if row_type == "Detail" and gl_num.startswith("5"):
                    cogs_rows += 1
                    total_amount += amount
                    total_prev += prev
                    total_adj += adj

            print(f"    COGS detail rows (rowType=Detail, GL starts with 5): {cogs_rows}")
            print(f"    Total amount (ending inv): ${total_amount:,.2f}")
            print(f"    Total previousCountTotal (beginning inv): ${total_prev:,.2f}")
            print(f"    Total adjustment: ${total_adj:,.2f}")

            if cogs_rows == 0 and is_target:
                print(f"    >>> NO COGS ROWS! Dashboard will show zero inventory for this count.")
                print(f"    >>> Checking: are there ANY detail rows?")
                if not dets:
                    print(f"    >>> ZERO detail rows for this transaction!")
                else:
                    print(f"    >>> There ARE {len(dets)} detail rows but NONE have rowType=Detail + GL 5xxx")
                    # Show what GL accounts ARE present
                    gl_counts = defaultdict(int)
                    rt_counts = defaultdict(int)
                    for td in dets:
                        gl_id = td.get("glAccountId", "")
                        gl_num = gl_map.get(gl_id, {}).get("number", "???")
                        rt = td.get("rowType", "???")
                        gl_counts[gl_num] += 1
                        rt_counts[rt] += 1
                    print(f"    >>> GL accounts present: {dict(gl_counts)}")
                    print(f"    >>> Row types present: {dict(rt_counts)}")

    # ----------------------------------------------------------
    # Step 8: Extra diagnostics for Pewaukee
    # ----------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"  DIAGNOSTIC SUMMARY FOR STORE 8008 (Pewaukee)")
    print(f"{'='*70}")

    pewaukee_entries = sc_by_store.get("8008", [])
    if not pewaukee_entries:
        print(f"\n  RESULT: NO Stock Count transactions found for store 8008 in the extended range")
        print(f"  Extended range searched: {EXT_START} to {EXT_END}")
        print(f"")
        print(f"  Possible causes:")
        print(f"    1. Stock counts for Pewaukee have not been entered in R365")
        print(f"    2. Stock counts exist but are assigned to a different locationId")
        print(f"    3. Stock counts exist but with a different transaction type")
        print(f"    4. Location '8008' is not in the R365 Location view")
        print(f"")

        # Check: are there any transactions at all for Pewaukee?
        if pewaukee_loc_id:
            print(f"  Pewaukee locationId: {pewaukee_loc_id}")
            print(f"  Checking if ANY transactions (not just Stock Count) reference this locationId...")
            any_pewaukee = [txn for txn in stock_counts if txn.get("locationId") == pewaukee_loc_id]
            print(f"  Stock Count txns with Pewaukee locationId: {len(any_pewaukee)}")

            # Check TransactionDetail for Pewaukee locationId
            pewaukee_details = [td for td in all_details if td.get("locationId") == pewaukee_loc_id]
            print(f"  TransactionDetail rows with Pewaukee locationId: {len(pewaukee_details)}")
            if pewaukee_details:
                # What transaction types do these belong to?
                parent_txn_ids = set(td.get("transactionId") for td in pewaukee_details)
                print(f"  Parent transactions: {len(parent_txn_ids)}")
                for pid in list(parent_txn_ids)[:10]:
                    parent = sc_by_id.get(pid)
                    if parent:
                        print(f"    txnId={pid[:30]}... type={parent.get('type')} date={parent.get('date','')[:10]} name={parent.get('name','')}")
                    else:
                        print(f"    txnId={pid[:30]}... (not in our Stock Count set - may be invoice/other type)")
        else:
            print(f"  Pewaukee locationId: NOT FOUND - store 8008 has no matching Location record!")
    else:
        in_p2 = [e for e in pewaukee_entries if e["in_p2"]]
        outside = [e for e in pewaukee_entries if not e["in_p2"]]

        print(f"\n  Stock Count transactions for 8008:")
        print(f"    In P2 ({P2_START} to {P2_END}): {len(in_p2)}")
        print(f"    Outside P2: {len(outside)}")

        if in_p2:
            print(f"\n  In-P2 transactions:")
            for e in in_p2:
                dets = details_by_txn.get(e["id"], [])
                cogs_dets = [td for td in dets
                             if td.get("rowType") == "Detail"
                             and gl_map.get(td.get("glAccountId", ""), {}).get("number", "").startswith("5")]
                print(f"    {e['date']} | {e['name']} | {len(dets)} detail rows | {len(cogs_dets)} COGS rows")
                if not cogs_dets:
                    print(f"      >>> ZERO COGS detail rows - THIS IS WHY INVENTORY IS MISSING")

        if outside:
            print(f"\n  Outside-P2 transactions:")
            for e in outside:
                print(f"    {e['date']} | {e['name']}")

    # ----------------------------------------------------------
    # Step 9: Check if dashboard logic would match these records
    # ----------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"  DASHBOARD LOGIC CHECK")
    print(f"{'='*70}")
    print(f"\n  The dashboard filters for:")
    print(f"    txn_type == 'Stock Count'")
    print(f"    row_type == 'Detail'")
    print(f"    GL account starts with '5'")
    print(f"    locationId maps to a store in STORE_NAMES")
    print(f"    date falls within P2 ({P2_START} to {P2_END})")
    print(f"")

    # Simulate dashboard logic
    print(f"  Simulating dashboard Stock Count processing for ALL stores...")
    sim_results = defaultdict(lambda: {"count": 0, "amount": 0, "prev": 0})
    for td in sc_details:
        txn_id = td.get("transactionId", "")
        txn = sc_by_id.get(txn_id)
        if not txn:
            continue

        txn_date = txn.get("date", "")[:10]
        if not (P2_START <= txn_date <= P2_END):
            continue

        row_type = td.get("rowType", "")
        gl_id = td.get("glAccountId", "")
        gl_num = gl_map.get(gl_id, {}).get("number", "")

        if row_type != "Detail" or not gl_num.startswith("5"):
            continue

        loc_id = td.get("locationId") or txn.get("locationId", "")
        store_num = loc_map.get(loc_id, {}).get("number", "???")
        if store_num not in STORE_NAMES:
            continue

        amount = td.get("amount", 0) or 0
        prev = td.get("previousCountTotal", 0) or 0
        sim_results[store_num]["count"] += 1
        sim_results[store_num]["amount"] += amount
        sim_results[store_num]["prev"] += prev

    print(f"\n  {'Store':<8} {'Name':<20} {'COGS Rows':>10} {'End Inv':>12} {'Begin Inv':>12}")
    print(f"  {'-'*8} {'-'*20} {'-'*10} {'-'*12} {'-'*12}")
    for sn in sorted(STORE_NAMES.keys()):
        r = sim_results.get(sn, {"count": 0, "amount": 0, "prev": 0})
        marker = " <<<< MISSING!" if r["count"] == 0 else ""
        print(f"  {sn:<8} {STORE_NAMES[sn]:<20} {r['count']:>10} ${r['amount']:>11,.2f} ${r['prev']:>11,.2f}{marker}")

    print(f"\n  Done. Check above for root cause of 8008 missing inventory.")


if __name__ == "__main__":
    main()
