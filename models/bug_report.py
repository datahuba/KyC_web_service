"""
Reporte de Bugs / Errores del sistema
=====================================

F-REPORTE-BUGS (2026-08-17, Kevin): modulo para que el personal
administrativo reporte errores desde la propia aplicacion, con detalle y
evidencia adjunta, en vez de avisarlos por WhatsApp o de boca.

Kevin: "crear un nuevo modulo en el sidebar para todos los perfiles excepto
docentes y estudiantes, solo perfiles adm, que puedan reportar bugs o
errores con un detalle del error mas una captura o imagen cargada o pdf".

RBAC: lo usan superadmin, admin, mae, cpd, cobranza, encargado_curso y
coordinador. Docentes y estudiantes NO — ellos reportan por los canales
que ya existen.

Nota sobre por que un modelo propio y no reusar `ErrorLog`: ese guarda
excepciones que captura el backend automaticamente (path, stack trace,
status code). Esto es lo contrario — lo escribe una persona que vio algo
raro en la pantalla, y muchas veces el backend ni se entero (un boton que
no hace nada, un numero mal calculado, un texto confuso).
"""

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import Field

from models.base import MongoBaseModel, PyObjectId


class BugReport(MongoBaseModel):
    """Reporte de un problema, cargado a mano por el staff."""

    # --- Que paso ---
    titulo: str = Field(
        ...,
        min_length=5,
        max_length=150,
        description="Resumen corto del problema, para la lista",
    )
    descripcion: str = Field(
        ...,
        min_length=10,
        max_length=4000,
        description="Detalle: que se esperaba, que paso, y como reproducirlo",
    )
    # Se guarda la URL de la pantalla donde ocurrio. Vale mas que cualquier
    # descripcion para ubicar el problema.
    pagina: Optional[str] = Field(
        None,
        max_length=500,
        description="Ruta de la app donde se vio el problema (ej. /app/payments)",
    )

    # --- Evidencia ---
    # Varios archivos: una captura sola muchas veces no alcanza (el antes y el
    # despues, o la pantalla + la consola del navegador).
    adjuntos: List[str] = Field(
        default_factory=list,
        description="URLs de las capturas/PDF subidos a Cloudinary",
    )

    # --- Clasificacion ---
    severidad: str = Field(
        default="media",
        description="critica | alta | media | baja",
    )
    modulo: Optional[str] = Field(
        None,
        max_length=80,
        description="Area afectada: pagos, inscripciones, certificados, etc.",
    )

    # --- Quien lo reporto (snapshot: si el usuario se borra, el reporte queda) ---
    reportado_por_id: PyObjectId = Field(..., description="ID del User que reporto")
    reportado_por_nombre: str = Field(..., description="Nombre visible al momento de reportar")
    reportado_por_rol: str = Field(..., description="Rol al momento de reportar")

    # --- Seguimiento ---
    estado: str = Field(
        default="abierto",
        description="abierto | en_revision | resuelto | descartado",
    )
    # Se exige al resolver o descartar: un reporte que se cierra sin decir por
    # que no le sirve a quien lo abrio.
    respuesta: Optional[str] = Field(
        None,
        max_length=2000,
        description="Que se hizo, o por que se descarto",
    )
    atendido_por: Optional[str] = Field(None, description="Quien lo atendio")
    fecha_atencion: Optional[datetime] = Field(None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "bug_reports"
        indexes = [
            "estado",
            "severidad",
            "reportado_por_id",
            [("created_at", -1)],
        ]
