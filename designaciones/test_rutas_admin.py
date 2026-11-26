"""Pruebas de importación de rutas y protección de operaciones."""

from io import StringIO
import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from .models import (
    FamiliaRuta,
    OperacionDetallada,
    OperacionMadre,
    PasoRuta,
)


class ImportarRutasAdminTests(TestCase):

    def setUp(self):
        call_command(
            "sincronizar_rutas",
            "--apply",
            stdout=StringIO(),
        )
        # Todo el sistema pide iniciar sesión: se entra con un usuario sin permisos especiales
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user("lector", password="Clave-segura-123"))

    def test_simulacion_no_escribe(self):
        call_command(
            "importar_rutas_admin",
            "--dry-run",
            stdout=StringIO(),
        )

        self.assertEqual(FamiliaRuta.objects.count(), 0)
        self.assertEqual(PasoRuta.objects.count(), 0)

    def test_importa_y_conserva_los_catalogos(self):
        madres_antes = OperacionMadre.objects.count()
        detalladas_antes = OperacionDetallada.objects.count()

        call_command(
            "importar_rutas_admin",
            "--apply",
            stdout=StringIO(),
        )

        self.assertEqual(FamiliaRuta.objects.count(), 15)
        self.assertEqual(PasoRuta.objects.count(), 269)

        self.assertEqual(
            OperacionMadre.objects.count(),
            madres_antes,
        )

        self.assertEqual(
            OperacionDetallada.objects.count(),
            detalladas_antes,
        )

        orden = list(
            PasoRuta.objects.filter(
                familia__nombre="Base troquelada (MT)"
            ).values_list("orden", flat=True)
        )

        self.assertEqual(
            orden,
            list(range(1, 35)),
        )

    def test_no_reimporta_ni_sobrescribe_cambios(self):
        call_command(
            "importar_rutas_admin",
            "--apply",
            stdout=StringIO(),
        )

        with self.assertRaises(CommandError):
            call_command(
                "importar_rutas_admin",
                "--apply",
                stdout=StringIO(),
            )

        self.assertEqual(PasoRuta.objects.count(), 269)

    def test_rechaza_condicion_desconocida(self):
        paso = PasoRuta(
            orden=1,
            detallada="Prueba",
            condicion="regla_desconocida=si",
        )

        with self.assertRaises(ValidationError):
            paso.clean()


    def test_api_sin_importacion_conserva_json_original(self):
        respuesta = self.client.get(
            reverse("designaciones:api_catalogo_rutas")
        )

        self.assertEqual(respuesta.status_code, 200)

        datos = json.loads(
            (
                Path(settings.BASE_DIR)
                / "static/designaciones/data/datos_rutas_inaher.json"
            ).read_text(encoding="utf-8-sig")
        )

        self.assertEqual(respuesta.json(), datos)

    def test_api_con_importacion_coincide_con_json(self):
        call_command(
            "importar_rutas_admin",
            "--apply",
            stdout=StringIO(),
        )

        respuesta = self.client.get(
            reverse("designaciones:api_catalogo_rutas")
        )

        self.assertEqual(respuesta.status_code, 200)

        datos = json.loads(
            (
                Path(settings.BASE_DIR)
                / "static/designaciones/data/datos_rutas_inaher.json"
            ).read_text(encoding="utf-8-sig")
        )

        self.assertEqual(respuesta.json(), datos)

        self.assertIn(
            "no-store",
            respuesta["Cache-Control"],
        )

    def test_api_refleja_edicion_de_paso(self):
        call_command(
            "importar_rutas_admin",
            "--apply",
            stdout=StringIO(),
        )

        paso = PasoRuta.objects.order_by("pk").first()

        paso.detallada = "Paso editado desde el administrador"
        paso.full_clean()
        paso.save(update_fields=["detallada"])

        respuesta = self.client.get(
            reverse("designaciones:api_catalogo_rutas")
        )

        self.assertEqual(respuesta.status_code, 200)

        self.assertEqual(
            respuesta.json()["rutas"][0]["detallada"],
            paso.detallada,
        )

    def test_api_excluye_familias_y_pasos_desactivados(self):
        call_command(
            "importar_rutas_admin",
            "--apply",
            stdout=StringIO(),
        )

        paso = PasoRuta.objects.order_by("pk").first()
        paso.activo = False
        paso.save(update_fields=["activo"])

        familia = FamiliaRuta.objects.exclude(
            pk=paso.familia_id
        ).order_by("pk").first()

        familia.activa = False
        familia.save(update_fields=["activa"])

        respuesta = self.client.get(
            reverse("designaciones:api_catalogo_rutas")
        )

        self.assertEqual(respuesta.status_code, 200)

        datos = respuesta.json()

        self.assertNotIn(
            familia.nombre,
            [f["familia"] for f in datos["familias"]],
        )

        self.assertTrue(
            all(
                ruta["familia"] != familia.nombre
                for ruta in datos["rutas"]
            )
        )

        self.assertEqual(
            len(datos["rutas"]),
            269 - familia.pasos.count() - 1,
        )


    def test_designacion_consulta_la_api_de_rutas(self):
        from django.contrib.auth import get_user_model

        administrador = get_user_model().objects.create_superuser(
            username="administrador_rutas_prueba",
            email="admin-rutas@example.test",
            password="ClaveSeguraSoloPrueba123!",
        )

        self.client.force_login(administrador)

        respuesta = self.client.get(
            reverse("designaciones:hoy")
        )

        self.assertEqual(respuesta.status_code, 200)

        self.assertContains(
            respuesta,
            f'data-json-url="{reverse("designaciones:api_catalogo_rutas")}"',
        )

        self.assertNotContains(
            respuesta,
            'data-json-url="/static/designaciones/data/datos_rutas_inaher.json"',
        )


    def test_catalogos_muestra_editor_a_administrador(self):
        from django.contrib.auth import get_user_model

        administrador = get_user_model().objects.create_superuser(
            username="editor_rutas_prueba",
            email="editor@example.test",
            password="ClaveSeguraSoloPrueba123!",
        )

        self.client.force_login(administrador)

        respuesta = self.client.get(
            reverse("core:catalogos")
        )

        self.assertEqual(respuesta.status_code, 200)

        self.assertContains(
            respuesta,
            "Rutas de producción",
        )

        self.assertContains(
            respuesta,
            reverse("core:rutas"),
        )

        respuesta_editor = self.client.get(
            reverse("core:rutas")
        )

        self.assertEqual(
            respuesta_editor.status_code,
            200,
        )

        # El panel de Django ya no existe
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_catalogos_oculta_editor_a_usuario_sin_permisos(self):
        respuesta = self.client.get(
            reverse("core:catalogos")
        )

        self.assertEqual(respuesta.status_code, 200)

        self.assertNotContains(
            respuesta,
            "Rutas de producción",
        )

        respuesta_editor = self.client.get(
            reverse("core:rutas")
        )

        self.assertEqual(
            respuesta_editor.status_code,
            403,
        )

    def test_catalogos_oculta_editor_a_staff_sin_permiso(self):
        from django.contrib.auth import get_user_model

        usuario = get_user_model().objects.create_user(
            username="staff_sin_rutas_prueba",
            password="ClaveSeguraSoloPrueba123!",
            is_staff=True,
        )

        self.client.force_login(usuario)

        respuesta = self.client.get(
            reverse("core:catalogos")
        )

        self.assertEqual(respuesta.status_code, 200)

        self.assertNotContains(
            respuesta,
            "Rutas de producción",
        )
