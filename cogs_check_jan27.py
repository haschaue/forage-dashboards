"""Check Jan 27 stock counts - do they have previousCountTotal populated?
If so, we can use that as the beginning inventory.
"""
import base64, urllib.request, json, time
from collections import defaultdict

cred = b'foragekitchen\x5chenry@foragekombucha.com:KingJames1!'
auth = base64.b64encode(cred).decode()
HEADERS = {"Authorization": "Basic " + auth, "Accept": "application/json"}
BASE = "https://odata.restaurant365.net/api/v2/views"

STORE_NAMES = {
    "8001": "State Street", "8002": "Hilldale", "8003": "Monona",
    "8004": "Old Sauk", "8005": "Champaign", "8006": "Whitefish Bay",
    "8007": "Sun Prairie", "8008": "Pewaukee", "8009": "MKE Public Market",
}


def fetch(url):
    url = url.replace(" ", "%20")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


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


locations = fetch(BASE + "/Location").get("value", [])
loc_map = {l["locationId"]: l.get("locationNumber", "") for l in locations}
gl = fetch(BASE + "/GlAccount?$top=1000").get("value", [])
gl_map = {a["glAccountId"]: a.get("glAccountNumber", "") for a in gl}

# Get Jan stock counts
print("Pulling Jan 2026 Stock Count transactions...")
url = (f"{BASE}/Transaction?$top=5000"
       f"&$filter=type eq 'Stock Count'"
       f" and date ge 2026-01-01T00:00:00Z"
       f" and date le 2026-01-31T23:59:59Z")
jan_sc = fetch(url).get("value", [])
print(f"Found {len(jan_sc)} Jan stock counts\n")

for t in sorted(jan_sc, key=lambda x: (x.get("date", ""), loc_map.get(x.get("locationId", ""), ""))):
    sn = loc_map.get(t.get("locationId", ""), "?")
    print(f"  {t['date'][:10]} | {sn} {STORE_NAMES.get(sn, '')} | {t.get('name', '')[:55]}")

# Pull details
print("\nPulling all transaction details...")
all_td = fetch_all(BASE + "/TransactionDetail")
print(f"Total: {len(all_td)}")

jan_sc_ids = {t["transactionId"]: t for t in jan_sc}
jan_details = [d for d in all_td if d.get("transactionId", "") in jan_sc_ids]
print(f"Jan stock count details: {len(jan_details)}")

# Organize by store
by_store = defaultdict(list)
for d in jan_details:
    txn = jan_sc_ids.get(d.get("transactionId", ""), {})
    loc_id = d.get("locationId") or txn.get("locationId", "")
    sn = loc_map.get(loc_id, "?")
    by_store[sn].append(d)

print("\n" + "=" * 80)
print("JAN 27/28 STOCK COUNTS - DETAIL ANALYSIS")
print("=" * 80)

ACTUAL_COGS = {
    "8001": 15555.30, "8002": 24151.52, "8003": 27176.67,
    "8004": 28453.66, "8005": 6712.20, "8006": 27856.49,
    "8007": 27116.83, "8008": 15229.31, "8009": 20097.30,
}

for sn in sorted(STORE_NAMES.keys()):
    details = by_store.get(sn, [])
    if not details:
        print(f"\n{sn} {STORE_NAMES[sn]}: NO DETAIL LINES")
        continue

    # Only 5xxx GL (COGS) Detail rows
    cogs_details = [d for d in details
                    if d.get("rowType") == "Detail"
                    and gl_map.get(d.get("glAccountId", ""), "").startswith("5")]

    total_amount = sum(d.get("amount", 0) or 0 for d in cogs_details)
    total_prev = sum(d.get("previousCountTotal", 0) or 0 for d in cogs_details)
    total_adj = sum(d.get("adjustment", 0) or 0 for d in cogs_details)
    total_debit = sum(d.get("debit", 0) or 0 for d in cogs_details)
    total_credit = sum(d.get("credit", 0) or 0 for d in cogs_details)

    actual = ACTUAL_COGS.get(sn, 0)

    # COGS from inventory method:
    # Begin Inv (previousCountTotal) + Purchases - End Inv (amount) = COGS
    # Or: previousCountTotal - amount + Purchases = COGS
    # Inventory decrease = COGS consumed from shelf (without purchases)
    # adjustment = amount - previousCountTotal (positive = inventory grew)
    inv_decrease = total_prev - total_amount  # positive = consumed

    print(f"\n{sn} {STORE_NAMES[sn]}:")
    print(f"  COGS Detail lines: {len(cogs_details)}")
    print(f"  Ending Inv (amount):        ${total_amount:>12,.2f}")
    print(f"  Beginning Inv (prevCount):   ${total_prev:>12,.2f}")
    print(f"  Adjustment:                  ${total_adj:>12,.2f}")
    print(f"  Inventory decrease:          ${inv_decrease:>12,.2f}")
    print(f"  Debit total:                 ${total_debit:>12,.2f}")
    print(f"  Credit total:                ${total_credit:>12,.2f}")
    print(f"  Actual P&L COGS:             ${actual:>12,.2f}")
    print(f"  Implied purchases needed:    ${actual - inv_decrease:>12,.2f}")

# Now the key calculation
print("\n\n" + "=" * 80)
print("SUMMARY: INVENTORY-BASED COGS CALCULATION")
print("=" * 80)
print(f"\n  Using: COGS = Beginning Inventory - Ending Inventory + Purchases")
print(f"  Where: Beginning = previousCountTotal, Ending = amount from Jan 27/28 count")
print(f"\n  {'STORE':<25} {'Begin Inv':>12} {'End Inv':>12} {'Consumed':>12} "
      f"{'Actual COGS':>12} {'Gap=Purch':>12}")
print("-" * 90)

grand_begin = 0
grand_end = 0
grand_consumed = 0
grand_actual = 0

for sn in sorted(STORE_NAMES.keys()):
    details = by_store.get(sn, [])
    cogs_details = [d for d in details
                    if d.get("rowType") == "Detail"
                    and gl_map.get(d.get("glAccountId", ""), "").startswith("5")]

    begin = sum(d.get("previousCountTotal", 0) or 0 for d in cogs_details)
    end = sum(d.get("amount", 0) or 0 for d in cogs_details)
    consumed = begin - end
    actual = ACTUAL_COGS.get(sn, 0)
    gap = actual - consumed

    grand_begin += begin
    grand_end += end
    grand_consumed += consumed
    grand_actual += actual

    print(f"  {sn + ' ' + STORE_NAMES[sn]:<25} "
          f"${begin:>10,.2f} ${end:>10,.2f} ${consumed:>10,.2f} "
          f"${actual:>10,.2f} ${gap:>10,.2f}")

grand_gap = grand_actual - grand_consumed
print("-" * 90)
print(f"  {'TOTAL':<25} "
      f"${grand_begin:>10,.2f} ${grand_end:>10,.2f} ${grand_consumed:>10,.2f} "
      f"${grand_actual:>10,.2f} ${grand_gap:>10,.2f}")

print(f"\n  Beginning Inventory (all stores): ${grand_begin:,.2f}")
print(f"  Ending Inventory (all stores):    ${grand_end:,.2f}")
print(f"  Inventory Consumed (shelf draw):  ${grand_consumed:,.2f}")
print(f"  Actual P&L COGS:                  ${grand_actual:,.2f}")
print(f"  Gap (= Total Purchases during P1):${grand_gap:,.2f}")
print(f"\n  Validation: Begin(${grand_begin:,.0f}) + Purchases(${grand_gap:,.0f}) "
      f"- End(${grand_end:,.0f}) = ${grand_begin + grand_gap - grand_end:,.0f} "
      f"(should = Actual COGS ${grand_actual:,.0f})")
