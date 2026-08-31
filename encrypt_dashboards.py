"""
Encrypt dashboard HTML files with a password.

Reads plaintext HTML files in the current directory, encrypts each one's
contents with AES-256-GCM using a PBKDF2-derived key, and wraps them in a
password-prompt template. Decryption happens client-side in the browser
via WebCrypto (SubtleCrypto).

Password comes from dashboard_password.txt (gitignored). The plaintext
files are OVERWRITTEN with the encrypted versions — re-run the dashboard
builders to regenerate the plaintext.

Usage:
    python encrypt_dashboards.py           # encrypt all HTMLs
    python encrypt_dashboards.py file.html # encrypt one specific file
"""
import os
import sys
import base64
import json
import secrets
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

OUTDIR = os.path.dirname(os.path.abspath(__file__))
PASSWORD_FILE = os.path.join(OUTDIR, "dashboard_password.txt")
PBKDF2_ITERATIONS = 200_000

# Files to skip (kept public — no sensitive data)
SKIP_FILES = {
    # add any HTML files here that should NOT be encrypted
}

# Marker in encrypted files so we don't double-encrypt on re-runs
ENCRYPT_MARKER = "<!-- STATICRYPT-ENCRYPTED -->"


def load_password():
    if not os.path.exists(PASSWORD_FILE):
        print(f"ERROR: {PASSWORD_FILE} not found.")
        print(f"Create it with the desired password on the first line.")
        sys.exit(1)
    with open(PASSWORD_FILE, "r", encoding="utf-8") as f:
        pw = f.read().strip()
    if not pw or pw == "CHANGE_ME_TO_YOUR_PASSWORD":
        print(f"ERROR: Password in {PASSWORD_FILE} has not been set.")
        print(f"Edit that file and put your password on the first line.")
        sys.exit(1)
    return pw


def encrypt_content(plaintext: str, password: str) -> dict:
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return {
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "iterations": PBKDF2_ITERATIONS,
    }


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forage Kitchen Dashboard</title>
{ENCRYPT_MARKER}
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: #0f172a; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; min-height: 100vh; }}
  .lock-container {{ display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }}
  .lock-box {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 40px; max-width: 400px; width: 100%; box-shadow: 0 8px 40px rgba(0,0,0,0.4); }}
  .lock-title {{ font-size: 20px; font-weight: 600; margin: 0 0 8px 0; color: #f8fafc; }}
  .lock-sub {{ font-size: 14px; color: #94a3b8; margin: 0 0 24px 0; }}
  .lock-input {{ width: 100%; padding: 12px 14px; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #f8fafc; font-size: 16px; margin-bottom: 12px; }}
  .lock-input:focus {{ outline: none; border-color: #3b82f6; }}
  .lock-btn {{ width: 100%; padding: 12px; background: #3b82f6; border: none; border-radius: 8px; color: white; font-size: 15px; font-weight: 500; cursor: pointer; }}
  .lock-btn:hover {{ background: #2563eb; }}
  .lock-btn:disabled {{ background: #475569; cursor: not-allowed; }}
  .lock-error {{ color: #f87171; font-size: 13px; margin-top: 12px; text-align: center; min-height: 18px; }}
</style>
</head>
<body>
<div class="lock-container" id="lockContainer">
  <form class="lock-box" id="lockForm">
    <h1 class="lock-title">Forage Dashboards</h1>
    <p class="lock-sub">Enter password to view</p>
    <input type="password" class="lock-input" id="pw" autocomplete="current-password" autofocus required>
    <button type="submit" class="lock-btn" id="submitBtn">Unlock</button>
    <div class="lock-error" id="err"></div>
  </form>
</div>
<script>
const PAYLOAD = {PAYLOAD_JSON};

function b64ToBytes(s) {{
  const bin = atob(s);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}}

async function decrypt(password) {{
  const salt = b64ToBytes(PAYLOAD.salt);
  const iv = b64ToBytes(PAYLOAD.iv);
  const ct = b64ToBytes(PAYLOAD.ciphertext);
  const keyMaterial = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password),
    "PBKDF2", false, ["deriveKey"]
  );
  const key = await crypto.subtle.deriveKey(
    {{ name: "PBKDF2", salt: salt, iterations: PAYLOAD.iterations, hash: "SHA-256" }},
    keyMaterial,
    {{ name: "AES-GCM", length: 256 }},
    false, ["decrypt"]
  );
  const plainBytes = await crypto.subtle.decrypt({{ name: "AES-GCM", iv: iv }}, key, ct);
  return new TextDecoder().decode(plainBytes);
}}

const STORAGE_KEY = "forage_dashboard_pw";

async function tryUnlock(password, remember) {{
  const html = await decrypt(password);
  if (remember) {{
    try {{ sessionStorage.setItem(STORAGE_KEY, password); }} catch (e) {{}}
  }}
  document.open();
  document.write(html);
  document.close();
}}

document.getElementById("lockForm").addEventListener("submit", async (e) => {{
  e.preventDefault();
  const pw = document.getElementById("pw").value;
  const btn = document.getElementById("submitBtn");
  const err = document.getElementById("err");
  err.textContent = "";
  btn.disabled = true;
  btn.textContent = "Unlocking...";
  try {{
    await tryUnlock(pw, true);
  }} catch (ex) {{
    err.textContent = "Incorrect password";
    btn.disabled = false;
    btn.textContent = "Unlock";
    document.getElementById("pw").select();
  }}
}});

// Try auto-unlock from session
(async () => {{
  try {{
    const saved = sessionStorage.getItem(STORAGE_KEY);
    if (saved) await tryUnlock(saved, false);
  }} catch (e) {{
    try {{ sessionStorage.removeItem(STORAGE_KEY); }} catch (e2) {{}}
  }}
}})();
</script>
</body>
</html>
"""


def is_encrypted(html: str) -> bool:
    return ENCRYPT_MARKER in html[:2048]


def encrypt_file(path: str, password: str) -> bool:
    """Encrypt one file in place. Returns True if changed, False if skipped."""
    fname = os.path.basename(path)
    if fname in SKIP_FILES:
        print(f"  SKIP (excluded): {fname}")
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if is_encrypted(content):
        print(f"  SKIP (already encrypted): {fname}")
        return False
    payload = encrypt_content(content, password)
    wrapped = TEMPLATE.format(
        ENCRYPT_MARKER=ENCRYPT_MARKER,
        PAYLOAD_JSON=json.dumps(payload),
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(wrapped)
    orig_kb = len(content) / 1024
    new_kb = len(wrapped) / 1024
    print(f"  encrypted: {fname} ({orig_kb:.1f} KB -> {new_kb:.1f} KB)")
    return True


def main():
    password = load_password()

    # Collect files
    if len(sys.argv) > 1:
        targets = [os.path.join(OUTDIR, arg) for arg in sys.argv[1:]]
    else:
        targets = [
            os.path.join(OUTDIR, f)
            for f in os.listdir(OUTDIR)
            if f.endswith(".html")
        ]

    if not targets:
        print("No HTML files found.")
        return

    print(f"Encrypting {len(targets)} file(s)...")
    changed = 0
    for path in sorted(targets):
        if not os.path.exists(path):
            print(f"  MISSING: {os.path.basename(path)}")
            continue
        if encrypt_file(path, password):
            changed += 1
    print(f"\nDone. {changed} file(s) encrypted.")


if __name__ == "__main__":
    main()
