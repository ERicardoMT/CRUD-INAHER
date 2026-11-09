import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from decimal import Decimal
from django.core.management.base import BaseCommand
from designaciones.models import Operario, Maquina, OperacionMadre, OperacionDetallada
from pedidos.models import Pedido


def excel_date_to_date(serial):
    try:
        val = float(serial)
        # Excel base date is 1899-12-30 due to the 1900 leap year bug
        base = datetime(1899, 12, 30)
        return (base + timedelta(days=val)).date()
    except Exception:
        return None


class Command(BaseCommand):
    help = "Carga operarios, máquinas, operaciones y pedidos iniciales desde designacion.xlsx"

    def handle(self, *args, **options):
        xlsx_path = "designacion.xlsx"
        if not os.path.exists(xlsx_path):
            xlsx_path = os.path.join("..", "designacion.xlsx")

        ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

        try:
            z = zipfile.ZipFile(xlsx_path)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"No se pudo abrir {xlsx_path}: {e}"))
            return

        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('ns:si', ns):
                shared_strings.append(''.join(t.text or '' for t in si.findall('.//ns:t', ns)))

        # 1. Leer Config (sheet7.xml)
        if 'xl/worksheets/sheet7.xml' in z.namelist():
            sheet_xml = z.read('xl/worksheets/sheet7.xml')
            root = ET.fromstring(sheet_xml)
            for row in root.findall('.//ns:row', ns):
                r_num = int(row.attrib.get('r'))
                cols = {}
                for c in row.findall('ns:c', ns):
                    ref = c.attrib.get('r')
                    col = ''.join(ch for ch in ref if ch.isalpha())
                    t = c.attrib.get('t')
                    v = c.find('ns:v', ns)
                    v_txt = v.text if v is not None else ''
                    if t == 's' and v_txt.isdigit():
                        v_txt = shared_strings[int(v_txt)]
                    cols[col] = (v_txt or "").strip()

                if r_num >= 6:
                    persona = cols.get('A')
                    if persona and persona not in ["Personas", "1 · PERSONAS"]:
                        Operario.objects.get_or_create(nombre=persona, defaults={'orden': r_num})

                    maq = cols.get('F')
                    tipo_maq = cols.get('G', '')
                    if maq and maq not in ["Máquina", "3 · MÁQUINAS (con su tipo)"]:
                        Maquina.objects.get_or_create(nombre=maq, defaults={'tipo': tipo_maq})

                    op_madre = cols.get('C')
                    tipo_m = cols.get('D', '')
                    if op_madre and op_madre not in ["Operación madre", "2 · OPERACIONES MADRE (con su tipo de máquina)"]:
                        OperacionMadre.objects.get_or_create(nombre=op_madre, defaults={'tipo_maquina': tipo_m})

                    madre_det = cols.get('K')
                    det = cols.get('L')
                    min_pz_str = cols.get('O', '0')
                    try:
                        min_pz = Decimal(min_pz_str)
                    except Exception:
                        min_pz = Decimal('0.0')

                    if madre_det and det and madre_det not in ["Op. madre", "5 · OPERACIONES DETALLADAS"]:
                        madre_obj, _ = OperacionMadre.objects.get_or_create(nombre=madre_det)
                        OperacionDetallada.objects.get_or_create(
                            madre=madre_obj,
                            nombre=det,
                            defaults={'minutos_estandar': min_pz}
                        )

        # 2. Leer Pedidos (sheet6.xml)
        if 'xl/worksheets/sheet6.xml' in z.namelist():
            sheet_xml = z.read('xl/worksheets/sheet6.xml')
            root = ET.fromstring(sheet_xml)
            pedidos_creados = 0
            for row in root.findall('.//ns:row', ns):
                r_num = int(row.attrib.get('r'))
                if r_num < 7:
                    continue
                cols = {}
                for c in row.findall('ns:c', ns):
                    ref = c.attrib.get('r')
                    col = ''.join(ch for ch in ref if ch.isalpha())
                    t = c.attrib.get('t')
                    v = c.find('ns:v', ns)
                    v_txt = v.text if v is not None else ''
                    if t == 's' and v_txt.isdigit():
                        v_txt = shared_strings[int(v_txt)]
                    cols[col] = (v_txt or "").strip()

                num_raw = cols.get('A')
                if not num_raw or num_raw == "# Pedido":
                    continue
                # Remove .0 if float
                num_pedido = str(int(float(num_raw))) if num_raw.replace('.', '', 1).isdigit() else str(num_raw)
                desc = cols.get('B', '')
                cant_raw = cols.get('C', '1')
                try:
                    cant = int(float(cant_raw))
                except Exception:
                    cant = 1
                fecha_salida = excel_date_to_date(cols.get('D'))
                estatus_raw = cols.get('G', 'EN PROCESO').upper()
                if "TERMINADO" in estatus_raw:
                    estatus = Pedido.Estado.TERMINADO
                elif "ESPERA" in estatus_raw:
                    estatus = Pedido.Estado.EN_ESPERA
                else:
                    estatus = Pedido.Estado.EN_PROCESO

                notas = cols.get('H', '')

                pedido, created = Pedido.objects.update_or_create(
                    numero=num_pedido,
                    defaults={
                        'fecha_salida': fecha_salida,
                        'estado': estatus,
                        'detenido': "DETENIDO" in estatus_raw,
                        'notas': notas,
                    }
                )
                pedido.partidas.all().delete()
                pedido.partidas.create(cantidad=max(cant, 1), descripcion=(desc or "Sin descripción")[:255])
                pedido.actualizar_resumen()
                if created:
                    pedidos_creados += 1

            self.stdout.write(self.style.SUCCESS(f"Pedidos cargados: {pedidos_creados} nuevos pedidos."))

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {Operario.objects.count()} operarios, "
            f"{Maquina.objects.count()} máquinas, "
            f"{OperacionMadre.objects.count()} operaciones madre, "
            f"{OperacionDetallada.objects.count()} operaciones detalladas, "
            f"{Pedido.objects.count()} pedidos en total."
        ))
