"""Check Cloudinary account delivery type settings."""
import cloudinary
import cloudinary.api
import os
import json

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# Get account usage details which may include delivery settings
try:
    usage = cloudinary.api.usage()
    print("Usage:", json.dumps(usage, indent=2, default=str)[:2000])
except Exception as e:
    print("Usage error:", e)

# Get a single asset to check its properties
try:
    resource = cloudinary.api.resource("kyc/certificates/test_public_access.pdf", resource_type="raw")
    print("\nTest public access resource:")
    for k, v in resource.items():
        if not k.startswith('_') and not isinstance(v, (dict, list)):
            print(f"  {k}: {v}")
except Exception as e:
    print("Resource error:", e)
