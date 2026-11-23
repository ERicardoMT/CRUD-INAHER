"""Estudio de tiempos · pestaña Mediciones y sus ventanas (Nueva medición, editar, borrar y parámetros)."""
from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from archivo.excel import libro_excel
from archivo.views import _pagina, botones_rango, con_parametros, leer_rango
from core.models import Configuracion
from designaciones.models import MADRE_EMPAQUETAR, OperacionDetallada, OperacionMadre
from designaciones.reglas import sin_acentos
from pedidos.views import quien_hace

from . import calculos
from . import importar as importar_libro
from .forms import NUEVA, AprobarForm, MedicionForm, ParametrosForm, TiempoFijoForm
from .hoja import hoja_empaquetar, hoja_mediciones, hoja_operaciones
from .importar import clave_medicion
from .models import LETRA_MATERIAL, Bitacora, Importacion, MedicionBorrada, MedicionTiempo

ADMIN = "tiempos.administrar_estudio"
VER = {
    "todas": "Todas",
    "excluidas": "Excluidas",
    "revisar": "Por revisar",
    "nuevas": "Nuevas",
    "fuera": "Fuera de tolerancia",
}


def solo_admin(vista):
    """Regla 11: ver y exportar, todos; lo demás, solo el administrador (sin sesión, pide entrar)."""
    return login_required(permission_required(ADMIN, raise_exception=True)(vista))


def rangos_estudio(hoy):
    """Periodo: clave → (nombre, desde, hasta)."""
    return {
        "todo": ("Todo", None, None),
        "semana": ("Esta semana", hoy - timedelta(days=hoy.weekday()), hoy),
        "mes": ("Este mes", hoy.replace(day=1), hoy),
        "90": ("90 días", hoy - timedelta(days=90), hoy),
    }


def filtrar_mediciones(request, hoy, tolerancia):
    """Lo que se ve en pantalla. Lo comparten la tabla y el Excel para que siempre coincidan."""
    f = {"q": request.GET.get("q", "").strip()[:80], "ver": request.GET.get("ver", "todas")}
    if f["ver"] not in VER:
        f["ver"] = "todas"
    f["rango"], f["desde"], f["hasta"] = leer_rango(request, hoy, rangos=rangos_estudio, defecto="todo")

    mediciones = MedicionTiempo.objects.select_related(
        "operador", "operacion_madre", "maquina", "operacion_detallada__madre", "operacion_detallada__tiempo_fijo", "importacion",
    ).prefetch_related("operacion_detallada__escalones")
    if f["desde"]:
        mediciones = mediciones.filter(fecha__gte=f["desde"])
    if f["hasta"]:
        mediciones = mediciones.filter(fecha__lte=f["hasta"])
    for palabra in f["q"].split():
        mediciones = mediciones.filter(
            Q(operacion_madre__nombre__icontains=palabra) | Q(operacion_detallada__nombre__icontains=palabra)
            | Q(detallada_nueva__icontains=palabra) | Q(modelo_pieza__icontains=palabra)
            | Q(operador__nombre__icontains=palabra) | Q(quien_midio__icontains=palabra)
            | Q(maquina__nombre__icontains=palabra) | Q(medida__icontains=palabra)
        )
    ver = {
        "excluidas": Q(alerta=MedicionTiempo.Alerta.EXCLUIDA),
        "revisar": Q(alerta=MedicionTiempo.Alerta.REVISAR),
        "nuevas": Q(operacion_detallada__isnull=True),
        "fuera": Q(pct_dif__gt=tolerancia) | Q(pct_dif__lt=-tolerancia),
    }.get(f["ver"])
    if ver:
        mediciones = mediciones.filter(ver)
    return mediciones, f


def mediciones(request):
    hoy = timezone.localdate()
    config = Configuracion.actual()
    lista, f = filtrar_mediciones(request, hoy, config.estudio_tolerancia_pct)
    pagina, paginas = _pagina(request, lista)
    pagina.object_list = calculos.preparar_filas(list(pagina.object_list), config.estudio_tolerancia_pct)
    resumen = calculos.resumen_operaciones()
    tarjetas = calculos.tarjetas_mediciones(hoy, resumen, config)
    return render(request, "tiempos/mediciones.html", {
        **f,
        "pestana": "mediciones",
        "config": config,
        "tarjetas": tarjetas,
        "total_mediciones": tarjetas[0]["valor"],
        "total_operaciones": len(resumen),
        "pagina": pagina,
        "paginas": paginas,
        "rangos": botones_rango(request, hoy, f["rango"], rangos=rangos_estudio),
        "opciones_ver": VER,
        "consulta": con_parametros(request),
    })


def exportar(request):
    """Lo que se ve, con sus filtros; sin filtros sale todo y sirve de respaldo (12h)."""
    hoy = timezone.localdate()
    lista, f = filtrar_mediciones(request, hoy, Configuracion.actual().estudio_tolerancia_pct)
    periodo = rangos_estudio(hoy).get(f["rango"], ("fechas a mano",))[0]
    subtitulo = f"Ver: {VER[f['ver']]} · Periodo: {periodo}" + (f" · busca «{f['q']}»" if f["q"] else "")

    def liga(m):
        return request.build_absolute_uri(m.foto.url) if m.foto else m.foto_url

    return libro_excel("estudio_tiempos", [hoja_mediciones(lista, subtitulo, liga)])


# ---------------------------------------------------------------- ventanas (solo administrador)

def _ventana_medicion(request, form, status=200):
    return render(request, "tiempos/ventana_medicion.html", {
        "form": form,
        "nueva": NUEVA,
        "tolerancia": Configuracion.actual().estudio_tolerancia_pct,
        "madre_empaquetar": OperacionMadre.objects.filter(nombre=MADRE_EMPAQUETAR).values_list("pk", flat=True).first(),
        "midieron": MedicionTiempo.objects.exclude(quien_midio="").order_by("quien_midio")
                    .values_list("quien_midio", flat=True).distinct(),
    }, status=status)


def _iniciales(request):
    """La siguiente abre con la misma fecha, quién midió y operador; "Medir" trae la operación puesta."""
    iniciales = dict(request.session.get("estudio_ultima", {}))
    for campo in ("operacion_madre", "detallada"):
        if request.GET.get(campo, "").isdigit():
            iniciales[campo] = request.GET[campo]
        if "detallada" in iniciales:
            operacion = OperacionDetallada.objects.filter(pk=iniciales["detallada"]).first()
            iniciales["material"] = LETRA_MATERIAL.get(operacion.material, "") if operacion else ""
    return iniciales


@solo_admin
@require_http_methods(["GET", "POST"])
def medicion(request, pk=None):
    """Nueva medición y editar: la misma ventana (página 4, A)."""
    antes = get_object_or_404(MedicionTiempo, pk=pk) if pk else None
    actual = MedicionTiempo.objects.get(pk=pk) if pk else None  # el formulario la cambia; "antes" queda igual
    if request.method == "GET":
        return _ventana_medicion(request, MedicionForm(instance=actual, initial=None if pk else _iniciales(request)))

    form = MedicionForm(request.POST, request.FILES, instance=actual)
    if not form.is_valid():
        return _ventana_medicion(request, form, status=400)
    with transaction.atomic():
        guardada = form.save()
        calculos.recalcular(guardada)
        if antes and antes.clave_operacion != guardada.clave_operacion:
            calculos.recalcular(antes)  # la operación que dejó también recalcula su tiempo
        Bitacora.anotar(
            quien_hace(request), "Cambio de medición" if antes else "Alta de medición", guardada,
            antes.resumen() if antes else "", guardada.resumen(),
        )
    request.session["estudio_ultima"] = {
        "fecha": guardada.fecha.isoformat(), "quien_midio": guardada.quien_midio, "operador": guardada.operador_id,
    }
    return HttpResponse(status=204)


@solo_admin
@require_http_methods(["GET", "POST"])
def borrar(request, pk):
    """Borrar pide confirmación; la operación recalcula su tiempo y queda en la bitácora."""
    medicion = get_object_or_404(MedicionTiempo, pk=pk)
    if request.method == "GET":
        return render(request, "tiempos/ventana_borrar.html", {"medicion": medicion})
    with transaction.atomic():
        resumen = medicion.resumen()
        MedicionBorrada.objects.create(clave=clave_medicion(medicion))
        medicion.delete()
        calculos.recalcular(medicion)
        Bitacora.anotar(quien_hace(request), "Baja de medición", medicion, resumen, "")
    return HttpResponse(status=204)


@solo_admin
@require_http_methods(["GET", "POST"])
def parametros(request):
    """Tolerancia y desvío máximo. Cambiar el desvío revisa otra vez todas las mediciones (regla 4)."""
    config = Configuracion.actual()
    anterior = f"tolerancia {config.estudio_tolerancia_pct} % · desvío {config.estudio_desvio_pct} %"
    desvio_antes = config.estudio_desvio_pct
    if request.method == "GET":
        return render(request, "tiempos/ventana_parametros.html", {"form": ParametrosForm(instance=config)})

    form = ParametrosForm(request.POST, instance=config)
    if not form.is_valid():
        return render(request, "tiempos/ventana_parametros.html", {"form": form}, status=400)
    with transaction.atomic():
        config = form.save()
        if config.estudio_desvio_pct != desvio_antes:
            calculos.recalcular_todo()
        Bitacora.anotar(
            quien_hace(request), "Cambio de parámetros", "Estudio de tiempos", anterior,
            f"tolerancia {config.estudio_tolerancia_pct} % · desvío {config.estudio_desvio_pct} %",
        )
    return HttpResponse(status=204)

# ---------------------------------------------------------------- pestaña Tiempos por operación

FILTROS_OPERACION = {
    "todas": ("Todas", None),
    "faltan": ("Faltan de medir", ("falta", "dispersa")),
    "pocas": ("1 o 2 muestras", ("pocas",)),
    "listas": ("Listas", ("lista",)),
    "fijo": ("Fijo o aprobado", ("fijo", "aprobado")),
}
ORDEN_OPERACIONES = {  # así abre: primero las que tienen más tareas activas
    "tareas": ("Tareas activas", lambda f: (-f["tareas"], f["operacion"].madre.nombre.lower(), f["operacion"].nombre.lower())),
    "nombre": ("Nombre", lambda f: (f["operacion"].madre.nombre.lower(), f["operacion"].nombre.lower())),
    "muestras": ("Muestras", lambda f: (-f["validas"], -f["total"], f["operacion"].nombre.lower())),
}


def filtrar_operaciones(request):
    """Lo que se ve en la pestaña. Lo comparten la tabla y el Excel."""
    resumen = calculos.resumen_operaciones()
    f = {
        "q": request.GET.get("q", "").strip()[:80],
        "filtro": request.GET.get("filtro", "todas"),
        "orden": request.GET.get("orden", "tareas"),
    }
    if f["filtro"] not in FILTROS_OPERACION:
        f["filtro"] = "todas"
    if f["orden"] not in ORDEN_OPERACIONES:
        f["orden"] = "tareas"
    claves = FILTROS_OPERACION[f["filtro"]][1]
    texto = sin_acentos(f["q"])
    filas = [
        fila for fila in resumen
        if (not claves or fila["fuente"]["clave"] in claves)
        and texto in sin_acentos(f"{fila['operacion'].madre.nombre} {fila['operacion'].nombre}")
    ]
    filas.sort(key=ORDEN_OPERACIONES[f["orden"]][1])
    return resumen, filas, f


def operaciones(request):
    resumen, filas, f = filtrar_operaciones(request)
    pagina, paginas = _pagina(request, filas)
    cuenta = Counter(fila["fuente"]["clave"] for fila in resumen)
    return render(request, "tiempos/operaciones.html", {
        **f,
        "pestana": "operaciones",
        "tarjetas": calculos.tarjetas_operaciones(resumen),
        "total_mediciones": MedicionTiempo.objects.count(),
        "total_operaciones": len(resumen),
        "pagina": pagina,
        "paginas": paginas,
        "botones": [
            {"nombre": nombre, "n": sum(cuenta[c] for c in claves) if claves else len(resumen),
             "activo": clave == f["filtro"], "url": con_parametros(request, filtro=clave)}
            for clave, (nombre, claves) in FILTROS_OPERACION.items()
        ],
        "ordenes": {clave: nombre for clave, (nombre, _) in ORDEN_OPERACIONES.items()},
        "empaquetar": calculos.empaquetar_por_modelo(),
        "consulta": con_parametros(request),
    })


def exportar_operaciones(request):
    """Una fila por operación (con sus filtros) y Empaquetar por modelo. De consulta: no se importan."""
    _, filas, _ = filtrar_operaciones(request)
    return libro_excel("tiempos_por_operacion", [hoja_operaciones(filas), hoja_empaquetar(calculos.empaquetar_por_modelo())])


def ver_operacion(request, pk):
    """Ventana B: todas las mediciones de una operación y por qué entra o no cada una."""
    operacion = get_object_or_404(calculos.operaciones_del_estudio(), pk=pk)
    return render(request, "tiempos/ventana_operacion.html", {
        "operacion": operacion,
        "detalle": calculos.detalle_operacion(operacion),
        "desvio": Configuracion.actual().estudio_desvio_pct,
    })


@solo_admin
@require_http_methods(["GET", "POST"])
def aprobar(request, pk):
    """Ventana C: el aprobado manda sobre el tiempo fijo y la mediana (regla 6)."""
    operacion = get_object_or_404(calculos.operaciones_del_estudio(), pk=pk)
    if request.POST.get("accion") == "quitar":
        calculos.aprobar(operacion, None, "", quien_hace(request))
        return HttpResponse(status=204)
    form = AprobarForm(request.POST or None, initial={
        "minutos": operacion.minutos_aprobado, "motivo": operacion.aprobado_motivo,
    })
    form.fields["minutos"].label = f"Min por {'pedido' if operacion.es_por_pedido else 'pieza'} aprobado"
    if form.is_valid():
        calculos.aprobar(operacion, form.cleaned_data["minutos"], form.cleaned_data["motivo"], quien_hace(request))
        return HttpResponse(status=204)
    return render(request, "tiempos/ventana_aprobar.html", {
        "form": form, "operacion": operacion, "detalle": calculos.detalle_operacion(operacion),
    }, status=400 if form.is_bound else 200)


@solo_admin
@require_http_methods(["GET", "POST"])
def tiempo_fijo(request, pk):
    """⋮ › Tiempo fijo (regla 7). Borrarlo vuelve a usar la mediana."""
    operacion = get_object_or_404(calculos.operaciones_del_estudio(), pk=pk)
    fijo = getattr(operacion, "tiempo_fijo", None)
    if request.POST.get("accion") == "borrar":
        calculos.guardar_tiempo_fijo(operacion, None, False, quien_hace(request))
        return HttpResponse(status=204)
    form = TiempoFijoForm(request.POST or None, initial={
        "minutos": fijo.minutos if fijo else None,
        "por_pedido": fijo.por_pedido if fijo else operacion.es_por_pedido,
    })
    if form.is_valid():
        calculos.guardar_tiempo_fijo(operacion, form.cleaned_data["minutos"], form.cleaned_data["por_pedido"], quien_hace(request))
        return HttpResponse(status=204)
    return render(request, "tiempos/ventana_fijo.html", {
        "form": form, "operacion": operacion, "fijo": fijo, "escalones": list(operacion.escalones.all()),
    }, status=400 if form.is_bound else 200)


@solo_admin
@require_POST
def agregar_nueva(request, pk):
    """Regla 3: solo administrador. Desde ese momento sus mediciones cuentan."""
    medicion = get_object_or_404(MedicionTiempo, pk=pk, operacion_detallada__isnull=True, operacion_madre__isnull=False)
    operacion = calculos.agregar_al_catalogo(medicion, quien_hace(request))
    messages.success(request, f"«{operacion.nombre}» quedó en el catálogo de {operacion.madre.nombre}; sus mediciones ya cuentan.")
    return redirect("tiempos:lista")
# ---------------------------------------------------------------- importar (regla 12)

@solo_admin
@require_http_methods(["GET", "POST"])
def importar(request):
    """Subir el libro → resumen (no guarda nada) → Cargar. Todo en la misma ventana (12c)."""
    if request.POST.get("accion") == "cargar":
        resumen = request.session.pop("estudio_importar", None)
        if resumen and resumen["nuevas"]:
            importacion = importar_libro.cargar(resumen, quien_hace(request))
            messages.success(request, f"Se cargaron {importacion.cargadas} mediciones de «{importacion.archivo}».")
        return HttpResponse(status=204)

    error = ""
    if request.method == "POST":
        archivo = request.FILES.get("libro")
        if not archivo or not archivo.name.lower().endswith(".xlsx"):
            error = "Sube el libro descargado como Excel (.xlsx)."
        elif archivo.size > 10 * 1024 * 1024:
            error = "El archivo pesa más de 10 MB."
        else:
            try:
                resumen = importar_libro.revisar(archivo)
            except ValidationError as e:
                error = e.messages[0]
            else:
                request.session["estudio_importar"] = resumen
                return render(request, "tiempos/ventana_importar_resumen.html", {"resumen": resumen})
    return render(request, "tiempos/ventana_importar.html", {
        "error": error, "importaciones": Importacion.objects.filter(deshecha=False)[:5],
    }, status=400 if error else 200)


@solo_admin
@require_POST
def deshacer_importacion(request, pk):
    """Se subió el archivo equivocado: quita solo lo de esa carga (12g)."""
    importacion = get_object_or_404(Importacion, pk=pk, deshecha=False)
    cuantas = importar_libro.deshacer(importacion, quien_hace(request))
    messages.success(request, f"Se quitaron las {cuantas} mediciones de «{importacion.archivo}».")
    return HttpResponse(status=204)    