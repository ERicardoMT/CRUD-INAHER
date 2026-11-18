from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_POST

from archivo.excel import libro_excel
from archivo.views import _texto_rango, botones_rango, con_parametros, leer_rango
from core.models import Configuracion
from designaciones.models import ItemDesignacion, Maquina, OperacionDetallada, OperacionMadre, Operario
from pedidos.views import quien_hace

from . import calculos, hojas
from .models import CambioEstandar

MOSTRAR = {"medidas": "medidas", "fuera": "fuera de tolerancia", "listas": "listas"}

# Dirección y Exportar todo: con sesión y con el permiso; si no, 403
solo_direccion = [login_required, permission_required("eficiencia.ver_direccion", raise_exception=True)]


def puede(request, permiso):
    """Superusuario, o quien el administrador autorice con el permiso."""
    return request.user.has_perm(f"eficiencia.{permiso}")


def leer_dia(request):
    try:
        return parse_date(request.GET.get("dia", "")) or timezone.localdate()
    except ValueError:
        return timezone.localdate()


def leer_periodo(request, hoy):
    """Un solo control de periodo para Por operación y Dirección; abre en Este mes."""
    return leer_rango(request, hoy, calculos.rangos_periodo, "mes")


def leer_ver(request):
    ver = request.GET.get("ver", "operador")
    return ver if ver in calculos.VER_POR else "operador"


def leer_filtros(request):
    """Cuatro filtros independientes; vacío = no filtra."""
    elegidos = {clave: request.GET.get(clave, "") for clave in calculos.FILTROS}
    filtros = {calculos.FILTROS[c]: v for c, v in elegidos.items() if v.isdigit()}
    return elegidos, filtros


def _vistas(request, ver):
    return [{"nombre": n, "activo": c == ver, "url": con_parametros(request, ver=c)}
            for c, (n, _) in calculos.VER_POR.items()]


def _contexto_dia(dia, filtros):
    """Tareas del día y sus tarjetas. Lo comparten las páginas y el guardado de Min real."""
    _, desde, hasta = calculos.rangos_periodo(timezone.localdate())["mes"]
    resumen = calculos.resumen_operaciones(desde, hasta, Configuracion.actual())
    fuera = sum(1 for f in resumen if f["estado"] == "FUERA")
    tareas = list(calculos.tareas_del_dia(dia, filtros))
    url_fuera = reverse("eficiencia:operaciones") + "?mostrar=fuera"
    return tareas, calculos.tarjetas_dia(tareas, fuera, url_fuera)


def _encabezado(request, dia, pestana):
    return {
        "pestana": pestana,
        "dia": dia,
        "config": Configuracion.actual(),
        "dia_anterior": con_parametros(request, dia=(dia - timedelta(days=1)).isoformat()),
        "dia_siguiente": con_parametros(request, dia=(dia + timedelta(days=1)).isoformat()),
        "puede_medir": puede(request, "capturar_tiempos"),
        "puede_cambiar": puede(request, "cambiar_estandar"),
    }


def selects_filtros(elegidos):
    """Opciones de los 4 filtros (las dadas de baja salen marcadas)."""
    def baja(activo):
        return "" if activo else " (baja)"

    return [
        {"nombre": "quien", "etiqueta": "Persona", "elegido": elegidos["quien"],
         "opciones": [(o.pk, o.nombre + baja(o.activo)) for o in Operario.objects.order_by("-activo", "nombre")]},
        {"nombre": "madre", "etiqueta": "Operación madre", "elegido": elegidos["madre"],
         "opciones": [(m.pk, m.nombre + baja(m.activa)) for m in OperacionMadre.objects.order_by("-activa", "nombre")]},
        {"nombre": "detallada", "etiqueta": "Operación detallada", "elegido": elegidos["detallada"],
         "opciones": [(d.pk, d.nombre + baja(d.activa))
                      for d in OperacionDetallada.objects.order_by("madre__nombre", "nombre")]},
        {"nombre": "maquina", "etiqueta": "Máquina", "elegido": elegidos["maquina"],
         "opciones": [(m.pk, m.nombre + baja(m.activa)) for m in Maquina.objects.order_by("-activa", "nombre")]},
    ]


# ---------------------------------------------------------------- pestañas

def tareas(request):
    dia = leer_dia(request)
    elegidos, filtros = leer_filtros(request)
    lista, tarjetas = _contexto_dia(dia, filtros)
    return render(request, "eficiencia/tareas.html", {
        **_encabezado(request, dia, "tareas"),
        "tareas": lista,
        "tarjetas": tarjetas,
        "selects": selects_filtros(elegidos),
    })


def operaciones(request):
    hoy = timezone.localdate()
    config = Configuracion.actual()
    rango, desde, hasta = leer_periodo(request, hoy)
    filas = calculos.resumen_operaciones(desde, hasta, config)
    mostrar = request.GET.get("mostrar", "medidas")
    if mostrar == "fuera":
        visibles = [f for f in filas if f["estado"] == "FUERA"]
    elif mostrar == "listas":
        visibles = [f for f in filas if f["medidas"] >= config.minimo_medidas]
    else:
        mostrar, visibles = "medidas", filas
    return render(request, "eficiencia/operaciones.html", {
        **_encabezado(request, hoy, "operaciones"),
        "tarjetas": calculos.tarjetas_periodo(filas, config, hoy),
        "filas": visibles,
        "rango": rango, "desde": desde, "hasta": hasta,
        "rangos": botones_rango(request, hoy, rango, calculos.rangos_periodo),
        "mostrar": mostrar,
        "opciones_mostrar": MOSTRAR,
        "cambios": CambioEstandar.objects.select_related("operacion")[:5],
    })


def minutos(request):
    dia = leer_dia(request)
    ver = leer_ver(request)
    lista, tarjetas = _contexto_dia(dia, {})
    config = Configuracion.actual()
    grupos, total = calculos.minutos_por(lista, ver, config.turno_minutos)
    titulo, nota = calculos.VER_POR[ver]
    return render(request, "eficiencia/minutos.html", {
        **_encabezado(request, dia, "minutos"),
        "tarjetas": tarjetas,
        "grupos": grupos,
        "total": total,
        "ver": ver,
        "ver_titulo": titulo,
        "nota": nota,
        "con_turno": ver in ("operador", "maquina"),
        "vistas": _vistas(request, ver),
    })


@solo_direccion[0]
@solo_direccion[1]
def direccion(request):
    """Pestaña Dirección: zona HOY (no cambia con el periodo) y zona PERIODO."""
    hoy = timezone.localdate()
    config = Configuracion.actual()
    rango, desde, hasta = leer_periodo(request, hoy)
    ver = leer_ver(request)
    datos = calculos.datos_direccion(hoy, desde, hasta, config)
    produccion, produccion_total = calculos.minutos_por(
        datos["tareas_produccion"], ver, datos["turno_periodo"], por_piezas=True,
    )
    _, tarjetas = _contexto_dia(hoy, {})
    return render(request, "eficiencia/direccion.html", {
        **_encabezado(request, hoy, "direccion"),
        **datos,
        "tarjetas": tarjetas,
        "produccion": produccion,
        "produccion_total": produccion_total,
        "ver": ver,
        "ver_titulo": calculos.VER_POR[ver][0],
        "con_turno": ver in ("operador", "maquina"),
        "vistas": _vistas(request, ver),
        "rango": rango, "desde": desde, "hasta": hasta,
        "rangos": botones_rango(request, hoy, rango, calculos.rangos_periodo),
    })


# ---------------------------------------------------------------- captura y estándar

@require_POST
def guardar_min_real(request, pk):
    """Casilla Min real: se guarda sola. Vacía = no cuenta. Regresa la fila y las tarjetas recalculadas."""
    if not puede(request, "capturar_tiempos"):
        return HttpResponseForbidden("Solo el administrador captura Min real.")
    tarea = get_object_or_404(ItemDesignacion, pk=pk)
    texto = request.POST.get("min_real", "").strip().replace(",", ".")
    if texto:
        try:
            valor = Decimal(texto).quantize(Decimal("0.1"))
        except InvalidOperation:
            valor = None
        if valor is None or not (0 < valor < 100000):
            return JsonResponse({"error": "Escribe los minutos reales (mayor a 0)."}, status=400)
        tarea.min_real, tarea.min_real_por, tarea.min_real_en = valor, quien_hace(request), timezone.now()
    else:
        tarea.min_real, tarea.min_real_por, tarea.min_real_en = None, "", None
    tarea.save(update_fields=["min_real", "min_real_por", "min_real_en"])

    lista, tarjetas = _contexto_dia(leer_dia(request), leer_filtros(request)[1])
    fila = next((t for t in lista if t.pk == tarea.pk), tarea)
    return JsonResponse({
        "fila": render_to_string("eficiencia/_fila_tarea.html", {"t": fila, "puede_medir": True}, request),
        "tarjetas": render_to_string("archivo/_tarjetas.html", {"tarjetas": tarjetas}, request),
    })


@require_http_methods(["GET", "POST"])
def cambiar_estandar(request, pk):
    """Pide confirmar con valor anterior y nuevo. Queda en bitácora."""
    if not puede(request, "cambiar_estandar"):
        return HttpResponseForbidden("Solo el administrador puede cambiar el estándar.")
    operacion = get_object_or_404(OperacionDetallada.objects.select_related("madre"), pk=pk)
    error = ""

    if request.method == "POST":
        medidas = request.POST.get("medidas", "")
        medidas = int(medidas) if medidas.isdigit() else 0
        try:
            nuevo = Decimal(request.POST.get("nuevo", "").replace(",", ".")).quantize(Decimal("0.01"))
        except InvalidOperation:
            nuevo = None
        if nuevo is None or not (0 < nuevo < 100000):
            error = "Escribe el minuto por pieza (mayor a 0)."
            propuesto = request.POST.get("nuevo", "")
        else:
            calculos.aplicar_estandar(operacion, nuevo, medidas, quien_hace(request) or "Sin nombre")
            return HttpResponse(status=204)
    else:
        _, desde, hasta = leer_periodo(request, timezone.localdate())
        filas = calculos.resumen_operaciones(desde, hasta, Configuracion.actual(), operacion_id=operacion.pk)
        propuesto = filas[0]["real"] if filas else operacion.minutos_estandar
        medidas = filas[0]["medidas"] if filas else 0

    return render(request, "eficiencia/ventana_estandar.html", {
        "operacion": operacion, "propuesto": propuesto, "medidas": medidas, "error": error,
    }, status=400 if error else 200)


# ---------------------------------------------------------------- Excel

def exportar(request, tabla):
    """Exporta la pestaña elegida. Minutos del día baja sus 4 vistas, cada una en su hoja."""
    hoy = timezone.localdate()
    dia = leer_dia(request)
    config = Configuracion.actual()
    if tabla == "operaciones":
        _, desde, hasta = leer_periodo(request, hoy)
        lista = [hojas.hoja_operaciones(calculos.resumen_operaciones(desde, hasta, config), desde, hasta)]
    elif tabla == "minutos":
        subtitulo = f"día {dia:%d/%m/%Y} · turno {config.turno_minutos} min"
        lista = hojas.hojas_minutos(list(calculos.tareas_del_dia(dia)), subtitulo, config.turno_minutos)
    else:
        tabla = "tareas"
        lista = [hojas.hoja_tareas(calculos.tareas_del_dia(dia, leer_filtros(request)[1]), dia)]
    return libro_excel(f"eficiencia_{tabla}", lista)

@solo_direccion[0]
@solo_direccion[1]
def exportar_todo(request):
    """Un solo archivo, una hoja por tabla, del día y periodo elegidos y sin filtros de pantalla."""
    hoy = timezone.localdate()
    dia = leer_dia(request)
    config = Configuracion.actual()
    _, desde, hasta = leer_periodo(request, hoy)
    datos = calculos.datos_direccion(hoy, desde, hasta, config)
    tareas_dia = list(calculos.tareas_del_dia(dia))
    periodo = _texto_rango(desde, hasta)
    lista = [
        hojas.hoja_tareas(tareas_dia, dia),
        hojas.hoja_operaciones(calculos.resumen_operaciones(desde, hasta, config), desde, hasta),
        *hojas.hojas_minutos(tareas_dia, f"día {dia:%d/%m/%Y} · turno {config.turno_minutos} min",
                             config.turno_minutos),
        hojas.hoja_carga(datos["carga"], datos["capacidad_dia"]),
        hojas.hoja_personas(datos["personas"], periodo),
        hojas.hoja_costos(datos["costos"], datos["hay_tarifas"]),
        hojas.hoja_faltan(datos["faltan"], datos["total_operaciones"]),
        *hojas.hojas_minutos(datos["tareas_produccion"],
                             f"terminadas {periodo} · {datos['dias_habiles']} días hábiles",
                             datos["turno_periodo"], prefijo="Producción", por_piezas=True),
    ]
    return libro_excel("eficiencia_todo", lista)
