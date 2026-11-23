"""Lista de trabajo del día (módulo Por operación). La comparten la pantalla, la impresión y el Excel."""
from datetime import date
from itertools import groupby

from designaciones import reglas

MOSTRAR = {"todas": "Todas las tareas", "pendientes": "Solo pendientes (sin ✓)"}
ORDENES = {
    "operacion": "Por máquina y operación (juntar iguales)",
    "urgencia": "Por máquina y urgencia",
}
# Mismos colores que Designación diaria: rojo ATRASADO y SALE HOY, ámbar URGENTE, verde EN TIEMPO
CLASE_ALERTA = {
    "ATRASADO": "status-detenido",
    "SALE HOY": "status-detenido",
    "URGENTE": "status-proceso",
    "EN TIEMPO": "status-terminado",
}
SIN_MAQUINA = "Sin máquina"

def _orden_operacion(t):
    """Máquina, operación madre, operación detallada y persona: junta las operaciones iguales."""
    return (t.maquina_id is None, t.maquina_nombre.lower(), t.operacion_madre.nombre.lower(),
            t.operacion_detallada.nombre.lower(), t.quien.nombre.lower() if t.quien_id else "")


def _orden_urgencia(t):
    """Máquina, fecha de salida, pedido y paso: lo más urgente arriba, lo que no tiene pedido al final."""
    salida = t.pedido.fecha_salida if t.pedido and t.pedido.fecha_salida else date.max
    return (t.maquina_id is None, t.maquina_nombre.lower(), t.pedido_id is None, salida,
            t.pedido.numero if t.pedido else "", t.paso)


def lista_del_dia(filtros=None, mostrar="todas", orden="operacion"):
    """Las mismas tareas activas que Designación diaria, con sus mismos estados (regla 10)."""
    todas = reglas.preparar(reglas.tareas_activas())  # el estado se calcula con TODAS, aunque luego se filtren
    for t in todas:
        t.alerta_texto = t.alerta_info["texto"] if t.alerta_info else ""
        t.alerta_clase = CLASE_ALERTA.get(t.alerta_texto, "status-neutral")
        t.maquina_nombre = t.maquina.nombre if t.maquina else SIN_MAQUINA

    # Filtros de quien consulta: vacío = no filtra; con varios, la tarea debe cumplir todos
    filas = [
        t for t in todas
        if all(str(getattr(t, campo)) == valor for campo, valor in (filtros or {}).items())
        and (mostrar != "pendientes" or not t.hecho)
    ]
    filas.sort(key=_orden_urgencia if orden == "urgencia" else _orden_operacion)

    anterior = None
    for t in filas:  # el primer renglón de cada máquina va resaltado
        t.inicio_maquina = t.maquina_nombre != anterior
        anterior = t.maquina_nombre

    totales = {
        "piezas": sum(t.cantidad for t in filas),
        "faltan": sum(t.faltan for t in filas),
        "minutos": sum(t.minutos for t in filas),
        "hechos": sum(1 for t in filas if t.hecho),
    }
    return filas, totales


def por_maquina(filas):
    """Para imprimir: una hoja por máquina."""
    return [{"maquina": nombre, "filas": list(grupo)} for nombre, grupo in groupby(filas, key=lambda t: t.maquina_nombre)]


def tarjetas(totales):
    return [
        {"titulo": "Piezas", "valor": totales["piezas"], "texto": "suma de Cant",
         "tono": "blue", "icono": "bi-box-seam", "activo": True},
        {"titulo": "Faltan", "valor": totales["faltan"], "texto": "piezas por hacer",
         "tono": "amber", "icono": "bi-hourglass-split"},
        {"titulo": "Minutos", "valor": totales["minutos"], "texto": "minutos estándar",
         "tono": "gray", "icono": "bi-stopwatch"},
        {"titulo": "Hechos ✓", "valor": totales["hechos"], "texto": "tareas palomeadas",
         "tono": "green", "icono": "bi-check2-square"},
    ]


def _numero(texto):
    """En Excel, el # de pedido como número si es solo dígitos."""
    return int(texto) if texto and texto.isdigit() else texto


def hoja_excel(filas, dia):
    return {
        "titulo": "Por operación",
        "subtitulo": f"tareas de hoy {dia:%d/%m/%Y} · lista completa, sin filtros de pantalla",
        "encabezados": ["Quién", "# Pedido", "Paso", "Producto", "Op. madre", "Op. detallada", "Máquina", "Detalle",
                        "Cant", "Min", "✓", "Hechas", "Faltan", "Fecha salida", "Alerta", "Estado"],
        "filas": [
            [t.quien.nombre if t.quien_id else "sin asignar", _numero(t.pedido.numero) if t.pedido else "", t.paso or None,
             " · ".join(filter(None, [t.producto, t.partida_texto])),
             t.operacion_madre.nombre, t.operacion_detallada.nombre, t.maquina_nombre, t.detalle,
             t.cantidad, t.minutos, "✓" if t.hecho else "", t.hechas, t.faltan,
             t.pedido.fecha_salida if t.pedido else None, t.alerta_texto, t.estado_texto]
            for t in filas
        ],
        "anchos": [12, 10, 6, 34, 24, 34, 22, 18, 7, 7, 4, 8, 8, 12, 12, 20],
        "columnas_fecha": (13,),
    }
