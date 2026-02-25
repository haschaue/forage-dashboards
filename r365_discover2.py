import base64
import urllib.request
import urllib.error
import json
import ssl

cred = b'foragekitchen\henry@foragekombucha.com:KingJames1!'
auth = base64.b64encode(cred).decode()
HEADERS = {"Authorization": "Basic " + auth, "Accept": "application/json"}
BASE = "https://odata.restaurant365.net/api/v2/views"
ctx = ssl.create_default_context()

def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=60, context=ctx)
        return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)

# =============================================
# Part 1: Test remaining entity sets from metadata
# =============================================
remaining = [
    "Company", "Employee", "EmployeeLite", "EmployeeLiteDto",
    "EntityDeleted", "GlAccount", "JobTitle", "LaborDetail",
    "MenuItemCategory", "PayrollSummary", "PosEmployee",
    "SalesDetail", "SalesEmployee", "SalesEmployeeTax", "SalesPayment"
]

print("=" * 80)
print("PART 1: Testing remaining entity sets from $metadata")
print("=" * 80)

for ep in remaining:
    url = f"{BASE}/{ep}?$top=2"
    status, data = fetch_json(url)
    if status == 200 and data:
        records = data.get("value", [])
        print(f"\n  {ep}: OK ({len(records)} records)")
        if records:
            print(f"    Fields: {list(records[0].keys())}")
    else:
        print(f"\n  {ep}: HTTP {status}")

# =============================================
# Part 2: Explore Transaction types
# =============================================
print("\n" + "=" * 80)
print("PART 2: Transaction types available")
print("=" * 80)

# Get distinct transaction types
url = f"{BASE}/Transaction?$top=500&$select=type"
status, data = fetch_json(url)
if status == 200 and data:
    types = set(r.get("type", "") for r in data.get("value", []))
    print(f"  Transaction types found (from first 500 records):")
    for t in sorted(types):
        print(f"    - {t}")

# =============================================
# Part 3: Filter AP Invoice transactions
# =============================================
print("\n" + "=" * 80)
print("PART 3: AP Invoice transactions (sample)")
print("=" * 80)

url = f"{BASE}/Transaction?$filter=type eq 'AP Invoice'&$top=3"
status, data = fetch_json(url)
if status == 200 and data:
    records = data.get("value", [])
    print(f"  Found {len(records)} AP Invoice transaction(s)")
    for i, r in enumerate(records):
        print(f"\n  Record {i+1}:")
        for k, v in r.items():
            print(f"    {k}: {v}")
else:
    print(f"  Status: {status}")
    # Try alternate filter syntax
    url2 = f"{BASE}/Transaction?$filter=contains(type,'AP')&$top=3"
    status2, data2 = fetch_json(url2)
    print(f"  Alternate filter status: {status2}")
    if status2 == 200 and data2:
        for r in data2.get("value", []):
            print(f"    type={r.get('type')}, name={r.get('name')}")

# =============================================
# Part 4: AP Invoice Detail lines
# =============================================
print("\n" + "=" * 80)
print("PART 4: TransactionDetail with item data (AP lines)")
print("=" * 80)

url = f"{BASE}/TransactionDetail?$filter=itemId ne null&$top=5"
status, data = fetch_json(url)
if status == 200 and data:
    records = data.get("value", [])
    print(f"  Found {len(records)} detail records with items")
    for i, r in enumerate(records):
        print(f"\n  Record {i+1}:")
        for k, v in r.items():
            print(f"    {k}: {v}")
else:
    print(f"  Filter status: {status}")
    # Try without filter, just look for ones with items
    url2 = f"{BASE}/TransactionDetail?$top=20"
    status2, data2 = fetch_json(url2)
    if status2 == 200 and data2:
        records = data2.get("value", [])
        with_items = [r for r in records if r.get("itemId")]
        print(f"  From top 20 details, {len(with_items)} have itemId")
        if with_items:
            print(f"\n  Sample detail with item:")
            for k, v in with_items[0].items():
                print(f"    {k}: {v}")

# =============================================
# Part 5: Check for Inventory Count transactions
# =============================================
print("\n" + "=" * 80)
print("PART 5: Looking for Inventory-related transaction types")
print("=" * 80)

# Grab more transaction types
for txn_type in ["Inventory Count", "Inventory Transfer", "AP Credit Memo", "Purchase Order", "Waste Log"]:
    url = f"{BASE}/Transaction?$filter=type eq '{txn_type}'&$top=1"
    status, data = fetch_json(url)
    if status == 200 and data:
        recs = data.get("value", [])
        print(f"  '{txn_type}': {len(recs)} record(s) returned")
        if recs:
            print(f"    Sample: {recs[0].get('name', 'N/A')}, date={recs[0].get('date', 'N/A')}")
    else:
        print(f"  '{txn_type}': HTTP {status}")

# =============================================
# Part 6: Full metadata field details for key entities
# =============================================
print("\n" + "=" * 80)
print("PART 6: Metadata - field definitions for Transaction and TransactionDetail")
print("=" * 80)

import re
req = urllib.request.Request(BASE + "/$metadata", headers={
    "Authorization": "Basic " + auth,
    "Accept": "application/xml"
})
try:
    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    xml = resp.read().decode('utf-8')
    
    # Extract properties for each EntityType
    for etype in ["Transaction", "TransactionDetail", "Item", "GlAccount"]:
        pattern = rf'<EntityType Name="{etype}">(.*?)</EntityType>'
        match = re.search(pattern, xml, re.DOTALL)
        if match:
            props = re.findall(r'<Property Name="(\w+)" Type="([^"]+)"', match.group(1))
            print(f"\n  {etype} fields:")
            for pname, ptype in props:
                print(f"    {pname}: {ptype}")
except Exception as e:
    print(f"  Error: {e}")

# =============================================
# Part 7: Item endpoint - get more items for inventory context
# =============================================
print("\n" + "=" * 80)
print("PART 7: Item records (inventory items)")
print("=" * 80)

url = f"{BASE}/Item?$top=10"
status, data = fetch_json(url)
if status == 200 and data:
    records = data.get("value", [])
    print(f"  Found {len(records)} items")
    for r in records[:5]:
        print(f"    {r.get('name', 'N/A')} | number={r.get('itemNumber')} | cat1={r.get('category1')} | cat2={r.get('category2')}")

