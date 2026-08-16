"""
Cache en memoria para lookups frecuentes de Student y Enrollment.

F-CACHE-SHARED (2026-08-08, Kevin): antes, cada request a /payments/
hacia 2 round-trips a MongoDB (students + enrollments) incluso para los
mismos IDs. Con este cache, los lookups se hacen 1 vez cada TTL segundos
(default 30s) para todos los requests concurrentes.

Por que en memoria (no Redis):
1. El VPS tiene 1 sola instancia del backend. No hay replicas.
2. Los datos cacheados (nombre del estudiante, cantidad de cuotas)
   no son criticos en tiempo real: 30s de staleness es aceptable
   para una lista de pagos.
3. Cero infraestructura adicional. Sin puntos de falla extra.
4. ~200KB de memoria para 1000 entries. Trivial.

Por que NO es un cache agresivo (e.g. cachear TODO Student.get()):
1. Riesgo de staleness en lugares donde SÍ importa data fresca
   (e.g. actualizacion de perfil, aprobacion de pagos).
2. Mantenimiento: cualquier endpoint que mute el documento deberia
   invalidar el cache. Es facil olvidarse.
3. Esta primera version es CONSERVADORA: solo cachea los lookups
   en bulk (enrich) y `enrollment_service.get_enrollment()`.
   NO toca `Student.get()` directamente.

Configuracion via .env:
- CACHE_TTL_SECONDS: TTL de cada entry (default 30s)
- CACHE_MAX_ENTRIES: LRU max size por cache (default 1000)
- CACHE_ENABLED: kill switch (default True)

Thread-safety: usa asyncio.Lock (FastAPI es async, no necesita thread lock).
"""
import asyncio
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Any

from core.config import settings
from core.timezone_utils import utcnow_naive


# ========================================================================
# CACHE GENÉRICO LRU + TTL
# ========================================================================
class TTLCache:
    """
    Cache LRU con TTL por entry.

    - get(key): retorna el value si no expiro, sino None
    - set(key, value, ttl): guarda con expiracion
    - delete(key): elimina una entry
    - clear(): limpia todo
    - stats: dict con hits, misses, evictions
    """

    def __init__(self, name: str, max_entries: int = 1000, default_ttl: int = 30):
        self._name = name
        self._max = max_entries
        self._default_ttl = default_ttl
        self._data: OrderedDict = OrderedDict()  # key -> (value, expires_at)
        self._lock = asyncio.Lock()
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "sets": 0}

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._data:
                self.stats["misses"] += 1
                return None
            value, expires_at = self._data[key]
            if expires_at < time.time():
                del self._data[key]
                self.stats["misses"] += 1
                return None
            # LRU: mover al final
            self._data.move_to_end(key)
            self.stats["hits"] += 1
            return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        async with self._lock:
            if key in self._data:
                # Update + LRU
                self._data.move_to_end(key)
            self._data[key] = (value, time.time() + (ttl or self._default_ttl))
            self.stats["sets"] += 1
            # Evict si excede el max (LRU: el primero es el mas viejo)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
                self.stats["evictions"] += 1

    async def set_many(self, items: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Bulk set para evitar N locks."""
        async with self._lock:
            now = time.time()
            for key, value in items.items():
                if key in self._data:
                    self._data.move_to_end(key)
                self._data[key] = (value, now + (ttl or self._default_ttl))
                self.stats["sets"] += 1
            while len(self._data) > self._max:
                self._data.popitem(last=False)
                self.stats["evictions"] += 1

    async def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Retorna {key: value} solo para los que existen y no expiraron."""
        async with self._lock:
            result = {}
            now = time.time()
            for key in keys:
                if key not in self._data:
                    self.stats["misses"] += 1
                    continue
                value, expires_at = self._data[key]
                if expires_at < now:
                    del self._data[key]
                    self.stats["misses"] += 1
                    continue
                self._data.move_to_end(key)
                result[key] = value
                self.stats["hits"] += 1
            return result

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()

    def size(self) -> int:
        return len(self._data)


# ========================================================================
# CACHES ESPECÍFICOS POR COLECCIÓN
# ========================================================================
# F-CACHE-SHARED: 2 caches separados. Students y Enrollments tienen TTLs
# diferentes porque cambian con frecuencias distintas.
#
# Students: cambian raramente (nombre, CI, registro). TTL largo OK.
# Enrollments: cambian mas seguido (modulos pagados, descuentos). TTL
# un poco mas corto para no servir datos muy stale en la lista de pagos.
_students_cache = TTLCache(
    name="students",
    max_entries=int(getattr(settings, "CACHE_MAX_ENTRIES", 1000)),
    default_ttl=int(getattr(settings, "CACHE_TTL_STUDENTS_SECONDS", 60)),
)
_enrollments_cache = TTLCache(
    name="enrollments",
    max_entries=int(getattr(settings, "CACHE_MAX_ENTRIES", 1000)),
    default_ttl=int(getattr(settings, "CACHE_TTL_ENROLLMENTS_SECONDS", 30)),
)


def cache_enabled() -> bool:
    """Kill switch via env (CACHE_ENABLED=false desactiva todos los caches)."""
    return bool(getattr(settings, "CACHE_ENABLED", True))


async def get_students_bulk_cached(
    ids: List[Any],
    projection: Optional[Dict[str, int]] = None,
) -> Dict[str, dict]:
    """
    Retorna {id_str: student_dict} para los IDs dados.

    - Primero busca en cache. Hits no tocan Mongo.
    - Solo los misses van a Mongo (en una sola query batch).
    - Los resultados se guardan en cache para la proxima request.

    F-CACHE-SHARED: ANTES payment_service.enrich_payments_with_details_bulk
    hacia 1 query a Mongo en cada request. AHORA, si los IDs ya estan en
    cache (caso tipico: el mismo usuario refresca la lista de pagos cada
    30s), retorna sin tocar Mongo.

    Args:
        ids: lista de ObjectId, PydanticObjectId, o str
        projection: campos a traer de Mongo. Si None, trae el documento
            completo (Beanie object se serializa a dict).
    """
    if not ids or not cache_enabled():
        return {}

    from beanie import PydanticObjectId
    from bson import ObjectId as BsonObjectId

    # Normalizar a str (key del cache)
    def _to_key(x):
        if isinstance(x, str):
            return x
        return str(x)

    keys = [_to_key(i) for i in ids]
    unique_keys = list(dict.fromkeys(keys))  # dedupe preservando orden

    # 1. Buscar en cache
    cached = await _students_cache.get_many(unique_keys)

    # 2. Para los misses, ir a Mongo
    missing_keys = [k for k in unique_keys if k not in cached]
    if missing_keys:
        # Convertir keys a ObjectId para la query
        oids = []
        for k in missing_keys:
            try:
                if len(k) == 24:
                    oids.append(BsonObjectId(k))
                else:
                    oids.append(k)  # fallback
            except Exception:
                oids.append(k)

        from models.student import Student
        coll = Student.get_motor_collection()
        query = {"_id": {"$in": oids}}
        if projection:
            cursor = coll.find(query, projection)
        else:
            cursor = coll.find(query)
        docs = await cursor.to_list(length=len(oids))

        # Indexar por _id (como string) para el cache
        new_entries = {}
        for d in docs:
            key = _to_key(d["_id"])
            # NO removemos _id: el caller hace `students_map[s["_id"]] = s`
            # para lookup rapido. 12 bytes extra por entry es despreciable.
            new_entries[key] = d

        # Tambien guardar los que NO se encontraron (None) para no volver
        # a buscarlos hasta el TTL. Patron: cache negatives.
        for k in missing_keys:
            if k not in new_entries:
                new_entries[k] = None

        await _students_cache.set_many(new_entries)
        cached.update(new_entries)

    # 3. Retornar solo los que SI se encontraron
    return {k: v for k, v in cached.items() if v is not None}


async def get_enrollments_bulk_cached(
    ids: List[Any],
    projection: Optional[Dict[str, int]] = None,
) -> Dict[str, dict]:
    """Equivalente a get_students_bulk_cached pero para enrollments."""
    if not ids or not cache_enabled():
        return {}

    from bson import ObjectId as BsonObjectId

    def _to_key(x):
        if isinstance(x, str):
            return x
        return str(x)

    keys = [_to_key(i) for i in ids]
    unique_keys = list(dict.fromkeys(keys))

    cached = await _enrollments_cache.get_many(unique_keys)

    missing_keys = [k for k in unique_keys if k not in cached]
    if missing_keys:
        oids = []
        for k in missing_keys:
            try:
                if len(k) == 24:
                    oids.append(BsonObjectId(k))
                else:
                    oids.append(k)
            except Exception:
                oids.append(k)

        from models.enrollment import Enrollment
        coll = Enrollment.get_motor_collection()
        query = {"_id": {"$in": oids}}
        if projection:
            cursor = coll.find(query, projection)
        else:
            cursor = coll.find(query)
        docs = await cursor.to_list(length=len(oids))

        new_entries = {}
        for d in docs:
            key = _to_key(d["_id"])
            # Mantenemos _id en el dict para compatibilidad con el caller
            # (enrollment_service hace `enrollments_map[e["_id"]] = e`).
            new_entries[key] = d

        for k in missing_keys:
            if k not in new_entries:
                new_entries[k] = None

        await _enrollments_cache.set_many(new_entries)
        cached.update(new_entries)

    return {k: v for k, v in cached.items() if v is not None}


async def get_enrollment_cached(id) -> Optional[dict]:
    """
    Cachea el lookup de un enrollment individual (1 por vez).

    F-CACHE-SHARED: enrollment_service.get_enrollment() se usa en muchos
    lugares. Antes cada llamada era un round-trip a Mongo. Ahora, si el
    enrollment ya esta en cache, retorna sin tocar Mongo.

    Returns: dict del enrollment (o None si no existe).
    """
    if not cache_enabled():
        return None

    key = str(id)
    cached = await _enrollments_cache.get(key)
    if cached is not None:
        # Si tiene _found=False, era un cache negative (no existe)
        if cached.get("_found") is False:
            return None
        return cached

    from bson import ObjectId as BsonObjectId
    from models.enrollment import Enrollment

    try:
        oid = BsonObjectId(key) if len(key) == 24 else key
    except Exception:
        oid = key

    doc = await Enrollment.get_motor_collection().find_one({"_id": oid})
    if doc:
        await _enrollments_cache.set(key, doc)
        return doc
    else:
        # Cache negative (no encontrado) por TTL para no volver a buscar
        await _enrollments_cache.set(key, {"_found": False})
        return None


async def invalidate_student(id) -> None:
    """Invalida un estudiante del cache (llamar cuando se actualiza)."""
    await _students_cache.delete(str(id))


async def invalidate_enrollment(id) -> None:
    """Invalida un enrollment del cache (llamar cuando se actualiza)."""
    await _enrollments_cache.delete(str(id))


async def invalidate_all() -> None:
    """Limpia todo el cache. Util en admin/debug."""
    await _students_cache.clear()
    await _enrollments_cache.clear()


def get_cache_stats() -> dict:
    """Retorna estadisticas de los caches para debug."""
    return {
        "students": {
            "size": _students_cache.size(),
            "stats": dict(_students_cache.stats),
        },
        "enrollments": {
            "size": _enrollments_cache.size(),
            "stats": dict(_enrollments_cache.stats),
        },
        "enabled": cache_enabled(),
        "config": {
            "students_ttl": int(getattr(settings, "CACHE_TTL_STUDENTS_SECONDS", 60)),
            "enrollments_ttl": int(getattr(settings, "CACHE_TTL_ENROLLMENTS_SECONDS", 30)),
            "max_entries": int(getattr(settings, "CACHE_MAX_ENTRIES", 1000)),
        },
    }
