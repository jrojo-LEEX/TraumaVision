"""
plantillas.py — Fábrica única de `Jinja2Templates`.

Cada módulo de rutas se construía su propio `Jinja2Templates(directory=...)`.
Mientras el entorno no tuviera nada configurado eso daba igual; en cuanto hubo
que registrar filtros —los de fecha, para no mostrar UTC como si fuera hora
local— tener cuatro entornos independientes significaba registrar lo mismo
cuatro veces y que la quinta pantalla saliera con el día corrido.

Todas las rutas piden su objeto acá. Los filtros se definen una sola vez.

Filtros de fecha disponibles en cualquier plantilla:

    {{ a.created_at|fecha }}        24/08/2026
    {{ a.created_at|hora }}         23:38
    {{ a.created_at|fecha_hora }}   24/08/2026 23:38
    {{ a.created_at|iso_local }}    2026-08-24T23:38:00-03:00

Los cuatro convierten desde UTC a la zona de presentación (config/tiempo.py).
Ninguna plantilla debe llamar a `.strftime()` sobre un `created_at`: lo que
hay en la columna es UTC y formatearlo directo lo muestra tres horas adelante.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from config.tiempo import a_local, fmt_local

_DIRECTORIO = Path(__file__).parent / "templates"

def _iso_local(dt) -> str:
    """ISO 8601 con offset. Es el valor de orden de la tabla del historial:
    tiene que ordenar por lo mismo que se ve, no por otra zona."""
    local = a_local(dt)
    return local.isoformat() if local else ""


FILTROS = {
    "fecha": lambda dt: fmt_local(dt, "%d/%m/%Y"),
    "hora": lambda dt: fmt_local(dt, "%H:%M"),
    "fecha_hora": lambda dt: fmt_local(dt, "%d/%m/%Y %H:%M"),
    "iso_local": _iso_local,
}


def crear_templates() -> Jinja2Templates:
    """Un `Jinja2Templates` apuntando a app/templates, con los filtros puestos."""
    templates = Jinja2Templates(directory=str(_DIRECTORIO))
    templates.env.filters.update(FILTROS)
    return templates
