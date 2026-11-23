"""
Regla 12 · Importar el libro de Frida y Axel (o un Excel exportado de aquí: es el mismo acomodo).
revisar() no guarda nada: arma el resumen de la ventana (12c). cargar() guarda todo o nada.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from designaciones.models import MADRE_EMPAQUETAR, Maquina, NombreAnterior, OperacionDetallada, OperacionMadre, Operario
from designaciones.reglas import sin_acentos

from . import calculos
from .hoja import COLUMNAS
from .models import VARIOS_MODELOS, Bitacora, Importacion, MedicionBorrada, MedicionTiempo, segundos_de, texto_mmss

HOJA = "Estudio de tiempos"
FILA_ENCABEZADOS = 5
# Palabra que debe traer cada encabezado, de A a R (sin acentos ni mayúsculas).
# Si el libro real dice otra cosa en alguna columna, solo se cambia aquí.
ENCABEZADOS = [
    "fecha", "midio", "operador", "modelo", "madre", "detallada", "maquina", "medida", "inox",
    "pieza", "pieza", "total", "teorico", "dif", "min", "foto", "observ", "alerta",
]
MATERIALES = {"f": "F", "fierro": "F", "i": "I", "inox": "I", "f y i": "FI", "fyi": "FI", "f/i": "FI", "fierro e inox": "FI"}


def _norma(texto):
    """Para comparar nombres: sin acentos, sin mayúsculas y sin espacios de más."""
    return sin_acentos(" ".join(str(texto or "").split()))


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).split())


def _fecha(valor):
    """Fecha de Excel o texto día/mes/año (12f)."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(_texto(valor), formato).date()
        except ValueError:
            pass
    return None


def _segundos(valor):
    """
    min:seg escrito (0:20, 00:20, 06:22; 0:80 entra como 1:20) o lo que Excel convirtió en hora:
    Excel lee 0:20 como 0 h 20 min, y eso es 0 min 20 s (12f). Vale para 1 pieza y tiempo total.
    """
    if valor is None or _texto(valor) == "":
        return None
    if isinstance(valor, datetime):
        valor = valor - datetime(1899, 12, 30)
    elif isinstance(valor, (int, float)):
        valor = timedelta(days=valor)
    if isinstance(valor, timedelta):
        return round(valor.total_seconds() / 60)
    if isinstance(valor, time):
        return valor.hour * 60 + valor.minute
    return segundos_de(_texto(valor), acarrear=True)


# ---------------------------------------------------------------- cómo sabe que ya estaba (12e)

def operacion_de(madre_id, detallada_id, nueva):
    return f"{madre_id}:{detallada_id}" if detallada_id else f"{madre_id}:{_norma(nueva)}"


def clave(fecha, quien, operador_id, operacion, piezas, segundos):
    """Misma fecha, quién midió, operador, operación, piezas y tiempo total."""
    return "|".join(map(str, (fecha.isoformat(), _norma(quien), operador_id or "", operacion, piezas, segundos)))


def clave_medicion(m):
    return clave(
        m.fecha, m.quien_midio, m.operador_id,
        operacion_de(m.operacion_madre_id, m.operacion_detallada_id, m.detallada_nueva),
        m.muestra_piezas, segundos_de(m.muestra_tiempo_total, acarrear=True),
    )


# ---------------------------------------------------------------- revisar (12c, 12d, 12f)

def revisar(archivo):
    """Lee el libro y arma el resumen sin guardar nada. Si los encabezados no están en su lugar, no carga nada."""
    try:
        libro = load_workbook(archivo, read_only=True, data_only=True)
    except Exception:
        raise ValidationError("No se pudo leer el archivo. Sube el libro descargado como Excel (.xlsx).")
    hoja = libro[HOJA] if HOJA in libro.sheetnames else libro.worksheets[0]
    renglones = hoja.iter_rows(min_row=FILA_ENCABEZADOS, max_col=len(COLUMNAS), values_only=True)
    encabezados = [*next(renglones, ()), *[None] * len(COLUMNAS)]
    for i, palabra in enumerate(ENCABEZADOS):
        if palabra not in _norma(encabezados[i]):
            raise ValidationError(
                f"La columna {chr(65 + i)} de la fila {FILA_ENCABEZADOS} debería ser «{COLUMNAS[i]}» y dice "
                f"«{_texto(encabezados[i]) or 'vacía'}». Alguien movió, borró o metió una columna: no se cargó nada."
            )

    operadores = {_norma(o.nombre): o.pk for o in Operario.objects.all()}  # también los dados de baja
    madres = {_norma(m.nombre): m for m in OperacionMadre.objects.all()}
    detalladas = defaultdict(dict)
    for madre_id, pk, nombre in OperacionDetallada.objects.values_list("madre_id", "pk", "nombre"):
        detalladas[madre_id][_norma(nombre)] = pk
    for madre_id, pk, nombre in NombreAnterior.objects.values_list("operacion__madre_id", "operacion_id", "nombre"):
        detalladas[madre_id].setdefault(_norma(nombre), pk)  # nombre viejo → la operación de hoy
    maquinas = {_norma(m.nombre): m.pk for m in Maquina.objects.all()}
    existentes = Counter(clave_medicion(m) for m in MedicionTiempo.objects.all())
    borradas = Counter(MedicionBorrada.objects.values_list("clave", flat=True))
    hoy = timezone.localdate()

    nuevas, errores, avisos = [], defaultdict(list), defaultdict(list)
    ya = saltadas = pendientes = 0
    for numero, renglon in enumerate(renglones, start=FILA_ENCABEZADOS + 1):  # sin tope de renglones
        c = [*renglon, *[None] * len(COLUMNAS)][:len(COLUMNAS)]
        if all(_texto(v) == "" for v in c):
            continue  # renglón vacío
        try:
            total = _segundos(c[11])
        except ValidationError:
            errores["El tiempo total no es min:seg."].append(numero)
            continue
        if not total:
            pendientes += 1  # sin tiempo: operación pendiente de medir, no es error
            continue
        fecha, madre = _fecha(c[0]), madres.get(_norma(c[4]))
        operador_id, piezas = operadores.get(_norma(c[2])), _texto(c[10])
        motivo = (
            "Fecha vacía o que no se entiende." if not fecha
            else "Fecha futura." if fecha > hoy
            else "Operación madre que no existe en el catálogo." if not madre
            else "Tiene tiempo y no tiene operación detallada." if not _texto(c[5])
            else "Operador que no está en Catálogos." if not operador_id
            else "Piezas en cero o que no son número." if not piezas.isdigit() or int(piezas) < 1
            else ""
        )
        if motivo:
            errores[motivo].append(numero)
            continue

        detallada_id = detalladas[madre.pk].get(_norma(c[5]))
        nueva = "" if detallada_id else _texto(c[5])  # no está en el catálogo: entra NUEVA
        maquina_id = maquinas.get(_norma(c[6]))
        if _texto(c[6]) and not maquina_id:
            avisos["Máquina que no está en el catálogo."].append(numero)
        material = MATERIALES.get(_norma(c[8]), "")
        if _texto(c[8]) and not material:
            avisos["Material que no se reconoce."].append(numero)
        try:
            uno = _segundos(c[9])
        except ValidationError:
            uno = None
            avisos["1 pieza no es min:seg."].append(numero)
        modelo = _texto(c[3])
        if madre.nombre == MADRE_EMPAQUETAR and "," in modelo:
            modelo = VARIOS_MODELOS
        foto = _texto(c[15])

        k = clave(fecha, c[1], operador_id, operacion_de(madre.pk, detallada_id, nueva), int(piezas), total)
        if existentes[k]:  # dos iguales en el libro y una en el sistema: entra una
            existentes[k] -= 1
            ya += 1
            continue
        if borradas[k]:  # se borró en el sistema: no regresa
            borradas[k] -= 1
            saltadas += 1
            continue
        nuevas.append({
            "fila": numero, "fecha": fecha.isoformat(), "quien": _texto(c[1])[:80], "operador": operador_id,
            "modelo": modelo[:150], "madre": madre.pk, "detallada": detallada_id, "nueva": nueva[:200],
            "maquina": maquina_id, "medida": _texto(c[7])[:50], "material": material,
            "uno": texto_mmss(uno) if uno else "", "piezas": int(piezas), "total": texto_mmss(total),
            "foto": foto[:200] if foto.lower().startswith("http") else "", "observaciones": _texto(c[16]),
        })
    libro.close()
    return {
        "archivo": getattr(archivo, "name", "libro.xlsx"), "nuevas": nuevas, "ya": ya, "borradas": saltadas,
        "pendientes": pendientes, "no_cargan": sum(len(filas) for filas in errores.values()),
        "errores": [[motivo, " · ".join(map(str, filas))] for motivo, filas in errores.items()],
        "avisos": [[motivo, " · ".join(map(str, filas))] for motivo, filas in avisos.items()],
    }


# ---------------------------------------------------------------- cargar y deshacer

@transaction.atomic
def cargar(resumen, usuario):
    """Todo o nada (12f): si algo falla a la mitad, no queda nada. Después se revisan todas las operaciones."""
    importacion = Importacion.objects.create(
        usuario=usuario or "Sin nombre", archivo=resumen["archivo"][:255], cargadas=len(resumen["nuevas"]),
    )
    for d in resumen["nuevas"]:
        MedicionTiempo(
            origen=MedicionTiempo.Origen.IMPORTADA, importacion=importacion, fila_hoja=d["fila"],
            fecha=date.fromisoformat(d["fecha"]), quien_midio=d["quien"], operador_id=d["operador"],
            modelo_pieza=d["modelo"], operacion_madre_id=d["madre"], operacion_detallada_id=d["detallada"],
            detallada_nueva=d["nueva"], maquina_id=d["maquina"], medida=d["medida"], material=d["material"],
            tiempo_1_pieza=d["uno"], muestra_piezas=d["piezas"], muestra_tiempo_total=d["total"],
            foto_url=d["foto"], observaciones=d["observaciones"],
        ).save()
    calculos.recalcular_todo()
    Bitacora.anotar(usuario, "Importar mediciones", importacion, "", f"{importacion.cargadas} mediciones")
    return importacion


@transaction.atomic
def deshacer(importacion, usuario):
    """Quita solo lo que entró en esa carga (12g). No las marca como borradas: se pueden volver a importar."""
    cuantas = importacion.mediciones.count()
    importacion.mediciones.all().delete()
    importacion.deshecha = True
    importacion.save(update_fields=["deshecha"])
    calculos.recalcular_todo()
    Bitacora.anotar(usuario, "Deshacer importación", importacion, f"{cuantas} mediciones", "")
    return cuantas