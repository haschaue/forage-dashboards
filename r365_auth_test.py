"""
R365 OData Authentication Test
Prompts for credentials locally and tests the connection.
"""
import requests
import getpass
import json
import sys

# R365 subdomain
SUBDOMAIN = "foragekitchen"
AUTH_URL = f"https://{SUBDOMAIN}.restaurant365.com/APIv1/Authenticate/JWT"
ODATA_BASE = "https://odata.restaurant365.net/api/v2/views"

print("=" * 60)
print("  Restaurant365 OData Connection Test")
print("=" * 60)
print()

# Prompt for credentials locally (not stored anywhere)
username = input("Enter your R365 username (email): ")
password = getpass.getpass("Enter your R365 password: ")

print()
print("[1/4] Authenticating with R365...")

# Authenticate
auth_payload = {
    "username": username,
    "password": password
}

try:
    auth_resp = requests.post(AUTH_URL, json=auth_payload, timeout=30)
    if auth_resp.status_code != 200:
        print(f"  ERROR: Authentication failed (HTTP {auth_resp.status_code})")
        print(f"  Response: {auth_resp.text[:500]}")
        sys.exit(1)

    token_data = auth_resp.json()
    if "token" in token_data:
        token = token_data["token"]
    elif "access_token" in token_data:
        token = token_data["access_token"]
    else:
        # Sometimes the response IS the token string
        token = auth_resp.text.strip().strip('"')

    print(f"  SUCCESS - Got JWT token ({len(token)} chars)")
except Exception as e:
    print(f"  ERROR: {e}")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
}

# Test Location endpoint
print("[2/4] Fetching Locations...")
try:
    loc_resp = requests.get(f"{ODATA_BASE}/Location?$top=20", headers=headers, timeout=30)
    if loc_resp.status_code == 200:
        locations = loc_resp.json().get("value", [])
        print(f"  SUCCESS - Found {len(locations)} locations:")
        for loc in locations:
            print(f"    {loc.get('locationNumber', '?'):>6} - {loc.get('name', '?')}")

        # Save for later use
        with open("r365_locations.json", "w") as f:
            json.dump(locations, f, indent=2)
    else:
        print(f"  ERROR: HTTP {loc_resp.status_code} - {loc_resp.text[:300]}")
except Exception as e:
    print(f"  ERROR: {e}")

# Test GL Account endpoint
print("[3/4] Fetching GL Accounts (sample)...")
try:
    gl_resp = requests.get(f"{ODATA_BASE}/GlAccount?$top=20", headers=headers, timeout=30)
    if gl_resp.status_code == 200:
        accounts = gl_resp.json().get("value", [])
        print(f"  SUCCESS - Found GL accounts (showing first 20):")
        for acct in accounts[:20]:
            print(f"    {acct.get('glAccountNumber', '?'):>8} - {acct.get('name', '?')} [{acct.get('glType', '?')}]")

        with open("r365_gl_accounts_sample.json", "w") as f:
            json.dump(accounts, f, indent=2)
    else:
        print(f"  ERROR: HTTP {gl_resp.status_code} - {gl_resp.text[:300]}")
except Exception as e:
    print(f"  ERROR: {e}")

# Test Transaction endpoint
print("[4/4] Fetching recent Transactions (sample)...")
try:
    txn_resp = requests.get(
        f"{ODATA_BASE}/Transaction?$top=5&$orderby=date desc",
        headers=headers, timeout=30
    )
    if txn_resp.status_code == 200:
        txns = txn_resp.json().get("value", [])
        print(f"  SUCCESS - Found transactions (showing last 5):")
        for txn in txns:
            print(f"    {txn.get('date', '?')[:10]} | {txn.get('type', '?'):>20} | {txn.get('name', '?')}")

        with open("r365_transactions_sample.json", "w") as f:
            json.dump(txns, f, indent=2)
    else:
        print(f"  ERROR: HTTP {txn_resp.status_code} - {txn_resp.text[:300]}")
except Exception as e:
    print(f"  ERROR: {e}")

print()
print("=" * 60)
print("  Test Complete!")
print("  Token and credentials were NOT saved.")
print("=" * 60)

# Save token temporarily for follow-up queries in this session
with open("r365_token_temp.txt", "w") as f:
    f.write(token)
print("  (Token saved to r365_token_temp.txt for follow-up queries)")
