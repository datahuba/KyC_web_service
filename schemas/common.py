from typing import Generic, TypeVar, List
from pydantic import BaseModel, Field

T = TypeVar("T")

class PaginationMeta(BaseModel):
    """Metadatos de paginación"""
    page: int = Field(..., description="Número de página actual")
    limit: int = Field(..., description="Elementos por página")
    totalItems: int = Field(..., description="Total de elementos encontrados")
    totalPages: int = Field(..., description="Total de páginas disponibles")
    hasNextPage: bool = Field(..., description="¿Hay página siguiente?")
    hasPrevPage: bool = Field(..., description="¿Hay página anterior?")

class PaginatedResponse(BaseModel, Generic[T]):
    """
    Respuesta genérica paginada.

    Estructura:
    {
        "items": [...],  # FIX-ISSUE-250 (2026-08-14): estandarizar en `items`
                          # para que el frontend (SvelteKit) pueda leer
                          # el mismo campo en TODOS los endpoints paginados.
        "data": [...],   # alias retro-compat
        "meta": { ... }
    }

    Pydantic v2 por defecto EXCLUYE campos no declarados. Para que
    `items` llegue al cliente, lo declaramos explicitamente. Tambien
    mantenemos `data` como alias retro-compat (mismo valor que `items`).
    """
    items: List[T] = Field(..., description="Lista de resultados (canonico)")
    data: List[T] = Field(..., description="Alias retro-compat de items")
    meta: PaginationMeta = Field(..., description="Metadatos de paginación")

    @classmethod
    def from_response(cls, items: List[T], meta: PaginationMeta) -> "PaginatedResponse":
        """Helper para construir con items=data."""
        return cls(items=items, data=items, meta=meta)
