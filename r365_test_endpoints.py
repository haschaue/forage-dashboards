"""Test R365 OData endpoints for sales, labor, and transaction data."""
import base64
import urllib.request
import json

cred = b'foragekitchen\x5chenry@foragekombucha.com:KingJames1!'
auth = base64.b64encode(cred).decode()
HEADERS = {"Authorization": "Basic " + auth, "Accept": "application/json"}
BASE = "https://odata.restaurant365.net/api/v2/views"


def fetch(url):
    url = url.replace(" ", "%20")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


# Test SalesDetail with date filter
print("=== SalesDetail (Jan 2025) ===")
try:
    url = (BASE + "/SalesDetail?$top=5"
           + "&$filter=date%20ge%202025-01-01T00:00:00Z%20and%20date%20le%202025-01-31T23:59:59Z")
    data = fetch(url)
    records = data.get("value", [])
    print(f"  Found {len(records)} records (showing first 5)")
    for s in records[:5]:
        print(f"  Date: {str(s.get('date',''))[:10]} | Amt: {s.get('amount',0):>10,.2f}"
              f" | Menu: {s.get('menuitem','')} | Cat: {s.get('category','')}"
              f" | Loc: {str(s.get('location',''))[:12]}...")
except Exception as e:
    print(f"  ERROR: {e}")

# Test SalesEmployee with date filter
print("\n=== SalesEmployee (Jan 2025) ===")
try:
    url = (BASE + "/SalesEmployee?$top=5"
           + "&$filter=date%20ge%202025-01-01T00:00:00Z%20and%20date%20le%202025-01-31T23:59:59Z")
    data = fetch(url)
    records = data.get("value", [])
    print(f"  Found {len(records)} records (showing first 5)")
    for s in records[:5]:
        print(f"  Date: {str(s.get('date',''))[:10]} | Net: {s.get('netSales',0):>10,.2f}"
              f" | Gross: {s.get('grossSales',0):>10,.2f} | Guests: {s.get('numberofGuests',0)}"
              f" | Loc: {str(s.get('location',''))[:12]}...")
except Exception as e:
    print(f"  ERROR: {e}")

# Test LaborDetail with date filter
print("\n=== LaborDetail (Jan 2025) ===")
try:
    url = (BASE + "/LaborDetail?$top=5"
           + "&$filter=dateWorked%20ge%202025-01-01T00:00:00Z%20and%20dateWorked%20le%202025-01-31T23:59:59Z")
    data = fetch(url)
    records = data.get("value", [])
    print(f"  Found {len(records)} records (showing first 5)")
    for l in records[:5]:
        print(f"  Date: {str(l.get('dateWorked',''))[:10]} | Hours: {l.get('hours',0)}"
              f" | Total: {l.get('total',0):>10,.2f} | Job: {l.get('jobTitle','')}"
              f" | Loc: {str(l.get('location',''))[:12]}...")
except Exception as e:
    print(f"  ERROR: {e}")

# Count TransactionDetails - see if we can page through all
print("\n=== TransactionDetail total ===")
try:
    total = 0
    skip = 0
    while True:
        url = f"{BASE}/TransactionDetail?$top=5000&$skip={skip}"
        data = fetch(url)
        batch = data.get("value", [])
        total += len(batch)
        print(f"  Page (skip={skip}): {len(batch)} records, running total: {total}")
        if len(batch) < 5000:
            break
        skip += 5000
        if skip > 500000:
            print("  Stopping at 500k")
            break
except Exception as e:
    print(f"  ERROR: {e}")
