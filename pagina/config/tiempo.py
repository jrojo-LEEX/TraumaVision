"""
tiempo.py — Zona horaria de PRESENTACIÓN.

La base guarda todo en UTC: `models._utcnow()` devuelve `datetime.now(timezone.utc)`.
Pero las columnas son `DateTime` sin `timezone=True`, así que SQLite guarda el
reloj de pared UTC como texto y SQLAlchemy lo devuelve **naive**: sin tzinfo,
pero con la hora de UTC adentro.

Formatear ese naive con `strftime` lo muestra como si fuera hora local. En
Argentina (UTC-3) eso corre el registro clínico tres horas, y entre las 21:00
y las 24:00 cambia el DÍA del estudio. Verificado contra la base real: el
análisis más reciente se guardó a las 02:38 UTC del 25/08 y la app lo mostraba
como «25/08 02:38» cuando la placa se leyó el **24/08 a las 23:38**.

El mismo desfase hacía desaparecer análisis del gráfico de 30 días: un estudio
de las 22:00 locales cae en el día siguiente en UTC, y ese bucket no existía
entre las etiquetas del gráfico.

Acá vive la ÚNICA conversión UTC → zona de presentación de toda la app.
Nadie formatea un `created_at` sin pasar por acá: ni las plantillas (usan los
filtros de `app/plantillas.py`), ni el PDF, ni las exportaciones CSV.

Guardar en UTC está bien y no se toca. Lo que faltaba era decir en qué zona se
MUESTRA, y decirlo en un solo lugar.
"""

import os
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

# Zona en la que se LEE la app. No cambia lo que se guarda: sólo cómo se
# muestra. Argentina no aplica horario de verano desde 2009, así que el offset
# es constante -03:00; aun así se usa ZoneInfo y no un offset fijo, para que
# cambiar `DISPLAY_TIMEZONE` en .env alcance para reubicar el despliegue.
ZONA_PRESENTACION = os.getenv("DISPLAY_TIMEZONE", "America/Argentina/Buenos_Aires")

_ZONA: tzinfo | None = None


def zona() -> tzinfo:
    """La zona de presentación configurada.

    Si el nombre no existe en la base de datos de zonas del sistema se cae a
    UTC en vez de reventar: un despliegue mal configurado tiene que mostrar
    una hora rara, no dejar de emitir informes.
    """
    global _ZONA
    if _ZONA is None:
        try:
            _ZONA = ZoneInfo(ZONA_PRESENTACION)
        except Exception:
            _ZONA = timezone.utc
    return _ZONA


def a_local(dt: datetime | None) -> datetime | None:
    """Un instante de la base, en la zona de presentación.

    Un `datetime` naive se interpreta como UTC, que es lo que efectivamente
    guardaron `models._utcnow()` y SQLite. Uno aware se convierte.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zona())


def fmt_local(dt: datetime | None, formato: str) -> str:
    """`strftime` en la zona de presentación. Sin fecha, cadena vacía."""
    local = a_local(dt)
    return local.strftime(formato) if local else ""


def ahora_local() -> datetime:
    """El instante actual, en la zona de presentación."""
    return datetime.now(timezone.utc).astimezone(zona())


def ahora_utc_naive() -> datetime:
    """El instante actual como naive-UTC, comparable con las columnas.

    Es lo que hay que usar para acotar consultas por `created_at`.
    `datetime.now()` devuelve hora local naive y compararla contra una columna
    en UTC corre la ventana tantas horas como tenga el offset.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
