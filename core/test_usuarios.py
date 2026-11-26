"""Configuración › Usuarios: alta, edición, contraseña, baja y reactivación."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from designaciones.models import Operario

from .usuarios import ADMINISTRADOR, CAPTURA, TRABAJADOR, asignar_rol, rol_de

CLAVE = "Clave-segura-123"


class UsuariosTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser("marcos", "m@inaher.mx", CLAVE)
        self.client.force_login(self.admin)

    def alta(self, **datos):
        base = {"username": "ernesto", "first_name": "Ernesto", "rol": TRABAJADOR,
                "password1": "Planta-2026-xyz", "password2": "Planta-2026-xyz"}
        return self.client.post(reverse("core:usuario_nuevo"), {**base, **datos})

    def test_lista_y_menu_solo_para_quien_administra(self):
        r = self.client.get(reverse("core:usuarios"))
        self.assertContains(r, "Alta de usuario")
        self.assertContains(self.client.get("/"), reverse("core:usuarios"))  # botón en la barra lateral

        captura = User.objects.create_user("denisse", password=CLAVE)
        asignar_rol(captura, CAPTURA)
        self.client.force_login(captura)
        self.assertEqual(self.client.get(reverse("core:usuarios")).status_code, 403)
        self.assertNotContains(self.client.get("/"), reverse("core:usuarios"))

    def test_alta_de_trabajador_crea_su_persona(self):
        r = self.alta()
        self.assertRedirects(r, reverse("core:usuarios"))
        user = User.objects.get(username="ernesto")
        self.assertEqual(rol_de(user), TRABAJADOR)
        self.assertEqual(user.operario.nombre, "Ernesto")
        self.assertFalse(user.is_staff)
        # Entra con su contraseña y llega a su lista
        self.client.logout()
        r = self.client.post(reverse("core:entrar"), {"username": "ernesto", "password": "Planta-2026-xyz"}, follow=True)
        self.assertEqual(r.request["PATH_INFO"], reverse("mi_lista"))

    def test_trabajador_se_liga_a_la_persona_que_ya_se_llama_asi(self):
        noe = Operario.objects.create(nombre="Noe")
        self.alta(username="noe", first_name="Noe")
        noe.refresh_from_db()
        self.assertEqual(noe.usuario.username, "noe")
        self.assertEqual(Operario.objects.filter(nombre__iexact="noe").count(), 1)

    def test_nombre_de_persona_ocupado_pide_apellido(self):
        self.alta()
        self.alta(username="ernesto2")  # otra cuenta con la misma persona «Ernesto»
        self.assertFalse(User.objects.filter(username="ernesto2").exists())
        self.alta(username="ernesto2", last_name="Ruiz")
        self.assertEqual(User.objects.get(username="ernesto2").operario.nombre, "Ernesto Ruiz")

    def test_personas_sin_cuenta_con_crear_usuario(self):
        vilchis = Operario.objects.create(nombre="Vilchis")
        r = self.client.get(reverse("core:usuarios"))
        self.assertContains(r, "Personas sin cuenta")
        self.assertContains(r, f"?persona={vilchis.pk}")
        r = self.client.get(reverse("core:usuario_nuevo"), {"persona": vilchis.pk})
        self.assertContains(r, 'value="vilchis"')

    def test_catalogos_ya_no_da_altas_ni_bajas_de_personas(self):
        self.client.post(reverse("core:guardar_catalogo", args=["operario"]), {"nombre": "Pirata", "orden": 0})
        self.assertFalse(Operario.objects.filter(nombre="Pirata").exists())
        noe = Operario.objects.create(nombre="Noe")
        self.client.post(reverse("core:eliminar_catalogo", args=["operario", noe.pk]))
        self.assertTrue(Operario.objects.filter(pk=noe.pk).exists())

    def test_alta_con_persona_existente(self):
        noe = Operario.objects.create(nombre="Noe")
        self.alta(username="noe", first_name="Noe", persona=noe.pk)
        noe.refresh_from_db()
        self.assertEqual(noe.usuario.username, "noe")

    def test_alta_de_administrador_y_captura(self):
        self.alta(username="victor", first_name="Víctor", rol=ADMINISTRADOR)
        victor = User.objects.get(username="victor")
        self.assertTrue(victor.has_perm("designaciones.cerrar_dia"))
        self.assertTrue(victor.has_perm("auth.change_user"))
        self.assertTrue(victor.is_staff)

        self.alta(username="denisse", first_name="Denisse", rol=CAPTURA)
        denisse = User.objects.get(username="denisse")
        self.assertTrue(denisse.has_perm("designaciones.imprimir_designacion"))
        self.assertFalse(denisse.has_perm("designaciones.palomear_designacion"))

    def test_validaciones(self):
        self.alta(username="con espacio")
        self.alta(username="corta", password1="123", password2="123")
        self.alta(username="distinta", password2="Otra-cosa-999")
        self.alta(username="MARCOS", rol=CAPTURA)  # ya existe (sin distinguir mayúsculas)
        self.assertEqual(User.objects.count(), 1)

    def test_editar_rol_y_persona(self):
        self.alta()
        user = User.objects.get(username="ernesto")
        r = self.client.post(reverse("core:usuario_editar", args=[user.pk]), {
            "username": "ernesto", "first_name": "Ernesto", "last_name": "Ruiz", "rol": CAPTURA, "persona": "",
        })
        self.assertRedirects(r, reverse("core:usuarios"))
        user.refresh_from_db()
        self.assertEqual((rol_de(user), user.last_name), (CAPTURA, "Ruiz"))
        self.assertFalse(Operario.objects.filter(usuario=user).exists())  # se liberó la persona

    def test_cambiar_contrasena(self):
        self.alta()
        user = User.objects.get(username="ernesto")
        self.client.post(reverse("core:usuario_contrasena", args=[user.pk]),
                         {"password1": "Nueva-Clave-777", "password2": "Nueva-Clave-777"})
        user.refresh_from_db()
        self.assertTrue(user.check_password("Nueva-Clave-777"))

    def test_baja_y_reactivar(self):
        self.alta()
        user = User.objects.get(username="ernesto")
        self.client.post(reverse("core:usuario_baja", args=[user.pk]))
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(Operario.objects.get(usuario=user).activo)  # ya no sale para asignarle tareas
        self.assertTrue(User.objects.filter(pk=user.pk).exists())  # no se borra
        self.assertFalse(self.client.login(username="ernesto", password="Planta-2026-xyz"))

        self.client.force_login(self.admin)
        self.client.post(reverse("core:usuario_reactivar", args=[user.pk]))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(Operario.objects.get(usuario=user).activo)

    def test_no_te_puedes_dar_de_baja(self):
        self.client.post(reverse("core:usuario_baja", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_no_se_queda_sin_administrador(self):
        victor = User.objects.create_user("victor", password=CLAVE)
        asignar_rol(victor, ADMINISTRADOR)
        self.admin.is_active = False  # el superusuario ya no está
        self.admin.save()
        self.client.force_login(victor)
        otro = User.objects.create_user("otro", password=CLAVE)
        asignar_rol(otro, CAPTURA)
        r = self.client.post(reverse("core:usuario_editar", args=[victor.pk]), {
            "username": "victor", "first_name": "Víctor", "rol": CAPTURA,
        })
        self.assertEqual(r.status_code, 200)  # no lo deja: es el único administrador
        self.assertEqual(rol_de(User.objects.get(pk=victor.pk)), ADMINISTRADOR)
