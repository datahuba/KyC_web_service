"""
F-FIX-SSE-TICKET-MULTIWORKER (2026-08-19)
==========================================

Antes, `SSETicketService` guardaba los tickets de un solo uso en un dict
en memoria del proceso. El backend en produccion corre con
`uvicorn --workers 4` (4 procesos separados, sin memoria compartida): el
ticket emitido por `POST /notifications/stream-ticket` podia caer en el
worker A, y el `GET /notifications/stream?ticket=...` inmediato siguiente
caer en el worker B, C o D — que nunca vio ese ticket en su dict — y
devolver 401. Con el reintento automatico del frontend cada 5s, esto
generaba un loop de reconexion fallida casi constante (~75% de las veces,
segun a que worker cae cada request), visible como 401 repetidos en la
consola y contribuyendo al "timeout en casi todo" que reporto Kevin en
capacitacion (el loop de reconexion satura la cola de requests del
navegador).

Fix: los tickets se guardan en MongoDB (compartido por los 4 workers, a
diferencia de la memoria de cada proceso), con un indice unico sobre
`ticket` y TTL de limpieza de respaldo. El consumo usa
`find_one_and_delete` atomico directo sobre la coleccion de Motor (no vía
Beanie ORM), para que el "de un solo uso" siga siendo verdad incluso con
requests concurrentes en distintos workers.
"""

from datetime import datetime
from pydantic import Field
from beanie import Document

from core.timezone_utils import utcnow_naive


class SSETicket(Document):
    ticket: str = Field(..., description="Token de un solo uso, indexado unico")
    user_id: str
    user_type: str
    # F-FIX-DATETIME-UTCNOW-DEPRECADO (2026-08-22, encontrado en la
    # auditoria completa): este archivo arreglo el bug de multi-worker
    # pero seguia usando `datetime.utcnow()`, exactamente el patron
    # deprecado que AGENTS.md prohibe para codigo nuevo. `utcnow_naive()`
    # es el helper que ya usa el resto del proyecto para timestamps
    # naive-pero-UTC — se alinea con eso en vez de con datetime.utcnow().
    created_at: datetime = Field(default_factory=utcnow_naive)

    class Settings:
        name = "sse_tickets"
        from pymongo import IndexModel, ASCENDING

        indexes = [
            IndexModel([("ticket", ASCENDING)], unique=True, name="unique_ticket"),
            # Respaldo de limpieza: si un ticket nunca se consume (cliente
            # abandona la conexion), Mongo lo borra solo a los 60s. El TTL
            # monitor de Mongo corre cada ~60s, no instantaneo, por eso la
            # logica de `consume()` en sse_ticket_service.py TAMBIEN
            # valida expiracion explicita — el indice es solo limpieza,
            # no la fuente de verdad de la validez.
            IndexModel([("created_at", ASCENDING)], expireAfterSeconds=60, name="ttl_created_at_60s"),
        ]
