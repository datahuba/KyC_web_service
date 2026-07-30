"""Try with proper authentication headers."""
import cloudinary
import cloudinary.api
import os
import urllib.request
import urllib.error
import base64

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# Method: Use Basic auth on the resource URL
api_key = os.environ.get("CLOUDINARY_API_KEY")
api_secret = os.environ.get("CLOUDINARY_API_SECRET")
auth = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()

url = "https://res.cloudinary.com/dckj1wnra/raw/upload/v1785421757/kyc/certificates/test_public_access.pdf"
print(f"=== With Basic auth ===")
try:
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    resp = urllib.request.urlopen(req, timeout=30)
    print("Status:", resp.status, "Length:", len(resp.read()))
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read()[:200])
except Exception as e:
    print("Error:", e)

# Method: Use the resource API with file download
print(f"\n=== cloudinary.api.resource with file=raw ===")
import tempfile
import requests
try:
    # This might work - download the actual file
    result = cloudinary.Downloader(folder="kyc/certificates")
except Exception as e:
    print("Downloader error:", e)

# Method: Use cloudinary's download URL format
print(f"\n=== Try the /image/fetch/ for raw download ===")
url2 = f"https://res.cloudinary.com/dckj1wnra/image/fetch/{base64.b64encode(b'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf').decode()}"
print(f"URL: {url2[:100]}")
try:
    req = urllib.request.Request(url2)
    resp = urllib.request.urlopen(req, timeout=30)
    print("Status:", resp.status)
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read()[:200])
