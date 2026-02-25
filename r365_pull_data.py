"""
R365 OData Full P&L Data Pull
Pulls all transactions and transaction details, maps to GL accounts and locations,
and outputs data organized by fiscal period (4-4-5 calendar).
"""
import base64
import urllib.request
import json
import os
import calendar
from datetime import datetime, timedelta

OUTDIR = "C:/Users/ascha/OneDrive/Desktop/forage-data"

# Auth
cred = b'foragekitchen\x5chenry@foragekombucha.com:KingJames1!'
auth = base64.b64encode(cred).decode()
HEADERS = {"Authorization": "Basic " + auth, "Accept": "application/json"}
BASE = "https://odata.restaurant365.net/api/v2/views"


def fetch_url(url):
    # Ensure spaces are properly encoded
    url = url.replace(" ", "%20")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def fetch_all_pages(endpoint, filter_str="", page_size=5000):
    """Fetch all results with pagination."""
    all_results = []
    skip = 0
    while True:
        params = f"$top={page_size}&$skip={skip}"
        if filter_str:
            params += "&" + filter_str
        url = f"{BASE}/{endpoint}?{params}"
        data = fetch_url(url)
        batch = data.get("value", [])
        all_results.extend(batch)
        if len(batch) < page_size:
            break
        skip += len(batch)
    return all_results


# ============================================================
# 4-4-5 FISCAL PERIOD CALENDAR
# ============================================================
# 4-4-5 means: P1=4 weeks, P2=4 weeks, P3=5 weeks, repeating
# Each quarter: 4+4+5 = 13 weeks = 91 days
# Full year: 52 weeks = 364 days
# Need to know the fiscal year start date

# Common: Fiscal year starts on the Monday closest to Jan 1
# For Forage Kitchen, let's define based on their P&L data
# From the Excel: 2024 P1 likely starts around Jan 1, 2024
# 2025 P1 likely starts around Dec 30, 2024

# Standard 4-4-5 period definitions
def get_445_periods(fiscal_year_start):
    """Generate 12 periods based on 4-4-5 calendar."""
    periods = []
    current = fiscal_year_start
    pattern = [4, 4, 5, 4, 4, 5, 4, 4, 5, 4, 4, 5]  # weeks per period

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


# Fiscal year starts (Monday nearest to Jan 1)
# 2024: Jan 1 2024 is Monday
# 2025: Dec 30 2024 is Monday
FY_STARTS = {
    2024: datetime(2024, 1, 1),
    2025: datetime(2024, 12, 30),
    2026: datetime(2025, 12, 29),
}


def main():
    # Step 1: Load locations
    print("=" * 60)
    print("  R365 OData P&L Data Pull")
    print("=" * 60)

    print("\n[1/5] Loading locations...")
    locations = fetch_url(f"{BASE}/Location").get("value", [])
    loc_map = {}
    for loc in locations:
        loc_map[loc["locationId"]] = {
            "number": loc.get("locationNumber", ""),
            "name": loc.get("name", "")
        }
        print(f"  {loc.get('locationNumber',''):>6} - {loc.get('name','')}")

    # Step 2: Load GL accounts
    print("\n[2/5] Loading GL accounts...")
    gl_accounts = fetch_url(f"{BASE}/GlAccount?$top=1000").get("value", [])
    gl_map = {}  # glAccountId -> info
    for acct in gl_accounts:
        gl_map[acct["glAccountId"]] = {
            "number": acct.get("glAccountNumber", ""),
            "name": acct.get("name", ""),
            "type": acct.get("glType", "")
        }
    print(f"  Loaded {len(gl_accounts)} GL accounts")

    # Define P&L categories based on GL account numbers
    def categorize_gl(gl_number):
        """Map GL account number to P&L category."""
        if not gl_number:
            return "Other"
        num = gl_number.strip()
        if num.startswith("4"):
            return "Net Sales"
        elif num.startswith("5"):
            return "COGS"
        elif num in ("6110", "6120", "6160", "6170", "6220", "6280"):
            return "Labor"
        elif num in ("6310",):
            return "Rent"
        elif num in ("6410", "6415", "6418", "6427"):
            return "Utilities"
        elif num in ("6430",):
            return "Insurance"
        elif num.startswith("6") or num.startswith("7") or num.startswith("8") or num.startswith("9"):
            return "Other OpEx"
        else:
            return "Other"

    # Step 3: Print fiscal period calendars
    print("\n[3/5] Fiscal period calendars (4-4-5)...")
    for fy_year in [2024, 2025]:
        periods = get_445_periods(FY_STARTS[fy_year])
        print(f"\n  FY {fy_year}:")
        for p in periods:
            print(f"    P{p['period']:>2}: {p['start'].strftime('%Y-%m-%d')} to {p['end'].strftime('%Y-%m-%d')} ({p['weeks']} weeks)")

    # Step 4: Pull transaction details
    # Instead of pulling Transaction then TransactionDetail separately,
    # let's pull TransactionDetail with location filter directly
    # TransactionDetail has locationId and glAccountId but no date
    # We need to join with Transaction for dates
    # Alternative: Pull by SalesEmployee/SalesDetail for sales data

    print("\n[4/5] Pulling financial data...")

    # Approach: Pull transactions month by month, then get their details
    all_txn_details = []  # list of {date, locationId, glAccountId, amount, debit, credit}

    for year in [2024, 2025, 2026]:
        end_m = 2 if year == 2026 else 12
        for month in range(1, end_m + 1):
            last_day = calendar.monthrange(year, month)[1]
            start_str = f"{year}-{month:02d}-01T00:00:00Z"
            end_str = f"{year}-{month:02d}-{last_day}T23:59:59Z"

            # Get transactions for this month (max $top is 5000)
            url = (BASE + "/Transaction?$top=5000"
                   + "&$filter=date%20ge%20" + start_str
                   + "%20and%20date%20le%20" + end_str)
            try:
                txns = fetch_url(url).get("value", [])
                print(f"  {year}-{month:02d}: {len(txns)} transactions", end="")

                # Build txn map: txnId -> {date, locationId}
                txn_map = {}
                for t in txns:
                    txn_map[t["transactionId"]] = {
                        "date": t.get("date", ""),
                        "locationId": t.get("locationId", ""),
                        "type": t.get("type", "")
                    }

                # Now get transaction details for these transactions
                # We need to filter TransactionDetail by transactionId
                # OData doesn't support IN queries easily, so let's pull details
                # filtered by date range indirectly through the transaction link
                # Actually, TransactionDetail doesn't have a date field directly
                # We need a different approach...

                # Store transactions with their metadata
                for txn_id, meta in txn_map.items():
                    all_txn_details.append({
                        "txnId": txn_id,
                        "date": meta["date"],
                        "locationId": meta["locationId"],
                        "type": meta["type"]
                    })

                print(f" -> stored {len(txns)} txn headers")

            except Exception as e:
                print(f"  {year}-{month:02d}: ERROR - {e}")

    print(f"\n  Total transaction headers: {len(all_txn_details)}")

    # Now pull ALL TransactionDetails (paginated)
    # This contains the GL account and amounts
    print("\n  Pulling all transaction details (this may take a while)...")
    all_td = []
    skip = 0
    page = 0
    while True:
        url = f"{BASE}/TransactionDetail?$top=5000&$skip={skip}"
        try:
            data = fetch_url(url)
            batch = data.get("value", [])
            all_td.extend(batch)
            page += 1
            print(f"    Page {page}: {len(batch)} details (total: {len(all_td)})")
            if len(batch) < 5000:
                break
            skip += len(batch)
        except Exception as e:
            print(f"    Page {page + 1}: ERROR - {e}")
            break

    print(f"\n  Total transaction details: {len(all_td)}")

    # Build txn lookup: txnId -> {date, locationId}
    txn_lookup = {}
    for td in all_txn_details:
        txn_lookup[td["txnId"]] = {"date": td["date"], "locationId": td["locationId"]}

    # Step 5: Aggregate into P&L by location and period
    print("\n[5/5] Aggregating P&L data...")

    # Structure: {fy_year: {period: {locationNumber: {category: amount}}}}
    pl_data = {}

    matched = 0
    unmatched = 0

    for td in all_td:
        txn_id = td.get("transactionId", "")
        gl_id = td.get("glAccountId", "")
        amount = td.get("amount", 0) or 0

        # Look up transaction for date and location
        txn_meta = txn_lookup.get(txn_id)
        if not txn_meta:
            unmatched += 1
            continue

        matched += 1
        date_str = txn_meta["date"]
        loc_id = td.get("locationId") or txn_meta["locationId"]

        # Parse date
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except:
            continue

        # Determine fiscal year and period
        fiscal_year = None
        period_num = None
        for fy_year in [2024, 2025, 2026]:
            if fy_year not in FY_STARTS:
                continue
            periods = get_445_periods(FY_STARTS[fy_year])
            for p in periods:
                if p["start"] <= dt.replace(tzinfo=None) <= p["end"]:
                    fiscal_year = fy_year
                    period_num = p["period"]
                    break
            if fiscal_year:
                break

        if not fiscal_year:
            continue

        # Get GL category
        gl_info = gl_map.get(gl_id, {})
        gl_number = gl_info.get("number", "")
        category = categorize_gl(gl_number)

        # Get location number
        loc_info = loc_map.get(loc_id, {})
        loc_number = loc_info.get("number", "Unknown")

        # Aggregate
        if fiscal_year not in pl_data:
            pl_data[fiscal_year] = {}
        if period_num not in pl_data[fiscal_year]:
            pl_data[fiscal_year][period_num] = {}
        if loc_number not in pl_data[fiscal_year][period_num]:
            pl_data[fiscal_year][period_num][loc_number] = {}
        if category not in pl_data[fiscal_year][period_num][loc_number]:
            pl_data[fiscal_year][period_num][loc_number][category] = 0.0

        # For Sales accounts, credit = positive sales (revenue is a credit)
        # For expense accounts, debit = positive expense
        if category == "Net Sales":
            # Sales are credits, so we want the credit amount (positive = revenue)
            pl_data[fiscal_year][period_num][loc_number][category] += abs(amount)
        else:
            pl_data[fiscal_year][period_num][loc_number][category] += abs(amount)

    print(f"  Matched: {matched}, Unmatched: {unmatched}")

    # Print summary
    print("\n=== P&L SUMMARY ===")
    for fy in sorted(pl_data.keys()):
        print(f"\n--- FY {fy} ---")
        for period in sorted(pl_data[fy].keys()):
            print(f"\n  Period {period}:")
            for loc in sorted(pl_data[fy][period].keys()):
                cats = pl_data[fy][period][loc]
                sales = cats.get("Net Sales", 0)
                cogs = cats.get("COGS", 0)
                labor = cats.get("Labor", 0)
                rent = cats.get("Rent", 0)
                utilities = cats.get("Utilities", 0)
                insurance = cats.get("Insurance", 0)
                occupancy = rent + utilities + insurance
                other = cats.get("Other OpEx", 0)
                ebitda = sales - cogs - labor - occupancy - other
                print(f"    {loc:>6}: Sales={sales:>12,.2f}  COGS={cogs:>10,.2f}  Labor={labor:>10,.2f}  Occ={occupancy:>10,.2f}  EBITDA={ebitda:>12,.2f}")

    # Save raw data
    output = {
        "locations": {lid: info for lid, info in loc_map.items()},
        "gl_accounts": {gid: info for gid, info in gl_map.items()},
        "pl_data": {}
    }
    # Convert pl_data keys to strings for JSON
    for fy in pl_data:
        output["pl_data"][str(fy)] = {}
        for p in pl_data[fy]:
            output["pl_data"][str(fy)][str(p)] = pl_data[fy][p]

    with open(os.path.join(OUTDIR, "r365_pl_data.json"), "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved P&L data to r365_pl_data.json")


if __name__ == "__main__":
    main()
