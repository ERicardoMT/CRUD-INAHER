from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def respuesta_excel(nombre, titulo, subtitulo, encabezados, filas, anchos, columnas_fecha=()):
    """Excel con título, encabezado congelado y autofiltro. columnas_fecha: índices (desde 0) con fecha."""
    ahora = timezone.localtime()
    libro = Workbook()
    hoja = libro.active
    hoja.title = titulo[:31]

    hoja.append([f"INAHER · {titulo}"])
    hoja["A1"].font = Font(bold=True, size=14)
    hoja.append([f"Exportado: {ahora:%d/%m/%Y %H:%M} · {subtitulo}"])
    hoja.append([])
    hoja.append(encabezados)
    fila_encabezado = hoja.max_row
    for celda in hoja[fila_encabezado]:
        celda.font = Font(bold=True)
        celda.fill = PatternFill("solid", fgColor="E8EEF6")

    for fila in filas:
        hoja.append(fila)

    for fila in hoja.iter_rows(min_row=fila_encabezado + 1):
        for i in columnas_fecha:
            fila[i].number_format = "DD/MM/YYYY"
        for celda in fila:
            celda.alignment = Alignment(vertical="top", wrap_text=True)

    for i, ancho in enumerate(anchos, start=1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.freeze_panes = hoja.cell(row=fila_encabezado + 1, column=1)
    hoja.auto_filter.ref = f"A{fila_encabezado}:{get_column_letter(len(encabezados))}{hoja.max_row}"

    respuesta = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}_{ahora:%Y%m%d_%H%M}.xlsx"'
    libro.save(respuesta)
    return respuesta
