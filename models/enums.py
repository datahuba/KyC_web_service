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
    
    ¿Por qué necesitamos esto?
    -------------------------
    El sistema maneja diferentes niveles de programas académicos, cada uno
    con características distintas (duración, requisitos, certificación).
    
    Valores:
    -------
    - CURSO: Programas cortos, generalmente de actualización
    - TALLER: Programas prácticos y específicos
    - DIPLOMADO: Programas de especialización (6-12 meses)
    - MAESTRIA: Posgrado de maestría (1-2 años)
    - DOCTORADO: Posgrado doctoral (3-5 años)
    - OTRO: Para casos especiales no categorizados
    
    Uso en el sistema:
    -----------------
    - Filtrar cursos por tipo
    - Determinar requisitos de inscripción
    - Generar el tipo de título/certificado correcto
    """
    CURSO = "curso"
    TALLER = "taller"
    DIPLOMADO = "diplomado"
    MAESTRIA = "maestría"
    DOCTORADO = "doctorado"
    OTRO = "otro"


class Modalidad(str, Enum):
    """
    Modalidades de enseñanza disponibles
    
    ¿Por qué necesitamos esto?
    -------------------------
    La modalidad afecta:
    - Logística (aulas, plataformas virtuales)
    - Precios (virtual puede ser más económico)
    - Requisitos técnicos (internet, equipos)
    
    Valores:
    -------
    - PRESENCIAL: Clases físicas en campus
    - VIRTUAL: 100% en línea
    - HIBRIDO: Combinación de presencial y virtual
    
    Uso en el sistema:
    -----------------
    - Filtrar cursos por modalidad preferida
    - Planificación de recursos (aulas vs. licencias de software)
    - Información para estudiantes sobre formato del curso
    """
    PRESENCIAL = "presencial"
    VIRTUAL = "virtual"
    HIBRIDO = "híbrido"


class EstadoInscripcion(str, Enum):
    """
    Estados posibles de una inscripción
    
    ¿Por qué necesitamos esto?
    -------------------------
    Una inscripción pasa por diferentes estados durante su ciclo de vida.
    Esto permite:
    - Rastrear el progreso del estudiante
    - Generar reportes (cuántos activos, completados, etc.)
    - Aplicar reglas de negocio (solo activos pueden pagar)
    
    Valores:
    -------
    - ACTIVO: Estudiante cursando actualmente
    - COMPLETADO: Estudiante finalizó el curso exitosamente
    - CANCELADO: Inscripción cancelada (abandono o expulsión)
    - CONGELADO: Temporalmente inactivo (puede reactivarse)
    
    Flujo típico:
    ------------
    ACTIVO → COMPLETADO (caso exitoso)
    ACTIVO → ABANDONO (abandono)
    ACTIVO → CONGELADO (pausa temporal)
    """
    ACTIVO = "activo"
    COMPLETADO = "completado"
    ABANDONO = "abandono"
    CONGELADO = "congelado"


class TipoPago(str, Enum):
    """
    Tipos de plan de pago disponibles
    
    ¿Por qué necesitamos esto?
    -------------------------
    Los estudiantes pueden pagar de diferentes formas:
    - Algunos prefieren pagar todo de una vez (descuento)
    - Otros necesitan pagar en cuotas (facilidad)
    
    Valores:
    -------
    - CONTADO: Pago único del monto total
    - CUOTAS: Pago dividido en varias cuotas
    
    Uso en el sistema:
    -----------------
    - Calcular el monto total (contado puede tener descuento)
    - Generar calendario de pagos
    - Validar que los pagos sigan el plan elegido
    """
    CONTADO = "contado"
    CUOTAS = "cuotas"


class EstadoPago(str, Enum):
    """
    Estados de un pago individual
    
    ¿Por qué necesitamos esto?
    -------------------------
    Cada pago debe ser revisado y aprobado manualmente:
    1. Estudiante sube voucher → PENDIENTE
    2. Admin revisa → PAGADO o RECHAZADO
    
    Valores:
    -------
    - PENDIENTE: Voucher subido, esperando revisión
    - ACEPTADO: Pago verificado y aprobado
    - RECHAZADO: Voucher inválido o pago no encontrado
    
    Flujo de trabajo:
    ----------------
    PENDIENTE → ACEPTADO (voucher válido)
    PENDIENTE → RECHAZADO (voucher inválido)
    RECHAZADO → PENDIENTE (estudiante sube nuevo voucher)
    """
    PENDIENTE = "pendiente"
    RECHAZADO = "rechazado"
    ACEPTADO = "aceptado"


class TipoTitulo(str, Enum):
    """
    Tipos de títulos/certificados que se pueden emitir
    
    ¿Por qué necesitamos esto?
    -------------------------
    Cada tipo de curso otorga un tipo diferente de documento:
    - Formato diferente
    - Validez académica diferente
    - Requisitos legales diferentes
    
    Valores:
    -------
    - CERTIFICADO: Para cursos y talleres cortos
    - DIPLOMA: Para diplomados
    - TITULO_MAESTRIA: Título oficial de maestría
    - TITULO_DOCTORADO: Título oficial de doctorado
    
    Uso en el sistema:
    -----------------
    - Generar el documento correcto
    - Validar que el curso permita ese tipo de título
    - Requisitos legales (maestría/doctorado necesitan más validaciones)
    """
    CERTIFICADO = "certificado"
    DIPLOMA = "diploma"
    TITULO_MAESTRIA = "título de maestría"
    TITULO_DOCTORADO = "título de doctorado"


class TipoEstudiante(str, Enum):
    """
    Tipo de estudiante según su relación con la universidad
    
    ¿Por qué necesitamos esto?
    -------------------------
    **CARACTERÍSTICA CRÍTICA**: La universidad ofrece precios diferenciados:
    
    - INTERNO: Estudiantes de la universidad (precio preferencial)
    - EXTERNO: Público en general (precio estándar)
    
    Valores:
    -------
    - INTERNO: Estudiante activo de la universidad
    - EXTERNO: Persona externa a la universidad
    
    Impacto en el sistema:
    ---------------------
    - Determina qué precio aplicar (interno vs externo)
    - Afecta cálculo de matrícula y cuotas
    - Puede requerir validación de registro universitario
    - Se registra en la inscripción para mantener histórico
    
    Ejemplo:
    -------
    Curso: Diplomado en IA
    - Precio interno: 3000 Bs
    - Precio externo: 5000 Bs
    
    Un estudiante interno paga 3000 Bs, uno externo 5000 Bs
    """
    INTERNO = "interno"
    EXTERNO = "externo"


class UserRole(str, Enum):
    """
    Roles de usuario para control de acceso (RBAC)
    
    Valores:
    -------
    - ADMIN: crea estudiantes, cursos, descuentos, enrollments,
    - SUPERADMIN: crea todo lo anterior y usuarios de tipo admin """
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

