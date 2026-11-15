"""Bloqueo de fuerza bruta en el inicio de sesión: muchos intentos fallidos → esperar unos minutos."""
import hashlib

from django.conf import settings
from django.core.cache import cache


def _contadores(request, usuario):
    """Un contador por usuario (no se guarda el nombre tal cual) y otro por equipo (IP)."""
    usuario_hash = hashlib.sha256((usuario or "").strip().lower().encode()).hexdigest()
    ip = request.META.get("REMOTE_ADDR", "")
    return (
        (f"login:usuario:{usuario_hash}", settings.LOGIN_INTENTOS_POR_USUARIO),
        (f"login:ip:{ip}", settings.LOGIN_INTENTOS_POR_IP),
    )


def esta_bloqueado(request, usuario):
    return any(cache.get(clave, 0) >= limite for clave, limite in _contadores(request, usuario))


def registrar_fallo(request, usuario):
    segundos = settings.LOGIN_BLOQUEO_MINUTOS * 60
    for clave, _ in _contadores(request, usuario):
        cache.add(clave, 0, segundos)
        try:
            cache.incr(clave)
        except ValueError:  # expiró justo entre las dos líneas
            cache.set(clave, 1, segundos)


def limpiar(request, usuario):
    cache.delete_many([clave for clave, _ in _contadores(request, usuario)])
