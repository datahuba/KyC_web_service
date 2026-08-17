"""
Servicio de Certificados
========================

Lógica de negocio para emisión de Certificados de Notas y No Deudor
desde el portal del estudiante.

F-CERTIFICADOS (2026-07-29): ver spec en
.agents/specs/CERTIFICADOS/{requirements,design,tasks}.md

Patrones respetados del proyecto:
- Pydantic v2, Beanie ODM, datetime UTC.
- `datetime.now(timezone.utc)` (nunca `utcnow()`).
- Auditoría inmutable: cada Certificate emitido es un snapshot inmutable.
- Cloudinary para PDFs (folder `kyc/certificates/`).
- Errores HTTP claros (422 con detalle accionable, 409 si ya existe, 404, 403).
"""

import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument

from models.certificate import Certificate, ModuloCertificado
from models.certificate_counter import CertificateCounter
from models.course import Course
from models.enrollment import Enrollment
from models.enums import TipoCertificado
from models.student import Student

logger = logging.getLogger(__name__)


# ========================================================================
# CONSTANTES INSTITUCIONALES (UAGRM / Postgrado Contaduría)
# ========================================================================

UAGRM_NOMBRE = "UNIDAD DE POSTGRADO"
# CORREGIDO (Kevin 2026-08-17): el nombre que estaba, "FACULTAD DE AUDITORIA
# FINANCIERA O CONTADURIA PUBLICA", no es el de la facultad. El correcto es el
# que figura en la hoja membretada y en el cargo del director.
UAGRM_FACULTAD = (
    "FACULTAD DE CIENCIAS CONTABLES, AUDITORÍA, "
    "SISTEMAS DE CONTROL DE GESTIÓN Y FINANZAS"
)
UAGRM_UNIVERSIDAD = 'UNIVERSIDAD AUTÓNOMA "GABRIEL RENÉ MORENO"'
UAGRM_DIRECCION = "Av. Centenario entre primer y segundo anillo"
UAGRM_EMAIL = "postgradocontaduria@uagrm.edu.bo"
UAGRM_TELEFONO = "Telf. Fax: 337-0569"
UAGRM_CIUDAD = "Santa Cruz"

# ========================================================================
# Firmantes de los certificados
# ========================================================================
# Datos confirmados por Kevin el 2026-08-17 tras revisar el certificado
# N° 007/2026 ya emitido. Los valores anteriores tenian DOS errores en un
# documento oficial que la unidad entrega firmado:
#
#   1. El nombre decia "Claudio" (masculino) en vez de "Claudia", en una
#      firma cuyo cargo dice "COORDINADORA".
#   2. La segunda firma era otra persona: figuraba "M.Sc. Ortega Blanca
#      Muñoz / DIRECTORA", cuando quien dirige Postgrado es el Ph.D. Fausto
#      Mendoza Iriarte.
#
# Estos datos los usan los DOS tipos de certificado (Notas y No Deudor).
FIRMANTE_COORD_NOMBRE = "Lic. Claudia R. Cuéllar Paz"
# El cargo ya no repite el nombre de la facultad: la hoja membretada lo trae
# impreso arriba y el cuerpo del certificado lo dice una vez. Repetirlo en el
# pie de firma era la cuarta aparición en la misma carilla.
FIRMANTE_COORD_CARGO = (
    "COORDINADORA ADMINISTRATIVA Y FINANCIERA\n"
    "UNIDAD DE POSTGRADO"
)
FIRMANTE_DIRECTORA_NOMBRE = "Ph.D. Fausto Mendoza Iriarte"
FIRMANTE_DIRECTORA_CARGO = (
    "DIRECTOR DE POSTGRADO\n"
    "FACULTAD DE CIENCIAS CONTABLES, AUDITORÍA,\n"
    "SISTEMAS DE CONTROL DE GESTIÓN Y FINANZAS\n"
    "U.A.G.R.M."
)

# Roles staff (los únicos que pueden ver/descargar certificados de cualquier estudiante)
# BUG FIX (2026-07-30): los valores del enum UserRole están en MINÚSCULAS
# ("admin", "cpd", etc). El set anterior estaba en MAYÚSCULAS, lo que
# provocaba que NUNCA matcheara y los staff no pudieran ver certs de
# otros estudiantes (siempre caía al 403).
STAFF_ROLES = {"superadmin", "admin", "cpd", "cobranza", "mae"}


# ========================================================================
# HELPERS: conversión y formato
# ========================================================================

_UNIDADES = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
             "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis",
             "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidós",
             "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete",
             "veintiocho", "veintinueve"]
_DECENAS = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_CENTENAS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos",
             "seiscientos", "setecientos", "ochocientos", "novecientos"]


def _numero_a_literal_es(n: int) -> str:
    """
    Convierte un número 0-100 a su literal en español.
    Ej: 93 -> "Noventa y tres", 100 -> "Cien", 0 -> "Cero".

    FIX (2026-07-29): bug detectado en test funcional standalone.
    - `.capitalize()` solo capitaliza la primera letra de toda la cadena.
      Para "noventa y tres" lo dejaba como "Noventa y tres" ✓
    - `.title()` capitaliza CADA palabra, lo que rompe la "y" (español formal
      la deja en minúscula: "Noventa Y Tres" ✗).
    - Solución: construir la cadena en minúsculas y luego capitalizar SOLO
      el primer carácter.
    """
    if n < 0 or n > 100:
        raise ValueError(f"_numero_a_literal_es solo soporta 0-100, recibido {n}")
    if n == 0:
        return "Cero"
    if n == 100:
        return "Cien"
    if n < 30:
        texto = _UNIDADES[n]
    elif n < 100:
        decena = n // 10
        unidad = n % 10
        if unidad == 0:
            texto = _DECENAS[decena]
        else:
            texto = f"{_DECENAS[decena]} y {_UNIDADES[unidad]}"
    else:
        texto = str(n)
    # Capitalizar solo la primera letra (en español formal, "y" va minúscula)
    return texto[0].upper() + texto[1:] if texto else texto


def _format_fecha_dd_mm_yyyy(dt: Optional[datetime]) -> str:
    """Formatea datetime a 'dd/mm/yyyy' en UTC (los certificados se emiten en UTC)."""
    if dt is None:
        return "—"
    return dt.strftime("%d/%m/%Y")


def _format_ci_full(ci: Optional[str], extension: Optional[str], complemento: Optional[str]) -> str:
    """Formatea el CI: '10781482 BEN' o '1234567-1D SC'. Sin extensión -> solo el número."""
    if not ci:
        return "—"
    base = str(ci).strip()
    if complemento:
        base = f"{base}-{complemento.strip().upper()}"
    if extension:
        return f"{base} {extension.strip().upper()}"
    return base


def _format_fecha_larga_es(dt: datetime) -> str:
    """Formatea datetime a '20 de enero de 2026'."""
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    return f"{dt.day} de {meses[dt.month - 1]} de {dt.year}"


def _format_rango_modulo(fecha_inicio: Optional[datetime], fecha_fin: Optional[datetime]) -> str:
    """Formatea un rango 'dd/mm/yyyy al dd/mm/yyyy' (o solo una fecha si fin es None)."""
    ini = _format_fecha_dd_mm_yyyy(fecha_inicio)
    fin = _format_fecha_dd_mm_yyyy(fecha_fin)
    if ini == fin or fin == "—":
        return ini
    return f"{ini} al {fin}"


def _slug_nombre(nombre: str) -> str:
    """Convierte 'Sanguino Ribera Erlinda Kaori' a 'SANGUINO_RIBERA_ERLINDA_KAORI'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", nombre)
    # Quitar diacríticos (combining characters)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.upper()
    # Reemplazar todo lo que no sea A-Z o 0-9 por _
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = s.strip("_")
    return s[:60]  # Limitar longitud


def _format_folio(numero: int, anio: int) -> str:
    return f"N° {numero:03d}/{anio}"


# F-CERT-APROBACION (2026-07-30): helper para evitar duplicados al aprobar
# solicitudes de certificado. Busca un Certificate existente para
# (enrollment_id, tipo, hasta_modulo_n). Usado por cert_request_service.aprobar_solicitud
# y por api/certificates._buscar_cert_duplicado.
async def _buscar_cert_duplicado(
    enrollment_id: str, tipo: str, hasta_modulo_n: Optional[int] = None
) -> Optional[Certificate]:
    from beanie import PydanticObjectId
    try:
        eid = PydanticObjectId(enrollment_id)
    except Exception:
        return None
    query = Certificate.find(
        Certificate.enrollment_id == eid,
        Certificate.tipo == tipo,
    )
    if tipo == "no_deudor" and hasta_modulo_n is not None:
        query = query.find(Certificate.hasta_modulo_n == hasta_modulo_n)
    return await query.first_or_none()
    """Formatea el folio: 42 -> 'N° 042/2026'."""
    return f"N° {numero:03d}/{anio}"


# ========================================================================
# CORRELATIVO ATÓMICO
# ========================================================================

async def next_correlativo(anio: int) -> int:
    """
    Obtiene el siguiente número correlativo para el año dado.
    Operación atómica: usa find_one_and_update con $inc y upsert=True.
    MongoDB garantiza que dos requests simultáneos reciban números distintos.

    F-CERTIFICADOS-FIX (2026-07-29): bug detectado en producción.
    Beanie no expone `find_one_and_update` como método directo de la clase
    del modelo (es `find().update()` para bulk, o hay que acceder a la
    collection de motor). Usamos `get_motor_collection()` para hacer
    la operación atómica real.
    """
    collection = CertificateCounter.get_motor_collection()
    doc = await collection.find_one_and_update(
        {"anio": anio},
        {"$inc": {"last_number": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        # Edge case: el upsert con Beanie + Motor no devuelve el doc creado
        # en algunas versiones. Hacemos un find normal para recuperarlo.
        doc = await collection.find_one({"anio": anio})
    return doc["last_number"]


# ========================================================================
# VALIDACIONES DE REQUISITOS (F-CERTIFICADOS §5.2 y §5.3)
# ========================================================================

async def validar_requisitos_notas(enrollment: Enrollment) -> None:
    """
    Valida que el estudiante puede pedir Certificado de Notas.

    F-CERT-SIEMPRE (2026-07-30): según reunión con Sandra Zabala + Chicho,
    el Certificado de Notas debe poder sacarse SIEMPRE que la inscripción
    tenga al menos un módulo asociado. No se exige:
      - que todos los módulos estén finalizados (puede estar "Cursando")
      - que la inscripción esté completamente pagada

    El certificado queda como snapshot inmutable; si después suben notas
    adicionales, el estudiante puede pedir un NUEVO certificado (los
    anteriores quedan como histórico).

    Requisitos:
      1. La inscripción debe tener al menos un módulo asociado.

    Lanza HTTPException 422 con detalle si falla.
    """
    if not enrollment.modulos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Esta inscripción no tiene módulos asociados. No se puede emitir Certificado de Notas.",
        )


async def validar_requisitos_no_deudor(
    enrollment: Enrollment, hasta_modulo_n: int
) -> None:
    """
    Valida que el estudiante puede pedir Certificado de No Deudor hasta el módulo N.

    F-CERT-SIEMPRE (2026-07-30): según reunión con Sandra Zabala + Chicho,
    el Certificado de No Deudor "hasta módulo N" debe poder emitirse SIEMPRE
    que N esté dentro del rango válido. No se exige que los módulos previos
    estén pagados. La "deuda" se reporta en el cuerpo del certificado; el
    estudiante puede emitir varios a medida que avanza y los antiguos quedan
    como snapshot histórico.

    Requisitos:
      1. 1 <= hasta_modulo_n <= len(enrollment.modulos).

    Lanza HTTPException 422 con detalle si falla.
    """
    total = len(enrollment.modulos)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Esta inscripción no tiene módulos asociados. No se puede emitir Certificado de No Deudor.",
        )
    if hasta_modulo_n < 1 or hasta_modulo_n > total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"El alcance 'hasta_módulo_n' debe estar entre 1 y {total} "
                f"(total de módulos de tu programa). Recibido: {hasta_modulo_n}."
            ),
        )


# ========================================================================
# PDF: helpers compartidos
# ========================================================================

def _make_pdf_styles():
    """Crea los ParagraphStyles usados en ambos PDFs."""
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib import colors

    base = getSampleStyleSheet()
    styles = {
        "uagrm_header_top": ParagraphStyle(
            "uagrm_header_top", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11, alignment=TA_CENTER,
            textColor=colors.HexColor("#8a1f2f"), spaceAfter=2,
        ),
        "uagrm_header_sub": ParagraphStyle(
            "uagrm_header_sub", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9, alignment=TA_CENTER,
            textColor=colors.HexColor("#023273"), spaceAfter=1,
        ),
        "folio": ParagraphStyle(
            "folio", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11, alignment=TA_RIGHT,
            textColor=colors.HexColor("#8a1f2f"),
        ),
        "titulo_doc": ParagraphStyle(
            "titulo_doc", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=18, alignment=TA_CENTER,
            textColor=colors.HexColor("#8a1f2f"), spaceBefore=18, spaceAfter=18,
            leading=22,
        ),
        "cuerpo": ParagraphStyle(
            "cuerpo", parent=base["Normal"],
            fontName="Helvetica", fontSize=11, alignment=TA_JUSTIFY,
            leading=15, spaceAfter=10,
        ),
        "cuerpo_centrado": ParagraphStyle(
            "cuerpo_centrado", parent=base["Normal"],
            fontName="Helvetica", fontSize=11, alignment=TA_CENTER,
            leading=15, spaceAfter=10,
        ),
        "caja_programa": ParagraphStyle(
            "caja_programa", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=12, alignment=TA_CENTER,
            textColor=colors.HexColor("#023273"), leading=15,
        ),
        "certifica_label": ParagraphStyle(
            "certifica_label", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11, alignment=TA_LEFT,
            textColor=colors.black, spaceAfter=6,
        ),
        "firma_nombre": ParagraphStyle(
            "firma_nombre", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=10, alignment=TA_CENTER,
            textColor=colors.black,
        ),
        "firma_cargo": ParagraphStyle(
            "firma_cargo", parent=base["Normal"],
            fontName="Helvetica", fontSize=8, alignment=TA_CENTER,
            textColor=colors.HexColor("#444444"), leading=11,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"],
            fontName="Helvetica", fontSize=8, alignment=TA_CENTER,
            textColor=colors.HexColor("#666666"), leading=10,
        ),
        "no_deudor_enfasis": ParagraphStyle(
            "no_deudor_enfasis", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11, alignment=TA_JUSTIFY,
            textColor=colors.HexColor("#8a1f2f"), leading=15, spaceAfter=10,
        ),
    }
    return styles


def _header_table(folio: str, styles: dict, ancho_total: float = 200.0):
    """
    Tabla de encabezado: titulos UAGRM centrados + folio a la derecha.

    `ancho_total` se agrego el 2026-08-17 al corregir el nombre de la
    facultad: el nuevo ("FACULTAD DE CIENCIAS CONTABLES, AUDITORÍA, SISTEMAS
    DE CONTROL DE GESTIÓN Y FINANZAS") es mucho mas largo que el anterior y
    con las 150pt fijas que tenia la columna se partia en cuatro renglones,
    el folio salia cortado ("N° 010/" y "2026" en lineas distintas) y el
    certificado de Notas se iba a DOS paginas. La tabla ahora usa el ancho
    util real del marco.
    """
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors

    p_top = Paragraph(UAGRM_NOMBRE, styles["uagrm_header_top"])
    p_fac = Paragraph(UAGRM_FACULTAD, styles["uagrm_header_sub"])
    p_uni = Paragraph(UAGRM_UNIVERSIDAD, styles["uagrm_header_sub"])

    titulos = [p_top, p_fac, p_uni]
    folio_p = Paragraph(folio, styles["folio"])

    # El folio necesita ancho fijo para no cortarse; el resto va a los titulos.
    ancho_folio = 70.0
    t = Table(
        [[titulos, folio_p]],
        colWidths=[max(ancho_total - ancho_folio, 130.0), ancho_folio],
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _linea_horizontal(ancho: float = 200.0):
    """
    Línea horizontal separadora (decorativa, color institucional).

    Toma el ancho para acompañar al encabezado: con las 200pt fijas quedaba
    una rayita corta debajo de un bloque que ocupa todo el marco.
    """
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    t = Table([[""]], colWidths=[ancho], rowHeights=[1])
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#023273")),
    ]))
    return t


def _seccion_firmas(styles: dict, ancho_columna: float = 100.0):
    """
    Tabla con las dos firmas (Coord. Administrativa + Directora).

    `ancho_columna` existe porque la hoja membretada es bastante más ancha
    que el marco de los PDF originales: con las 100pt de siempre, los cargos
    se partían en una columna finita de ocho renglones y quedaba ilegible.
    Los renders viejos siguen usando el default para no cambiarles el
    aspecto.
    """
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors

    # Firmas como placeholders textuales (las imágenes se agregan en follow-up)
    p_coord_nombre = Paragraph(FIRMANTE_COORD_NOMBRE, styles["firma_nombre"])
    p_coord_cargo = Paragraph(
        FIRMANTE_COORD_CARGO.replace("\n", "<br/>"),
        styles["firma_cargo"],
    )
    p_directora_nombre = Paragraph(FIRMANTE_DIRECTORA_NOMBRE, styles["firma_nombre"])
    p_directora_cargo = Paragraph(
        FIRMANTE_DIRECTORA_CARGO.replace("\n", "<br/>"),
        styles["firma_cargo"],
    )

    # Celda izquierda: Coord. Administrativa
    celda_izq = [p_coord_nombre, p_coord_cargo]
    # Celda derecha: Directora
    celda_der = [p_directora_nombre, p_directora_cargo]

    t = Table(
        [[celda_izq, celda_der]],
        colWidths=[ancho_columna, ancho_columna],
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _footer(styles: dict):
    """Pie de página: dirección, email, teléfono."""
    from reportlab.platypus import Paragraph
    p = Paragraph(
        f"{UAGRM_DIRECCION} | E-mail: {UAGRM_EMAIL} | {UAGRM_TELEFONO}",
        styles["footer"],
    )
    return p


# ========================================================================
# F-CERT-NO-DEUDOR-COBRO (2026-08-17): render sobre hoja membretada
# ========================================================================
# Kevin: "el modelo final que le llega al estudiante debe ser con la hoja
# membretada y el texto que ya tienes registrado en el sistema".
#
# Los membretes que pasó (assets/membretes/) son PDF SOLO GRÁFICOS: tienen
# 0 caracteres extraíbles. O sea que no se pueden "rellenar" como si fueran
# una plantilla con campos — hay que generar el texto aparte y superponerlo
# sobre la hoja. Eso es lo que hace `_componer_sobre_membrete`.

MEMBRETES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "membretes"
)

# Zona segura de cada formato, MEDIDA sobre el PDF real (no estimada): se
# renderizó cada hoja y se buscó hasta dónde llega la banda verde de arriba y
# desde dónde arranca la de abajo. A eso se le sumó un colchón para que el
# texto no quede pegado al gráfico.
#
#   CARTA  (612x792 pt): banda superior hasta 35.3mm, inferior desde 41.6mm
#   OFICIO (612x1008 pt): banda superior hasta 36.7mm, inferior desde 64.9mm
#
# El pie del OFICIO es mucho más alto que el de CARTA, así que NO sirve usar
# los mismos márgenes para los dos: el texto se metería debajo del gráfico.
MEMBRETE_LAYOUT = {
    "CARTA": {"ancho_pt": 612.0, "alto_pt": 792.0, "top_mm": 42.0, "bottom_mm": 48.0},
    "OFICIO": {"ancho_pt": 612.0, "alto_pt": 1008.0, "top_mm": 44.0, "bottom_mm": 72.0},
}
MEMBRETE_MARGEN_LATERAL_MM = 25.0

# Formato por defecto. CARTA es el tamaño de hoja habitual de la oficina;
# OFICIO queda disponible para certificados con mucho texto.
MEMBRETE_FORMATO_DEFAULT = "CARTA"


def _ruta_membrete(formato: str) -> str:
    """Ruta al PDF del membrete. Lanza ValueError si el formato no existe."""
    formato = (formato or MEMBRETE_FORMATO_DEFAULT).upper()
    if formato not in MEMBRETE_LAYOUT:
        raise ValueError(
            f"Formato de membrete desconocido: {formato}. "
            f"Válidos: {', '.join(sorted(MEMBRETE_LAYOUT))}."
        )
    return os.path.join(MEMBRETES_DIR, f"{formato}.pdf")


def hay_membrete(formato: str = MEMBRETE_FORMATO_DEFAULT) -> bool:
    """
    True si el archivo del membrete está presente y es legible.

    Se chequea antes de emitir para poder caer al formato sin membrete en
    vez de reventar: un despliegue al que le falte `assets/` no debería
    dejar a la unidad sin poder emitir certificados.
    """
    try:
        return os.path.isfile(_ruta_membrete(formato))
    except ValueError:
        return False


def _componer_sobre_membrete(
    contenido_pdf: bytes, formato: str = MEMBRETE_FORMATO_DEFAULT
) -> bytes:
    """
    Superpone el PDF de contenido sobre la hoja membretada.

    El membrete queda ABAJO y el texto ARRIBA, así el texto nunca queda
    tapado por el escudo de agua del fondo.

    Si el contenido ocupa más de una página, cada página recibe su propia
    copia del membrete: una hoja 2 sin membrete se vería como si fuera de
    otro documento.
    """
    from pypdf import PdfReader, PdfWriter

    ruta = _ruta_membrete(formato)
    contenido = PdfReader(io.BytesIO(contenido_pdf))
    writer = PdfWriter()

    for pagina_contenido in contenido.pages:
        # Se relee el membrete en cada vuelta a propósito: pypdf muta la
        # página al hacer merge, así que reusar el mismo objeto acumularía
        # el texto de las páginas anteriores.
        base = PdfReader(ruta).pages[0]
        base.merge_page(pagina_contenido)
        writer.add_page(base)

    salida = io.BytesIO()
    writer.write(salida)
    return salida.getvalue()


def _nombre_con_tratamiento(nombre: str, tratamiento: Optional[str]) -> str:
    """
    Antepone el tratamiento profesional al nombre, si corresponde.

    Kevin: "a los profesionales debe decir lic. o ing. o lo que sea respecto
    a su carrera y su nombre, tipo lic. kevin soto o ing. kevin soto". Los de
    diplomado continuo no llevan tratamiento, y por eso `tratamiento` puede
    venir en None y el nombre sale tal cual.
    """
    nombre = (nombre or "").strip().upper()
    tratamiento = (tratamiento or "").strip()
    if not tratamiento:
        return nombre
    return f"{tratamiento.upper()} {nombre}"


# ========================================================================
# PDF: render del Certificado de Notas
# ========================================================================

def render_pdf_notas(
    *,
    student: Student,
    course: Course,
    enrollment: Enrollment,
    folio: str,
    emitido_en: datetime,
) -> bytes:
    """
    Genera el PDF del Certificado de Notas (formato UAGRM).
    Retorna bytes listos para subir a Cloudinary o devolver al cliente.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors

    styles = _make_pdf_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Certificado de Notas - {student.nombre or ''}",
    )

    elements = []
    # Encabezado
    ancho_util_a4 = 170 * mm
    elements.append(_header_table(folio, styles, ancho_total=ancho_util_a4))
    elements.append(_linea_horizontal(ancho_util_a4))
    elements.append(Spacer(1, 6 * mm))

    # Título
    elements.append(Paragraph("CERTIFICADO DE NOTAS", styles["titulo_doc"]))

    # Encabezado institucional
    elements.append(Paragraph(
        f"LA UNIDAD DE POSTGRADO DE LA {UAGRM_FACULTAD} "
        f"DE LA {UAGRM_UNIVERSIDAD}",
        styles["cuerpo"],
    ))

    # "CERTIFICA:"
    elements.append(Paragraph("CERTIFICA:", styles["certifica_label"]))

    # Datos del estudiante
    ci_full = _format_ci_full(student.carnet, student.extension, student.complemento_carnet)
    elements.append(Paragraph(
        f"QUE EL (LA) <b>{(student.nombre or '').upper()}</b> "
        f"Con registro universitario No.: <b>{student.registro}</b> "
        f"y carnet de identidad No.: <b>{ci_full}</b>",
        styles["cuerpo"],
    ))

    # Texto del programa
    elements.append(Paragraph(
        "HA FINALIZADO CON EL PROGRAMA ACADEMICO DEL DIPLOMADO EN:",
        styles["cuerpo"],
    ))

    # Caja con nombre del programa
    nombre_prog = (course.nombre_programa or "").upper()
    if course.codigo:
        nombre_prog = f"{nombre_prog} ({course.codigo})"
    elements.append(Paragraph(nombre_prog, styles["caja_programa"]))
    elements.append(Spacer(1, 4 * mm))

    # Subtítulo tabla
    elements.append(Paragraph(
        "HABIENDO CURSADO LOS SIGUIENTES MODULOS CON LAS SIGUIENTES CALIFICACIONES:",
        styles["cuerpo"],
    ))
    elements.append(Spacer(1, 2 * mm))

    # Tabla de módulos
    header = [
        Paragraph("<b>N°</b>", styles["cuerpo_centrado"]),
        Paragraph("<b>MÓDULO</b>", styles["cuerpo_centrado"]),
        Paragraph("<b>NOTA</b>", styles["cuerpo_centrado"]),
        Paragraph("<b>LITERAL</b>", styles["cuerpo_centrado"]),
        Paragraph("<b>FECHA</b>", styles["cuerpo_centrado"]),
    ]
    rows = [header]
    for i, m in enumerate(enrollment.modulos, start=1):
        nota = m.nota
        literal = _numero_a_literal_es(int(nota)) if nota is not None else "—"
        # Combinar fechas del ModuloEstado (snapshot) y de Course.modulos
        # (configuración original). Prioridad: snapshot > config.
        fecha_ini = getattr(m, "fecha_inicio", None) or None
        fecha_fin = getattr(m, "fecha_fin", None) or None
        # Si no hay fechas en el snapshot, intentar el Course.modulos
        if (fecha_ini is None or fecha_fin is None) and course.modulos:
            idx = i - 1
            if 0 <= idx < len(course.modulos):
                cm = course.modulos[idx]
                fecha_ini = fecha_ini or getattr(cm, "fecha_inicio", None)
                fecha_fin = fecha_fin or getattr(cm, "fecha_fin", None)
        fecha_str = _format_rango_modulo(fecha_ini, fecha_fin)

        rows.append([
            Paragraph(str(i), styles["cuerpo_centrado"]),
            Paragraph((m.nombre or "—").upper(), styles["cuerpo"]),
            Paragraph(str(int(nota)) if nota is not None else "—", styles["cuerpo_centrado"]),
            Paragraph(literal, styles["cuerpo_centrado"]),
            Paragraph(fecha_str, styles["cuerpo_centrado"]),
        ])

    tabla = Table(
        rows,
        colWidths=[12 * mm, 75 * mm, 18 * mm, 35 * mm, 38 * mm],
        repeatRows=1,
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8a1f2f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(tabla)
    elements.append(Spacer(1, 6 * mm))

    # Cierre
    elements.append(Paragraph(
        f"Al haber cumplido con los requisitos exigidos en el reglamento de {course.nombre_programa}. "
        f"Se extiende el presente Certificado de notas, las mismas que están respaldadas por nuestros archivos.",
        styles["cuerpo"],
    ))

    elements.append(Paragraph(
        f"{UAGRM_CIUDAD}, {_format_fecha_larga_es(emitido_en)}.",
        styles["cuerpo"],
    ))

    elements.append(Spacer(1, 8 * mm))
    elements.append(_seccion_firmas(styles))
    elements.append(Spacer(1, 8 * mm))
    elements.append(_footer(styles))

    doc.build(elements)
    return buf.getvalue()


# ========================================================================
# PDF: render del Certificado de No Deudor
# ========================================================================

def render_pdf_no_deudor(
    *,
    student: Student,
    course: Course,
    enrollment: Enrollment,
    hasta_modulo_n: int,
    folio: str,
    emitido_en: datetime,
) -> bytes:
    """
    Genera el PDF del Certificado de No Deudor (formato UAGRM).
    Si hasta_modulo_n == len(modulos), dice 'del mencionado programa'.
    Si hasta_modulo_n < len(modulos), dice 'hasta el Módulo N del mencionado programa'.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors

    styles = _make_pdf_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Certificado de No Deudor - {student.nombre or ''}",
    )

    elements = []
    ancho_util_a4 = 170 * mm
    elements.append(_header_table(folio, styles, ancho_total=ancho_util_a4))
    elements.append(_linea_horizontal(ancho_util_a4))
    elements.append(Spacer(1, 6 * mm))

    elements.append(Paragraph("CERTIFICADO DE NO DEUDOR", styles["titulo_doc"]))

    elements.append(Paragraph(
        f"La Unidad de Postgrado de la {UAGRM_FACULTAD} de la {UAGRM_UNIVERSIDAD}.",
        styles["cuerpo"],
    ))

    elements.append(Paragraph("CERTIFICA:", styles["certifica_label"]))

    ci_full = _format_ci_full(student.carnet, student.extension, student.complemento_carnet)
    elements.append(Paragraph(
        f"Que, revisando los registros de pagos existentes en la Unidad de Postgrado de la "
        f"{UAGRM_FACULTAD}, se puede evidenciar que el (la):",
        styles["cuerpo"],
    ))
    elements.append(Paragraph(
        f"<b>{(student.nombre or '').upper()}</b><br/>"
        f"CI. {ci_full}.",
        styles["cuerpo_centrado"],
    ))

    # Versión y edición si están disponibles
    partes_nombre = [(course.nombre_programa or "").upper()]
    if course.codigo:
        partes_nombre.append(f"CÓDIGO {course.codigo}")
    prog_label = " ".join(partes_nombre)
    elements.append(Paragraph(
        f"Del Programa Académico DIPLOMADO en:",
        styles["cuerpo"],
    ))
    elements.append(Paragraph(prog_label, styles["caja_programa"]))
    elements.append(Spacer(1, 4 * mm))

    # Párrafo de "NO TIENE DEUDA" con énfasis y mención del módulo N
    total = len(enrollment.modulos)
    if hasta_modulo_n == total:
        texto_no_deuda = (
            '<b>"NO TIENE DEUDA ECONOMICA PENDIENTE"</b>, habiendo cancelado el total del costo '
            'del mencionado programa de acuerdo al compromiso de pago firmado con la Unidad de Postgrado.'
        )
    else:
        # Mismo BUG-FIX que en la versión membretada (2026-08-17): sin fechas
        # cargadas el rango sale "—" y quedaba un "(—)" suelto en el
        # documento oficial.
        rango = _format_rango_modulo(
            getattr(enrollment.modulos[hasta_modulo_n - 1], "fecha_inicio", None),
            getattr(enrollment.modulos[hasta_modulo_n - 1], "fecha_fin", None),
        )
        detalle_rango = f" ({rango})" if rango and rango != "—" else ""
        texto_no_deuda = (
            f'<b>"NO TIENE DEUDA ECONOMICA PENDIENTE"</b> hasta el <b>Módulo {hasta_modulo_n}</b>'
            f'{detalle_rango} del mencionado programa, de acuerdo al compromiso de pago '
            f'firmado con la Unidad de Postgrado.'
        )
    elements.append(Paragraph(texto_no_deuda, styles["no_deudor_enfasis"]))

    elements.append(Paragraph(
        f"{UAGRM_CIUDAD}, {_format_fecha_larga_es(emitido_en)}.",
        styles["cuerpo"],
    ))

    elements.append(Spacer(1, 8 * mm))
    elements.append(_seccion_firmas(styles))
    elements.append(Spacer(1, 8 * mm))
    elements.append(_footer(styles))

    doc.build(elements)
    return buf.getvalue()


def render_pdf_no_deudor_membretado(
    *,
    student: Student,
    course: Course,
    enrollment: Enrollment,
    hasta_modulo_n: int,
    folio: str,
    emitido_en: datetime,
    tratamiento: Optional[str] = None,
    formato: str = MEMBRETE_FORMATO_DEFAULT,
) -> bytes:
    """
    Certificado de No Deudor sobre la hoja membretada de la Unidad.

    F-CERT-NO-DEUDOR-COBRO (Kevin 2026-08-17): "el modelo final que le llega
    al estudiante debe ser con la hoja membretada".

    Diferencias con `render_pdf_no_deudor` (la versión sin membrete):
      - No se dibuja el encabezado institucional ni el pie de dirección: ya
        vienen impresos en la hoja. Repetirlos se vería como un documento
        mal armado.
      - Los márgenes salen de `MEMBRETE_LAYOUT`, medidos sobre el archivo
        real, para que el texto no se meta bajo las bandas verdes.
      - El nombre puede llevar tratamiento profesional (Lic./Ing./...).

    El texto del cuerpo es el mismo que ya estaba en el sistema, que es lo
    que Kevin pidió conservar.
    """
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    layout = MEMBRETE_LAYOUT[(formato or MEMBRETE_FORMATO_DEFAULT).upper()]
    styles = _make_pdf_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=(layout["ancho_pt"], layout["alto_pt"]),
        leftMargin=MEMBRETE_MARGEN_LATERAL_MM * mm,
        rightMargin=MEMBRETE_MARGEN_LATERAL_MM * mm,
        topMargin=layout["top_mm"] * mm,
        bottomMargin=layout["bottom_mm"] * mm,
        title=f"Certificado de No Deudor - {student.nombre or ''}",
    )

    elements = []

    # Folio arriba a la derecha. Es lo único del encabezado viejo que se
    # conserva: el membrete no lo trae y sin folio el documento no es
    # rastreable.
    elements.append(Paragraph(folio, styles["folio"]))
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph("CERTIFICADO DE NO DEUDOR", styles["titulo_doc"]))

    # F-CERT-REDACCION (Kevin 2026-08-17): "que no repita lo mismo".
    #
    # La versión anterior nombraba a la facultad TRES veces en media carilla:
    # en la línea de presentación, otra vez dentro del "Que, revisando los
    # registros...", y una tercera en el pie de cada firma. Encima la hoja
    # membretada ya la trae impresa arriba, así que eran cuatro.
    #
    # Ahora se nombra UNA sola vez, en la presentación, y el cuerpo va
    # directo al grano con la redacción que dictó Kevin.
    elements.append(Paragraph(
        f"La Unidad de Postgrado de la {UAGRM_FACULTAD} de la {UAGRM_UNIVERSIDAD}.",
        styles["cuerpo"],
    ))

    elements.append(Paragraph("CERTIFICA:", styles["certifica_label"]))

    ci_full = _format_ci_full(student.carnet, student.extension, student.complemento_carnet)

    # Se conserva la ESTRUCTURA del formato original (nombre centrado en su
    # propia línea, programa destacado en su recuadro, y la frase de no deuda
    # resaltada): Kevin lo pidió explícitamente, "lo quiero así pero con el
    # texto cambiado". Lo que cambia es la redacción.
    #
    # De paso desaparece la segunda mención a la facultad, que antes venía en
    # el "Que, revisando los registros de pagos existentes en la Unidad de
    # Postgrado de la FACULTAD...".
    elements.append(Paragraph("Que el o la postgraduante:", styles["cuerpo"]))
    elements.append(Paragraph(
        f"<b>{_nombre_con_tratamiento(student.nombre or '', tratamiento)}</b><br/>"
        f"CI. {ci_full}.",
        styles["cuerpo_centrado"],
    ))

    # Se mantiene en mayúsculas como en el formato original. Solo se
    # normalizan los espacios de más, que vienen en los datos ("APLICADA A
    # LA  EDUCACIÓN,  LA INVESTIGACIÓN") y ensuciaban el renglón.
    nombre_programa = re.sub(r"\s+", " ", (course.nombre_programa or "").strip()).upper()
    partes_programa = [nombre_programa]
    if course.codigo:
        partes_programa.append(f"CÓDIGO {course.codigo}")
    elements.append(Paragraph("Del programa:", styles["cuerpo"]))
    elements.append(Paragraph(" ".join(partes_programa), styles["caja_programa"]))
    elements.append(Spacer(1, 4 * mm))

    # Alcance. La redacción que dictó Kevin afirma que no hay deuda "del
    # programa mencionado", sin más. Eso es correcto SOLO cuando el
    # certificado cubre el programa entero; si cubre hasta el módulo N de un
    # total mayor hay que decirlo, porque si no el documento afirmaría que el
    # estudiante no debe nada de un programa que todavía está pagando.
    total = len(enrollment.modulos)
    if hasta_modulo_n >= total:
        alcance = ""
    else:
        # Si el módulo no tiene fechas cargadas, `_format_rango_modulo`
        # devuelve "—" y antes salía "hasta el Módulo 1 (—)" — visto en el
        # certificado N° 007/2026, ya emitido. Sin rango se omite el
        # paréntesis entero.
        rango = _format_rango_modulo(
            getattr(enrollment.modulos[hasta_modulo_n - 1], "fecha_inicio", None),
            getattr(enrollment.modulos[hasta_modulo_n - 1], "fecha_fin", None),
        )
        detalle_rango = f" ({rango})" if rango and rango != "—" else ""
        alcance = f" hasta el <b>Módulo {hasta_modulo_n}</b>{detalle_rango}"

    elements.append(Paragraph(
        f"<b>NO TIENE DEUDA ECONÓMICA PENDIENTE</b>{alcance} del programa mencionado, "
        f"de acuerdo al compromiso de pago firmado con la Unidad de Postgrado.",
        styles["no_deudor_enfasis"],
    ))

    elements.append(Paragraph(
        f"{UAGRM_CIUDAD}, {_format_fecha_larga_es(emitido_en)}.",
        styles["cuerpo"],
    ))

    elements.append(Spacer(1, 10 * mm))
    # Las firmas ocupan el ancho útil completo de la hoja: con el ancho
    # chico heredado del PDF A4, los cargos se partían en dos columnas
    # finitas de ocho renglones.
    ancho_util = layout["ancho_pt"] - 2 * MEMBRETE_MARGEN_LATERAL_MM * mm
    elements.append(_seccion_firmas(styles, ancho_columna=ancho_util / 2))

    doc.build(elements)
    return _componer_sobre_membrete(buf.getvalue(), formato=formato)


# ========================================================================
# CLOUDINARY: subir PDF
# ========================================================================

async def _subir_pdf_a_cloudinary(pdf_bytes: bytes, public_id: str) -> str:
    """
    Sube el PDF a Cloudinary en el folder kyc/certificates/ como raw asset.
    Retorna la URL segura (https) del PDF.

    NOTA: No usamos el wrapper `upload_pdf` de core/cloudinary_utils.py porque
    ese helper espera un `fastapi.UploadFile` (con `.content_type` y `.file`),
    y aquí tenemos bytes puros del PDF generado por reportlab. Usamos la API
    de Cloudinary directamente, en un executor para no bloquear el event loop.
    """
    import asyncio
    import cloudinary.uploader

    def _do_upload():
        result = cloudinary.uploader.upload(
            io.BytesIO(pdf_bytes),
            folder="kyc/certificates",
            public_id=public_id,
            resource_type="raw",
            type="upload",
            access_mode="public",
            overwrite=True,
            format="pdf",
        )
        return result.get("secure_url") or result.get("url", "")

    loop = asyncio.get_event_loop()
    secure_url = await loop.run_in_executor(None, _do_upload)
    if secure_url and not secure_url.lower().endswith(".pdf"):
        secure_url = f"{secure_url}.pdf"
    return secure_url


# ========================================================================
# DESCARGA DE PDF DESDE CLOUDINARY
# ========================================================================

async def _descargar_pdf_desde_url(url: str) -> bytes:
    """
    Descarga los bytes del PDF desde una URL (Cloudinary u otra).

    BUG-FIX (2026-07-30): si la URL es de Cloudinary y falla con 401
    (asset privado legacy), regenera una signed URL con acceso temporal.
    Esto permite descargar PDFs emitidos antes del fix `access_mode='public'`
    sin tener que reemitir el certificado.
    """
    import httpx
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code == 401 and 'cloudinary' in url:
            # Intentar regenerar con signed URL
            signed_url = _cloudinary_signed_url_from_public_url(url)
            if signed_url and signed_url != url:
                resp = await client.get(signed_url)
        resp.raise_for_status()
        return resp.content


def _cloudinary_signed_url_from_public_url(public_url: str) -> str | None:
    """
    Dada una URL pública de Cloudinary (sin firma), regenera una signed URL
    con expiración de 1 hora. Útil para assets legacy subidos sin
    access_mode='public' o con access_type='authenticated'.
    """
    try:
        import cloudinary.utils
        # La URL típica es: https://res.cloudinary.com/<cloud>/<resource_type>/<type>/v123/folder/file.pdf
        # Extraer el public_id (sin extensión .pdf)
        # Primero quitamos el query string
        from urllib.parse import urlparse
        parsed = urlparse(public_url)
        path = parsed.path  # /<cloud>/raw/upload/v123/folder/file.pdf
        parts = path.split('/')
        # parts[0] = '', parts[1] = cloud_name, parts[2] = resource_type, parts[3] = type, parts[4] = version?, parts[5:] = public_id
        if len(parts) < 5:
            return None
        # Encontrar el public_id (todo después de la versión)
        version_idx = None
        for i, p in enumerate(parts):
            if p.startswith('v') and p[1:].isdigit():
                version_idx = i
                break
        if version_idx is None or version_idx == len(parts) - 1:
            return None
        public_id = '/'.join(parts[version_idx + 1:])
        # NO quitamos la extensión .pdf: para raw assets en Cloudinary,
        # el public_id se almacena CON la extensión original. Si la
        # quitamos, el signed URL apunta a un asset inexistente (404).
        # Determinar resource_type
        resource_type = parts[2] if len(parts) > 2 else 'raw'
        # Generar signed URL
        # cloudinary.utils.cloudinary_url retorna una tupla (url, options_dict).
        signed = cloudinary.utils.cloudinary_url(
            public_id,
            resource_type=resource_type,
            sign_url=True,
            secure=True,
            expires_at=int(__import__('time').time()) + 3600,
        )
        # La tupla tiene (url, options). Extraer el primer elemento.
        if isinstance(signed, tuple) and len(signed) > 0:
            return signed[0]
        return signed
    except Exception:
        return None


# ========================================================================
# RBAC
# ========================================================================

def verificar_acceso_certificado(cert: Certificate, current_user) -> None:
    """
    Verifica que el usuario puede acceder al certificado:
    - Estudiante: solo si es el dueño (cert.student_id == current_user.id).
    - Staff: cualquier cert (los roles en STAFF_ROLES o COORDINADOR).
    Lanza HTTPException 403 si no tiene acceso.

    LECCIÓN (2026-07-30): no usar `isinstance(current_user, User)` porque
    en los tests y en algunos callers el user es un Mock/spec. Usar
    `getattr(user, 'rol', None)` con fallback al valor del enum o string.
    """
    user_rol = getattr(current_user, "rol", None)
    if user_rol is not None:
        # Normalizar a string (puede ser Enum o str)
        rol_value = getattr(user_rol, "value", user_rol)
        if rol_value in STAFF_ROLES or rol_value == "COORDINADOR":
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a este certificado.",
        )
    # current_user es Student: debe ser el dueño del cert
    if getattr(current_user, "id", None) != cert.student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a este certificado.",
        )


# ========================================================================
# EMISIÓN: orquestación
# ========================================================================

async def _obtener_curso_estudiante_enrollment(
    enrollment_id: str, current_user
) -> Tuple[Student, Course, Enrollment]:
    """
    Helper: dado un enrollment_id (string), valida que pertenece al estudiante
    autenticado y devuelve (student, course, enrollment).
    """
    from models.user import User
    from bson.errors import InvalidId

    try:
        eid = ObjectId(enrollment_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="enrollment_id inválido.",
        )

    enrollment = await Enrollment.get(eid)
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inscripción no encontrada.",
        )

    # Verificar que el current_user sea el dueño de la inscripción
    # FIX 2026-07-29 19:27 (Kevin "permiso"): comparar con str() para evitar
    # problemas de tipo entre PydanticObjectId y ObjectId (que pueden dar
    # False aunque sean el mismo id).
    if isinstance(current_user, Student):
        if str(enrollment.estudiante_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta inscripción no te pertenece.",
            )
        student = current_user
    else:
        # Si es staff pidiendo en nombre de un estudiante, buscamos el student
        student = await Student.get(enrollment.estudiante_id)
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Estudiante asociado a la inscripción no encontrado.",
            )

    course = await Course.get(enrollment.curso_id)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curso asociado a la inscripción no encontrado.",
        )

    return student, course, enrollment


async def emitir_certificado_notas(
    enrollment_id: str, current_user
) -> Certificate:
    """
    Emite un Certificado de Notas. Valida requisitos, genera PDF, sube a
    Cloudinary y persiste el Certificate.
    """
    student, course, enrollment = await _obtener_curso_estudiante_enrollment(
        enrollment_id, current_user
    )

    await validar_requisitos_notas(enrollment)

    # Verificar duplicado: 1 certificado de NOTAS por enrollment
    existente = await Certificate.find_one(
        Certificate.enrollment_id == enrollment.id,
        Certificate.tipo == TipoCertificado.NOTAS,
    )
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ya se emitió el Certificado de Notas para esta inscripción. "
                f"Folio: {_format_folio(existente.numero, existente.anio)}."
            ),
        )

    # Generar correlativo
    anio = datetime.now(timezone.utc).year
    numero = await next_correlativo(anio)
    folio = _format_folio(numero, anio)

    emitido_en = datetime.now(timezone.utc)

    # Construir snapshot de módulos
    modulos_snapshot: List[ModuloCertificado] = []
    for m in enrollment.modulos:
        nota = m.nota
        literal = _numero_a_literal_es(int(nota)) if nota is not None else None
        modulos_snapshot.append(ModuloCertificado(
            nombre=m.nombre,
            nota=int(nota) if nota is not None else None,
            literal=literal,
            estado=m.estado_academico,
            fecha_inicio=getattr(m, "fecha_inicio", None),
            fecha_fin=getattr(m, "fecha_fin", None),
        ))

    # Generar PDF
    pdf_bytes = render_pdf_notas(
        student=student,
        course=course,
        enrollment=enrollment,
        folio=folio,
        emitido_en=emitido_en,
    )

    # Subir a Cloudinary
    slug = _slug_nombre(student.nombre or student.registro or "estudiante")
    public_id = f"cert_notas_{numero:03d}_{anio}_{slug}"
    pdf_filename = f"certificado_notas_N{numero:03d}_{anio}_{slug}.pdf"
    pdf_url = await _subir_pdf_a_cloudinary(pdf_bytes, public_id=public_id)

    # Generar código de verificación (12 chars hex)
    verificacion_code = uuid.uuid4().hex[:12]

    # Persistir Certificate
    cert = Certificate(
        tipo=TipoCertificado.NOTAS,
        numero=numero,
        anio=anio,
        student_id=student.id,
        course_id=course.id,
        enrollment_id=enrollment.id,
        modulos_snapshot=modulos_snapshot,
        hasta_modulo_n=None,
        programa_nombre=course.nombre_programa or "",
        programa_codigo=course.codigo or "",
        programa_version="",
        programa_edicion="",
        estudiante_nombre=(student.nombre or "").upper(),
        estudiante_registro=student.registro or "",
        estudiante_ci=student.carnet or "",
        estudiante_extension=student.extension,
        estudiante_complemento=student.complemento_carnet,
        emitido_en=emitido_en,
        emitido_por=str(getattr(current_user, "registro", "") or getattr(current_user, "username", "")),
        verificacion_code=verificacion_code,
        pdf_url=pdf_url,
        pdf_filename=pdf_filename,
    )
    await cert.insert()
    return cert


async def emitir_certificado_no_deudor(
    enrollment_id: str,
    hasta_modulo_n: int,
    current_user,
    tratamiento: Optional[str] = None,
    formato_membrete: str = MEMBRETE_FORMATO_DEFAULT,
) -> Certificate:
    """
    Emite un Certificado de No Deudor hasta el módulo N. Valida requisitos,
    genera PDF, sube a Cloudinary y persiste el Certificate.

    F-CERT-NO-DEUDOR-COBRO (2026-08-17): el PDF sale sobre la hoja membretada
    y con el tratamiento profesional adelante del nombre, si corresponde.
    Si el archivo del membrete no está disponible se emite igual con el
    formato anterior: dejar a la unidad sin poder emitir certificados por un
    asset faltante sería peor que emitirlos sin membrete.
    """
    student, course, enrollment = await _obtener_curso_estudiante_enrollment(
        enrollment_id, current_user
    )

    await validar_requisitos_no_deudor(enrollment, hasta_modulo_n)

    # Generar correlativo
    anio = datetime.now(timezone.utc).year
    numero = await next_correlativo(anio)
    folio = _format_folio(numero, anio)

    emitido_en = datetime.now(timezone.utc)

    # Snapshot: solo los módulos hasta N
    modulos_snapshot: List[ModuloCertificado] = []
    for m in enrollment.modulos[:hasta_modulo_n]:
        modulos_snapshot.append(ModuloCertificado(
            nombre=m.nombre,
            nota=None,
            literal=None,
            estado=m.estado,
            fecha_inicio=getattr(m, "fecha_inicio", None),
            fecha_fin=getattr(m, "fecha_fin", None),
        ))

    # Generar PDF (sobre membrete si el asset está disponible)
    usar_membrete = hay_membrete(formato_membrete)
    if usar_membrete:
        pdf_bytes = render_pdf_no_deudor_membretado(
            student=student,
            course=course,
            enrollment=enrollment,
            hasta_modulo_n=hasta_modulo_n,
            folio=folio,
            emitido_en=emitido_en,
            tratamiento=tratamiento,
            formato=formato_membrete,
        )
    else:
        logger.warning(
            "[CERT] Membrete '%s' no encontrado en %s. Se emite con el formato "
            "anterior, sin hoja membretada.", formato_membrete, MEMBRETES_DIR
        )
        pdf_bytes = render_pdf_no_deudor(
            student=student,
            course=course,
            enrollment=enrollment,
            hasta_modulo_n=hasta_modulo_n,
            folio=folio,
            emitido_en=emitido_en,
        )

    slug = _slug_nombre(student.nombre or student.registro or "estudiante")
    public_id = f"cert_nodeudor_{numero:03d}_{anio}_{slug}"
    pdf_filename = f"certificado_nodeudor_N{numero:03d}_{anio}_{slug}_M{hasta_modulo_n}.pdf"
    pdf_url = await _subir_pdf_a_cloudinary(pdf_bytes, public_id=public_id)

    verificacion_code = uuid.uuid4().hex[:12]

    cert = Certificate(
        tipo=TipoCertificado.NO_DEUDOR,
        numero=numero,
        anio=anio,
        student_id=student.id,
        course_id=course.id,
        enrollment_id=enrollment.id,
        modulos_snapshot=modulos_snapshot,
        hasta_modulo_n=hasta_modulo_n,
        programa_nombre=course.nombre_programa or "",
        programa_codigo=course.codigo or "",
        programa_version="",
        programa_edicion="",
        estudiante_nombre=(student.nombre or "").upper(),
        estudiante_registro=student.registro or "",
        estudiante_ci=student.carnet or "",
        estudiante_extension=student.extension,
        estudiante_complemento=student.complemento_carnet,
        emitido_en=emitido_en,
        emitido_por=str(getattr(current_user, "registro", "") or getattr(current_user, "username", "")),
        verificacion_code=verificacion_code,
        tratamiento=tratamiento,
        membrete=(formato_membrete.upper() if usar_membrete else None),
        pdf_url=pdf_url,
        pdf_filename=pdf_filename,
    )
    await cert.insert()
    return cert


# ========================================================================
# DESCARGAR PDF (re-descarga desde Cloudinary)
# ========================================================================

async def descargar_pdf_bytes(cert: Certificate) -> bytes:
    """
    Descarga los bytes del PDF del certificado desde Cloudinary.

    BUG-FIX (2026-07-30): la cuenta de Cloudinary 'dckj1wnra' tiene una
    restricción a nivel de account (delivery type) que hace que TODAS
    las URLs (públicas y firmadas) devuelvan 401. El SDK de Cloudinary
    no expone un método para descargar archivos raw via API autenticada
    (solo via URL). Por eso, cuando la descarga desde URL falla con 401
    o cualquier error, hacemos fallback a RE-RENDERIZAR el PDF en el
    servidor usando los datos del cert + el enrollment/course/student
    y streameamos los bytes al cliente. Esto es más lento pero NO
    depende del acceso por URL a Cloudinary.
    """
    try:
        return await _descargar_pdf_desde_url(cert.pdf_url)
    except Exception as url_error:
        # Fallback: re-renderizar el PDF con los datos del cert.
        # Esto evita el bloqueo cuando la cuenta de Cloudinary tiene
        # restricciones de delivery.
        from models.enrollment import Enrollment
        from models.student import Student
        from models.course import Course

        enrollment = await Enrollment.get(cert.enrollment_id)
        student = await Student.get(cert.student_id)
        course = await Course.get(cert.course_id)
        if not (enrollment and student and course):
            raise RuntimeError(
                f"No se pudo descargar el PDF de Cloudinary ({url_error}) "
                f"ni re-renderizarlo (faltan enrollment/student/course)."
            )

        folio = _format_folio(cert.numero, cert.anio)
        emitido_en = cert.emitido_en

        if cert.tipo == TipoCertificado.NOTAS:
            return render_pdf_notas(
                student=student,
                course=course,
                enrollment=enrollment,
                folio=folio,
                emitido_en=emitido_en,
            )
        elif cert.tipo == TipoCertificado.NO_DEUDOR:
            # Se respeta cómo se emitió: un certificado viejo (membrete=None)
            # se re-renderiza con el formato viejo. Si no, un documento de
            # julio volvería con el diseño de agosto y no coincidiría con la
            # copia que el estudiante ya tiene.
            if cert.membrete and hay_membrete(cert.membrete):
                return render_pdf_no_deudor_membretado(
                    student=student,
                    course=course,
                    enrollment=enrollment,
                    hasta_modulo_n=cert.hasta_modulo_n or 1,
                    folio=folio,
                    emitido_en=emitido_en,
                    tratamiento=cert.tratamiento,
                    formato=cert.membrete,
                )
            return render_pdf_no_deudor(
                student=student,
                course=course,
                enrollment=enrollment,
                hasta_modulo_n=cert.hasta_modulo_n or 1,
                folio=folio,
                emitido_en=emitido_en,
            )
        else:
            raise RuntimeError(
                f"Tipo de certificado desconocido: {cert.tipo}"
            )
