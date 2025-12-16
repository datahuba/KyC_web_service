# Guía de Implementación: Filtros y Paginación
**Para:** Equipo de Desarrollo (Backend & Frontend)
**Objetivo:** Estandarizar la forma de listar datos en el sistema para garantizar rendimiento y usabilidad.

---

## 1. Introducción

Cuando una aplicación escala, no podemos devolver "todos" los registros de golpe.
*   **Backend**: Sobrecarga la base de datos y la memoria.
*   **Frontend**: Congela el navegador y consume muchos datos.

**Solución:** Implementar **Paginación** (traer datos por bloques) y **Filtros** (traer solo lo necesario) en el servidor.

---

## 2. Guía para Backend (FastAPI + Beanie)

### Paso A: Estandarizar la Respuesta
No devuelvas una lista plana `[Obj1, Obj2]`. Devuelve un objeto con metadatos.

**Schema Genérico (`schemas/common.py`):**
```python
from typing import Generic, TypeVar, List
from pydantic import BaseModel

T = TypeVar("T")

class PaginatedResponse(BaseModel, Generic[T]):
    total: int          # Total de registros que coinciden con el filtro
    page: int           # Página actual
    per_page: int       # Elementos por página
    total_pages: int    # Total de páginas calculadas
    data: List[T]       # Los datos reales
```

### Paso B: Implementar Lógica en el Servicio
El servicio debe recibir `page`, `per_page` y los filtros opcionales.

**Ejemplo (`services/student_service.py`):**
```python
async def get_students(
    page: int, 
    per_page: int, 
    q: Optional[str] = None  # Búsqueda de texto
) -> tuple[List[Student], int]:
    
    query = Student.find()
    
    # 1. Aplicar Filtros
    if q:
        # Búsqueda "case-insensitive" en múltiples campos
        regex = {"$regex": q, "$options": "i"}
        query = query.find(
            Or(
                Student.nombre == regex,
                Student.email == regex
            )
        )
    
    # 2. Contar Total (Importante para el frontend)
    total_count = await query.count()
    
    # 3. Paginar
    skip = (page - 1) * per_page
    items = await query.skip(skip).limit(per_page).to_list()
    
    return items, total_count
```

### Paso C: Exponer en el Endpoint
El endpoint conecta todo y calcula `total_pages`.

**Ejemplo (`api/students.py`):**
```python
@router.get("/", response_model=PaginatedResponse[StudentResponse])
async def list_students(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    q: Optional[str] = None
):
    items, total = await student_service.get_students(page, per_page, q)
    
    # Calcular total de páginas
    import math
    total_pages = math.ceil(total / per_page)
    
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "data": items
    }
```

---

## 3. Guía para Frontend

### Paso A: Construcción de la URL
Nunca filtres en el cliente (usando `array.filter()`) si hay muchos datos. Envía los parámetros al servidor.

**Ejemplo de Request:**
```javascript
// GET /api/v1/students?page=1&per_page=10&q=juan
const params = new URLSearchParams({
  page: currentPage,
  per_page: 10,
  q: searchTerm // "juan"
});

const response = await fetch(`/api/v1/students?${params}`);
const result = await response.json();
```

### Paso B: Manejo de la Búsqueda (Debounce)
Cuando el usuario escribe en el buscador, no hagas una petición por cada letra. Espera a que deje de escribir.

**Patrón Recomendado:**
1. Usuario escribe "J"... (esperar 300ms)
2. Usuario escribe "u"... (esperar 300ms)
3. Usuario escribe "an" -> (Pasaron 300ms) -> **Hacer Petición**.

### Paso C: Renderizado de Paginación
Usa los metadatos de la respuesta para dibujar los botones.

```javascript
// Datos recibidos del backend
const { total_pages, page } = result;

// Renderizar
return (
  <div>
    <button disabled={page === 1} onClick={() => setPage(page - 1)}>
      Anterior
    </button>
    
    <span>Página {page} de {total_pages}</span>
    
    <button disabled={page === total_pages} onClick={() => setPage(page + 1)}>
      Siguiente
    </button>
  </div>
);
```

---

## 4. Resumen de Reglas de Oro

1.  **Siempre devuelve el `total`**: El frontend necesita saber cuántos registros hay en total para calcular las páginas.
2.  **Usa `regex` con `$options: "i"`**: Para que la búsqueda no distinga entre mayúsculas y minúsculas ("Juan" == "juan").
3.  **Limita el `per_page`**: No permitas que pidan 1 millón de registros. Pon un tope (ej: `le=100`).
4.  **Resetea la página al filtrar**: Si el usuario busca algo nuevo, automáticamente envíalo a la `page=1`.

---
**Fin de la Guía**
