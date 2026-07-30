"""Try various methods to download the PDF as bytes."""
import cloudinary
import cloudinary.api
import cloudinary.uploader
import cloudinary.utils
import os
import sys
import urllib.request
import urllib.error
import http.client
import json

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# Method 1: Use signed URL but with a different signature algorithm
# Maybe the SDK is generating an old-style signature
print("=== Method 1: Direct API request with signature ===")
import time
import hashlib

ts = int(time.time())
to_sign = f"expires_at={ts+3600}&public_id=kyc/certificates/test_public_access.pdf&timestamp={ts}"
to_sign_full = f"{to_sign}{os.environ.get('CLOUDINARY_API_SECRET')}"
sig = hashlib.sha1(to_sign_full.encode('utf-8')).hexdigest()
url = f"https://api.cloudinary.com/v1_1/dckj1wnra/raw/download?public_id=kyc/certificates/test_public_access.pdf&timestamp={ts}&expires_at={ts+3600}&signature={sig}"
print("URL:", url[:100])
try:
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=30)
    print("Status:", resp.status, "Length:", len(resp.read()))
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read()[:200])
except Exception as e:
    print("Error:", e)

# Method 2: Use the destroy with notification_url to get the file
# Method 3: Use a different resource_type
print("\n=== Method 2: Use image resource_type ===")
try:
    # Re-upload as image type
    result = cloudinary.uploader.upload(
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        folder="kyc/certificates",
        public_id="test_as_image",
        resource_type="image",
        type="upload",
        access_mode="public",
        overwrite=True,
        format="pdf",
    )
    print("Uploaded as image. URL:", result.get("secure_url"))
    url = result.get("secure_url")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    print("Status:", resp.status, "Length:", len(resp.read()))
except Exception as e:
    print("Error:", e)
