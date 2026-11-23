"""
Reglas del Estudio de tiempos que dependen de varias mediciones: alerta de muestra, exclusión,
mediana de cada operación y el tiempo que usan Designación diaria, Por operación y Eficiencia.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
from statistics import median

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from core.models import Configuracion
from designaciones.models import (
    MADRE_EMPAQUETAR, TAREA_ESPECIAL, ItemDesignacion, OperacionDetallada, TiempoFijo, redondear,
)
from designaciones.reglas import Q_ACTIVA

from .models import VARIOS_MODELOS, Bitacora, MedicionTiempo, a_decimales, con_signo, segundos_de

SIN_MODELO = "Sin modelo"
EXCLUIDA, REVISAR = MedicionTiempo.Alerta.EXCLUIDA, MedicionTiempo.Alerta.REVISAR


# ---------------------------------------------------------------- regla 4 · alerta de muestra y exclusión

def revisar(mediciones, desvio_pct):
    """
    Cada medición contra la mediana de TODAS las demás de su operación (también las excluidas).
    Es una sola pasada: no se repite quitando las excluidas.
    """
    limite = Decimal(desvio_pct) / 100
    for m in mediciones:
        otras = [x.min_pz for x in mediciones if x is not m]
        base = median(otras) if otras else None
        desvio = m.min_pz / base - 1 if base else None
        alerta = ""
        if desvio is not None and abs(desvio) > limite:
            alerta = EXCLUIDA if len(mediciones) >= 3 else REVISAR
        desvio = desvio.quantize(Decimal("0.0001")) if desvio is not None else None
        if (m.desvio, m.alerta) != (desvio, alerta):
            m.desvio, m.alerta = desvio, alerta
            m.save(update_fields=["desvio", "alerta"])


def mediana_valida(mediciones):
    """Mediana del min/pz de las válidas (las excluidas no cuentan). None si no queda ninguna."""
    validas = [m.min_pz for m in mediciones if m.alerta != EXCLUIDA]
    return median(validas) if validas else None


def recalcular_tareas(operacion):
    """Regla 9: las tareas activas toman el tiempo nuevo en ese momento; lo archivado no cambia."""
    for tarea in ItemDesignacion.objects.filter(Q_ACTIVA, operacion_detallada=operacion):
        tarea.save()


def guardar_mediana(operacion, mediciones):
    nueva = mediana_valida(mediciones) or Decimal(0)
    if operacion.minutos_estandar != nueva:
        operacion.minutos_estandar = nueva
        operacion.save(update_fields=["minutos_estandar"])
        recalcular_tareas(operacion)


def _misma_operacion(medicion):
    if medicion.operacion_detallada_id:
        return MedicionTiempo.objects.filter(operacion_detallada_id=medicion.operacion_detallada_id)
    return MedicionTiempo.objects.filter(
        operacion_detallada__isnull=True, operacion_madre_id=medicion.operacion_madre_id,
        detallada_nueva__iexact=medicion.detallada_nueva.strip(),
    )


@transaction.atomic
def recalcular(medicion):
    """Al guardar, editar o borrar una medición: su operación se revisa y recalcula su tiempo."""
    mediciones = list(_misma_operacion(medicion))
    revisar(mediciones, Configuracion.actual().estudio_desvio_pct)
    if medicion.operacion_detallada_id:
        guardar_mediana(OperacionDetallada.objects.get(pk=medicion.operacion_detallada_id), mediciones)


@transaction.atomic
def recalcular_todo():
    """Al cambiar el desvío máximo: todas las operaciones medidas."""
    desvio = Configuracion.actual().estudio_desvio_pct
    grupos = defaultdict(list)
    for m in MedicionTiempo.objects.select_related("operacion_madre"):
        grupos[m.clave_operacion].append(m)
    for mediciones in grupos.values():
        revisar(mediciones, desvio)
    for operacion in OperacionDetallada.objects.filter(mediciones__isnull=False).distinct():
        guardar_mediana(operacion, grupos[("catalogo", operacion.pk)])
    for operacion in OperacionDetallada.objects.filter(mediciones__isnull=True).exclude(minutos_estandar=0):
        guardar_mediana(operacion, [])    


# ---------------------------------------------------------------- regla 5 · el tiempo de cada operación

FUENTES = {
    "aprobado": ("Aprobado", "status-aprobado"),
    "fijo": ("Tiempo fijo", "status-neutral"),
    "lista": ("Mediana · {n} muestras", "status-terminado"),
    "pocas": ("Mediana · {n} muestra{s}", "status-proceso"),
    "dispersa": ("Dispersa · sin tiempo", "status-detenido"),
    "falta": ("Falta medir", "status-detenido"),
}


def operaciones_del_estudio():
    """Las del catálogo que se miden: activas y sin la Tarea especial (su tiempo vive en la tarea)."""
    madre, nombre = TAREA_ESPECIAL
    return (
        OperacionDetallada.objects.filter(activa=True)
        .exclude(madre__nombre=madre, nombre=nombre)
        .select_related("madre", "tiempo_fijo").prefetch_related("escalones")
    )


def fuente_de(operacion, validas, total):
    """De dónde sale Usa HOY: aprobado › tiempo fijo › mediana (lista o con 1 o 2) › dispersa › falta medir."""
    origen = operacion.usa_hoy_origen
    if origen in ("aprobado", "tiempo fijo"):
        clave = "aprobado" if origen == "aprobado" else "fijo"
    elif validas >= 3:
        clave = "lista"
    elif validas:
        clave = "pocas"
    else:
        clave = "dispersa" if total else "falta"
    texto, clase = FUENTES[clave]
    return {"clave": clave, "texto": texto.format(n=validas, s="" if validas == 1 else "s"), "clase": clase}


def resumen_operaciones():
    """Una fila por operación del catálogo (Tiempos por operación, Catálogos y las tarjetas)."""
    conteo = defaultdict(lambda: {"total": 0, "revisar": 0, "validas": []})
    for operacion_id, alerta, min_pz in MedicionTiempo.objects.filter(
        operacion_detallada__isnull=False
    ).values_list("operacion_detallada_id", "alerta", "min_pz"):
        fila = conteo[operacion_id]
        fila["total"] += 1
        fila["revisar"] += alerta == REVISAR
        if alerta != EXCLUIDA:
            fila["validas"].append(min_pz)
    activas = dict(
        ItemDesignacion.objects.filter(Q_ACTIVA).values_list("operacion_detallada").annotate(n=Count("pk"))
    )

    filas = []
    for operacion in operaciones_del_estudio():
        c = conteo[operacion.pk]
        validas = len(c["validas"])
        filas.append({
            "operacion": operacion,
            "total": c["total"],
            "validas": validas,
            "excluidas": c["total"] - validas,
            "revisar": c["revisar"],
            "mediana": median(c["validas"]) if validas else None,
            "usa_hoy": operacion.usa_hoy,
            "fijo": getattr(operacion, "tiempo_fijo", None),
            "escalones": list(operacion.escalones.all()),
            "fuente": fuente_de(operacion, validas, c["total"]),
            "tareas": activas.get(operacion.pk, 0),
        })
    return filas


# ---------------------------------------------------------------- pestaña Mediciones

def tarjetas_mediciones(hoy, resumen, config):
    """Las tarjetas no cambian con los filtros (página 1)."""
    todas = MedicionTiempo.objects.all()
    lunes = hoy - timedelta(days=hoy.weekday())
    difs = list(todas.filter(pct_dif__isnull=False).values_list("pct_dif", flat=True))
    dentro = sum(1 for d in difs if abs(d) <= config.estudio_tolerancia_pct)
    nuevas = {
        (madre, texto.strip().lower())
        for madre, texto in todas.filter(operacion_detallada__isnull=True).values_list("operacion_madre", "detallada_nueva")
    }
    revisar_ops = {m.clave_operacion for m in todas.filter(alerta=REVISAR)}
    excluidas = todas.filter(alerta=EXCLUIDA).count()
    pct = redondear(dentro * 100 / len(difs)) if difs else None
    promedio = sum(difs) / len(difs) if difs else None

    return [
        {"titulo": "Mediciones", "valor": todas.count(), "texto": "todas las guardadas",
         "tono": "blue", "icono": "bi-stopwatch"},
        {"titulo": "Esta semana", "valor": todas.filter(fecha__gte=lunes, fecha__lte=hoy).count(),
         "texto": "de lunes a hoy", "tono": "gray", "icono": "bi-calendar2-week"},
        {"titulo": "Operaciones medidas", "valor": sum(1 for f in resumen if f["total"]),
         "texto": f"de {len(resumen)} del catálogo", "tono": "gray", "icono": "bi-diagram-3"},
        {"titulo": "Dentro de tolerancia", "valor": f"{pct} %" if pct is not None else "—",
         "texto": f"± {config.estudio_tolerancia_pct} % contra el teórico", "tono": "green", "icono": "bi-check2-circle"},
        {"titulo": "Listas · 3+ muestras", "valor": sum(1 for f in resumen if f["validas"] >= 3),
         "texto": "tiempo confiable", "tono": "green", "icono": "bi-collection"},
        {"titulo": "Nuevas sin catálogo", "valor": len(nuevas), "texto": "amarillo si hay alguna",
         "tono": "amber" if nuevas else "gray", "icono": "bi-plus-circle"},
        {"titulo": "Dif. promedio", "valor": f"{con_signo(promedio)} %" if promedio is not None else "—",
         "texto": "muestra contra teórico", "tono": "gray", "icono": "bi-graph-up"},
        {"titulo": "Excluidas", "valor": excluidas,
         "texto": f"no entran al tiempo · {len(revisar_ops)} por revisar",
         "tono": "amber" if excluidas else "gray", "icono": "bi-exclamation-triangle"},
    ]


def preparar_filas(mediciones, tolerancia):
    """Usa HOY de cada renglón: verde si la muestra queda a ± tolerancia de él; rojo si no."""
    for m in mediciones:
        m.fuera = m.pct_dif is not None and abs(m.pct_dif) > tolerancia
        m.usa_hoy = m.usa_hoy_origen = None
        m.usa_hoy_dentro = False
        if m.operacion_detallada_id:
            operacion = m.operacion_detallada
            m.usa_hoy, m.usa_hoy_origen = operacion.usa_hoy, operacion.usa_hoy_origen
            if m.usa_hoy:
                m.usa_hoy_dentro = abs(m.min_pz / m.usa_hoy - 1) * 100 <= tolerancia
    return mediciones
# ---------------------------------------------------------------- pestaña Tiempos por operación

def tarjetas_operaciones(resumen):
    """Con tiempo = listas + con 1 o 2 muestras + tiempo fijo + aprobadas (página 3)."""
    cuenta = Counter(fila["fuente"]["clave"] for fila in resumen)
    con_tiempo = cuenta["lista"] + cuenta["pocas"] + cuenta["fijo"] + cuenta["aprobado"]
    faltan = cuenta["falta"] + cuenta["dispersa"]
    return [
        {"titulo": "Operaciones", "valor": len(resumen), "texto": "madre › detallada del catálogo",
         "tono": "blue", "icono": "bi-diagram-3"},
        {"titulo": "Con tiempo", "valor": con_tiempo,
         "texto": f"{cuenta['lista']} + {cuenta['pocas']} + {cuenta['fijo']} + {cuenta['aprobado']} de las tarjetas siguientes",
         "tono": "green", "icono": "bi-check2-circle"},
        {"titulo": "Listas · 3+ muestras", "valor": cuenta["lista"], "texto": "mediana confiable",
         "tono": "green", "icono": "bi-collection"},
        {"titulo": "Con 1 o 2 muestras", "valor": cuenta["pocas"], "texto": "tienen tiempo; falta confirmarlo",
         "tono": "amber", "icono": "bi-hourglass-split"},
        {"titulo": "Tiempo fijo", "valor": cuenta["fijo"], "texto": "decididos, no medidos",
         "tono": "gray", "icono": "bi-pin-angle"},
        {"titulo": "Aprobadas por Marcos", "valor": cuenta["aprobado"], "texto": "mandan sobre todo lo demás",
         "tono": "blue", "icono": "bi-patch-check"},
        {"titulo": "Faltan de medir", "valor": faltan, "texto": f"sin tiempo · {cuenta['dispersa']} dispersa",
         "tono": "red" if faltan else "gray", "icono": "bi-exclamation-triangle"},
    ]


def detalle_operacion(operacion):
    """Ventana Ver mediciones: cada una contra la mediana de las otras y por qué entra o no (regla 4)."""
    mediciones = list(operacion.mediciones.select_related("operador").order_by("fecha", "pk"))
    for m in mediciones:
        m.otras = sorted(x.min_pz for x in mediciones if x is not m)
        m.mediana_otras = median(m.otras) if m.otras else None
    validas = sum(1 for m in mediciones if not m.excluida)
    return {
        "mediciones": mediciones,
        "validas": validas,
        "mediana": mediana_valida(mediciones),
        "fuente": fuente_de(operacion, validas, len(mediciones)),
        "tareas": ItemDesignacion.objects.filter(Q_ACTIVA, operacion_detallada=operacion).count(),
    }


def empaquetar_por_modelo():
    """Página 10: una fila por modelo; los pedidos de varios modelos juntos; lo medido sin modelo aparte."""
    grupos = defaultdict(list)
    empaques = MedicionTiempo.objects.filter(operacion_madre__nombre=MADRE_EMPAQUETAR).exclude(
        operacion_detallada__escalones__isnull=False  # Contar y revisar no es empaque
    )
    for m in empaques:
        grupos[VARIOS_MODELOS if len(m.modelos) > 1 else (m.modelo_pieza or SIN_MODELO)].append(m)
    filas = []
    for modelo, medidas in sorted(grupos.items(), key=lambda g: (g[0] in (VARIOS_MODELOS, SIN_MODELO), g[0])):
        piezas = sorted(m.muestra_piezas for m in medidas)
        filas.append({
            "modelo": modelo,
            "pedidos": len(medidas),
            "piezas": str(piezas[0]) if piezas[0] == piezas[-1] else f"{piezas[0]} a {piezas[-1]}",
            "por_pedido": median(m.min_pz for m in medidas),
            "por_pieza": median(
                a_decimales(Decimal(segundos_de(m.muestra_tiempo_total)) / 60 / m.muestra_piezas, 2) for m in medidas
            ),
        })
    return filas
# ---------------------------------------------------------------- lo que cambia el administrador

def _minutos(valor):
    return f"{valor:.2f}" if valor is not None else ""


@transaction.atomic
def aprobar(operacion, minutos, motivo, usuario):
    """Regla 6: el aprobado manda sobre el tiempo fijo y la mediana; None lo quita. Queda en la bitácora."""
    anterior = operacion.minutos_aprobado
    operacion.minutos_aprobado = minutos
    operacion.aprobado_motivo = (motivo or "")[:200] if minutos else ""
    operacion.aprobado_por = usuario if minutos else ""
    operacion.aprobado_en = timezone.now() if minutos else None
    operacion.save(update_fields=["minutos_aprobado", "aprobado_motivo", "aprobado_por", "aprobado_en"])
    Bitacora.anotar(usuario, "Aprobar tiempo" if minutos else "Quitar aprobado", operacion,
                    _minutos(anterior), _minutos(minutos))
    recalcular_tareas(operacion)


@transaction.atomic
def guardar_tiempo_fijo(operacion, minutos, por_pedido, usuario):
    """Regla 7: None lo borra y vuelve a usarse la mediana. Queda en la bitácora."""
    fijo = getattr(operacion, "tiempo_fijo", None)
    unidad = lambda pedido: "por pedido" if pedido else "por pieza"
    anterior = f"{_minutos(fijo.minutos)} {unidad(fijo.por_pedido)}" if fijo else ""
    if minutos is None:
        if fijo:
            fijo.delete()
        nuevo = ""
    else:
        TiempoFijo.objects.update_or_create(operacion=operacion, defaults={"minutos": minutos, "por_pedido": por_pedido})
        nuevo = f"{_minutos(minutos)} {unidad(por_pedido)}"
    Bitacora.anotar(usuario, "Tiempo fijo", operacion, anterior, nuevo)
    recalcular_tareas(operacion)


@transaction.atomic
def agregar_al_catalogo(medicion, usuario):
    """Regla 3: crea la operación con esa madre y desde ese momento sus mediciones cuentan."""
    texto, madre = medicion.detallada_nueva.strip(), medicion.operacion_madre
    operacion = (madre.detalles.filter(nombre__iexact=texto).first()
                 or OperacionDetallada.objects.create(madre=madre, nombre=texto))
    _misma_operacion(medicion).update(operacion_detallada=operacion, detallada_nueva="")
    Bitacora.anotar(usuario, "Agregar NUEVA al catálogo", operacion, texto, str(operacion))
    recalcular(MedicionTiempo.objects.filter(operacion_detallada=operacion).first())
    return operacion