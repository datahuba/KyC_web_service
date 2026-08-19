"""
SSE Ticket Service — tickets de un solo uso para autenticar el stream SSE
==========================================================================

El navegador (EventSource) no permite enviar headers custom, así que el
JWT no puede viajar por Authorization. Antes se pasaba el JWT completo en
la query string (`?token=...`), lo que lo deja expuesto en el historial
del navegador, en los access logs de Nginx y en el header Referer de
cualquier recurso externo que cargue esa página.

Este servicio reemplaza eso: el cliente pide un ticket corto y de un solo
uso (autenticado por header Authorization normal), y abre el EventSource
con ese ticket en vez del JWT. El ticket expira a los 30s y se invalida
apenas se usa, así que aunque quede en un log no sirve para nada después.

F-FIX-SSE-TICKET-MULTIWORKER (2026-08-19): la primera versión guardaba los
tickets en un dict en memoria del proceso. El backend en producción corre
con `uvicorn --workers 4` (4 procesos SIN memoria compartida): el ticket
emitido por `issue()` en un worker no existía en el dict de otro, así que
`consume()` fallaba con 401 en, en promedio, 3 de cada 4 intentos. Ahora
los tickets viven en MongoDB (`SSETicket`, compartido por los 4 workers) y
`consume()` usa `find_one_and_delete` atómico directo sobre la colección
de Motor — no vía Beanie ORM — para que el "de un solo uso" siga
garantizado incluso con requests concurrentes en distintos workers.
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple

from models.sse_ticket import SSETicket

_TICKET_TTL_SECONDS = 30


class SSETicketService:
    async def issue(self, user_id: str, user_type: str) -> str:
        """Genera un ticket de un solo uso, válido por _TICKET_TTL_SECONDS."""
        import secrets

        ticket = secrets.token_urlsafe(32)
        await SSETicket(ticket=ticket, user_id=user_id, user_type=user_type).insert()
        return ticket

    async def consume(self, ticket: str) -> Optional[Tuple[str, str]]:
        """
        Valida y consume un ticket (uso único). Devuelve (user_id, user_type)
        si es válido, o None si no existe / ya se usó / expiró.

        `find_one_and_delete` es atómico a nivel de MongoDB: si dos workers
        reciben la misma request duplicada (retry del cliente) casi al
        mismo tiempo, solo uno de los dos se lleva el documento.
        """
        collection = SSETicket.get_motor_collection()
        doc = await collection.find_one_and_delete({"ticket": ticket})
        if doc is None:
            return None

        created_at = doc.get("created_at")
        if created_at is not None and datetime.utcnow() - created_at > timedelta(seconds=_TICKET_TTL_SECONDS):
            return None

        return doc["user_id"], doc["user_type"]


sse_ticket_service = SSETicketService()
