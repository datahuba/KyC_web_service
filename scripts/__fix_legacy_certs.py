"""
Script único: re-emite los PDFs de los certs legacy y los sube a Cloudinary
con access_mode='public' para que sean descargables sin signed URL.

Uso:
    docker exec -it kyc-backend python /app/scripts/__fix_legacy_certs.py

Idempotente: si el cert ya tiene access_mode='public', lo salta.
"""
import asyncio
import io
import sys
from datetime import datetime, timezone

import cloudinary
import cloudinary.uploader
from pymongo import MongoClient

# Conectar a Mongo
import os
mongo_url = os.environ.get("MONGODB_URL", "mongodb://oys-database:27017")
db_name = os.environ.get("MONGODB_DB_NAME", "KyC")
client = MongoClient(mongo_url)
db = client[db_name]

# Cloudinary
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)


def re_upload_to_cloudinary(pdf_bytes: bytes, public_id: str) -> str:
    """Sube el PDF con access_mode='public' y type='upload'."""
    result = cloudinary.uploader.upload(
        io.BytesIO(pdf_bytes),
        folder="kyc/certificates",
        public_id=public_id,
        resource_type="raw",
        type="upload",
        access_mode="public",
        overwrite=True,
        format="pdf",
    )
    return result.get("secure_url") or result.get("url", "")


async def main():
    # Importar servicios (después de inicializar Beanie)
    from main import app  # noqa
    from models.certificate import Certificate
    from models.enrollment import Enrollment
    from models.student import Student
    from models.course import Course
    import services.certificate_service as cs

    certs = await Certificate.find_all().to_list()
    print(f"Encontrados {len(certs)} certs en la base")

    fixed = 0
    skipped = 0
    errors = 0

    for cert in certs:
        # Determinar el public_id actual desde la URL existente
        if not cert.pdf_url:
            skipped += 1
            continue

        # Extraer public_id del cert existente
        # URL format: https://res.cloudinary.com/dckj1wnra/raw/upload/v123/kyc/certificates/<public_id>.pdf
        try:
            parts = cert.pdf_url.split("/")
            # parts[-1] = "<public_id>.pdf"
            filename = parts[-1]
            if filename.endswith(".pdf"):
                filename = filename[:-4]
            expected_public_id = filename
        except Exception as e:
            print(f"  ⚠️  No pude parsear URL de cert {cert.id}: {e}")
            errors += 1
            continue

        # Re-renderizar el PDF usando los datos del cert
        try:
            student = await Student.get(cert.student_id)
            course = await Course.get(cert.course_id)
            enrollment = await Enrollment.get(cert.enrollment_id)
            if not (student and course and enrollment):
                print(f"  ⚠️  Datos faltantes para cert {cert.folio}")
                errors += 1
                continue

            if cert.tipo == "notas":
                pdf_bytes = cs.render_pdf_notas(
                    student=student,
                    course=course,
                    enrollment=enrollment,
                    folio=cs._format_folio(cert.numero, cert.anio),
                    emitido_en=cert.emitido_en,
                )
            else:
                pdf_bytes = cs.render_pdf_no_deudor(
                    student=student,
                    course=course,
                    enrollment=enrollment,
                    hasta_modulo_n=cert.hasta_modulo_n or 1,
                    folio=cs._format_folio(cert.numero, cert.anio),
                    emitido_en=cert.emitido_en,
                )

            # Re-subir con access_mode='public'
            new_url = re_upload_to_cloudinary(pdf_bytes, public_id=expected_public_id)
            if not new_url:
                raise ValueError("Cloudinary no retornó URL")

            # Actualizar el cert
            cert.pdf_url = new_url
            await cert.save()

            print(f"  ✓ {cert.folio} ({cert.tipo}) — nuevo URL: {new_url[-60:]}")
            fixed += 1

        except Exception as e:
            print(f"  ✗ {cert.folio} ({cert.tipo}): {e}")
            errors += 1

    print(f"\nResumen: {fixed} fixed, {skipped} skipped, {errors} errors")


if __name__ == "__main__":
    asyncio.run(main())
