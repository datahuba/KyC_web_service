# ✅ ACTUALIZACIÓN: Comprobantes como Imagen o PDF

## 📸 CAMBIO FINAL IMPLEMENTADO

El endpoint ahora acepta **tanto imágenes como PDFs** para los comprobantes de pago, ya que la mayoría serán **fotos tomadas con celular**.

---

## 🎯 FORMATOS ACEPTADOS

### ✅ Imágenes (Principales)
- **JPG / JPEG** - Fotos de celular
- **PNG** - Capturas de pantalla
- **WEBP** - Formato moderno

**Tamaño máximo:** 5MB  
**Uso típico:** 📱 Foto del comprobante con el celular

### ✅ PDFs (Casos raros)
- **PDF** - Comprobantes digitales

**Tamaño máximo:** 10MB  
**Uso típico:** 💻 Comprobante digital del banco

---

## 🔄 CÓMO FUNCIONA

### Detección Automática

```python
# El sistema detecta automáticamente el tipo
if file.content_type in ["image/jpeg", "image/jpg", "image/png", "image/webp"]:
    # Es imagen → upload_image()
    comprobante_url = await upload_image(file, folder, public_id)
    
elif file.content_type == "application/pdf":
    # Es PDF → upload_pdf()
    comprobante_url = await upload_pdf(file, folder, public_id)
    
else:
    # Formato no permitido
    raise HTTPException(400, "Use imagen (JPG, PNG, WEBP) o PDF")
```

---

## 📝 EJEMPLOS DE USO

### 📱 Caso 1: Foto del Comprobante (Más Común)

```bash
# Estudiante toma foto con su celular
# Archivo: comprobante.jpg (2.3 MB)

curl -X POST http://localhost:8000/api/v1/payments/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/ruta/foto_comprobante.jpg" \
  -F "inscripcion_id=675f..." \
  -F "numero_transaccion=TRX-001"
```

**Sistema:**
1. ✅ Detecta que es JPG
2. ✅ Valida tamaño (<5MB)
3. ✅ Usa `upload_image()
`
4. ✅ Optimiza la imagen automáticamente
5. ✅ Sube a Cloudinary
6. ✅ Crea payment con URL

---

### 🖼️ Caso 2: Captura de Pantalla (PNG)

```javascript
// Frontend React
const handleSubmit = async (e) => {
  e.preventDefault();
  
  const formData = new FormData();
  formData.append('file', screenshotFile);  // PNG de captura
  formData.append('inscripcion_id', enrollmentId);
  formData.append('numero_transaccion', 'TRX-002');
  
  await fetch('/api/v1/payments/', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` },
    body: formData
  });
};
```

---

### 📄 Caso 3: PDF del Banco (Raro)

```bash
# Estudiante descarga comprobante PDF del banco
# Archivo: comprobante_banco.pdf (800 KB)

curl -X POST http://localhost:8000/api/v1/payments/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@comprobante_banco.pdf" \
  -F "inscripcion_id=675f..." \
  -F "numero_transaccion=TRX-003"
```

**Sistema:**
1. ✅ Detecta que es PDF
2. ✅ Valida tamaño (<10MB)
3. ✅ Usa `upload_pdf()`
4. ✅ Sube a Cloudinary
5. ✅ Crea payment con URL

---

## ⚠️ VALIDACIONES

| Formato | Validación | Error si... |
|---------|------------|-------------|
| **JPG** | `content_type == "image/jpeg"` | No es imagen válida |
| **PNG** | `content_type == "image/png"` | No es imagen válida |
| **WEBP** | `content_type == "image/webp"` | No es imagen válida |
| **PDF** | `content_type == "application/pdf"` | No es PDF válido |
| **Tamaño imagen** | < 5MB | Imagen muy grande |
| **Tamaño PDF** | < 10MB | PDF muy grande |
| **Otros formatos** | ❌ | Error 400: "Formato no permitido" |

---

## 🎨 Interface de Usuario

### HTML Input

```html
<!-- Acepta imágenes Y PDFs -->
<input 
  type="file" 
  id="comprobante" 
  accept="image/jpeg,image/jpg,image/png,image/webp,application/pdf"
  capture="environment"  <!-- Activa cámara en móviles -->
  required
/>
```

### React Component

```jsx
function ComprobanteUpload() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  
  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    setFile(selectedFile);
    
    // Preview solo para imágenes
    if (selectedFile && selectedFile.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onloadend = () => setPreview(reader.result);
      reader.readAsDataURL(selectedFile);
    } else {
      setPreview(null); // Es PDF, no hay preview
    }
  };
  
  return (
    <div>
      <input 
        type="file"
        accept="image/jpeg,image/png,image/webp,application/pdf"
        onChange={handleFileChange}
      />
      
      {preview && (
        <img src={preview} alt="Preview" style={{maxWidth: '300px'}} />
      )}
      
      {file && !preview && (
        <p>📄 PDF seleccionado: {file.name}</p>
      )}
    </div>
  );
}
```

### Mobile-First (Foto desde celular)

```html
<!-- Input optimizado para móvil -->
<label class="upload-btn">
  📸 Tomar Foto del Comprobante
  <input 
    type="file" 
    accept="image/*"          <!-- Solo imágenes en móvil -->
    capture="environment"      <!-- Abre cámara trasera -->
    style="display: none"
  />
</label>

<!-- O cargar desde galería -->
<label class="upload-btn">
  🖼️ Seleccionar desde Galería
  <input 
    type="file" 
    accept="image/*,application/pdf"
    style="display: none"
  />
</label>
```

---

## 📊 RESPUESTA

El sistema retorna la misma estructura, sin importar si fue imagen o PDF:

```json
{
  "_id": "675f...",
  "comprobante_url": "https://res.cloudinary.com/.../voucher_TRX-001.jpg",
  "concepto": "Matrícula",
  "cantidad_pago": 500.0,
  "estado_pago": "pendiente",
  "fecha_subida": "2024-12-18T15:00:00Z"
}
```

**Nota:** El `comprobante_url` tendrá extensión según el archivo original:
- `.jpg` para fotos JPG
- `.png` para capturas PNG
- `.pdf` para PDFs

---

## 🔍 VENTAJAS POR FORMATO

### 📸 Imágenes (JPG, PNG, WEBP)

**Ventajas:**
- ✅ Más fácil (tomar foto con celular)
- ✅ Más rápido
- ✅ Cloudinary optimiza automáticamente
- ✅ Redimensiona si es muy grande
- ✅ Convierte a formato eficiente
- ✅ Visualización directa en navegador

**Optimizaciones de Cloudinary:**
```javascript
// Cloudinary aplica automáticamente:
- Redimensionar: max 800x800
- Calidad: auto
- Formato: auto (WebP si el navegador soporta)
```

---

### 📄 PDFs

**Ventajas:**
- ✅ Mejor calidad
- ✅ Comprobantes oficiales del banco
- ✅ Múltiples páginas si es necesario
- ✅ Formato profesional

**Desventajas:**
- ⚠️ No se puede previsualizar en navegador (necesita abrir)
- ⚠️ Archivos más grandes

---

## 💡 RECOMENDACIONES PARA FRONTEND

### 1. **Mostrar Formatos Aceptados**

```jsx
<div className="upload-instructions">
  <p>📸 Formatos aceptados:</p>
  <ul>
    <li>✅ Foto JPG/PNG (recomendado)</li>
    <li>✅ Captura de pantalla PNG</li>
    <li>✅ PDF del banco</li>
  </ul>
  <p>📏 Tamaño máximo: 5MB (imágenes) / 10MB (PDF)</p>
</div>
```

---

### 2. **Validación en el Cliente**

```javascript
function validateFile(file) {
  const validTypes = [
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/webp',
    'application/pdf'
  ];
  
  const maxSizeImage = 5 * 1024 * 1024; // 5MB
  const maxSizePDF = 10 * 1024 * 1024; // 10MB
  
  // Validar tipo
  if (!validTypes.includes(file.type)) {
    alert('Formato no permitido. Use JPG, PNG, WEBP o PDF');
    return false;
  }
  
  // Validar tamaño
  const isImage = file.type.startsWith('image/');
  const maxSize = isImage ? maxSizeImage : maxSizePDF;
  
  if (file.size > maxSize) {
    const limitMB = maxSize / (1024 * 1024);
    alert(`Archivo muy grande. Máximo: ${limitMB}MB`);
    return false;
  }
  
  return true;
}
```

---

### 3. **Preview Condicional**

```jsx
function ComprobantePreview({ file }) {
  if (!file) return null;
  
  const isImage = file.type.startsWith('image/');
  
  if (isImage) {
    return (
      <div className="preview">
        <img src={URL.createObjectURL(file)} alt="Preview" />
        <p>✅ Imagen lista para subir</p>
      </div>
    );
  } else {
    return (
      <div className="preview">
        <div className="pdf-icon">📄</div>
        <p>{file.name}</p>
        <p>✅ PDF listo para subir</p>
      </div>
    );
  }
}
```

---

### 4. **Compresión de Imágenes (Opcional)**

```javascript
// Si la imagen es muy grande, comprimirla antes de subir
import imageCompression from 'browser-image-compression';

async function compressImage(file) {
  if (!file.type.startsWith('image/')) {
    return file; // No comprimir PDFs
  }
  
  const options = {
    maxSizeMB: 2,          // Máximo 2MB
    maxWidthOrHeight: 1920,  // Máx 1920px
    useWebWorker: true
  };
  
  try {
    const compressed = await imageCompression(file, options);
    console.log(`Comprimido: ${file.size/1024}KB → ${compressed.size/1024}KB`);
    return compressed;
  } catch (error) {
    console.error('Error al comprimir:', error);
    return file; // Retornar original si falla
  }
}
```

---

## 📱 FLUJO TÍPICO EN MÓVIL

```
1. Usuario abre app en celular
       ↓
2. Hace clic en "Subir Comprobante"
       ↓
3. Sistema abre cámara
       ↓
4. Usuario toma foto del voucher
       ↓
5. Preview de la foto
       ↓
6. "Confirmar y Subir"
       ↓
7. Sistema detecta: image/jpeg
       ↓
8. Sube a Cloudinary (optimizada)
       ↓
9. Crea Payment con URL
       ↓
10. ✅ "Comprobante recibido, en revisión"
```

---

## ✅ RESUMEN

| Aspecto | Implementación |
|---------|----------------|
| **Formatos imágenes** | JPG, PNG, WEBP ✅ |
| **Formato PDF** | PDF ✅ |
| **Detección** | Automática ✅ |
| **Tamaño imagen** | Max 5MB ✅ |
| **Tamaño PDF** | Max 10MB ✅ |
| **Optimización** | Automática (imágenes) ✅ |
| **Validación** | Servidor y cliente ✅ |
| **Uso móvil** | Optimizado ✅ |

---

## 🎯 ARCHIVOS MODIFICADOS

| Archivo | Cambio |
|---------|--------|
| `api/payments.py` | ✅ Acepta imagen Y PDF con detección automática |

---

## 🚀 ESTADO FINAL

```
╔═══════════════════════════════════════════╗
║  ✅ COMPROBANTES: IMAGEN O PDF           ║
╚═══════════════════════════════════════════╝

✅ JPG/PNG/WEBP (foto celular)
✅ PDF (comprobante digital)
✅ Detección automática
✅ Validación por tipo
✅ Optimización de imágenes
✅ Tamaños diferenciados

📱 Optimizado para móviles
🚀 Listo para usar
```

---

**Fecha:** 18 de Diciembre de 2024  
**Feature:** Upload de Comprobantes (Imagen o PDF)  
**Sistema:** KyC Payment System API
