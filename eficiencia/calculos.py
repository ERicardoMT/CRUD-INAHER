"""Cálculos de Eficiencia. Los usan las pantallas, las tarjetas y el Excel para que siempre coincidan."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum

from designaciones.models import ItemDesignacion, OperacionDetallada, Operario, clase_eficiencia

from .models import CambioEstandar

# Filtros de Tareas del día: parámetro de la dirección → campo de la tarea
FILTROS = {
    "quien": "quien_id",
    "madre": "operacion_madre_id",
    "detallada": "operacion_detallada_id",
    "maquina": "maquina_id",
}

# Minutos del día: vista → (título de la columna, nota al pie)
VER_POR = {
    "operador": ("Operador", "Solo minutos estándar de Designación diaria. De aquí no se calcula eficiencia. "
                             "Min libres en rojo y negativo = ya no le cabe en el turno."),
    "maquina": ("Máquina", "Solo máquinas con tareas ese día. Tarea manual no es una máquina: no lleva minutos "
                           "libres. De aquí no se calcula eficiencia."),
    "madre": ("Operación madre", "Solo operaciones con tareas ese día. Una operación no tiene turno: no lleva "
                                 "minutos libres. De aquí no se calcula eficiencia."),
    "detallada": ("Operación detallada", "Solo operaciones con tareas ese día. Debajo de cada una, su operación "
                                         "madre. De aquí no se calcula eficiencia."),
}

ESTADOS = {
    "OK": ("OK", "status-terminado"),
    "FUERA": ("FUERA", "status-detenido"),
    "FALTAN": ("FALTAN MEDIDAS", "status-neutral"),
    "NUEVO": ("NUEVO", "status-proceso"),
}


def tono_eficiencia(pct):
    return {"efic-ok": "green", "efic-media": "amber", "efic-baja": "red"}.get(clase_eficiencia(pct), "gray")


# ---------------------------------------------------------------- tareas del día

def tareas_del_dia(dia, filtros=None):
    """Las tareas de Designación diaria de ese día, tal cual (incluye jornadas ya archivadas)."""
    tareas = (
        ItemDesignacion.objects.filter(designacion__fecha=dia, cerrada_al_archivar=False)
        .select_related("quien", "pedido", "operacion_madre", "operacion_detallada", "maquina")
        .order_by("quien__orden", "quien__nombre", "paso", "orden", "pk")
    )
    return tareas.filter(**(filtros or {}))


def eficiencia_de(tareas):
    """Min estándar ÷ min real, solo sobre las tareas medidas que tienen estándar."""
    validas = [t for t in tareas if t.eficiencia is not None]
    real = sum(t.min_real for t in validas)
    return (round(sum(t.minutos for t in validas) * 100 / real) if real else None), len(validas)


def tarjetas_dia(tareas, fuera, url_fuera):
    medidas = sum(1 for t in tareas if t.min_real)
    pct, validas = eficiencia_de(tareas)
    return [
        {"titulo": "Tareas del día", "valor": len(tareas), "texto": "de Designación",
         "tono": "blue", "icono": "bi-list-check", "activo": True},
        {"titulo": "Con tiempo real", "valor": medidas, "texto": "medidas este día",
         "tono": "gray", "icono": "bi-stopwatch"},
        {"titulo": "Eficiencia del día", "valor": f"{pct} %" if pct is not None else "—",
         "texto": f"sobre {validas} medida(s) con estándar", "tono": tono_eficiencia(pct), "icono": "bi-speedometer2"},
        {"titulo": "Operaciones fuera", "valor": fuera, "texto": "estándar a revisar · ver Por operación",
         "tono": "red", "icono": "bi-exclamation-triangle", "url": url_fuera},
    ]


# ---------------------------------------------------------------- por operación

def resumen_operaciones(desde, hasta, config, operacion_id=None):
    """Por operación detallada: estándar contra el promedio real (min/pz) de las tareas medidas en el periodo."""
    medidas = ItemDesignacion.objects.filter(min_real__isnull=False)
    if desde:
        medidas = medidas.filter(designacion__fecha__gte=desde)
    if hasta:
        medidas = medidas.filter(designacion__fecha__lte=hasta)
    if operacion_id:
        medidas = medidas.filter(operacion_detallada_id=operacion_id)

    filas = (
        medidas.values(
            "operacion_detallada", "operacion_detallada__nombre",
            "operacion_detallada__madre__nombre", "operacion_detallada__minutos_estandar",
        )
        .annotate(medidas=Count("pk"), real_total=Sum("min_real"), piezas=Sum("cantidad"), estandar_total=Sum("minutos"))
        .order_by("operacion_detallada__madre__nombre", "operacion_detallada__nombre")
    )
    tolerancia = Decimal(config.tolerancia_pct) / 100
    resultado = []
    for f in filas:
        estandar = f["operacion_detallada__minutos_estandar"] or None
        real = (f["real_total"] / f["piezas"]).quantize(Decimal("0.01")) if f["piezas"] else None
        diferencia = (real - estandar) / estandar if estandar and real else None

        if f["medidas"] < config.minimo_medidas:
            estado = "FALTAN"
        elif not estandar:
            estado = "NUEVO"
        else:
            estado = "OK" if abs(diferencia) <= tolerancia else "FUERA"

        resultado.append({
            "id": f["operacion_detallada"],
            "nombre": f["operacion_detallada__nombre"],
            "madre": f["operacion_detallada__madre__nombre"],
            "estandar": estandar,
            "real": real,
            "pzas_hora": round(60 / real) if real else None,
            "medidas": f["medidas"],
            "diferencia": round(diferencia * 100) if diferencia is not None else None,
            "estado": estado,
            "estado_texto": ESTADOS[estado][0],
            "estado_clase": ESTADOS[estado][1],
            "puede_actualizar": estado in ("FUERA", "NUEVO") and bool(real),
            "estandar_total": f["estandar_total"],
            "real_total": f["real_total"],
        })
    return resultado


def tarjetas_periodo(filas, config, hoy):
    medidas = sum(f["medidas"] for f in filas)
    semana = ItemDesignacion.objects.filter(
        min_real__isnull=False, designacion__fecha__gte=hoy - timedelta(days=hoy.weekday())
    ).count()
    listas = sum(1 for f in filas if f["medidas"] >= config.minimo_medidas)
    fuera = sum(1 for f in filas if f["estado"] == "FUERA")
    con_estandar = [f for f in filas if f["estandar"]]
    real = sum(f["real_total"] for f in con_estandar)
    pct = round(sum(f["estandar_total"] for f in con_estandar) * 100 / real) if real else None
    return [
        {"titulo": "Tareas medidas", "valor": medidas, "texto": f"en el periodo · {semana} esta semana",
         "tono": "blue", "icono": "bi-stopwatch", "activo": True},
        {"titulo": "Operaciones medidas",
         "valor": f"{len(filas)} de {OperacionDetallada.objects.filter(activa=True).count()}",
         "texto": f"{listas} con {config.minimo_medidas} o más (listas)", "tono": "gray", "icono": "bi-diagram-3"},
        {"titulo": "Fuera de tolerancia", "valor": fuera,
         "texto": f"real ≠ estándar más de {config.tolerancia_pct} %", "tono": "red", "icono": "bi-exclamation-triangle"},
        {"titulo": "Eficiencia promedio", "valor": f"{pct} %" if pct is not None else "—",
         "texto": "sobre tareas medidas", "tono": tono_eficiencia(pct), "icono": "bi-speedometer2"},
    ]


@transaction.atomic
def aplicar_estandar(operacion, nuevo, medidas, usuario):
    """Cambia el estándar en el catálogo. Lo vigente recalcula sus minutos; lo cerrado o archivado conserva los suyos."""
    CambioEstandar.objects.create(
        operacion=operacion, anterior=operacion.minutos_estandar, nuevo=nuevo, medidas=medidas, usuario=usuario,
    )
    operacion.minutos_estandar = nuevo
    operacion.save(update_fields=["minutos_estandar"])
    vigentes = ItemDesignacion.objects.filter(
        operacion_detallada=operacion, designacion__cerrada=False, fecha_cierre__isnull=True,
    ).exclude(pedido__archivado=True)
    for tarea in vigentes:
        tarea.minutos = round(nuevo * tarea.cantidad)
        tarea.save(update_fields=["minutos"])


# ---------------------------------------------------------------- minutos del día

def _grupo(nombre, sub="", con_turno=False):
    return {"nombre": nombre, "sub": sub, "con_turno": con_turno, "tareas": 0, "piezas": 0, "ocupados": 0, "hechos": 0}


def _renglon(tarea, ver):
    """A qué renglón va la tarea: (clave, nombre, operación madre debajo, ¿lleva turno?)."""
    if ver == "operador":
        if not tarea.quien_id:
            return "sin", "Sin asignar", "", False
        return tarea.quien_id, tarea.quien.nombre, "", True
    if ver == "maquina":
        if not tarea.maquina_id:
            return "sin", "Sin máquina", "", False
        return tarea.maquina_id, tarea.maquina.nombre, "", not tarea.maquina.es_manual
    if ver == "madre":
        return tarea.operacion_madre_id, tarea.operacion_madre.nombre, "", False
    return tarea.operacion_detallada_id, tarea.operacion_detallada.nombre, tarea.operacion_madre.nombre, False


def minutos_por(tareas, ver, turno):
    """Las mismas tareas del día agrupadas por operador, máquina u operación. Los totales cuadran en las 4 vistas."""
    grupos = {}
    if ver == "operador":  # todos los operadores activos, aunque no tengan tareas
        for operario in Operario.objects.filter(activo=True).order_by("orden", "nombre"):
            grupos[operario.pk] = _grupo(operario.nombre, con_turno=True)

    for tarea in tareas:
        clave, nombre, sub, con_turno = _renglon(tarea, ver)
        grupo = grupos.setdefault(clave, _grupo(nombre, sub, con_turno))
        grupo["tareas"] += 1
        grupo["piezas"] += tarea.cantidad
        grupo["ocupados"] += tarea.minutos
        if tarea.hecho:
            grupo["hechos"] += tarea.minutos

    filas = list(grupos.values())
    if ver != "operador":
        filas.sort(key=lambda g: (g["nombre"].startswith("Sin "), g["nombre"].lower()))
    for g in filas:
        g["restantes"] = g["ocupados"] - g["hechos"]
        g["libres"] = turno - g["ocupados"] if g["con_turno"] else None
        g["pct"] = round(g["ocupados"] * 100 / turno) if g["con_turno"] and turno else None
        g["ancho"] = min(g["pct"] or 0, 100)
    total = {c: sum(g[c] for g in filas) for c in ("tareas", "piezas", "ocupados", "hechos", "restantes")}
    return filas, total
