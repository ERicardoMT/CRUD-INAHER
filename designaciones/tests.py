"""
Casos de prueba de Designación diaria v2 (página 8 del documento del 18-nov-2026).
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Configuracion
from pedidos.models import PartidaPedido, Pedido

from . import reglas
from .models import (
    TAREA_ESPECIAL, DesignacionDia, ItemDesignacion, Maquina, OperacionDetallada, OperacionMadre, Operario,
    TiempoFijo, redondear,
)
from .views import cerrar_dia


class BaseDesignacion(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser("marcos", "m@inaher.mx", "Clave-segura-123")
        self.client.force_login(self.admin)
        self.hoy = timezone.localdate()
        self.dia = DesignacionDia.objects.create(fecha=self.hoy)
        Configuracion.actual()  # turno 8:30–18:00 − 60 = 510

        self.vilchis = Operario.objects.create(nombre="Vilchis", orden=1)
        self.noe = Operario.objects.create(nombre="Noe", orden=2)
        self.angel = Operario.objects.create(nombre="Angel", orden=3)

        self.sierra = Maquina.objects.create(nombre="Sierra cinta universal", tipo="Sierra cinta")
        self.torno = Maquina.objects.create(nombre="Torno convencional", tipo="Torno convencional")
        self.cnc1 = Maquina.objects.create(nombre="Torno CNC Hermabro", tipo="Torno CNC")
        self.cnc2 = Maquina.objects.create(nombre="Torno CNC Universal", tipo="Torno CNC")
        self.manual = Maquina.objects.get_or_create(nombre="Tarea manual", defaults={"tipo": "Manual"})[0]
        self.esmeril = Maquina.objects.create(nombre="Esmeril de banco", tipo="Esmeril")

        self.m_cortar = OperacionMadre.objects.create(nombre="Cortar en sierra cinta", tipo_maquina="Sierra cinta")
        self.m_torno = OperacionMadre.objects.create(nombre="Maquinar en torno convencional", tipo_maquina="Torno convencional")
        self.m_cnc = OperacionMadre.objects.create(nombre="Maquinar en torno CNC", tipo_maquina="Torno CNC")
        self.m_barrenar = OperacionMadre.objects.create(nombre="Barrenar", tipo_maquina="Torno convencional")
        self.m_emp = OperacionMadre.objects.create(nombre="Empaquetar", tipo_maquina="Tarea manual")

        self.cortar = self.op(self.m_cortar, "Cortar varilla 5/16-3/8 · M8-M10 · inox-304", "0.855")
        self.carear = self.op(self.m_torno, "Carear y chaflanear tornillo 1/2-5/8 · M12-M16 · inox-304", "2.025")
        self.barrenar = self.op(self.m_barrenar, "Barrenar tornillo · inox-304", "0")
        self.refrentar = self.op(self.m_cnc, "Refrentar tocho 3\" · fierro-galv", "0")
        self.emp_chico = self.op(self.m_emp, "Empaquetar pedido chico", "0")
        TiempoFijo.objects.create(operacion=self.emp_chico, minutos=3, por_pedido=True)

        self.p5135 = self.pedido("5135", 1, [(4, "R-3 3/8 x 3 inox")])
        self.p5136 = self.pedido("5136", 4, [(20, "MKD-2 M16 x 150 inoxidable")])

    def op(self, madre, nombre, minpz):
        return OperacionDetallada.objects.create(madre=madre, nombre=nombre, minutos_estandar=Decimal(minpz))

    def pedido(self, numero, dias, partidas):
        p = Pedido.objects.create(numero=numero, fecha_salida=self.hoy + timedelta(days=dias))
        for cant, desc in partidas:
            PartidaPedido.objects.create(pedido=p, cantidad=cant, descripcion=desc)
        p.actualizar_resumen()
        return p

    def tarea(self, detallada, cantidad, pedido=None, partida=None, paso=1, quien=None, maquina=None, **extra):
        return ItemDesignacion.objects.create(
            designacion=self.dia, pedido=pedido, partida=partida, paso=paso, quien=quien,
            operacion_madre=detallada.madre, operacion_detallada=detallada, cantidad=cantidad,
            maquina=maquina, **extra,
        )

    def recargar(self, t):
        return ItemDesignacion.objects.get(pk=t.pk)


class MinutosYHechasTests(BaseDesignacion):

    def test_redondeo_como_la_hoja(self):
        self.assertEqual(redondear(Decimal("40.5")), 41)  # round() de Python daría 40
        self.assertEqual(self.tarea(self.cortar, 4).minutos, 3)  # 3.42 → 3

    def test_carear_hechas_y_check(self):
        t = self.tarea(self.carear, 20)
        self.assertEqual(t.minutos, 41)

        t.poner_hechas(8)
        t = self.recargar(t)
        self.assertEqual((t.faltan, t.min_restantes, t.min_hechos_hoy), (12, 24, 17))
        self.assertFalse(t.hecho)

        t.poner_hechas(20)  # al llegar al total se pone la ✓ sola
        t = self.recargar(t)
        self.assertTrue(t.hecho)
        self.assertEqual((t.min_restantes, t.min_hechos_hoy), (0, 41))

        t.poner_hechas(19)  # si baja, la ✓ se quita
        t = self.recargar(t)
        self.assertFalse(t.hecho)

    def test_quitar_check_regresa_hechas(self):
        t = self.tarea(self.carear, 20)
        t.poner_hechas(8)
        t = self.recargar(t)
        t.poner_check(True)
        self.assertEqual(self.recargar(t).piezas_hechas, 20)
        t = self.recargar(t)
        t.poner_check(False)
        self.assertEqual(self.recargar(t).piezas_hechas, 8)

    def test_empaquetar_por_pedido_sin_hechas(self):
        t = self.tarea(self.emp_chico, 4, pedido=self.p5135, paso=7)
        self.assertEqual(t.minutos, 3)  # no 12
        self.assertFalse(t.lleva_hechas)

    def test_sin_tiempo_suma_cero(self):
        t = self.tarea(self.barrenar, 20)
        self.assertEqual(t.minutos, 0)
        self.assertTrue(t.sin_tiempo)

    def test_tarea_especial(self):
        madre, _ = OperacionMadre.objects.get_or_create(nombre=TAREA_ESPECIAL[0])
        especial, _ = OperacionDetallada.objects.get_or_create(madre=madre, nombre=TAREA_ESPECIAL[1])
        t = self.tarea(especial, 40, maquina=self.esmeril, min_estimado_pz=Decimal("0.5"))
        self.assertEqual(t.minutos, 20)
        self.assertFalse(t.lleva_hechas)
        t2 = self.tarea(especial, 1, min_estimado_pz=Decimal("30"))
        self.assertEqual(t2.minutos, 30)
        tareas = reglas.preparar([t])
        self.assertEqual(tareas[0].marca_maquina, "")  # nunca rojo ni naranja

    def test_cambiar_cantidad_recalcula_min(self):
        t = self.tarea(self.carear, 20)
        t.cantidad = 10
        t.save()
        self.assertEqual(self.recargar(t).minutos, redondear(Decimal("2.025") * 10))


class EstadosYMarcasTests(BaseDesignacion):

    def test_estados_por_partida_y_empaquetar(self):
        partida = self.p5135.partidas.first()
        pasos = [self.tarea(self.cortar, 4, self.p5135, partida, paso=n) for n in range(1, 7)]
        emp = self.tarea(self.emp_chico, 4, self.p5135, None, paso=7)
        for t in pasos[:4]:
            t.poner_check(True)
        estados = {t.paso: t.estado_texto for t in reglas.preparar(reglas.tareas_activas())}
        self.assertEqual([estados[n] for n in range(1, 5)], ["Hecha"] * 4)
        self.assertEqual(estados[5], "Lista")
        self.assertEqual((estados[6], estados[7]), ("Espera paso anterior", "Espera paso anterior"))
        self.assertIsNotNone(emp)

    def test_en_proceso_manda(self):
        partida = self.p5136.partidas.first()
        self.tarea(self.cortar, 20, self.p5136, partida, paso=1)
        t2 = self.tarea(self.carear, 20, self.p5136, partida, paso=2)
        t2.poner_hechas(8)
        estados = {t.paso: t.estado_texto for t in reglas.preparar(reglas.tareas_activas())}
        self.assertEqual(estados[2], "En proceso")

    def test_stock_maquina_en_rojo(self):
        t = self.tarea(self.refrentar, 100, quien=self.angel)
        fila = reglas.preparar([t])[0]
        self.assertEqual((fila.estado_texto, fila.marca_maquina, fila.alerta_info), ("Lista", "rojo", None))
        self.assertEqual([m.nombre for m in fila.opciones_maquina], ["Torno CNC Hermabro", "Torno CNC Universal"])

    def test_naranja_material_y_maquina(self):
        p = self.pedido("5134", 5, [(8, "MR-400 M20 x 150 galvanizado")])
        t = self.tarea(self.cortar, 8, p, p.partidas.first(), maquina=self.torno)
        fila = reglas.preparar([t])[0]
        self.assertIn("inox-304", fila.marca_operacion)
        self.assertEqual(fila.marca_maquina, "naranja")

    def test_maquina_sola(self):
        self.assertEqual(self.m_cortar.maquina_sola(), self.sierra)
        self.assertIsNone(self.m_cnc.maquina_sola())  # dos tornos CNC: hay que escoger


class TarjetasYOrdenTests(BaseDesignacion):

    def test_tarjetas_y_carga_por_persona(self):
        partida = self.p5136.partidas.first()
        hecha = self.tarea(self.cortar, 4, self.p5135, self.p5135.partidas.first(), quien=self.vilchis)
        hecha.poner_check(True)
        carear = self.tarea(self.carear, 20, self.p5136, partida, paso=2, quien=self.noe)
        carear.poner_hechas(8)
        self.tarea(self.barrenar, 20, self.p5136, partida, paso=3)  # sin asignar, sin tiempo

        tareas = reglas.preparar(reglas.tareas_activas())
        t = reglas.tarjetas(tareas)
        self.assertEqual((t["tareas"], t["con_check"], t["en_proceso"], t["sin_tiempo"]), (3, 1, 1, 1))
        self.assertEqual((t["min_asignados"], t["min_hechos"], t["sin_asignar_tareas"]), (44, 20, 1))
        self.assertEqual(t["avance"], 45)

        carga = {f["operario"].nombre: f for f in reglas.carga_por_persona(tareas, 510)}
        self.assertEqual((carga["Noe"]["asignados"], carga["Noe"]["hechos"], carga["Noe"]["libres"]), (41, 17, 469))
        self.assertEqual(carga["Angel"]["libres"], 510)  # sale aunque no tenga tareas

    def test_orden_por_urgencia(self):
        stock = self.tarea(self.refrentar, 100)
        b = self.tarea(self.cortar, 20, self.p5136, self.p5136.partidas.first())
        a = self.tarea(self.cortar, 4, self.p5135, self.p5135.partidas.first())
        orden = reglas.ordenar(reglas.preparar(reglas.tareas_activas()), "urgencia")
        self.assertEqual([t.pk for t in orden], [a.pk, b.pk, stock.pk])

    def test_pantalla_y_ocultar_no_cambia_tarjetas(self):
        self.tarea(self.cortar, 4, self.p5135, self.p5135.partidas.first())
        r = self.client.get(reverse("designaciones:hoy"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["tarjetas"]["tareas"], 1)


class NuevoDiaTests(BaseDesignacion):

    def test_arrastre_del_avance(self):
        partida = self.p5136.partidas.first()
        hecha = self.tarea(self.cortar, 20, self.p5136, partida, paso=1, quien=self.vilchis)
        hecha.poner_check(True)
        carear = self.tarea(self.carear, 20, self.p5136, partida, paso=2, quien=self.noe, detalle="Carear a 15 cm")
        carear.poner_hechas(8)
        sin_avance = self.tarea(self.barrenar, 20, self.p5136, partida, paso=3)
        total_antes = Pedido.objects.con_minutos().get(pk=self.p5136.pk).min_total

        siguiente, archivadas, con_avance, sin = cerrar_dia()
        self.assertEqual((archivadas, con_avance, sin), (1, 1, 1))

        # Lo de hoy queda archivado: 8 pzas · 17 min
        archivado = self.recargar(carear)
        self.assertEqual((archivado.cierre, archivado.piezas_dia, archivado.minutos), ("AVANCE", 8, 17))
        self.assertEqual(archivado.fecha_cierre, self.hoy)

        # Mañana amanece con 12 pzas y 24 min, con su persona y detalle
        activas = list(reglas.tareas_activas())
        self.assertEqual(len(activas), 2)
        nueva = next(t for t in activas if t.operacion_detallada_id == self.carear.pk)
        self.assertEqual((nueva.faltan, nueva.minutos, nueva.quien, nueva.detalle), (12, 24, self.noe, "Carear a 15 cm"))
        self.assertEqual(nueva.designacion.fecha, siguiente)
        self.assertTrue(any(t.operacion_detallada_id == self.barrenar.pk for t in activas))
        self.assertIsNotNone(sin_avance)

        # El Min total del pedido no se mueve al cerrar el día
        self.assertEqual(Pedido.objects.con_minutos().get(pk=self.p5136.pk).min_total, total_antes)

        # Al día siguiente, terminar carear: se archivan 12 pzas · 24 min (20 pzas · 41 min entre los dos)
        nueva.poner_hechas(20)
        cerrar_dia()
        final = self.recargar(nueva)
        self.assertEqual((final.piezas_dia, final.minutos, final.cierre), (12, 24, "CHECK"))
        self.assertEqual(archivado.piezas_dia + final.piezas_dia, 20)
        self.assertEqual(archivado.minutos + final.minutos, 41)

    def test_vacia_moldes(self):
        self.dia.molde_1, self.dia.molde_2 = "M-338", "SPORT"
        self.dia.save()
        siguiente, *_ = cerrar_dia()
        nuevo = DesignacionDia.objects.get(fecha=siguiente)
        self.assertEqual((nuevo.molde_1, nuevo.molde_2), ("", ""))


class PedidosDesdeDesignacionTests(BaseDesignacion):

    def test_estatus_en_proceso_con_el_primer_avance(self):
        t = self.tarea(self.carear, 20, self.p5136, self.p5136.partidas.first())
        self.client.post(reverse("designaciones:guardar_campo", args=[t.pk]), {"campo": "piezas_hechas", "valor": "8"})
        self.p5136.refresh_from_db()
        self.assertEqual(self.p5136.estado, Pedido.Estado.EN_PROCESO)

    def test_min_restante_y_avance_del_pedido(self):
        t = self.tarea(self.carear, 20, self.p5136, self.p5136.partidas.first())
        t.poner_hechas(8)
        p = Pedido.objects.con_minutos().get(pk=self.p5136.pk)
        self.assertEqual((p.min_total, p.min_restante), (41, 24))

    def test_palomear_paso_7_antes_que_5_y_6(self):
        partida = self.p5135.partidas.first()
        tareas = [self.tarea(self.cortar, 4, self.p5135, partida, paso=n) for n in range(1, 7)]
        emp = self.tarea(self.emp_chico, 4, self.p5135, None, paso=7)
        self.client.post(reverse("designaciones:toggle_hecho", args=[emp.pk]))
        self.p5135.refresh_from_db()
        self.assertEqual(self.p5135.estado, Pedido.Estado.EN_PROCESO)
        for t in tareas:
            self.client.post(reverse("designaciones:toggle_hecho", args=[t.pk]))
        self.p5135.refresh_from_db()
        self.assertEqual(self.p5135.estado, Pedido.Estado.TERMINADO)

    def test_cant_sigue_a_la_partida_salvo_a_mano(self):
        partida = self.p5136.partidas.first()
        auto = self.tarea(self.carear, 20, self.p5136, partida)
        mano = self.tarea(self.cortar, 20, self.p5136, partida, cantidad_manual=True)
        partida.cantidad = 30
        partida.save()
        self.p5136.actualizar_resumen()
        self.assertEqual((self.recargar(auto).cantidad, self.recargar(mano).cantidad), (30, 20))


class AccionesTests(BaseDesignacion):

    def test_validaciones_de_hechas_y_cant(self):
        t = self.tarea(self.carear, 20)
        url = reverse("designaciones:guardar_campo", args=[t.pk])
        ajax = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        self.assertEqual(self.client.post(url, {"campo": "piezas_hechas", "valor": "21"}, **ajax).status_code, 400)
        self.client.post(url, {"campo": "piezas_hechas", "valor": "8"}, **ajax)
        self.assertEqual(self.client.post(url, {"campo": "cantidad", "valor": "5"}, **ajax).status_code, 400)
        r = self.client.post(url, {"campo": "cantidad", "valor": "10"}, **ajax)
        self.assertTrue(r.json()["ok"])
        self.assertIn("tabla", r.json())
        self.assertTrue(self.recargar(t).cantidad_manual)

    def test_quitar_y_deshacer(self):
        t = self.tarea(self.cortar, 4)
        self.client.post(reverse("designaciones:quitar_seleccionadas"), {"item_ids": [t.pk]})
        self.assertFalse(ItemDesignacion.objects.filter(pk=t.pk).exists())
        self.client.post(reverse("designaciones:deshacer_quitar"))
        self.assertTrue(ItemDesignacion.objects.filter(pk=t.pk).exists())

    def test_asignar_persona(self):
        t = self.tarea(self.cortar, 4)
        self.client.post(reverse("designaciones:asignar_persona"), {"item_ids": [t.pk], "quien": self.noe.pk})
        self.assertEqual(self.recargar(t).quien, self.noe)

    def test_agregar_tarea_stock(self):
        r = self.client.post(reverse("designaciones:agregar_item"), {
            "operacion_madre": self.m_cnc.pk, "operacion_detallada": self.refrentar.pk,
            "cantidad": 100, "detalle": "Para stock", "quien": self.angel.pk,
        })
        self.assertEqual(r.status_code, 302)
        t = ItemDesignacion.objects.get(operacion_detallada=self.refrentar)
        self.assertTrue(t.es_stock)
        self.assertIsNone(t.maquina)  # dos tornos CNC: queda en rojo

    def test_agregar_valida_detallada_de_la_madre(self):
        self.client.post(reverse("designaciones:agregar_item"), {
            "operacion_madre": self.m_cnc.pk, "operacion_detallada": self.cortar.pk, "cantidad": 1,
        })
        self.assertFalse(ItemDesignacion.objects.exists())

    def test_imprimir_y_exportar(self):
        self.tarea(self.cortar, 4, self.p5135, self.p5135.partidas.first())
        self.assertContains(self.client.get(reverse("designaciones:imprimir_lista")), "counter(pages)")
        r = self.client.get(reverse("designaciones:exportar_excel"))
        self.assertEqual(r["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_permisos(self):
        captura = User.objects.create_user("denisse", password="Clave-segura-123")
        captura.user_permissions.add(Permission.objects.get(codename="imprimir_designacion"))
        self.client.force_login(captura)
        t = self.tarea(self.cortar, 4)
        r = self.client.post(reverse("designaciones:toggle_hecho", args=[t.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post(reverse("designaciones:nuevo_dia")).status_code, 302)
        self.assertTrue(DesignacionDia.objects.filter(cerrada=False, pk=self.dia.pk).exists())
        self.assertEqual(self.client.get(reverse("designaciones:exportar_excel")).status_code, 200)


class CargarRutaTests(BaseDesignacion):

    def cargar(self, datos):
        return self.client.post(reverse("designaciones:cargar_ruta"), json.dumps(datos), content_type="application/json")

    def test_crea_tareas_y_un_empaquetar(self):
        p = self.pedido("5134", 5, [(16, "M-338 M16 x 150 inox"), (8, "MR-400 M20 x 150 galvanizado")])
        p1, p2 = p.partidas.all()
        datos = {
            "pedido_id": p.pk,
            "partidas": [
                {"partida_id": p1.pk, "pasos": [
                    {"orden": 1, "madre": "Cortar en sierra cinta", "detallada": self.cortar.nombre, "maquina": "Sierra cinta universal"},
                    {"orden": 2, "madre": "Maquinar en torno convencional", "detallada": self.carear.nombre, "maquina": ""},
                ]},
                {"partida_id": p2.pk, "pasos": [
                    {"orden": 1, "madre": "Cortar en sierra cinta", "detallada": "Cortar varilla 3/4-1\" · M20-M24 · fierro-galv", "maquina": "Sierra cinta universal"},
                ]},
            ],
            "empaquetar": {"madre": "Empaquetar", "detallada": "Empaquetar pedido chico", "maquina": "Tarea manual"},
        }
        r = self.cargar(datos)
        self.assertTrue(r.json()["ok"])
        tareas = ItemDesignacion.objects.filter(pedido=p)
        self.assertEqual(tareas.count(), 4)
        emp = tareas.get(operacion_detallada=self.emp_chico)
        self.assertEqual((emp.partida, emp.cantidad, emp.paso, emp.minutos), (None, 24, 3, 3))
        self.assertTrue(all(t.quien_id is None and t.detalle == "" for t in tareas))
        self.assertEqual(tareas.get(partida=p1, paso=1).cantidad, 16)
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.EN_ESPERA)  # sigue EN ESPERA hasta la primera ✓ o avance

        # Ya cargada: pide confirmar
        r = self.cargar(datos)
        self.assertTrue(r.json().get("confirmar"))
        self.assertEqual(tareas.count(), 4)
        self.assertTrue(self.cargar({**datos, "confirmar": True}).json()["ok"])

    def test_minutos_de_la_vista_previa(self):
        r = self.client.post(
            reverse("designaciones:api_minutos_ruta"),
            json.dumps([{"madre": self.m_torno.nombre, "detallada": self.carear.nombre, "cantidad": 20},
                        {"madre": "Barrenar", "detallada": self.barrenar.nombre, "cantidad": 20}]),
            content_type="application/json",
        )
        self.assertEqual(r.json()["minutos"], [41, None])
