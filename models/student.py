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
from pydantic import Field, EmailStr
from .base import MongoBaseModel, PyObjectId
from .enums import TipoEstudiante


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
       - es_estudiante_interno: ¿Es estudiante de esta universidad?
       - lista_cursos_ids: Cursos en los que está inscrito
       - lista_titulos_ids: Títulos que ha obtenido
    
    5. ESTADO:
       - activo: ¿Puede usar el sistema?
       - fecha_registro: Cuándo se registró
    
    ¿Por qué es_estudiante_interno es importante?
    --------------------------------------------
    Este campo determina qué precio paga el estudiante:
    - INTERNO: Precios preferenciales (estudiante de la U)
    - EXTERNO: Precios estándar (público general)
    
    Ejemplo:
        Estudiante interno: Paga 3000 Bs por diplomado
        Estudiante externo: Paga 5000 Bs por el mismo diplomado
    
    ¿Por qué almacenar listas de cursos y títulos?
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
    
    registro: str = Field(
        ...,
        description="Número de registro único del estudiante (usado como username)"
    )
    
    password: str = Field(
        ...,
        description="Contraseña hasheada con bcrypt (NUNCA almacenar en texto plano)"
    )
    
    # ========================================================================
    # INFORMACIÓN PERSONAL
    # ========================================================================
    
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
        description="Fecha de nacimiento (requerido para certificados y títulos)"
    )
    
    foto_url: Optional[str] = Field(
        None,
        description="URL de la foto de perfil del estudiante"
    )
    
    # ========================================================================
    # CONTACTO
    # ========================================================================
    
    celular: str = Field(
        ...,
        description="Número de celular para notificaciones"
    )
    
    email: EmailStr = Field(
        ...,
        description="Correo electrónico (validado automáticamente por Pydantic)"
    )
    
    domicilio: Optional[str] = Field(
        None,
        description="Dirección física del estudiante (requerido para certificados)"
    )
    
    # ========================================================================
    # INFORMACIÓN ACADÉMICA
    # ========================================================================
    
    carrera: str = Field(
        ...,
        description="Carrera de pregrado del estudiante"
    )
    
    es_estudiante_interno: TipoEstudiante = Field(
        ...,
        description=(
            "Tipo de estudiante: INTERNO (de la universidad) o EXTERNO (público general). "
            "Determina qué precio paga en los cursos."
        )
    )
    
    lista_cursos_ids: List[PyObjectId] = Field(
        default_factory=list,
        description="Lista de IDs de cursos en los que el estudiante está inscrito"
    )
    
    lista_titulos_ids: List[PyObjectId] = Field(
        default_factory=list,
        description="Lista de IDs de títulos/certificados obtenidos por el estudiante"
    )
    
    # ========================================================================
    # ESTADO Y METADATA
    # ========================================================================
    
    fecha_registro: datetime = Field(
        default_factory=datetime.utcnow,
        description="Fecha y hora en que el estudiante se registró en el sistema"
    )
    
    activo: bool = Field(
        default=True,
        description="Si el estudiante puede acceder al sistema y realizar acciones"
    )
    
    class Config:
        """Configuración y ejemplo de uso"""
        schema_extra = {
            "example": {
                "registro": "EST-2024-001",
                "password": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIq.Ru",
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
                "activo": True
            }
        }
