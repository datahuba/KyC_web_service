"""Try cloudinary.uploader.explicit to update access mode."""
import cloudinary
import cloudinary.uploader
import os

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# Use explicit to update an existing asset's access mode
print("=== Trying explicit with type=upload + access_mode=public ===")
try:
    result = cloudinary.uploader.explicit(
        "kyc/certificates/test_public_access",
        type="upload",
        resource_type="raw",
        access_mode="public",
        format="pdf",
    )
    print("Result:", result)
except Exception as e:
    print("Error:", e)

print("\n=== Trying rename to new public_id ===")
try:
    result = cloudinary.uploader.rename(
        "kyc/certificates/test_public_access",
        "kyc/certificates/test_public_access_v2",
        resource_type="raw",
        type="upload",
        access_mode="public",
    )
    print("Result:", result)
except Exception as e:
    print("Error:", e)
