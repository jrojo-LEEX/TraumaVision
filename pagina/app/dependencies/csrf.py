"""
csrf.py — Protección contra Cross-Site Request Forgery.

EL ATAQUE QUE EVITA
La sesión vive en una cookie. El navegador la manda automáticamente en toda
petición al dominio, incluso si la petición la originó otra página. Sin esta
protección, un sitio cualquiera podía incluir:

    <form action="http://localhost:8000/analysis/12/email" method="post">
      <input name="to_email" value="atacante@ejemplo.com">
    </form>
    <script>document.forms[0].submit()</script>

y un médico logueado que visitara esa página enviaba el informe de un paciente
sin enterarse. Lo mismo con el feedback o el logout.

CÓMO FUNCIONA
Se genera un token aleatorio por sesión, se incrusta como campo oculto en cada
formulario y se verifica en cada POST. El atacante no puede leerlo (la política
de mismo origen se lo impide), así que no puede construir la petición.

Se compara con `secrets.compare_digest` para no filtrar información por el
tiempo de comparación.
"""

import secrets

from fastapi import HTTPException, Request

SESSION_CSRF_KEY = "csrf_token"
FORM_FIELD = "csrf_token"


def get_csrf_token(request: Request) -> str:
    """Devuelve el token de la sesión, creándolo la primera vez."""
    token = request.session.get(SESSION_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_CSRF_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Dependency para endpoints POST que usan sesión.

    Raises:
        HTTPException 403: falta el token o no coincide con el de la sesión.
    """
    esperado = request.session.get(SESSION_CSRF_KEY)

    enviado = request.headers.get("X-CSRF-Token")
    if not enviado:
        try:
            formulario = await request.form()
            enviado = formulario.get(FORM_FIELD)
        except Exception:
            enviado = None

    if not esperado or not enviado or not secrets.compare_digest(str(esperado), str(enviado)):
        raise HTTPException(
            status_code=403,
            detail=(
                "Token de seguridad inválido o vencido. "
                "Recargá la página e intentá de nuevo."
            ),
        )


def rotate_csrf_token(request: Request) -> str:
    """Genera un token nuevo. Se llama al iniciar sesión.

    Rotarlo en el login evita la fijación de sesión: un token conocido de
    antemano por un atacante deja de servir en cuanto el usuario se autentica.
    """
    token = secrets.token_urlsafe(32)
    request.session[SESSION_CSRF_KEY] = token
    return token
