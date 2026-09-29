"""
security.py — Hash y verificación de contraseñas.

Usa PBKDF2-HMAC-SHA256 de la biblioteca estándar, con salt por usuario y
comparación en tiempo constante. No requiere dependencias externas.

Para un despliegue real conviene migrar a Argon2id (`argon2-cffi`); PBKDF2 es
suficiente y auditable para un prototipo de tesis.
"""

import hashlib
import hmac
import secrets

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 240_000
_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = _ITERATIONS) -> str:
    """Devuelve 'pbkdf2_sha256$<iteraciones>$<salt_hex>$<hash_hex>'."""
    if not password:
        raise ValueError("La contraseña no puede estar vacía.")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verifica una contraseña contra su hash almacenado.

    Devuelve False ante cualquier formato inválido, en vez de levantar: así un
    usuario sin contraseña seteada nunca puede autenticarse por accidente.
    """
    if not password or not stored:
        return False
    try:
        algorithm, iterations_s, salt_hex, expected_hex = stored.split("$")
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    try:
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except ValueError:
        return False

    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)
