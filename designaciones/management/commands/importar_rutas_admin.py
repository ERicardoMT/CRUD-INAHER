"""Carga inicial del catálogo de rutas administrables, sin tocar tiempos."""

import json
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from designaciones.models import FamiliaRuta, OperacionMadre, PasoRuta


class Command(BaseCommand):
    help = "Importa una sola vez las rutas del JSON al administrador."

    def add_arguments(self, parser):
        modo = parser.add_mutually_exclusive_group(required=True)
        modo.add_argument("--dry-run", action="store_true")
        modo.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if FamiliaRuta.objects.exists() or PasoRuta.objects.exists():
            raise CommandError(
                "Ya existen rutas administrables. No se sobrescribe "
                "ningún cambio del administrador."
            )

        archivo = (
            Path(settings.BASE_DIR)
            / "static/designaciones/data/datos_rutas_inaher.json"
        )

        try:
            datos = json.loads(archivo.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(
                f"No se pudo leer el JSON: {exc}"
            ) from exc

        familias, pasos, madres = self.preparar(datos)

        self.stdout.write("\nIMPORTACIÓN DE RUTAS ADMINISTRABLES")
        self.stdout.write(
            f"Modo: {'SIMULACIÓN' if options['dry_run'] else 'APLICACIÓN'}"
        )
        self.stdout.write(f"Versión: {datos['generado']}")
        self.stdout.write(f"Familias: {len(familias)}")
        self.stdout.write(f"Pasos: {len(pasos)}")
        self.stdout.write(
            "Operaciones madre reutilizadas: "
            f"{len(set(x['madre'] for x in pasos))}"
        )
        self.stdout.write(
            "Operaciones y tiempos existentes: sin cambios"
        )

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Simulación correcta. No se escribió en la base de datos."
                )
            )
            return

        with transaction.atomic():
            if FamiliaRuta.objects.exists() or PasoRuta.objects.exists():
                raise CommandError(
                    "Las tablas dejaron de estar vacías. Se canceló."
                )

            familias_guardadas = {}

            for item in familias:
                familia = FamiliaRuta(**item)
                familia.full_clean()
                familia.save()
                familias_guardadas[familia.nombre] = familia

            for item in pasos:
                paso = PasoRuta(
                    familia=familias_guardadas[item["familia"]],
                    madre_id=madres[item["madre"]],
                    orden=item["orden"],
                    detallada=item["detallada"],
                    condicion=item["condicion"],
                    nota=item["nota"],
                )

                paso.full_clean()
                paso.save()

            totales = (
                FamiliaRuta.objects.count(),
                PasoRuta.objects.count(),
            )

            if totales != (15, 269):
                raise CommandError(
                    "Los totales no coinciden. "
                    "Se canceló toda la transacción."
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Importación aplicada correctamente."
            )
        )

    def preparar(self, datos):
        if (
            not isinstance(datos, dict)
            or datos.get("generado") != "23-nov-2026"
        ):
            raise CommandError(
                "No es el catálogo de rutas del 23-nov-2026."
            )

        if (
            not isinstance(datos.get("familias"), list)
            or len(datos["familias"]) != 15
        ):
            raise CommandError(
                "Se requieren exactamente 15 familias."
            )

        if (
            not isinstance(datos.get("rutas"), list)
            or len(datos["rutas"]) != 269
        ):
            raise CommandError(
                "Se requieren exactamente 269 pasos."
            )

        def texto(item, clave, ubicacion, obligatorio=False):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get(clave), str)
            ):
                raise CommandError(
                    f"Texto inválido: {ubicacion}, {clave}."
                )

            valor = item[clave].strip()

            if obligatorio and not valor:
                raise CommandError(
                    f"Campo vacío: {ubicacion}, {clave}."
                )

            return valor

        familias = []
        familias_vistas = set()

        for numero, item in enumerate(datos["familias"], 1):
            ubicacion = f"familia {numero}"

            nombre = texto(
                item, "familia", ubicacion, True
            )
            modelos = texto(
                item, "modelos", ubicacion, True
            )
            descripcion = texto(
                item, "descripcion", ubicacion
            )

            if nombre in familias_vistas or len(nombre) > 180:
                raise CommandError(
                    f"Familia duplicada o demasiado larga: {nombre}"
                )

            familias_vistas.add(nombre)

            familias.append({
                "nombre": nombre,
                "modelos": modelos,
                "descripcion": descripcion,
                "orden": numero,
            })

        madres = dict(
            OperacionMadre.objects.values_list("nombre", "pk")
        )

        if not madres:
            raise CommandError(
                "No hay operaciones madre sincronizadas."
            )

        pasos = []
        por_familia = Counter()
        claves_vistas = set()

        for numero, item in enumerate(datos["rutas"], 1):
            ubicacion = f"paso {numero}"

            familia = texto(
                item, "familia", ubicacion, True
            )
            madre = texto(
                item, "madre", ubicacion, True
            )
            detallada = texto(
                item, "detallada", ubicacion, True
            )
            condicion = texto(
                item, "condicion", ubicacion
            )
            nota = texto(
                item, "nota", ubicacion
            )

            if familia not in familias_vistas:
                raise CommandError(
                    f"Familia desconocida en {ubicacion}: {familia}"
                )

            if madre not in madres:
                raise CommandError(
                    f"Operación madre inexistente en {ubicacion}: {madre}"
                )

            if len(detallada) > 200 or len(condicion) > 500:
                raise CommandError(
                    f"Texto demasiado largo en {ubicacion}."
                )

            clave = (
                familia,
                madre,
                detallada,
                condicion,
            )

            if clave in claves_vistas:
                raise CommandError(
                    f"Regla repetida en {ubicacion}."
                )

            claves_vistas.add(clave)

            por_familia[familia] += 1
            orden = por_familia[familia]

            try:
                PasoRuta(
                    orden=orden,
                    madre_id=madres[madre],
                    detallada=detallada,
                    condicion=condicion,
                    nota=nota,
                ).clean()

            except ValidationError as exc:
                raise CommandError(
                    f"Condición inválida en {ubicacion}: {exc}"
                ) from exc

            pasos.append({
                "familia": familia,
                "madre": madre,
                "orden": orden,
                "detallada": detallada,
                "condicion": condicion,
                "nota": nota,
            })

        if set(por_familia) != familias_vistas:
            raise CommandError(
                "Hay familias sin pasos de ruta."
            )

        return familias, pasos, madres
