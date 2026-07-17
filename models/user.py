"""
Modelo de Usuario
=================

Gestiona los usuarios del sistema (administradores, staff, etc).
Colección MongoDB: users
"""

from datetime import datetime
from typing import Optional, List
import pymongo
from pydantic import Field, EmailStr
from .base import MongoBaseModel, PyObjectId
from .enums import UserRole, SubtipoCoordinador

class User(MongoBaseModel):
    """
    Modelo de Usuario del Sistema
    
    Representa a cualquier usuario que puede hacer login en el sistema administrativo.
    Nota: Los estudiantes tienen su propio modelo (Student), aunque podrían unificarse en el futuro.
    """
    
    username: str = Field(..., min_length=3, description="Nombre de usuario único")
    email: EmailStr = Field(..., description="Correo electrónico único")
    password: str = Field(..., description="Contraseña hasheada")
    
    rol: UserRole = Field(default=UserRole.ADMIN, description="Rol para permisos")
    activo: bool = Field(default=True, description="Si el usuario puede acceder al sistema")
    ultimo_acceso: Optional[datetime] = Field(None, description="Fecha del último login exitoso")

    # GAP-1 (audio 2026-07-08): Carnet de Identidad del personal (docentes/staff).
    # Si se completa al crear el usuario y no se especifica contraseña, se genera
    # automáticamente como 'Uagrm.<CI>' (convención institucional confirmada por
    # el usuario). Opcional y sin índice único: no reemplaza al username.
    carnet: Optional[str] = Field(
        None,
        max_length=20,
        description="Carnet de Identidad (CI) del personal. Si se completa y no se especifica contraseña al crear, se genera automáticamente como 'Uagrm.<CI>'."
    )

    # ISSUE-R-ROLES / ISSUE-R-PERFIL-GENERICO: nombre por función/programa (no por
    # persona) para roles rotativos. Obligatorio para ENCARGADO_CURSO, COORDINADOR
    # y COBRANZA (perfiles institucionales que rotan de responsable con frecuencia).
    nombre_funcional: Optional[str] = Field(
        None,
        max_length=150,
        description="Nombre por función/programa (ej. 'Encargado Maestría Gerencia Tributaria', 'Cajero Ventanilla 1'). Obligatorio si rol es ENCARGADO_CURSO, COORDINADOR o COBRANZA."
    )

    # ISSUE-R-ROLES / ISSUE-P-SEGMENTACION: cursos que este usuario puede operar (ENCARGADO_CURSO o COBRANZA)
    cursos_asignados: List[PyObjectId] = Field(
        default_factory=list,
        description="IDs de cursos asignados a este usuario. Relevante si rol es ENCARGADO_CURSO o COBRANZA."
    )

    # ISSUE-R-PERFIL-GENERICO: subtipo del COORDINADOR (financiero/academico/investigacion).
    # Solo el coordinador FINANCIERO tiene acceso a la información económica.
    subtipo_coordinador: Optional[SubtipoCoordinador] = Field(
        None,
        description="Subtipo del rol Coordinador. Solo 'financiero' ve lo económico. Obligatorio si rol es COORDINADOR."
    )

    # ISSUE-A-VERIFICACION: Verificación de Correo Electrónico (NO bloqueante)
    email_verificado: bool = Field(default=False, description="Si el usuario confirmó que su correo es válido y accesible. No bloquea el acceso al sistema.")
    fecha_verificacion_email: Optional[datetime] = Field(default=None, description="Fecha (UTC) en que se verificó el correo actual. Se reinicia a None si el correo cambia.")

    # HOJA-DE-VIDA-DOCENTE: Subida de CV para docentes
    cv_url: Optional[str] = Field(None, description="URL de la hoja de vida (CV) del docente (aplica principalmente al rol docente)")

    # ========================================================================
    # ISSUE-R-PERFIL-GENERICO (2026-07-08, reunión de postgrado contaduría)
    # ========================================================================
    @property
    def nombre_visible(self) -> str:
        """
        Identidad institucional a mostrar/registrar en auditoría, notificaciones
        y cualquier lugar donde se atribuya una acción a "quien la hizo".

        Los perfiles administrativos rotativos (Cobranza, Encargado de Curso,
        Coordinador) deben identificarse por FUNCIÓN/PROGRAMA (ej. "Cajero
        Ventanilla 1", "Encargado Maestría Gerencia Tributaria"), no por el
        nombre de la persona que ocupa el cargo hoy -- así el historial de
        acciones (pagos aprobados, notas validadas, solicitudes revisadas,
        etc.) sigue siendo coherente aunque la persona real detrás del cargo
        cambie con el tiempo, sin necesidad de migrar datos entre cuentas.

        Devuelve `nombre_funcional` si está definido, o `username` como
        fallback (roles sin nombre_funcional -- admin/superadmin/mae/cpd/
        docente -- siguen identificándose por su username, comportamiento
        sin cambios para ellos).
        """
        return self.nombre_funcional or self.username

    class Settings:
        name = "users"
        indexes = [
            # username es el credencial de login ÚNICO de cada perfil administrativo.
            pymongo.IndexModel([("username", pymongo.ASCENDING)], unique=True),
            # email NO es único a propósito: una misma persona puede tener varios
            # perfiles funcionales (ej. Cobranza de un programa + Encargado del
            # mismo programa) con el MISMO correo de contacto. El login se hace
            # por username. El índice se mantiene (no único) solo para búsquedas.
            pymongo.IndexModel([("email", pymongo.ASCENDING)], unique=False)
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "username": "admin",
                "email": "admin@kyc.com",
                "password": "hashed_secret_password",
                "rol": "admin",
                "activo": True
            }
        }
        