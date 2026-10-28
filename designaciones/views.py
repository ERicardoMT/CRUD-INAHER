import json
from datetime import datetime
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

    items = designacion.items.select_related(
        "quien", "pedido", "operacion_madre", "operacion_detallada", "maquina"
    ).all()

    # Resumen por cada persona (como en columnas O, P, Q del Excel)
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
