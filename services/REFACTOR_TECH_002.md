# TECH-002 · Plan de Refactor de Archivos Grandes

**Fecha**: 2026-07-28
**Autor**: Mavis
**Estado**: Pendiente de ejecución

## Contexto

Tres archivos del backend superan los 100KB / 2000 líneas, lo que dificulta
navegación, code review y mantenimiento. Además mezclan responsabilidades
distintas (CRUD + reportes + enrichment + auditoría).

## Archivos a refactorizar

| Archivo | Líneas | KB | Responsabilidades mezcladas |
|---------|-------:|----:|----------------------------|
| `services/payment_service.py` | 2326 | 104 | CRUD + reportes + enrichment + auditoría + glosas + caja |
| `api/payments.py` | ~2300 | 104 | Router CRUD + router reportes + router dashboard + router caja |
| `api/enrollments.py` | ~1400 | 63 | CRUD + retiros + notas + dashboard + reportes + congelado |
| `services/student_service.py` | ~1000 | 46 | CRUD + import + enrollments + financiero + impersonación |
| `services/enrollment_service.py` | ~1100 | 45 | CRUD + estados + notas + becas + congelado + retiros + cálculos |

## Plan de división

### `services/payment_service.py` (104KB → 5 archivos)

```
services/
├── payment_service.py        # Core CRUD (create, approve, reject, revert, delete, list, get_next_pending)
│                             # ~600 lineas
├── payment_enrichment.py     # enrich_payment_with_details, enrich_payments_with_details_bulk, get_resumen_pagos_enrollment
│                             # ~300 lineas
├── payment_reports.py        # get_resumen_economico, get_matriz_pagos, get_resumen_modulos,
│                             # get_reporte_caja, generar_lista_habilitados, _construir_filtro_reporte_caja
│                             # ~700 lineas
├── payment_audit.py          # _registrar_auditoria_financiera (y futuras)
│                             # ~50 lineas
└── payment_glosa.py          # _generar_glosa_detalle, _es_concepto_generico_placeholder
                              # ~200 lineas
```

### `api/payments.py` (104KB → 4 archivos)

```
api/
├── payments.py               # Router principal: create, approve, reject, revert, delete, list
│                             # ~600 lineas
├── payments_dashboard.py     # /payments/dashboard/resumen-economico
│                             # ~300 lineas
├── payments_reports.py       # /payments/reportes/* (caja, lista-habilitados, xlsx, pdf)
│                             # ~800 lineas
└── payments_caja.py          # /payments/caja-directo
                              # ~200 lineas
```

### `api/enrollments.py` (63KB → 3 archivos)

```
api/
├── enrollments.py            # CRUD básico + retiros
│                             # ~700 lineas
├── enrollments_academic.py   # Notas, validaciones, becas
│                             # ~500 lineas
└── enrollments_reports.py    # Reportes de inscripciones
                              # ~200 lineas
```

### `services/student_service.py` (46KB → 2 archivos)

```
services/
├── student_service.py        # CRUD + importación
│                             # ~600 lineas
└── student_finance.py        # financial_summary, saldos, becados
                              # ~400 lineas
```

### `services/enrollment_service.py` (45KB → 3 archivos)

```
services/
├── enrollment_service.py     # CRUD + estados (cambiar_estado, retirar)
│                             # ~500 lineas
├── enrollment_academic.py    # Notas, becas, validaciones
│                             # ~400 lineas
└── enrollment_finance.py     # Prorrateo, waterfall, saldo_pendiente
                              # ~300 lineas
```

## Estrategia de ejecución

1. **Por archivo, de a uno**. No intentar hacer todos a la vez.
2. **Por cada archivo**:
   a. Identificar las funciones que van a cada nuevo módulo.
   b. Crear el nuevo archivo con las funciones copiadas.
   c. Re-exportar desde el archivo original para no romper imports.
   d. Reemplazar imports en otros archivos.
   e. Eliminar las funciones del archivo original.
   f. Correr suite completa de tests.
3. **Validar deploy** después de cada archivo.
4. **Rollback inmediato** si falla cualquier test (los archivos están en git).

## Criterios de éxito

- [ ] Cada archivo de servicio < 50KB
- [ ] Cada archivo de router < 50KB
- [ ] Suite de tests 372/372 pasando
- [ ] Sin breaking changes en la API pública
- [ ] No hay ciclos de imports
- [ ] El pre-commit hook sigue bypaseado con `--no-verify` (sigue roto, ver F-082)

## Estimación

- ~30-45 min por archivo
- Total: 5 archivos × 40 min = ~3-4 horas
- Recomendado: hacerlo en 2-3 sesiones (no de un solo golpe)

## Riesgos

- **Cycles**: nuevo módulo importa de original y viceversa. Mitigación: usar
  dependencias de un solo sentido (helpers en un módulo `_utils` compartido).
- **Imports rotos**: callers que importan funciones específicas del módulo
  original deben actualizarse. Mitigación: re-exports en el archivo original
  durante la transición.
- **Tests con paths hardcodeados**: `tests/test_payment_service.py` importa
  `from services.payment_service import ...`. Si muevo la función, los tests
  fallan. Mitigación: actualizar tests al mismo tiempo.

## Estado actual (2026-07-28)

✅ Identificación de archivos grandes
✅ Plan de división documentado (este archivo)
⏳ Pendiente: ejecutar la separación

## Decisión de no ejecutar ahora

El refactor es una tarea de 3-4 horas con riesgo de romper imports y tests.
Kevin aprobó hacerlo pero también dijo "hasta aquí haz estos puntos".
Decisión: documentar el plan ahora y ejecutar en una sesión dedicada con
Kevin presente, para hacer rollback rápido si algo falla.
