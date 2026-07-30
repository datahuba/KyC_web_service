"""Test signed URL generation for the test_public_access PDF."""
import cloudinary
import cloudinary.utils
import os

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# Generar signed URL
signed = cloudinary.utils.cloudinary_url(
    "kyc/certificates/test_public_access.pdf",
    resource_type="raw",
    sign_url=True,
    secure=True,
    expires_at=int(os.popen("date +%s").read().strip()) + 3600,
)
print("Signed URL:", signed)
print("Type of signed:", type(signed))
print("Length:", len(signed))
if isinstance(signed, tuple):
    print("Tuple[0]:", signed[0])
