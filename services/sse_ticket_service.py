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
"""
import asyncio
import secrets
import time
from typing import Dict, Optional, Tuple

_TICKET_TTL_SECONDS = 30


class SSETicketService:
    def __init__(self):
        # ticket -> (user_id, user_type, expires_at)
        self._tickets: Dict[str, Tuple[str, str, float]] = {}
        self._lock = asyncio.Lock()

    async def issue(self, user_id: str, user_type: str) -> str:
        """Genera un ticket de un solo uso, válido por _TICKET_TTL_SECONDS."""
        ticket = secrets.token_urlsafe(32)
        expires_at = time.monotonic() + _TICKET_TTL_SECONDS
        async with self._lock:
            await self._purge_expired_locked()
            self._tickets[ticket] = (user_id, user_type, expires_at)
        return ticket

    async def consume(self, ticket: str) -> Optional[Tuple[str, str]]:
        """
        Valida y consume un ticket (uso único). Devuelve (user_id, user_type)
        si es válido, o None si no existe / ya se usó / expiró.
        """
        async with self._lock:
            entry = self._tickets.pop(ticket, None)
        if entry is None:
            return None
        user_id, user_type, expires_at = entry
        if time.monotonic() > expires_at:
            return None
        return user_id, user_type

    async def _purge_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [t for t, (_, _, exp) in self._tickets.items() if exp < now]
        for t in expired:
            del self._tickets[t]


sse_ticket_service = SSETicketService()
