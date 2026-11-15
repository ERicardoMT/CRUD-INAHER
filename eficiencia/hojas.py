"""Hojas de Excel de Eficiencia: las usa Exportar de cada pestaña."""
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
        "encabezados": ["Operación madre", "Operación detallada", "Estándar min/pz", "Real promedio min/pz",
                        "Pzas/hora real", "Veces medida", "Diferencia %", "Estado"],
        "filas": [
            [f["madre"], f["nombre"], f["estandar"], f["real"], f["pzas_hora"], f["medidas"],
             f["diferencia"], f["estado_texto"]]
            for f in filas
        ],
        "anchos": [26, 40, 14, 16, 12, 12, 12, 16],
    }


def hojas_minutos(tareas, subtitulo, turno):
    """Las 4 vistas, cada una en su hoja, sin importar cuál esté elegida en pantalla (pág. 8)."""
    hojas = []
    for ver, (nombre, _) in calculos.VER_POR.items():
        grupos, total = calculos.minutos_por(tareas, ver, turno)
        filas = [[g["nombre"], g["sub"], g["tareas"], g["piezas"], g["ocupados"], g["libres"], g["hechos"],
                  g["restantes"], g["pct"]] for g in grupos]
        filas.append(["TOTAL", "", total["tareas"], total["piezas"], total["ocupados"], None,
                      total["hechos"], total["restantes"], None])
        hojas.append({
            "titulo": f"Minutos · {nombre}",
            "subtitulo": subtitulo,
            "encabezados": [nombre, "Operación madre", "Tareas", "Piezas", "Min ocupados", "Min libres",
                            "Min hechos", "Min restantes", "% del turno"],
            "filas": filas,
            "anchos": [30, 26, 8, 8, 12, 10, 11, 12, 11],
        })
    return hojas
