"""
tiempo.py — Zona horaria en la que se MUESTRAN las fechas.

La base guarda UTC sin tzinfo; toda conversión a hora local pasa por acá
(plantillas, PDF, CSV y gráficos).
"""

import os
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

ZONA_PRESENTACION = os.getenv("DISPLAY_TIMEZONE", "America/Argentina/Buenos_Aires")

_ZONA: tzinfo | None = None


def zona() -> tzinfo:
    """La zona de presentación; si el nombre no existe, UTC."""
    global _ZONA
    if _ZONA is None:
        try:
            _ZONA = ZoneInfo(ZONA_PRESENTACION)
        except Exception:
            _ZONA = timezone.utc
    return _ZONA


def a_local(dt: datetime | None) -> datetime | None:
    """Fecha de la base en hora local. Un `datetime` sin tzinfo se toma como UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zona())


def fmt_local(dt: datetime | None, formato: str) -> str:
    """`strftime` en hora local; sin fecha, cadena vacía."""
    local = a_local(dt)
    return local.strftime(formato) if local else ""


def ahora_local() -> datetime:
    return datetime.now(timezone.utc).astimezone(zona())


def ahora_utc_naive() -> datetime:
    """Ahora en UTC sin tzinfo: lo que hay que usar para filtrar por `created_at`."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
