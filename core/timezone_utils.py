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
