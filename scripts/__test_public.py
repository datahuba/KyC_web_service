"""Test simple: subir un PDF con access_mode=public a un public_id unico."""
import cloudinary
import cloudinary.uploader
import os
import sys

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# Subir un PDF dummy
result = cloudinary.uploader.upload(
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
    folder="kyc/certificates",
    public_id="test_public_access",
    resource_type="raw",
    type="upload",
    access_mode="public",
    overwrite=True,
    format="pdf",
)
print("Uploaded. URL:", result.get("secure_url"))
print("Access mode:", result.get("access_mode"))
print("Type:", result.get("type"))
