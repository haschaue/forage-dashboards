import base64, urllib.request, urllib.error, urllib.parse, json, ssl

cred = b"foragekitchen" + b"\\" + b"henry@foragekombucha.com:KingJames1!"
auth = base64.b64encode(cred).decode()