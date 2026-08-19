"""
Utilidades para subir archivos a Cloudinary
============================================

Funciones para subir y gestionar archivos en Cloudinary.
"""

import os
import cloudinary
import cloudinary.uploader
from fastapi import UploadFile, HTTPException
from core.config import settings
from typing import Optional

# Configurar Cloudinary
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)


def _normalizar_public_id(file: UploadFile, public_id: Optional[str]) -> Optional[str]:
    """Asegura que el public_id contenga la extensión adecuada del archivo (.pdf, .jpg, .png, .webp).
    Esto evita que Cloudinary genere URLs de archivos sin extensión al ser descargados en Windows/Mac."""
    if not public_id:
        return public_id
    
    ext = ""
    filename = file.filename or ""
    if "." in filename:
        candidate = os.path.splitext(filename)[1].lower()
        if candidate in [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".doc", ".docx"]:
            ext = candidate

    if not ext:
        ctype = (file.content_type or "").lower()
        if "pdf" in ctype:
            ext = ".pdf"
        elif "jpeg" in ctype or "jpg" in ctype:
            ext = ".jpg"
        elif "png" in ctype:
            ext = ".png"
        elif "webp" in ctype:
            ext = ".webp"

    if ext and not public_id.lower().endswith(ext):
        return f"{public_id}{ext}"
    return public_id


async def upload_pdf(
    file: UploadFile,
    folder: str,
    public_id: Optional[str] = None
) -> str:
    """
    Subir un archivo PDF a Cloudinary
    
    Args:
        file: Archivo a subir
        folder: Carpeta en Cloudinary (ej: "students/cv")
        public_id: ID público (nombre del archivo)
        
    Returns:
        URL del archivo subido con extensión .pdf
    """
    # Validar que sea PDF
    if not file.content_type == "application/pdf":
        raise HTTPException(
            status_code=400,
            detail=f"El archivo debe ser PDF, recibido: {file.content_type}"
        )
    
    # Validar tamaño (máximo 10MB)
    file.file.seek(0, 2)  # Ir al final del archivo
    file_size = file.file.tell()  # Obtener tamaño
    file.file.seek(0)  # Volver al inicio
    
    if file_size > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(
            status_code=400,
            detail="El archivo es demasiado grande (máximo 10MB)"
        )
    
    try:
        final_public_id = _normalizar_public_id(file, public_id)
        # Subir a Cloudinary
        result = cloudinary.uploader.upload(
            file.file,
            folder=folder,
            public_id=final_public_id,
            resource_type="raw",  # Para PDFs
            overwrite=True
        )
        
        secure_url = result["secure_url"]
        if not secure_url.lower().endswith(".pdf"):
            secure_url = f"{secure_url}.pdf"
        return secure_url
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir archivo: {str(e)}"
        )


async def upload_image(
    file: UploadFile,
    folder: str,
    public_id: Optional[str] = None
) -> str:
    """
    Subir una imagen a Cloudinary
    
    Args:
        file: Archivo a subir
        folder: Carpeta en Cloudinary (ej: "students/photos")
        public_id: ID público opcional (nombre del archivo)
        
    Returns:
        URL de la imagen subida
        
    Raises:
        HTTPException: Si el archivo no es imagen o hay error al subir
    """
    # Validar que sea imagen
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"El archivo debe ser imagen (JPG, PNG, WEBP), recibido: {file.content_type}"
        )
    
    # Validar tamaño (máximo 5MB)
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    if file_size > 5 * 1024 * 1024:  # 5MB
        raise HTTPException(
            status_code=400,
            detail="La imagen es demasiado grande (máximo 5MB)"
        )
    
    try:
        final_public_id = _normalizar_public_id(file, public_id)
        # Subir a Cloudinary con transformaciones
        result = cloudinary.uploader.upload(
            file.file,
            folder=folder,
            public_id=final_public_id,
            resource_type="image",
            overwrite=True,
            transformation=[
                {"width": 800, "height": 800, "crop": "limit"},  # Redimensionar
                {"quality": "auto"},  # Calidad automática
                {"fetch_format": "auto"}  # Formato automático
            ]
        )
        
        return result["secure_url"]
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir imagen: {str(e)}"
        )


async def upload_document(
    file: UploadFile,
    folder: str,
    public_id: Optional[str] = None
) -> dict:
    """
    Sube un documento o imagen a Cloudinary.

    Tipos permitidos: PDF, Word (.doc/.docx), PPT (.ppt/.pptx),
                      Excel (.xls/.xlsx), imágenes (JPG, PNG, WEBP).
    Tamaño máximo: 20 MB.

    Returns:
        dict con claves: url, public_id, resource_type, mime_type, size_bytes
    """
    ALLOWED: dict[str, str] = {
        "application/pdf": "raw",
        "application/msword": "raw",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "raw",
        "application/vnd.ms-powerpoint": "raw",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "raw",
        "application/vnd.ms-excel": "raw",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "raw",
        "image/jpeg": "image",
        "image/png": "image",
        "image/webp": "image",
    }
    MAX_SIZE = 20 * 1024 * 1024  # 20 MB

    content_type = file.content_type or ""
    if content_type not in ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tipo de archivo no permitido: {content_type}. "
                "Permitidos: PDF, Word, PPT, Excel, JPG, PNG, WEBP."
            ),
        )

    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(0)

    if size_bytes > MAX_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Archivo demasiado grande (máximo 20 MB).",
        )

    resource_type = ALLOWED[content_type]

    try:
        import asyncio

        file_content = await file.read()
        loop = asyncio.get_event_loop()
        final_public_id = _normalizar_public_id(file, public_id)

        # F-FIX-CLOUDINARY-URL-ROTA (2026-08-19): antes esta funcion subia
        # el archivo SIN indicarle el formato a Cloudinary (`public_id` es
        # None en TODOS los llamadores de upload_document — comprobantes,
        # adjuntos de bug-reports, cartas/resoluciones de pre-inscripcion,
        # materiales de aula, entregas de tareas — asi que
        # `_normalizar_public_id` nunca agregaba nada: solo actua cuando
        # SI se pasa un public_id explicito). Cloudinary generaba un ID
        # aleatorio SIN extension (`format: None` al consultarlo), y el
        # codigo de abajo intentaba arreglarlo pegando ".pdf" al FINAL del
        # string de la URL devuelta.
        #
        # Eso rompia el archivo: la URL con extension pegada NUNCA
        # existio en Cloudinary (confirmado en vivo: la URL con ".pdf" da
        # 404, la misma URL sin la extension da 200). Kevin lo encontro
        # al intentar ver el comprobante de un certificado desde el
        # perfil de coordinador financiero.
        #
        # DOS INTENTOS DE FIX QUE NO SIRVIERON (dejados documentados para no
        # repetir el error):
        #
        # 1. Pasarle `format=ext` a `cloudinary.uploader.upload()`. Para
        #    `resource_type="raw"` ese parametro es un no-op del lado del
        #    servidor — el recurso se guarda igual con `format: None`. El
        #    SDK arma el `secure_url` de la respuesta pegandole la extension
        #    localmente ANTES de confirmar que el recurso se sirve ahi, asi
        #    que la URL devuelta parecia correcta pero daba 404.
        #
        # 2. Generar un `public_id` propio con la extension incluida
        #    (`<uuid>.pdf`), para que la extension SI quede en el path real.
        #    Esto si logra que la URL exista — pero la cuenta de Cloudinary
        #    tiene activa la proteccion de seguridad "Restricted media
        #    types" (default de Cloudinary desde 2023/2024): bloquea con
        #    401 la entrega PUBLICA de cualquier recurso "raw" cuya URL
        #    termine en una extension reconocida como PDF/ZIP, sin importar
        #    `access_mode` (probado explicitamente con `access_mode="public"`
        #    en el upload — sigue dando 401). Es un toggle de la consola de
        #    Cloudinary (Settings > Security > "Allow delivery of PDF and
        #    ZIP files"), no algo resoluble por API con las credenciales
        #    actuales.
        #
        # FIX real (el unico que la cuenta actual sirve con 200): dejar que
        # Cloudinary genere su public_id SIN extension, tal cual, sin tocar
        # el string de la URL para nada. El navegador igual descarga/abre el
        # archivo correctamente porque el Content-Type real (via el mime
        # guardado aparte en Mongo) no depende de la extension en la URL.
        # Pendiente para Kevin: si se quiere que el archivo abra CON su
        # nombre y extension originales (en vez de un nombre generico sin
        # extension), hay que entrar a la consola de Cloudinary y activar
        # esa opcion, o migrar a URLs firmadas (`type="authenticated"`).
        upload_kwargs: dict = {
            "folder": folder,
            "public_id": final_public_id,
            "resource_type": resource_type,
            "overwrite": True,
        }

        result = await loop.run_in_executor(
            None,
            lambda: cloudinary.uploader.upload(file_content, **upload_kwargs),
        )

        url = result["secure_url"]

        return {
            "url": url,
            "public_id": result["public_id"],
            "resource_type": resource_type,
            "mime_type": content_type,
            "size_bytes": size_bytes,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir archivo a Cloudinary: {str(e)}",
        )


async def delete_file(public_id: str, resource_type: str = "raw") -> bool:
    """
    Eliminar un archivo de Cloudinary
    
    Args:
        public_id: ID público del archivo
        resource_type: Tipo de recurso ("raw" para PDFs, "image" para imágenes)
        
    Returns:
        True si se eliminó correctamente
    """
    try:
        result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
        return result.get("result") == "ok"
    except Exception:
        return False
