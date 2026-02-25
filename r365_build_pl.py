"""
R365 OData - Full P&L Builder
Uses SalesEmployee for sales, LaborDetail for labor costs,
and Transaction/TransactionDetail for COGS and other expenses.
Organizes by 4-4-5 fiscal periods.
"""
import base64
import urllib.request
import json
import os
import calendar
from datetime import datetime, timedelta
from collections import defaultdict

OUTDIR = "C:/Users/ascha/OneDrive/Desktop/forage-data"

# Auth
cred = b'foragekitchen\x5chenry@foragekombucha.com:KingJames1!'
auth = base64.b64encode(cred).decode()
HEADERS = {"Authorization": "Basic " + auth, "Accept": "application/json"}
BASE = "https://odata.restaurant365.net/api/v2/views"


def fetch(url):
    url = url.replace(" ", "%20")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


# ============================================================
# 4-4-5 FISCAL PERIOD CALENDAR
# ============================================================
def get_445_periods(fiscal_year_start):
    periods = []
    current = fiscal_year_start
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


# Fiscal year starts
FY_STARTS = {
    2024: datetime(2024, 1, 1),
    2025: datetime(2024, 12, 30),
    2026: datetime(2025, 12, 29),
}

# Build period lookup
ALL_PERIODS = {}
for fy, start in FY_STARTS.items():
    ALL_PERIODS[fy] = get_445_periods(start)


def date_to_fy_period(dt):
    """Given a datetime, return (fiscal_year, period_number) or None."""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00")).replace(tzinfo=None)
        except:
            return None
    for fy in sorted(ALL_PERIODS.keys()):
        for p in ALL_PERIODS[fy]:
            if p["start"] <= dt <= p["end"]:
                return (fy, p["period"])
    return None


def main():
    print("=" * 60)
    print("  R365 OData - Full P&L Builder")
    print("=" * 60)

    # --------------------------------------------------------
    # Step 1: Load reference data
    # --------------------------------------------------------
    print("\n[1/6] Loading locations...")
    locations = fetch(BASE + "/Location").get("value", [])
    loc_id_to_number = {}
    loc_id_to_name = {}
    for loc in sorted(locations, key=lambda x: x.get("locationNumber", "")):
        lid = loc["locationId"]
        num = loc.get("locationNumber", "")
        name = loc.get("name", "")
        loc_id_to_number[lid] = num
        loc_id_to_name[lid] = name
        print(f"  {num:>6} - {name}")

    print("\n[2/6] Loading GL accounts...")
    gl_accounts = fetch(BASE + "/GlAccount?$top=1000").get("value", [])
    gl_id_to_info = {}
    for acct in gl_accounts:
        gl_id_to_info[acct["glAccountId"]] = {
            "number": acct.get("glAccountNumber", ""),
            "name": acct.get("name", ""),
            "type": acct.get("glType", "")
        }
    print(f"  Loaded {len(gl_accounts)} GL accounts")

    # Print fiscal periods
    print("\n[3/6] Fiscal periods (4-4-5)...")
    for fy in sorted(ALL_PERIODS.keys()):
        print(f"\n  FY {fy}:")
        for p in ALL_PERIODS[fy]:
            print(f"    P{p['period']:>2}: {p['start'].strftime('%Y-%m-%d')} to {p['end'].strftime('%Y-%m-%d')} ({p['weeks']}w)")

    # --------------------------------------------------------
    # Step 2: Pull Sales data from SalesEmployee
    # --------------------------------------------------------
    print("\n[4/6] Pulling sales data (SalesEmployee)...")

    # Structure: {(fy, period, loc_number): {"net_sales": X, "gross_sales": X, "guests": X}}
    sales_data = defaultdict(lambda: {"net_sales": 0, "gross_sales": 0, "guests": 0})

    total_sales_records = 0
    for year in [2024, 2025, 2026]:
        end_m = 2 if year == 2026 else 12
        for month in range(1, end_m + 1):
            last_day = calendar.monthrange(year, month)[1]
            start_str = f"{year}-{month:02d}-01T00:00:00Z"
            end_str = f"{year}-{month:02d}-{last_day}T23:59:59Z"

            skip = 0
            month_count = 0
            while True:
                url = (BASE + f"/SalesEmployee?$top=5000&$skip={skip}"
                       + f"&$filter=date%20ge%20{start_str}%20and%20date%20le%20{end_str}")
                try:
                    data = fetch(url)
                    records = data.get("value", [])
                    for r in records:
                        loc_id = r.get("location", "")
                        loc_num = loc_id_to_number.get(loc_id, "Unknown")
                        date_str = r.get("date", "")
                        fp = date_to_fy_period(date_str)
                        if fp is None:
                            continue
                        fy, period = fp
                        key = (fy, period, loc_num)
                        sales_data[key]["net_sales"] += r.get("netSales", 0) or 0
                        sales_data[key]["gross_sales"] += r.get("grossSales", 0) or 0
                        sales_data[key]["guests"] += r.get("numberofGuests", 0) or 0

                    month_count += len(records)
                    if len(records) < 5000:
                        break
                    skip += 5000
                except Exception as e:
                    print(f"  {year}-{month:02d} skip={skip}: ERROR - {e}")
                    break

            total_sales_records += month_count
            print(f"  {year}-{month:02d}: {month_count} sales records")

    print(f"  Total sales records: {total_sales_records}")

    # --------------------------------------------------------
    # Step 3: Pull Labor data from LaborDetail
    # --------------------------------------------------------
    print("\n[5/6] Pulling labor data (LaborDetail)...")

    # Structure: {(fy, period, loc_number): {"labor_cost": X, "labor_hours": X}}
    labor_data = defaultdict(lambda: {"labor_cost": 0, "labor_hours": 0})

    total_labor_records = 0
    for year in [2024, 2025, 2026]:
        end_m = 2 if year == 2026 else 12
        for month in range(1, end_m + 1):
            last_day = calendar.monthrange(year, month)[1]
            start_str = f"{year}-{month:02d}-01T00:00:00Z"
            end_str = f"{year}-{month:02d}-{last_day}T23:59:59Z"

            skip = 0
            month_count = 0
            while True:
                url = (BASE + f"/LaborDetail?$top=5000&$skip={skip}"
                       + f"&$filter=dateWorked%20ge%20{start_str}%20and%20dateWorked%20le%20{end_str}")
                try:
                    data = fetch(url)
                    records = data.get("value", [])
                    for r in records:
                        loc_name = r.get("location", "")
                        # LaborDetail has location name, not ID - need to map
                        loc_num = "Unknown"
                        loc_id = r.get("location_ID", "")
                        if loc_id:
                            loc_num = loc_id_to_number.get(loc_id, "Unknown")
                        else:
                            # Match by name
                            for lid, name in loc_id_to_name.items():
                                if name.strip().lower() == loc_name.strip().lower():
                                    loc_num = loc_id_to_number[lid]
                                    break

                        date_str = r.get("dateWorked", "")
                        fp = date_to_fy_period(date_str)
                        if fp is None:
                            continue
                        fy, period = fp
                        key = (fy, period, loc_num)
                        labor_data[key]["labor_cost"] += r.get("total", 0) or 0
                        labor_data[key]["labor_hours"] += r.get("hours", 0) or 0

                    month_count += len(records)
                    if len(records) < 5000:
                        break
                    skip += 5000
                except Exception as e:
                    print(f"  {year}-{month:02d} skip={skip}: ERROR - {e}")
                    break

            total_labor_records += month_count
            print(f"  {year}-{month:02d}: {month_count} labor records")

    print(f"  Total labor records: {total_labor_records}")

    # --------------------------------------------------------
    # Step 4: Pull COGS and other expenses from Transactions
    # --------------------------------------------------------
    print("\n[6/6] Pulling COGS and expenses (Transaction + TransactionDetail)...")

    # First pull all transactions to get dates and locations
    txn_meta = {}  # txnId -> {date, locationId}
    total_txns = 0

    for year in [2024, 2025, 2026]:
        end_m = 2 if year == 2026 else 12
        for month in range(1, end_m + 1):
            last_day = calendar.monthrange(year, month)[1]
            start_str = f"{year}-{month:02d}-01T00:00:00Z"
            end_str = f"{year}-{month:02d}-{last_day}T23:59:59Z"

            url = (BASE + "/Transaction?$top=5000"
                   + f"&$filter=date%20ge%20{start_str}%20and%20date%20le%20{end_str}")
            try:
                data = fetch(url)
                txns = data.get("value", [])
                for t in txns:
                    txn_meta[t["transactionId"]] = {
                        "date": t.get("date", ""),
                        "locationId": t.get("locationId", "")
                    }
                total_txns += len(txns)
                print(f"  {year}-{month:02d}: {len(txns)} transactions")
            except Exception as e:
                print(f"  {year}-{month:02d}: ERROR - {e}")

    print(f"  Total transaction headers: {total_txns}")

    # Now pull all TransactionDetails
    print("  Pulling transaction details...")
    all_td = []
    skip = 0
    page = 0
    while True:
        url = f"{BASE}/TransactionDetail?$top=5000&$skip={skip}"
        try:
            data = fetch(url)
            batch = data.get("value", [])
            all_td.extend(batch)
            page += 1
            if page % 10 == 0 or len(batch) < 5000:
                print(f"    Page {page}: total {len(all_td)} details so far")
            if len(batch) < 5000:
                break
            skip += 5000
        except Exception as e:
            print(f"    Page {page + 1}: ERROR - {e}")
            break

    print(f"  Total transaction details: {len(all_td)}")

    # Categorize by GL account
    def gl_category(gl_id):
        info = gl_id_to_info.get(gl_id, {})
        num = info.get("number", "")
        if not num:
            return "Other"
        if num.startswith("5"):  # COGS
            return "COGS"
        elif num in ("6310",):  # Rent
            return "Rent"
        elif num in ("6410", "6415", "6418", "6427"):  # Utilities
            return "Utilities"
        elif num in ("6430",):  # Insurance
            return "Insurance"
        elif num.startswith("6") or num.startswith("7") or num.startswith("8") or num.startswith("9"):
            return "Other_OpEx"
        else:
            return "Other"

    # Aggregate expense data from TransactionDetails
    expense_data = defaultdict(lambda: defaultdict(float))  # (fy,period,loc) -> {cat: amt}

    matched = 0
    unmatched = 0
    for td in all_td:
        txn_id = td.get("transactionId", "")
        meta = txn_meta.get(txn_id)
        if not meta:
            unmatched += 1
            continue
        matched += 1

        gl_id = td.get("glAccountId", "")
        cat = gl_category(gl_id)
        if cat in ("Other",):  # Skip non-expense items
            continue

        loc_id = td.get("locationId") or meta["locationId"]
        loc_num = loc_id_to_number.get(loc_id, "Unknown")
        fp = date_to_fy_period(meta["date"])
        if fp is None:
            continue
        fy, period = fp
        key = (fy, period, loc_num)

        # Use absolute value of amount for expenses
        amount = abs(td.get("amount", 0) or 0)
        debit = td.get("debit", 0) or 0

        # For expenses, debit is the cost
        if debit > 0:
            expense_data[key][cat] += debit

    print(f"  Matched: {matched}, Unmatched: {unmatched}")

    # --------------------------------------------------------
    # Combine all data
    # --------------------------------------------------------
    print("\n" + "=" * 60)
    print("  COMBINED P&L RESULTS")
    print("=" * 60)

    # Get all unique (fy, period, loc) keys
    all_keys = set(sales_data.keys()) | set(labor_data.keys()) | set(expense_data.keys())

    # Organize output
    output = {}  # {fy: {period: {loc: {metric: value}}}}
    for key in all_keys:
        fy, period, loc = key
        if fy not in output:
            output[fy] = {}
        if period not in output[fy]:
            output[fy][period] = {}
        if loc not in output[fy][period]:
            output[fy][period][loc] = {}

        sd = sales_data.get(key, {})
        ld = labor_data.get(key, {})
        ed = expense_data.get(key, {})

        net_sales = sd.get("net_sales", 0)
        gross_sales = sd.get("gross_sales", 0)
        guests = sd.get("guests", 0)
        labor_cost = ld.get("labor_cost", 0)
        labor_hours = ld.get("labor_hours", 0)
        cogs = ed.get("COGS", 0)
        rent = ed.get("Rent", 0)
        utilities = ed.get("Utilities", 0)
        insurance = ed.get("Insurance", 0)
        other_opex = ed.get("Other_OpEx", 0)
        occupancy = rent + utilities + insurance
        total_expenses = cogs + labor_cost + occupancy + other_opex
        ebitda = net_sales - total_expenses

        output[fy][period][loc] = {
            "Net Sales": round(net_sales, 2),
            "Gross Sales": round(gross_sales, 2),
            "Guests": guests,
            "COGS": round(cogs, 2),
            "Labor": round(labor_cost, 2),
            "Labor Hours": round(labor_hours, 2),
            "Rent": round(rent, 2),
            "Utilities": round(utilities, 2),
            "Insurance": round(insurance, 2),
            "Total Occupancy": round(occupancy, 2),
            "Other OpEx": round(other_opex, 2),
            "EBITDA": round(ebitda, 2),
            "Labor %": round(labor_cost / net_sales * 100, 1) if net_sales > 0 else 0,
            "COGS %": round(cogs / net_sales * 100, 1) if net_sales > 0 else 0,
            "Occupancy %": round(occupancy / net_sales * 100, 1) if net_sales > 0 else 0,
            "EBITDA %": round(ebitda / net_sales * 100, 1) if net_sales > 0 else 0,
        }

    # Print summary
    for fy in sorted(output.keys()):
        print(f"\n{'='*60}")
        print(f"  FISCAL YEAR {fy}")
        print(f"{'='*60}")
        for period in sorted(output[fy].keys()):
            print(f"\n  --- Period {period} ---")
            for loc in sorted(output[fy][period].keys()):
                d = output[fy][period][loc]
                if d["Net Sales"] > 0 or d["COGS"] > 0 or d["Labor"] > 0:
                    print(f"    {loc:>6}: Net Sales={d['Net Sales']:>12,.2f}"
                          f"  COGS={d['COGS']:>10,.2f} ({d['COGS %']}%)"
                          f"  Labor={d['Labor']:>10,.2f} ({d['Labor %']}%)"
                          f"  Occ={d['Total Occupancy']:>10,.2f} ({d['Occupancy %']}%)"
                          f"  EBITDA={d['EBITDA']:>12,.2f} ({d['EBITDA %']}%)")

    # Save to JSON
    # Convert keys to strings for JSON
    json_output = {
        "generated": datetime.now().isoformat(),
        "fiscal_periods": {},
        "locations": {lid: {"number": loc_id_to_number[lid], "name": loc_id_to_name[lid]} for lid in loc_id_to_number},
        "pl_data": {}
    }

    for fy in ALL_PERIODS:
        json_output["fiscal_periods"][str(fy)] = [
            {"period": p["period"], "start": p["start"].strftime("%Y-%m-%d"), "end": p["end"].strftime("%Y-%m-%d"), "weeks": p["weeks"]}
            for p in ALL_PERIODS[fy]
        ]

    for fy in output:
        json_output["pl_data"][str(fy)] = {}
        for period in output[fy]:
            json_output["pl_data"][str(fy)][str(period)] = output[fy][period]

    outpath = os.path.join(OUTDIR, "r365_pl_data.json")
    with open(outpath, "w") as f:
        json.dump(json_output, f, indent=2)
    print(f"\n\nSaved complete P&L data to {outpath}")


if __name__ == "__main__":
    main()
