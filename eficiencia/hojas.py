"""Hojas de Excel de Eficiencia: las usan Exportar de cada pestaña y Exportar todo."""
from archivo.views import _texto_rango

from . import calculos


def hoja_tareas(tareas, dia):
    return {
        "titulo": "Tareas del día",
        "subtitulo": f"día {dia:%d/%m/%Y}",
        "encabezados": ["Fecha", "Quién", "# P", "Paso", "Operación madre", "Operación detallada", "Máquina",
                        "Cant", "Min est", "Min real", "Efic %", "Pzas/hora", "✓"],
        "filas": [
            [dia, t.quien.nombre, t.pedido.numero if t.pedido else "stock", t.paso, t.operacion_madre.nombre,
             t.operacion_detallada.nombre, t.maquina.nombre if t.maquina else "", t.cantidad, t.minutos,
             t.min_real, t.eficiencia, t.pzas_hora, "✓" if t.hecho else ""]
            for t in tareas
        ],
        "anchos": [11, 14, 10, 6, 26, 36, 22, 7, 9, 9, 8, 10, 5],
        "columnas_fecha": (0,),
    }


def hoja_operaciones(filas, desde, hasta):
    return {
        "titulo": "Por operación",
        "subtitulo": f"medidas {_texto_rango(desde, hasta)}",
        "encabezados": ["Operación madre", "Operación detallada", "Unidad", "Estándar", "Real promedio",
                        "Pzas/hora real", "Veces medida", "Diferencia %", "Estado"],
        "filas": [
            [f["madre"], f["nombre"], f["unidad"], f["estandar"], f["real"], f["pzas_hora"], f["medidas"],
             f["diferencia"], f["estado_texto"]]
            for f in filas
        ],
        "anchos": [26, 40, 11, 10, 13, 12, 12, 12, 16],
    }


def hojas_minutos(tareas, subtitulo, turno, prefijo="Minutos", por_piezas=False):
    """Las 4 vistas, cada una en su hoja, sin importar cuál esté elegida en pantalla."""
    hojas = []
    for ver, (nombre, _) in calculos.VER_POR.items():
        grupos, total = calculos.minutos_por(tareas, ver, turno, por_piezas)
        filas = [[g["nombre"], g["sub"], g["tareas"], g["piezas"], g["ocupados"], g["libres"], g["hechos"],
                  g["restantes"], g["pct"]] for g in grupos]
        filas.append(["TOTAL", "", total["tareas"], total["piezas"], total["ocupados"], None,
                      total["hechos"], total["restantes"], None])
        hojas.append({
            "titulo": f"{prefijo} · {nombre}",
            "subtitulo": subtitulo,
            "encabezados": [nombre, "Operación madre", "Tareas", "Piezas", "Min ocupados", "Min libres",
                            "Min hechos", "Min restantes", "% del turno"],
            "filas": filas,
            "anchos": [30, 26, 8, 8, 12, 10, 11, 12, 11],
        })
    return hojas


def hoja_carga(carga, capacidad_dia):
    return {
        "titulo": "Carga de la semana",
        "subtitulo": f"capacidad {capacidad_dia:,} min por día hábil",
        "encabezados": ["Sale", "Pedidos", "Min pendientes", "Min acumulados", "Capacidad acumulada", "¿Cabe?"],
        "filas": [[r["sale"], r["pedidos"], r["pendientes"], r["acumulados"], r["capacidad"], r["cabe"]] for r in carga],
        "anchos": [14, 9, 14, 15, 18, 24],
        "columnas_fecha": (0,),
    }


def hoja_personas(personas, periodo):
    return {
        "titulo": "Eficiencia por persona",
        "subtitulo": f"periodo {periodo}",
        "encabezados": ["Persona", "Tareas medidas", "Min estándar", "Min real", "Eficiencia %"],
        "filas": [[p["nombre"], p["tareas"], p["estandar"], p["real"], p["pct"]] for p in personas],
        "anchos": [18, 14, 13, 11, 12],
    }


def hoja_costos(costos, hay_tarifas):
    return {
        "titulo": "Costo por pedido",
        "subtitulo": "sin material" if hay_tarifas else "sin tarifas capturadas",
        "encabezados": ["Pedido", "Descripción", "Min del pedido", "Costo mano de obra", "Costo máquina", "Costo MO + máquina"],
        "filas": [[c["numero"], c["descripcion"], c["minutos"], c["mano_obra"], c["maquina"], c["total"]] for c in costos],
        "anchos": [10, 40, 13, 17, 14, 18],
    }


def hoja_faltan(faltan, total):
    return {
        "titulo": "Faltan de medir",
        "subtitulo": f"{len(faltan)} de {total} operaciones no tienen tiempo",
        "encabezados": ["Operación detallada sin tiempo", "Operación madre", "Tareas hoy"],
        "filas": [[f["nombre"], f["madre"], f["hoy"] or None] for f in faltan],
        "anchos": [44, 30, 11],
    }
