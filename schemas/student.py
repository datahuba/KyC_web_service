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
import re
from pydantic import BaseModel, Field, EmailStr, field_validator, AliasChoices
from models.enums import Sexo, EstadoCivil, TipoSangre
from models.base import PyObjectId

# Helper para validar carnets con formato boliviano
# Acepta carnet puro (8130604) o con sufijo (8099472-1A, 8130604-1J) o float mal exportado (8130604.0)
_CARNET_RE = re.compile(r'^\d{5,12}([.\-,/][A-Z0-9]{1,3})?$')

def _carnet_valido_boliviano(v: str) -> bool:
    """True si el carnet tiene formato valido de Bolivia (con o sin sufijo de letra, float mal exportado)."""
    return bool(_CARNET_RE.match(v))


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
    
    El carnet se usará como contraseña inicial por defecto.
    Se puede enviar un password personalizado y un course_id opcionalmente.
    """
    
    # Campos obligatorios
    # FIX-ISSUE-260 (2026-08-14): aceptar `carnet_identidad` (UI) como
    # alias de `carnet`. Y `registro_universitario` como alias de `registro`.
    registro: str = Field(
        ...,
        description="Número de registro único del estudiante (usado como username)",
        validation_alias=AliasChoices("registro", "registro_universitario"),
    )
    carnet: str = Field(
        ...,
        description="Carnet de identidad (será usado como contraseña inicial y almacenado si no se provee un password)",
        validation_alias=AliasChoices("carnet", "carnet_identidad", "ci"),
    )

    # Campos opcionales nuevos (Para formulario rápido)
    password: Optional[str] = Field(None, min_length=5, description="Contraseña inicial del estudiante (opcional, fallback a carnet)")
    course_id: Optional[PyObjectId] = Field(None, description="ID del curso para inscripción inicial (opcional)")

    # Campos opcionales estándar
    # FIX-ISSUE-260: aceptar `nombre_completo` como alias de `nombre`.
    nombre: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Nombre completo del estudiante",
        validation_alias=AliasChoices("nombre", "nombre_completo", "full_name"),
    )
    email: Optional[EmailStr] = Field(None, description="Correo electrónico")
    complemento_carnet: Optional[str] = Field(None, max_length=10, description="Complemento del CI (ej. '1D', '1J'), distinto de la extensión/lugar de expedición.")
    extension: Optional[str] = Field(None, description="Extension del carnet de identidad")
    celular: Optional[str] = Field(None, description="Número de celular para notificaciones")
    domicilio: Optional[str] = Field(None, description="Dirección física del estudiante")
    fecha_nacimiento: Optional[datetime] = Field(None, description="Fecha de nacimiento")

    # Datos oficiales UAGRM (opcionales)
    sexo: Optional[Sexo] = None
    estado_civil: Optional[EstadoCivil] = None
    pais: Optional[str] = None
    departamento: Optional[str] = None
    provincia: Optional[str] = None
    nacionalidad: Optional[str] = None
    telefono: Optional[str] = None
    modalidad_ingreso: Optional[str] = None
    periodo: Optional[str] = None
    tipo_sangre: Optional[TipoSangre] = None
    titulo_bachiller: Optional[str] = None

    # F-2026-08-11-CAMPOS-EC: campos específicos del Diplomado Gestión
    # Tributaria y demás programas de educación continua (planilla de Lisa).
    registro_universitario: Optional[str] = Field(None, max_length=30)
    avance_academico_codigo: Optional[int] = Field(None, ge=0)
    formulario_descuento_numero: Optional[int] = Field(None, ge=0)
    carrera_codigo: Optional[str] = Field(None, max_length=20)
    descuento_porcentaje: Optional[float] = Field(None, ge=0, le=1)

    # F-2026-08-11-CAMPOS-EC-MODALIDAD (reunion UAGRM 2026-08-11).
    # procedencia (codigo departamento Bolivia), modalidad (presencial/virtual),
    # carta_firmada_url (PDF firmado por el director). Validacion detallada en
    # schemas/pre_registration.py al enviar el form publico.
    procedencia: Optional[str] = Field(None, max_length=10)
    modalidad: Optional[str] = Field(None, max_length=20)
    carta_firmada_url: Optional[str] = Field(None, max_length=500)

    # F-2026-08-11-CAMPOS-EC-RESOLUCION (Kevin 22:37): URL de la resolucion
    # del programa que el estudiante subio al preinscribirse. Es OPCIONAL
    # (tambien el admin puede subirla despues via /app/courses).
    resolucion_url: Optional[str] = Field(None, max_length=500)

    # F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12, reunion UAGRM):
    # Discriminacion primera carrera vs profesional con titulo.
    # es_primer_carrera=True: cobra matricula primer carrera (default 200).
    # es_primer_carrera=False: cobra matricula profesional (default 500) Y
    # titulo_profesional_url es OBLIGATORIA (validado por el encargado EC).
    es_primer_carrera: bool = Field(
        default=True,
        description="F-2026-08-12-DESCUENTO-BECA: True=primera carrera (cobra menos matricula), "
                    "False=ya tiene titulo profesional (cobra mas matricula)."
    )
    titulo_profesional_url: Optional[str] = Field(
        None, max_length=500,
        description="F-2026-08-12-DESCUENTO-BECA: URL de la foto del titulo profesional "
                    "(PDF/JPG/PNG en Cloudinary). Requerida si es_primer_carrera=False."
    )
    titulo_profesional_estado: str = Field(
        default="pendiente",
        description="F-2026-08-12-DESCUENTO-BECA: 'pendiente'|'verificado'|'rechazado'. "
                    "Lo setea el encargado EC al revisar el documento."
    )
    titulo_profesional_motivo_rechazo: Optional[str] = Field(
        None, max_length=500,
        description="F-2026-08-12-DESCUENTO-BECA: motivo si el encargado EC rechazo el titulo."
    )

    @field_validator('sexo', 'estado_civil', 'tipo_sangre', mode='before')
    @classmethod
    def _empty_enum_a_none(cls, v):
        # Los <select> del frontend envían "" cuando no se elige nada; para enums
        # opcionales eso debe interpretarse como None (no como valor inválido).
        if v == '' or v is None:
            return None
        return v

    @field_validator('password', mode='before')
    @classmethod
    def _password_vacio_a_none(cls, v):
        # El frontend envía "" cuando el campo de contraseña queda vacío. Sin este
        # validador, Pydantic evaluaba "" contra min_length=5 y rechazaba la
        # creación con "string should have at least 5 characters", aunque el
        # carnet estuviera presente para generar la contraseña por defecto.
        # Se normaliza "" -> None para que el servicio genere 'Uagrm.<carnet>'.
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @field_validator('carnet')
    @classmethod
    def _carnet_numerico(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        # F-CARNET-BOLIVIANO (2026-08-05, Kevin): aceptar carnet con:
        # - Solo digitos: '8130604'
        # - Sufijo de letra: '8099472-1A', '8130604-1J' (comun en Bolivia)
        # - Float mal exportado de Excel: '8130604.0' o '8130604,0'
        # Rechaza: texto, simbolos raros, letras sueltas
        if v and not _carnet_valido_boliviano(v):
            raise ValueError('El carnet debe contener solo numeros (admite sufijo tipo 1234567-1A).')
        # Normalizar float mal exportado: '8130604.0' -> '8130604'
        # y '8130604,0' -> '8130604' (algunos Excels usan coma como decimal)
        if v.endswith('.0') and v[:-2].isdigit():
            v = v[:-2]
        elif v.endswith(',0') and v[:-2].isdigit():
            v = v[:-2]
        return v

    @field_validator('celular', 'telefono')
    @classmethod
    def _telefono_numerico(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if v and not v.isdigit():
            raise ValueError('El teléfono/celular debe contener solo números.')
        return v or None

    model_config = {
        "json_schema_extra": {
            "example": {
                "registro": "20240001",
                "carnet": "12345678",
                "password": "MiClaveSegura123",
                "course_id": "507f1f77bcf86cd799439012",
                "nombre": "María Fernanda López García",
                "email": "maria.lopez@estudiante.edu.bo",
                "extension": "LP",
                "celular": "70123456",
                "domicilio": "Av. 6 de Agosto #1234, La Paz, Bolivia",
                "fecha_nacimiento": "2000-05-15T00:00:00"
            }
        }
    }



class StudentResponse(BaseModel):
    """
    Schema para mostrar información de un estudiante (Sincronizado con MongoDB y Svelte)
    """
    
    id: PyObjectId = Field(..., alias="_id")
    registro: str
    nombre: Optional[str] = None
    email: Optional[EmailStr] = None
    carnet: Optional[str] = None
    complemento_carnet: Optional[str] = None
    extension: Optional[str] = None
    celular: Optional[str] = None
    domicilio: Optional[str] = None
    fecha_nacimiento: Optional[datetime] = None
    foto_url: Optional[str] = None

    # Datos oficiales UAGRM
    sexo: Optional[Sexo] = None
    estado_civil: Optional[EstadoCivil] = None
    pais: Optional[str] = None
    departamento: Optional[str] = None
    provincia: Optional[str] = None
    nacionalidad: Optional[str] = None
    telefono: Optional[str] = None
    modalidad_ingreso: Optional[str] = None
    periodo: Optional[str] = None
    tipo_sangre: Optional[TipoSangre] = None
    titulo_bachiller: Optional[str] = None
    
    # DOCUMENTACIÓN (URLs de Cloudinary de los PDFs)
    cv_url: Optional[str] = None
    cv_estado: str = "pendiente"
    cv_motivo_rechazo: Optional[str] = None

    carnet_url: Optional[str] = None
    carnet_estado: str = "pendiente"
    carnet_motivo_rechazo: Optional[str] = None

    afiliacion_url: Optional[str] = None
    afiliacion_estado: str = "pendiente"
    afiliacion_motivo_rechazo: Optional[str] = None
    
    # OBJETO ANIDADO DEL TÍTULO PROFESIONAL
    titulo: Optional[dict] = None

    # F-2026-08-11-CAMPOS-EC: campos específicos educación continua
    registro_universitario: Optional[str] = None
    avance_academico_codigo: Optional[int] = None
    formulario_descuento_numero: Optional[int] = None
    carrera_codigo: Optional[str] = None
    descuento_porcentaje: Optional[float] = None

    # F-2026-08-11-CAMPOS-EC-MODALIDAD
    procedencia: Optional[str] = None
    modalidad: Optional[str] = None
    carta_firmada_url: Optional[str] = None
    # F-2026-08-11-CAMPOS-EC-RESOLUCION
    resolucion_url: Optional[str] = None

    # F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12): discriminacion
    # primera carrera vs profesional con titulo.
    es_primer_carrera: bool = True
    titulo_profesional_url: Optional[str] = None
    titulo_profesional_estado: str = "pendiente"
    titulo_profesional_motivo_rechazo: Optional[str] = None

    # F-2026-08-12-DESCUENTO-BECA-VALIDACION (Kevin 2026-08-12, post-reunion UAGRM):
    # descuento de vicerrectorado que el estudiante propuso. El encargado EC
    # debe validarlo explicitamente (mismo patron que el titulo profesional).
    # Si estado=aprobado, el descuento se aplica. Si rechazado, se cobra completo.
    descuento_vicerrectorado_monto: Optional[float] = None
    descuento_vicerrectorado_estado: str = "no_aplica"
    descuento_vicerrectorado_motivo_rechazo: Optional[str] = None

    # Estado y Metadata
    activo: bool
    lista_cursos_ids: List[PyObjectId] = []
    created_at: datetime
    updated_at: datetime

    # ISSUE-Q-PRE: Términos y Condiciones
    terminos_aceptados: bool = False
    fecha_aceptacion_terminos: Optional[datetime] = None
    
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
    """
    
    celular: Optional[str] = None
    domicilio: Optional[str] = None
    telefono: Optional[str] = None

    # Reunión postgrado 2026-07-09: el estudiante ahora puede completar/editar
    # sus propios datos oficiales UAGRM desde su perfil (antes solo CPD), para
    # aliviar la carga de CPD. Todos opcionales.
    sexo: Optional[Sexo] = None
    estado_civil: Optional[EstadoCivil] = None
    tipo_sangre: Optional[TipoSangre] = None
    pais: Optional[str] = None
    departamento: Optional[str] = None
    provincia: Optional[str] = None
    nacionalidad: Optional[str] = None
    modalidad_ingreso: Optional[str] = None
    periodo: Optional[str] = None
    titulo_bachiller: Optional[str] = None

    @field_validator('sexo', 'estado_civil', 'tipo_sangre', mode='before')
    @classmethod
    def _self_empty_enum_a_none(cls, v):
        if v == '' or v is None:
            return None
        return v

    @field_validator('celular', 'telefono')
    @classmethod
    def _self_telefono_numerico(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if v and not v.isdigit():
            raise ValueError('El teléfono/celular debe contener solo números.')
        return v or None
    
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
    """
    registro: Optional[str] = None
    password: Optional[str] = Field(None, min_length=5)
    nombre: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    carnet: Optional[str] = None
    complemento_carnet: Optional[str] = None
    extension: Optional[str] = None
    celular: Optional[str] = None
    domicilio: Optional[str] = None
    fecha_nacimiento: Optional[datetime] = None
    activo: Optional[bool] = None
    lista_cursos_ids: Optional[List[PyObjectId]] = None

    # Datos oficiales UAGRM (opcionales)
    sexo: Optional[Sexo] = None
    estado_civil: Optional[EstadoCivil] = None
    pais: Optional[str] = None
    departamento: Optional[str] = None
    provincia: Optional[str] = None
    nacionalidad: Optional[str] = None
    telefono: Optional[str] = None
    modalidad_ingreso: Optional[str] = None
    periodo: Optional[str] = None
    tipo_sangre: Optional[TipoSangre] = None
    titulo_bachiller: Optional[str] = None

    # F-2026-08-11-CAMPOS-EC
    registro_universitario: Optional[str] = Field(None, max_length=30)
    avance_academico_codigo: Optional[int] = Field(None, ge=0)
    formulario_descuento_numero: Optional[int] = Field(None, ge=0)
    carrera_codigo: Optional[str] = Field(None, max_length=20)
    descuento_porcentaje: Optional[float] = Field(None, ge=0, le=1)

    # F-2026-08-11-CAMPOS-EC-MODALIDAD
    procedencia: Optional[str] = Field(None, max_length=10)
    modalidad: Optional[str] = Field(None, max_length=20)
    carta_firmada_url: Optional[str] = Field(None, max_length=500)
    # F-2026-08-11-CAMPOS-EC-RESOLUCION
    resolucion_url: Optional[str] = Field(None, max_length=500)
    # F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12)
    es_primer_carrera: Optional[bool] = Field(
        default=None,
        description="F-2026-08-12-DESCUENTO-BECA: True=primera carrera, False=profesional con titulo. "
                    "Si no se envia, se conserva el valor actual del Student."
    )
    titulo_profesional_url: Optional[str] = Field(None, max_length=500)
    titulo_profesional_estado: Optional[str] = Field(
        default=None,
        description="F-2026-08-12-DESCUENTO-BECA: 'pendiente'|'verificado'|'rechazado'. "
                    "Si no se envia, se conserva el valor actual."
    )
    titulo_profesional_motivo_rechazo: Optional[str] = Field(None, max_length=500)

    @field_validator('sexo', 'estado_civil', 'tipo_sangre', mode='before')
    @classmethod
    def _admin_empty_enum_a_none(cls, v):
        if v == '' or v is None:
            return None
        return v

    @field_validator('carnet')
    @classmethod
    def _admin_carnet_numerico(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if v and not v.isdigit():
            raise ValueError('El carnet debe contener solo números.')
        return v

    @field_validator('celular', 'telefono')
    @classmethod
    def _admin_telefono_numerico(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if v and not v.isdigit():
            raise ValueError('El teléfono/celular debe contener solo números.')
        return v or None
    
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
                "activo": True,
                "lista_cursos_ids": ["507f1f77bcf86cd799439012"]
            }
        }
    }
    