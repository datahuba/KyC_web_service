"""
Servicio de Estudiantes
=======================

Lógica de negocio para estudiantes (Funciones).
"""

from typing import List, Optional, Union
from models.student import Student
from models.enums import EstadoTitulo
from schemas.student import StudentCreate, StudentUpdateSelf, StudentUpdateAdmin
from beanie import PydanticObjectId
from beanie.operators import Or, RegEx


async def get_students(
    skip: int = 0,
    limit: int = 100,
    q: Optional[str] = None,
    activo: Optional[bool] = None,
    estado_titulo: Optional[EstadoTitulo] = None,
    curso_id: Optional[PydanticObjectId] = None
) -> List[Student]:
    """
    Obtener lista de estudiantes con filtros avanzados
    
    Args:
        skip: Paginación (saltar)
        limit: Paginación (límite)
        q: Búsqueda por texto (nombre, email, carnet, registro)
        activo: Filtrar por estado activo/inactivo
        estado_titulo: Filtrar por estado del título
        curso_id: Filtrar por inscripción en un curso
    """
    # Iniciar consulta base
    query = Student.find()
    
    # 1. Filtro de búsqueda (q)
    if q:
        # Usar sintaxis nativa de MongoDB para regex (más robusta)
        regex_pattern = {"$regex": q, "$options": "i"}
        query = query.find(
            Or(
                Student.nombre == regex_pattern,
                Student.email == regex_pattern,
                Student.carnet == regex_pattern,
                Student.registro == regex_pattern
            )
        )
    
    # 2. Filtro por estado activo
    if activo is not None:
        query = query.find(Student.activo == activo)
    
    # 3. Filtro por estado del título
    if estado_titulo:
        if estado_titulo == EstadoTitulo.SIN_TITULO:
            # Caso especial: Incluir los que tienen estado SIN_TITULO Y los que no tienen objeto título (None)
            query = query.find(
                Or(
                    Student.titulo.estado == EstadoTitulo.SIN_TITULO,
                    Student.titulo == None
                )
            )
        else:
            # Caso normal: Filtrar por el estado específico
            query = query.find(Student.titulo.estado == estado_titulo)
    
    # 4. Filtro por curso inscrito
    if curso_id:
        # lista_cursos_ids es una lista de IDs (Optimizado)
        query = query.find(Student.lista_cursos_ids == curso_id)
    
    # Ejecutar consulta con paginación
    return await query.skip(skip).limit(limit).to_list()


async def get_student(id: PydanticObjectId) -> Optional[Student]:
    """Obtener estudiante por ID"""
    return await Student.get(id)


async def create_student(student_in: StudentCreate) -> Student:
    """
    Crear nuevo estudiante
    
    La contraseña será el carnet (hasheado automáticamente).
    El estudiante puede cambiar su contraseña después.
    """
    from core.security import get_password_hash
    
    student_data = student_in.model_dump(exclude_unset=True)
    
    # Usar el carnet como contraseña inicial
    student_data["password"] = get_password_hash(student_data["carnet"])
    
    student = Student(**student_data)
    await student.insert()
    return student


async def update_student(
    student: Student,
    student_in: Union[StudentUpdateSelf, StudentUpdateAdmin]
) -> Student:
    """
    Actualizar estudiante existente
    
    Args:
        student: Estudiante a actualizar
        student_in: Datos de actualización (StudentUpdateSelf o StudentUpdateAdmin)
    
    Returns:
        Estudiante actualizado
    
    Nota:
        - Solo actualiza campos que fueron enviados (exclude_unset=True)
        - Si se actualiza password, se hashea automáticamente
        - StudentUpdateSelf permite menos campos que StudentUpdateAdmin
    """
    from core.security import get_password_hash
    
    # Obtener solo los campos que fueron enviados (no None por defecto)
    update_data = student_in.model_dump(exclude_unset=True)
    
    # Si se está actualizando la contraseña, hashearla
    if "password" in update_data and update_data["password"]:
        update_data["password"] = get_password_hash(update_data["password"])
    
    # Actualizar los campos del estudiante
    for field, value in update_data.items():
        setattr(student, field, value)
    
    # Guardar cambios
    await student.save()
    
    return student


async def delete_student(id: PydanticObjectId) -> Student:
    """Eliminar estudiante"""
    student = await Student.get(id)
    if student:
        await student.delete()
    return student
