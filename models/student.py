"""
Modelo de Estudiante
====================

Este módulo define el modelo de datos para los estudiantes del sistema.

¿Por qué existe este modelo?
----------------------------
Los estudiantes son el núcleo del sistema. Necesitamos almacenar:
1. Información de autenticación (login)
2. Datos personales (para certificados y contacto)
3. Datos académicos (carrera, cursos)
4. Tipo de estudiante (para precios diferenciados)

Colección MongoDB: students
"""

from datetime import datetime
from typing import Optional, List
import pymongo
from pydantic import Field, EmailStr
from .base import MongoBaseModel, PyObjectId
from .enums import Sexo, EstadoCivil, TipoSangre


class Student(MongoBaseModel):
    """
    Modelo de Estudiante
    
    Representa a una persona que puede inscribirse en cursos de posgrado.
    
    ¿Qué información almacena?
    -------------------------
    
    1. AUTENTICACIÓN (para login):
       - registro: Usuario único para login
       - password: Contraseña hasheada (nunca en texto plano)
    
    2. IDENTIFICACIÓN PERSONAL:
       - nombre: Nombre completo
       - extension: CI/Documento de identidad
       - fecha_nacimiento: Para certificados y validación de edad
       - foto_url: Foto de perfil
    
    3. CONTACTO:
       - celular: Para notificaciones
       - email: Para comunicación oficial
       - domicilio: Dirección física (requerido en certificados)
    
    4. INFORMACIÓN ACADÉMICA:
       - carrera: Carrera de pregrado
       - lista_cursos_ids: Cursos en los que está inscrito
    
    5. ESTADO:
       - activo: ¿Puede usar el sistema?
       - fecha_registro: Cuándo se registró
    
    NOTA: Los documentos (CV, CI, títulos, etc.) ahora se manejan
    en Enrollment.requisitos según los requisitos definidos por cada curso.
    
    ¿Por qué almacenar listas de cursos?
    ---------------------------------------------
    Permite navegación bidireccional:
    - Desde estudiante → ver sus cursos
    - Desde curso → ver sus estudiantes
    
    También facilita:
    - Generar historial académico
    - Validar prerrequisitos
    - Generar reportes
    """
  
    # ========================================================================
    # AUTENTICACIÓN
    # ========================================================================
    
    registro: str = Field(...,description="Número de registro único del estudiante (usado como username)")
    password: str = Field(...,description="Contraseña hasheada con bcrypt (NUNCA almacenar en texto plano)")
    nombre: Optional[str] = Field(None,min_length=1,max_length=200,description="Nombre completo del estudiante")
    email: Optional[EmailStr] = Field(None,description="Correo electrónico (validado automáticamente por Pydantic)")
    carnet: Optional[str] = Field(None,description="Carnet de identidad (solo los números, sin complemento)")
    # ISSUE-Q-COMPLEMENTO-CI (2026-07-08): el "complemento" del CI (ej. '1D',
    # '1J', '1O' en carnets como '2726683-1J') es un dato DISTINTO de
    # `extension` (que es el lugar de expedición del carnet, ej. 'SC'/'LPZ').
    # Antes se perdía al limpiar el carnet para las validaciones de unicidad;
    # ahora se guarda aparte para no perder el dato oficial completo del CI.
    complemento_carnet: Optional[str] = Field(None, max_length=10, description="Complemento del carnet de identidad (ej. '1D', '1J'), distinto de la extensión/lugar de expedición.")
    extension: Optional[str] = Field(None,description="Extension del carnet de identidad")
    celular: Optional[str] = Field(None,description="Número de celular para notificaciones")
    domicilio: Optional[str] = Field(None,description="Dirección física del estudiante (requerido para certificados)")
    fecha_nacimiento: Optional[datetime] = Field(None,description="Fecha de nacimiento (requerido para certificados y títulos)")
    foto_url: Optional[str] = Field(None,description="URL de la foto de perfil del estudiante")

    # ========================================================================
    # DATOS PERSONALES OFICIALES (Ficha UAGRM) — todos opcionales
    # ========================================================================
    sexo: Optional[Sexo] = Field(None, description="Sexo del estudiante")
    estado_civil: Optional[EstadoCivil] = Field(None, description="Estado civil")
    pais: Optional[str] = Field(None, description="País de residencia/origen")
    departamento: Optional[str] = Field(None, description="Departamento")
    provincia: Optional[str] = Field(None, description="Provincia")
    nacionalidad: Optional[str] = Field(None, description="Nacionalidad")
    telefono: Optional[str] = Field(None, description="Teléfono fijo (distinto del celular)")

    # ========================================================================
    # DATOS ACADÉMICOS OFICIALES (Ficha UAGRM)
    # ========================================================================
    modalidad_ingreso: Optional[str] = Field(None, description="Modalidad de ingreso (ej. P.S.A.)")
    periodo: Optional[str] = Field(None, description="Periodo de ingreso (ej. 1/2019)")
    tipo_sangre: Optional[TipoSangre] = Field(None, description="Grupo sanguíneo")
    titulo_bachiller: Optional[str] = Field(None, description="Número/registro del título de bachiller")

    activo: bool = Field(default=True,description="Si el estudiante puede acceder al sistema y realizar acciones")
    lista_cursos_ids: List[PyObjectId] = Field(default_factory=list,description="Lista de IDs de cursos en los que el estudiante está inscrito")

    # ========================================================================
    # ISSUE-Q-PRE: Términos y Condiciones (aceptación en el primer login)
    # ========================================================================
    terminos_aceptados: bool = Field(default=False, description="Si el estudiante ya aceptó el reglamento de Posgrado. Se exige en el primer login.")
    fecha_aceptacion_terminos: Optional[datetime] = Field(default=None, description="Fecha (UTC) en la que el estudiante aceptó los términos por primera vez.")

    # ========================================================================
    # ISSUE-A-VERIFICACION: Verificación de Correo Electrónico (NO bloqueante)
    # ========================================================================
    email_verificado: bool = Field(default=False, description="Si el estudiante confirmó que su correo es válido y accesible. No bloquea el acceso al sistema.")
    fecha_verificacion_email: Optional[datetime] = Field(default=None, description="Fecha (UTC) en que se verificó el correo actual. Se reinicia a None si el correo cambia.")

    # ========================================================================
    # DOCUMENTACIÓN (Cargados desde el Panel de Admin)
    # ========================================================================
    cv_url: Optional[str] = Field(None, description="URL del Currículum Vitae (PDF)")
    cv_estado: str = Field("pendiente", description="Estado de validación: pendiente, verificado, rechazado")
    cv_motivo_rechazo: Optional[str] = Field(None, description="Motivo si fue rechazado")

    carnet_url: Optional[str] = Field(None, description="URL del Carnet de Identidad (PDF)")
    carnet_estado: str = Field("pendiente", description="Estado de validación: pendiente, verificado, rechazado")
    carnet_motivo_rechazo: Optional[str] = Field(None, description="Motivo si fue rechazado")

    afiliacion_url: Optional[str] = Field(None, description="URL de la Afiliación (PDF)")
    afiliacion_estado: str = Field("pendiente", description="Estado de validación: pendiente, verificado, rechazado")
    afiliacion_motivo_rechazo: Optional[str] = Field(None, description="Motivo si fue rechazado")
    
    # INFORMACIÓN ACADÉMICA DEL TÍTULO PROFESIONAL
    titulo: Optional[dict] = Field(
        default=None,
        description="Información completa del título profesional: {titulo, numero_titulo, año_expedicion, universidad, estado, url, motivo_rechazo}"
    )

    # ========================================================================
    # F-2026-08-11-CAMPOS-EC: Datos específicos del Diplomado Gestión Tributaria
    # y demás programas de EDUCACIÓN CONTINUA (reunión UAGRM 2026-08-11).
    # Todos opcionales porque no aplican a estudiantes profesionales (maestría,
    # doctorado) que usan otros campos.
    #
    # Reunion Kevin 2026-08-11: Lisa/encargada diplomados UAGRM maneja planillas
    # Excel con estos datos y los necesita persistidos al aprobar el form de
    # preinscripción. Se reusan campos del modelo cuando existen (departamento,
    # carrera, modalidad_ingreso) para no duplicar.
    # ========================================================================

    # Número de REGISTRO UNIVERSITARIO (de la UAGRM, distinto del `registro`
    # que es el username de login). Ej: "220000123" del kardex UAGRM.
    registro_universitario: Optional[str] = Field(
        None, max_length=30,
        description="Registro universitario UAGRM (de la ficha del estudiante, NO es el username de login).",
    )

    # Código de AVANCE ACADÉMICO (campo numérico del Excel de Lisa). Indica
    # cuántos créditos/módulos ha completado el estudiante a nivel UAGRM.
    avance_academico_codigo: Optional[int] = Field(
        None, ge=0,
        description="Código de avance académico del estudiante (nivel UAGRM, planilla de Lisa).",
    )

    # Número de FORMULARIO DE DESCUENTO (campo del Excel de Lisa). El
    # estudiante trajo este formulario físico firmado por el director.
    formulario_descuento_numero: Optional[int] = Field(
        None, ge=0,
        description="Número del formulario de descuento (planilla de Lisa). Indica que el estudiante trae descuento pre-aprobado.",
    )

    # Código de CARRERA (del Excel, ej: "CONT-001"). Distinto de `carrera`
    # que es el nombre libre de la carrera. Sirve para vincular con sistemas
    # externos UAGRM.
    carrera_codigo: Optional[str] = Field(
        None, max_length=20,
        description="Código de carrera (de la planilla de Lisa). Distinto del campo `carrera` que es el nombre libre.",
    )

    # Descuento pre-aprobado del Excel EC (formato 0.0-1.0, ej: 0.5 = 50%).
    # Aplica SOLO a módulos, NUNCA a matrícula (regla F-074-FIX-4 Kevin 2026-07-23).
    descuento_porcentaje: Optional[float] = Field(
        None, ge=0, le=1,
        description="Descuento pre-aprobado del Excel EC (0.0-1.0). Aplica SOLO a módulos, NO a matrícula.",
    )

    # ========================================================================
    # F-2026-08-11-CAMPOS-EC-MODALIDAD (reunion UAGRM 2026-08-11, seccion 4):
    # Modalidad de estudio + carta firmada por el director.
    # Si el estudiante es de PROVINCIA (procedencia != SCZ) o eligio VIRTUAL,
    # debe subir la carta firmada por el director (decision de la reunion).
    # ========================================================================

    # Modalidad de estudio. 'presencial' = asiste fisicamente, 'virtual' = online.
    # Distinto de `modalidad_ingreso` (P.S.A. y similares) que es el canal de ADMISION.
    modalidad: Optional[str] = Field(
        None, max_length=20,
        description="Modalidad de estudio del programa ('presencial' | 'virtual'). Distinto de modalidad_ingreso (P.S.A.).",
    )

    # URL o identificador de la carta firmada por el director. Requerida para
    # estudiantes de provincia o modalidad virtual. El estudiante sube el PDF
    # a Google Drive / OneDrive / Dropbox y pega el link aca.
    carta_firmada_url: Optional[str] = Field(
        None, max_length=500,
        description="URL de la carta firmada por el director (PDF en Google Drive, OneDrive, Dropbox). Requerida si el estudiante es de provincia o modalidad virtual.",
    )
    
    class Settings:
        name = "students"
        indexes = [
            # Índices únicos estrictos para evitar colisiones de registros
            pymongo.IndexModel([("registro", pymongo.ASCENDING)], unique=True),
            # Índices condicionales dispersos (sparse) de unicidad en campos opcionales
            pymongo.IndexModel([("carnet", pymongo.ASCENDING)], unique=True, sparse=True),
            pymongo.IndexModel([("email", pymongo.ASCENDING)], unique=True, sparse=True),
            # Índice para la consulta textual regular y búsquedas por coincidencia parcial de nombres
            "nombre",
            # Índice Multikey optimizado para búsquedas por filtrado de cursos de posgrado inscritos
            "lista_cursos_ids",
            # Índice compuesto optimizado para el paginador administrativo
            [("activo", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            # Índice temporal simple para ordenación por defecto
            [("created_at", pymongo.DESCENDING)]
        ]

    class Config:
        """Configuración y ejemplo de uso"""
        json_schema_extra = {
            "example": {
                "registro": "220005958",
                "password": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIq.Ru",
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

            }
        }
