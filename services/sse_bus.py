"""
SSE Bus (TECH-003) — Server-Sent Events para notificaciones en tiempo real
==========================================================================

Reemplaza el polling cada 45s del frontend con un push real desde el backend.
Cuando se crea una notificación (notification_service.create_notification),
se publica en el bus para que se emita a todos los streams SSE activos del
usuario destinatario.

Uso:
    from services.sse_bus import sse_bus

    # Backend: publicar después de crear la notificación
    await notification.insert()
    await sse_bus.publish(user_id, notification_dict)

    # Backend: endpoint SSE
    @router.get("/stream")
    async def stream(user_id = Depends(...)):
        async def event_generator():
            queue = await sse_bus.subscribe(user_id)
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    data = await queue.get()
                    yield {"event": "notification", "data": json.dumps(data)}
            finally:
                await sse_bus.unsubscribe(user_id, queue)
        return EventSourceResponse(event_generator())
"""
import asyncio
import json
from typing import Any, Dict, Set
from beanie import PydanticObjectId


class SSEBus:
    """
    Bus de eventos SSE en memoria.
    Para producción con múltiples workers, considerar Redis Pub/Sub.
    """

    def __init__(self):
        # user_id (str) -> set de queues (asyncio.Queue)
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: PydanticObjectId | str) -> asyncio.Queue:
        """Suscribirse al bus para un usuario. Devuelve la queue para iterar."""
        key = str(user_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        async with self._lock:
            if key not in self._subscribers:
                self._subscribers[key] = set()
            self._subscribers[key].add(queue)
        return queue

    async def unsubscribe(self, user_id: PydanticObjectId | str, queue: asyncio.Queue) -> None:
        """Desuscribirse cuando el cliente desconecta."""
        key = str(user_id)
        async with self._lock:
            if key in self._subscribers:
                self._subscribers[key].discard(queue)
                if not self._subscribers[key]:
                    del self._subscribers[key]

    async def publish(self, user_id: PydanticObjectId | str, data: Any) -> int:
        """
        Publicar un evento a todos los subscribers de un usuario.
        Devuelve la cantidad de queues que recibieron el mensaje.
        Si una queue está llena, descarta el mensaje (no bloquea).
        """
        key = str(user_id)
        async with self._lock:
            queues = list(self._subscribers.get(key, set()))
        count = 0
        for queue in queues:
            try:
                queue.put_nowait(data)
                count += 1
            except asyncio.QueueFull:
                # Si la queue está llena, descartar. El cliente puede hacer
                # polling fallback o reconectarse.
                pass
        return count

    def stats(self) -> Dict[str, int]:
        """Estadísticas del bus (para debugging)."""
        return {
            "total_users": len(self._subscribers),
            "total_subscriptions": sum(len(q) for q in self._subscribers.values()),
        }


# Instancia global del bus
sse_bus = SSEBus()
