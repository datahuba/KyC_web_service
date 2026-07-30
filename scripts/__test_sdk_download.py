"""Download the test PDF using the cloudinary SDK (bypass URL)."""
import cloudinary
import cloudinary.api
import os
import sys

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# Try the api.resource with bytes=True (if supported)
print("=== api.resource with bytes ===")
try:
    result = cloudinary.api.resource(
        "kyc/certificates/test_public_access.pdf",
        resource_type="raw",
        bytes=True,
    )
    print("Got result, keys:", list(result.keys()) if isinstance(result, dict) else "not a dict")
    if isinstance(result, dict) and "bytes" in result:
        print("Bytes length:", len(result["bytes"]))
except Exception as e:
    print("Error:", e)

# Try downloading via streaming
print("\n=== Try with type=authenticated + sign ===")
import cloudinary.utils
signed = cloudinary.utils.cloudinary_url(
    "kyc/certificates/test_public_access.pdf",
    resource_type="raw",
    type="authenticated",
    sign_url=True,
    secure=True,
    expires_at=int(os.popen("date +%s").read().strip()) + 3600,
)
url = signed[0] if isinstance(signed, tuple) else signed
print("URL:", url)
try:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    print("Status:", resp.status, "Length:", len(resp.read()))
except Exception as e:
    print("Error:", e)
