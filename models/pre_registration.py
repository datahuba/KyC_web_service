"""
Modelos de Pre-registro de Estudiantes
======================================

Sistema de formularios dinámicos (ISSUE-Q-PRE-REGISTRO-FORM):

- PreRegistrationForm: template creado por el super admin. Define el
  programa asociado (o "general" si es null), la fecha de cierre, y un
  slug público. Un link público se expone al estudiante; al hacer submit
  se crea una PreRegistration.

- PreRegistration: respuesta pública al formulario. Contiene los datos
  del estudiante en un dict. Cuando CPD/Encargado de Curso aprueba, se
  crea un Student + User con la convención 'Uagrm.<CI>'.

Colecciones MongoDB: pre_registration_forms, pre_registrations
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field
from .base import MongoBaseModel, PyObjectId


class PreRegistrationForm(MongoBaseModel):
    """
    Formulario de pre-registro público (template).

    Si programa_id es None, el formulario es "general" y CPD lo ve.
    Si programa_id está seteado, el formulario es delegado al
    Encargado de Curso / Coordinador de ese programa.
    """
    nombre: str = Field(..., min_length=3, max_length=200, description="Nombre interno del formulario (solo visible para admin)")
    slug: str = Field(..., min_length=3, max_length=120, description="Identificador URL-safe único. El link público es /pre-registro/{slug}")
    descripcion: Optional[str] = Field(None, max_length=1000, description="Descripción visible para el estudiante en la página pública")
    programa_id: Optional[PyObjectId] = Field(None, description="ID del programa asociado. None = formulario general (visible para CPD)")
    fecha_inicio: datetime = Field(..., description="Inicio de la ventana de recepción")
    fecha_fin: datetime = Field(..., description="Fin de la ventana de recepción (countdown en la página pública)")
    estado: str = Field(default="activo", description="activo | cerrado (el super admin puede cerrar/reabrir manualmente)")
    created_by: str = Field(..., description="Username del super admin que creó el formulario")

    class Settings:
        name = "pre_registration_forms"
        indexes = [
            pymongo.IndexModel([("slug", pymongo.ASCENDING)], unique=True, name="uniq_slug"),
            [("estado", pymongo.ASCENDING), ("fecha_fin", pymongo.ASCENDING)],
            "programa_id",
            [("created_at", pymongo.DESCENDING)],
            # B-2026-08-22-PRE-REG-BATCH-ENRICH: indice compuesto para que
            # el aggregation de /counters (match por programa_id + group por
            # estado) use el indice en vez de hacer COLLSCAN.
            [("programa_id", pymongo.ASCENDING), ("estado", pymongo.ASCENDING)],
        ]


class PreRegistration(MongoBaseModel):
    """
    Respuesta pública a un formulario de pre-registro.

    `data` contiene todos los campos necesarios para crear un Student
    (nombre, email, carnet, celular, fecha_nacimiento, etc.). La estructura
    es flexible para soportar extensiones futuras sin migraciones.
    """
    form_id: PyObjectId = Field(..., description="ID del PreRegistrationForm respondido")
    data: dict = Field(..., description="Datos enviados por el visitante. Claves esperadas: nombre, email, carnet, celular, fecha_nacimiento (ISO), etc.")

    estado: str = Field(default="pendiente", description="pendiente | aprobado | rechazado")
    motivo_rechazo: Optional[str] = Field(None, max_length=500, description="Motivo si fue rechazada")
    revisado_por: Optional[str] = Field(None, description="Username del revisor (CPD/Encargado)")
    fecha_revision: Optional[datetime] = Field(None, description="Fecha de aprobación/rechazo")
    migrated_to_student_id: Optional[PyObjectId] = Field(None, description="ID del Student creado al aprobar (migración exitosa)")

    class Settings:
        name = "pre_registrations"
        # AUDITORÍA: use_revision previene aprobar/rechazar el mismo registro
        # dos veces por race conditions (mismo patrón que Payment/EnrollmentRequest).
        use_revision = True
        indexes = [
            [("estado", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            "form_id",
            # B-2026-08-22-PRE-REG-BATCH-ENRICH: indice compuesto (form_id, estado)
            # para que el aggregation de /forms y /counters use el indice en vez
            # de COLLSCAN. Cubre $match por form_id + $group por estado.
            [("form_id", pymongo.ASCENDING), ("estado", pymongo.ASCENDING)],
        ]
