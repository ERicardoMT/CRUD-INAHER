"""Cálculos de Eficiencia. Los usan las pantallas, las tarjetas y el Excel para que siempre coincidan."""
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, F, Sum
from django.db.models.functions import Coalesce

from designaciones.models import (
    Escalon, ItemDesignacion, Maquina, OperacionDetallada, Operario, TiempoFijo, clase_eficiencia,
)
from pedidos.models import Q_ITEM_VIGENTE, Pedido

from .calendario import Calendario
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


def rangos_periodo(hoy):
    """Un solo control de periodo (abre en Este mes). Escribir una fecha pasa a "fechas a mano"."""
    inicio_mes = hoy.replace(day=1)
    fin_mes_pasado = inicio_mes - timedelta(days=1)
    return {
        "hoy": ("Hoy", hoy, hoy),
        "semana": ("Esta semana", hoy - timedelta(days=hoy.weekday()), hoy),
        "mes": ("Este mes", inicio_mes, hoy),
        "mes_pasado": ("Mes pasado", fin_mes_pasado.replace(day=1), fin_mes_pasado),
        "30": ("Últimos 30 días", hoy - timedelta(days=29), hoy),
        "anio": ("Este año", hoy.replace(month=1, day=1), hoy),
    }


def tono_eficiencia(pct):
    return {"efic-ok": "green", "efic-media": "amber", "efic-baja": "red"}.get(clase_eficiencia(pct), "gray")


def ids_con_tiempo_fijo(solo_por_pedido=False):
    """Operaciones con tiempo fijo o escalones. solo_por_pedido: las que no se multiplican por la cantidad."""
    fijos = TiempoFijo.objects.all()
    if solo_por_pedido:
        fijos = fijos.filter(por_pedido=True)
    return set(fijos.values_list("operacion_id", flat=True)) | set(Escalon.objects.values_list("operacion_id", flat=True))


# ---------------------------------------------------------------- tareas del día

def tareas_del_dia(dia, filtros=None):
    """Las tareas de Designación diaria de ese día, tal cual (incluye jornadas ya archivadas)."""
    tareas = (
        ItemDesignacion.objects.filter(designacion__fecha=dia, cerrada_al_archivar=False)
        .select_related("quien", "pedido", "operacion_madre", "operacion_detallada__tiempo_fijo", "maquina")
        .prefetch_related("operacion_detallada__escalones")
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
    """
    Estándar contra el promedio real de las tareas medidas en el periodo.
    Normal: min/pz. Por pedido (Empaquetar, Contar y revisar): promedio de Min est contra promedio de Min real.
    """
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
    por_pedido = ids_con_tiempo_fijo(solo_por_pedido=True)
    tolerancia = Decimal(config.tolerancia_pct) / 100
    centavos = Decimal("0.01")
    resultado = []
    for f in filas:
        es_por_pedido = f["operacion_detallada"] in por_pedido
        if es_por_pedido:
            estandar = (Decimal(f["estandar_total"]) / f["medidas"]).quantize(centavos) or None
            real = (f["real_total"] / f["medidas"]).quantize(centavos)
        else:
            estandar = f["operacion_detallada__minutos_estandar"] or None
            real = (f["real_total"] / f["piezas"]).quantize(centavos) if f["piezas"] else None
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
            "por_pedido": es_por_pedido,
            "unidad": "min/pedido" if es_por_pedido else "min/pz",
            "estandar": estandar,
            "real": real,
            "pzas_hora": round(60 / real) if real and not es_por_pedido else None,
            "medidas": f["medidas"],
            "diferencia": round(diferencia * 100) if diferencia is not None else None,
            "estado": estado,
            "estado_texto": ESTADOS[estado][0],
            "estado_clase": ESTADOS[estado][1],
            # El tiempo por pedido se cambia en la tabla de tiempos fijos, no en el estudio
            "puede_actualizar": estado in ("FUERA", "NUEVO") and bool(real) and not es_por_pedido,
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
        tarea.minutos = operacion.minutos_para(tarea.cantidad)
        tarea.save(update_fields=["minutos"])


# ---------------------------------------------------------------- minutos del día y producción

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


def minutos_por(tareas, ver, turno, por_piezas=False):
    """
    Las mismas tareas agrupadas por operador, máquina u operación. Los totales cuadran en las 4 vistas.
    por_piezas: de más a menos piezas (Producción del periodo).
    """
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
    if por_piezas:
        filas.sort(key=lambda g: (g["nombre"].startswith("Sin "), -g["piezas"], g["nombre"].lower()))
    elif ver != "operador":
        filas.sort(key=lambda g: (g["nombre"].startswith("Sin "), g["nombre"].lower()))
    for g in filas:
        g["restantes"] = g["ocupados"] - g["hechos"]
        g["libres"] = turno - g["ocupados"] if g["con_turno"] and turno else None
        g["pct"] = round(g["ocupados"] * 100 / turno) if g["con_turno"] and turno else None
        g["ancho"] = min(g["pct"] or 0, 100)
    total = {c: sum(g[c] for g in filas) for c in ("tareas", "piezas", "ocupados", "hechos", "restantes")}
    return filas, total


# ---------------------------------------------------------------- Dirección (solo administración)

def _carga(sale, es_dia=False):
    return {"sale": sale, "es_dia": es_dia, "pedidos": 0, "pendientes": 0, "acumulados": 0,
            "capacidad": None, "cabe": "", "cabe_clase": ""}


def carga_semana(hoy, config, calendario):
    """Minutos pendientes de los pedidos activos contra la capacidad (hoy y los 9 días hábiles siguientes)."""
    capacidad_dia = config.personas_en_planta * config.turno_minutos
    renglones = {"atrasados": _carga("Atrasados")}
    renglones.update({dia: _carga(dia, es_dia=True) for dia in calendario.dias_de_carga(hoy)})
    renglones["despues"] = _carga("Después")

    for pedido in Pedido.objects.activos().con_minutos().filter(min_restante__gt=0):
        salida = pedido.fecha_salida
        if not salida:
            clave = "despues"
        elif salida < hoy:
            clave = "atrasados"
        else:
            # Fin de semana o festivo cuenta en el siguiente día hábil
            dia = salida if salida == hoy else calendario.siguiente_habil(salida)
            clave = dia if dia in renglones else "despues"
        renglones[clave]["pedidos"] += 1
        renglones[clave]["pendientes"] += pedido.min_restante

    filas = list(renglones.values())
    acumulado = 0
    for numero, fila in enumerate(filas):  # "Atrasados" es el 0, así hoy es el día 1
        acumulado += fila["pendientes"]
        fila["acumulados"] = acumulado
        if fila["es_dia"]:
            fila["capacidad"] = capacidad_dia * numero
            sobran = fila["capacidad"] - acumulado
            fila["cabe"] = f"Cabe · sobran {sobran:,}" if sobran >= 0 else f"NO CABE · faltan {-sobran:,}"
            fila["cabe_clase"] = "cabe-si" if sobran >= 0 else "cabe-no"
    return filas, capacidad_dia


def eficiencia_por_persona(desde, hasta):
    """Un renglón por operador activo: tareas del periodo con minuto real y con estándar."""
    sumas = {
        f["quien"]: f for f in ItemDesignacion.objects.filter(
            designacion__fecha__range=(desde, hasta), min_real__isnull=False, minutos__gt=0,
        ).values("quien").annotate(tareas=Count("pk"), estandar=Sum("minutos"), real=Sum("min_real"))
    }
    filas = []
    for operario in Operario.objects.filter(activo=True).order_by("orden", "nombre"):
        f = sumas.get(operario.pk, {})
        real = f.get("real") or 0
        pct = round(f["estandar"] * 100 / real) if real else None
        filas.append({"nombre": operario.nombre, "tareas": f.get("tareas", 0), "estandar": f.get("estandar", 0),
                      "real": real, "pct": pct, "clase": clase_eficiencia(pct)})
    return filas


def costos_por_pedido(pedidos):
    """
    Minutos estándar × tarifa por hora ÷ 60, de la persona y de la máquina de cada tarea (activas y archivadas).
    Sin tarifa suma cero. Si no hay ninguna tarifa capturada, las columnas quedan vacías.
    """
    hay_tarifas = (Operario.objects.filter(tarifa_hora__isnull=False).exists()
                   or Maquina.objects.filter(tarifa_hora__isnull=False).exists())
    pedidos = list(pedidos)
    dinero = DecimalField(max_digits=14, decimal_places=2)
    sumas = {
        f["pedido"]: f for f in ItemDesignacion.objects.filter(Q_ITEM_VIGENTE, pedido__in=pedidos)
        .exclude(cerrada_al_archivar=True, hecho=False)
        .values("pedido").annotate(
            minutos=Sum("minutos"),
            mano_obra=Sum(F("minutos") * F("quien__tarifa_hora"), output_field=dinero),
            maquina=Sum(F("minutos") * F("maquina__tarifa_hora"), output_field=dinero),
        )
    }
    filas = []
    for pedido in pedidos:
        f = sumas.get(pedido.pk, {})
        mano_obra = (f.get("mano_obra") or Decimal(0)) / 60 if hay_tarifas else None
        maquina = (f.get("maquina") or Decimal(0)) / 60 if hay_tarifas else None
        filas.append({
            "numero": pedido.numero, "descripcion": pedido.descripcion, "minutos": f.get("minutos") or 0,
            "mano_obra": mano_obra, "maquina": maquina,
            "total": mano_obra + maquina if hay_tarifas else None,
        })
    return filas, hay_tarifas


def faltan_de_medir(hoy):
    """Operaciones activas sin tiempo. Arriba, las que hoy están en Designación (suman cero minutos)."""
    activas = OperacionDetallada.objects.filter(activa=True)
    sin_tiempo = (activas.filter(minutos_estandar=0).exclude(pk__in=ids_con_tiempo_fijo())
                  .select_related("madre"))
    hoy_por_operacion = dict(
        ItemDesignacion.objects.filter(designacion__fecha=hoy, operacion_detallada__in=sin_tiempo)
        .values_list("operacion_detallada").annotate(n=Count("pk"))
    )
    filas = [{"nombre": d.nombre, "madre": d.madre.nombre, "hoy": hoy_por_operacion.get(d.pk, 0)} for d in sin_tiempo]
    filas.sort(key=lambda f: (-f["hoy"], f["madre"].lower(), f["nombre"].lower()))
    return filas, activas.count()


def tareas_terminadas(desde, hasta):
    """Terminadas en el periodo: con ✓, incluidas las de pedidos archivados como "ya se terminó"."""
    return (
        ItemDesignacion.objects.filter(hecho=True)
        .annotate(terminada=Coalesce("fecha_cierre", "designacion__fecha"))
        .filter(terminada__range=(desde, hasta))
        .select_related("quien", "operacion_madre", "operacion_detallada", "maquina")
    )


def datos_direccion(hoy, desde, hasta, config):
    """Todo lo de la pestaña Dirección. Lo comparten la pantalla y Exportar todo."""
    calendario = Calendario()
    carga, capacidad_dia = carga_semana(hoy, config, calendario)
    pedidos = Pedido.objects.activos().order_by(F("fecha_salida").asc(nulls_last=True), "numero")
    costos, hay_tarifas = costos_por_pedido(pedidos)
    faltan, total_operaciones = faltan_de_medir(hoy)
    dias_habiles = calendario.habiles_entre(desde, hasta)
    return {
        "carga": carga,
        "capacidad_dia": capacidad_dia,
        "personas": eficiencia_por_persona(desde, hasta),
        "costos": costos,
        "hay_tarifas": hay_tarifas,
        "faltan": faltan,
        "total_operaciones": total_operaciones,
        "tareas_produccion": list(tareas_terminadas(desde, hasta)),
        "dias_habiles": dias_habiles,
        "turno_periodo": config.turno_minutos * dias_habiles,
    }
