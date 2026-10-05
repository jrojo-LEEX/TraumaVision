"""
plantillas.py — Crea el `Jinja2Templates` que usan todas las rutas.

Registra los filtros de fecha (`fecha`, `hora`, `fecha_hora`, `iso_local`),
que pasan de UTC (como se guarda en la base) a la hora local, y `decimal`,
que redondea hacia arriba en el empate (0,8875 → 0,888) y usa coma decimal.
"""

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

from config.tiempo import a_local, fmt_local

_DIRECTORIO = Path(__file__).parent / "templates"


def _decimal(valor, decimales=2) -> str:
    redondeado = Decimal(str(valor)).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    return str(redondeado).replace(".", ",")


def _iso_local(dt) -> str:
    local = a_local(dt)
    return local.isoformat() if local else ""


FILTROS = {
    "fecha": lambda dt: fmt_local(dt, "%d/%m/%Y"),
    "hora": lambda dt: fmt_local(dt, "%H:%M"),
    "fecha_hora": lambda dt: fmt_local(dt, "%d/%m/%Y %H:%M"),
    "iso_local": _iso_local,
    "decimal": _decimal,
}


def crear_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(_DIRECTORIO))
    templates.env.filters.update(FILTROS)
    return templates
