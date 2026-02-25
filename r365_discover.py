import base64
import urllib.request
import urllib.error
import json
import ssl

# Auth setup
cred = b'foragekitchen\henry@foragekombucha.com:KingJames1!'
auth = base64.b64encode(cred).decode()
HEADERS = {"Authorization": "Basic " + auth, "Accept": "application/json"}
BASE = "https://odata.restaurant365.net/api/v2/views"

# Allow unverified SSL if needed
ctx = ssl.create_default_context()

def fetch(url, label=""):
    """Fetch a URL and return (status, data_or_error)"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        body = resp.read().decode('utf-8')
        return resp.status, body
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode('utf-8')[:500]
        except:
            pass
        return e.code, body
    except Exception as e:
        return 0, str(e)

print("=" * 80)
print("R365 OData API Discovery")
print("=" * 80)

# 1. Try service document (base URL)
print("\n[1] SERVICE DOCUMENT (base URL)")
print("-" * 60)
status, body = fetch(BASE)
print(f"    URL: {BASE}")
print(f"    Status: {status}")
if status == 200:
    try:
        data = json.loads(body)
        if "value" in data:
            entities = [v.get("name", v.get("url", str(v))) for v in data["value"]]
            print(f"    Found {len(entities)} entity sets:")
            for e in sorted(entities):
                print(f"      - {e}")
        else:
            # Print keys and a snippet
            print(f"    Keys: {list(data.keys())}")
            print(f"    Snippet: {body[:1000]}")
    except:
        print(f"    Raw (first 1000 chars): {body[:1000]}")
else:
    print(f"    Response: {body[:500]}")

# 2. Try $metadata
print("\n[2] $metadata")
print("-" * 60)
meta_url = BASE + "/$metadata"
# For metadata, accept XML
req = urllib.request.Request(meta_url, headers={
    "Authorization": "Basic " + auth,
    "Accept": "application/xml"
})
try:
    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    mbody = resp.read().decode('utf-8')
    print(f"    URL: {meta_url}")
    print(f"    Status: {resp.status}")
    # Extract EntitySet names from XML
    import re
    entity_sets = re.findall(r'EntitySet\s+Name="([^"]+)"', mbody)
    entity_types = re.findall(r'EntityType\s+Name="([^"]+)"', mbody)
    if entity_sets:
        print(f"    Found {len(entity_sets)} EntitySets:")
        for es in sorted(entity_sets):
            print(f"      - {es}")
    if entity_types:
        print(f"\n    Found {len(entity_types)} EntityTypes:")
        for et in sorted(entity_types):
            print(f"      - {et}")
    if not entity_sets and not entity_types:
        print(f"    Metadata snippet (first 2000 chars):\n{mbody[:2000]}")
except urllib.error.HTTPError as e:
    print(f"    Status: {e.code}")
    try:
        print(f"    Response: {e.read().decode('utf-8')[:500]}")
    except:
        pass
except Exception as e:
    print(f"    Error: {e}")

# 3. Try specific endpoints
endpoints_to_try = [
    # AP / Invoices
    "APInvoice",
    "ApInvoice",
    "APInvoiceHeader",
    "AP_Invoice",
    "APInvoiceDetail",
    "ApInvoiceDetail",
    "AP_InvoiceDetail",
    "APTransaction",
    "AP_Transaction",
    "ApTransaction",
    # Inventory
    "Inventory",
    "InventoryCount",
    "InventoryItem",
    "Inventory_Item",
    "Item",
    "InventoryTransfer",
    "Inventory_Transfer",
    # Vendor
    "Vendor",
    "Vendors",
    # Purchase Orders
    "PurchaseOrder",
    "PurchaseOrderDetail",
    "PurchaseOrderHeader",
    "Purchase_Order",
    # Waste
    "WasteLog",
    "Waste",
    "Waste_Log",
    # Other common ones
    "GLAccount",
    "GL_Account",
    "Account",
    "Location",
    "Transaction",
    "TransactionDetail",
    "JournalEntry",
    "Recipe",
    "UnitOfMeasure",
]

print("\n[3] TESTING SPECIFIC ENDPOINTS ($top=3)")
print("=" * 80)

working = []
failed = []

for ep in endpoints_to_try:
    url = f"{BASE}/{ep}?$top=3"
    status, body = fetch(url, ep)
    
    if status == 200:
        try:
            data = json.loads(body)
            records = data.get("value", [])
            print(f"\n  FOUND: {ep}  (Status {status}, {len(records)} records returned)")
            print(f"  URL: {url}")
            print("-" * 60)
            if records:
                fields = list(records[0].keys())
                print(f"  Fields ({len(fields)}):")
                for f in fields:
                    print(f"    - {f}")
                print(f"\n  Sample record (first):")
                for k, v in records[0].items():
                    val_str = str(v)
                    if len(val_str) > 120:
                        val_str = val_str[:120] + "..."
                    print(f"    {k}: {val_str}")
            else:
                print("  (No records returned, but endpoint exists)")
                # Still print keys from response
                print(f"  Response keys: {list(data.keys())}")
            working.append(ep)
        except json.JSONDecodeError:
            print(f"\n  FOUND (non-JSON): {ep}  (Status {status})")
            print(f"  Body snippet: {body[:500]}")
            working.append(ep)
    else:
        failed.append((ep, status))

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"\nWorking endpoints ({len(working)}):")
for ep in working:
    print(f"  + {BASE}/{ep}")

print(f"\nFailed endpoints ({len(failed)}):")
for ep, code in failed:
    print(f"  - {ep} (HTTP {code})")

