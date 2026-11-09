from datetime import timedelta
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from designaciones.models import (
    DesignacionDia,
    ItemDesignacion,
    OperacionDetallada,
    OperacionMadre,
    Operario,
)

from .forms import PedidoForm, PartidaFormSet
from .models import MovimientoPedido, PartidaPedido, Pedido


class ReglasHistoricoTests(TestCase):

    def setUp(self):
        self.hoy = timezone.localdate()
        self.operario = Operario.objects.create(nombre="Ángel")
        self.madre = OperacionMadre.objects.create(nombre="Cortar")
        self.detallada = OperacionDetallada.objects.create(madre=self.madre, nombre="Cortar varilla")
        self.dia = DesignacionDia.objects.create(fecha=self.hoy)

    def crear_pedido(self, numero, **kwargs):
        pedido = Pedido.objects.create(numero=numero, **kwargs)
        PartidaPedido.objects.create(pedido=pedido, cantidad=4, descripcion="REBO 400")
        pedido.actualizar_resumen()
        return pedido

    def crear_tarea(self, pedido, hecho, minutos=30):
        return ItemDesignacion.objects.create(
            designacion=self.dia, quien=self.operario, pedido=pedido,
            operacion_madre=self.madre, operacion_detallada=self.detallada,
            minutos=minutos, hecho=hecho,
        )

    # ----- Archivar -----
    def test_archivar_terminado_es_directo(self):
        pedido = self.crear_pedido("A1", estado=Pedido.Estado.TERMINADO)
        self.crear_tarea(pedido, hecho=True)

        self.client.post(reverse("pedidos:archivar"), {"pedido_ids": [pedido.pk]})

        pedido.refresh_from_db()
        self.assertTrue(pedido.archivado)
        self.assertFalse(pedido.archivado_sin_terminar)
        self.assertEqual(MovimientoPedido.objects.get().accion, MovimientoPedido.Accion.ARCHIVADO)

    def test_archivar_con_tareas_sin_palomear_pide_confirmar(self):
        pedido = self.crear_pedido("A2", estado=Pedido.Estado.EN_PROCESO)
        self.crear_tarea(pedido, hecho=True)
        self.crear_tarea(pedido, hecho=False)

        respuesta = self.client.post(reverse("pedidos:archivar"), {"pedido_ids": [pedido.pk]})
        self.assertTemplateUsed(respuesta, "pedidos/pedido_confirm_archivar.html")
        pedido.refresh_from_db()
        self.assertFalse(pedido.archivado)

        self.client.post(reverse("pedidos:archivar"), {
            "pedido_ids": [pedido.pk], "confirmar": "1", "quien": "Denisse",
        })
        pedido.refresh_from_db()
        self.assertTrue(pedido.archivado)
        self.assertTrue(pedido.archivado_sin_terminar)
        mov = MovimientoPedido.objects.get()
        self.assertEqual(mov.accion, MovimientoPedido.Accion.ARCHIVADO_SIN_TERMINAR)
        self.assertEqual(mov.usuario, "Denisse")

    def test_archivado_sale_de_activos_y_carga_de_planta(self):
        pedido = self.crear_pedido("A3", estado=Pedido.Estado.EN_PROCESO, archivado=True)
        self.assertNotIn(pedido, Pedido.objects.por_filtro("activos"))
        self.assertNotIn(pedido, Pedido.objects.por_filtro("todos"))
        self.assertNotIn(pedido, Pedido.objects.carga_planta())
        self.assertIn(pedido, Pedido.objects.por_filtro("historico"))

    def test_desarchivar(self):
        pedido = self.crear_pedido("A4", archivado=True, archivado_sin_terminar=True)
        self.client.post(reverse("pedidos:desarchivar"), {"pedido_ids": [pedido.pk]})
        pedido.refresh_from_db()
        self.assertFalse(pedido.archivado)
        self.assertFalse(pedido.archivado_sin_terminar)
        self.assertEqual(MovimientoPedido.objects.get().accion, MovimientoPedido.Accion.DESARCHIVADO)

    # ----- Eliminar -----
    def test_eliminar_sin_avance_pide_quien_y_registra_bitacora(self):
        pedido = self.crear_pedido("E1")
        tarea = self.crear_tarea(pedido, hecho=False)
        url = reverse("pedidos:eliminar", args=[pedido.pk])

        # Sin nombre no elimina
        self.client.post(url, {"confirmar": "1"})
        self.assertTrue(Pedido.objects.filter(pk=pedido.pk).exists())

        self.client.post(url, {"confirmar": "1", "quien": "Denisse"})
        self.assertFalse(Pedido.objects.filter(pk=pedido.pk).exists())
        self.assertFalse(ItemDesignacion.objects.filter(pk=tarea.pk).exists())
        mov = MovimientoPedido.objects.get()
        self.assertEqual((mov.accion, mov.pedido_numero, mov.usuario), ("ELIMINADO", "E1", "Denisse"))

    def test_no_elimina_con_avance_y_ofrece_archivar(self):
        pedido = self.crear_pedido("E2")
        self.crear_tarea(pedido, hecho=True)
        url = reverse("pedidos:eliminar", args=[pedido.pk])

        respuesta = self.client.get(url)
        self.assertContains(respuesta, "Archivar en su lugar")

        self.client.post(url, {"confirmar": "1", "quien": "Denisse"})
        self.assertTrue(Pedido.objects.filter(pk=pedido.pk).exists())
        self.assertFalse(MovimientoPedido.objects.exists())

    def test_eliminar_seleccionados_solo_borra_los_permitidos(self):
        libre = self.crear_pedido("E3")
        con_avance = self.crear_pedido("E4")
        self.crear_tarea(con_avance, hecho=True)

        self.client.post(reverse("pedidos:eliminar_seleccionados"), {
            "pedido_ids": [libre.pk, con_avance.pk], "confirmar": "1", "quien": "Denisse",
        })
        self.assertFalse(Pedido.objects.filter(pk=libre.pk).exists())
        self.assertTrue(Pedido.objects.filter(pk=con_avance.pk).exists())

    # ----- Opciones del listado -----
    def test_ordenar_por_fecha_de_captura(self):
        self.crear_pedido("O1", fecha_captura=self.hoy - timedelta(days=5), fecha_salida=self.hoy)
        self.crear_pedido("O2", fecha_captura=self.hoy, fecha_salida=self.hoy + timedelta(days=9))

        por_salida = self.client.get(reverse("pedidos:lista"))
        self.assertEqual([p.numero for p in por_salida.context["pedidos"]], ["O1", "O2"])

        por_captura = self.client.get(reverse("pedidos:lista"), {"orden": "fecha_captura"})
        self.assertEqual([p.numero for p in por_captura.context["pedidos"]], ["O2", "O1"])

    def test_exportar_excel_respeta_el_filtro(self):
        self.crear_pedido("X1", estado=Pedido.Estado.EN_PROCESO)
        self.crear_pedido("X2", estado=Pedido.Estado.ENTREGADO)

        respuesta = self.client.get(reverse("pedidos:exportar_excel"), {"ver": "activos"})
        hoja = load_workbook(BytesIO(respuesta.content)).active
        numeros = [fila[0] for fila in hoja.iter_rows(min_row=6, values_only=True)]
        self.assertEqual(numeros, ["X1"])

    def test_impresiones(self):
        pedido = self.crear_pedido("P1")
        listado = self.client.get(reverse("pedidos:imprimir_listado"), {"ver": "activos", "orden": "estatus"})
        self.assertContains(listado, "INAHER · Pedidos activos")
        self.assertContains(listado, "orden:</strong> estatus")
        self.assertContains(listado, 'counter(pages)')

        ficha = self.client.get(reverse("pedidos:imprimir_ficha", args=[pedido.pk]))
        self.assertContains(ficha, "INAHER · Pedido P1")
        self.assertContains(ficha, "REBO 400")


class ReglasEstatusTests(TestCase):
    """Reglas de estatus (lista), DETENIDO (bandera), estado por fecha y avance."""

    def setUp(self):
        self.hoy = timezone.localdate()
        self.operario = Operario.objects.create(nombre="Ángel")
        self.madre = OperacionMadre.objects.create(nombre="Cortar")
        self.detallada = OperacionDetallada.objects.create(madre=self.madre, nombre="Cortar varilla")
        self.dia = DesignacionDia.objects.create(fecha=self.hoy)
        self.pedido = Pedido.objects.create(numero="R1", fecha_salida=self.hoy + timedelta(days=5))
        self.p1 = PartidaPedido.objects.create(pedido=self.pedido, cantidad=4, descripcion="REBO 400")
        self.p2 = PartidaPedido.objects.create(pedido=self.pedido, cantidad=6, descripcion="SCN-90 inox")
        self.pedido.actualizar_resumen()

    def tarea(self, partida=None, minutos=30, hecho=False, bloqueado_por=""):
        return ItemDesignacion.objects.create(
            designacion=self.dia, quien=self.operario, pedido=self.pedido, partida=partida,
            operacion_madre=self.madre, operacion_detallada=self.detallada,
            minutos=minutos, hecho=hecho, bloqueado_por=bloqueado_por,
        )

    def toggle(self, item):
        self.client.post(reverse("designaciones:toggle_hecho", args=[item.pk]))
        self.pedido.refresh_from_db()

    # ----- Estatus -----
    def test_ciclo_automatico_y_fecha_de_terminado(self):
        self.assertEqual(self.pedido.estado, Pedido.Estado.EN_ESPERA)
        t1, t2 = self.tarea(self.p1), self.tarea(self.p2)

        self.toggle(t1)
        self.assertEqual(self.pedido.estado, Pedido.Estado.EN_PROCESO)

        self.toggle(t2)
        self.assertEqual(self.pedido.estado, Pedido.Estado.TERMINADO)
        self.assertEqual(self.pedido.fecha_terminado, self.hoy)

        self.toggle(t2)  # se quita una ✓
        self.assertEqual(self.pedido.estado, Pedido.Estado.EN_PROCESO)
        self.assertIsNone(self.pedido.fecha_terminado)

    def test_terminado_a_mano_guarda_fecha(self):
        self.client.post(reverse("pedidos:cambiar_estado", args=[self.pedido.pk]), {"estado": "TERMINADO"})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.TERMINADO)
        self.assertEqual(self.pedido.fecha_terminado, self.hoy)

    def test_entregado_desde_la_lista_pide_fecha_y_cantidad(self):
        respuesta = self.client.post(reverse("pedidos:cambiar_estado", args=[self.pedido.pk]), {"estado": "ENTREGADO"})
        self.assertRedirects(respuesta, reverse("pedidos:registrar_entrega", args=[self.pedido.pk]))
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.EN_ESPERA)

    def test_entrega_parcial_y_completa(self):
        url = reverse("pedidos:registrar_entrega", args=[self.pedido.pk])

        self.client.post(url, {"fecha": self.hoy.isoformat(), "cantidad": 4})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.EN_PROCESO)
        self.assertTrue(self.pedido.entrega_parcial)
        self.assertEqual(self.pedido.cantidad_entregada, 4)
        self.assertIn(self.pedido, Pedido.objects.por_filtro("activos"))

        # No deja entregar de más
        respuesta = self.client.post(url, {"fecha": self.hoy.isoformat(), "cantidad": 7})
        self.assertContains(respuesta, "Solo faltan 6 pzas")

        self.client.post(url, {"fecha": self.hoy.isoformat(), "cantidad": 6})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.ENTREGADO)
        self.assertEqual(self.pedido.fecha_entrega, self.hoy)
        self.assertNotIn(self.pedido, Pedido.objects.por_filtro("activos"))

        # Quitar una entrega reabre el pedido
        entrega = self.pedido.entregas.last()
        self.client.post(reverse("pedidos:eliminar_entrega", args=[entrega.pk]))
        self.pedido.refresh_from_db()
        self.assertNotEqual(self.pedido.estado, Pedido.Estado.ENTREGADO)

    def test_las_tareas_no_cierran_un_entregado(self):
        self.pedido.establecer_estado(Pedido.Estado.ENTREGADO)
        t = self.tarea()
        self.toggle(t)
        self.assertEqual(self.pedido.estado, Pedido.Estado.ENTREGADO)

    # ----- DETENIDO -----
    def test_detenido_automatico_por_tarea_bloqueada(self):
        t = self.tarea(bloqueado_por="Base MT-2 · llega 12 nov")
        self.client.post(reverse("designaciones:toggle_hecho", args=[t.pk]))  # dispara la sincronización
        self.client.post(reverse("designaciones:toggle_hecho", args=[t.pk]))
        self.pedido.refresh_from_db()
        self.assertTrue(self.pedido.detenido)
        self.assertFalse(self.pedido.detenido_manual)
        self.assertEqual(self.pedido.detenido_por, "Base MT-2 · llega 12 nov")

        t.bloqueado_por = ""
        t.save()
        self.pedido.sincronizar_detenido()
        self.pedido.refresh_from_db()
        self.assertFalse(self.pedido.detenido)

    def test_lo_automatico_no_apaga_una_bandera_manual(self):
        self.pedido.detenido = True
        self.pedido.detenido_manual = True
        self.pedido.detenido_por = "Cliente pidió esperar"
        self.pedido.save()

        self.pedido.sincronizar_detenido()  # no hay tareas bloqueadas
        self.pedido.refresh_from_db()
        self.assertTrue(self.pedido.detenido)
        self.assertEqual(self.pedido.detenido_por, "Cliente pidió esperar")

    # ----- Estado por fecha -----
    def test_estado_por_fecha(self):
        casos = {-2: "ATRASADO", 0: "SALE HOY", 1: "URGENTE", 2: "URGENTE", 3: "EN TIEMPO"}
        for dias, texto in casos.items():
            self.pedido.fecha_salida = self.hoy + timedelta(days=dias)
            self.assertEqual(self.pedido.alerta_estado["texto"], texto, dias)
            self.assertEqual(self.pedido.dias_restantes, dias)
        self.assertNotEqual(
            Pedido(fecha_salida=self.hoy, estado="EN_ESPERA").alerta_estado["clase"],
            Pedido(fecha_salida=self.hoy + timedelta(days=1), estado="EN_ESPERA").alerta_estado["clase"],
        )
        self.pedido.estado = Pedido.Estado.TERMINADO
        self.assertIsNone(self.pedido.dias_restantes)

    # ----- Avance -----
    def test_avance_por_partida_y_pedido(self):
        self.tarea(self.p1, minutos=30, hecho=True)
        self.tarea(self.p1, minutos=30, hecho=False)
        self.tarea(self.p2, minutos=40, hecho=False)
        self.tarea(None, minutos=10, hecho=False)  # Empaquetar: todo el pedido

        filas = {f["partida"].pk: f["pct"] for f in self.pedido.avance_partidas()}
        self.assertEqual(filas, {self.p1.pk: 50, self.p2.pk: 0})

        pedido = Pedido.objects.con_minutos().get(pk=self.pedido.pk)
        self.assertEqual((pedido.min_total, pedido.min_restante, pedido.pct_avance), (110, 80, 27))

    def test_ruta_carga_por_partida_y_empaquetar_una_vez(self):
        self.client.post(
            reverse("designaciones:cargar_ruta", args=[self.dia.pk]),
            {"pedido_id": self.pedido.pk, "operario_id": self.operario.pk, "familia": "MT"},
        )
        tareas = ItemDesignacion.objects.filter(pedido=self.pedido)
        self.assertEqual(tareas.filter(operacion_madre__nombre="Empaquetar").count(), 1)
        self.assertEqual(tareas.filter(partida=self.p1).count(), 5)
        self.assertEqual(tareas.filter(partida=self.p2).count(), 5)
class CorreccionesFichaPedidoTests(TestCase):

    def setUp(self):
        self.hoy = timezone.localdate()

        self.operario = Operario.objects.create(
            nombre="Operario de prueba"
        )

        self.madre = OperacionMadre.objects.create(
            nombre="Corte"
        )

        self.detallada = OperacionDetallada.objects.create(
            madre=self.madre,
            nombre="Cortar varilla",
        )

        self.dia = DesignacionDia.objects.create(
            fecha=self.hoy
        )

        self.pedido = Pedido.objects.create(
            numero="SAE-TEST-01",
            fecha_salida=self.hoy + timedelta(days=5),
        )

        self.partida = PartidaPedido.objects.create(
            pedido=self.pedido,
            cantidad=10,
            descripcion="REBO 400",
        )

        self.pedido.actualizar_resumen()

        self.tarea = ItemDesignacion.objects.create(
            designacion=self.dia,
            quien=self.operario,
            pedido=self.pedido,
            partida=self.partida,
            paso=1,
            operacion_madre=self.madre,
            operacion_detallada=self.detallada,
            cantidad=10,
            minutos=30,
            hecho=True,
        )

    def datos_partida(self, **extra):
        datos = {
            "partidas-TOTAL_FORMS": "1",
            "partidas-INITIAL_FORMS": "1",
            "partidas-MIN_NUM_FORMS": "1",
            "partidas-MAX_NUM_FORMS": "1000",
            "partidas-0-id": str(self.partida.pk),
            "partidas-0-cantidad": str(self.partida.cantidad),
            "partidas-0-descripcion": self.partida.descripcion,
        }

        datos.update(extra)
        return datos

    def test_numero_sae_bloqueado_al_editar(self):
        form = PedidoForm(instance=self.pedido)
        self.assertTrue(form.fields["numero"].disabled)

    def test_no_permite_eliminar_partida_con_tarea_completada(self):
        datos = self.datos_partida(
            **{"partidas-0-DELETE": "on"}
        )

        formset = PartidaFormSet(
            data=datos,
            instance=self.pedido,
            prefix="partidas",
        )

        self.assertFalse(formset.is_valid())
        self.assertIn(
            "no se pueden eliminar",
            str(formset.non_form_errors()).lower(),
        )

    def test_permite_cambiar_cantidad_de_partida_con_avance(self):
        datos = self.datos_partida(
            **{"partidas-0-cantidad": "12"}
        )

        formset = PartidaFormSet(
            data=datos,
            instance=self.pedido,
            prefix="partidas",
        )

        self.assertTrue(formset.is_valid(), formset.errors)
        self.assertTrue(formset.forms[0].tiene_avance)

    def test_ficha_muestra_tareas_de_designacion_solo_consulta(self):
        respuesta = self.client.get(
            reverse("pedidos:detalle", args=[self.pedido.pk])
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Tareas en Designación")
        self.assertContains(respuesta, "Cortar varilla")
        self.assertContains(respuesta, "Completada")

class PedidoFichaPaginaTests(TestCase):

    def crear_pedido(self, numero):
        pedido = Pedido.objects.create(
            numero=numero,
            fecha_salida=timezone.localdate() + timedelta(days=3),
            notas="Cliente solicita entrega prioritaria.",
        )

        PartidaPedido.objects.create(
            pedido=pedido,
            cantidad=4,
            descripcion="REBO 400",
        )

        PartidaPedido.objects.create(
            pedido=pedido,
            cantidad=6,
            descripcion="SCN-90 inox",
        )

        pedido.actualizar_resumen()
        return pedido

    def test_ficha_muestra_distribucion_de_dos_columnas(self):
        pedido = self.crear_pedido("FICHA-01")

        respuesta = self.client.get(
            reverse("pedidos:detalle", args=[pedido.pk])
        )

        self.assertEqual(respuesta.status_code, 200)

        for texto in (
            "pedido-ficha-grid",
            "Partidas",
            "Tareas en Designación",
            "Seguimiento",
            "Entregas",
            "Notas y fotos",
            "Bitácora",
            "REBO 400",
            "SCN-90 inox",
        ):
            self.assertContains(respuesta, texto)

    def test_listado_tiene_navegacion_desde_el_renglon(self):
        pedido = self.crear_pedido("FICHA-02")

        respuesta = self.client.get(
            reverse("pedidos:lista")
        )

        self.assertEqual(respuesta.status_code, 200)

        self.assertContains(
            respuesta,
            f'data-pedido-url="{reverse("pedidos:detalle", args=[pedido.pk])}"',
        )

        self.assertContains(
            respuesta,
            "Abrir pedido",
        )