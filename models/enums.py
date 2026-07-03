"""
Enumeraciones del Sistema
=========================

Este módulo define todas las enumeraciones (valores predefinidos) usadas en el sistema.

¿Por qué usar Enums?
-------------------
Las enumeraciones garantizan que los campos solo puedan tener valores específicos:

1. **Validación automática**: Pydantic rechaza valores no permitidos
2. **Autocompletado**: Los IDEs pueden sugerir valores válidos
3. **Documentación**: Queda claro qué valores son aceptables
4. **Prevención de errores**: No se pueden usar valores incorrectos por typos

Ejemplo sin Enum (MALO):
    estado = "actibo"  # Typo, pero se acepta

Ejemplo con Enum (BUENO):
    estado = EstadoInscripcion.ACTIVO  # Validado, sin errores
"""

from enum import Enum


class TipoCurso(str, Enum):
    """
    Tipos de programas académicos disponibles
    """
    CURSO = "curso"
    TALLER = "taller"
    DIPLOMADO = "diplomado"
    MAESTRIA = "maestría"
    DOCTORADO = "doctorado"
    OTRO = "otro"


class EstadoTitulo(str, Enum):
    """
    Estados de validación de un título profesional
    """
    SIN_TITULO = "sin_titulo"
    PENDIENTE = "pendiente"
    VERIFICADO = "verificado"
    RECHAZADO = "rechazado"


class Modalidad(str, Enum):
    """
    Modalidades de enseñanza disponibles
    """
    PRESENCIAL = "presencial"
    VIRTUAL = "virtual"
    HIBRIDO = "híbrido"


class EstadoInscripcion(str, Enum):
    """
    Estados posibles de una inscripción
    """
    PENDIENTE_PAGO = "pendiente_pago"
    ACTIVO = "activo"
    SUSPENDIDO = "suspendido"
    COMPLETADO = "completado"
    CANCELADO = "cancelado"


class TipoPago(str, Enum):
    """
    Tipos de plan de pago disponibles
    """
    CONTADO = "contado"
    CUOTAS = "cuotas"


class EstadoPago(str, Enum):
    """
    Estados de un pago individual
    
    Flujo de trabajo ampliado (ISSUE-P-CANALES):
    -------------------------------------------
    PENDIENTE → APROBADO (dinero sumado a saldo)
    PENDIENTE → RECHAZADO (voucher inválido)
    APROBADO  → ANULADO (reversión de fondos por cheque rebotado)
    """
    PENDIENTE = "pendiente"
    RECHAZADO = "rechazado"
    APROBADO = "aprobado"
    ANULADO = "anulado"  # NUEVO: Rollback Financiero


class TipoTitulo(str, Enum):
    """
    Tipos de títulos/certificados que se pueden emitir
    """
    CERTIFICADO = "certificado"
    DIPLOMA = "diploma"
    TITULO_MAESTRIA = "título de maestría"
    TITULO_DOCTORADO = "título de doctorado"


class TipoEstudiante(str, Enum):
    """
    Tipo de estudiante según su relación con la universidad
    """
    INTERNO = "interno"
    EXTERNO = "externo"


class Sexo(str, Enum):
    """Sexo del estudiante (dato oficial UAGRM)"""
    MASCULINO = "masculino"
    FEMENINO = "femenino"


class EstadoCivil(str, Enum):
    """Estado civil del estudiante (dato oficial UAGRM)"""
    SOLTERO = "soltero"
    CASADO = "casado"
    DIVORCIADO = "divorciado"
    VIUDO = "viudo"
    OTRO = "otro"


class TipoSangre(str, Enum):
    """Grupo sanguíneo del estudiante (dato oficial UAGRM)"""
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class EstadoRequisito(str, Enum):
    """
    Estados de validación de un requisito/documento
    """
    PENDIENTE = "pendiente"        
    EN_PROCESO = "en_proceso"      
    APROBADO = "aprobado"          
    RECHAZADO = "rechazado"        


class UserRole(str, Enum):
    """
    Roles de usuario para control de acceso (RBAC) en la UAGRM
    """
    DOCENTE = "docente"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"
    MAE = "mae"
    CPD = "cpd"
    COBRANZA = "cobranza"


class AssignmentType(str, Enum):
    """Tipo de actividad evaluable en un classroom"""
    TASK = "TASK"
    EXAM = "EXAM"


class SubmissionStatus(str, Enum):
    """Estado de la entrega de un estudiante"""
    PENDING = "pending"      
    SUBMITTED = "submitted"  
    GRADED = "graded"
    