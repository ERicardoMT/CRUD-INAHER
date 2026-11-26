"""
A dónde va cada quien al entrar.

- Administrador / Captura (cualquier usuario con permisos, staff o superusuario): el panel principal.
- Trabajador (usuario ligado a una persona en Catálogos, sin ningún permiso): solo «Mi lista de hoy».
  Si intenta abrir otra pantalla del sistema, se le regresa a su lista.
"""
from django.shortcuts import redirect
from django.urls import reverse


def es_solo_trabajador(user):
    if not getattr(user, "is_authenticated", False) or user.is_staff or user.is_superuser:
        return False
    if user.get_all_permissions():
        return False
    operario = getattr(user, "operario", None) if hasattr(user, "operario") else None
    return bool(operario and operario.activo)


class SoloSuLista:
    """El trabajador solo ve su lista (y puede salir)."""

    PERMITIDAS = ("/mi-lista/", "/salir/", "/entrar/", "/static/", "/favicon.ico")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if es_solo_trabajador(request.user) and not request.path.startswith(self.PERMITIDAS):
            return redirect(reverse("mi_lista"))
        return self.get_response(request)
