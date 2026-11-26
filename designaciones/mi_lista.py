"""
Pantalla de los trabajadores · «Mi lista de hoy» (documento del 25-nov-2026).

Para celular. Cada quien entra con su usuario y ve solo sus tareas activas.
El trabajador NO ve precios, costos, clientes, tareas de otras personas,
cronómetro, total de minutos del día ni comparación contra lo que tardó.
"""
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.roles import EDITAR, nombre_de, puede

from . import reglas
from .models import ItemDesignacion, Operario

VISTAS = {
    "pedido": "Por pedido",
    "maquina": "Por máquina",
    "urgencia": "Por urgencia",
}

# Franjas de «Por urgencia», en este orden; clase = colores que ya usa el sistema
ALERTAS = [
    ("ATRASADO", "Atrasado", "alerta-roja"),
    ("SALE HOY", "Sale hoy", "alerta-naranja"),
    ("URGENTE", "Urgente", "alerta-ambar"),
    ("EN TIEMPO", "En tiempo", "alerta-verde"),
]
CLASE_ALERTA = {clave: clase for clave, _, clase in ALERTAS}
SIN_MAQUINA = "Sin máquina"


def _texto_minutos(minutos):
    """«Estimado 5 min» · «Estimado 2 h 30 min»."""
    horas, resto = divmod(int(minutos), 60)
    if not horas:
        return f"{resto} min"
    return f"{horas} h {resto} min" if resto else f"{horas} h"


def _preparar_renglon(t):
    """Lo que se ve en el renglón (sin cliente, sin costos, sin comparación)."""
    if t.pedido_id:
        t.titulo = t.producto
        t.subtitulo = t.detalle  # medida o nota que puso el administrador
    else:
        t.titulo = t.detalle or (t.descripcion_manual if t.descripcion_manual else t.operacion_detallada.nombre)
        t.subtitulo = ""
    t.maquina_texto = t.maquina.nombre if t.maquina_id else ""
    t.estimado = "" if t.sin_tiempo or not t.minutos else _texto_minutos(t.minutos)
    t.espera = t.estado_clave == "espera"
    alerta = t.alerta_info["texto"] if t.alerta_info else ""
    t.alerta_texto = alerta
    t.alerta_clase = CLASE_ALERTA.get(alerta, "alerta-gris")
    return t


def _clave_pedido(t):
    salida = t.pedido.fecha_salida if t.pedido_id and t.pedido.fecha_salida else date.max
    return (salida, t.pedido.numero if t.pedido_id else "", t.partida_id is None, t.partida_id or 0, t.paso, t.pk)


def _grupo(clave, titulo, clase="", salida=None, alerta="", tipo=""):
    return {"clave": clave, "titulo": titulo, "clase": clase, "salida": salida, "alerta": alerta,
            "tipo": tipo, "tareas": []}


def agrupar(pendientes, vista):
    """Franjas de la vista elegida. Las tareas generales (sin pedido) van al final en su franja."""
    con_pedido = sorted([t for t in pendientes if t.pedido_id], key=_clave_pedido)
    generales = sorted([t for t in pendientes if not t.pedido_id], key=lambda t: (t.paso, t.pk))
    grupos = {}

    if vista == "maquina":
        # Las generales van dentro de su máquina
        for t in con_pedido + generales:
            nombre = t.maquina_texto or SIN_MAQUINA
            grupos.setdefault(nombre, _grupo(f"maq-{t.maquina_id or 0}", nombre, tipo="Máquina"))["tareas"].append(t)
        return sorted(grupos.values(), key=lambda g: (g["titulo"] == SIN_MAQUINA, -len(g["tareas"]), g["titulo"].lower()))

    if vista == "urgencia":
        orden = {clave: i for i, (clave, _, _) in enumerate(ALERTAS)}
        nombres = {clave: nombre for clave, nombre, _ in ALERTAS}
        for t in con_pedido:
            clave = t.alerta_texto if t.alerta_texto in orden else "SIN FECHA"
            grupo = grupos.setdefault(clave, _grupo(
                f"alerta-{orden.get(clave, 9)}", nombres.get(clave, "Sin fecha"),
                CLASE_ALERTA.get(clave, "alerta-gris"), tipo="Alerta",
            ))
            grupo["tareas"].append(t)
        lista = sorted(grupos.values(), key=lambda g: g["clave"])
    else:
        for t in con_pedido:
            numero = t.pedido.numero
            grupos.setdefault(numero, _grupo(
                f"ped-{t.pedido_id}", numero, t.alerta_clase, t.pedido.fecha_salida, t.alerta_texto, tipo="Pedido",
            ))["tareas"].append(t)
        lista = list(grupos.values())  # ya vienen por fecha de salida

    if generales:
        general = _grupo("generales", "Tareas generales", "alerta-gris", tipo="Sin pedido")
        general["tareas"] = generales
        lista.append(general)
    return lista


def _operario_de(request):
    """
    El operario ligado al usuario. Quien administra Designación puede ver la lista de otra
    persona con ?operario=<id> (solo para revisar; no puede palomear por ella).
    """
    elegido = request.GET.get("operario") or request.POST.get("operario") or ""
    if elegido.isdigit() and puede(request.user, EDITAR):
        return get_object_or_404(Operario, pk=elegido, activo=True), True
    operario = Operario.objects.filter(usuario=request.user, activo=True).first()
    return operario, False


def _vista(request):
    vista = request.GET.get("ver") or request.POST.get("ver") or "pedido"
    return vista if vista in VISTAS else "pedido"


def datos_de(operario, vista):
    """Sus tareas activas, con estado calculado contra TODAS (el paso anterior puede ser de otra persona)."""
    todas = reglas.preparar(reglas.tareas_activas())
    mias = [_preparar_renglon(t) for t in todas if t.quien_id == operario.pk]
    pendientes = [t for t in mias if not t.hecho]
    terminadas = sorted([t for t in mias if t.hecho], key=lambda t: t.hecho_en or timezone.now(), reverse=True)
    grupos = agrupar(pendientes, vista)
    total = len(mias)
    return {
        "operario": operario,
        "vista": vista,
        "vistas": VISTAS,
        "grupos": grupos,
        "terminadas": terminadas,
        "total": total,
        "hechas": len(terminadas),
        "avance": round(len(terminadas) * 100 / total) if total else 0,
    }


@login_required
def mi_lista(request):
    operario, revisando = _operario_de(request)
    if not operario:
        return render(request, "designaciones/mi_lista_sin_operario.html", status=403)
    contexto = datos_de(operario, _vista(request))
    contexto.update({"hoy": timezone.localdate(), "revisando": revisando})
    return render(request, "designaciones/mi_lista.html", contexto)


def _tarea_propia(request, pk):
    """Solo sus tareas activas: nadie palomea por otra persona desde aquí."""
    return get_object_or_404(
        ItemDesignacion.objects.filter(reglas.Q_ACTIVA, quien__usuario=request.user, quien__activo=True), pk=pk,
    )


def _responder(request, tarea):
    from .views import sincronizar_pedidos  # estatus del pedido con ✓ y avances

    sincronizar_pedidos(tarea.pedido)
    contexto = datos_de(tarea.quien, _vista(request))
    contexto.update({"hoy": timezone.localdate(), "revisando": False})
    return JsonResponse({
        "ok": True,
        "lista": render_to_string("designaciones/_mi_lista_cuerpo.html", contexto, request=request),
    })


@login_required
@require_POST
def marcar(request, pk):
    """Palomita verde: terminada con todas sus piezas (o Deshacer desde «Ya terminadas»)."""
    tarea = _tarea_propia(request, pk)
    tarea.poner_check(request.POST.get("hecho") == "1", nombre_de(request.user))
    return _responder(request, tarea)


@login_required
@require_POST
def anotar_piezas(request, pk):
    """Piezas hechas, acumuladas. Al llegar al total se palomea sola."""
    tarea = _tarea_propia(request, pk)
    valor = (request.POST.get("piezas") or "").strip()
    if not tarea.lleva_hechas:
        return JsonResponse({"ok": False, "error": "Esta tarea no lleva piezas: solo se palomea."}, status=400)
    if not valor.isdigit() or int(valor) > tarea.cantidad:
        return JsonResponse({"ok": False, "error": f"Escribe un número de 0 a {tarea.cantidad}."}, status=400)
    tarea.poner_hechas(int(valor), nombre_de(request.user))
    return _responder(request, tarea)


def entrada(request):
    """Después de entrar: quien solo tiene su lista va directo a ella."""
    if request.user.is_authenticated and not puede(request.user, EDITAR) \
            and Operario.objects.filter(usuario=request.user, activo=True).exists():
        return redirect("mi_lista")
    return None
