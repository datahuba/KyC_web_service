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
    
    La contraseña será el carnet (hasheado automáticamente).
    """
    from core.security import get_password_hash
    
    student_data = student_in.model_dump(exclude_unset=True)
    student_data["password"] = get_password_hash(student_data["carnet"])
    
    student = Student(**student_data)
    await student.insert()
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
    
    ¡SOPORTE DE MAPEO DINÁMICO DE CABECERAS!
    Busca de forma inteligente las palabras clave en la Fila 1 para asignar
    las columnas sin importar el orden o si hay columnas complementarias.
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
    # Leemos la fila de cabecera y la convertimos a minúsculas
    header_row = []
    for col_idx in range(1, sheet.max_column + 1):
        cell_val = sheet.cell(row=1, column=col_idx).value
        header_row.append(str(cell_val).strip().lower() if cell_val is not None else "")
        
    # Inicializar índices de columnas mapeadas (1-based index, 0 = no encontrado)
    col_nombre = 0
    col_registro = 0
    col_carnet = 0
    col_extension = 0
    col_email = 0
    col_celular = 0
    col_domicilio = 0
    col_tipo = 0
    
    # Mapear columnas buscando coincidencias en la cabecera
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
            
    # Validaciones críticas de existencia de columnas indispensables
    if col_nombre == 0:
        raise ValueError("No se encontró la columna de 'Nombre' en la fila de cabecera del Excel.")
    if col_carnet == 0:
        raise ValueError("No se encontró la columna de 'CI' o 'Carnet' en la fila de cabecera del Excel.")
        
    success_count = 0
    errors = []
    
    # 2. EVITAR TIMEOUT: Protector contra celdas vacías formateadas
    empty_row_streak = 0
    
    # Recorrer filas omitiendo la cabecera
    for row_idx in range(2, sheet.max_row + 1):
        try:
            # Leer los dos campos críticos para verificar si la fila está vacía
            nombre_val = sheet.cell(row=row_idx, column=col_nombre).value if col_nombre > 0 else None
            carnet_val = sheet.cell(row=row_idx, column=col_carnet).value if col_carnet > 0 else None
            
            nombre_str = str(nombre_val).strip() if nombre_val is not None else ""
            carnet_str = str(carnet_val).strip() if carnet_val is not None else ""
            
            # Si encontramos 5 filas completamente vacías consecutivas, detenemos el proceso
            if not nombre_str and not carnet_str:
                empty_row_streak += 1
                if empty_row_streak >= 5:
                    break # Salir del bucle para no causar timeout
                continue
            else:
                empty_row_streak = 0 # Resetear contador si la fila tiene datos
                
            # Leer el resto de los campos de forma dinámica según su columna mapeada
            registro = sheet.cell(row=row_idx, column=col_registro).value if col_registro > 0 else None
            extension = sheet.cell(row=row_idx, column=col_extension).value if col_extension > 0 else None
            email = sheet.cell(row=row_idx, column=col_email).value if col_email > 0 else None
            celular = sheet.cell(row=row_idx, column=col_celular).value if col_celular > 0 else None
            domicilio = sheet.cell(row=row_idx, column=col_domicilio).value if col_domicilio > 0 else None
            tipo_raw = sheet.cell(row=row_idx, column=col_tipo).value if col_tipo > 0 else None
            
            # Sanitizar textos definitivos
            nombre = nombre_str if nombre_str else None
            carnet = carnet_str if carnet_str else None
            registro = str(registro).strip() if registro is not None else None
            extension = str(extension).strip() if extension is not None else None
            email = str(email).strip() if email is not None else None
            celular = str(celular).strip() if celular is not None else None
            domicilio = str(domicilio).strip() if domicilio is not None else None
            
            # Clasificar tipo de estudiante
            tipo_estudiante = TipoEstudiante.EXTERNO
            if tipo_raw:
                tipo_clean = str(tipo_raw).strip().lower()
                if "interno" in tipo_clean:
                    tipo_estudiante = TipoEstudiante.INTERNO
                    
            # Validaciones obligatorias de fila
            if not nombre:
                errors.append(f"Fila {row_idx}: El nombre completo es obligatorio.")
                continue
                
            if not carnet:
                errors.append(f"Fila {row_idx}: El carnet (CI) de '{nombre}' es obligatorio.")
                continue
                
            # REGLA DE FALLBACK SOLICITADA:
            # Si no viene Registro académico, el Email se convierte en su nombre de usuario (registro)
            if not registro:
                if not email:
                    errors.append(
                        f"Fila {row_idx}: El estudiante '{nombre}' no tiene Registro académico. "
                        f"Se intentó usar el correo como usuario, pero el campo 'Email' también está vacío."
                    )
                    continue
                registro = email # Aplicamos fallback
                
            # Validar duplicados por usuario/registro único en MongoDB
            existing_student = await Student.find_one(Student.registro == registro)
            if existing_student:
                errors.append(f"Fila {row_idx}: El usuario/registro '{registro}' ya existe en el sistema.")
                continue
                
            # Hashear la contraseña inicial (Carnet de identidad)
            hashed_password = get_password_hash(carnet)
            
            # Instanciar modelo
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
