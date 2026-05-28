"""
Servicio de Estudiantes
=======================

Lógica de negocio para estudiantes (Funciones).
"""

import openpyxl
from io import BytesIO
from typing import List, Optional, Union
from models.student import Student
from models.enums import EstadoTitulo, TipoEstudiante
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
    
    # 1. Validaciones robustas de Unicidad (Registro, Carnet, Correo) en base de datos
    check_conditions = []
    if student_in.registro:
        check_conditions.append(Student.registro == student_in.registro)
    if student_in.carnet:
        check_conditions.append(Student.carnet == student_in.carnet)
    if student_in.email and student_in.email.strip():
        check_conditions.append(Student.email == student_in.email.strip().lower())
        
    if check_conditions:
        existing = await Student.find_one(Or(*check_conditions))
        if existing:
            if student_in.registro and existing.registro == student_in.registro:
                raise ValueError(f"Ya existe un estudiante registrado con el Registro Académico: '{student_in.registro}'.")
            if student_in.carnet and existing.carnet == student_in.carnet:
                raise ValueError(f"Ya existe un estudiante registrado con el Carnet de Identidad (C.I.): '{student_in.carnet}'.")
            if student_in.email and existing.email and existing.email.lower() == student_in.email.strip().lower():
                raise ValueError(f"Ya existe un estudiante registrado con el Correo Electrónico: '{student_in.email}'.")

    student_data = student_in.model_dump(exclude_unset=True)
    
    # Extraer campos opcionales sin romper el resto de la lógica
    course_id = student_data.pop("course_id", None)
    password_input = student_data.pop("password", None)
    
    # Normalizar correo electrónico si se ha proporcionado
    if "email" in student_data and student_data["email"]:
        student_data["email"] = student_data["email"].strip().lower()
    
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
    
    # 1. Validaciones robustas de Unicidad en Modificación (Excluyendo al propio estudiante)
    check_conditions = []
    new_registro = update_data.get("registro")
    new_carnet = update_data.get("carnet")
    new_email = update_data.get("email")
    
    if new_registro and new_registro != student.registro:
        check_conditions.append(Student.registro == new_registro)
    if new_carnet and new_carnet != student.carnet:
        check_conditions.append(Student.carnet == new_carnet)
    if new_email and new_email.strip() and (not student.email or new_email.strip().lower() != student.email.lower()):
        check_conditions.append(Student.email == new_email.strip().lower())
        
    if check_conditions:
        existing = await Student.find_one(
            Or(*check_conditions),
            Student.id != student.id
        )
        if existing:
            if new_registro and existing.registro == new_registro:
                raise ValueError(f"El Registro Académico '{new_registro}' ya está siendo usado por otro estudiante.")
            if new_carnet and existing.carnet == new_carnet:
                raise ValueError(f"El Carnet de Identidad '{new_carnet}' ya está registrado en otra cuenta.")
            if new_email and existing.email and existing.email.lower() == new_email.strip().lower():
                raise ValueError(f"El Correo Electrónico '{new_email}' ya está registrado en otra cuenta.")

    if "password" in update_data and update_data["password"]:
        update_data["password"] = get_password_hash(update_data["password"])
        
    if "email" in update_data and update_data["email"]:
        update_data["email"] = update_data["email"].strip().lower()
    
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
# LOGICA DE IMPORTACIÓN MASIVA DESDE EXCEL OPTIMIZADA DE ALTA VELOCIDAD (Bulk Write)
# ============================================================================

async def import_students_from_excel(file_content: bytes, force_tipo: TipoEstudiante) -> dict:
    """
    Importar estudiantes de forma masiva desde un archivo de Excel (.xlsx).
    
    ¡OPTIMIZACIÓN DE ALTO RENDIMIENTO (ISSUE G)!
    Forzará el tipo de estudiante basado en `force_tipo` (INTERNO/EXTERNO) enviado desde el frontend,
    ignorando cualquier columna que diga "tipo" en el Excel, previniendo errores de digitación de los administrativos.
    """
    from core.security import get_password_hash
    
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
        
    col_nombre = col_registro = col_carnet = col_extension = col_email = col_celular = col_domicilio = 0
    
    for idx, header in enumerate(header_row, start=1):
        if "nombre" in header: col_nombre = idx
        elif "registro" in header: col_registro = idx
        elif header == "ci" or "carnet" in header or "documento" in header: col_carnet = idx
        elif "extension" in header or "ext" in header: col_extension = idx
        elif "correo" in header or "email" in header or "mail" in header: col_email = idx
        elif "celular" in header or "telefono" in header or "telf" in header: col_celular = idx
        elif "domicilio" in header or "direccion" in header or "dir" in header: col_domicilio = idx
            
    if col_nombre == 0:
        raise ValueError("No se encontró la columna de 'Nombre' en la fila de cabecera del Excel.")
    if col_carnet == 0:
        raise ValueError("No se encontró la columna de 'CI' o 'Carnet' en la fila de cabecera del Excel.")
        
    errors = []
    candidates = []
    
    registros_en_archivo = set()
    carnets_en_archivo = set()
    emails_en_archivo = set()
    empty_row_streak = 0
    
    # 2. ESCANEAR FILAS Y VALIDAR EN MEMORIA (FILTRANDO VACÍOS Y DUPLICADOS INTERNOS)
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
            
            nombre = nombre_str if nombre_str else None
            carnet = carnet_str if carnet_str else None
            registro = str(registro).strip() if registro is not None else None
            extension = str(extension).strip() if extension is not None else None
            email = str(email).strip().lower() if email is not None else None
            celular = str(celular).strip() if celular is not None else None
            domicilio = str(domicilio).strip() if domicilio is not None else None
                    
            if not nombre:
                errors.append(f"Fila {row_idx}: El nombre completo es obligatorio.")
                continue
                
            if not carnet:
                errors.append(f"Fila {row_idx}: El carnet (CI) de '{nombre}' es obligatorio.")
                continue
                
            if not registro:
                if not email:
                    errors.append(
                        f"Fila {row_idx}: El estudiante '{nombre}' no tiene Registro académico ni Email de fallback."
                    )
                    continue
                registro = email 
                
            # Controlar duplicados en el mismo archivo para no meter llaves repetidas a BD
            if registro in registros_en_archivo:
                errors.append(f"Fila {row_idx}: El Registro Académico o correo '{registro}' de '{nombre}' está duplicado dentro de este archivo Excel.")
                continue
            
            if carnet in carnets_en_archivo:
                errors.append(f"Fila {row_idx}: El Carnet de Identidad (CI) '{carnet}' de '{nombre}' está duplicado dentro de este archivo Excel.")
                continue
                
            if email:
                if email in emails_en_archivo:
                    errors.append(f"Fila {row_idx}: El Correo Electrónico '{email}' de '{nombre}' está duplicado dentro de este archivo Excel.")
                    continue
                emails_en_archivo.add(email)
                
            registros_en_archivo.add(registro)
            carnets_en_archivo.add(carnet)
            
            candidates.append({
                "row_idx": row_idx,
                "registro": registro,
                "nombre": nombre,
                "email": email,
                "carnet": carnet,
                "extension": extension,
                "celular": celular,
                "domicilio": domicilio,
                "es_estudiante_interno": force_tipo # ISSUE G
            })
        except Exception as e:
            errors.append(f"Fila {row_idx}: Error al procesar datos de la fila: {str(e)}")
            
    # 3. VERIFICAR DUPLICADOS EN BASE DE DATOS (1 SOLA CONSULTA DE RED)
    existing_registros = set()
    existing_carnets = set()
    existing_emails = set()
    
    if candidates:
        all_registros_excel = [c["registro"] for c in candidates]
        all_carnets_excel = [c["carnet"] for c in candidates]
        all_emails_excel = [c["email"] for c in candidates if c["email"]]
        
        db_query = {
            "$or": [
                {"registro": {"$in": all_registros_excel}},
                {"carnet": {"$in": all_carnets_excel}}
            ]
        }
        if all_emails_excel:
            db_query["$or"].append({"email": {"$in": all_emails_excel}})
            
        existing_students_db = await Student.find(db_query).to_list()
        
        for s in existing_students_db:
            if s.registro:
                existing_registros.add(s.registro)
            if s.carnet:
                existing_carnets.add(s.carnet)
            if s.email:
                existing_emails.add(s.email.lower())
        
    # 4. PREPARAR OBJETOS DE INSERTIÓN Y HASHEAR CONTRASEÑAS (PROCESADOR CPU CONTINUO)
    students_to_insert = []
    for c in candidates:
        has_error = False
        if c["registro"] in existing_registros:
            errors.append(f"Fila {c['row_idx']}: El Registro/Usuario '{c['registro']}' ya está registrado en la base de datos.")
            has_error = True
        if c["carnet"] in existing_carnets:
            errors.append(f"Fila {c['row_idx']}: El Carnet de Identidad '{c['carnet']}' de '{c['nombre']}' ya está registrado en la base de datos.")
            has_error = True
        if c["email"] and c["email"].lower() in existing_emails:
            errors.append(f"Fila {c['row_idx']}: El Correo Electrónico '{c['email']}' de '{c['nombre']}' ya está registrado en la base de datos.")
            has_error = True
            
        if has_error:
            continue
            
        hashed_password = get_password_hash(c["carnet"])
        
        students_to_insert.append(
            Student(
                registro=c["registro"],
                password=hashed_password,
                nombre=c["nombre"],
                email=c["email"],
                carnet=c["carnet"],
                extension=c["extension"],
                celular=c["celular"],
                domicilio=c["domicilio"],
                es_estudiante_interno=c["es_estudiante_interno"],
                activo=True,
                lista_cursos_ids=[]
            )
        )
        
    # 5. INSERCIÓN MASIVA DE ALTO RENDIMIENTO (1 SOLA ESCRITURA DE RED)
    success_count = 0
    if students_to_insert:
        await Student.insert_many(students_to_insert)
        success_count = len(students_to_insert)
        
    return {
        "success_count": success_count,
        "errors": errors
    }
