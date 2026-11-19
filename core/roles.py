"""
Permisos de Designación diaria (versión 2, tabla de permisos).

Siguen el mismo esquema que el resto del sistema: permisos de Django definidos en el
Meta de ItemDesignacion, que se asignan a usuarios o grupos desde el admin.

| Acción                                         | Permiso                               | Administrador | Captura | Operador |
|------------------------------------------------|---------------------------------------|:-:|:-:|:-:|
| Ver, buscar y ordenar                          | (cualquier usuario)                   | ✓ | ✓ | ✓ |
| Imprimir y exportar                            | designaciones.imprimir_designacion    | ✓ | ✓ | — |
| Cargar ruta, agregar, editar, asignar, quitar  | designaciones.editar_designacion      | ✓ | — | — |
| ✓ y Hechas                                     | designaciones.palomear_designacion    | ✓ | — | — |
| Nuevo día                                      | designaciones.cerrar_dia              | ✓ | — | — |

El superusuario (Marcos) los tiene todos. Para abrirle algo a Captura (p. ej. que Denisse
cargue rutas) basta con darle ese permiso a su usuario o a su grupo.
"""
from functools import wraps

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect

VER, IMPRIMIR, EDITAR, PALOMEAR, NUEVO_DIA = "ver", "imprimir", "editar", "palomear", "nuevo_dia"

PERMISO = {
    IMPRIMIR: "designaciones.imprimir_designacion",
    EDITAR: "designaciones.editar_designacion",
    PALOMEAR: "designaciones.palomear_designacion",
    NUEVO_DIA: "designaciones.cerrar_dia",
}

def puede(user, accion):
    if accion == VER:
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    return user.has_perm(PERMISO[accion])


def permisos_de(user):
    """Para las plantillas: {"editar": True, ...}."""
    return {accion: puede(user, accion) for accion in (VER, IMPRIMIR, EDITAR, PALOMEAR, NUEVO_DIA)}


def nombre_de(user):
    """Quién hizo el cambio (se guarda con la ✓ y con Hechas)."""
    if getattr(user, "is_authenticated", False):
        return user.get_full_name() or user.get_username()
    return "Sin sesión"


def requiere(accion):
    """Decorador: sin permiso responde 403 (JSON) o regresa a la pantalla con un aviso."""
    def decorador(vista):
        @wraps(vista)
        def envuelta(request, *args, **kwargs):
            if puede(request.user, accion):
                return vista(request, *args, **kwargs)
            mensaje = "Tu usuario no tiene permiso para esta acción."
            if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.content_type == "application/json":
                return JsonResponse({"ok": False, "error": mensaje}, status=403)
            messages.error(request, mensaje)
            return redirect("designaciones:hoy")
        return envuelta
    return decorador
