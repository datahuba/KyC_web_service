"""
Servicio de Estudiantes
=======================

Lógica de negocio para estudiantes (Funciones).
"""

import openpyxl
from io import BytesIO
from typing import List, Optional, Union
from models.student import Student
from models.enums import EstadoTitulo
from schemas.student import StudentCreate, StudentUpdateSelf, StudentUpdateAdmin
from beanie import PydanticObjectId
from beanie.operators import Or, RegEx


async def get_students(
    page: int = 1,
    per_page: int = 10,
    q: Optional[str] = None,
    activo: Optional[bool] = None,
    estado_titulo: Optional[EstadoTitulo] = None,
    curso_id: Optional[PydanticObjectId] = None
) -> tuple[List[Student], int]:
    """
    Obtener lista de estudiantes con filtros avanzados y paginación
    """
    query = Student.find()
    
    if q:
        regex_pattern = {"$regex": q, "$options": "i"}
        query = query.find(
            Or(
                Student.nombre == regex_pattern,
                Student.email == regex_pattern,
                Student.carnet == regex_pattern,
                Student.registro == regex_pattern
            )
        )
    
    if activo is not None:
        query = query.find(Student.activo == activo)
    
    if estado_titulo:
        if estado_titulo == EstadoTitulo.SIN_TITULO:
            query = query.find(
                Or(
                    Student.titulo.estado == EstadoTitulo.SIN_TITULO,
                    Student.titulo == None
                )
            )
        else:
            query = query.find(Student.titulo.estado == estado_titulo)
    
    if curso_id:
        query = query.find(Student.lista_cursos_ids == curso_id)
    
    total_count = await query.count()
    skip = (page - 1) * per_page
    
    students = await query.sort("-created_at").skip(skip).limit(per_page).to_list()
    
    return students, total_count


async def get_student(id: PydanticObjectId) -> Optional[Student]:
    """Obtener estudiante por ID"""
    return await Student.get(id)


async def create_student(student_in: StudentCreate) -> Student:
    """
    Crear nuevo estudiante
    
    Si se provee password, se usa; sino, se hashea el carnet (fallback).
    Si se provee course_id, se inscribe automáticamente (y se validan los datos primero).
    """
    from core.security import get_password_hash
    from models.course import Course
    from schemas.enrollment import EnrollmentCreate
    from services import enrollment_service
    
    student_data = student_in.model_dump(exclude_unset=True)
    
    # 1. Extraer campos opcionales sin romper el resto de la lógica
    course_id = student_data.pop("course_id", None)
    password_input = student_data.pop("password", None)
    
    # 2. Validar existencia del curso ANTES de crear al estudiante (Ahorro de BD)
    course_obj = None
    if course_id:
        course_obj = await Course.get(course_id)
        if not course_obj:
            raise ValueError("Curso no encontrado")
        if not course_obj.activo:
            raise ValueError("El curso seleccionado está inactivo")

    # 3. Lógica Inteligente de Contraseña
    if password_input:
        student_data["password"] = get_password_hash(password_input)
    else:
        student_data["password"] = get_password_hash(student_data["carnet"])
        
    # 4. Persistir Estudiante
    student = Student(**student_data)
    await student.insert()
    
    # 5. Puente de Inscripción Integrado
    if course_obj:
        try:
            await enrollment_service.create_enrollment(
                enrollment_in=EnrollmentCreate(
                    estudiante_id=student.id,
                    curso_id=course_obj.id,
                    descuento_id=None,
                    descuento_personalizado=None
                ),
                admin_username="system_student_create"
            )
        except Exception as e:
            # Rollback compensatorio si la inscripción falla por error interno
            await student.delete()
            raise ValueError(f"Error en la auto-inscripción: {str(e)}")
            
    return student


async def update_student(
    student: Student,
    student_in: Union[StudentUpdateSelf, StudentUpdateAdmin]
) -> Student:
    """Actualizar estudiante existente"""
    from core.security import get_password_hash
    
    update_data = student_in.model_dump(exclude_unset=True)
    
    if "password" in update_data and update_data["password"]:
        update_data["password"] = get_password_hash(update_data["password"])
    
    for field, value in update_data.items():
        setattr(student, field, value)
    
    await student.save()
    return student


async def delete_student(id: PydanticObjectId) -> Student:
    """Eliminar estudiante"""
    student = await Student.get(id)
    if student:
        await student.delete()
    return student


# ============================================================================
# LOGICA DE IMPORTACIÓN MASIVA DESDE EXCEL
# ============================================================================

async def import_students_from_excel(file_content: bytes) -> dict:
    """
    Importar estudiantes de forma masiva desde un archivo de Excel (.xlsx).
    """
    from core.security import get_password_hash
    from models.enums import TipoEstudiante
    
    try:
        # Cargar libro en memoria de forma optimizada
        wb = openpyxl.load_workbook(BytesIO(file_content), data_only=True)
        sheet = wb.active
        if not sheet:
            raise ValueError("El archivo Excel no tiene hojas activas.")
    except Exception as e:
        raise ValueError(f"No se pudo parsear el archivo Excel: {str(e)}")
        
    # 1. ESCANEO DINÁMICO DE CABECERAS (FILA 1)
    header_row = []
    for col_idx in range(1, sheet.max_column + 1):
        cell_val = sheet.cell(row=1, column=col_idx).value
        header_row.append(str(cell_val).strip().lower() if cell_val is not None else "")
        
    col_nombre = 0
    col_registro = 0
    col_carnet = 0
    col_extension = 0
    col_email = 0
    col_celular = 0
    col_domicilio = 0
    col_tipo = 0
    
    for idx, header in enumerate(header_row, start=1):
        if "nombre" in header:
            col_nombre = idx
        elif "registro" in header:
            col_registro = idx
        elif header == "ci" or "carnet" in header or "documento" in header:
            col_carnet = idx
        elif "extension" in header or "ext" in header:
            col_extension = idx
        elif "correo" in header or "email" in header or "mail" in header:
            col_email = idx
        elif "celular" in header or "telefono" in header or "telf" in header:
            col_celular = idx
        elif "domicilio" in header or "direccion" in header or "dir" in header:
            col_domicilio = idx
        elif "tipo" in header or "interno" in header:
            col_tipo = idx
            
    if col_nombre == 0:
        raise ValueError("No se encontró la columna de 'Nombre' en la fila de cabecera del Excel.")
    if col_carnet == 0:
        raise ValueError("No se encontró la columna de 'CI' o 'Carnet' en la fila de cabecera del Excel.")
        
    success_count = 0
    errors = []
    
    empty_row_streak = 0
    
    for row_idx in range(2, sheet.max_row + 1):
        try:
            nombre_val = sheet.cell(row=row_idx, column=col_nombre).value if col_nombre > 0 else None
            carnet_val = sheet.cell(row=row_idx, column=col_carnet).value if col_carnet > 0 else None
            
            nombre_str = str(nombre_val).strip() if nombre_val is not None else ""
            carnet_str = str(carnet_val).strip() if carnet_val is not None else ""
            
            if not nombre_str and not carnet_str:
                empty_row_streak += 1
                if empty_row_streak >= 5:
                    break 
                continue
            else:
                empty_row_streak = 0
                
            registro = sheet.cell(row=row_idx, column=col_registro).value if col_registro > 0 else None
            extension = sheet.cell(row=row_idx, column=col_extension).value if col_extension > 0 else None
            email = sheet.cell(row=row_idx, column=col_email).value if col_email > 0 else None
            celular = sheet.cell(row=row_idx, column=col_celular).value if col_celular > 0 else None
            domicilio = sheet.cell(row=row_idx, column=col_domicilio).value if col_domicilio > 0 else None
            tipo_raw = sheet.cell(row=row_idx, column=col_tipo).value if col_tipo > 0 else None
            
            nombre = nombre_str if nombre_str else None
            carnet = carnet_str if carnet_str else None
            registro = str(registro).strip() if registro is not None else None
            extension = str(extension).strip() if extension is not None else None
            email = str(email).strip() if email is not None else None
            celular = str(celular).strip() if celular is not None else None
            domicilio = str(domicilio).strip() if domicilio is not None else None
            
            tipo_estudiante = TipoEstudiante.EXTERNO
            if tipo_raw:
                tipo_clean = str(tipo_raw).strip().lower()
                if "interno" in tipo_clean:
                    tipo_estudiante = TipoEstudiante.INTERNO
                    
            if not nombre:
                errors.append(f"Fila {row_idx}: El nombre completo es obligatorio.")
                continue
                
            if not carnet:
                errors.append(f"Fila {row_idx}: El carnet (CI) de '{nombre}' es obligatorio.")
                continue
                
            if not registro:
                if not email:
                    errors.append(
                        f"Fila {row_idx}: El estudiante '{nombre}' no tiene Registro académico. "
                        f"Se intentó usar el correo como usuario, pero el campo 'Email' también está vacío."
                    )
                    continue
                registro = email 
                
            existing_student = await Student.find_one(Student.registro == registro)
            if existing_student:
                errors.append(f"Fila {row_idx}: El usuario/registro '{registro}' ya existe en el sistema.")
                continue
                
            hashed_password = get_password_hash(carnet)
            
            student = Student(
                registro=registro,
                password=hashed_password,
                nombre=nombre,
                email=email,
                carnet=carnet,
                extension=extension,
                celular=celular,
                domicilio=domicilio,
                es_estudiante_interno=tipo_estudiante,
                activo=True,
                lista_cursos_ids=[]
            )
            
            await student.insert()
            success_count += 1
            
        except Exception as ex:
            errors.append(f"Fila {row_idx}: Error inesperado: {str(ex)}")
            
    return {
        "success_count": success_count,
        "errors": errors
    }
