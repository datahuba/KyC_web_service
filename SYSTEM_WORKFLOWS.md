# Informe Técnico y Flujos de Uso del Sistema de Gestión Académica

**Fecha de Actualización:** 16 de Diciembre de 2024
**Versión del Sistema:** 1.2 (Con Filtros Avanzados y Pagos Inteligentes)

---

## 1. Introducción

Este documento detalla los flujos de operación y la arquitectura lógica del Sistema de Gestión Académica. El sistema está diseñado para administrar el ciclo de vida completo de la educación de posgrado, desde la creación de cursos hasta la certificación, con un fuerte énfasis en la integridad financiera y la trazabilidad.

## 2. Actores y Roles

*   **ADMINISTRADOR (Admin/Superadmin)**:
    *   Gestiona catálogos (Cursos, Descuentos).
    *   Inscribe estudiantes.
    *   Valida y aprueba pagos.
    *   Tiene acceso a reportes y filtros avanzados.
*   **ESTUDIANTE**:
    *   Visualiza su estado académico y financiero.
    *   Registra pagos subiendo comprobantes.
    *   Descarga material y certificados (futuro).

---

## 3. Flujos de Negocio Detallados

### 3.1. Gestión de Catálogos (Configuración)

Antes de cualquier operación, el Administrador debe configurar la oferta.

1.  **Gestión de Descuentos**:
    *   Se crean entidades de descuento reutilizables.
    *   *Ejemplo*: "Beca Excelencia 20%", "Descuento Corporativo 10%".
    *   *Dato Clave*: `porcentaje` (0-100).

2.  **Gestión de Cursos**:
    *   Se definen los programas académicos.
    *   **Precios Diferenciados**: `costo_total_interno` (para alumnos de la U) vs `costo_total_externo`.
    *   **Estructura de Pago**: `matricula` inicial + `cantidad_cuotas`.
    *   **Descuento Global**: Se puede asociar un `descuento_id` que aplicará a *todos* los inscritos en este curso.

### 3.2. Flujo de Inscripción (Core)

El proceso de inscripción es donde se "congelan" las condiciones comerciales.

1.  **Selección**: Admin elige Estudiante + Curso.
2.  **Selección de Descuento**: Admin puede elegir un `descuento_id` adicional específico para este estudiante.
3.  **Cálculo Automático (Backend)**:
    *   Determina si es Interno/Externo.
    *   Aplica **Descuento Curso** (si existe).
    *   Aplica **Descuento Estudiante** (si existe) sobre el resultado.
4.  **Snapshot**: Se guardan los valores calculados (`total_a_pagar`, `saldo_pendiente`) y los IDs de los descuentos usados.
    *   *Beneficio*: Si los precios del curso cambian después, la inscripción del estudiante NO se altera.

### 3.3. Ciclo de Pagos Inteligente

El sistema guía al estudiante para evitar errores en los pagos.

1.  **Consulta de Deuda (Estudiante)**:
    *   El estudiante ve su inscripción.
    *   El sistema calcula dinámicamente el **Siguiente Pago Sugerido**.
    *   *Lógica*:
        *   Si `pagado < matricula` → Sugiere pagar Matrícula.
        *   Si `pagado >= matricula` → Sugiere pagar Cuota X (según saldo).

2.  **Registro de Pago (Estudiante)**:
    *   Estudiante sube foto del comprobante y número de transacción.
    *   **Control Estricto**: El backend ignora cualquier monto ingresado manualmente y **asigna automáticamente** el monto sugerido calculado.
    *   Estado: `PENDIENTE`.

3.  **Validación (Admin)**:
    *   Admin revisa la foto vs el monto registrado.
    *   **Aprobar**: Se suma al saldo, se actualiza el estado (`ACTIVO`/`COMPLETADO`).
    *   **Rechazar**: Se marca como rechazado con un motivo.

---

## 4. Documentación Técnica

### 4.1. Endpoints Clave

#### Inscripciones
*   `POST /api/v1/enrollments/`: Crea inscripción con doble descuento.
*   `GET /api/v1/enrollments/`: Listado con filtros avanzados.
    *   Filtros: `q` (Nombre/Carnet/Curso), `estado`, `curso_id`, `estudiante_id`.

#### Pagos
*   `POST /api/v1/payments/`: Crea pago (autocalculado).
*   `PUT /api/v1/payments/{id}/aprobar`: Aprueba y actualiza saldo.
*   `GET /api/v1/payments/`: Listado con filtros.
    *   Filtros: `q` (Transacción/Comprobante), `estado`.

### 4.2. Modelos de Datos (Schema Simplificado)

**Enrollment (Inscripción)**
```python
{
  "estudiante_id": ObjectId,
  "curso_id": ObjectId,
  "costo_total": float,        # Snapshot
  "descuento_curso_id": ObjectId,
  "descuento_estudiante_id": ObjectId,
  "total_a_pagar": float,      # Final calculado
  "total_pagado": float,       # Suma de pagos aprobados
  "saldo_pendiente": float,    # Calculado
  "siguiente_pago": {          # Propiedad calculada (no en DB)
      "concepto": "Cuota 1",
      "monto_sugerido": 500.0
  }
}
```

**Payment (Pago)**
```python
{
  "inscripcion_id": ObjectId,
  "concepto": "Cuota 1",       # Autocalculado
  "cantidad_pago": 500.0,      # Autocalculado
  "comprobante_url": "url...",
  "estado_pago": "PENDIENTE"
}
```

### 4.3. Reglas de Negocio Implementadas

1.  **Single Source of Truth**: El estado financiero (`saldo_pendiente`) es la verdad absoluta. Los pagos se derivan de él.
2.  **Inmutabilidad de Condiciones**: Una vez inscrito, el precio no cambia aunque cambie el curso.
3.  **Validación Estricta de Pagos**: El backend no confía en el input de monto del usuario; lo calcula.
4.  **Trazabilidad**: Se guarda quién aprobó cada pago y qué descuentos exactos se aplicaron.
