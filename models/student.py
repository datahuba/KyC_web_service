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
from .title import Title


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
       - titulo: Título en provisión nacional (Embebido)
    
    5. DOCUMENTOS (URLs):
       - ci_url: PDF del carnet de identidad
       - afiliacion_url: PDF de afiliación profesional
       - cv_url: PDF del currículum vitae
    
    6. ESTADO:
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
    nombre: str = Field(...,min_length=1,max_length=200,description="Nombre completo del estudiante")
    email: EmailStr = Field(...,description="Correo electrónico (validado automáticamente por Pydantic)")
    carnet: Optional[str] = Field(None,description="Carnet de identidad")
    extension: Optional[str] = Field(None,description="Extension del carnet de identidad")
    celular: str = Field(...,description="Número de celular para notificaciones")
    domicilio: Optional[str] = Field(None,description="Dirección física del estudiante (requerido para certificados)")
    fecha_nacimiento: datetime = Field(...,description="Fecha de nacimiento (requerido para certificados y títulos)")
    foto_url: Optional[str] = Field(None,description="URL de la foto de perfil del estudiante")
    es_estudiante_interno: TipoEstudiante = Field(...,description=("Tipo de estudiante: INTERNO (de la universidad) o EXTERNO (público general). "))
    activo: bool = Field(default=True,description="Si el estudiante puede acceder al sistema y realizar acciones")
    lista_cursos_ids: List[PyObjectId] = Field(default_factory=list,description="Lista de IDs de cursos en los que el estudiante está inscrito")
    titulo: Optional[Title] = Field(None, description="Título obtenido por el estudiante (Embebido)")
    ci_url: Optional[str] = Field(None,description="URL del PDF del carnet de identidad")
    afiliacion_url: Optional[str] = Field(None,description="URL del PDF de afiliacion a colegio profesional para descuentos")
    cv_url: Optional[str] = Field(None,description="URL del PDF de currículum vitae")
    
    class Settings:
        name = "students"

    class Config:
        """Configuración y ejemplo de uso"""
        schema_extra = {
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
                "cv_url": "https://storage.example.com/docs/cv_brandon.pdf"
            }
        }
