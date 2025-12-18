# 🔍 EXPLICACIÓN DETALLADA: Endpoint CREATE PAYMENT

## 📌 Información General

**Endpoint:** `POST /api/v1/payments/`  
**Permiso:** Solo STUDENT  
**Función:** Crear un nuevo pago (subir comprobante)  
**Estado Inicial:** PENDIENTE (requiere aprobación admin)

---

## 🎯 FLUJO COMPLETO

```
┌─────────────────────────────────────────────────────┐
│  ESTUDIANTE: Crear Pago                             │
└─────────────────────────────────────────────────────┘
                       ↓
    POST /api/v1/payments/
    {
      "inscripcion_id": "...",
      "numero_transaccion": "TRX-ABC123",
      "comprobante_url": "https://cloudinary.../voucher.pdf"
    }
                       ↓
    ┌────────────────────────────────────────┐
    │ 1. API Layer (api/payments.py)         │
    │    - Verifica que sea Student          │
    │    - Llama al servicio                 │
    └────────────────────────────────────────┘
                       ↓
    ┌────────────────────────────────────────┐
    │ 2. Service Layer                       │
    │    (services/payment_service.py)       │
    │    - create_payment()                  │
    └────────────────────────────────────────┘
                       ↓
    ┌────────────────────────────────────────┐
    │ 3. Validaciones                        │
    │    a) ¿Existe inscripción?             │
    │    b) ¿Es dueño el estudiante?         │
    │    c) ¿Tiene saldo pendiente?          │
    └────────────────────────────────────────┘
                       ↓
    ┌────────────────────────────────────────┐
    │ 4. Cálculo Automático                  │
    │    - Lee enrollment.siguiente_pago     │
    │    - IGNORA lo que envió el estudiante │
    │    - USA valores del sistema           │
    └────────────────────────────────────────┘
                       ↓
    ┌────────────────────────────────────────┐
    │ 5. Crear Payment                       │
    │    - Estado: PENDIENTE                 │
    │    - Concepto: autocalculado           │
    │    - Monto: autocalculado              │
    │    - Comprobante: del estudiante       │
    └────────────────────────────────────────┘
                       ↓
    ✅ Payment creado (aguarda aprobación)
```

---

## 📋 CÓDIGO EXPLICADO PASO A PASO

### PASO 1: API Layer (`api/payments.py` líneas 38-76)

```python
@router.post("/", response_model=PaymentResponse, status_code=201)
async def create_payment(
    *,
    payment_in: PaymentCreate,          # Schema con datos del estudiante
    current_user: Student = Depends(get_current_user)  # Estudiante autenticado
) -> Any:
```

**¿Qué hace?**
1. Recibe los datos del estudiante (`payment_in`)
2. Obtiene el estudiante autenticado (`current_user`)
3. Valida que sea un STUDENT (no admin)

```python
    # Solo estudiantes pueden crear pagos
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo los estudiantes pueden subir comprobantes de pago"
        )
```

4. Llama al servicio para crear el pago

```python
    try:
        payment = await payment_service.create_payment(
            payment_in=payment_in,
            student_id=current_user.id
        )
        return payment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

---

### PASO 2: Service Layer (`services/payment_service.py` líneas 26-93)

```python
async def create_payment(
    payment_in: PaymentCreate,
    student_id: PydanticObjectId
) -> Payment:
```

#### VALIDACIÓN 1: ¿Existe la inscripción?

```python
    # 1. Obtener inscripción
    enrollment = await Enrollment.get(payment_in.inscripcion_id)
    if not enrollment:
        raise ValueError(f"Inscripción {payment_in.inscripcion_id} no encontrada")
```

**¿Qué valida?**
- La inscripción ID que envió el estudiante existe en la BD
- Si NO existe → Error 400

---

#### VALIDACIÓN 2: ¿Es el estudiante dueño?

```python
    # 2. Validar que el estudiante sea dueño de la inscripción
    if enrollment.estudiante_id != student_id:
        raise ValueError(
            "No puedes crear un pago para una inscripción que no te pertenece"
        )
```

**¿Qué valida?**
- El estudiante autenticado es el dueño de la inscripción
- Previene que un estudiante pague por otro
- Si NO coincide → Error 400

---

#### CÁLCULO AUTOMÁTICO: ¿Qué debe pagar?

```python
    # 3. Calcular detalles del pago automáticamente (Single Source of Truth)
    siguiente = enrollment.siguiente_pago
    
    if siguiente["monto_sugerido"] <= 0:
        raise ValueError("Esta inscripción ya está completamente pagada")
```

**¿Qué hace `enrollment.siguiente_pago`?**
- Es un **property calculado** del modelo Enrollment
- Calcula automáticamente:
  - ¿Debe pagar matrícula o cuota?
  - ¿Qué número de cuota?
  - ¿Cuánto exactamente?

**Ejemplo de respuesta:**
```json
{
  "concepto": "Matrícula",
  "numero_cuota": 0,
  "monto_sugerido": 500.0
}
```

o

```json
{
  "concepto": "Cuota 5",
  "numero_cuota": 5,
  "monto_sugerido": 172.08
}
```

---

#### ASIGNACIÓN DE VALORES

```python
    # Forzamos los valores calculados por el sistema
    concepto_final = siguiente["concepto"]
    numero_cuota_final = siguiente["numero_cuota"] if siguiente["numero_cuota"] > 0 else None
    cantidad_final = siguiente["monto_sugerido"]
```

**⚠️ IMPORTANTE:**
- El sistema **IGNORA** cualquier valor que envíe el estudiante
- El estudiante **NO PUEDE** elegir el monto
- El concepto se calcula **AUTOMÁTICAMENTE**
- El número de cuota se asigna **AUTOMÁTICAMENTE**

**Comentario en el código:**
```python
    # Si el usuario envió una cantidad diferente, podríamos lanzar error,
    # pero para cumplir "no tiene opción de poner cantidad distinta",
    # simplemente ignoramos su input y usamos el calculado.
    # El admin verificará si el comprobante coincide con este monto.
```

---

#### CREACIÓN DEL PAYMENT

```python
    # 4. Crear pago
    payment = Payment(
        inscripcion_id=payment_in.inscripcion_id,  # Del estudiante
        estudiante_id=enrollment.estudiante_id,    # Del enrollment
        curso_id=enrollment.curso_id,              # Del enrollment
        concepto=concepto_final,                   # ← AUTOCALCULADO
        numero_cuota=numero_cuota_final,           # ← AUTOCALCULADO
        numero_transaccion=payment_in.numero_transaccion,  # Del estudiante
        cantidad_pago=cantidad_final,              # ← AUTOCALCULADO
        descuento_aplicado=payment_in.descuento_aplicado,  # Del estudiante
        comprobante_url=payment_in.comprobante_url,  # Del estudiante
        estado_pago=EstadoPago.PENDIENTE           # ← Siempre PENDIENTE
    )
    
    await payment.insert()
    return payment
```

**Campos del Payment:**

| Campo | Origen | ¿Editable? |
|-------|--------|------------|
| `inscripcion_id` | Estudiante envía | ✅ |
| `estudiante_id` | Del enrollment | ❌ (se obtiene automático) |
| `curso_id` | Del enrollment | ❌ (se obtiene automático) |
| `concepto` | **AUTOCALCULADO** | ❌ |
| `numero_cuota` | **AUTOCALCULADO** | ❌ |
| `numero_transaccion` | Estudiante envía | ✅ |
| `cantidad_pago` | **AUTOCALCULADO** | ❌ |
| `descuento_aplicado` | Estudiante envía | ✅ |
| `comprobante_url` | Estudiante envía | ✅ |
| `estado_pago` | Siempre PENDIENTE | ❌ |

---

## 📝 SCHEMA: PaymentCreate

El estudiante envía este JSON:

```json
{
  "inscripcion_id": "507f1f77bcf86cd799439013",
  "numero_transaccion": "TRX-ABC123456",
  "comprobante_url": "https://res.cloudinary.com/.../voucher.pdf",
  "descuento_aplicado": 0  // opcional
}
```

**Campos OPCIONALES (se ignoran):**
```json
{
  "concepto": "...",        // ← SE IGNORA
  "numero_cuota": 5,        // ← SE IGNORA
  "cantidad_pago": 500.0    // ← SE IGNORA
}
```

Aunque el schema los tiene como `Optional`, **el sistema NO los usa**.

---

## 🔄 EJEMPLO COMPLETO

### Contexto:
```
Estudiante: Juan Pérez
Enrollment:
  - total_a_pagar: 2565 Bs
  - total_pagado: 0 Bs
  - costo_matricula: 500 Bs
  - cantidad_cuotas: 12
```

### Paso 1: Juan consulta qué debe pagar
```bash
GET /api/v1/enrollments/{id}

Response:
{
  "siguiente_pago": {
    "concepto": "Matrícula",
    "numero_cuota": 0,
    "monto_sugerido": 500.0
  }
}
```

### Paso 2: Juan realiza transferencia de 500 Bs

### Paso 3: Juan sube comprobante
```bash
POST /api/v1/payments/
{
  "inscripcion_id": "675f...",
  "numero_transaccion": "TRX-BNB-12345",
  "comprobante_url": "https://cloudinary.com/.../voucher.pdf"
}
```

### Paso 4: Sistema procesa

**Validaciones:**
1. ✅ Inscripción existe
2. ✅ Juan es dueño de la inscripción
3. ✅ Tiene saldo pendiente (2565 Bs)

**Cálculo automático:**
```python
siguiente = enrollment.siguiente_pago
# {
#   "concepto": "Matrícula",
#   "numero_cuota": 0,
#   "monto_sugerido": 500.0
# }

concepto_final = "Matrícula"       # ← Del sistema
numero_cuota_final = None          # ← Del sistema (0 se convierte en None)
cantidad_final = 500.0             # ← Del sistema
```

**Payment creado:**
```json
{
  "_id": "675f...",
  "inscripcion_id": "675f...",
  "estudiante_id": "675f...",
  "curso_id": "675f...",
  "concepto": "Matrícula",           ← AUTOCALCULADO
  "numero_cuota": null,               ← AUTOCALCULADO
  "numero_transaccion": "TRX-BNB-12345",
  "cantidad_pago": 500.0,             ← AUTOCALCULADO
  "comprobante_url": "https://...",
  "estado_pago": "pendiente",         ← Siempre PENDIENTE
  "fecha_subida": "2024-12-18T10:00:00Z"
}
```

---

## ⚙️ ¿QUÉ PUEDES MODIFICAR?

Si planeas modificar el endpoint, aquí están las cosas que podrías cambiar:

### 1. **Agregar Validaciones Adicionales**

```python
# En payment_service.py, antes de crear el payment

# Validar que el comprobante sea válido
if not payment_in.comprobante_url.startswith("https://"):
    raise ValueError("URL del comprobante inválida")

# Validar formato de número de transacción
if len(payment_in.numero_transaccion) < 5:
    raise ValueError("Número de transacción muy corto")

# Prevenir pagos duplicados
existing = await Payment.find_one({
    "numero_transaccion": payment_in.numero_transaccion,
    "inscripcion_id": payment_in.inscripcion_id
})
if existing:
    raise ValueError("Ya existe un pago con este número de transacción")
```

---

### 2. **Cambiar a Upload Directo del Comprobante**

Actualmente el estudiante sube el PDF a Cloudinary manualmente y envía la URL.

**Podrías cambiarlo a:**

```python
# api/payments.py
from fastapi import UploadFile, Form, File

@router.post("/", response_model=PaymentResponse, status_code=201)
async def create_payment(
    *,
    file: UploadFile = File(..., description="Comprobante PDF"),
    inscripcion_id: str = Form(...),
    numero_transaccion: str = Form(...),
    current_user: Student = Depends(get_current_user)
):
    from core.cloudinary_utils import upload_pdf
    
    # Subir PDF automáticamente
    folder = f"payments/{current_user.id}"
    public_id = f"voucher_{numero_transaccion}"
    comprobante_url = await upload_pdf(file, folder, public_id)
    
    # Crear payment con URL generada
    payment_in = PaymentCreate(
        inscripcion_id=inscripcion_id,
        numero_transaccion=numero_transaccion,
        comprobante_url=comprobante_url
    )
    
    payment = await payment_service.create_payment(
        payment_in=payment_in,
        student_id=current_user.id
    )
    return payment
```

---

### 3. **Permitir Pagos Parciales**

Actualmente el sistema force el monto completo de la cuota.

**Podrías permitir pagos parciales:**

```python
# En payment_service.py

# En lugar de:
cantidad_final = siguiente["monto_sugerido"]

# Podrías usar:
cantidad_enviada = payment_in.cantidad_pago
monto_sugerido = siguiente["monto_sugerido"]

# Validar que no exceda
if cantidad_enviada > monto_sugerido:
    raise ValueError(f"El monto no puede exceder {monto_sugerido} Bs")

# Permitir menor
cantidad_final = cantidad_enviada
```

**Pero tendrías que modificar la lógica de aprobar:**
- Si pago parcial de matrícula → No activar enrollment
- Si pago parcial de cuota → Registrar pero no avanzar cuota

---

### 4. **Agregar Notificaciones**

```python
# Después de crear el payment

# Notificar al admin
await send_notification_to_admin(
    message=f"Nuevo pago pendiente de {student.nombre}",
    payment_id=payment.id
)

# Notificar al estudiante
await send_email_to_student(
    email=student.email,
    subject="Comprobante recibido",
    message=f"Tu pago de {payment.cantidad_pago} Bs está en revisión"
)
```

---

### 5. **Agregar Campo de Notas**

```python
# En PaymentCreate schema
notas: Optional[str] = Field(
    None,
    max_length=500,
    description="Notas adicionales del estudiante"
)

# En Payment model
notas: Optional[str] = Field(None)

# Usar en create_payment
payment = Payment(
    # ... otros campos ...
    notas=payment_in.notas
)
```

---

## 🎯 RESUMEN

### ¿Qué hace el endpoint?

1. ✅ Recibe comprobante del estudiante
2. ✅ Valida que sea dueño de la inscripción
3. ✅ **CALCULA AUTOMÁTICAMENTE** qué debe pagar
4. ✅ **IGNORA** montos que envíe el estudiante
5. ✅ Crea payment en estado **PENDIENTE**
6. ✅ Espera aprobación del admin

### ¿Qué NO puede hacer el estudiante?

❌ Elegir el monto  
❌ Elegir el concepto  
❌ Elegir el número de cuota  
❌ Aprobar su propio pago  

### ¿Qué SÍ puede hacer el estudiante?

✅ Elegir qué inscripción  
✅ Subir comprobante  
✅ Poner número de transacción  
✅ Ver estado de su pago  

---

## 📂 Archivos Involucrados

```
Sistema de Creación de Pagos:

├── api/payments.py (líneas 38-76)
│   └── POST / → create_payment()
│       - Valida que sea Student
│       - Llama al servicio
│
├── services/payment_service.py (líneas 26-93)
│   └── create_payment()
│       - Valida inscripción
│       - Calcula monto automático
│       - Crea Payment
│
├── schemas/payment.py (líneas 22-85)
│   └── PaymentCreate
│       - Define campos entrada
│
└── models/enrollment.py
    └── propert siguiente_pago
        - Calcula qué debe pagar
```

---

**¿Qué específicamente quieres modificar?** Te puedo ayudar a implementar el cambio que necesites. 🚀
