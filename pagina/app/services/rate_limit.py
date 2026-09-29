"""
rate_limit.py — Limitador de tasa por usuario, en memoria.

Ventana deslizante simple. Se usa para el envío de informes por email, que es
el endpoint que saca datos de paciente fuera del sistema: sin tope servía como
canal de exfiltración y como relay de spam usando la cuenta SMTP configurada.

Al ser en memoria, el contador se reinicia cuando se reinicia el proceso. Es
proporcionado para un prototipo de un solo worker; un despliegue con varios
procesos necesitaría Redis o una tabla.
"""

import threading
import time
from collections import defaultdict, deque

_ventanas: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def check_and_consume(clave: str, limite: int, ventana_segundos: int = 3600) -> tuple[bool, int]:
    """Registra un uso si queda cupo.

    Devuelve (permitido, restantes_despues_de_este). Si no hay cupo, devuelve
    (False, 0) y no consume nada.
    """
    if limite <= 0:
        return False, 0

    ahora = time.time()
    corte = ahora - ventana_segundos

    with _lock:
        usos = _ventanas[clave]
        while usos and usos[0] < corte:
            usos.popleft()

        if len(usos) >= limite:
            return False, 0

        usos.append(ahora)
        return True, limite - len(usos)


def segundos_hasta_liberar(clave: str, ventana_segundos: int = 3600) -> int:
    """Cuántos segundos faltan para que se libere el cupo más viejo."""
    with _lock:
        usos = _ventanas.get(clave)
        if not usos:
            return 0
        return max(0, int(usos[0] + ventana_segundos - time.time()))


def reset(clave: str | None = None) -> None:
    """Limpia los contadores. Se usa en los tests."""
    with _lock:
        if clave is None:
            _ventanas.clear()
        else:
            _ventanas.pop(clave, None)
