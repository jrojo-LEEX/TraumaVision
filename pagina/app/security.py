"""
security.py — Hash y verificación de contraseñas.

PBKDF2-HMAC-SHA256 de la biblioteca estándar, con salt por usuario.
"""

import hashlib
import hmac
import secrets

_ALGORITMO = "pbkdf2_sha256"
_ITERACIONES = 240_000
_BYTES_DE_SALT = 16


def _pbkdf2(password: str, salt: bytes, iteraciones: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iteraciones)


def hash_password(password: str) -> str:
    """Devuelve 'pbkdf2_sha256$<iteraciones>$<salt_hex>$<hash_hex>'."""
    if not password:
        raise ValueError("La contraseña no puede estar vacía.")
    salt = secrets.token_bytes(_BYTES_DE_SALT)
    digest = _pbkdf2(password, salt, _ITERACIONES)
    return f"{_ALGORITMO}${_ITERACIONES}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """True si la contraseña coincide. Ante un hash mal formado, False."""
    if not password or not stored:
        return False
    try:
        algoritmo, iteraciones, salt_hex, esperado_hex = stored.split("$")
        iteraciones = int(iteraciones)
        salt = bytes.fromhex(salt_hex)
        esperado = bytes.fromhex(esperado_hex)
    except ValueError:
        return False
    if algoritmo != _ALGORITMO:
        return False
    # compare_digest tarda lo mismo acierte o no: no filtra información por el tiempo.
    return hmac.compare_digest(_pbkdf2(password, salt, iteraciones), esperado)
