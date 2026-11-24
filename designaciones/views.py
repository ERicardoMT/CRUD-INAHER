"""
Designación diaria · versión 2 (18-nov-2026).
Las reglas viven en reglas.py; aquí solo se arman pantallas, ventanas y acciones.
"""
import json
from datetime import timedelta

from django.contrib import messages
from django.core import serializers
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.roles import EDITAR, IMPRIMIR, NUEVO_DIA, PALOMEAR, nombre_de, permisos_de, requiere
from pedidos.models import MovimientoPedido, Pedido

from . import reglas
from .forms import ItemDesignacionForm
from .models import (
    MAQUINA_MANUAL, DesignacionDia, ItemDesignacion, Maquina, OperacionDetallada, OperacionMadre, Operario,
)

DESHACER_SEGUNDOS = 10


def sincronizar_pedidos(*pedidos):
    """Tras cambiar tareas: estatus por ✓/avance y bandera DETENIDO por tareas bloqueadas."""
    for pedido in {p for p in pedidos if p}:
        pedido.refresh_from_db()
        pedido.sincronizar_estatus()
        pedido.sincronizar_detenido()


def _es_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _orden(request):
    orden = request.GET.get("orden") or request.POST.get("orden") or "urgencia"
    return orden if orden in reglas.ORDENES else "urgencia"


def _a_la_pantalla(request):
    return redirect(f"{reverse('designaciones:hoy')}?orden={_orden(request)}")


# ---------------------------------------------------------------- pantalla

def _datos_pantalla(request):
    """Lo que necesitan la pantalla y los fragmentos que se recargan al editar un renglón."""
    orden = _orden(request)
    maquinas = list(Maquina.objects.filter(activa=True))
    tareas = reglas.preparar(reglas.tareas_activas(), maquinas)
    turno = reglas.turno_minutos()
    return {
        "tareas": reglas.ordenar(tareas, orden),
        "tarjetas": reglas.tarjetas(tareas),
        "carga": reglas.carga_por_persona(tareas, turno),
        "turno": turno,
        "orden": orden,
        "ordenes": reglas.ORDENES,
        "operarios": Operario.objects.filter(activo=True).order_by("orden", "nombre"),
        "maquinas": maquinas,
        "permisos": permisos_de(request.user),
        "resumen_dia": reglas.resumen_nuevo_dia(tareas),
    }


def designacion_hoy(request):
    datos = _datos_pantalla(request)
    jornada = reglas.jornada_activa()
    datos.update({
        "designacion": jornada,
        "hoy": timezone.localdate(),
        "form_item": ItemDesignacionForm(),
        "pedidos_ruta": _pedidos_para_ruta(),
        "siguiente_fecha": reglas.siguiente_jornada(jornada),
        "deshacer": _deshacer_vigente(request),
    })
    return render(request, "designaciones/designacion_hoy.html", datos)


def _fragmentos(request):
    """Tabla, tarjetas y carga por persona ya calculadas, para reemplazarlas sin recargar la página."""
    datos = _datos_pantalla(request)
    return {
        "ok": True,
        "tabla": render_to_string("designaciones/_filas.html", datos, request=request),
        "tarjetas": render_to_string("designaciones/_tarjetas.html", datos, request=request),
        "carga": render_to_string("designaciones/_carga.html", datos, request=request),
    }


def _respuesta(request, mensaje=None):
    if _es_ajax(request):
        respuesta = _fragmentos(request)
        if mensaje:
            respuesta["mensaje"] = mensaje
        return JsonResponse(respuesta)
    if mensaje:
        messages.success(request, mensaje)
    return _a_la_pantalla(request)


def _error(request, texto):
    if _es_ajax(request):
        return JsonResponse({"ok": False, "error": texto}, status=400)
    messages.error(request, texto)
    return _a_la_pantalla(request)


# ---------------------------------------------------------------- edición en el renglón (regla 6)

CAMPOS_RENGLON = {"quien", "maquina", "detalle", "cantidad", "piezas_hechas"}


@require_POST
@requiere(EDITAR)
def guardar_campo(request, pk):
    """Todo lo azul se cambia en el renglón y se guarda al salir de la casilla."""
    tarea = get_object_or_404(ItemDesignacion.objects.filter(reglas.Q_ACTIVA), pk=pk)
    campo = request.POST.get("campo", "")
    valor = (request.POST.get("valor") or "").strip()
    quien = nombre_de(request.user)

    if campo not in CAMPOS_RENGLON:
        return _error(request, "Ese dato no se edita aquí.")

    if campo == "piezas_hechas":
        if not tarea.lleva_hechas:
            return _error(request, "Esta tarea no lleva Hechas: solo se palomea.")
        valor = valor or "0"
        if not valor.isdigit():
            return _error(request, "Hechas debe ser un número entero de 0 a Cant.")
        if int(valor) > tarea.cantidad:
            return _error(request, f"Hechas no puede pasar de {tarea.cantidad}.")
        tarea.poner_hechas(int(valor), quien)

    elif campo == "cantidad":
        if not valor.isdigit():
            return _error(request, "La cantidad es un número entero, cero o más.")
        cantidad = int(valor)
        if cantidad < tarea.hechas:
            return _error(request, f"Cant no puede ser menor que Hechas ({tarea.hechas}).")
        tarea.cantidad = cantidad
        tarea.cantidad_manual = True
        tarea.save()  # recalcula Min y Min restantes

    elif campo == "quien":
        operario = Operario.objects.filter(pk=valor, activo=True).first() if valor.isdigit() else None
        if valor and not operario:
            return _error(request, "Elige una persona activa del catálogo.")
        tarea.quien = operario
        tarea.save(update_fields=["quien"])

    elif campo == "maquina":
        maquina = Maquina.objects.filter(pk=valor, activa=True).first() if valor.isdigit() else None
        if valor and not maquina:
            return _error(request, "Esa máquina no está activa.")
        tarea.maquina = maquina  # si no es de los tipos de la operación queda en naranja: avisa, no bloquea
        tarea.save(update_fields=["maquina"])

    elif campo == "detalle":
        tarea.detalle = valor[:255]
        tarea.save(update_fields=["detalle"])

    sincronizar_pedidos(tarea.pedido)
    return _respuesta(request)


@require_POST
@requiere(PALOMEAR)
def toggle_item_hecho(request, pk):
    """✓: palomear pone Hechas = Cant; quitarla regresa Hechas a lo que tenía."""
    tarea = get_object_or_404(ItemDesignacion.objects.filter(reglas.Q_ACTIVA), pk=pk)
    tarea.poner_check(not tarea.hecho, nombre_de(request.user))
    sincronizar_pedidos(tarea.pedido)
    return _respuesta(request)


# ---------------------------------------------------------------- agregar, editar, quitar

def _completar_tarea(tarea):
    """Lo que se llena solo al agregar: STOCK, paso, máquina sola."""
    tarea.es_stock = not tarea.pedido_id
    if tarea.es_stock:
        tarea.partida = None
        tarea.paso = 0
    elif not tarea.paso:
        ultimo = ItemDesignacion.objects.filter(
            reglas.Q_ACTIVA, pedido=tarea.pedido, partida=tarea.partida,
        ).exclude(pk=tarea.pk).aggregate(m=Max("paso"))["m"]
        tarea.paso = (ultimo or 0) + 1
    if not tarea.maquina_id:
        if tarea.operacion_detallada.es_tarea_especial:
            tarea.maquina = Maquina.objects.filter(nombre=MAQUINA_MANUAL).first()
        else:
            tarea.maquina = tarea.operacion_madre.maquina_sola()


def _errores_de(form):
    partes = []
    for campo, errores in form.errors.items():
        etiqueta = form.fields[campo].label if campo in form.fields else ""
        partes.append(f"{etiqueta}: {' '.join(errores)}" if etiqueta else " ".join(errores))
    return "; ".join(partes)


@require_POST
@requiere(EDITAR)
def agregar_item(request):
    """Agregar tarea: lo que no viene de una ruta (stock, vulcanizado, Chemlok…)."""
    form = ItemDesignacionForm(request.POST)
    if form.is_valid():
        tarea = form.save(commit=False)
        tarea.designacion = reglas.jornada_activa()
        _completar_tarea(tarea)
        tarea.save()
        sincronizar_pedidos(tarea.pedido)
        destino = tarea.quien.nombre if tarea.quien_id else "sin asignar"
        messages.success(request, f"Tarea agregada ({destino}).")
    else:
        messages.error(request, f"No se agregó la tarea. {_errores_de(form)}")
    return _a_la_pantalla(request)


@requiere(EDITAR)
def editar_item(request, pk):
    item = get_object_or_404(ItemDesignacion.objects.filter(reglas.Q_ACTIVA), pk=pk)  # lo archivado no cambia
    if request.method == "POST":
        pedido_anterior = item.pedido
        form = ItemDesignacionForm(request.POST, instance=item)
        if form.is_valid():
            tarea = form.save(commit=False)
            if "cantidad" in form.changed_data:
                tarea.cantidad_manual = True
            _completar_tarea(tarea)
            tarea.save()
            sincronizar_pedidos(pedido_anterior, tarea.pedido)
            messages.success(request, "Tarea actualizada.")
            return redirect("designaciones:hoy")
    else:
        form = ItemDesignacionForm(instance=item)

    return render(request, "designaciones/item_form.html", {
        "form": form,
        "item": item,
        "designacion": item.designacion,
    })


def _deshacer_vigente(request):
    copia = request.session.get("designacion_deshacer")
    if not copia:
        return None
    restan = copia["vence"] - timezone.now().timestamp()
    if restan <= 0:
        request.session.pop("designacion_deshacer", None)
        return None
    return {"cuantas": copia["cuantas"], "segundos": int(restan) + 1}


def _quitar(request, tareas):
    """Quitar de hoy: borra (no archiva). Guarda una copia para Deshacer durante 10 s."""
    tareas = list(tareas.select_related("pedido"))
    if not tareas:
        return 0
    request.session["designacion_deshacer"] = {
        "datos": serializers.serialize("json", tareas),
        "cuantas": len(tareas),
        "vence": (timezone.now() + timedelta(seconds=DESHACER_SEGUNDOS)).timestamp(),
    }
    pedidos = [t.pedido for t in tareas]
    with transaction.atomic():
        ItemDesignacion.objects.filter(pk__in=[t.pk for t in tareas]).delete()
    sincronizar_pedidos(*pedidos)
    return len(tareas)


@require_POST
@requiere(EDITAR)
def eliminar_item(request, pk):
    _quitar(request, ItemDesignacion.objects.filter(reglas.Q_ACTIVA, pk=pk))
    return _a_la_pantalla(request)


@require_POST
@requiere(EDITAR)
def quitar_seleccionadas(request):
    ids = [i for i in request.POST.getlist("item_ids") if i.isdigit()]
    if not ids:
        messages.warning(request, "Marca al menos una tarea con la casilla de la izquierda.")
        return _a_la_pantalla(request)
    _quitar(request, ItemDesignacion.objects.filter(reglas.Q_ACTIVA, pk__in=ids))
    return _a_la_pantalla(request)


@require_POST
@requiere(EDITAR)
def deshacer_quitar(request):
    copia = request.session.pop("designacion_deshacer", None)
    if not copia:
        messages.info(request, "No hay nada que deshacer.")
    elif timezone.now().timestamp() > copia["vence"] + 5:  # 5 s de gracia por la red
        messages.warning(request, "Ya pasó el tiempo para deshacer.")
    else:
        pedidos = []
        with transaction.atomic():
            for obj in serializers.deserialize("json", copia["datos"]):
                obj.save()
                pedidos.append(obj.object.pedido)
        sincronizar_pedidos(*pedidos)
        messages.success(request, f"Se regresaron {copia['cuantas']} tarea(s).")
    return _a_la_pantalla(request)


@require_POST
@requiere(EDITAR)
def asignar_persona(request):
    """Opciones › Asignar persona a las tareas marcadas (vacío = sin asignar)."""
    ids = [i for i in request.POST.getlist("item_ids") if i.isdigit()]
    valor = request.POST.get("quien", "")
    operario = Operario.objects.filter(pk=valor, activo=True).first() if valor.isdigit() else None
    if not ids:
        messages.warning(request, "Marca al menos una tarea con la casilla de la izquierda.")
    elif valor and not operario:
        messages.error(request, "Elige una persona activa del catálogo.")
    else:
        n = ItemDesignacion.objects.filter(reglas.Q_ACTIVA, pk__in=ids).update(quien=operario)
        destino = operario.nombre if operario else "sin asignar"
        messages.success(request, f"{n} tarea(s) → {destino}.")
    return _a_la_pantalla(request)


@require_POST
@requiere(EDITAR)
def actualizar_moldes(request, pk):
    """Vulcanizado del día: dos textos libres; no crean tareas ni suman minutos."""
    designacion = get_object_or_404(DesignacionDia, pk=pk)
    designacion.molde_1 = request.POST.get("molde_1", "").strip()[:150]
    designacion.molde_2 = request.POST.get("molde_2", "").strip()[:150]
    designacion.save(update_fields=["molde_1", "molde_2"])
    messages.success(request, "Moldes de vulcanizado actualizados.")
    return _a_la_pantalla(request)


# ---------------------------------------------------------------- Nuevo día (regla 9)

def _fecha_de(tarea):
    """La del día en que se palomeó o se capturó el avance, no la del botón."""
    momento = tarea.hecho_en or tarea.hechas_en
    return timezone.localtime(momento).date() if momento else tarea.designacion.fecha


def cerrar_dia():
    """
    Con ✓: se archivan y salen. Con avance y sin ✓: se archiva lo de hoy y la tarea se queda
    con lo que falta. Sin avance: se quedan igual. Regresa (fecha nueva, archivadas, con avance, sin avance).
    """
    actual = reglas.jornada_activa()
    siguiente = reglas.siguiente_jornada(actual)
    tareas = list(reglas.tareas_activas())
    archivadas = con_avance = sin_avance = 0

    with transaction.atomic():
        nuevo, _ = DesignacionDia.objects.get_or_create(fecha=siguiente)
        nuevo.cerrada = False
        nuevo.molde_1 = nuevo.molde_2 = ""  # también se vacían los 2 moldes
        nuevo.save()

        for t in tareas:
            if t.designacion_id == nuevo.pk:
                continue
            if t.hecho:
                t.fecha_cierre, t.cierre = _fecha_de(t), ItemDesignacion.Cierre.CHECK
                t.save(update_fields=["fecha_cierre", "cierre"])
                archivadas += 1
                continue

            continuacion = ItemDesignacion.objects.get(pk=t.pk)
            continuacion.pk = None
            continuacion.designacion = nuevo
            continuacion.min_real, continuacion.min_real_por, continuacion.min_real_en = None, "", None

            if t.tiene_avance:
                # Mañana amanece con lo que falta: Min = min/pz × (Cant − Hechas)
                continuacion.piezas_base = t.piezas_hechas
                continuacion.save()
                # Lo de hoy se archiva: piezas hechas hoy y Min hechos hoy (el estándar de ese día)
                piezas_hoy, min_hoy = t.hechas_hoy, t.min_hechos_hoy
                t.fecha_cierre, t.cierre = _fecha_de(t), ItemDesignacion.Cierre.AVANCE
                t.cantidad = t.piezas_hechas = piezas_hoy
                t.piezas_base = 0
                t.minutos, t.min_restantes = min_hoy, 0
                t.hecho = True
                t.save(update_fields=["fecha_cierre", "cierre", "cantidad", "piezas_hechas",
                                      "piezas_base", "minutos", "min_restantes", "hecho"])
                con_avance += 1
            else:
                continuacion.save()  # igual: persona, máquina, detalle y cantidad
                sin_avance += 1

        DesignacionDia.objects.filter(cerrada=False).exclude(pk=nuevo.pk).update(cerrada=True)
    return siguiente, archivadas, con_avance, sin_avance


@require_POST
@requiere(NUEVO_DIA)
def nuevo_dia(request):
    siguiente, archivadas, con_avance, sin_avance = cerrar_dia()
    messages.success(
        request,
        f"Día cerrado: {archivadas} tarea(s) con ✓ y {con_avance} avance(s) al Archivo. "
        f"Quedan {con_avance + sin_avance} tarea(s) para el {siguiente:%d/%m/%Y}.",
    )
    return _a_la_pantalla(request)


# ---------------------------------------------------------------- imprimir y exportar (regla 8)

@requiere(IMPRIMIR)
def imprimir_lista(request):
    datos = _datos_pantalla(request)
    datos.update({
        "ahora": timezone.localtime(),
        "orden_nombre": reglas.ORDENES[datos["orden"]][0].lower(),
    })
    return render(request, "designaciones/imprimir_lista.html", datos)


@requiere(IMPRIMIR)
def exportar_excel(request):
    """Todas las tareas del día, sin aplicar el buscador. Números como número, fechas como fecha."""
    datos = _datos_pantalla(request)
    ahora = timezone.localtime()
    wb = Workbook()
    ws = wb.active
    ws.title = "Designación"
    ws.append([f"INAHER · Designación diaria · {ahora:%d/%m/%Y %H:%M}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Orden: {reglas.ORDENES[datos['orden']][0].lower()} · {len(datos['tareas'])} tarea(s)"])
    ws.append([])
    encabezados = [
        "Quién", "# Pedido", "Paso", "Producto", "Partida", "Notas del pedido", "Operación madre",
        "Operación detallada", "Máquina", "Detalle", "Cant", "Min", "✓", "Hechas", "Faltan",
        "Min restantes", "Fecha salida", "Alerta", "Estado",
    ]
    ws.append(encabezados)
    fila_enc = ws.max_row
    for celda in ws[fila_enc]:
        celda.font = Font(bold=True)
        celda.fill = PatternFill("solid", fgColor="E8EEF6")

    for t in datos["tareas"]:
        numero = t.pedido.numero if t.pedido_id else "STOCK"
        ws.append([
            t.quien.nombre if t.quien_id else "",
            int(numero) if numero.isdigit() else numero,
            t.paso or None,
            t.producto,
            t.partida_texto,
            t.notas_pedido,
            t.operacion_madre.nombre,
            t.operacion_detallada.nombre,
            t.maquina.nombre if t.maquina_id else "",
            t.detalle,
            t.cantidad,
            None if t.sin_tiempo else t.minutos,
            "✓" if t.hecho else "",
            t.hechas if t.lleva_hechas else None,
            t.faltan if t.lleva_hechas else None,
            t.min_restantes,
            t.pedido.fecha_salida if t.pedido_id else None,
            t.alerta_info["texto"] if t.alerta_info else "",
            t.estado_texto,
        ])
    for fila in ws.iter_rows(min_row=fila_enc + 1):
        fila[16].number_format = "DD/MM/YYYY"
        for i in (3, 7):
            fila[i].alignment = Alignment(wrap_text=True, vertical="top")
    for i, ancho in enumerate([12, 10, 6, 34, 14, 26, 26, 40, 22, 26, 7, 7, 4, 8, 8, 10, 12, 11, 18], start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.freeze_panes = ws.cell(row=fila_enc + 1, column=1)
    ws.auto_filter.ref = f"A{fila_enc}:{get_column_letter(len(encabezados))}{ws.max_row}"

    respuesta = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="designacion_{ahora:%Y%m%d_%H%M}.xlsx"'
    wb.save(respuesta)
    return respuesta


# ---------------------------------------------------------------- catálogos para los formularios

@require_GET
def api_operaciones_detalladas(request):
    """Detalladas de esa madre y máquinas de sus tipos (en orden de preferencia)."""
    madre_id = request.GET.get("madre_id") or ""
    madre = OperacionMadre.objects.filter(pk=madre_id).first() if madre_id.isdigit() else None
    if not madre:
        return JsonResponse({"detalles": [], "maquinas": []})
    detalles = [
        {"id": d.pk, "nombre": d.nombre, "minutos_estandar": float(d.minutos_estandar),
         "usa_hoy": float(d.usa_hoy) if d.usa_hoy else None, "origen": d.usa_hoy_origen,
         "maquina_sugerida_id": d.maquina_sugerida_id, "especial": d.es_tarea_especial}
        for d in madre.detalles.filter(activa=True).select_related("madre", "tiempo_fijo").prefetch_related("escalones")
    ]
    sola = madre.maquina_sola()
    return JsonResponse({
        "detalles": detalles,
        "maquinas": [{"id": m.pk, "nombre": m.nombre} for m in madre.opciones_maquina()],
        "maquina_sola": sola.pk if sola else None,
    })


@require_GET
def api_pedido_info(request):
    pedido_id = request.GET.get("pedido_id") or ""
    pedido = Pedido.objects.filter(pk=pedido_id).prefetch_related("partidas").first() if pedido_id.isdigit() else None
    if not pedido:
        return JsonResponse({"error": "No existe"}, status=404)
    return JsonResponse({
        "descripcion": pedido.descripcion,
        "cantidad": pedido.cantidad,
        "fecha_salida": pedido.fecha_salida.strftime("%Y-%m-%d") if pedido.fecha_salida else "",
        "partidas": [{"id": x.pk, "cantidad": x.cantidad, "descripcion": x.descripcion} for x in pedido.partidas.all()],
    })


# ---------------------------------------------------------------- Cargar ruta de pedido (regla 7)

def _pedidos_para_ruta():
    """Pedidos activos: primero los que no tienen ruta cargada, por fecha de salida."""
    pedidos = list(Pedido.objects.carga_planta().annotate(tareas=Count("items_designacion")))
    lejana = timezone.localdate().replace(year=9999)
    pedidos.sort(key=lambda p: (p.tareas > 0, p.fecha_salida or lejana, p.numero))
    return pedidos


@require_GET
def api_ruta_pedido(request):
    """Partidas del pedido tal como se capturaron, y cuántas tareas tiene ya cada una (activas o archivadas)."""
    pedido_id = request.GET.get("pedido_id") or ""
    pedido = get_object_or_404(Pedido.objects.prefetch_related("partidas"), pk=pedido_id if pedido_id.isdigit() else 0)
    cargadas = dict(
        ItemDesignacion.objects.filter(pedido=pedido, partida__isnull=False)
        .filter(reglas.Q_ACTIVA | Q(fecha_cierre__isnull=False))  # sin las copias que deja Nuevo día
        .values_list("partida").annotate(n=Count("pk"))
    )
    alerta = pedido.alerta_estado
    return JsonResponse({
        "id": pedido.pk,
        "numero": pedido.numero,
        "cantidad": pedido.cantidad,
        "estatus": pedido.get_estado_display(),
        "fecha_salida": pedido.fecha_salida.strftime("%d/%m/%y") if pedido.fecha_salida else "",
        "alerta": alerta["texto"],
        "alerta_clase": alerta["clase"],
        "partidas": [
            {"id": p.pk, "cantidad": p.cantidad, "descripcion": p.descripcion, "tareas": cargadas.get(p.pk, 0)}
            for p in pedido.partidas.all()
        ],
    })


def _operacion(madre_nombre, detallada_nombre):
    madre, _ = OperacionMadre.objects.get_or_create(nombre=str(madre_nombre).strip()[:150])
    detallada, _ = OperacionDetallada.objects.get_or_create(madre=madre, nombre=str(detallada_nombre).strip()[:200])
    return madre, detallada


def _leer_json(request):
    try:
        return json.loads(request.body or "null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


@require_POST
@requiere(EDITAR)
def api_minutos_ruta(request):
    """Min de cada paso de la vista previa, con los tiempos vigentes del catálogo (null = sin tiempo)."""
    pasos = _leer_json(request)
    if not isinstance(pasos, list):
        return JsonResponse({"ok": False, "error": "Datos inválidos."}, status=400)
    resultado = []
    for paso in pasos[:300]:
        paso = paso if isinstance(paso, dict) else {}
        detallada = (
            OperacionDetallada.objects.filter(madre__nombre=paso.get("madre", ""), nombre=paso.get("detallada", ""))
            .select_related("madre", "tiempo_fijo").prefetch_related("escalones").first()
        )
        try:
            cantidad = max(int(paso.get("cantidad") or 0), 0)
        except (TypeError, ValueError):
            cantidad = 0
        resultado.append(None if not detallada or detallada.sin_tiempo else detallada.minutos_para(cantidad))
    return JsonResponse({"ok": True, "minutos": resultado})


@require_POST
@requiere(EDITAR)
def cargar_ruta(request):
    """
    Crea las tareas de la vista previa: un paso = una tarea, sin persona y sin detalle.
    Un solo Empaquetar al final, con la cantidad total. El estatus del pedido no cambia.
    """
    datos = _leer_json(request)
    if not isinstance(datos, dict):
        return JsonResponse({"ok": False, "error": "Datos inválidos."}, status=400)

    pedido_id = str(datos.get("pedido_id") or "")
    pedido = Pedido.objects.carga_planta().filter(pk=pedido_id).first() if pedido_id.isdigit() else None
    if not pedido:
        return JsonResponse({"ok": False, "error": "El pedido no está activo."}, status=400)
    partidas = {p.pk: p for p in pedido.partidas.all()}
    grupos = [g for g in (datos.get("partidas") or []) if isinstance(g, dict)]
    empaquetar = datos.get("empaquetar") if isinstance(datos.get("empaquetar"), dict) else None
    if not any(g.get("pasos") for g in grupos) and not empaquetar:
        return JsonResponse({"ok": False, "error": "No hay pasos que cargar."}, status=400)
    if any(g.get("partida_id") not in partidas for g in grupos):
        return JsonResponse({"ok": False, "error": "Una partida no es de este pedido."}, status=400)

    # Ya cargada (activas o archivadas): pide confirmar antes de cargarla otra vez
    repetidas = [partidas[g["partida_id"]].descripcion for g in grupos
                 if partidas[g["partida_id"]].items_designacion.exists()]
    if repetidas and not datos.get("confirmar"):
        return JsonResponse({"ok": False, "confirmar": True, "repetidas": repetidas})

    maquinas = {m.nombre.lower(): m for m in Maquina.objects.filter(activa=True)}
    jornada = reglas.jornada_activa()
    creadas = []
    with transaction.atomic():
        ultimo = 0
        for grupo in grupos:
            partida = partidas[grupo["partida_id"]]
            for paso in grupo.get("pasos") or []:
                madre, detallada = _operacion(paso.get("madre", ""), paso.get("detallada", ""))
                orden = int(paso.get("orden") or 0)
                ultimo = max(ultimo, orden)
                creadas.append(ItemDesignacion.objects.create(
                    designacion=jornada, pedido=pedido, partida=partida, paso=orden,
                    operacion_madre=madre, operacion_detallada=detallada,
                    maquina=maquinas.get(str(paso.get("maquina") or "").lower()),
                    cantidad=partida.cantidad,
                ))
        if empaquetar:
            madre, detallada = _operacion(empaquetar.get("madre", ""), empaquetar.get("detallada", ""))
            creadas.append(ItemDesignacion.objects.create(
                designacion=jornada, pedido=pedido, partida=None, paso=ultimo + 1,
                operacion_madre=madre, operacion_detallada=detallada,
                maquina=maquinas.get(str(empaquetar.get("maquina") or "").lower()),
                cantidad=pedido.cantidad,
            ))
    sincronizar_pedidos(pedido)  # sigue EN ESPERA: no hay ✓ ni avance
    total = sum(t.minutos for t in creadas)
    sin_tiempo = sum(1 for t in creadas if t.sin_tiempo)
    MovimientoPedido.registrar(pedido, MovimientoPedido.Accion.RUTA, nombre_de(request.user),
                            f"{len(creadas)} tareas · {total} min · {sin_tiempo} sin tiempo")
    messages.success(
        request,
        f"Se agregaron {len(creadas)} tareas del pedido {pedido.numero}: {total} min · {sin_tiempo} sin tiempo · nacen sin persona.",
    )
    return JsonResponse({"ok": True, "creadas": len(creadas), "url": reverse("designaciones:hoy")})
