"""Quick check: Why are Dec 30 stock counts showing $0 for most stores?
The stock count transactions exist (we saw them), but the detail amounts are 0.
Let's look at the raw detail data.
"""
import base64, urllib.request, json, time
from collections import defaultdict

cred = b'foragekitchen\x5chenry@foragekombucha.com:KingJames1!'
auth = base64.b64encode(cred).decode()
HEADERS = {"Authorization": "Basic " + auth, "Accept": "application/json"}
BASE = "https://odata.restaurant365.net/api/v2/views"


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


# Get locations
locations = fetch(BASE + "/Location").get("value", [])
loc_map = {l["locationId"]: l.get("locationNumber", "") for l in locations}
loc_names = {l["locationId"]: l.get("name", "") for l in locations}

# Get GL
gl = fetch(BASE + "/GlAccount?$top=1000").get("value", [])
gl_map = {a["glAccountId"]: a.get("glAccountNumber", "") for a in gl}

# Pull Dec stock count transactions
print("Pulling Dec 2025 Stock Count transactions...")
url = (f"{BASE}/Transaction?$top=5000"
       f"&$filter=type eq 'Stock Count'"
       f" and date ge 2025-12-01T00:00:00Z"
       f" and date le 2025-12-31T23:59:59Z")
dec_sc = fetch(url).get("value", [])
print(f"Found {len(dec_sc)} Dec stock counts:\n")

for t in sorted(dec_sc, key=lambda x: x.get("date", "")):
    loc = loc_map.get(t.get("locationId", ""), "?")
    print(f"  {t['date'][:10]} | {loc} | {t.get('name', '')[:60]} | ID: {t['transactionId'][:8]}...")

# Pull ALL transaction details
print("\nPulling all transaction details...")
all_td = fetch_all(BASE + "/TransactionDetail")
print(f"Total: {len(all_td)}")

# Filter to Dec 30 stock count IDs
dec_sc_ids = {t["transactionId"] for t in dec_sc if "2025-12-30" in t.get("date", "")}
dec30_details = [d for d in all_td if d.get("transactionId", "") in dec_sc_ids]
print(f"\nDec 30 stock count details: {len(dec30_details)}")

# Show sample by store
by_store = defaultdict(list)
for d in dec30_details:
    loc_id = d.get("locationId", "")
    sn = loc_map.get(loc_id, "?")
    by_store[sn].append(d)

for sn in sorted(by_store.keys()):
    details = by_store[sn]
    print(f"\n{sn}: {len(details)} detail lines")

    # Count by row type
    by_type = defaultdict(int)
    total_amt = 0
    total_debit = 0
    total_credit = 0
    total_qty = 0
    total_prev = 0
    total_adj = 0
    cogs_count = 0

    for d in details:
        rt = d.get("rowType", "?")
        by_type[rt] += 1
        gl_num = gl_map.get(d.get("glAccountId", ""), "")

        if rt == "Detail" and gl_num.startswith("5"):
            cogs_count += 1
            total_amt += d.get("amount", 0) or 0
            total_debit += d.get("debit", 0) or 0
            total_credit += d.get("credit", 0) or 0
            total_qty += d.get("quantity", 0) or 0
            total_prev += d.get("previousCountTotal", 0) or 0
            total_adj += d.get("adjustment", 0) or 0

    print(f"  Row types: {dict(by_type)}")
    print(f"  COGS (5xxx) Detail lines: {cogs_count}")
    print(f"  Total amount: ${total_amt:,.2f}")
    print(f"  Total debit: ${total_debit:,.2f}")
    print(f"  Total credit: ${total_credit:,.2f}")
    print(f"  Total quantity: {total_qty:,.2f}")
    print(f"  Total previousCountTotal: ${total_prev:,.2f}")
    print(f"  Total adjustment: ${total_adj:,.2f}")

    # Show first 3 detail lines raw
    cogs_details = [d for d in details
                    if d.get("rowType") == "Detail"
                    and gl_map.get(d.get("glAccountId", ""), "").startswith("5")]
    if cogs_details:
        print(f"  Sample lines:")
        for d in cogs_details[:3]:
            print(f"    amt={d.get('amount',0):.2f} debit={d.get('debit',0):.2f} "
                  f"credit={d.get('credit',0):.2f} qty={d.get('quantity',0):.2f} "
                  f"prev={d.get('previousCountTotal',0):.2f} adj={d.get('adjustment',0):.2f} "
                  f"comment={d.get('comment','')[:30]}")
