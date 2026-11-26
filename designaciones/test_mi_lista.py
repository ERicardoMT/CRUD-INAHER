"""«Mi lista de hoy» · pantalla de los trabajadores (documento del 25-nov-2026)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pedidos.models import Cliente, PartidaPedido, Pedido

from .mi_lista import _texto_minutos
from .models import DesignacionDia, ItemDesignacion, Maquina, OperacionDetallada, OperacionMadre, Operario


class MiListaTests(TestCase):

    def setUp(self):
        hoy = timezone.localdate()
        self.dia = DesignacionDia.objects.create(fecha=hoy)
        self.u_ernesto = User.objects.create_user("ernesto", password="Clave-segura-123")
        self.u_noe = User.objects.create_user("noe", password="Clave-segura-123")
        self.ernesto = Operario.objects.create(nombre="Ernesto", usuario=self.u_ernesto)
        self.noe = Operario.objects.create(nombre="Noe", usuario=self.u_noe)

        self.manual = Maquina.objects.get_or_create(nombre="Tarea manual", defaults={"tipo": "Manual"})[0]
        self.taladro = Maquina.objects.create(nombre="Taladro fresador", tipo="Taladro")
        madre = OperacionMadre.objects.create(nombre="Rebabear en tijera o cuter")
        self.rebabear = OperacionDetallada.objects.create(madre=madre, nombre="Rebabear IVH con cúter", minutos_estandar=Decimal("1.25"))
        self.etiqueta = OperacionDetallada.objects.create(madre=madre, nombre="Poner etiqueta IVH", minutos_estandar=Decimal("1.25"))
        self.limpiar = OperacionDetallada.objects.create(madre=madre, nombre="Limpiar la máquina")  # sin tiempo

        cliente = Cliente.objects.create(nombre="Cliente Secreto SA")
        self.p5143 = Pedido.objects.create(numero="5143", cliente=cliente, fecha_salida=hoy - timedelta(days=2))
        self.partida = PartidaPedido.objects.create(pedido=self.p5143, cantidad=4, descripcion="IVH-4 de 5/8 galv")
        self.p5145 = Pedido.objects.create(numero="5145", fecha_salida=hoy + timedelta(days=5))
        PartidaPedido.objects.create(pedido=self.p5145, cantidad=40, descripcion="IVH-4 de 1/2 galv")
        for p in (self.p5143, self.p5145):
            p.actualizar_resumen()

        self.paso1 = self.tarea(self.noe, self.rebabear, paso=1)        # de otra persona
        self.paso2 = self.tarea(self.ernesto, self.etiqueta, paso=2)     # espera al paso 1 de Noe
        self.general = ItemDesignacion.objects.create(
            designacion=self.dia, quien=self.ernesto, operacion_madre=madre, operacion_detallada=self.limpiar,
            cantidad=0, paso=0, detalle="Limpiar la máquina", maquina=self.taladro,
        )
        self.client.force_login(self.u_ernesto)

    def tarea(self, quien, detallada, paso, cantidad=4):
        return ItemDesignacion.objects.create(
            designacion=self.dia, quien=quien, pedido=self.p5143, partida=self.partida, paso=paso,
            operacion_madre=detallada.madre, operacion_detallada=detallada, cantidad=cantidad, maquina=self.manual,
        )

    def lista(self, **params):
        return self.client.get(reverse("mi_lista"), params)

    def test_solo_sus_tareas_y_sin_clientes(self):
        r = self.lista()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Poner etiqueta IVH")
        self.assertNotContains(r, "Rebabear IVH con cúter")  # es de Noe
        self.assertNotContains(r, "Cliente Secreto")
        self.assertContains(r, "0 de 2 terminadas")
        self.assertContains(r, "Espera el paso anterior")
        self.assertContains(r, "Tareas generales")

    def test_tiempo_estimado_solo_si_tiene(self):
        r = self.lista()
        self.assertContains(r, "Tarea manual · Estimado 5 min")
        self.assertNotContains(r, "Estimado 0 min")
        self.assertEqual(_texto_minutos(150), "2 h 30 min")

    def test_tres_vistas(self):
        for vista, texto in (("pedido", "5143"), ("maquina", "Taladro fresador"), ("urgencia", "Atrasado")):
            r = self.lista(ver=vista)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, texto)

    def test_palomear_y_deshacer(self):
        url = reverse("mi_lista_marcar", args=[self.paso2.pk])
        r = self.client.post(url, {"hecho": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(r.json()["ok"])
        self.assertIn("Ya terminadas (1)", r.json()["lista"])
        self.paso2.refresh_from_db()
        self.assertTrue(self.paso2.hecho)
        self.assertEqual(self.paso2.hecho_por, "ernesto")
        self.p5143.refresh_from_db()
        self.assertEqual(self.p5143.estado, Pedido.Estado.EN_PROCESO)

        self.client.post(url, {"hecho": "0"})
        self.paso2.refresh_from_db()
        self.assertFalse(self.paso2.hecho)

    def test_anotar_piezas(self):
        url = reverse("mi_lista_piezas", args=[self.paso2.pk])
        r = self.client.post(url, {"piezas": "3"})
        self.assertIn("Llevas 3 de 4", r.json()["lista"])
        self.assertEqual(self.client.post(url, {"piezas": "9"}).status_code, 400)
        self.client.post(url, {"piezas": "4"})  # al llegar al total se palomea sola
        self.paso2.refresh_from_db()
        self.assertTrue(self.paso2.hecho)

    def test_tarea_general_no_lleva_piezas(self):
        r = self.client.post(reverse("mi_lista_piezas", args=[self.general.pk]), {"piezas": "1"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(reverse("mi_lista_marcar", args=[self.general.pk]), {"hecho": "1"})
        self.assertTrue(r.json()["ok"])

    def test_no_puede_tocar_tareas_de_otros(self):
        r = self.client.post(reverse("mi_lista_marcar", args=[self.paso1.pk]), {"hecho": "1"})
        self.assertEqual(r.status_code, 404)
        self.paso1.refresh_from_db()
        self.assertFalse(self.paso1.hecho)

    def test_el_aviso_se_quita_al_palomear_el_paso_anterior(self):
        self.paso1.poner_check(True)
        self.assertNotContains(self.lista(), "Espera el paso anterior")

    def test_usuario_sin_operario(self):
        sin = User.objects.create_user("visita", password="Clave-segura-123")
        self.client.force_login(sin)
        r = self.lista()
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "no tiene lista", status_code=403)

    def test_pide_entrar(self):
        self.client.logout()
        self.assertEqual(self.lista().status_code, 302)

    def test_trabajador_entra_directo_a_su_lista(self):
        r = self.client.get(reverse("core:inicio"))
        self.assertRedirects(r, reverse("mi_lista"))

    def test_administrador_revisa_la_lista_de_otro(self):
        admin = User.objects.create_superuser("marcos", "m@inaher.mx", "Clave-segura-123")
        self.client.force_login(admin)
        r = self.lista(operario=self.ernesto.pk)
        self.assertContains(r, "Vista de revisión")
        self.assertNotContains(r, "js-marcar")
        r = self.client.post(reverse("mi_lista_marcar", args=[self.paso2.pk]), {"hecho": "1"})
        self.assertEqual(r.status_code, 404)  # no palomea por otra persona


class AccesoTests(TestCase):
    """Al entrar: el administrador al panel principal; el trabajador solo a «Mi lista de hoy»."""

    def setUp(self):
        self.admin = User.objects.create_superuser("marcos", "m@inaher.mx", "Clave-segura-123")
        self.trabajador = User.objects.create_user("ernesto", password="Clave-segura-123")
        Operario.objects.create(nombre="Ernesto", usuario=self.trabajador)

    def entrar(self, usuario):
        return self.client.post(reverse("core:entrar"), {"username": usuario, "password": "Clave-segura-123"}, follow=True)

    def test_sin_sesion_pide_entrar(self):
        for url in ("/", "/pedidos/", "/designacion/", "/mi-lista/"):
            r = self.client.get(url, follow=True)
            self.assertEqual(r.request["PATH_INFO"], reverse("core:entrar"), url)

    def test_administrador_llega_al_panel(self):
        r = self.entrar("marcos")
        self.assertEqual(r.request["PATH_INFO"], reverse("core:inicio"))
        self.assertEqual(self.client.get("/pedidos/").status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 404)  # el panel de Django está cerrado

    def test_trabajador_llega_a_su_lista_y_no_sale_de_ahi(self):
        r = self.entrar("ernesto")
        self.assertEqual(r.request["PATH_INFO"], reverse("mi_lista"))
        for url in ("/", "/pedidos/", "/designacion/", "/catalogos/", "/admin/"):
            r = self.client.get(url)
            self.assertRedirects(r, reverse("mi_lista"), fetch_redirect_response=False, msg_prefix=url)

    def test_trabajador_con_next_tambien_va_a_su_lista(self):
        r = self.client.post(f"{reverse('core:entrar')}?next=/pedidos/",
                             {"username": "ernesto", "password": "Clave-segura-123"}, follow=True)
        self.assertEqual(r.request["PATH_INFO"], reverse("mi_lista"))
