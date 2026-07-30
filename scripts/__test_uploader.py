"""Check cloudinary.uploader for download methods."""
import cloudinary.uploader as cu

methods = [m for m in dir(cu) if not m.startswith('_')]
for m in methods:
    print(m)
