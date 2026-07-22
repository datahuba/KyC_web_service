"""
Utilidades de Zona Horaria
===========================

Funciones helper para convertir timestamps UTC a hora boliviana (UTC-4).

Uso:
----
from core.timezone_utils import utcnow_naive, to_bolivia_time, convert_dict_dates_to_bolivia

# Convertir un datetime
fecha_bolivia = to_bolivia_time(payment.fecha_subida)

# Convertir múltiples campos en un dict
data = convert_dict_dates_to_bolivia(
    payment_dict,
    ['fecha_subida', 'created_at', 'updated_at']
)
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any

# Constante: Offset de Bolivia respecto a UTC
BOLIVIA_OFFSET = timedelta(hours=-4)


def utcnow_naive() -> datetime:
    """
    Retorna el datetime UTC actual SIN timezone info (naive).
    Reemplazo compatible de `utcnow_naive()` (deprecado en Python 3.12+).

    Mantener el resultado NAIVE es importante: todos los datetimes
    almacenados en MongoDB son naive (UTC por convención del proyecto,
    ver `tech.md` seccion 3). Mezclar datetimes aware y naive causa
    `TypeError: can't subtract offset-naive and offset-aware datetimes`
    al compararlos (ej: `enrollment.fecha_pago > datetime.now()`).

    Si en el futuro se quiere migrar a datetimes aware, hay que hacerlo
    de forma coordinada en TODOS los modelos + scripts de migración
    de datos + tests. Por ahora, mantener naive es la convencion.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_bolivia_time(utc_dt: Optional[datetime]) -> str:
    """
    Convierte un datetime UTC a string en hora boliviana (UTC-4)
    
    Args:
        utc_dt: Datetime en UTC (o None)
    
    Returns:
        String en formato "YYYY-MM-DD HH:MM:SS" en hora Bolivia
        String vacío si utc_dt es None
    
    Ejemplo:
        >>> from datetime import datetime
        >>> utc = datetime(2024, 12, 29, 14, 0, 0)  # 14:00 UTC
        >>> to_bolivia_time(utc)
        '2024-12-29 10:00:00'  # 10:00 Bolivia
    """
    if not utc_dt:
        return ""
    
    bolivia_dt = utc_dt + BOLIVIA_OFFSET
    return bolivia_dt.strftime("%Y-%m-%d %H:%M:%S")


def convert_dict_dates_to_bolivia(
    data: Dict[str, Any],
    date_fields: List[str]
) -> Dict[str, Any]:
    """
    Convierte múltiples campos datetime en un diccionario a hora boliviana
    
    Args:
        data: Diccionario con datos (ej: payment.model_dump())
        date_fields: Lista de nombres de campos a convertir
    
    Returns:
        Diccionario con campos convertidos (modifica in-place)
    
    Ejemplo:
        >>> payment_dict = {
        ...     'id': '123',
        ...     'fecha_subida': datetime(2024, 12, 29, 14, 0, 0),
        ...     'created_at': datetime(2024, 12, 29, 10, 0, 0),
        ...     'monto': 500.0
        ... }
        >>> convert_dict_dates_to_bolivia(
        ...     payment_dict,
        ...     ['fecha_subida', 'created_at']
        ... )
        {
            'id': '123',
            'fecha_subida': '2024-12-29 10:00:00',
            'created_at': '2024-12-29 06:00:00',
            'monto': 500.0
        }
    """
    for field in date_fields:
        if field in data and isinstance(data[field], datetime):
            data[field] = to_bolivia_time(data[field])

    return data


def format_fecha(fecha_val, fmt: str = "%Y-%m-%d", fallback: str = "") -> str:
    """
    Helper para formatear fechas que pueden venir como datetime, date,
    string ISO, o None. Usado en F-COBRANZA-016 (export XLSX) porque
    `fecha_comprobante` puede llegar como string 'YYYY-MM-DD' en lugar
    de datetime, y `to_bolivia_time()` espera un datetime.

    Args:
        fecha_val: datetime | date | str | None
        fmt: formato strftime de salida
        fallback: string a devolver si fecha_val es None

    Returns:
        String formateado, o fallback si es None, o el string crudo
        si no se puede parsear.
    """
    from datetime import datetime, date
    if fecha_val is None:
        return fallback
    if isinstance(fecha_val, (datetime, date)):
        return fecha_val.strftime(fmt)
    if isinstance(fecha_val, str):
        # viene como '2026-07-22' o '2026-07-22T15:14:33'
        try:
            try:
                dt = datetime.fromisoformat(fecha_val.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.strptime(fecha_val, "%Y-%m-%d")
            return dt.strftime(fmt)
        except (ValueError, AttributeError):
            return fecha_val  # si no se puede parsear, devolver el string original
    return fallback
