import base64
import urllib.request
import urllib.error
import urllib.parse
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
        body = ""
        try:
            body = e.read().decode('utf-8')[:300]
        except:
            pass
        return e.code, body
    except Exception as e:
        return 0, str(e)

# =============================================
# Get ALL transaction types by fetching more records
# =============================================
print("=" * 80)
print("ALL TRANSACTION TYPES (scanning 2000 records)")
print("=" * 80)

url = f"{BASE}/Transaction?$select=type&$top=2000"
status, data = fetch_json(url)
if status == 200 and isinstance(data, dict):
    records = data.get("value", [])
    types = {}
    for r in records:
        t = r.get("type", "UNKNOWN")
        types[t] = types.get(t, 0) + 1
    print(f"  Scanned {len(records)} transactions")
    print(f"  Types found:")
    for t, count in sorted(types.items(), key=lambda x: -x[1]):
        print(f"    {t}: {count} records")
else:
    print(f"  Status: {status}, data: {str(data)[:300]}")

# =============================================
# Try filtered queries with proper URL encoding
# =============================================
print("\n" + "=" * 80)
print("FILTERED TRANSACTION QUERIES")
print("=" * 80)

filters = [
    ("AP Invoice", "type eq 'AP Invoice'"),
    ("AP Credit Memo", "type eq 'AP Credit Memo'"),
    ("Stock Count", "type eq 'Stock Count'"),
    ("Journal Entry", "type eq 'Journal Entry'"),
    ("AP Payment", "type eq 'AP Payment'"),
    ("Inventory Transfer", "type eq 'Inventory Transfer'"),
    ("Purchase Order", "type eq 'Purchase Order'"),
    ("Waste Log", "type eq 'Waste Log'"),
]

for label, filt in filters:
    encoded = urllib.parse.quote(filt)
    url = f"{BASE}/Transaction?$filter={encoded}&$top=2&$orderby=date desc"
    status, data = fetch_json(url)
    if status == 200 and isinstance(data, dict):
        recs = data.get("value", [])
        print(f"\n  [{label}] - {len(recs)} record(s)")
        for r in recs:
            print(f"    name={r.get('name')}")
            print(f"    date={r.get('date')}, txnNum={r.get('transactionNumber')}")
            print(f"    approved={r.get('isApproved')}, locationName={r.get('locationName')}")
    else:
        print(f"\n  [{label}] - HTTP {status}: {str(data)[:200]}")

# =============================================
# Get TransactionDetail for a specific AP Invoice
# =============================================
print("\n" + "=" * 80)
print("AP INVOICE DETAIL LINES (joined with Transaction)")
print("=" * 80)

# First get an AP Invoice transaction ID
encoded_f = urllib.parse.quote("type eq 'AP Invoice'")
url = f"{BASE}/Transaction?$filter={encoded_f}&$top=1&$orderby=date desc"
status, data = fetch_json(url)
if status == 200 and isinstance(data, dict):
    txns = data.get("value", [])
    if txns:
        txn = txns[0]
        txn_id = txn["transactionId"]
        print(f"  AP Invoice: {txn['name']}")
        print(f"  Date: {txn['date']}, Location: {txn['locationName']}")
        print(f"  transactionId: {txn_id}")
        
        # Now get detail lines for this transaction
        detail_filter = urllib.parse.quote(f"transactionId eq {txn_id}")
        url2 = f"{BASE}/TransactionDetail?$filter={detail_filter}&$top=20"
        status2, data2 = fetch_json(url2)
        if status2 == 200 and isinstance(data2, dict):
            details = data2.get("value", [])
            print(f"\n  Detail lines: {len(details)}")
            for i, d in enumerate(details):
                print(f"\n  Line {i+1}:")
                print(f"    comment: {d.get('comment')}")
                print(f"    amount: {d.get('amount')}, debit: {d.get('debit')}, credit: {d.get('credit')}")
                print(f"    quantity: {d.get('quantity')}, UOM: {d.get('unitOfMeasureName')}")
                print(f"    itemId: {d.get('itemId')}")
                print(f"    glAccountId: {d.get('glAccountId')}")
                print(f"    rowType: {d.get('rowType')}")
        else:
            print(f"  Detail query status: {status2}: {str(data2)[:300]}")
else:
    print(f"  Status: {status}: {str(data)[:300]}")

# =============================================
# Stock Count transaction detail
# =============================================
print("\n" + "=" * 80)
print("STOCK COUNT DETAIL LINES")
print("=" * 80)

encoded_f = urllib.parse.quote("type eq 'Stock Count'")
url = f"{BASE}/Transaction?$filter={encoded_f}&$top=1&$orderby=date desc"
status, data = fetch_json(url)
if status == 200 and isinstance(data, dict):
    txns = data.get("value", [])
    if txns:
        txn = txns[0]
        txn_id = txn["transactionId"]
        print(f"  Stock Count: {txn['name']}")
        print(f"  Date: {txn['date']}, Location: {txn['locationName']}")
        
        detail_filter = urllib.parse.quote(f"transactionId eq {txn_id}")
        url2 = f"{BASE}/TransactionDetail?$filter={detail_filter}&$top=10"
        status2, data2 = fetch_json(url2)
        if status2 == 200 and isinstance(data2, dict):
            details = data2.get("value", [])
            print(f"  Detail lines: {len(details)}")
            for i, d in enumerate(details[:5]):
                print(f"\n  Line {i+1}:")
                print(f"    comment: {d.get('comment')}")
                print(f"    amount: {d.get('amount')}, quantity: {d.get('quantity')}")
                print(f"    previousCountTotal: {d.get('previousCountTotal')}")
                print(f"    adjustment: {d.get('adjustment')}")
                print(f"    UOM: {d.get('unitOfMeasureName')}")
                print(f"    itemId: {d.get('itemId')}")
        else:
            print(f"  Detail query status: {status2}")
else:
    print(f"  No Stock Count transactions found. Status: {status}")

# =============================================
# Get total record counts
# =============================================
print("\n" + "=" * 80)
print("RECORD COUNTS")
print("=" * 80)

for entity in ["Transaction", "TransactionDetail", "Item", "GlAccount", "Location", "Company"]:
    url = f"{BASE}/{entity}?$count=true&$top=0"
    status, data = fetch_json(url)
    if status == 200 and isinstance(data, dict):
        count = data.get("@odata.count", "N/A")
        print(f"  {entity}: {count} total records")
    else:
        # Try alternate count approach
        url2 = f"{BASE}/{entity}/$count"
        status2, data2 = fetch_json(url2)
        print(f"  {entity}: count not available (tried $count=true -> {status}, /$count -> {status2})")

