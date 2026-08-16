"""
F-PERF-DASHBOARD-PRECOMPUTE (2026-08-08, Kevin): background job que pre-computa
el dashboard cada 5 min para usuarios activos.

Por que:
- El dashboard hace 7+ queries a MongoDB con latencia alta (VPS Germany ->
  Mongo Brazil ~200ms). El cold tarda 5-13s.
- Con cache TTL 5min, el cold es 1 vez cada 5 min POR USUARIO. Si Kevin (u
  otro user) entra 10 veces al dashboard, ve cold 1-2 veces = 5-26s perdidos.
- El pre-compute elimina el cold: el job corre en background y mantiene
  el cache caliente.

Como funciona:
1. Cuando un user accede al dashboard, se agrega a `_active_dashboard_users` (set in-memory).
2. Un asyncio task en background corre cada 5 min.
3. Por cada user en el set, llama al endpoint (o su funcion interna) y guarda
   el resultado en `_DASHBOARD_CACHE` y `_DASHBOARD_V2_CACHE`.
4. Cuando un user accede, el cache ya esta caliente, retorna instantaneamente.

Limitaciones:
- Solo funciona para users que ya accedieron al menos 1 vez (despues del
  restart del proceso). El primer request de cada user es cold.
- Si hay muchos users, el job pre-computa para todos, lo que puede ser
  lento. Hay un limite MAX_USERS para evitar sobrecargar el server.
- Si el job falla, no afecta el endpoint. Solo el cache no se actualiza.

Para apagar: PRECOMPUTE_ENABLED=false en .env.
"""
import asyncio
import time
from typing import Optional, Set

from core.config import settings


# Set de usuarios activos (user_id como string). Thread-safe porque FastAPI
# es async (solo un loop event a la vez). En multi-process habria que
# usar Redis, pero en VPS 1 proceso es OK.
_active_dashboard_users: Set[str] = set()
_active_dashboard_users_lock = asyncio.Lock()

# Limite de usuarios a pre-computar por ciclo (para no overload del server)
MAX_USERS_PER_CYCLE = 10
PRECOMPUTE_INTERVAL_SECONDS = int(getattr(settings, "DASHBOARD_PRECOMPUTE_INTERVAL_SECONDS", 240))  # 4 min (menos que el TTL de 5)
PRECOMPUTE_ENABLED = bool(getattr(settings, "DASHBOARD_PRECOMPUTE_ENABLED", True))


async def track_dashboard_user(user_id: str) -> None:
    """
    Llamado por los endpoints /dashboard/stats y /dashboard/v2 cuando sirven
    un response (cold o warm). Agrega el user a la lista de activos.

    Solo trackea si el response fue COLD (cache miss), porque si fue warm
    el cache ya esta caliente y no necesitamos pre-computar.
    """
    async with _active_dashboard_users_lock:
        _active_dashboard_users.add(str(user_id))
        # Limitar el tamano del set para evitar memory leak
        if len(_active_dashboard_users) > 100:
            # Convertir a list, quedarse con los ultimos 50
            recent = list(_active_dashboard_users)[-50:]
            _active_dashboard_users.clear()
            _active_dashboard_users.update(recent)


async def get_active_dashboard_users() -> list:
    """Retorna la lista de user_ids activos (snapshot)."""
    async with _active_dashboard_users_lock:
        return list(_active_dashboard_users)


def _is_enabled() -> bool:
    return PRECOMPUTE_ENABLED


async def _precompute_user_dashboard(user_id: str) -> bool:
    """
    Pre-computa el dashboard para un user. Retorna True si exitoso, False si fallo.

    NOTA: Importamos las funciones del endpoint dentro de la funcion para
    evitar circular imports. La funcion del endpoint chequea el cache, y si
    no esta, lo computa. Si ya esta, no hace nada. Para forzar la pre-computa,
    primero invalidamos el cache del user.
    """
    try:
        from beanie import PydanticObjectId
        from models.user import User
        from api.dashboard import (
            get_dashboard_stats,
            get_dashboard_v2,
            _dashboard_cache_key,
            _DASHBOARD_CACHE,
            _DASHBOARD_V2_CACHE,
        )

        # Buscar el user
        user = await User.get(PydanticObjectId(user_id))
        if not user:
            return False

        # Invalidar el cache del user para forzar el computo
        cache_key = _dashboard_cache_key(user)
        _DASHBOARD_CACHE.pop(cache_key, None)
        _DASHBOARD_V2_CACHE.pop(cache_key + ":v2", None)

        # Llamar a los endpoints (que ahora haran cold + setearan el cache)
        # Simulamos una llamada HTTP usando un mock current_user
        # La forma mas limpia es duplicar la logica de computo.
        # Por ahora, lo mas simple: hacer una llamada directa a las funciones.
        await get_dashboard_stats(current_user=user)
        await get_dashboard_v2(current_user=user)
        return True
    except Exception as e:
        # No fallar el job si un user falla
        print(f"[dashboard-precomputer] Error pre-computando dashboard para user {user_id}: {e}")
        return False


async def _precomputer_loop() -> None:
    """
    Loop principal del pre-computer. Corre cada PRECOMPUTE_INTERVAL_SECONDS
    y pre-computa el dashboard para los usuarios activos.
    """
    print(f"[dashboard-precomputer] Iniciado. Intervalo: {PRECOMPUTE_INTERVAL_SECONDS}s, MAX_USERS: {MAX_USERS_PER_CYCLE}")
    while True:
        try:
            await asyncio.sleep(PRECOMPUTE_INTERVAL_SECONDS)
            if not _is_enabled():
                continue

            active_users = await get_active_dashboard_users()
            if not active_users:
                continue

            # Limitar a MAX_USERS_PER_CYCLE
            users_to_process = active_users[:MAX_USERS_PER_CYCLE]
            print(f"[dashboard-precomputer] Pre-computando dashboard para {len(users_to_process)} users activos")

            # Pre-computar en paralelo (con gather)
            tasks = [_precompute_user_dashboard(uid) for uid in users_to_process]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if r is True)
            print(f"[dashboard-precomputer] Ciclo completo: {success_count}/{len(users_to_process)} exitosos")
        except asyncio.CancelledError:
            print("[dashboard-precomputer] Detenido (cancelado)")
            break
        except Exception as e:
            print(f"[dashboard-precomputer] Error en loop: {e}")
            # No dejar que un error mate el loop
            await asyncio.sleep(60)  # Esperar 1 min antes de reintentar


_precomputer_task: Optional[asyncio.Task] = None


def start_precomputer() -> None:
    """Inicia el job de pre-compute. Llamar desde main.py en startup."""
    global _precomputer_task
    if not _is_enabled():
        print("[dashboard-precomputer] Deshabilitado por env (PRECOMPUTE_ENABLED=false)")
        return
    if _precomputer_task is not None and not _precomputer_task.done():
        print("[dashboard-precomputer] Ya esta corriendo")
        return
    _precomputer_task = asyncio.create_task(_precomputer_loop())
    print("[dashboard-precomputer] Job iniciado")


def stop_precomputer() -> None:
    """Detiene el job. Llamar desde main.py en shutdown."""
    global _precomputer_task
    if _precomputer_task and not _precomputer_task.done():
        _precomputer_task.cancel()
        _precomputer_task = None
        print("[dashboard-precomputer] Job detenido")
