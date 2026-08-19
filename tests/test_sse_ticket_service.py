"""
Tests para el servicio de tickets de un solo uso del stream SSE
=================================================================

FIX-SSE-TOKEN-URL (2026-08-17): antes el JWT completo viajaba en la query
string de /notifications/stream, quedando expuesto en el historial del
navegador, en los access logs de Nginx y en el header Referer. Este
servicio emite tickets cortos, de un solo uso y de corta duración para
reemplazar eso.
"""
import asyncio

import pytest

from services.sse_ticket_service import SSETicketService


class TestSSETicketService:
    @pytest.mark.asyncio
    async def test_issue_devuelve_ticket_no_vacio(self):
        svc = SSETicketService()
        ticket = await svc.issue("user-1", "user")
        assert ticket
        assert isinstance(ticket, str)

    @pytest.mark.asyncio
    async def test_consume_valido_devuelve_user(self):
        svc = SSETicketService()
        ticket = await svc.issue("user-1", "user")
        result = await svc.consume(ticket)
        assert result == ("user-1", "user")

    @pytest.mark.asyncio
    async def test_ticket_es_de_un_solo_uso(self):
        svc = SSETicketService()
        ticket = await svc.issue("user-1", "user")
        primero = await svc.consume(ticket)
        segundo = await svc.consume(ticket)
        assert primero == ("user-1", "user")
        assert segundo is None

    @pytest.mark.asyncio
    async def test_ticket_invalido_devuelve_none(self):
        svc = SSETicketService()
        result = await svc.consume("ticket-que-no-existe")
        assert result is None

    @pytest.mark.asyncio
    async def test_ticket_expirado_devuelve_none(self):
        svc = SSETicketService()
        ticket = await svc.issue("user-1", "user")
        # Forzar expiración manipulando directamente el TTL almacenado
        user_id, user_type, _ = svc._tickets[ticket]
        svc._tickets[ticket] = (user_id, user_type, 0.0)  # ya vencido
        result = await svc.consume(ticket)
        assert result is None

    @pytest.mark.asyncio
    async def test_tickets_distintos_para_usuarios_distintos(self):
        svc = SSETicketService()
        t1 = await svc.issue("user-1", "user")
        t2 = await svc.issue("user-2", "student")
        assert t1 != t2
        assert await svc.consume(t1) == ("user-1", "user")
        assert await svc.consume(t2) == ("user-2", "student")
