# 💰 INFORME COMPLETO: FLUJO DE PAGOS DEL SISTEMA

## 📌 Información del Sistema
**Sistema:** KyC Payment System API  
**Fecha del Informe:** 18 de Diciembre de 2024  
**Versión:** 1.0  
**Tipo:** Sistema de Gestión de Pagos para Cursos de Posgrado

---

## 📋 ÍNDICE

1. [Resumen Ejecutivo](#resumen-ejecutivo)
2. [Actores del Sistema](#actores-del-sistema)
3. [Flujo Completo de Pagos](#flujo-completo-de-pagos)
4. [Cálculo Inteligente de Pagos](#cálculo-inteligente-de-pagos)
5. [Estados y Transiciones](#estados-y-transiciones)
6. [Configuración de Pagos](#configuración-de-pagos)
7. [Seguridad y Validaciones](#seguridad-y-validaciones)
8. [Casos de Uso Detallados](#casos-de-uso-detallados)
9. [Reportes y Consultas](#reportes-y-consultas)
10. [Diagramas de Flujo](#diagramas-de-flujo)

---

## 1. RESUMEN EJECUTIVO

### 🎯 Objetivo del Sistema
Gestionar de forma automatizada el proceso completo de pagos de estudiantes inscritos en cursos de posgrado, desde la inscripción hasta la finalización del pago total, con cálculos automáticos y validaciones administrativas.

### ✨ Características Principales

| Característica | Descripción |
|---------------|-------------|
| **Cálculo Automático** | El sistema calcula automáticamente qué debe pagar el estudiante |
| **Pagos Inteligentes** | Solo permite pagar lo que corresponde (matrícula o cuota siguiente) |
| **Doble Descuento** | Descuento del curso + descuento personalizado del estudiante |
| **Snapshot de Precios** | El estudiante mantiene el precio al momento de inscripción |
| **Validación Admin** | Todo pago requiere aprobación administrativa |
| **Trazabilidad** | Historial completo de cada transacción |
| **Progreso Visual** | Sistema de tracking de cuotas pagadas (8/12) |

### 📊 Estadísticas del Sistema

```
┌─────────────────────────────────────────┐
│ COMPONENTES DEL SISTEMA DE PAGOS       │
├─────────────────────────────────────────┤
│ Modelos:          3 (Enrollment, Payment│
│                      PaymentConfig)     │
│ Servicios:        2 principales         │
│ Endpoints API:    15+                   │
│ Estados Payment:  3 (Pendiente,         │
│                      Aprobado, Rechazado│
│ Estados Enrollment: 5 transiciones      │
│ Validaciones:     12+ automáticas       │
└─────────────────────────────────────────┘
```

---

## 2. ACTORES DEL SISTEMA

### 👤 ESTUDIANTE (Student)

**Rol:** Usuario final que realiza pagos

**Permisos:**
- ✅ Consultar su configuración de pagos (QR, cuenta)
- ✅ Consultar sus inscripciones
- ✅ Ver qué debe pagar (monto automático)
- ✅ Subir comprobantes de pago
- ✅ Ver estado de sus pagos
- ✅ Ver historial de pagos
- ❌ NO puede modificar montos
- ❌ NO puede ver pagos de otros
- ❌ NO puede aprobar/rechazar pagos

**Endpoints Disponibles:**
```
GET  /api/v1/payment-config/          # Ver QR y cuenta
GET  /api/v1/enrollments/{id}         # Ver su inscripción
POST /api/v1/payments/                 # Subir comprobante
GET  /api/v1/payments/                 # Ver sus pagos
GET  /api/v1/payments/{id}             # Ver un pago suyo
```

---

### 👨‍💼 ADMINISTRADOR (Admin/SuperAdmin)

**Rol:** Personal administrativo que gestiona pagos

**Permisos:**
- ✅ Crear/Actualizar configuración de pagos
- ✅ Ver TODOS los pagos del sistema
- ✅ Aprobar pagos pendientes
- ✅ Rechazar pagos con motivo
- ✅ Consultar reportes y estadísticas
- ✅ Modificar inscripciones
- ✅ Ver pagos de cualquier estudiante
- ✅ Filtrar y buscar pagos

**Endpoints Disponibles:**
```
POST   /api/v1/payment-config/        # Crear config (con QR)
PUT    /api/v1/payment-config/        # Actualizar config
DELETE /api/v1/payment-config/        # Eliminar config
GET    /api/v1/payments/              # Ver TODOS los pagos
PUT    /api/v1/payments/{id}/aprobar  # Aprobar pago
PUT    /api/v1/payments/{id}/rechazar # Rechazar pago
GET    /api/v1/payments/pendientes/list # Pagos por revisar
```

---

### 🤖 SISTEMA (Automatización)

**Rol:** Lógica automática que gestiona cálculos

**Responsabilidades:**
- ✅ Calcular automáticamente el siguiente pago
- ✅ Determinar concepto (Matrícula, Cuota X)
- ✅ Calcular montos exactos
- ✅ Aplicar descuentos en cascada
- ✅ Actualizar saldos al aprobar pagos
- ✅ Cambiar estados automáticamente
- ✅ Mantener snapshot de precios
- ✅ Validar consistencia de datos

---

## 3. FLUJO COMPLETO DE PAGOS

### 🔄 FASE 1: CONFIGURACIÓN INICIAL (Admin)

El admin debe configurar el QR y cuenta bancaria antes que los estudiantes puedan pagar.

```
┌─────────────────────────────────────────┐
│  ADMIN: Configurar Método de Pago      │
└─────────────────────────────────────────┘
                ↓
    POST /api/v1/payment-config/
    - file: qr_bnb.png
    - numero_cuenta: "1234567890"
    - banco: "BNB"
    - titular: "UMSA"
                ↓
    ┌───────────────────────────┐
    │ Sistema:                  │
    │ 1. Valida imagen          │
    │ 2. Sube a Cloudinary      │
    │ 3. Guarda URL + datos     │
    │ 4. Activa configuración   │
    └───────────────────────────┘
                ↓
    ✅ SISTEMA LISTO PARA RECIBIR PAGOS
```

**Resultado:**
```json
{
  "numero_cuenta": "1234567890",
  "banco": "BNB",
  "titular": "UMSA",
  "qr_url": "https://res.cloudinary.com/.../qr_payment.png",
  "is_active": true
}
```

---

### 🔄 FASE 2: INSCRIPCIÓN DEL ESTUDIANTE (Admin)

El admin inscribe al estudiante y el sistema calcula todos los precios.

```
┌─────────────────────────────────────────┐
│  ADMIN: Inscribir Estudiante           │
└─────────────────────────────────────────┘
                ↓
    POST /api/v1/enrollments/
    - estudiante_id: "123"
    - curso_id: "456"
    - descuento_id: "789" (opcional)
                ↓
    ┌────────────────────────────────────┐
    │ Sistema Calcula Automáticamente:   │
    │ 1. Obtiene datos del curso         │
    │ 2. Determina precio (interno/      │
    │    externo)                        │
    │ 3. Aplica descuento del curso      │
    │    (si existe)                     │
    │ 4. Aplica descuento del estudiante │
    │ 5. Calcula total_a_pagar           │
    │ 6. Inicializa saldo_pendiente      │
    └────────────────────────────────────┘
                ↓
    Enrollment creado:
    - costo_total: 3000 Bs
    - costo_matricula: 500 Bs  
    - cantidad_cuotas: 12
    - descuento_curso: 10%
    - descuento_estudiante: 5%
    - total_a_pagar: 2565 Bs
    - total_pagado: 0 Bs
    - saldo_pendiente: 2565 Bs
    - estado: PENDIENTE_PAGO
```

**Cálculo de Descuentos:**
```
Precio base (interno):      3000 Bs
- Descuento curso (10%):    - 300 Bs = 2700 Bs
- Descuento estudiante (5%): - 135 Bs = 2565 Bs
────────────────────────────────────────
TOTAL A PAGAR:              2565 Bs
```

---

### 🔄 FASE 3: CONSULTA DE DEUDA (Estudiante)

El estudiante consulta cuánto debe pagar.

```
┌─────────────────────────────────────────┐
│  ESTUDIANTE: ¿Cuánto debo pagar?       │
└─────────────────────────────────────────┘
                ↓
    GET /api/v1/enrollments/{id}
                ↓
    ┌────────────────────────────────────┐
    │ Sistema Calcula en Tiempo Real:    │
    │ 1. Verifica si pagó matrícula      │
    │ 2. Si no: retorna matrícula        │
    │ 3. Si sí: calcula siguiente cuota  │
    │ 4. Determina número de cuota       │
    └────────────────────────────────────┘
                ↓
    Response:
    {
      "total_a_pagar": 2565,
      "total_pagado": 0,
      "saldo_pendiente": 2565,
      "siguiente_pago": {
        "concepto": "Matrícula",
        "numero_cuota": 0,
        "monto_sugerido": 500.0
      },
      "cuotas_pagadas_info": {
        "cuotas_pagadas": 0,
        "cuotas_totales": 12,
        "porcentaje": 0.0
      }
    }
```

---

### 🔄 FASE 4: REALIZAR PAGO (Estudiante)

El estudiante sube el comprobante de pago.

```
┌─────────────────────────────────────────┐
│  ESTUDIANTE: Realizar Pago de Matrícula│
└─────────────────────────────────────────┘
                ↓
    1. Estudiante consulta QR y cuenta:
       GET /api/v1/payment-config/
                ↓
    2. Estudiante realiza transferencia
       bancaria de 500 Bs
                ↓
    3. Estudiante sube comprobante:
       POST /api/v1/payments/
       {
         "inscripcion_id": "...",
         "numero_transaccion": "TRX-ABC123",
         "comprobante_url": "https://cloudinary..."
       }
                ↓
    ┌────────────────────────────────────┐
    │ Sistema Calcula Automáticamente:   │
    │ 1. Lee siguiente_pago del          │
    │    enrollment                      │
    │ 2. IGNORA cualquier monto que      │
    │    envíe el estudiante             │
    │ 3. USA el monto calculado (500)    │
    │ 4. Asigna concepto: "Matrícula"    │
    │ 5. Asigna numero_cuota: 0          │
    │ 6. Estado: PENDIENTE               │
    └────────────────────────────────────┘
                ↓
    Payment creado:
    {
      "concepto": "Matrícula",
      "numero_cuota": 0,
      "cantidad_pago": 500.0,  ← AUTOCALCULADO
      "estado_pago": "pendiente",
      "comprobante_url": "...",
      "fecha_subida": "2024-12-18T10:00:00Z"
    }
```

**⚠️ IMPORTANTE:**
- El estudiante **NO** puede elegir el monto
- El sistema **CALCULA** automáticamente cuánto debe pagar
- El estudiante solo proporciona: comprobante + nº transacción

---

### 🔄 FASE 5: REVISIÓN ADMIN

El admin revisa el comprobante y decide aprobar o rechazar.

```
┌─────────────────────────────────────────┐
│  ADMIN: Revisar Pagos Pendientes       │
└─────────────────────────────────────────┘
                ↓
    GET /api/v1/payments/pendientes/list
                ↓
    Admin ve lista de pagos pendientes:
    [
      {
        "id": "...",
        "estudiante_id": "...",
        "concepto": "Matrícula",
        "cantidad_pago": 500.0,
        "comprobante_url": "...",
        "numero_transaccion": "TRX-ABC123"
      }
    ]
                ↓
    Admin descarga comprobante PDF
                ↓
    Admin verifica en sistema bancario
                ↓
    ┌───────────────┬───────────────┐
    │   VÁLIDO      │   INVÁLIDO    │
    └───────────────┴───────────────┘
          ↓                ↓
    APROBAR            RECHAZAR
```

---

#### 5.1. SI EL ADMIN APRUEBA:

```
PUT /api/v1/payments/{id}/aprobar
                ↓
    ┌────────────────────────────────────┐
    │ Sistema Ejecuta Automáticamente:   │
    │ 1. Marca pago como APROBADO        │
    │ 2. Registra admin_username         │
    │ 3. Registra fecha_verificacion     │
    │ 4. Actualiza enrollment:           │
    │    - total_pagado += 500           │
    │    - saldo_pendiente -= 500        │
    │ 5. Cambia estado enrollment:       │
    │    PENDIENTE_PAGO → ACTIVO         │
    └────────────────────────────────────┘
                ↓
    Estado del Enrollment AHORA:
    {
      "total_pagado": 500,           ← +500
      "saldo_pendiente": 2065,       ← -500
      "estado": "activo",            ← Cambió!
      "siguiente_pago": {
        "concepto": "Cuota 1",       ← Siguiente
        "numero_cuota": 1,
        "monto_sugerido": 171.0
      },
      "cuotas_pagadas_info": {
        "cuotas_pagadas": 0,         ← Aún 0 (solo matrícula)
        "cuotas_totales": 12,
        "porcentaje": 0.0
      }
    }
```

---

#### 5.2. SI EL ADMIN RECHAZA:

```
PUT /api/v1/payments/{id}/rechazar
{
  "motivo": "Comprobante ilegible. Por favor suba imagen más clara"
}
                ↓
    ┌────────────────────────────────────┐
    │ Sistema:                            │
    │ 1. Marca pago como RECHAZADO       │
    │ 2. Guarda motivo_rechazo           │
    │ 3. Registra admin_username         │
    │ 4. NO actualiza enrollment         │
    └────────────────────────────────────┘
                ↓
    Estudiante puede:
    - Ver motivo del rechazo
    - Subir un nuevo comprobante
    - El enrollment se mantiene igual
```

---

### 🔄 FASE 6: PAGO DE CUOTAS (Ciclo)

El estudiante ahora debe pagar las cuotas mensuales.

```
┌─────────────────────────────────────────┐
│  CICLO: PAGO DE CUOTAS (1 a 12)        │
└─────────────────────────────────────────┘
                ↓
    Estudiante consulta:
    GET /api/v1/enrollments/{id}
                ↓
    Sistema responde:
    {
      "siguiente_pago": {
        "concepto": "Cuota 1",
        "numero_cuota": 1,
        "monto_sugerido": 171.0
      }
    }
                ↓
    Estudiante paga 171 Bs
                ↓
    POST /api/v1/payments/
    (Sistema asigna monto 171 automáticamente)
                ↓
    Admin aprueba
                ↓
    Sistema actualiza:
    - total_pagado: 671 Bs
    - cuotas_pagadas: 1/12 (8.33%)
                ↓
    [REPETIR CICLO 11 VECES MÁS]
```

**Progreso Visual:**

```
Después de pagar Cuota 1:
{
  "cuotas_pagadas_info": {
    "cuotas_pagadas": 1,
    "cuotas_totales": 12,
    "porcentaje": 8.33
  }
}

Después de pagar Cuota 8:
{
  "cuotas_pagadas_info": {
    "cuotas_pagadas": 8,
    "cuotas_totales": 12,
    "porcentaje": 66.67
  }
}

Después de pagar Cuota 12 (última):
{
  "cuotas_pagadas_info": {
    "cuotas_pagadas": 12,
    "cuotas_totales": 12,
    "porcentaje": 100.0
  },
  "saldo_pendiente": 0,
  "estado": "completado"
}
```

---

### 🔄 FASE 7: FINALIZACIÓN

Cuando el estudiante termina de pagar todo.

```
┌─────────────────────────────────────────┐
│  ESTUDIANTE: Pago Completado           │
└─────────────────────────────────────────┘
                ↓
    Admin aprueba último pago
                ↓
    ┌────────────────────────────────────┐
    │ Sistema Detecta Automáticamente:   │
    │ - saldo_pendiente = 0              │
    │ - Cambia estado: COMPLETADO        │
    └────────────────────────────────────┘
                ↓
    Enrollment Final:
    {
      "total_a_pagar": 2565,
      "total_pagado": 2565,
      "saldo_pendiente": 0,
      "estado": "completado",
      "siguiente_pago": {
        "concepto": "Pago Completado",
        "numero_cuota": 0,
        "monto_sugerido": 0
      },
      "cuotas_pagadas_info": {
        "cuotas_pagadas": 12,
        "cuotas_totales": 12,
        "porcentaje": 100.0
      }
    }
                ↓
    ✅ Estudiante puede recibir certificado
```

---

## 4. CÁLCULO INTELIGENTE DE PAGOS

### 🧮 Algoritmo de Siguiente Pago

El sistema calcula automáticamente qué debe pagar el estudiante usando el property `siguiente_pago` del modelo `Enrollment`.

```python
@property
def siguiente_pago(self) -> dict:
    # 1. ¿Ya pagó todo?
    if self.saldo_pendiente <= 0.01:
        return {
            "concepto": "Pago Completado",
            "numero_cuota": 0,
            "monto_sugerido": 0.0
        }
    
    # 2. ¿Falta pagar matrícula?
    if self.total_pagado < self.costo_matricula:
        pendiente = self.costo_matricula - self.total_pagado
        return {
            "concepto": "Matrícula",
            "numero_cuota": 0,
            "monto_sugerido": pendiente
        }
    
    # 3. Calcular siguiente cuota
    pagado_a_cuotas = self.total_pagado - self.costo_matricula
    monto_por_cuota = (self.total_a_pagar - self.costo_matricula) / self.cantidad_cuotas
    cuotas_pagadas = int(pagado_a_cuotas / monto_por_cuota)
    siguiente_cuota = cuotas_pagadas + 1
    
    return {
        "concepto": f"Cuota {siguiente_cuota}",
        "numero_cuota": siguiente_cuota,
        "monto_sugerido": monto_por_cuota
    }
```

### 📊 Ejemplos de Cálculo

#### Ejemplo 1: Recién Inscrito
```
Enrollment:
- costo_matricula: 500
- total_a_pagar: 2565
- total_pagado: 0
- cantidad_cuotas: 12

Siguiente Pago:
{
  "concepto": "Matrícula",
  "numero_cuota": 0,
  "monto_sugerido": 500.0
}
```

#### Ejemplo 2: Pagó Matrícula
```
Enrollment:
- total_pagado: 500
- saldo_pendiente: 2065

Cálculo:
- Pagado a cuotas = 500 - 500 = 0
- Total cuotas = 2565 - 500 = 2065
- Monto por cuota = 2065 / 12 = 172.08
- Cuotas pagadas = 0 / 172.08 = 0
- Siguiente = 0 + 1 = 1

Siguiente Pago:
{
  "concepto": "Cuota 1",
  "numero_cuota": 1,
  "monto_sugerido": 172.08
}
```

#### Ejemplo 3: Pagó 8 Cuotas
```
Enrollment:
- total_pagado = 500 + (8 × 172.08) = 1876.64

Cálculo:
- Pagado a cuotas = 1876.64 - 500 = 1376.64
- Cuotas pagadas = 1376.64 / 172.08 = 8
- Siguiente = 8 + 1 = 9

Siguiente Pago:
{
  "concepto": "Cuota 9",
  "numero_cuota": 9,
  "monto_sugerido": 172.08
}
```

---

## 5. ESTADOS Y TRANSICIONES

### 📌 Estados del Payment

| Estado | Descripción | Cómo Llega | Puede Cambiar A |
|--------|-------------|------------|-----------------|
| **PENDIENTE** | Comprobante subido, esperando revisión | Al crear payment | APROBADO o RECHAZADO |
| **APROBADO** | Admin verificó y aprobó el pago | Admin aprueba | *Final* |
| **RECHAZADO** | Comprobante inválido o incorrecto | Admin rechaza | *Final* (puede subir otro) |

### 📌 Estados del Enrollment

| Estado | Descripción | Cómo Llega | Puede Cambiar A |
|--------|-------------|------------|-----------------|
| **PENDIENTE_PAGO** | Inscrito pero sin pagar matrícula | Al crear enrollment | ACTIVO |
| **ACTIVO** | Matrícula pagada, cursando | Al aprobar matrícula | COMPLETADO o SUSPENDIDO |
| **SUSPENDIDO** | Suspendido por falta de pago (manual) | Admin suspende | ACTIVO |
| **COMPLETADO** | Todo pagado | Saldo = 0 | *Final* |
| **CANCELADO** | Inscripción cancelada (manual) | Admin cancela | *Final* |

### 🔄 Diagrama de Transiciones

```
ENROLLMENT:

    [CREAR INSCRIPCIÓN]
            ↓
    PENDIENTE_PAGO
            ↓
    (Pagar Matrícula + Aprobar)
            ↓
        ACTIVO ←→ SUSPENDIDO
            ↓      (manual)
    (Pagar todas las cuotas)
            ↓
      COMPLETADO

    CANCELADO (puede ocurrir en cualquier momento - manual)


PAYMENT:

    [SUBIR COMPROBANTE]
            ↓
       PENDIENTE
       ↙      ↘
  APROBADO  RECHAZADO
   (final)   (puede subir otro)
```

---

## 6. CONFIGURACIÓN DE PAGOS

### 🏦 Payment Config

El admin configura **una única** cuenta bancaria y QR para todo el sistema.

**Características:**
- ✅ **Singleton**: Solo una configuración activa
- ✅ **QR Automático**: Sube imagen directamente
- ✅ **Cloudinary**: Almacenamiento en la nube
- ✅ **Auditoría**: Registro de quién crea/modifica

**Endpoints:**

```bash
# Crear (con imagen QR)
POST /api/v1/payment-config/
Content-Type: multipart/form-data
- file: qr_payment.png
- numero_cuenta: "1234567890"
- banco: "BNB"

# Consultar (estudiantes y admins)
GET /api/v1/payment-config/

# Actualizar (solo nuevo campo o QR)
PUT /api/v1/payment-config/
- file: nuevo_qr.png (opcional)
- numero_cuenta: "9999999999" (opcional)
```

---

## 7. SEGURIDAD Y VALIDACIONES

### 🔒 Validaciones del Sistema

#### En Payment:

| Validación | Descripción | Error |
|------------|-------------|-------|
| **Estudiante dueño** | Solo puede crear pago de su inscripción | 403 Forbidden |
| **Inscripción existe** | La inscripción debe existir | 404 Not Found |
| **Monto inmutable** | Estudiante NO puede cambiar monto | N/A (se ignora) |
| **Concepto automático** | Sistema asigna concepto | N/A |
| **Estado PENDIENTE** | Solo se puede aprobar/rechazar si está pendiente | 400 Bad Request |

#### En Enrollment:

| Validación | Descripción | Error |
|------------|-------------|-------|
| **Saldo coherente** | `saldo = total_a_pagar - total_pagado` | 400 ValidationError |
| **No sobrepago** | `total_pagado <=total_a_pagar` | Saldo mínimo 0 |
| **Cuotas válidas** | `cantidad_cuotas >= 1` | 400 Bad Request |
| **Descuentos válidos** | `porcentaje >= 0 y <= 100` | 400 Bad Request |

### 🔐 Permisos por Endpoint

```
POST   /payments/                 → STUDENT only
PUT    /payments/{id}/aprobar     → ADMIN only
PUT    /payments/{id}/rechazar    → ADMIN only
GET    /payments/                 → STUDENT (propios) | ADMIN (todos)
GET    /payments/pendientes/list  → ADMIN only
POST   /payment-config/           → ADMIN only
PUT    /payment-config/           → ADMIN only
DELETE /payment-config/           → ADMIN only
GET    /payment-config/           → Authenticated (todos)
```

---

## 8. CASOS DE USO DETALLADOS

### Caso 1: Pago de Matrícula Exitoso

```
CONTEXTO:
- Juan se inscribe al Diplomado de IA
- Costo: 3000 Bs interno
- Matrícula: 500 Bs
- Cuotas: 12
- Sin descuentos

FLUJO:
1. Admin inscribe a Juan
   → estado: PENDIENTE_PAGO
   → siguiente_pago: Matrícula (500 Bs)

2. Juan consulta QR y cuenta
   → GET /payment-config/

3. Juan realiza transferencia de 500 Bs

4. Juan sube comprobante
   → POST /payments/
   → Sistema asigna monto: 500 (automático)

5. Admin aprueba pago
   → PUT /payments/{id}/aprobar

6. Sistema actualiza:
   → total_pagado: 500
   → saldo_pendiente: 2500
   → estado: ACTIVO
   → siguiente_pago: Cuota 1 (208.33 Bs)

RESULTADO:
✅ Juan puede comenzar el curso
✅ Debe ahora 12 cuotas de 208.33 Bs c/u
```

### Caso 2: Comprobante Rechazado

```
CONTEXTO:
- María sube comprobante de matrícula
- Imagen está borrosa

FLUJO:
1. María sube comprobante
   → POST /payments/
   → estado: PENDIENTE

2. Admin revisa comprobante
   → Imagen ilegible

3. Admin rechaza
   → PUT /payments/{id}/rechazar
   → motivo: "Imagen borrosa, suba foto clara"

4. María consulta su pago
   → GET /payments/{id}
   → Ve motivo_rechazo

5. María sube NUEVO comprobante con imagen clara
   → POST /payments/ (nuevo payment)

6. Admin aprueba el nuevo
   → Proceso continúa normalmente

RESULTADO:
✅ Payment anterior: RECHAZADO (queda en historial)
✅ Payment nuevo: APROBADO
✅ Enrollment se actualiza con el nuevo pago
```

### Caso 3: Cambio de Precio del Curso

```
CONTEXTO:
- Luis se inscribe cuando curso cuesta 3000 Bs
- Después admin sube precio a 4000 Bs
- ¿Luis paga 3000 o 4000?

FLUJO:
1. Luis se inscribe (Marzo 2024)
   → costo_total: 3000 (snapshot)
   → total_a_pagar: 3000

2. Admin actualiza curso (Abril 2024)
   → Course.costo_total_interno: 4000

3. Luis consulta su inscripción
   → GET /enrollments/{id}
   → total_a_pagar: 3000 (NO cambia)

4. Nuevo estudiante se inscribe (Mayo 2024)
   → costo_total: 4000 (nuevo precio)

RESULTADO:
✅ Luis paga 3000 (precio original)
✅ Nuevo estudiante paga 4000
✅ Snapshot protege a estudiantes inscritos
```

### Caso 4: Estudiante con Progreso Parcial

```
CONTEXTO:
- Ana ha pagado 8 de 12 cuotas
- Quiere saber su progreso

FLUJO:
1. Ana consulta su inscripción
   → GET /enrollments/{id}

2. Sistema responde:
   {
     "total_a_pagar": 2500,
     "total_pagado": 1667,
     "saldo_pendiente": 833,
     "cuotas_pagadas_info": {
       "cuotas_pagadas": 8,
       "cuotas_totales": 12,
       "porcentaje": 66.67
     },
     "siguiente_pago": {
       "concepto": "Cuota 9",
       "numero_cuota": 9,
       "monto_sugerido": 208.33
     }
   }

RESULTADO:
✅ Ana ve que lleva 8/12 cuotas (66.67%)
✅ Le faltan 4 cuotas
✅ Siguiente pago: Cuota 9 de 208.33 Bs
```

---

## 9. REPORTES Y CONSULTAS

### 📊 Reportes Disponibles

#### Para ADMIN:

```sql
1. Pagos Pendientes de Revisión
   GET /api/v1/payments/pendientes/list
   → Lista de comprobantes por revisar

2. Todos los Pagos (con filtros)
   GET /api/v1/payments/?estado=aprobado&curso_id=123
   → Filtrar por estado, curso, estudiante, búsqueda

3. Resumen de Pagos por Inscripción
   GET /api/v1/payments/enrollment/{id}/resumen
   → {
       "total_pagos": 5,
       "pendientes": 1,
       "aprobados": 3,
       "rechazados": 1,
       "monto_total_aprobado": 1500
     }

4. Pagos de un Curso
   GET /api/v1/payments/?curso_id=123
   → Ver todos los pagos recibidos para un curso

5. Inscripciones con Filtros
   GET /api/v1/enrollments/?estado=activo&q=Juan
   → Buscar inscripciones por estado, estudiante, curso
```

#### Para ESTUDIANTE:

```sql
1. Mis Inscripciones
   GET /api/v1/enrollments/
   → Ver todas sus inscripciones

2. Detalle de Inscripción
   GET /api/v1/enrollments/{id}
   → Ver progreso, siguiente pago, cuotas pagadas

3. Mis Pagos
   GET /api/v1/payments/
   → Ver historial completo de pagos

4. Pagos de una Inscripción
   GET /api/v1/payments/enrollment/{id}
   → Ver pagos específicos de un curso
```

---

## 10. DIAGRAMAS DE FLUJO

### 📈 Flujo Simplificado

```
┌──────────────────────────────────────────────────────┐
│                  FLUJO DE PAGOS                      │
└──────────────────────────────────────────────────────┘

ADMIN                 SISTEMA                 ESTUDIANTE
  │                      │                         │
  ├─ Configurar QR ─────►│                         │
  │                      ├─ Guardar Config         │
  │                      │                         │
  ├─ Inscribir ─────────►│                         │
  │                      ├─ Calcular Total         │
  │                      ├─ Aplicar Descuentos     │
  │                      │                         │
  │                      │◄─ Consultar Deuda ──────┤
  │                      ├─ Calcular Siguiente ───►│
  │                      │                         │
  │                      │◄─ Subir Comprobante ────┤
  │                      ├─ Calcular Monto ────────┤
  │                      ├─ Crear Payment          │
  │                      ├─ Estado: PENDIENTE      │
  │                      │                         │
  │◄─ Notificar Pago ────┤                         │
  ├─ Revisar Voucher    │                         │
  ├─ Aprobar ───────────►│                         │
  │                      ├─ Actualizar Saldo       │
  │                      ├─ Cambiar Estado         │
  │                      │                         │
  │                      ├─ Estado: APROBADO ──────►│
  │                      │                         │
  │         [REPETIR PARA CADA CUOTA]              │
  │                      │                         │
  │                      ├─ Saldo = 0?             │
  │                      ├─ Estado: COMPLETADO ────►│
  │                      │                         │
  └──────────────────────┴─────────────────────────┘
```

### 📊 Modelo de Datos

```
┌─────────────────┐      ┌─────────────────┐
│   PaymentConfig │      │     Course      │
│─────────────────│      │─────────────────│
│ qr_url          │      │ costo_total     │
│ numero_cuenta   │      │ costo_matricula │
│ banco           │      │ cantidad_cuotas │
│ is_active       │      │ descuento_id    │
└─────────────────┘      └─────────────────┘
                                  │
                                  │ 1:N
                                  ↓
                         ┌─────────────────┐
┌─────────────┐         │   Enrollment    │          ┌─────────────┐
│   Student   │ 1:N ───►│─────────────────│◄─── 1:N │   Payment   │
│─────────────│         │ total_a_pagar   │          │─────────────│
│ nombre      │         │ total_pagado    │          │ concepto    │
│ tipo        │         │ saldo_pendiente │          │ cantidad    │
└─────────────┘         │ cantidad_cuot as│          │ estado_pago │
                        │ estado          │          │ comprobante │
                        └─────────────────┘          └─────────────┘
```

---

## 📋 RESUMEN FINAL

### ✅ Características Clave

1. **Automatización Total**
   - Sistema calcula montos automáticamente
   - Estudiante NO puede equivocarse con el monto
   - Administrador solo aprueba/rechaza

2. **Seguridad**
   - Validación en múltiples niveles
   - Auditoría completa (quién, cuándo)
   - Permisos estrictos

3. **Trazabilidad**
   - Historial completo de pagos
   - Estados claros y documentados
   - Motivos de rechazo registrados

4. **Transparencia**
   - Estudiante siempre sabe cuánto debe
   - Progreso visual de cuotas
   - Estado en tiempo real

5. **Flexibilidad**
   - Descuentos personalizados
   - Snapshot de precios
   - Configuración centralizada

---

## 📚 DOCUMENTOS RELACIONADOS

- `FLUJO_INSCRIPCIONES_PAGOS.md` - Flujo completo del sistema
- `FEATURE_CUOTAS_PAGADAS.md` - Sistema de progreso de cuotas
- `CONFIGURACION_PAGOS.md` - Documentación de payment config
- `SYSTEM_WORKFLOWS.md` - Workflows del sistema

---

**Fin del Informe**  
**Fecha:** 18 de Diciembre de 2024  
**Versión:** 1.0  
**Sistema:** KyC Payment System API
