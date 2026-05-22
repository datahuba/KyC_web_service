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
from pydantic import BaseModel, Field, EmailStr, field_validator
from models.enums import TipoEstudiante
from models.base import PyObjectId


class ChangePassword(BaseModel):
    """
    Schema para cambiar contraseña de forma segura
    
    Requiere:
    - Contraseña actual (para verificación)
    - Nueva contraseña (2 veces para confirmación)
    """
    
    current_password: str = Field(..., description="Contraseña actual")
    new_password: str = Field(..., min_length=5, description="Nueva contraseña (mínimo 5 caracteres)")
    confirm_password: str = Field(..., min_length=5, description="Confirmar nueva contraseña")
    
    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v, info):
        """Validar que las contraseñas nuevas coincidan"""
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('Las contraseñas nuevas no coinciden')
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "current_password": "12345678",
                "new_password": "NuevaPassword123!",
                "confirm_password": "NuevaPassword123!"
            }
        }
    }


class StudentCreate(BaseModel):
    """
    Schema para crear un nuevo estudiante
    
    Uso: POST /students/
    
    El carnet se usará como contraseña inicial (será hasheada automáticamente).
    Solo registro y carnet son obligatorios.
    """
    
    # Campos obligatorios
    registro: str = Field(..., description="Número de registro único del estudiante (usado como username)")
    carnet: str = Field(..., description="Carnet de identidad (será usado como contraseña inicial y almacenado)")
    
    # Campos opcionales
    nombre: Optional[str] = Field(None, min_length=1, max_length=200, description="Nombre completo del estudiante")
    email: Optional[EmailStr] = Field(None, description="Correo electrónico")
    extension: Optional[str] = Field(None, description="Extension del carnet de identidad")
    celular: Optional[str] = Field(None, description="Número de celular para notificaciones")
    domicilio: Optional[str] = Field(None, description="Dirección física del estudiante")
    fecha_nacimiento: Optional[datetime] = Field(None, description="Fecha de nacimiento")
    es_estudiante_interno: Optional[TipoEstudiante] = Field(None, description="Tipo de estudiante: INTERNO o EXTERNO")

    model_config = {
        "json_schema_extra": {
            "example": {
                "registro": "20240001",
                "carnet": "12345678",
                "nombre": "María Fernanda López García",
                "email": "maria.lopez@estudiante.edu.bo",
                "extension": "LP",
                "celular": "70123456",
                "domicilio": "Av. 6 de Agosto #1234, La Paz, Bolivia",
                "fecha_nacimiento": "2000-05-15T00:00:00",
                "es_estudiante_interno": "interno"
            }
        }
    }



class StudentResponse(BaseModel):
    """
    Schema para mostrar información de un estudiante
    """
    
    id: PyObjectId = Field(..., alias="_id")
    registro: str
    nombre: Optional[str] = None
    email: Optional[EmailStr] = None
    carnet: Optional[str] = None
    extension: Optional[str] = None
    celular: Optional[str] = None
    domicilio: Optional[str] = None
    fecha_nacimiento: Optional[datetime] = None
    foto_url: Optional[str] = None
    es_estudiante_interno: Optional[TipoEstudiante] = None
    cv_url: Optional[str] = None
    carnet_url: Optional[str] = None
    afiliacion_url: Optional[str] = None
    titulo_url: Optional[str] = None
    titulo: Optional[str] = None
    numero_titulo: Optional[str] = None
    año_expedicion: Optional[str] = None
    universidad: Optional[str] = None
    estado_titulo: Optional[str] = "sin_titulo"
    
    # Estado y Metadata
    activo: bool
    lista_cursos_ids: List[PyObjectId] = []
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

                "created_at": "2024-03-20T10:00:00",
                "updated_at": "2024-03-20T10:00:00"
            }
        }
    }



class StudentUpdateSelf(BaseModel):
    """
    Schema para que un estudiante actualice su propio perfil
    
    Uso: PATCH /students/me o PATCH /students/{id} (si es el mismo estudiante)
    
    Permite actualizar información personal básica.
    
    Nota: 
    - No se permite cambiar la contraseña desde este endpoint (usar POST /auth/change-password)
    - Para subir foto de perfil: POST /students/me/upload/photo
    """
    
    celular: Optional[str] = None
    domicilio: Optional[str] = None
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "celular": "71234567",
                "domicilio": "Av. Libertador Simón Bolívar #456, El Alto, Bolivia"
            }
        }
    }



class StudentUpdateAdmin(BaseModel):
    """
    Schema para que un admin actualice cualquier campo de un estudiante
    
    Uso: PATCH /students/{id} (solo admins)
    
    Permite actualizar todos los campos excepto: id, created_at, updated_at
    
    Nota: Los documentos ahora se manejan en Enrollment.requisitos
    """
    registro: Optional[str] = None
    password: Optional[str] = Field(None, min_length=5)
    nombre: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    carnet: Optional[str] = None
    extension: Optional[str] = None
    celular: Optional[str] = None
    domicilio: Optional[str] = None
    fecha_nacimiento: Optional[datetime] = None
    es_estudiante_interno: Optional[TipoEstudiante] = None
    activo: Optional[bool] = None
    lista_cursos_ids: Optional[List[PyObjectId]] = None
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "registro": "20240002",
                "password": "NuevoPassword456!",
                "nombre": "Carlos Alberto Rojas Mamani",
                "email": "carlos.rojas@estudiante.edu.bo",
                "carnet": "87654321",
                "extension": "CB",
                "celular": "68765432",
                "domicilio": "Calle Junín #789, Cochabamba, Bolivia",
                "fecha_nacimiento": "1995-08-22T00:00:00",
                "es_estudiante_interno": "externo",
                "activo": True,
                "lista_cursos_ids": ["507f1f77bcf86cd799439012"]
            }
        }
    }

