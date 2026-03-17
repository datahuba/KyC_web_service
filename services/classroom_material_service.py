"""
Servicio de Materiales de Classroom
=====================================

Upload/delete de archivos (Cloudinary) y persistencia de metadata (MongoDB).
"""

from typing import List, Optional
from fastapi import UploadFile
from beanie import PydanticObjectId

from models.classroom_material import ClassroomMaterial
from core.cloudinary_utils import upload_document, delete_file


async def get_materials(classroom_id: PydanticObjectId) -> List[ClassroomMaterial]:
    return await ClassroomMaterial.find(
        ClassroomMaterial.classroom_id == classroom_id,
        ClassroomMaterial.active == True,
    ).sort("-created_at").to_list()


async def upload_material(
    classroom_id: PydanticObjectId,
    file: UploadFile,
    title: str,
    uploaded_by: PydanticObjectId,
) -> ClassroomMaterial:
    """Sube archivo a Cloudinary y guarda metadata en MongoDB."""
    folder = f"classroom/{str(classroom_id)}/materials"
    result = await upload_document(file, folder)

    material = ClassroomMaterial(
        classroom_id=classroom_id,
        title=title,
        file_url=result["url"],
        public_id=result["public_id"],
        resource_type=result["resource_type"],
        mime_type=result["mime_type"],
        size_bytes=result["size_bytes"],
        uploaded_by=uploaded_by,
    )
    await material.create()
    return material


async def get_material(material_id: PydanticObjectId) -> Optional[ClassroomMaterial]:
    return await ClassroomMaterial.get(material_id)


async def delete_material(material_id: PydanticObjectId) -> bool:
    """Elimina de Cloudinary y hace soft-delete en MongoDB."""
    material = await ClassroomMaterial.get(material_id)
    if not material or not material.active:
        return False
    await delete_file(material.public_id, material.resource_type)
    material.active = False
    await material.save()
    return True
