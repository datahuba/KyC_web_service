"""Check cloudinary SDK for private download methods."""
import cloudinary.uploader as cu
import cloudinary.api as ca
import cloudinary.utils as cu_t

print("=== uploader methods ===")
for m in dir(cu):
    if not m.startswith('_'):
        print(f"  {m}")

print("\n=== api methods ===")
for m in dir(ca):
    if not m.startswith('_'):
        print(f"  {m}")

print("\n=== utils functions ===")
for m in dir(cu_t):
    if not m.startswith('_'):
        print(f"  {m}")
