import statistics
from decimal import Decimal
from django.contrib import messages
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from pedidos.models import Pedido
from designaciones.models import Operario, Maquina, OperacionMadre, OperacionDetallada
from tiempos.models import MedicionTiempo
from .forms import OperarioForm, MaquinaForm, OperacionMadreForm, OperacionDetalladaForm
from django.db.models import ProtectedError


MODULOS = [
    {
        "slug": "designacion-diaria",
        "titulo": "Designación diaria",
        "descripcion": "Organiza las tareas, personas, operaciones y máquinas de cada jornada.",
        "icono": "bi-calendar2-check",
    },
    {
        "slug": "eficiencia",
        "titulo": "Eficiencia",
        "descripcion": "Consulta la captura de producción y los indicadores de desempeño.",
        "icono": "bi-speedometer2",
    },
    {
        "slug": "estudio-de-tiempos",
        "titulo": "Estudio de tiempos",
        "descripcion": "Organiza las mediciones y los tiempos estándar de las operaciones.",
        "icono": "bi-stopwatch",
    },
    {
        "slug": "catalogos",
        "titulo": "Catálogos / Config",
        "descripcion": "Administra personas, máquinas, operaciones y tiempos estándar.",
        "icono": "bi-sliders",
    },
    {
        "slug": "historico-reportes",
        "titulo": "Archivo",
        "descripcion": "Pedidos archivados, seguimiento comercial y tareas cerradas.",
        "icono": "bi-archive",
    },
]


def inicio(request):
    contexto = {
        "total_pedidos": Pedido.objects.vigentes().count(),
        "pedidos_en_proceso": Pedido.objects.vigentes().filter(estado=Pedido.Estado.EN_PROCESO).count(),
        "pedidos_terminados": Pedido.objects.vigentes().filter(estado=Pedido.Estado.TERMINADO).count(),
        "modulos": MODULOS,
    }
    return render(request, "core/inicio.html", contexto)


def modulo_pendiente(request, slug):
    if slug == "catalogos":
        return redirect("core:catalogos")
    if slug == "historico-reportes":
        return redirect("archivo:pedidos")

    modulo = next((item for item in MODULOS if item["slug"] == slug), None)
    if modulo is None:
        raise Http404("El módulo solicitado no existe.")
    return render(request, "core/modulo_pendiente.html", {"modulo": modulo})

def catalogos_config(request):
    operarios = Operario.objects.all().order_by("orden", "nombre")
    maquinas = Maquina.objects.all().order_by("tipo", "nombre")
    madres = OperacionMadre.objects.all().order_by("nombre")
    detalladas = OperacionDetallada.objects.select_related("madre", "maquina_sugerida").all().order_by("madre__nombre", "nombre")

    ops_con_metricas = []
    total_confiables = 0

    for op in detalladas:
        mediciones = MedicionTiempo.objects.filter(operacion_detallada=op, muestra_piezas__gt=0)
        tiempos = [float(m.minutos_muestra_decimal) for m in mediciones if m.minutos_muestra_decimal > 0]
        n_muestras = len(tiempos)

        if n_muestras >= 3:
            badge_clase = "status-terminado"
            badge_texto = f"{n_muestras} muestras (Confiable)"
            total_confiables += 1
        elif n_muestras in (1, 2):
            badge_clase = "status-proceso"
            badge_texto = f"{n_muestras} muestra(s) (En estudio)"
        else:
            badge_clase = "status-neutral"
            badge_texto = "0 muestras"

        mediana_calculada = round(statistics.median(tiempos), 2) if tiempos else float(op.minutos_estandar)

        ops_con_metricas.append({
            "objeto": op,
            "muestras": n_muestras,
            "badge_clase": badge_clase,
            "badge_texto": badge_texto,
            "mediana": mediana_calculada,
        })

    nuevas_estudio = MedicionTiempo.objects.filter(
        operacion_detallada__isnull=True
    ).values("operacion_madre__nombre", "modelo_pieza").distinct()

    contexto = {
        "operarios": operarios,
        "maquinas": maquinas,
        "madres": madres,
        "detalladas": ops_con_metricas,
        "nuevas_estudio": nuevas_estudio,
        "kpis": {
            "total_operarios": operarios.count(),
            "total_maquinas": maquinas.count(),
            "total_madres": madres.count(),
            "total_detalladas": detalladas.count(),
            "confiables": total_confiables,
            "nuevas_pendientes": len(nuevas_estudio),
        },
        "form_operario": OperarioForm(),
        "form_maquina": MaquinaForm(),
        "form_madre": OperacionMadreForm(),
        "form_detallada": OperacionDetalladaForm(),
    }
    return render(request, "core/catalogos.html", contexto)

@require_POST
def agregar_nuevas_config(request):
    mediciones_sin_op = MedicionTiempo.objects.filter(operacion_detallada__isnull=True)
    agregadas = 0

    for m in mediciones_sin_op:
        if m.operacion_madre and m.modelo_pieza:
            op_det, created = OperacionDetallada.objects.get_or_create(
                madre=m.operacion_madre,
                nombre=m.modelo_pieza.strip(),
                defaults={
                    "minutos_estandar": m.minutos_muestra_decimal if m.minutos_muestra_decimal > 0 else Decimal("0.0"),
                    "maquina_sugerida": m.maquina,
                }
            )
            m.operacion_detallada = op_det
            m.save(update_fields=["operacion_detallada"])
            if created:
                agregadas += 1

    if agregadas > 0:
        messages.success(request, f"Se agregaron {agregadas} nueva(s) operación(es) desde el Estudio de Tiempos a Config.")
    else:
        messages.info(request, "No hay operaciones nuevas pendientes por agregar.")
    return redirect("core:catalogos")

@require_POST
def recalcular_tiempos_config(request):
    detalladas = OperacionDetallada.objects.all()
    actualizadas = 0

    for op in detalladas:
        mediciones = MedicionTiempo.objects.filter(operacion_detallada=op, muestra_piezas__gt=0)
        tiempos = [float(m.minutos_muestra_decimal) for m in mediciones if m.minutos_muestra_decimal > 0]
        if tiempos:
            mediana = Decimal(str(round(statistics.median(tiempos), 2)))
            if op.minutos_estandar != mediana:
                op.minutos_estandar = mediana
                op.save(update_fields=["minutos_estandar"])
                actualizadas += 1

    messages.success(request, f"Cálculo completado: Se actualizaron los minutos estándar de {actualizadas} operaciones usando la mediana del estudio.")
    return redirect("core:catalogos")

@require_POST
def guardar_catalogo(request, tipo):
    if tipo == "operario":
        form = OperarioForm(request.POST)
    elif tipo == "maquina":
        form = MaquinaForm(request.POST)
    elif tipo == "madre":
        form = OperacionMadreForm(request.POST)
    elif tipo == "detallada":
        form = OperacionDetalladaForm(request.POST)
    else:
        raise Http404()

    if form.is_valid():
        form.save()
        messages.success(request, "Registro guardado correctamente.")
    else:
        messages.error(request, "Hubo un error al guardar. Revisa que el nombre no esté duplicado.")
    return redirect("core:catalogos")

@require_POST
def eliminar_catalogo(request, tipo, pk):
    modelos = {
        "operario": Operario,
        "maquina": Maquina,
        "madre": OperacionMadre,
        "detallada": OperacionDetallada,
    }
    modelo = modelos.get(tipo)
    if not modelo:
        raise Http404()
    item = get_object_or_404(modelo, pk=pk)
    try:
        item.delete()
        messages.info(request, f"{tipo.capitalize()} eliminado correctamente.")
    except ProtectedError:
        # Tiene historial: no se borra, se da de baja (sigue saliendo en el Archivo marcado "baja")
        campo = "activo" if hasattr(item, "activo") else "activa"
        setattr(item, campo, False)
        item.save(update_fields=[campo])
        messages.info(request, f"“{item}” tiene historial: se dio de baja en lugar de borrarse.")
    return redirect("core:catalogos")