import json
from datetime import datetime, timedelta
from django.db.models import F
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib import messages

from .models import (
    DesignacionDia,
    ItemDesignacion,
    Operario,
    Maquina,
    OperacionMadre,
    OperacionDetallada,
)
from .forms import DesignacionDiaForm, ItemDesignacionForm
from pedidos.models import Pedido


def designacion_hoy(request):
    fecha_param = request.GET.get("fecha")
    if fecha_param:
        try:
            fecha_actual = datetime.strptime(fecha_param, "%Y-%m-%d").date()
        except ValueError:
            fecha_actual = timezone.localdate()
    else:
        fecha_actual = timezone.localdate()

    designacion, _ = DesignacionDia.objects.get_or_create(fecha=fecha_actual)

    items_qs = designacion.items.select_related(
        "quien", "pedido", "operacion_madre", "operacion_detallada", "maquina"
    )

    orden = request.GET.get("orden")
    if orden == "persona":
        items = items_qs.order_by("quien__nombre", "paso")
    elif orden == "operacion":
        items = items_qs.order_by("operacion_madre__nombre", "operacion_detallada__nombre", "paso")
    elif orden == "maquina":
        items = items_qs.order_by(F("maquina__nombre").asc(nulls_last=True), "paso")
    elif orden == "urgencia":
        items = items_qs.order_by(F("pedido__fecha_salida").asc(nulls_last=True), "paso")
    else:
        items = items_qs.order_by("orden", "id")

    operarios = Operario.objects.filter(activo=True)
    resumen_operarios = []
    for op in operarios:
        items_op = [i for i in items if i.quien_id == op.id]
        min_asig = sum(i.minutos for i in items_op)
        min_hech = sum(i.minutos for i in items_op if i.hecho)
        pct = round((min_hech / min_asig * 100)) if min_asig > 0 else 0
        resumen_operarios.append({
            "operario": op,
            "min_asignados": min_asig,
            "min_hechos": min_hech,
            "porcentaje": pct,
            "tareas_total": len(items_op),
            "tareas_hechas": len([i for i in items_op if i.hecho]),
            "items": items_op,
        })

    # Conteo de alertas
    alertas_conteo = {
        "atrasados": len([i for i in items if i.alerta["texto"].startswith("ATRASADO")]),
        "sale_hoy": len([i for i in items if i.alerta["texto"] == "SALE HOY"]),
        "urgentes": len([i for i in items if i.alerta["texto"].startswith("URGENTE")]),
    }

    form_item = ItemDesignacionForm()
    form_moldes = DesignacionDiaForm(instance=designacion)

    contexto = {
        "designacion": designacion,
        "fecha_actual": fecha_actual,
        "es_hoy": (fecha_actual == timezone.localdate()),
        "items": items,
        "resumen_operarios": resumen_operarios,
        "alertas_conteo": alertas_conteo,
        "form_item": form_item,
        "form_moldes": form_moldes,
        "operarios": operarios,
        "operaciones_madre": OperacionMadre.objects.filter(activa=True),
        "pedidos_activos": Pedido.objects.exclude(estado=Pedido.Estado.TERMINADO),
    }

    return render(request, "designaciones/designacion_hoy.html", contexto)


@require_POST
def toggle_item_hecho(request, pk):
    item = get_object_or_404(ItemDesignacion, pk=pk)
    item.hecho = not item.hecho
    item.save(update_fields=["hecho"])

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
        desig = item.designacion
        return JsonResponse({
            "success": True,
            "id": item.id,
            "hecho": item.hecho,
            "total_asignados": desig.total_minutos_asignados,
            "total_hechos": desig.total_minutos_hechos,
            "porcentaje_avance": desig.porcentaje_avance,
        })

    return redirect(f"{reverse('designaciones:hoy')}?fecha={item.designacion.fecha.strftime('%Y-%m-%d')}")


@require_POST
def agregar_item(request, designacion_id):
    designacion = get_object_or_404(DesignacionDia, pk=designacion_id)
    form = ItemDesignacionForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.designacion = designacion
        item.save()
        messages.success(request, f"Tarea asignada a {item.quien.nombre} correctamente.")
    else:
        messages.error(request, "Error al registrar la tarea. Verifica los campos requeridos.")

    return redirect(f"{reverse('designaciones:hoy')}?fecha={designacion.fecha.strftime('%Y-%m-%d')}")


def editar_item(request, pk):
    item = get_object_or_404(ItemDesignacion, pk=pk)
    if request.method == "POST":
        form = ItemDesignacionForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, "Tarea actualizada.")
            return redirect(f"{reverse('designaciones:hoy')}?fecha={item.designacion.fecha.strftime('%Y-%m-%d')}")
    else:
        form = ItemDesignacionForm(instance=item)

    return render(request, "designaciones/item_form.html", {
        "form": form,
        "item": item,
        "designacion": item.designacion,
    })


@require_POST
def eliminar_item(request, pk):
    item = get_object_or_404(ItemDesignacion, pk=pk)
    fecha_str = item.designacion.fecha.strftime("%Y-%m-%d")
    item.delete()
    messages.info(request, "Tarea eliminada de la designación.")
    return redirect(f"{reverse('designaciones:hoy')}?fecha={fecha_str}")


@require_POST
def actualizar_moldes(request, pk):
    designacion = get_object_or_404(DesignacionDia, pk=pk)
    designacion.molde_1 = request.POST.get("molde_1", "").strip()
    designacion.molde_2 = request.POST.get("molde_2", "").strip()
    designacion.save(update_fields=["molde_1", "molde_2"])
    messages.success(request, "Moldes de vulcanizado actualizados.")
    return redirect(f"{reverse('designaciones:hoy')}?fecha={designacion.fecha.strftime('%Y-%m-%d')}")


def api_operaciones_detalladas(request):
    madre_id = request.GET.get("madre_id")
    if not madre_id:
        return JsonResponse({"detalles": []})

    detalles = OperacionDetallada.objects.filter(madre_id=madre_id, activa=True).values(
        "id", "nombre", "minutos_estandar", "maquina_sugerida_id"
    )
    return JsonResponse({"detalles": list(detalles)})


def api_pedido_info(request):
    pedido_id = request.GET.get("pedido_id")
    if not pedido_id:
        return JsonResponse({"error": "No pedido_id provided"}, status=400)
    try:
        pedido = Pedido.objects.get(pk=pedido_id)
        return JsonResponse({
            "descripcion": pedido.descripcion,
            "cantidad": pedido.cantidad,
            "fecha_salida": pedido.fecha_salida.strftime("%Y-%m-%d") if pedido.fecha_salida else "",
        })
    except Pedido.DoesNotExist:
        return JsonResponse({"error": "No existe"}, status=404)

@require_POST
def vaciar_items_seleccionados(request, designacion_id):
    """Vacía las filas de tareas seleccionadas mediante checkboxes."""
    item_ids = request.POST.getlist("item_ids")
    if item_ids:
        eliminados, _ = ItemDesignacion.objects.filter(id__in=item_ids, designacion_id=designacion_id).delete()
        messages.success(request, f"Se vaciaron {eliminados} fila(s) seleccionada(s).")
    else:
        messages.warning(request, "No seleccionaste ninguna fila para vaciar.")
    fecha = request.POST.get("fecha", "")
    return redirect(f"{reverse('designaciones:hoy')}?fecha={fecha}" if fecha else reverse('designaciones:hoy'))


@require_POST
def nuevo_dia(request, designacion_id):
    """Archiva la jornada actual y prepara el siguiente día con las tareas pendientes."""
    actual = get_object_or_404(DesignacionDia, pk=designacion_id)
    actual.cerrada = True
    actual.save()

    siguiente_fecha = actual.fecha + timedelta(days=1)
    if siguiente_fecha.weekday() == 6: 
        siguiente_fecha += timedelta(days=1)

    nuevo, _ = DesignacionDia.objects.get_or_create(fecha=siguiente_fecha)

    pendientes = actual.items.filter(hecho=False)
    for p in pendientes:
        ItemDesignacion.objects.create(
            designacion=nuevo,
            quien=p.quien,
            pedido=p.pedido,
            es_stock=p.es_stock,
            paso=p.paso,
            descripcion_manual=p.descripcion_manual,
            operacion_madre=p.operacion_madre,
            operacion_detallada=p.operacion_detallada,
            maquina=p.maquina,
            detalle=p.detalle,
            cantidad=p.cantidad,
            minutos=p.minutos,
            hecho=False
        )

    messages.success(request, f"Jornada archivada. Se inició el nuevo día: {siguiente_fecha.strftime('%d/%m/%Y')}.")
    return redirect(f"{reverse('designaciones:hoy')}?fecha={siguiente_fecha.strftime('%Y-%m-%d')}")


@require_POST
def cargar_ruta(request, designacion_id):
    """Genera automáticamente las operaciones estándar del pedido según su familia."""
    designacion = get_object_or_404(DesignacionDia, pk=designacion_id)
    pedido_id = request.POST.get("pedido_id")
    operario_id = request.POST.get("operario_id")
    familia = request.POST.get("familia", "MT")

    pedido = get_object_or_404(Pedido, pk=pedido_id)
    quien = Operario.objects.filter(pk=operario_id).first() or Operario.objects.first()

    secuencia_rutas = {
        "MT": [
            ("Cortar en sierra cinta", "Sierra cinta universal"),
            ("Maquinar en torno convencional", "Torno convencional"),
            ("Barrenar en torno convencional", "Torno convencional"),
            ("Machuelear en brazo automático", "Machuelador automático"),
            ("Armar nivelador sencillo (tornillo y base)", "Manual (mesa)"),
            ("Empaquetar", "Manual (mesa)"),
        ],
        "MKD": [
            ("Cortar en sierra cinta", "Sierra cinta universal"),
            ("Maquinar en torno convencional", "Torno convencional"),
            ("Barrenar en torno convencional", "Torno convencional"),
            ("Machuelear en brazo automático", "Machuelador automático"),
            ("Armar nivelador sencillo (tornillo y base)", "Manual (mesa)"),
            ("Armar PAD con nivelador", "Manual (mesa)"),
            ("Empaquetar", "Manual (mesa)"),
        ],
        "ROTULA": [
            ("Cortar en sierra cinta", "Sierra cinta universal"),
            ("Maquinar en torno convencional", "Torno convencional"),
            ("Barrenar en torno convencional", "Torno convencional"),
            ("Machuelear en brazo automático", "Machuelador automático"),
            ("Armar rotula con tornillo (limpiar y poner trabaroscas)", "Manual (mesa)"),
            ("Armar rótula con base (con presion)", "Manual (mesa)"),
            ("Empaquetar", "Manual (mesa)"),
        ],
        "VULCANIZADO": [
            ("Cortar neopreno", "Manual (mesa)"),
            ("Vulcanizar", "Prensa azul hidráulica"),
            ("Rebabear en tijera o cuter", "Manual (mesa)"),
            ("Armar nivelador sencillo (tornillo y base)", "Manual (mesa)"),
            ("Empaquetar", "Manual (mesa)"),
        ]
    }

    pasos = secuencia_rutas.get(familia, secuencia_rutas["MT"])
    creadas = 0

    for idx, (nombre_madre, nombre_maq) in enumerate(pasos, start=1):
        madre = OperacionMadre.objects.filter(nombre__icontains=nombre_madre).first()
        if not madre:
            madre, _ = OperacionMadre.objects.get_or_create(nombre=nombre_madre)

        detallada = OperacionDetallada.objects.filter(madre=madre).first()
        if not detallada:
            detallada = OperacionDetallada.objects.create(madre=madre, nombre=f"{nombre_madre} general")

        maquina = Maquina.objects.filter(nombre__icontains=nombre_maq).first()

        ItemDesignacion.objects.create(
            designacion=designacion,
            quien=quien,
            pedido=pedido,
            paso=idx,
            operacion_madre=madre,
            operacion_detallada=detallada,
            maquina=maquina,
            cantidad=pedido.cantidad,
            minutos=int(round(float(detallada.minutos_estandar or 1) * pedido.cantidad))
        )
        creadas += 1

    messages.success(request, f"Se cargó la ruta ({familia}) con {creadas} pasos para el Pedido #{pedido.numero}.")
    return redirect(f"{reverse('designaciones:hoy')}?fecha={designacion.fecha.strftime('%Y-%m-%d')}")    
