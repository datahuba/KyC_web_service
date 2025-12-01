"""
Schemas de Estudiante
=====================

Define los schemas Pydantic para operaciones CRUD de estudiantes.

Schemas incluidos:
-----------------
1. StudentCreate: Para crear nuevos estudiantes (sin id, sin campos autogenerados)
2. StudentResponse: Para mostrar estudiantes (sin password)
3. StudentUpdate: Para actualizar estudiantes (todos los campos opcionales)
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr
from models.enums import TipoEstudiante
from models.base import PyObjectId


class StudentCreate(BaseModel):
    """
    Schema para crear un nuevo estudiante
    
    Uso: POST /students/
    
    ¿Qué incluye?
    ------------
    - Datos de autenticación (registro, password)
    - Información personal (nombre, CI, fecha nacimiento)
    - Contacto (celular, email, domicilio)
    - Información académica (carrera, tipo de estudiante)
    
    ¿Qué NO incluye?
    ---------------
    - id: Se genera automáticamente
    - fecha_registro: Se asigna al momento de creación
    - activo: Por defecto es True
    - lista_cursos_ids: Se llena cuando se inscribe
    - lista_titulos_ids: Se llena cuando obtiene títulos
    - created_at, updated_at: Autogenerados
    """
    
    registro: str = Field(
        ...,
        description="Número de registro único del estudiante (usado como username)"
    )
    
    password: str = Field(
        ...,
        min_length=8,
        description="Contraseña (será hasheada antes de guardar)"
    )
    
    nombre: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nombre completo del estudiante"
    )
    
    extension: str = Field(
        ...,
        description="Carnet de identidad o documento de identificación"
    )
    
    fecha_nacimiento: datetime = Field(
        ...,
        description="Fecha de nacimiento"
    )
    
    foto_url: Optional[str] = Field(
        None,
        description="URL de la foto de perfil"
    )
    
    celular: str = Field(
        ...,
        description="Número de celular para notificaciones"
    )
    
    email: EmailStr = Field(
        ...,
        description="Correo electrónico"
    )
    
    domicilio: Optional[str] = Field(
        None,
        description="Dirección física del estudiante"
    )
    
    carrera: str = Field(
        ...,
        description="Carrera de pregrado del estudiante"
    )
    
    es_estudiante_interno: TipoEstudiante = Field(
        ...,
        description="Tipo de estudiante: INTERNO o EXTERNO"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "registro": "EST-2024-001",
                "password": "MiPassword123!",
                "nombre": "Juan Pérez García",
                "extension": "12345678 LP",
                "fecha_nacimiento": "1995-05-15T00:00:00",
                "foto_url": "https://storage.example.com/photos/juan.jpg",
                "celular": "+591 70123456",
                "email": "juan.perez@example.com",
                "domicilio": "Av. Principal #123, La Paz, Bolivia",
                "carrera": "Ingeniería de Sistemas",
                "es_estudiante_interno": "interno"
            }
        }


class StudentResponse(BaseModel):
    """
    Schema para mostrar información de un estudiante
    
    Uso: GET /students/{id}, respuestas de POST/PUT/PATCH
    
    ¿Qué incluye?
    ------------
    - Todos los campos del estudiante
    - EXCEPTO: password (seguridad)
    
    ¿Por qué excluir password?
    -------------------------
    Las contraseñas hasheadas NUNCA deben enviarse al cliente,
    ni siquiera en formato hash. Es una buena práctica de seguridad.
    """
    
    id: PyObjectId = Field(..., alias="_id")
    registro: str
    nombre: str
    extension: str
    fecha_nacimiento: datetime
    foto_url: Optional[str]
    celular: str
    email: EmailStr
    domicilio: Optional[str]
    carrera: str
    es_estudiante_interno: TipoEstudiante
    lista_cursos_ids: List[PyObjectId] = []
    lista_titulos_ids: List[PyObjectId] = []
    fecha_registro: datetime
    activo: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439011",
                "registro": "EST-2024-001",
                "nombre": "Juan Pérez García",
                "extension": "12345678 LP",
                "fecha_nacimiento": "1995-05-15T00:00:00",
                "foto_url": "https://storage.example.com/photos/juan.jpg",
                "celular": "+591 70123456",
                "email": "juan.perez@example.com",
                "domicilio": "Av. Principal #123, La Paz, Bolivia",
                "carrera": "Ingeniería de Sistemas",
                "es_estudiante_interno": "interno",
                "lista_cursos_ids": [],
                "lista_titulos_ids": [],
                "fecha_registro": "2024-01-15T10:30:00",
                "activo": True,
                "created_at": "2024-01-15T10:30:00",
                "updated_at": "2024-01-15T10:30:00"
            }
        }


class StudentUpdate(BaseModel):
    """
    Schema para actualizar un estudiante existente
    
    Uso: PATCH /students/{id}
    
    ¿Qué incluye?
    ------------
    - Todos los campos son opcionales
    - Permite actualizaciones parciales
    - No se puede cambiar: id, fecha_registro, created_at
    
    Ejemplo de uso:
    --------------
    # Actualizar solo el email
    {"email": "nuevo@example.com"}
    
    # Actualizar nombre y celular
    {"nombre": "Juan Carlos Pérez", "celular": "+591 71234567"}
    
    # Desactivar estudiante
    {"activo": False}
    """
    
    registro: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    nombre: Optional[str] = Field(None, min_length=1, max_length=200)
    extension: Optional[str] = None
    fecha_nacimiento: Optional[datetime] = None
    foto_url: Optional[str] = None
    celular: Optional[str] = None
    email: Optional[EmailStr] = None
    domicilio: Optional[str] = None
    carrera: Optional[str] = None
    es_estudiante_interno: Optional[TipoEstudiante] = None
    lista_cursos_ids: Optional[List[PyObjectId]] = None
    lista_titulos_ids: Optional[List[PyObjectId]] = None
    activo: Optional[bool] = None
    
    class Config:
        schema_extra = {
            "example": {
                "email": "nuevo.email@example.com",
                "celular": "+591 71234567",
                "activo": True
            }
        }
