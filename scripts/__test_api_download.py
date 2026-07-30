"""Test: descargar PDF via API autenticada de Cloudinary (bypass URL)."""
import os
import sys
import json
import urllib.request
import urllib.error
import hashlib
import time

# Credenciales
cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "dckj1wnra")
api_key = os.environ.get("CLOUDINARY_API_KEY", "726662772921572")
api_secret = os.environ.get("CLOUDINARY_API_SECRET", "wM0qnCt_9kdxFJN7pwmGHvy6oYs")
public_id = "kyc/certificates/test_public_access"

# Method 1: POST a /resources/raw/download con auth
print("=== Method 1: POST /resources/raw/download ===")
ts = int(time.time())
# Construir string to_sign: sorted params + secret
params = {
    "public_id": public_id,
    "resource_type": "raw",
    "type": "upload",
    "format": "pdf",
    "timestamp": str(ts),
}
# Ordenar keys
sorted_keys = sorted(params.keys())
to_sign = "&".join(f"{k}={params[k]}" for k in sorted_keys)
sig = hashlib.sha1(f"{to_sign}{api_secret}".encode("utf-8")).hexdigest()
print(f"to_sign: {to_sign[:100]}...")
print(f"sig: {sig}")

# POST form data
import urllib.parse
post_data = urllib.parse.urlencode({**params, "signature": sig, "api_key": api_key}).encode("utf-8")
url = f"https://api.cloudinary.com/v1_1/{cloud_name}/resources/raw/download"
print(f"URL: {url}")
try:
    req = urllib.request.Request(url, data=post_data, method="POST")
    resp = urllib.request.urlopen(req, timeout=30)
    print(f"Status: {resp.status}, Length: {len(resp.read())}")
    # Save to /tmp
    req2 = urllib.request.Request(url, data=post_data, method="POST")
    resp2 = urllib.request.urlopen(req2, timeout=30)
    with open("/tmp/test_download.pdf", "wb") as f:
        f.write(resp2.read())
    print(f"Saved to /tmp/test_download.pdf, size: {os.path.getsize('/tmp/test_download.pdf')}")
except urllib.error.HTTPError as e:
    print(f"HTTPError: {e.code}, body: {e.read()[:500]}")
except Exception as e:
    print(f"Error: {e}")
