"""
Catálogos › Turno y eficiencia: tarifas por hora y días que no se trabaja.
Antes solo se podían cambiar en el admin de Django (que ya no se usa).
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from designaciones.models import Maquina, Operario

from .models import DiaInhabil

VER_COSTOS = "eficiencia.ver_direccion"       # quien ve costos es quien captura tarifas
ADMINISTRA = "designaciones.editar_designacion"


def _a_turno():
    return redirect("/catalogos/#tab-config")


def _tarifa(texto):
    """Vacío = sin tarifa (suma cero en costos). Regresa (valor, error)."""
    texto = (texto or "").strip().replace(",", ".").replace("$", "")
    if not texto:
        return None, None
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None, f"«{texto}» no es un número"
    if valor < 0 or valor >= Decimal("1000000"):
        return None, f"«{texto}» está fuera de rango"
    return valor.quantize(Decimal("0.01")), None


@require_POST
@permission_required(VER_COSTOS, raise_exception=True)
def guardar_tarifas(request):
    errores, cambios = [], 0
    for modelo, prefijo, campo_activo in ((Operario, "op", "activo"), (Maquina, "maq", "activa")):
        for objeto in modelo.objects.filter(**{campo_activo: True}):
            clave = f"{prefijo}_{objeto.pk}"
            if clave not in request.POST:
                continue
            valor, error = _tarifa(request.POST[clave])
            if error:
                errores.append(f"{objeto.nombre}: {error}")
            elif valor != objeto.tarifa_hora:
                objeto.tarifa_hora = valor
                objeto.save(update_fields=["tarifa_hora"])
                cambios += 1
    if errores:
        messages.error(request, "No se guardaron algunas tarifas. " + "; ".join(errores))
    if cambios or not errores:
        messages.success(request, f"Tarifas guardadas ({cambios} cambio{'s' if cambios != 1 else ''}).")
    return _a_turno()


@require_POST
@permission_required(ADMINISTRA, raise_exception=True)
def agregar_dia(request):
    try:
        fecha = datetime.strptime(request.POST.get("fecha", ""), "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Escribe una fecha válida.")
        return _a_turno()
    motivo = (request.POST.get("motivo") or "").strip()[:120]
    _, creado = DiaInhabil.objects.update_or_create(fecha=fecha, defaults={"motivo": motivo})
    messages.success(request, f"{fecha:%d/%m/%Y} {'agregado' if creado else 'actualizado'} como día que no se trabaja.")
    return _a_turno()


@require_POST
@permission_required(ADMINISTRA, raise_exception=True)
def quitar_dia(request, pk):
    dia = get_object_or_404(DiaInhabil, pk=pk)
    dia.delete()
    messages.success(request, f"{dia.fecha:%d/%m/%Y} ya cuenta como día de trabajo.")
    return _a_turno()
