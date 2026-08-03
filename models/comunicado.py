"""
Modelo de Comunicado
====================

US-003 (2026-08-03): Módulo "Comunicados" en sidebar admin.
Sirve para que el personal (superadmin / encargado / cobranzas) envíe
anuncios oficiales a los estudiantes. Los comunicados aparecen como
pop-up al iniciar sesión y, opcionalmente, se envían por email.

Colecciones MongoDB:
- `comunicados`: definición de cada anuncio.
- `comunicado_vistos`: tracking de qué estudiante ya vio qué comunicado
  (para no mostrar de nuevo el pop-up en cada login).
"""

from datetime import datetime
from typing import List, Optional
import pymongo
from pydantic import Field

from .base import MongoBaseModel, PyObjectId


class AdjuntoComunicado(dict):
    """
    Adjunto de un comunicado (PDF o imagen subido a Cloudinary).
    Estructura flexible (dict) para no romper al agregar campos.

    Campos esperados:
    - url: URL pública de Cloudinary
    - nombre: nombre del archivo para mostrar
    - tipo: 'image' o 'pdf' (heurística rápida de UI)
    - public_id: ID interno de Cloudinary (para borrar luego)
    """
    pass


class Comunicado(MongoBaseModel):
    """
    Anuncio oficial del personal administrativo hacia los estudiantes.

    Audiencia: lista de cursos a los que aplica. Si está VACÍA, el
    comunicado va dirigido a TODOS los estudiantes activos de cualquier
    curso (comunicado global).

    Estado de visualización: NO se almacena en este modelo. Se delega
    a ComunicadoVisto (un registro por (comunicado, estudiante)). Esto
    permite escalar sin penalizar la lectura del anuncio.
    """

    titulo: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Título del comunicado"
    )

    contenido: str = Field(
        ...,
        min_length=1,
        description="Contenido del comunicado en formato Markdown (sin HTML)."
    )

    # ------------------------------------------------------------------
    # Autor
    # ------------------------------------------------------------------
    autor_id: PyObjectId = Field(
        ...,
        description="ID del User que creó el comunicado (superadmin/encargado/cobranzas)"
    )

    autor_nombre: str = Field(
        ...,
        description="Denormalizado: nombre_funcional o username del autor (para mostrar sin join)"
    )

    autor_rol: str = Field(
        ...,
        description="Rol del autor al momento de crear (auditoría). Ej: 'superadmin', 'cobranza'."
    )

    # ------------------------------------------------------------------
    # Audiencia
    # ------------------------------------------------------------------
    cursos_ids: List[PyObjectId] = Field(
        default_factory=list,
        description="IDs de cursos a los que va dirigido. VACÍO = todos los estudiantes activos."
    )

    # ------------------------------------------------------------------
    # Importancia
    # ------------------------------------------------------------------
    importancia: str = Field(
        default="normal",
        description="'normal' o 'urgente'. Urgente se muestra con borde rojo y persiste más tiempo."
    )

    # ------------------------------------------------------------------
    # Adjuntos
    # ------------------------------------------------------------------
    adjuntos: List[dict] = Field(
        default_factory=list,
        description="Lista de adjuntos subidos a Cloudinary. Cada item: {url, nombre, tipo, public_id}."
    )

    # ------------------------------------------------------------------
    # Expiración
    # ------------------------------------------------------------------
    expira_en: Optional[datetime] = Field(
        None,
        description="Fecha después de la cual el comunicado deja de mostrarse. None = no expira."
    )

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------
    enviar_email: bool = Field(
        default=False,
        description="Si true, al crear se envía el comunicado por email a la audiencia."
    )

    email_enviado: bool = Field(
        default=False,
        description="True si ya se envió el email (idempotencia: no reenviar en cada GET)."
    )

    email_enviado_en: Optional[datetime] = Field(
        None,
        description="Timestamp del envío del email."
    )

    email_destinatarios: int = Field(
        default=0,
        description="Cantidad de emails enviados (auditoría)."
    )

    # ------------------------------------------------------------------
    # Estadísticas denormalizadas
    # ------------------------------------------------------------------
    total_vistos: int = Field(
        default=0,
        description="Cantidad de estudiantes que marcaron como visto (denormalizado para listados)."
    )

    class Settings:
        name = "comunicados"
        indexes = [
            # Listado cronológico general
            [("created_at", pymongo.DESCENDING)],
            # Filtro por audiencia (curso)
            [("cursos_ids", pymongo.ASCENDING)],
            # Filtro por autor
            [("autor_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
        ]


class ComunicadoVisto(MongoBaseModel):
    """
    Registro de visualización: qué estudiante ya vio qué comunicado.

    Permite que el pop-up no aparezca repetido en cada login: solo
    se muestra el comunicado si NO existe un ComunicadoVisto para
    (comunicado_id, estudiante_id).
    """

    comunicado_id: PyObjectId = Field(
        ...,
        description="ID del comunicado visto"
    )

    estudiante_id: PyObjectId = Field(
        ...,
        description="ID del estudiante que marcó como visto"
    )

    visto_en: datetime = Field(
        default_factory=datetime.utcnow,
        description="Fecha y hora en que el estudiante marcó como visto"
    )

    class Settings:
        name = "comunicado_vistos"
        indexes = [
            # Búsqueda rápida por comunicado (¿quién lo ha visto?)
            [("comunicado_id", pymongo.ASCENDING)],
            # Búsqueda por estudiante (¿qué le falta por ver?)
            [("estudiante_id", pymongo.ASCENDING)],
            # Unicidad: un estudiante solo puede marcar como visto una vez
            # el mismo comunicado. Esto evita duplicados al hacer spam-click.
            pymongo.IndexModel(
                [("comunicado_id", pymongo.ASCENDING), ("estudiante_id", pymongo.ASCENDING)],
                unique=True,
                name="uq_comunicado_estudiante"
            ),
        ]
