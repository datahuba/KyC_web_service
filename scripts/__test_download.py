"""Test multiple Cloudinary download methods."""
import cloudinary
import cloudinary.utils
import cloudinary.api
import os
import urllib.request

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# Method 1: cloudinary_url with type=authenticated
print("=== Method 1: type=upload ===")
url = cloudinary.utils.cloudinary_url(
    "kyc/certificates/test_public_access.pdf",
    resource_type="raw",
    type="upload",
    secure=True,
)
print("URL:", url[0] if isinstance(url, tuple) else url)
try:
    resp = urllib.request.urlopen(url[0] if isinstance(url, tuple) else url)
    print("Status:", resp.status, "Length:", len(resp.read()))
except Exception as e:
    print("Error:", e)

# Method 2: download_archive API
print("\n=== Method 2: download API ===")
try:
    result = cloudinary.api.download_folder(
        folder="kyc/certificates",
        resource_type="raw",
    )
    print("Result:", result)
except Exception as e:
    print("Error:", e)

# Method 3: get resource info
print("\n=== Method 3: get resource ===")
try:
    result = cloudinary.api.resource(
        "kyc/certificates/test_public_access.pdf",
        resource_type="raw",
    )
    print("Type:", result.get("type"))
    print("Access mode:", result.get("access_mode"))
    print("URL:", result.get("secure_url"))
except Exception as e:
    print("Error:", e)
