import base64, urllib.request, urllib.error, urllib.parse, json, ssl

cred = base64.b64decode('Zm9yYWdla2l0Y2hlblxoZW5yeUBmb3JhZ2Vrb21idWNoYS5jb206S2luZ0phbWVzMSE=')
auth = base64.b64encode(cred).decode()
HEADERS = dict(Authorization='Basic ' + auth, Accept='application/json')
BASE = 'https://odata.restaurant365.net/api/v2/views'
ctx = ssl.create_default_context()
DF = chr(36)

def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=60, context=ctx)
        return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = getattr(e, 'read', lambda: b'')()
        return e.code, body.decode('utf-8', errors='replace')[:500]
    except Exception as e:
        return 0, str(e)

date_filter = 'date ge 2026-01-01T00:00:00Z and date le 2026-01-31T23:59:59Z'

sep = '=' * 80
print(sep)
print('FILTERED TRANSACTION QUERIES (Jan 2026)')
print(sep)

for txn_type in ['AP Invoice', 'AP Credit Memo', 'Stock Count', 'Waste Log', 'Item Transfer', 'Journal Entry']:
    filt = "type eq '" + txn_type + "' and " + date_filter
    params = urllib.parse.urlencode({DF+'filter': filt, DF+'top': '3', DF+'orderby': 'date desc'})
    url = BASE + '/Transaction?' + params
    status, data = fetch_json(url)
    if status == 200 and isinstance(data, dict):
        recs = data.get('value', [])
        print()
        print('  [' + txn_type + '] - ' + str(len(recs)) + ' record(s)')
        for r in recs:
            print('    name: ' + str(r.get('name', '')))
            print('    date: ' + str(r.get('date', '')) + ' loc: ' + str(r.get('locationName', '')))
    else:
        print()
        print('  [' + txn_type + '] - HTTP ' + str(status) + ': ' + str(data)[:200])
