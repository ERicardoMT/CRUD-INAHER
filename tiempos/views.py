from datetime import timedelta
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from .models import MedicionTiempo
from .forms import MedicionTiempoForm
from designaciones.models import OperacionDetallada


def estudio_tiempos_list(request):
    mediciones = MedicionTiempo.objects.select_related(
        "operador", "operacion_madre", "operacion_detallada", "maquina"
    ).all()

    hoy = timezone.localdate()
    lunes_semana = hoy - timedelta(days=hoy.weekday())

    # Indicadores superiores (Filas 3 y 4 del Excel):
    total_mediciones = mediciones.count()
    esta_semana = mediciones.filter(fecha__gte=lunes_semana, fecha__lte=hoy).count()
    ops_medidas = mediciones.exclude(operacion_detallada__isnull=True).values("operacion_detallada").distinct().count()

    en_tolerancia = 0
    nuevas = 0
    diferencias = []

    for m in mediciones:
        st = m.estatus_tolerancia
        if st["texto"] == "EN TOLERANCIA":
            en_tolerancia += 1
        elif st["texto"] == "NUEVA":
            nuevas += 1
        diferencias.append(m.porcentaje_dif)

    pct_tolerancia = round((en_tolerancia / total_mediciones * 100), 1) if total_mediciones > 0 else 0
    dif_promedio = round(sum(diferencias) / len(diferencias), 1) if diferencias else 0

    # Operaciones listas (3+ muestras):
    listas_3_muestras = 0
    for op in OperacionDetallada.objects.all():
        if mediciones.filter(operacion_detallada=op).count() >= 3:
            listas_3_muestras += 1

    form = MedicionTiempoForm()

    contexto = {
        "mediciones": mediciones,
        "form": form,
        "kpis": {
            "total": total_mediciones,
            "semana": esta_semana,
            "ops_medidas": ops_medidas,
            "pct_tolerancia": pct_tolerancia,
            "listas": listas_3_muestras,
            "nuevas": nuevas,
            "dif_promedio": dif_promedio,
        },
    }
    return render(request, "tiempos/estudio_tiempos.html", contexto)


def medicion_crear(request):
    if request.method == "POST":
        form = MedicionTiempoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Medición registrada correctamente.")
        else:
            messages.error(request, "Error al guardar la medición. Revisa los campos.")
    return redirect("tiempos:lista")


def medicion_eliminar(request, pk):
    medicion = get_object_or_404(MedicionTiempo, pk=pk)
    if request.method == "POST":
        medicion.delete()
        messages.info(request, "Medición eliminada.")
    return redirect("tiempos:lista")