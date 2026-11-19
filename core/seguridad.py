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
    
class CabecerasSeguridad:
    """
    Cabeceras extra en todas las respuestas:
    - CSP: el navegador solo carga scripts, estilos e imágenes de este sitio y del CDN de Bootstrap.
      Bloquea scripts de otros dominios, plugins, cambiar la dirección base y mandar formularios a otro sitio.
    - Permissions-Policy: apaga permisos que el sistema no usa (ubicación, micrófono, pagos, USB).
    """

    CSP = "; ".join([
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "font-src 'self' https://cdn.jsdelivr.net data:",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])
    PERMISOS = "camera=(self), geolocation=(), microphone=(), payment=(), usb=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        respuesta = self.get_response(request)
        respuesta.setdefault("Content-Security-Policy", self.CSP)
        respuesta.setdefault("Permissions-Policy", self.PERMISOS)
        return respuesta