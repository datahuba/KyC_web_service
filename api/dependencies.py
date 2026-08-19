"""
Dependencias de FastAPI
=======================

Dependencias para autenticación y autorización en endpoints.
"""

from typing import Optional, Union
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from beanie import PydanticObjectId

from core.security import decode_access_token
from models.user import User
from models.student import Student
from models.enums import UserRole, SubtipoCoordinador

ADMIN_OR_ABOVE = {UserRole.ADMIN, UserRole.SUPERADMIN}
DOCENTE_OR_ABOVE = {UserRole.DOCENTE, UserRole.ADMIN, UserRole.SUPERADMIN}


def puede_ver_economico(current_user) -> bool:
    """
    ISSUE-R-PERFIL-GENERICO: True si el usuario puede ver información económica
    (reportes de caja, resumen de ingresos, pagos). Roles económicos:
    superadmin, admin, mae, cobranza, encargado_curso; y COORDINADOR únicamente
    si su subtipo es FINANCIERO (los coordinadores académico/investigación NO
    ven lo económico).

    F-2026-08-22-EC-PAGOS-READONLY (Kevin 2026-08-22): encargado_curso entra
    tambien (en modo SOLO LECTURA). El filtro por cursos_asignados que ya
    está en cada endpoint se encarga de la segmentacion: el EC solo ve
    pagos/certificados/reportes de SUS cursos asignados, igual que en
    payments y certificates.
    """
    if not isinstance(current_user, User):
        return False
    if current_user.rol in {UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.MAE, UserRole.COBRANZA, UserRole.ENCARGADO_CURSO}:
        return True
    return (
        current_user.rol == UserRole.COORDINADOR
        and current_user.subtipo_coordinador == SubtipoCoordinador.FINANCIERO
    )

# Security scheme para JWT (auto_error=False permite bypass en modo desarrollo)
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Union[User, Student]:
    """
    Obtener el usuario actual desde el token JWT
    
    En modo desarrollo (DEVELOPMENT_MODE=True), retorna un usuario admin mock
    sin requerir autenticación.
    
    Returns:
        User o Student autenticado
        
    Raises:
        HTTPException 401: Si el token es inválido o el usuario no existe
    """
    from core.config import settings
    
    # Modo desarrollo: bypass de autenticación
    if settings.DEVELOPMENT_MODE:
        # Retornar un usuario SUPERADMIN mock para desarrollo
        mock_user = User(
            id=PydanticObjectId("000000000000000000000001"),
            username="dev_admin",
            password="mock_password",
            email="dev@example.com",
            rol=UserRole.SUPERADMIN,
            activo=True
        )
        return mock_user
    
    # Modo producción: autenticación normal
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    payload = decode_access_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id: str = payload.get("sub")
    user_type: str = payload.get("user_type")
    
    if user_id is None or user_type is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # AUDITORÍA (ALTO #7 - seguridad): los tokens de un solo propósito
    # (password_reset) llevan el mismo formato base que un token de sesión
    # normal (sub + user_type), así que sin este rechazo explícito servían
    # como credencial de sesión completa durante sus 30 min de vigencia en
    # CUALQUIER endpoint protegido, no solo en /reset-password.
    if payload.get("purpose") == "password_reset":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Este token es de un solo uso para restablecer la contraseña, no es válido para autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ISSUE-A-VERIFICACION: mismo criterio que password_reset -- este token
    # solo sirve para confirmar un correo, no como credencial de sesión.
    if payload.get("purpose") == "email_verification":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Este token es de un solo uso para verificar tu correo, no es válido para autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Buscar usuario según el tipo
    if user_type == "user":
        user = await User.get(PydanticObjectId(user_id))
        if user is None or not user.activo:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario no encontrado o inactivo"
            )
        return user
    elif user_type == "student":
        student = await Student.get(PydanticObjectId(user_id))
        if student is None or not student.activo:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Estudiante no encontrado o inactivo"
            )
        return student
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de usuario inválido"
        )


def require_superadmin(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario sea SUPERADMIN
    
    Solo usuarios de tipo User con rol SUPERADMIN pueden pasar
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de SUPERADMIN"
        )
    
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de SUPERADMIN"
        )
    
    return current_user


def require_docente(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario sea DOCENTE, ADMIN o SUPERADMIN
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de DOCENTE o superior"
        )

    if current_user.rol not in DOCENTE_OR_ABOVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de DOCENTE o superior"
        )

    return current_user


def require_admin(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario sea ADMIN o SUPERADMIN
    
    Solo usuarios de tipo User con rol ADMIN o SUPERADMIN pueden pasar
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de ADMIN o superior"
        )
    
    if current_user.rol not in ADMIN_OR_ABOVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de ADMIN o superior"
        )
    
    return current_user


def require_cpd(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario pertenezca al Centro de Procesamiento de Datos (CPD) o superior
    
    Permite el acceso a roles: CPD, ADMIN y SUPERADMIN
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere credenciales de nivel CPD o superior administrativo"
        )
    
    if current_user.rol not in [UserRole.CPD, UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Esta acción académica está reservada para el CPD o Administración"
        )
    
    return current_user


def require_cobranza(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario pertenezca al área de Cobranzas o superior
    
    Permite el acceso a roles: COBRANZA, ADMIN y SUPERADMIN
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere credenciales del área de Cobranzas o superior"
        )
    
    if current_user.rol not in [UserRole.COBRANZA, UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Esta acción de conciliación de caja está reservada para Cobranzas o Administración"
        )
    
    return current_user


def require_mae(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario sea Máxima Autoridad Ejecutiva (MAE) o superior
    
    Permite el acceso a roles: MAE, ADMIN y SUPERADMIN
    Uso: Adecuado para endpoints analíticos y estadísticos de solo lectura (ingresos, desgloses)
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere nivel de acceso MAE (Lector) o superior"
        )
    
    if current_user.rol not in [UserRole.MAE, UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Esta sección analítica de toma de decisiones está reservada para MAE o Administración"
        )
    
    return current_user


def require_encargado_curso(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario sea Encargado de Curso, Coordinador (supervisa), CPD o superior.

    Permite el acceso a roles: ENCARGADO_CURSO, COORDINADOR, CPD, ADMIN y SUPERADMIN.
    (ISSUE-R-ROLES)
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere credenciales de Encargado de Curso o superior"
        )

    allowed = [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR, UserRole.CPD, UserRole.ADMIN, UserRole.SUPERADMIN]
    if current_user.rol not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Esta acción está reservada para el Encargado de Curso o Administración"
        )

    return current_user


def require_gestion_academica(
    current_user: User = Depends(require_encargado_curso),
) -> User:
    """
    F-FIX-COORD-FINANCIERO-NO-ACADEMICO (2026-08-19, Kevin): "financiero no
    deberia crear programas ni editar, tampoco estudiantes". Su alcance es
    economico (ve todo, aprueba No Deudor), no gestion de contenido
    academico.

    Igual que require_encargado_curso, pero excluye especificamente al
    COORDINADOR con subtipo FINANCIERO. Se usa SOLO en las acciones que
    Kevin nombro: crear/editar programas, cargar estudiantes (individual,
    lote o Excel) y cargar notas de modulos ejecutados. El resto de lo que
    permite require_encargado_curso (ver estudiantes, enviar comunicados,
    formularios de pre-inscripcion) sigue igual para el financiero — no se
    toco la dependencia compartida para no afectar esos otros endpoints sin
    que Kevin lo haya pedido.
    """
    if (
        current_user.rol == UserRole.COORDINADOR
        and current_user.subtipo_coordinador == SubtipoCoordinador.FINANCIERO
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "El coordinador financiero no gestiona el contenido académico "
                "de los programas (crear/editar programas, cargar estudiantes "
                "o notas). Su alcance es económico."
            ),
        )
    return current_user


def require_coordinador(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario sea Coordinador, ADMIN o SUPERADMIN.
    (ISSUE-R-ROLES)
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere credenciales de Coordinador o superior"
        )

    if current_user.rol not in [UserRole.COORDINADOR, UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Esta sección está reservada para Coordinación o Administración"
        )

    return current_user


def require_extracto_bancario(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere Cobranza, ADMIN o SUPERADMIN.
    (ISSUE-P-EXTRACTO): registro y cruce manual del extracto bancario.
    CPD queda EXCLUIDO: el extracto bancario es información económica y CPD no
    ve dinero (regla del usuario: "CPD nada de dinero salvo la matrícula").
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere credenciales de Cobranza o Administración"
        )

    allowed = [UserRole.COBRANZA, UserRole.ADMIN, UserRole.SUPERADMIN]
    if current_user.rol not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido a Cobranza o Administración (información económica)"
        )

    return current_user


def filtro_cursos_por_rol(current_user: User) -> Optional[dict]:
    """
    Devuelve un filtro Mongo para segmentar resultados por curso, o None si el usuario
    tiene acceso total (sin restricción).

    (ISSUE-R-ROLES / ISSUE-P-SEGMENTACION): reutilizable en cualquier servicio que liste
    inscripciones/estudiantes/pagos filtrando por curso.

    ISSUE-P-SEGMENTACION: COBRANZA se segmenta igual que ENCARGADO_CURSO SOLO SI
    tiene cursos_asignados no vacío (mismo criterio usado en ISSUE-R-VISTA-CURSOS
    para separar "Usuarios Globales" de "Asignados a Curso(s)"). Un cajero sin
    cursos marcados conserva acceso total, para no romper cuentas de Cobranza
    ya existentes que nunca se configuraron con cursos específicos.

    F-2026-08-12-EC-CURSOS-FILTRO (Kevin 2026-08-12 post-reunion UAGRM):
    extender el filtro a COORDINADOR tambien (supervisa EC de su area, debe
    ver solo datos de los cursos que supervisa, que son los mismos cursos
    asignados). Esto unifica el comportamiento EC + COORDINADOR + COBRANZA.

    F-FIX-COORD-FINANCIERO-VE-TODO (2026-08-19, Kevin): la regla de arriba
    resultaba INCORRECTA para el subtipo FINANCIERO. Kevin: "el coordinador
    deberia poder ver todo lo economico (...) los coordinadores ven los
    resumenes de todo dependientes de su area, en este caso hablamos de
    finanzas". El area de un financiero es lo economico en si, transversal
    a TODOS los programas — no un subconjunto de cursos_asignados.
    Sin esta excepcion, un coordinador financiero recien creado (sin
    cursos_asignados cargados) veia TODO en blanco en pagos e inscripciones
    ($in: [] no matchea nada) — el mismo sintoma que el bug del encargado
    arreglado el dia anterior (F-FIX-PAGOS-EC-EN-BLANCO).
    Kevin confirmo explicitamente: financiero SIEMPRE ve todo (sin
    excepcion, a diferencia de Cobranza que solo ve todo si tiene
    cursos_asignados vacio); academico e investigacion SIGUEN acotados a
    sus cursos_asignados, porque supervisan encargados de curso puntuales.
    """
    if (
        current_user.rol == UserRole.COORDINADOR
        and current_user.subtipo_coordinador == SubtipoCoordinador.FINANCIERO
    ):
        return None
    if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        return {"curso_id": {"$in": current_user.cursos_asignados}}
    if current_user.rol == UserRole.COBRANZA and current_user.cursos_asignados:
        return {"curso_id": {"$in": current_user.cursos_asignados}}
    return None


def filtro_cursos_por_rol_estricto(current_user: User) -> Optional[dict]:
    """
    Igual que filtro_cursos_por_rol pero retorna filtro incluso si cursos_asignados
    está vacío (devuelve $in [] = no muestra nada). Usar SOLO en endpoints que
    tienen sentido semántico de "0 cursos = 0 datos" (ej. dashboard del EC).

    F-2026-08-12-EC-CURSOS-FILTRO (Kevin 2026-08-12): el EC sin cursos asignados
    NO debe ver datos de TODOS los cursos por accidente. Si no tiene cursos,
    no ve nada (mejor que ver todo por error de config).
    """
    if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        cursos = current_user.cursos_asignados or []
        return {"curso_id": {"$in": cursos}}
    if current_user.rol == UserRole.COBRANZA and current_user.cursos_asignados:
        return {"curso_id": {"$in": current_user.cursos_asignados}}
    return None


def get_current_active_user(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Union[User, Student]:
    """
    Obtener usuario activo (cualquier rol autenticado)
    
    Alias para get_current_user, útil para endpoints que aceptan cualquier usuario autenticado
    """
    return current_user


def check_student_access(
    resource_student_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> bool:
    """
    Verificar si el usuario puede acceder a un recurso de estudiante
    
    - SUPERADMIN/ADMIN/MAE/CPD/COBRANZA (Cuentas tipo User): Pueden acceder a cualquier recurso
    - STUDENT: Solo puede acceder a sus propios recursos
    
    Args:
        resource_student_id: ID del estudiante dueño del recurso
        current_user: Usuario actual
        
    Returns:
        True si tiene acceso
        
    Raises:
        HTTPException 403: Si no tiene acceso
    """
    # Admins y personal administrativo con cuenta tipo User tienen acceso total a recursos de estudiantes
    if isinstance(current_user, User):
        return True
    
    # Estudiantes solo acceden a sus propios recursos
    if isinstance(current_user, Student):
        if current_user.id != resource_student_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para acceder a este recurso"
            )
        return True
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acceso denegado"
    )
def require_staff(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere cualquier rol del personal administrativo de Posgrado.
    Permite el acceso a: ADMIN, SUPERADMIN, MAE, CPD y COBRANZA.
    (Docentes y Estudiantes son bloqueados).
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere cuenta de personal administrativo."
        )
    
    staff_roles = [
        UserRole.ADMIN, UserRole.SUPERADMIN, UserRole.MAE, UserRole.CPD, UserRole.COBRANZA,
        UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR,  # ISSUE-R-ROLES
    ]
    if current_user.rol not in staff_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. No tienes permisos para ver esta sección administrativa."
        )
    
    return current_user
