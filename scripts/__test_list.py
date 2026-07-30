"""List raw assets."""
import cloudinary
import cloudinary.api
import os

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# List raw resources
print("=== Raw resources in kyc/ ===")
try:
    result = cloudinary.api.resources(
        type="upload",
        resource_type="raw",
        prefix="kyc/",
        max_results=10,
    )
    for r in result.get("resources", []):
        print(f"  {r.get('public_id')} | type={r.get('type')} | access={r.get('access_mode')}")
except Exception as e:
    print("Error:", e)

# List with image resource_type
print("\n=== Image resources in kyc/certificates/ ===")
try:
    result = cloudinary.api.resources(
        type="upload",
        resource_type="image",
        prefix="kyc/certificates/",
        max_results=10,
    )
    for r in result.get("resources", []):
        print(f"  {r.get('public_id')} | type={r.get('type')} | access={r.get('access_mode')}")
except Exception as e:
    print("Error:", e)

# Try by asset_folder
print("\n=== By asset_folder ===")
try:
    result = cloudinary.api.resources_by_asset_folder(
        "kyc/certificates",
        max_results=10,
    )
    for r in result.get("resources", []):
        print(f"  {r.get('public_id')} | type={r.get('type')} | access={r.get('access_mode')} | rtype={r.get('resource_type')}")
except Exception as e:
    print("Error:", e)
