"""
Reglas de Designación diaria (versión 2, 18-nov-2026).
Las comparten la pantalla, la impresión, el Excel y Nuevo día para que siempre coincidan.
"""
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from core.models import Configuracion

from .models import DesignacionDia, ItemDesignacion, Maquina, Operario

# Ordenar (regla 8): solo cambia la vista
ORDENES = {
    "urgencia": ("Urgencia", "fecha de salida · pedido · paso"),
    "persona": ("Persona", "persona · pedido · paso"),
    "operacion": ("Operación", "madre · detallada · persona"),
    "maquina": ("Máquina", "máquina · madre · detallada"),
}

ESTADOS = {
    "hecha": ("Hecha", "estado-hecha"),
    "proceso": ("En proceso", "estado-proceso"),
    "espera": ("Espera paso anterior", "estado-espera"),
    "lista": ("Lista", "estado-lista"),
}

Q_ACTIVA = Q(designacion__cerrada=False, fecha_cierre__isnull=True, cerrada_al_archivar=False)


def sin_acentos(texto):
    texto = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------- jornada y tareas

def jornada_activa():
    """La jornada abierta más reciente. Si no hay ninguna, la de hoy."""
    jornada = DesignacionDia.objects.filter(cerrada=False).order_by("-fecha").first()
    if jornada:
        return jornada
    return DesignacionDia.objects.get_or_create(fecha=timezone.localdate())[0]


def tareas_activas():
    """Todo lo que no se ha archivado, no solo lo creado hoy (punto 1 de la pantalla)."""
    return (
        ItemDesignacion.objects.filter(Q_ACTIVA)
        .select_related(
            "quien", "pedido", "pedido__cliente", "partida", "maquina",
            "operacion_madre", "operacion_detallada__madre", "operacion_detallada__tiempo_fijo",
        )
        .prefetch_related("operacion_detallada__escalones", "pedido__partidas")
    )


def siguiente_jornada(actual, hoy=None):
    """El día que sigue (sin domingo). Si la jornada abierta es de días atrás, hoy."""
    hoy = hoy or timezone.localdate()
    if actual.fecha < hoy:
        return hoy
    siguiente = actual.fecha + timedelta(days=1)
    if siguiente.weekday() == 6:
        siguiente += timedelta(days=1)
    return siguiente


# ---------------------------------------------------------------- estado y marcas (reglas 3 y 4)

def _espera_paso_anterior(tarea, pendientes):
    """
    En su misma partida hay un paso menor sin ✓.
    El Empaquetar del pedido (tarea sin partida) espera a todas las demás tareas del pedido.
    """
    for otra in pendientes.get(tarea.pedido_id, ()):
        if otra.pk == tarea.pk:
            continue
        if not tarea.partida_id:
            return True
        if otra.partida_id == tarea.partida_id and otra.paso < tarea.paso:
            return True
    return False


def calcular_estado(tarea, pendientes):
    """Hecha · En proceso (manda sobre las otras dos) · Espera paso anterior · Lista."""
    if tarea.hecho:
        return "hecha"
    if tarea.lleva_hechas and tarea.piezas_hechas > 0:
        return "proceso"
    if tarea.pedido_id and _espera_paso_anterior(tarea, pendientes):
        return "espera"
    return "lista"


def producto_de(tarea):
    """Solo la descripción de su partida y cuál es; el Empaquetar dice "Todo el pedido"."""
    if not tarea.pedido_id:
        return tarea.descripcion_manual or "Para stock (ver Detalle)", ""
    partidas = list(tarea.pedido.partidas.all())
    if tarea.partida_id:
        if len(partidas) > 1:
            numero = next((i for i, p in enumerate(partidas, 1) if p.pk == tarea.partida_id), None)
            return tarea.partida.descripcion, f"partida {numero} de {len(partidas)}" if numero else ""
        return tarea.partida.descripcion, ""
    if len(partidas) > 1:
        return f"Todo el pedido ({len(partidas)} partidas)", ""
    return (partidas[0].descripcion if partidas else tarea.pedido.descripcion), ""


def preparar(tareas, maquinas=None):
    """Le pone a cada tarea su estado, producto, alerta y marcas de color (las calcula con TODAS)."""
    tareas = list(tareas)
    maquinas = list(maquinas if maquinas is not None else Maquina.objects.filter(activa=True))
    pendientes = defaultdict(list)
    for t in tareas:
        if not t.hecho and t.pedido_id:
            pendientes[t.pedido_id].append(t)

    opciones_por_madre = {}
    for t in tareas:
        clave = calcular_estado(t, pendientes)
        t.estado_clave = clave
        t.estado_texto, t.estado_clase = ESTADOS[clave]
        t.producto, t.partida_texto = producto_de(t)
        t.notas_pedido = t.pedido.notas if t.pedido_id else ""
        t.alerta_info = t.pedido.alerta_estado if t.pedido_id else None

        madre = t.operacion_madre
        if madre.pk not in opciones_por_madre:
            opciones_por_madre[madre.pk] = madre.opciones_maquina(maquinas)
        t.opciones_maquina = maquinas if t.es_especial else opciones_por_madre[madre.pk]

        # Marcas: avisan, no bloquean
        t.marca_maquina = ""
        if t.es_especial:
            pass  # acepta cualquier máquina: nunca rojo ni naranja
        elif not t.maquina_id:
            t.marca_maquina = "rojo"
        elif madre.tipos and t.maquina not in opciones_por_madre[madre.pk]:
            t.marca_maquina = "naranja"
        t.marca_operacion = t.aviso_material
        t.texto_busqueda = sin_acentos(" ".join(filter(None, [
            t.pedido.numero if t.pedido_id else "stock",
            t.pedido.cliente.nombre if t.pedido_id and t.pedido.cliente_id else "",
            t.producto, t.notas_pedido, t.quien.nombre if t.quien_id else "sin asignar",
            madre.nombre, t.operacion_detallada.nombre, t.maquina.nombre if t.maquina_id else "",
            t.detalle,
        ])))
    return tareas


# ---------------------------------------------------------------- orden (regla 8)

def _salida(t):
    return t.pedido.fecha_salida if t.pedido_id and t.pedido.fecha_salida else date.max


def _clave_urgencia(t):
    sin_pedido = not t.pedido_id
    return (sin_pedido, _salida(t), t.pedido.numero if t.pedido_id else "",
            t.partida_id is None, t.partida_id or 0, t.paso, t.pk)


def ordenar(tareas, orden):
    if orden == "persona":
        clave = lambda t: (t.quien_id is not None, sin_acentos(t.quien.nombre) if t.quien_id else "",  # noqa: E731
                           t.pedido.numero if t.pedido_id else "~", t.paso, t.pk)
    elif orden == "operacion":
        clave = lambda t: (sin_acentos(t.operacion_madre.nombre), sin_acentos(t.operacion_detallada.nombre),  # noqa: E731
                           t.quien_id is not None, sin_acentos(t.quien.nombre) if t.quien_id else "", t.pk)
    elif orden == "maquina":
        clave = lambda t: (t.maquina_id is not None, sin_acentos(t.maquina.nombre) if t.maquina_id else "",  # noqa: E731
                           sin_acentos(t.operacion_madre.nombre), sin_acentos(t.operacion_detallada.nombre), t.pk)
    else:
        clave = _clave_urgencia
    return sorted(tareas, key=clave)


# ---------------------------------------------------------------- tarjetas y carga por persona (regla 5)

def turno_minutos():
    return Configuracion.actual().turno_minutos


def tarjetas(tareas):
    """De todo el día: el buscador, el orden y ocultar palomeadas no las cambian."""
    asignadas = [t for t in tareas if t.quien_id]
    sin_asignar = [t for t in tareas if not t.quien_id]
    asignados = sum(t.minutos for t in asignadas)
    hechos = sum(t.min_hechos_hoy for t in asignadas)
    return {
        "tareas": len(tareas),
        "con_check": sum(1 for t in tareas if t.hecho),
        "en_proceso": sum(1 for t in tareas if t.estado_clave == "proceso"),
        "sin_tiempo": sum(1 for t in tareas if t.sin_tiempo),
        "min_asignados": asignados,
        "sin_asignar_tareas": len(sin_asignar),
        "sin_asignar_min": sum(t.minutos for t in sin_asignar),
        "min_hechos": hechos,
        "avance": round(hechos * 100 / asignados) if asignados else 0,
    }


def carga_por_persona(tareas, turno):
    """Todas las personas activas, con o sin tareas. Libres = turno − asignados (rojo si es negativo)."""
    filas = []
    for operario in Operario.objects.filter(activo=True).order_by("orden", "nombre"):
        suyas = [t for t in tareas if t.quien_id == operario.pk]
        asignados = sum(t.minutos for t in suyas)
        hechos = sum(t.min_hechos_hoy for t in suyas)
        filas.append({
            "operario": operario,
            "asignados": asignados,
            "hechos": hechos,
            "libres": turno - asignados,
            "pct": min(round(hechos * 100 / asignados), 100) if asignados else 0,
            "tareas": len(suyas),
        })
    return filas


# ---------------------------------------------------------------- Nuevo día (regla 9)

def resumen_nuevo_dia(tareas):
    """Qué va a pasar con cada grupo de tareas antes de cerrar."""
    con_check = [t for t in tareas if t.hecho]
    con_avance = [t for t in tareas if t.tiene_avance]
    sin_avance = [t for t in tareas if not t.hecho and not t.tiene_avance]
    return {
        "con_check": con_check,
        "con_avance": con_avance,
        "sin_avance": sin_avance,
        "con_min_real": [t for t in tareas if t.min_real],
    }
