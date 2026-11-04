import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from designaciones.models import (
    Maquina,
    OperacionMadre,
    OperacionDetallada,
)


class Command(BaseCommand):
    help = "Sincroniza los catálogos del motor de rutas INAHER."

    def add_arguments(self, parser):
        grupo = parser.add_mutually_exclusive_group(required=True)
        grupo.add_argument("--dry-run", action="store_true")
        grupo.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        archivo = (
            Path(settings.BASE_DIR)
            / "static/designaciones/data/datos_rutas_inaher.json"
        )

        if not archivo.is_file():
            raise CommandError(f"No existe el JSON: {archivo}")

        try:
            data = json.loads(
                archivo.read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Error leyendo JSON: {exc}")

        madres, maquinas, operaciones = self.validar(data)
        preferencias = self.construir_preferencias(
            madres, maquinas
        )

        madres_bd = {
            x.nombre: x
            for x in OperacionMadre.objects.all()
        }

        maquinas_bd = {
            x.nombre: x
            for x in Maquina.objects.all()
        }

        operaciones_bd = {
            (x.madre.nombre, x.nombre): x
            for x in OperacionDetallada.objects.select_related(
                "madre", "maquina_sugerida"
            )
        }

        nuevas_madres = [
            x for x in madres
            if x["madre"] not in madres_bd
        ]

        nuevas_maquinas = [
            x for x in maquinas
            if x["maquina"] not in maquinas_bd
        ]

        nuevas_operaciones = [
            x for x in operaciones
            if (x["madre"], x["detallada"]) not in operaciones_bd
        ]

        completar_madres = [
            x for x in madres
            if (
                x["madre"] in madres_bd
                and not madres_bd[x["madre"]].tipo_maquina
                and x["tipos"]
            )
        ]

        completar_maquinas = [
            x for x in maquinas
            if (
                x["maquina"] in maquinas_bd
                and not maquinas_bd[x["maquina"]].tipo
                and x["tipo"]
            )
        ]

        sugerencias_nuevas = 0
        sin_preferencia = 0

        for item in operaciones:
            clave = (item["madre"], item["detallada"])
            objeto = operaciones_bd.get(clave)
            preferida = preferencias.get(item["madre"])

            if preferida:
                if objeto is None or objeto.maquina_sugerida_id is None:
                    sugerencias_nuevas += 1
            else:
                sin_preferencia += 1

        adicionales = (
            set(operaciones_bd)
            - {
                (x["madre"], x["detallada"])
                for x in operaciones
            }
        )

        conflictos = []

        for x in madres:
            actual = madres_bd.get(x["madre"])
            if (
                actual
                and actual.tipo_maquina
                and x["tipos"]
                and actual.tipo_maquina != x["tipos"]
            ):
                conflictos.append(
                    f"Madre {x['madre']}: "
                    f"{actual.tipo_maquina} / {x['tipos']}"
                )

        for x in maquinas:
            actual = maquinas_bd.get(x["maquina"])
            if (
                actual
                and actual.tipo
                and x["tipo"]
                and actual.tipo != x["tipo"]
            ):
                conflictos.append(
                    f"Máquina {x['maquina']}: "
                    f"{actual.tipo} / {x['tipo']}"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.NOTICE("SINCRONIZACIÓN MOTOR INAHER")
        )
        self.stdout.write(
            f"Modo: {'SIMULACIÓN' if options['dry_run'] else 'APLICACIÓN'}"
        )
        self.stdout.write("")

        self.stdout.write(
            f"Operaciones madre nuevas: {len(nuevas_madres)}"
        )
        self.stdout.write(
            f"Madres por completar: {len(completar_madres)}"
        )
        self.stdout.write(
            f"Máquinas nuevas: {len(nuevas_maquinas)}"
        )
        self.stdout.write(
            f"Máquinas por completar: {len(completar_maquinas)}"
        )
        self.stdout.write(
            f"Operaciones detalladas nuevas: {len(nuevas_operaciones)}"
        )
        self.stdout.write(
            f"Operaciones ya existentes: "
            f"{len(operaciones) - len(nuevas_operaciones)}"
        )
        self.stdout.write(
            f"Máquinas sugeridas por asignar: {sugerencias_nuevas}"
        )
        self.stdout.write(
            f"Operaciones sin máquina preferida: {sin_preferencia}"
        )
        self.stdout.write(
            f"Operaciones adicionales conservadas: {len(adicionales)}"
        )

        if conflictos:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Se detectaron diferencias. No se sobrescribirán:"
                )
            )
            for conflicto in conflictos:
                self.stdout.write(f" - {conflicto}")

        if options["dry_run"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Simulación finalizada. No se modificó la base de datos."
                )
            )
            return

        with transaction.atomic():
            mapa_madres = {}
            mapa_maquinas = {}

            for x in madres:
                objeto, _ = OperacionMadre.objects.get_or_create(
                    nombre=x["madre"],
                    defaults={"tipo_maquina": x["tipos"]},
                )

                if not objeto.tipo_maquina and x["tipos"]:
                    objeto.tipo_maquina = x["tipos"]
                    objeto.save(update_fields=["tipo_maquina"])

                mapa_madres[x["madre"]] = objeto

            for x in maquinas:
                objeto, _ = Maquina.objects.get_or_create(
                    nombre=x["maquina"],
                    defaults={"tipo": x["tipo"]},
                )

                if not objeto.tipo and x["tipo"]:
                    objeto.tipo = x["tipo"]
                    objeto.save(update_fields=["tipo"])

                mapa_maquinas[x["maquina"]] = objeto

            for x in operaciones:
                madre = mapa_madres[x["madre"]]
                maquina_nombre = preferencias.get(x["madre"])
                maquina = mapa_maquinas.get(maquina_nombre)

                objeto, creado = OperacionDetallada.objects.get_or_create(
                    madre=madre,
                    nombre=x["detallada"],
                    defaults={
                        "minutos_estandar": Decimal("0.00"),
                        "maquina_sugerida": maquina,
                    },
                )

                if (
                    not creado
                    and objeto.maquina_sugerida_id is None
                    and maquina is not None
                ):
                    objeto.maquina_sugerida = maquina
                    objeto.save(update_fields=["maquina_sugerida"])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Sincronización aplicada correctamente."
            )
        )

    def construir_preferencias(self, madres, maquinas):
        por_tipo = defaultdict(list)
        por_nombre = {}

        for maquina in maquinas:
            por_tipo[maquina["tipo"]].append(maquina["maquina"])
            por_nombre[maquina["maquina"]] = maquina["tipo"]

        resultado = {}

        for madre in madres:
            tokens = [
                x.strip()
                for x in madre["tipos"].split(" / ")
                if x.strip()
            ]

            if not tokens:
                resultado[madre["madre"]] = None
                continue

            primero = tokens[0]

            if primero in por_nombre:
                preferida = primero
            else:
                candidatas = por_tipo.get(primero, [])
                preferida = (
                    candidatas[0]
                    if len(candidatas) == 1
                    else None
                )

            resultado[madre["madre"]] = preferida

        return resultado

    def validar(self, data):
        if not isinstance(data, dict):
            raise CommandError("La raíz del JSON debe ser un objeto.")

        for clave in ("madres", "maquinas", "operaciones", "rutas"):
            if not isinstance(data.get(clave), list):
                raise CommandError(f"Lista inválida: {clave}")

        def leer(item, campo, seccion):
            valor = item.get(campo)

            if not isinstance(valor, str) or not valor.strip():
                raise CommandError(
                    f"Falta {campo} en {seccion}: {item}"
                )

            return valor.strip()

        madres = []
        nombres_madres = set()

        for item in data["madres"]:
            nombre = leer(item, "madre", "madres")
            tipo = str(item.get("tipos") or "").strip()

            if len(nombre) > 150 or len(tipo) > 100:
                raise CommandError(f"Longitud inválida: {nombre}")

            if nombre in nombres_madres:
                raise CommandError(f"Madre duplicada: {nombre}")

            nombres_madres.add(nombre)
            madres.append({
                "madre": nombre,
                "tipos": tipo,
            })

        maquinas = []
        nombres_maquinas = set()

        for item in data["maquinas"]:
            nombre = leer(item, "maquina", "maquinas")
            tipo = leer(item, "tipo", "maquinas")

            if len(nombre) > 120 or len(tipo) > 100:
                raise CommandError(f"Longitud inválida: {nombre}")

            if nombre in nombres_maquinas:
                raise CommandError(f"Máquina duplicada: {nombre}")

            nombres_maquinas.add(nombre)
            maquinas.append({
                "maquina": nombre,
                "tipo": tipo,
            })

        operaciones = []
        pares = set()

        for item in data["operaciones"]:
            madre = leer(item, "madre", "operaciones")
            detallada = leer(item, "detallada", "operaciones")

            if madre not in nombres_madres:
                raise CommandError(
                    f"Operación detallada sin madre: {madre}"
                )

            if len(detallada) > 200:
                raise CommandError(
                    f"Nombre demasiado largo: {detallada}"
                )

            par = (madre, detallada)

            if par in pares:
                raise CommandError(
                    f"Operación detallada duplicada: {par}"
                )

            pares.add(par)
            operaciones.append({
                "madre": madre,
                "detallada": detallada,
            })

        for item in data["rutas"]:
            madre = leer(item, "madre", "rutas")

            if madre not in nombres_madres:
                raise CommandError(
                    f"Ruta con madre inexistente: {madre}"
                )

        return madres, maquinas, operaciones