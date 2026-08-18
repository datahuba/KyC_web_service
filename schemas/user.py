"""
Schemas de Usuario
==================

Define los schemas Pydantic para operaciones CRUD de usuarios del sistema.

Schemas incluidos:
-----------------
1. UserCreate: Para crear nuevos usuarios
2. UserResponse: Para mostrar usuarios (sin password)
3. UserUpdate: Para actualizar usuarios
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator, AliasChoices
from models.enums import UserRole, SubtipoCoordinador, AmbitoFormacion, MAX_PROGRAMAS_POR_ENCARGADO
from models.base import PyObjectId

# Roles que requieren nombre_funcional obligatorio (ISSUE-R-ROLES + ISSUE-R-PERFIL-GENERICO)
# Estos roles rotan de persona con frecuencia; identificarlos por función/programa
# (no por el nombre de quien lo ocupa) permite rotar al responsable sin perder
# historial ni migrar datos entre cuentas.
_ROLES_REQUIEREN_NOMBRE_FUNCIONAL = {UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR, UserRole.COBRANZA}


class UserCreate(BaseModel):
    """
    Schema para crear un nuevo usuario

    Uso: POST /users/
    """
    username: str = Field(..., min_length=3, description="Nombre de usuario único")
    email: EmailStr = Field(..., description="Correo electrónico único")
    # GAP-1 (audio 2026-07-08): password ahora es opcional al crear. Si se omite
    # y se proveyó `carnet`, se autogenera como 'Uagrm.<CI>' (convención UAGRM
    # confirmada por el usuario para docentes/personal nuevo). Si no hay carnet
    # ni password, se rechaza explícitamente (ver validador abajo).
    password: Optional[str] = Field(None, min_length=5, description="Contraseña (será hasheada). Opcional si se provee 'carnet': se autogenera como 'Uagrm.<CI>'.")
    # F-FIX-USERS-ROLE-OBLIGATORIO (2026-08-10, Kevin): 'rol' es OBLIGATORIO.
    # Antes tenía default=ADMIN, lo cual causaba escalada silenciosa de
    # privilegios: si el cliente enviaba 'role' (inglés) o cualquier typo,
    # Pydantic lo ignoraba silenciosamente y el user se creaba como ADMIN
    # por default. Ahora 'rol' debe especificarse explícitamente.
    # Acepta tanto 'rol' (español, nombre interno) como 'role' (inglés, alias)
    # para compatibilidad con clientes que usan el nombre inglés.
    rol: UserRole = Field(..., description="Rol de usuario (obligatorio)", validation_alias=AliasChoices('rol', 'role'))

    # GAP-1 (audio 2026-07-08): CI del personal, usado para la contraseña por defecto.
    carnet: Optional[str] = Field(None, max_length=20, description="Carnet de Identidad (CI). Si se provee y no hay password, la contraseña inicial será 'Uagrm.<CI>'.")

    # ISSUE-R-ROLES
    nombre_funcional: Optional[str] = Field(
        None, max_length=150, validate_default=True,
        description="Nombre por función/programa. Obligatorio si rol es ENCARGADO_CURSO o COORDINADOR."
    )
    cursos_asignados: List[PyObjectId] = Field(
        default_factory=list,
        description="IDs de cursos asignados. Relevante si rol es ENCARGADO_CURSO o COBRANZA."
    )
    # ISSUE-R-PERFIL-GENERICO: subtipo del coordinador (obligatorio si rol=COORDINADOR)
    subtipo_coordinador: Optional[SubtipoCoordinador] = Field(
        None, validate_default=True,
        description="Subtipo del Coordinador (financiero/academico/investigacion). Obligatorio si rol es COORDINADOR."
    )

    @field_validator("nombre_funcional")
    @classmethod
    def validar_nombre_funcional(cls, v, info):
        rol = info.data.get("rol")
        if rol in _ROLES_REQUIEREN_NOMBRE_FUNCIONAL and not v:
            raise ValueError("nombre_funcional es obligatorio para los roles Encargado de Curso, Coordinador y Cobranza")
        return v

    # P-AMBITO-FORMACION (2026-08-18, Kevin): "separar las cuentas de
    # encargados de los de educacion continua y los de profesionales, asi
    # sabemos cual es cual". Define que campos de matricula ve al crear un
    # programa y el ambito por defecto de los programas que crea.
    ambito: Optional[AmbitoFormacion] = None

    @field_validator("subtipo_coordinador")
    @classmethod
    def validar_subtipo_coordinador(cls, v, info):
        if info.data.get("rol") == UserRole.COORDINADOR and not v:
            raise ValueError("subtipo_coordinador es obligatorio para el rol Coordinador (financiero/academico/investigacion)")
        return v

    @model_validator(mode="after")
    def validar_password_o_carnet(self):
        # GAP-1: si no hay password explícita, se exige carnet para poder
        # autogenerar 'Uagrm.<CI>' en create_user(). Sin ninguno de los dos,
        # no hay forma de que la cuenta tenga una contraseña válida.
        # Se usa model_validator (no field_validator) porque 'carnet' se
        # declara después de 'password' y por lo tanto no estaría disponible
        # todavía en info.data dentro de un validador de campo individual.
        if not self.password and not self.carnet:
            raise ValueError("Debes proveer 'password' o 'carnet' (la contraseña se autogenera como 'Uagrm.<CI>').")
        return self

    @model_validator(mode="after")
    def validar_limite_programas(self):
        # F-2026-08-11-LIMITE-10: antes 5, ahora 10 (reunión EC 2026-08-11).
        if self.rol == UserRole.ENCARGADO_CURSO and self.cursos_asignados and len(self.cursos_asignados) > MAX_PROGRAMAS_POR_ENCARGADO:
            raise ValueError(f"Un encargado de curso puede tener máximo {MAX_PROGRAMAS_POR_ENCARGADO} programas asignados")
        return self

    # F-FIX-USERS-ROLE-OBLIGATORIO (2026-08-10, Kevin): usar populate_by_name
    # para aceptar tanto 'rol' (español, nombre interno) como 'role' (inglés,
    # alias). Antes, los clientes que enviaban 'role' lo hacían silenciosamente
    # ignorado, y el default=ADMIN hacía que se creara como admin.
    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "username": "admin.finanzas",
                "email": "finanzas@kyc.edu.bo",
                "password": "KycSecure2024!",
                "rol": "admin"
            }
        }
    }

class UserResponse(BaseModel):
    """
    Schema para mostrar información de un usuario

    Uso: GET /users/{id}

    F-071 (2026-07-28): estandarización a `role` (inglés) en la respuesta JSON.
    Internamente el modelo Beanie sigue usando `rol` (español), pero en la
    respuesta HTTP el campo se serializa como `role` para coincidir con
    `/auth/me` (CurrentUserResponse) y con lo que el frontend espera.
    Antes el frontend usaba el fallback defensivo `user.role || user.rol`
    porque el modelo User se serializaba como `rol` y el CurrentUserResponse
    como `role` — inconsistencia que este cambio resuelve en backend.
    """
    id: PyObjectId = Field(..., alias="_id")
    username: str
    email: EmailStr
    # F-071: `rol` (Python/Beanie) -> `role` (JSON API). populate_by_name=True
    # permite que `from_attributes=True` lea `user.rol` del modelo, y la
    # serialización genera el campo `role` en la respuesta.
    rol: UserRole = Field(..., serialization_alias="role")
    activo: bool
    ultimo_acceso: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    nombre_funcional: Optional[str] = None
    cursos_asignados: List[PyObjectId] = Field(default_factory=list)
    carnet: Optional[str] = None  # GAP-1
    subtipo_coordinador: Optional[SubtipoCoordinador] = None  # ISSUE-R-PERFIL-GENERICO
    # P-AMBITO-FORMACION (2026-08-18, Kevin): "separar las cuentas de
    # encargados de los de educacion continua y los de profesionales, asi
    # sabemos cual es cual". Define que campos de matricula ve al crear un
    # programa y el ambito por defecto de los programas que crea.
    ambito: Optional[AmbitoFormacion] = None
    cv_url: Optional[str] = None  # HOJA-DE-VIDA-DOCENTE


    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439015",
                "username": "admin.academico",
                "email": "academico@kyc.edu.bo",
                "rol": "admin",
                "activo": True,
                "ultimo_acceso": "2024-12-18T16:45:00",
                "created_at": "2024-02-01T09:00:00",
                "updated_at": "2024-12-18T16:45:00"
            }
        }
    }

class UserUpdate(BaseModel):
    """
    Schema para actualizar un usuario existente
    
    Uso: PATCH /users/{id}
    """
    username: Optional[str] = Field(None, min_length=3)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=5)
    rol: Optional[UserRole] = None
    activo: Optional[bool] = None
    nombre_funcional: Optional[str] = Field(None, max_length=150, validate_default=True)
    cursos_asignados: Optional[List[PyObjectId]] = None
    carnet: Optional[str] = Field(None, max_length=20)  # GAP-1
    subtipo_coordinador: Optional[SubtipoCoordinador] = None  # ISSUE-R-PERFIL-GENERICO
    # P-AMBITO-FORMACION (2026-08-18, Kevin): "separar las cuentas de
    # encargados de los de educacion continua y los de profesionales, asi
    # sabemos cual es cual". Define que campos de matricula ve al crear un
    # programa y el ambito por defecto de los programas que crea.
    ambito: Optional[AmbitoFormacion] = None
    cv_url: Optional[str] = None  # HOJA-DE-VIDA-DOCENTE

    @field_validator("nombre_funcional")
    @classmethod
    def validar_nombre_funcional(cls, v, info):
        rol = info.data.get("rol")
        if rol in _ROLES_REQUIEREN_NOMBRE_FUNCIONAL and not v:
            raise ValueError("nombre_funcional es obligatorio para los roles Encargado de Curso, Coordinador y Cobranza")
        return v

    @field_validator("subtipo_coordinador")
    @classmethod
    def validar_subtipo_coordinador(cls, v, info):
        if info.data.get("rol") == UserRole.COORDINADOR and not v:
            raise ValueError("subtipo_coordinador es obligatorio para el rol Coordinador (financiero/academico/investigacion)")
        return v

    @model_validator(mode="after")
    def validar_limite_programas(self):
        # F-2026-08-11-LIMITE-10: antes 5, ahora 10 (reunión EC 2026-08-11).
        # Para UserUpdate, 'rol' puede ser None si no se envió en el PATCH,
        # pero asumimos que la validación completa en update_user en backend también pasará si es necesario.
        if self.rol == UserRole.ENCARGADO_CURSO and self.cursos_asignados and len(self.cursos_asignados) > MAX_PROGRAMAS_POR_ENCARGADO:
            raise ValueError(f"Un encargado de curso puede tener máximo {MAX_PROGRAMAS_POR_ENCARGADO} programas asignados")
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "nuevoemail@kyc.edu.bo",
                "activo": False
            }
        }
    }
