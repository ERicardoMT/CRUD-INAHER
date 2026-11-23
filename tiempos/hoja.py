"""El libro de Frida y Axel (regla 12): columnas A a R con encabezados en la fila 5. Lo comparten exportar e importar."""
from django.utils import timezone

COLUMNAS = [
    "Fecha", "Quién midió", "Operador", "Modelo", "Op. madre", "Op. detallada", "Máquina", "Medida",
    "Fierro / Inox", "1 pieza", "Muestra: piezas", "Muestra: tiempo total", "Teórico", "% dif.",
    "Min/pz", "Foto", "Observaciones", "Alerta",
]
MATERIAL_HOJA = {"F": "F", "I": "I", "FI": "F y I"}


def hoja_mediciones(mediciones, subtitulo, liga_foto):
    """Mismo acomodo que el libro; a la derecha, Origen y Fecha de captura (12h)."""
    filas = [[
        m.fecha, m.quien_midio, m.operador.nombre if m.operador_id else "",
        ", ".join(x["modelo"] for x in m.modelos) or m.modelo_pieza,
        m.operacion_madre.nombre if m.operacion_madre_id else "", m.operacion_nombre,
        m.maquina.nombre if m.maquina_id else "", m.medida, MATERIAL_HOJA.get(m.material, ""),
        m.tiempo_1_pieza, m.muestra_piezas, m.muestra_tiempo_total, m.teorico, m.pct_dif, m.min_pz,
        liga_foto(m), m.observaciones, m.alerta_texto,
        m.origen_texto, timezone.localtime(m.fecha_creacion).replace(tzinfo=None),
    ] for m in mediciones]
    return {
        "titulo": "Estudio de tiempos", "subtitulo": subtitulo,
        "encabezados": COLUMNAS + ["Origen", "Fecha de captura"], "filas": filas,
        "anchos": [10, 12, 12, 14, 26, 40, 22, 10, 8, 8, 9, 10, 9, 8, 9, 30, 30, 18, 20, 16],
        "columnas_fecha": (0, 19), "fila_encabezados": 5,
    }

def hoja_operaciones(filas):
    """Tiempos por operación (12h): de consulta, no se importa."""
    return {
        "titulo": "Tiempos por operación",
        "subtitulo": "una fila por operación del catálogo · de consulta, no se importa",
        "encabezados": ["Op. madre", "Op. detallada", "Muestras válidas", "Mediciones", "Mediana", "Tiempo fijo",
                        "Aprobado", "Usa HOY", "Unidad", "Estado", "Tareas activas"],
        "filas": [[
            f["operacion"].madre.nombre, f["operacion"].nombre, f["validas"], f["total"], f["mediana"],
            f["fijo"].minutos if f["fijo"] else ("por escalones" if f["escalones"] else None),
            f["operacion"].minutos_aprobado, f["usa_hoy"],
            "min por pedido" if f["operacion"].es_por_pedido else "min por pieza", f["fuente"]["texto"], f["tareas"],
        ] for f in filas],
        "anchos": [26, 44, 10, 11, 10, 12, 10, 10, 15, 22, 10],
    }

def hoja_empaquetar(filas):
    return {
        "titulo": "Empaquetar por modelo",
        "subtitulo": "con dos o más pedidos del mismo modelo se muestra la mediana",
        "encabezados": ["Modelo", "Pedidos medidos", "Piezas", "Min por pedido", "Min por pieza"],
        "filas": [[e["modelo"], e["pedidos"], e["piezas"], e["por_pedido"], e["por_pieza"]] for e in filas],
        "anchos": [20, 14, 12, 14, 14],
    }