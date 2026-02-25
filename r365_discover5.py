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

def show_detail(txn_type_name, date_filt):
    print()
    print(sep)
    print(txn_type_name.upper() + ' WITH DETAIL LINES')
    print(sep)
    filt = "type eq '" + txn_type_name + "' and " + date_filt
    params = urllib.parse.urlencode({DF+'filter': filt, DF+'top': '1', DF+'orderby': 'date desc'})
    url = BASE + '/Transaction?' + params
    status, data = fetch_json(url)
    if status == 200 and isinstance(data, dict):
        txns = data.get('value', [])
        if txns:
            txn = txns[0]
            txn_id = txn['transactionId']
            print('  Header: ' + str(txn['name']))
            print('  Date: ' + str(txn['date']))
            print('  Location: ' + str(txn.get('locationName', '')))
            print('  ID: ' + str(txn_id))
            params2 = urllib.parse.urlencode({DF+'filter': 'transactionId eq ' + str(txn_id), DF+'top': '50'})
            url2 = BASE + '/TransactionDetail?' + params2
            st2, d2 = fetch_json(url2)
            if st2 == 200 and isinstance(d2, dict):
                details = d2.get('value', [])
                print('  Detail lines: ' + str(len(details)))
                for i, d in enumerate(details[:8]):
                    print()
                    print('  Line ' + str(i+1) + ' (' + str(d.get('rowType', '')) + '):')
                    for k, v in d.items():
                        print('    ' + k + ': ' + str(v))
            else:
                print('  Detail HTTP ' + str(st2) + ': ' + str(d2)[:200])
        else:
            print('  No ' + txn_type_name + ' found in this period')
    else:
        print('  HTTP ' + str(status) + ': ' + str(data)[:200])

show_detail('AP Invoice', date_filter)
show_detail('Stock Count', date_filter)
show_detail('Waste Log', date_filter)
show_detail('Item Transfer', date_filter)

print()
print(sep)
print('ALL LOCATIONS')
print(sep)
url = BASE + '/Location?' + urllib.parse.urlencode({DF+'top': '50'})
status, data = fetch_json(url)
if status == 200 and isinstance(data, dict):
    locs = data.get('value', [])
    print('  ' + str(len(locs)) + ' locations:')
    for loc in locs:
        print('    ' + str(loc['name']) + ' (#' + str(loc.get('locationNumber', '')) + ') | entity=' + str(loc.get('legalEntityName', '')))

print()
print(sep)
print('ITEMS (first 25)')
print(sep)
url = BASE + '/Item?' + urllib.parse.urlencode({DF+'top': '25'})
status, data = fetch_json(url)
if status == 200 and isinstance(data, dict):
    items = data.get('value', [])
    for item in items:
        print('    ' + str(item['name']) + ' | cat1=' + str(item.get('category1', '')) + ' | cat2=' + str(item.get('category2', '')))
