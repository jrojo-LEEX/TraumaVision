"""
plantillas.py — Crea el `Jinja2Templates` que usan todas las rutas.

Registra los filtros de fecha (`fecha`, `hora`, `fecha_hora`, `iso_local`),
que pasan de UTC (como se guarda en la base) a la hora local.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from config.tiempo import a_local, fmt_local

_DIRECTORIO = Path(__file__).parent / "templates"


def _iso_local(dt) -> str:
    local = a_local(dt)
    return local.isoformat() if local else ""


FILTROS = {
    "fecha": lambda dt: fmt_local(dt, "%d/%m/%Y"),
    "hora": lambda dt: fmt_local(dt, "%H:%M"),
    "fecha_hora": lambda dt: fmt_local(dt, "%d/%m/%Y %H:%M"),
    "iso_local": _iso_local,
}


def crear_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(_DIRECTORIO))
    templates.env.filters.update(FILTROS)
    return templates
