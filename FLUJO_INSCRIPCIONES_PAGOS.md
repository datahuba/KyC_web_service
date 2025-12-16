# Flujo de Inscripciones y Pagos - Sistema KyC

## 📌 Documento Técnico
**Versión:** 1.2 (Actualizado con Filtros y Pagos Inteligentes)  
**Fecha:** 16 de Diciembre de 2024  
**Sistema:** KyC Payment System API

---

## 📋 Índice

1. [Actores del Sistema](#actores-del-sistema)
2. [Fase 1: Registro del Estudiante](#fase-1-registro-del-estudiante)
3. [Fase 2: Creación del Curso](#fase-2-creación-del-curso)
4. [Fase 3: Inscripción (Core)](#fase-3-inscripción)
5. [Fase 4: Pagos Inteligentes](#fase-4-pagos)
6. [Fase 5: Finalización](#fase-5-finalización)
7. [Filtros y Búsquedas](#filtros-y-búsquedas)
8. [Diagrama de Flujo](#diagrama-de-flujo)
9. [Estados y Transiciones](#estados-y-transiciones)
10. [Casos Especiales](#casos-especiales)

---

## 👥 Actores del Sistema

| Actor | Rol | Responsabilidades |
|-------|-----|-------------------|
| **Admin** | Personal administrativo | Crear estudiantes, cursos, inscripciones. Aprobar/rechazar pagos |
| **Estudiante** | Usuario final | Subir documentos, realizar pagos |
| **Sistema** | Automatización | Calcular precios, actualizar estados, validar datos, sugerir pagos |

---

## 🔄 FASE 1: Registro del Estudiante

### 1.1. Admin crea al estudiante

**Endpoint:** `POST /api/v1/students/`  
**Permiso:** ADMIN/SUPERADMIN

```json
{
  "registro": "2024001",
  "carnet": "1234567"
}
```

**Resultado:**
- Password inicial = carnet (hasheado con bcrypt)
- Estado: `activo`
- Todos los demás campos opcionales (nombre, email, etc.)

---

### 1.2. Estudiante sube documentos personales

**Endpoints:**
- `POST /students/me/upload/photo` - Foto de perfil
- `POST /students/me/upload/cv` - Currículum vitae
- `POST /students/me/upload/carnet` - Carnet de identidad (PDF)
- `POST /students/me/upload/afiliacion` - Certificado de afiliación profesional (opcional)

**Formato:**
```http
POST /students/me/upload/cv
Content-Type: multipart/form-data

file: [archivo.pdf]
```

**Resultado:**
```json
{
  "cv_url": "https://res.cloudinary.com/.../cv.pdf",
  "ci_url": "https://res.cloudinary.com/.../carnet.pdf",
  "foto_url": "https://res.cloudinary.com/.../foto.jpg"
}
```

---

### 1.3. Subir título profesional

**Endpoint:** `POST /students/{id}/upload/titulo`  
**Permiso:** ADMIN o STUDENT (propio)

```http
POST /students/{id}/upload/titulo
Content-Type: multipart/form-data

file: [titulo.pdf]
universidad: "UMSA"
numero_titulo: "12345"
año_expedicion: "2020"
titulo: "Licenciatura en Ingeniería de Sistemas"
```

**Resultado:**
```json
{
  "titulo": {
    "universidad": "UMSA",
    "numero_titulo": "12345",
    "año_expedicion": "2020",
    "titulo": "Licenciatura en Ingeniería de Sistemas",
    "titulo_url": "https://res.cloudinary.com/.../titulo.pdf",
    "estado": "pendiente"
  }
}
```

---

### 1.4. Admin verifica el título

**Endpoint:** `PUT /students/{id}/titulo/verificar`  
**Permiso:** ADMIN/SUPERADMIN

**Resultado:**
- `titulo.estado` → `verificado`
- `titulo.verificado_por` → `"admin1"`
- `titulo.fecha_verificacion` → timestamp actual

---

## 📚 FASE 2: Creación del Curso

### 2.1. Admin crea el curso

**Endpoint:** `POST /api/v1/courses/`  
**Permiso:** ADMIN/SUPERADMIN

```json
{
  "codigo": "DIPL-2024-001",
  "nombre_programa": "Diplomado en Ciencia de Datos e IA",
  "tipo_curso": "diplomado",
  "modalidad": "híbrido",
  "costo_total_interno": 3000,
  "costo_total_externo": 5000,
  "matricula_interno": 500,
  "matricula_externo": 500,
  "cantidad_cuotas": 5,
  "descuento_id": "507f1f77bcf86cd799439099", // Opcional: Descuento global
  "observacion": "Incluye certificación internacional"
}
```

**Notas importantes:**
- `costo_total_interno`: Precio para estudiantes de la universidad
- `costo_total_externo`: Precio para público general
- `descuento_id`: ID de un descuento global que aplicará a **todos** los inscritos.
- **NO** se guardan montos de cuota, se calculan dinámicamente

**Cálculo de cuota:**
```
monto_cuota = (costo_total - matricula) / cantidad_cuotas

Ejemplo interno:
(3000 - 500) / 5 = 500 Bs por cuota

Ejemplo externo:
(5000 - 500) / 5 = 900 Bs por cuota
```

---

## 📝 FASE 3: Inscripción

### 3.1. Admin inscribe al estudiante

**Endpoint:** `POST /api/v1/enrollments/`  
**Permiso:** ADMIN/SUPERADMIN

```json
{
  "estudiante_id": "507f1f77bcf86cd799439011",
  "curso_id": "507f1f77bcf86cd799439012",
  "descuento_id": "507f1f77bcf86cd799439088" // Opcional: Descuento específico para este estudiante
}
```

### 🔥 Proceso automático del sistema:

#### Paso 1: Obtener datos
```
Student.es_estudiante_interno = INTERNO
Course.costo_total_interno = 3000 Bs
Course tiene descuento_id (Global) = 10%
Enrollment tiene descuento_id (Estudiante) = 5%
```

#### Paso 2: Calcular precio base
```
Precio base = 3000 Bs (costo_total_interno)
```

#### Paso 3: Aplicar descuento del curso (Nivel 1)
```
Descuento curso = 3000 × 10% = 300 Bs
Precio intermedio = 3000 - 300 = 2700 Bs
```

#### Paso 4: Aplicar descuento del estudiante (Nivel 2)
```
Descuento estudiante = 2700 × 5% = 135 Bs
Precio final = 2700 - 135 = 2565 Bs
```

#### Paso 5: Crear Enrollment (snapshot)
```json
{
  "id": "507f1f77bcf86cd799439013",
  "estudiante_id": "507f1f77bcf86cd799439011",
  "curso_id": "507f1f77bcf86cd799439012",
  "es_estudiante_interno": "interno",
  "costo_total": 3000,
  "costo_matricula": 500,
  "cantidad_cuotas": 5,
  
  "descuento_curso_id": "507f1f77bcf86cd799439099",
  "descuento_curso_aplicado": 10,
  
  "descuento_estudiante_id": "507f1f77bcf86cd799439088",
  "descuento_personalizado": 5,
  
  "total_a_pagar": 2565,
  "total_pagado": 0,
  "saldo_pendiente": 2565,
  "estado": "pendiente_pago"
}
```

### ⚠️ Importante: Snapshot de precios

Si el curso cambia de precio después de la inscripción:
- **Course.costo_total_interno** cambia de 3000 → 4000
- **Enrollment.total_a_pagar** se mantiene en 2565 ✅

El estudiante **mantiene** el precio que tenía al momento de inscribirse.

---

## 💰 FASE 4: Pagos Inteligentes

### 4.1. Consulta de Deuda (Estudiante)

El estudiante consulta su inscripción y el sistema le sugiere qué pagar.

**Endpoint:** `GET /api/v1/enrollments/{id}`

**Response:**
```json
{
  "id": "...",
  "total_pagado": 0,
  "siguiente_pago": {
    "concepto": "Matrícula",
    "numero_cuota": 0,
    "monto_sugerido": 500.0
  }
}
```

---

### 4.2. Registro de Pago (Estudiante)

#### 4.2.1. Estudiante sube comprobante

**Endpoint:** `POST /api/v1/payments/`  
**Permiso:** STUDENT (autenticado)

```json
{
  "inscripcion_id": "507f1f77bcf86cd799439013",
  "numero_transaccion": "TRX-ABC123456",
  "comprobante_url": "https://res.cloudinary.com/.../voucher.pdf"
  // Nota: NO es necesario enviar monto ni concepto, el sistema lo calcula.
}
```

**Response:**
```json
{
  "id": "507f1f77bcf86cd799439014",
  "concepto": "Matrícula",     // Autocalculado
  "cantidad_pago": 500,        // Autocalculado
  "estado_pago": "pendiente",
  "fecha_subida": "2024-12-11T10:00:00Z"
}
```

Estado: **PENDIENTE** (esperando aprobación del admin)

---

#### 4.2.2. Admin revisa pagos pendientes

**Endpoint:** `GET /api/v1/payments/pendientes/list`  
**Permiso:** ADMIN/SUPERADMIN

El admin:
1. Abre el PDF del comprobante
2. Verifica en el sistema bancario
3. Confirma que el pago existe y coincide con el monto calculado

---

#### 4.2.3. Admin APRUEBA el pago

**Endpoint:** `PUT /api/v1/payments/{payment_id}/aprobar`  
**Permiso:** ADMIN/SUPERADMIN

**Request:** (vacío, solo requiere autenticación)

### 🔥 Proceso automático del sistema:

#### Actualiza Payment:
```json
{
  "estado_pago": "aprobado",
  "verificado_por": "admin1",
  "fecha_verificacion": "2024-12-11T11:00:00Z"
}
```

#### Actualiza Enrollment:
```json
{
  "total_pagado": 500,        // 0 + 500
  "saldo_pendiente": 2065,    // 2565 - 500
  "estado": "activo"          // PENDIENTE_PAGO → ACTIVO ✅
}
```

**Estado cambia automáticamente:**
- `PENDIENTE_PAGO` → `ACTIVO` cuando paga la matrícula

---

#### 4.2.4. O si el comprobante es inválido...

**Endpoint:** `PUT /api/v1/payments/{payment_id}/rechazar`  
**Permiso:** ADMIN/SUPERADMIN

```json
{
  "motivo": "El voucher está ilegible. Por favor, suba un comprobante de mejor calidad"
}
```

**Resultado:**
```json
{
  "estado_pago": "rechazado",
  "verificado_por": "admin1",
  "motivo_rechazo": "El voucher está ilegible...",
  "fecha_verificacion": "2024-12-11T11:00:00Z"
}
```

- **NO** actualiza el Enrollment
- El estudiante puede ver el motivo
- El estudiante puede subir un nuevo comprobante

---

## 🔍 Filtros y Búsquedas

El sistema ofrece potentes herramientas de búsqueda para el Administrador.

### A. Buscador de Inscripciones (`GET /enrollments/`)
*   **Búsqueda de Texto (`q`)**: Busca coincidencias parciales en:
    *   Nombre del Estudiante
    *   Carnet de Identidad
    *   Nombre del Curso
*   **Filtros Específicos**:
    *   `estado`: (pendiente_pago, activo, completado...)
    *   `curso_id`: Inscripciones de un curso específico
    *   `estudiante_id`: Inscripciones de un estudiante específico

### B. Buscador de Pagos (`GET /payments/`)
*   **Búsqueda de Texto (`q`)**: Busca coincidencias parciales en:
    *   Número de Transacción
    *   Concepto
    *   URL del comprobante
*   **Filtros Específicos**:
    *   `estado`: (pendiente, aprobado, rechazado)
    *   `curso_id`
    *   `estudiante_id`

### C. Buscador de Cursos (`GET /courses/`)
*   **Búsqueda de Texto (`q`)**: Nombre del programa o Código.
*   **Filtros**: `activo`, `tipo_curso`, `modalidad`.

---

## 🎓 FASE 5: Finalización

### Estado final del Enrollment:

```json
{
  "id": "507f1f77bcf86cd799439013",
  "estudiante_id": "507f1f77bcf86cd799439011",
  "curso_id": "507f1f77bcf86cd799439012",
  "total_a_pagar": 2565,
  "total_pagado": 2565,
  "saldo_pendiente": 0,
  "estado": "completado"
}
```

**El estudiante puede:**
- ✅ Recibir certificado/diploma
- ✅ Acceder a su título
- ✅ Consultar historial completo de pagos
- ✅ Solicitar constancias

---

## 📊 Diagrama de Flujo

```
┌─────────────────────────────────────────────────────────────┐
│ FASE 1: REGISTRO                                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
        Admin crea Student (registro + carnet)
                            ↓
        Student sube documentos (CV, CI, foto)
                            ↓
        Student/Admin sube título profesional
                            ↓
        Admin verifica título
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ FASE 2: CURSO                                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
        Admin crea Course con precios y descuento global
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ FASE 3: INSCRIPCIÓN                                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
        Admin crea Enrollment (selecciona descuento estudiante)
                            ↓
        Sistema calcula precios (Doble Descuento)
                            ↓
        Enrollment.estado = PENDIENTE_PAGO
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ FASE 4: PAGOS                                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
        ┌─────────────────────────────────────┐
        │ MATRÍCULA                           │
        └─────────────────────────────────────┘
                            ↓
        Sistema sugiere monto exacto
                            ↓
        Student sube comprobante (Monto autocalculado)
                            ↓
        Payment.estado = PENDIENTE
                            ↓
        Admin revisa comprobante
                            ↓
        ┌─────────────┬──────────────┐
        │   VÁLIDO    │   INVÁLIDO   │
        └─────────────┴──────────────┘
              ↓                ↓
         APROBAR          RECHAZAR
              ↓                ↓
    Enrollment.estado   Student ve motivo
       = ACTIVO         Puede subir otro
              ↓
        ┌─────────────────────────────────────┐
        │ CUOTAS (1, 2, 3, 4, 5)              │
        └─────────────────────────────────────┘
              ↓
        Sistema sugiere siguiente cuota
              ↓
        Student sube comprobante
              ↓
        Admin aprueba
              ↓
        Actualiza saldo
              ↓
        ¿Saldo = 0? ───No──→ Continúa pagando
              │
             Sí
              ↓
┌─────────────────────────────────────────────────────────────┐
│ FASE 5: COMPLETADO                                          │
└─────────────────────────────────────────────────────────────┘
              ↓
        Enrollment.estado = COMPLETADO
              ↓
        Puede recibir certificado/diploma
```

---

## 🔄 Estados y Transiciones

### Enrollment.estado

| Estado | Descripción | Cómo llega | Siguiente estado |
|--------|-------------|------------|------------------|
| `PENDIENTE_PAGO` | Inscrito, sin pagar matrícula | Al crear enrollment | `ACTIVO` |
| `ACTIVO` | Pagó matrícula, cursando | Al aprobar matrícula | `COMPLETADO` o `SUSPENDIDO` |
| `SUSPENDIDO` | Atrasado en pagos | Manual (admin) | `ACTIVO` |
| `COMPLETADO` | Pagó todo | Cuando saldo = 0 | Final |
| `CANCELADO` | Inscripción cancelada | Manual (admin) | Final |

### Payment.estado_pago

| Estado | Descripción | Cómo llega | Siguiente estado |
|--------|-------------|------------|------------------|
| `PENDIENTE` | Voucher subido, esperando | Al crear payment | `APROBADO` o `RECHAZADO` |
| `APROBADO` | Admin verificó y aprobó | Admin aprueba | Final |
| `RECHAZADO` | Voucher inválido | Admin rechaza | Puede subir otro |

---

## ⚠️ Casos Especiales

### ¿Qué pasa si el curso cambia de precio?

**Escenario:**
1. Estudiante se inscribe cuando el curso cuesta 3000 Bs
2. Admin cambia `Course.costo_total_interno` a 4000 Bs
3. ¿El estudiante paga 3000 o 4000?

**Response:** El estudiante paga **3000 Bs** ✅

**Razón:** El `Enrollment` guarda un **snapshot** de precios:
```json
{
  "costo_total": 3000,  // Precio al momento de inscripción
  "total_a_pagar": 2565 // No cambia aunque el curso cambie
}
```

---

### ¿Puede un estudiante inscribirse 2 veces al mismo curso?

**No** ❌

El sistema valida al crear enrollment:
```
Si existe Enrollment donde:
  - estudiante_id = X
  - curso_id = Y
  - estado != CANCELADO

→ Error: "El estudiante ya está inscrito en este curso"
```

Para reinscribir, el admin debe:
1. Cancelar el enrollment anterior
2. Crear un nuevo enrollment

---

### ¿Qué pasa si el admin rechaza un pago?

1. `Payment.estado_pago` = `RECHAZADO`
2. `Payment.motivo_rechazo` = razón del rechazo
3. El `Enrollment` **NO** se actualiza
4. El estudiante puede:
   - Ver el motivo en `GET /payments/{id}`
   - Subir un nuevo comprobante
   - El nuevo pago será otra transacción separada

---

### ¿Puede un estudiante ver pagos de otros?

**No** ❌

Validación en el endpoint:
```python
if isinstance(current_user, Student):
    if payment.estudiante_id != current_user.id:
        raise HTTPException(403, "No tienes permiso")
```

---

### ¿Cómo funcionan los descuentos acumulados?

**Ejemplo:**
- Curso tiene `descuento_curso` = 10%
- Admin da `descuento_personalizado` = 5% al estudiante

**Cálculo:**
```
Paso 1: Aplicar descuento del curso
3000 - (3000 × 10%) = 2700

Paso 2: Aplicar descuento personalizado
2700 - (2700 × 5%) = 2565
```

Los descuentos son **acumulativos** y se aplican en cascada.

---

## 📝 Resumen Ejecutivo

### Responsabilidades por Actor

| Tarea | Admin | Student | Sistema |
|-------|-------|---------|---------|
| Crear estudiante | ✅ | ❌ | - |
| Subir documentos | - | ✅ | - |
| Crear curso | ✅ | ❌ | - |
| Crear inscripción | ✅ | ❌ | - |
| Calcular precios | - | - | ✅ |
| Subir pagos | - | ✅ | - |
| Aprobar/Rechazar pagos | ✅ | ❌ | - |
| Actualizar saldos | - | - | ✅ |
| Cambiar estados | - | - | ✅ |

### Puntos Clave

1. ✅ **Admin crea inscripciones**, NO el estudiante
2. ✅ **Estudiante crea pagos**, admin los aprueba
3. ✅ **Precios se calculan automáticamente** al inscribir
4. ✅ **Snapshot protege** al estudiante de cambios de precio
5. ✅ **Estados cambian automáticamente** según pagos
6. ✅ **Trazabilidad completa** de cada transacción
7. ✅ **Pagos Autocalculados** evitan errores de monto

---

## 🔗 Endpoints Resumen

### Inscripciones
- `POST /api/v1/enrollments/` - Crear inscripción **(ADMIN)**
- `GET /api/v1/enrollments/` - Listar inscripciones
- `GET /api/v1/enrollments/{id}` - Ver inscripción
- `PATCH /api/v1/enrollments/{id}` - Actualizar **(ADMIN)**

### Pagos
- `POST /api/v1/payments/` - Subir comprobante **(STUDENT)**
- `GET /api/v1/payments/` - Listar pagos
- `GET /api/v1/payments/{id}` - Ver pago
- `PUT /api/v1/payments/{id}/aprobar` - Aprobar **(ADMIN)**
- `PUT /api/v1/payments/{id}/rechazar` - Rechazar **(ADMIN)**
- `GET /api/v1/payments/pendientes/list` - Pagos por revisar **(ADMIN)**

---

**Fin del documento**
