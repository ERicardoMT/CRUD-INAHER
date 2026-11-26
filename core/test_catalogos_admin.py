"""Editor propio de Rutas, tarifas y días que no se trabaja (el panel de Django está cerrado)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from designaciones.models import FamiliaRuta, Maquina, OperacionMadre, Operario, PasoRuta

from .models import DiaInhabil
from .usuarios import CAPTURA, asignar_rol

CLAVE = "Clave-segura-123"


class EditorRutasTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser("marcos", "m@inaher.mx", CLAVE)
        self.client.force_login(self.admin)
        self.madre = OperacionMadre.objects.create(nombre="Cortar en sierra cinta")

    def test_crear_familia_y_pasos(self):
        r = self.client.post(reverse("core:ruta_familia_nueva"), {
            "nombre": "Nivelador MT", "modelos": "MT-1, MT-2", "descripcion": "", "orden": 1, "activa": "on",
        })
        familia = FamiliaRuta.objects.get(nombre="Nivelador MT")
        self.assertRedirects(r, reverse("core:ruta_familia", args=[familia.pk]))

        r = self.client.post(reverse("core:ruta_paso_nuevo", args=[familia.pk]), {
            "orden": 1, "madre": self.madre.pk, "detallada": "Cortar varilla {rango} · {mat}",
            "condicion": "tornillo=no;d>=3/4", "nota": "", "activo": "on",
        })
        self.assertRedirects(r, reverse("core:ruta_familia", args=[familia.pk]))
        paso = familia.pasos.get()
        self.assertContains(self.client.get(reverse("core:ruta_familia", args=[familia.pk])), "Cortar varilla {rango}")

        # El motor lo recibe por la API
        datos = self.client.get(reverse("designaciones:api_catalogo_rutas")).json()
        self.assertTrue(any(r["detallada"] == paso.detallada for r in datos["rutas"]))

    def test_condicion_no_reconocida_no_se_guarda(self):
        familia = FamiliaRuta.objects.create(nombre="F", modelos="X-1")
        r = self.client.post(reverse("core:ruta_paso_nuevo", args=[familia.pk]), {
            "orden": 1, "madre": self.madre.pk, "detallada": "Algo {raro}", "condicion": "color=rojo", "activo": "on",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "no reconocida")
        self.assertFalse(PasoRuta.objects.exists())

    def test_desactivar_y_borrar_paso(self):
        familia = FamiliaRuta.objects.create(nombre="F", modelos="X-1")
        paso = PasoRuta.objects.create(familia=familia, orden=1, madre=self.madre, detallada="Cortar")
        self.client.post(reverse("core:ruta_paso_activo", args=[paso.pk]))
        paso.refresh_from_db()
        self.assertFalse(paso.activo)
        self.client.post(reverse("core:ruta_paso_quitar", args=[paso.pk]))
        self.assertFalse(PasoRuta.objects.exists())

    def test_sin_permiso_no_entra(self):
        captura = User.objects.create_user("denisse", password=CLAVE)
        asignar_rol(captura, CAPTURA)
        self.client.force_login(captura)
        self.assertEqual(self.client.get(reverse("core:rutas")).status_code, 403)


class TarifasYDiasTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser("marcos", "m@inaher.mx", CLAVE)
        self.client.force_login(self.admin)

    def test_tarifas(self):
        noe = Operario.objects.create(nombre="Noe")
        torno = Maquina.objects.create(nombre="Torno convencional")
        self.client.post(reverse("core:guardar_tarifas"), {f"op_{noe.pk}": "85.5", f"maq_{torno.pk}": "$120"})
        noe.refresh_from_db()
        torno.refresh_from_db()
        self.assertEqual((noe.tarifa_hora, torno.tarifa_hora), (Decimal("85.50"), Decimal("120.00")))
        self.client.post(reverse("core:guardar_tarifas"), {f"op_{noe.pk}": "", f"maq_{torno.pk}": "abc"})
        noe.refresh_from_db()
        torno.refresh_from_db()
        self.assertIsNone(noe.tarifa_hora)                 # vacío = sin tarifa
        self.assertEqual(torno.tarifa_hora, Decimal("120.00"))  # lo inválido no se guarda

    def test_dias_que_no_se_trabaja(self):
        self.client.post(reverse("core:agregar_dia"), {"fecha": "2026-12-24", "motivo": "Inventario"})
        dia = DiaInhabil.objects.get()
        self.assertEqual((dia.fecha, dia.motivo), (date(2026, 12, 24), "Inventario"))
        self.assertContains(self.client.get(reverse("core:catalogos")), "Inventario")
        self.client.post(reverse("core:quitar_dia", args=[dia.pk]))
        self.assertFalse(DiaInhabil.objects.exists())

    def test_panel_de_django_cerrado(self):
        for url in ("/admin/", "/admin/login/", "/admin/auth/user/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
