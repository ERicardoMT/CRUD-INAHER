from django.contrib import messages
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from pedidos.models import Pedido
from designaciones.models import Operario, Maquina, OperacionMadre, OperacionDetallada
from pedidos.views import quien_hace
from tiempos.calculos import guardar_tiempo_fijo, resumen_operaciones
from .forms import ConfiguracionForm, OperarioForm, MaquinaForm, OperacionMadreForm, OperacionDetalladaForm
from .models import Configuracion
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
        "slug": "por-operacion",
        "titulo": "Por operación",
        "descripcion": "Lista de trabajo de hoy por operación, máquina o persona, para imprimir.",
        "icono": "bi-list-check",
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

TARJETAS_INICIO = [
    {"clave": "todos", "titulo": "Pedidos registrados", "texto": "Todos los pedidos vigentes",
     "icono": "bi-clipboard-data", "color": "icon-blue"},
    {"clave": "en_proceso", "titulo": "En proceso", "texto": "Pedidos con estado en proceso",
     "icono": "bi-arrow-repeat", "color": "icon-teal"},
    {"clave": "terminados", "titulo": "Terminados", "texto": "Pedidos marcados como terminados",
     "icono": "bi-check2-circle", "color": "icon-green"},
]

def inicio(request):
    tarjetas = [{**t, "valor": Pedido.objects.por_filtro(t["clave"]).count()} for t in TARJETAS_INICIO]
    return render(request, "core/inicio.html", {"tarjetas": tarjetas, "modulos": MODULOS})

def modulo_pendiente(request, slug):
    if slug == "catalogos":
        return redirect("core:catalogos")
    if slug == "historico-reportes":
        return redirect("archivo:pedidos")
    if slug == "eficiencia":
        return redirect("eficiencia:tareas")
    if slug == "por-operacion":
        return redirect("lista_trabajo:lista")

    modulo = next((item for item in MODULOS if item["slug"] == slug), None)
    if modulo is None:
        raise Http404("El módulo solicitado no existe.")
    return render(request, "core/modulo_pendiente.html", {"modulo": modulo})

def catalogos_config(request):
    operarios = Operario.objects.all().order_by("orden", "nombre")
    maquinas = Maquina.objects.all().order_by("tipo", "nombre")
    madres = OperacionMadre.objects.all().order_by("nombre")
    detalladas = (
        OperacionDetallada.objects.select_related("madre", "maquina_sugerida", "tiempo_fijo")
        .prefetch_related("escalones").order_by("madre__nombre", "nombre")
    )
    # Usa HOY y de dónde sale: lo mismo que Estudio de tiempos (regla 10)
    fuentes = {fila["operacion"].pk: fila for fila in resumen_operaciones()}

    contexto = {
        "operarios": operarios,
        "maquinas": maquinas,
        "madres": madres,
        "detalladas": [{"objeto": op, "fila": fuentes.get(op.pk)} for op in detalladas],
        "kpis": {
            "total_operarios": operarios.count(),
            "total_maquinas": maquinas.count(),
            "total_madres": madres.count(),
            "total_detalladas": detalladas.count(),
            "confiables": sum(1 for fila in fuentes.values() if fila["validas"] >= 3),
        },
        "form_operario": OperarioForm(),
        "form_maquina": MaquinaForm(),
        "form_madre": OperacionMadreForm(),
        "form_detallada": OperacionDetalladaForm(),
        "form_config": ConfiguracionForm(instance=Configuracion.actual()),
    }
    return render(request, "core/catalogos.html", contexto)

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
        objeto = form.save()
        minutos = form.cleaned_data.get("min_estimado")
        if tipo == "detallada" and minutos:  # queda como tiempo fijo (Estudio de tiempos, regla 7)
            guardar_tiempo_fijo(objeto, minutos, objeto.es_por_pedido, quien_hace(request))
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

@require_POST
def guardar_configuracion(request):
    form = ConfiguracionForm(request.POST, instance=Configuracion.actual())
    if form.is_valid():
        form.save()
        messages.success(request, f"Turno y eficiencia guardados: turno de {form.instance.turno_minutos} minutos.")
    else:
        errores = " ".join(e for lista in form.errors.values() for e in lista)
        messages.error(request, f"No se guardó: {errores}")
    return redirect("core:catalogos")
