"""
Schemas de Estudiante
=====================

Define los schemas Pydantic para operaciones CRUD de estudiantes.

Schemas incluidos:
-----------------
1. StudentCreate: Para crear nuevos estudiantes (solo campos esenciales)
2. StudentResponse: Para mostrar estudiantes (sin password)
3. StudentUpdateSelf: Para que estudiantes actualicen su propio perfil
4. StudentUpdateAdmin: Para que admins actualicen cualquier campo
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr
from models.enums import TipoEstudiante
from models.base import PyObjectId
from models.title import Title


class StudentCreate(BaseModel):
    """
    Schema para crear un nuevo estudiante
    
    Uso: POST /students/
    
    Solo incluye los campos esenciales para el registro inicial.
    Los demás campos pueden ser actualizados posteriormente.
    """
    
    registro: str = Field(..., description="Número de registro único del estudiante (usado como username)")
    password: str = Field(..., min_length=4, description="Contraseña (será hasheada antes de guardar)")
    nombre: str = Field(..., min_length=1, max_length=200, description="Nombre completo del estudiante")
    email: EmailStr = Field(..., description="Correo electrónico")
    carnet: str = Field(..., description="Carnet de identidad")
    extension: Optional[str] = Field(None, description="Extension del carnet de identidad")
    celular: str = Field(..., description="Número de celular para notificaciones")
    domicilio: Optional[str] = Field(None, description="Dirección física del estudiante")
    fecha_nacimiento: datetime = Field(..., description="Fecha de nacimiento")
    es_estudiante_interno: TipoEstudiante = Field(..., description="Tipo de estudiante: INTERNO o EXTERNO")

    class Config:
        schema_extra = {
            "example": {
                "registro": "220005958",
                "password": "KyC123",
                "nombre": "Brandon Gonsales Coronado",
                "email": "bgonsalescoronado@gmail.com",
                "carnet": "12345678",
                "extension": "SC",
                "celular": "60984296",
                "domicilio": "Av. Internacional #13, Santa Cruz, Bolivia",
                "fecha_nacimiento": "2002-03-20T00:00:00",
                "es_estudiante_interno": "interno"
            }
        }


class StudentResponse(BaseModel):
    """
    Schema para mostrar información de un estudiante
    """
    
    id: PyObjectId = Field(..., alias="_id")
    registro: str
    nombre: str
    email: EmailStr
    carnet: Optional[str] = None
    extension: Optional[str] = None
    celular: str
    domicilio: Optional[str] = None
    fecha_nacimiento: datetime
    foto_url: Optional[str] = None
    es_estudiante_interno: TipoEstudiante
    
    # Documentos
    ci_url: Optional[str] = None
    afiliacion_url: Optional[str] = None
    cv_url: Optional[str] = None
    
    # Estado y Metadata
    activo: bool
    lista_cursos_ids: List[PyObjectId] = []
    titulo: Optional[Title] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439011",
                "registro": "220005958",
                "nombre": "Brandon Gonsales Coronado",
                "email": "bgonsalescoronado@gmail.com",
                "carnet": "12345678",
                "extension": "SC",
                "celular": "60984296",
                "domicilio": "Av. Internacional #13, Santa Cruz, Bolivia",
                "fecha_nacimiento": "2002-03-20T00:00:00",
                "foto_url": "https://storage.example.com/photos/brandon.jpg",
                "es_estudiante_interno": "interno",
                "activo": True,
                "lista_cursos_ids": [],
                "titulo": {
                    "titulo": "Licenciatura en Ingeniería de Sistemas",
                    "numero_titulo": "123456",
                    "año_expedicion": "2020",
                    "universidad": "Universidad Mayor de San Andrés",
                    "titulo_url": "https://storage.example.com/titulos/brandon.pdf"
                },
                "ci_url": "https://storage.example.com/docs/ci_brandon.pdf",
                "afiliacion_url": "https://storage.example.com/docs/afiliacion_brandon.pdf",
                "cv_url": "https://storage.example.com/docs/cv_brandon.pdf",
                "created_at": "2024-01-15T10:30:00",
                "updated_at": "2024-01-15T10:30:00"
            }
        }
    }


class StudentUpdateSelf(BaseModel):
    """
    Schema para que un estudiante actualice su propio perfil
    
    Uso: PATCH /students/me o PATCH /students/{id} (si es el mismo estudiante)
    
    Permite actualizar información personal y documentos,
    pero NO puede cambiar: registro, activo, lista_cursos_ids, titulo
    """
    
    password: Optional[str] = Field(None, min_length=8)
    celular: Optional[str] = None
    domicilio: Optional[str] = None
    foto_url: Optional[str] = None
    ci_url: Optional[str] = None
    afiliacion_url: Optional[str] = None
    cv_url: Optional[str] = None
    titulo: Optional[Title] = None
    
    class Config:
        schema_extra = {
            "example": {
                "password": "NuevaPassword123",
                "celular": "71234567",
                "domicilio": "Nueva Dirección #456, La Paz, Bolivia",
                "foto_url": "https://storage.example.com/photos/nueva_foto.jpg",
                "ci_url": "https://storage.example.com/docs/ci_actualizado.pdf",
                "afiliacion_url": "https://storage.example.com/docs/afiliacion_actualizado.pdf",
                "cv_url": "https://storage.example.com/docs/cv_actualizado.pdf",
                "titulo": {
                    "titulo": "Licenciatura en Ingeniería de Sistemas",
                    "numero_titulo": "123456",
                    "año_expedicion": "2020",
                    "universidad": "Universidad Mayor de San Andrés",
                    "titulo_url": "https://storage.example.com/titulos/brandon.pdf"
                }
            }
        }


class StudentUpdateAdmin(BaseModel):
    """
    Schema para que un admin actualice cualquier campo de un estudiante
    
    Uso: PATCH /students/{id} (solo admins)
    
    Permite actualizar todos los campos excepto: id, created_at, updated_at
    """
    registro: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    nombre: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    carnet: Optional[str] = None
    extension: Optional[str] = None
    celular: Optional[str] = None
    domicilio: Optional[str] = None
    fecha_nacimiento: Optional[datetime] = None
    foto_url: Optional[str] = None
    es_estudiante_interno: Optional[TipoEstudiante] = None
    ci_url: Optional[str] = None
    afiliacion_url: Optional[str] = None
    cv_url: Optional[str] = None
    activo: Optional[bool] = None
    lista_cursos_ids: Optional[List[PyObjectId]] = None
    titulo: Optional[Title] = None
    
    class Config:
        schema_extra = {
            "example": {
                "registro": "220005959",
                "password": "NuevaPassword456",
                "nombre": "Juan Carlos Pérez",
                "email": "juan.perez@example.com",
                "carnet": "87654321",
                "extension": "LP",
                "celular": "77777777",
                "domicilio": "Calle Falsa #123, La Paz, Bolivia",
                "fecha_nacimiento": "1990-01-01T00:00:00",
                "foto_url": "https://storage.example.com/photos/juan.jpg",
                "es_estudiante_interno": "externo",
                "ci_url": "https://storage.example.com/docs/ci_juan.pdf",
                "afiliacion_url": "https://storage.example.com/docs/afiliacion_juan.pdf",
                "cv_url": "https://storage.example.com/docs/cv_juan.pdf",
                "activo": False,
                "lista_cursos_ids": [],
                "titulo": {
                    "titulo": "Licenciatura en Ingeniería de Sistemas",
                    "numero_titulo": "123456",
                    "año_expedicion": "2020",
                    "universidad": "Universidad Mayor de San Andrés",
                    "titulo_url": "https://storage.example.com/titulos/juan.pdf"
                }
            }
        }
