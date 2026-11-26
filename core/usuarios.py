"""
Configuración › Usuarios: alta, edición, contraseña, baja y reactivación.

Tres roles (grupos de Django con los permisos que ya usa cada pantalla):
- Administrador: todo el sistema, incluido administrar usuarios.
- Captura: ve todo, imprime y exporta (Denisse).
- Trabajador: solo «Mi lista de hoy» en su celular; va ligado a su persona de Catálogos.

Dar de baja = desactivar la cuenta (no se borra): así se conserva quién hizo cada cosa
en las bitácoras, y se puede reactivar.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, password_validation, update_session_auth_hash
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from designaciones.models import Operario

User = get_user_model()
GESTIONAR = "auth.change_user"

ADMINISTRADOR, CAPTURA, TRABAJADOR = "administrador", "captura", "trabajador"
ROLES = {
    ADMINISTRADOR: "Administrador",
    CAPTURA: "Captura",
    TRABAJADOR: "Trabajador",
}
DESCRIPCION_ROL = {
    ADMINISTRADOR: "Todo el sistema: Pedidos, Designación (rutas, ✓, Nuevo día), Catálogos, Eficiencia, Archivo y usuarios.",
    CAPTURA: "Ve todo el sistema e imprime y exporta. No cambia datos de Designación.",
    TRABAJADOR: "Solo «Mi lista de hoy» en su celular: palomea sus tareas y anota piezas.",
}

# Permisos de cada rol (app_label.codename). Son los que ya revisan las pantallas.
PERMISOS_ROL = {
    ADMINISTRADOR: [
        "designaciones.editar_designacion", "designaciones.palomear_designacion",
        "designaciones.cerrar_dia", "designaciones.imprimir_designacion",
        "designaciones.change_familiaruta", "designaciones.change_pasoruta",
        "designaciones.add_pasoruta", "designaciones.delete_pasoruta", "designaciones.view_familiaruta",
        "designaciones.view_pasoruta",
        "pedidos.palomear_seguimiento", "pedidos.desarchivar_pedido", "pedidos.exportar_tareas",
        "eficiencia.capturar_tiempos", "eficiencia.cambiar_estandar", "eficiencia.ver_direccion",
        "tiempos.administrar_estudio",
        "auth.add_user", "auth.change_user", "auth.view_user",
    ],
    CAPTURA: [
        "designaciones.imprimir_designacion",
        "pedidos.exportar_tareas",
    ],
    TRABAJADOR: [],
}
NOMBRE_GRUPO = {ADMINISTRADOR: "Administrador", CAPTURA: "Captura", TRABAJADOR: "Trabajador"}


def asegurar_grupos():
    """Crea (o pone al día) los grupos de cada rol con sus permisos."""
    grupos = {}
    for rol, permisos in PERMISOS_ROL.items():
        grupo, _ = Group.objects.get_or_create(name=NOMBRE_GRUPO[rol])
        objetos = []
        for completo in permisos:
            app, codename = completo.split(".")
            permiso = Permission.objects.filter(content_type__app_label=app, codename=codename).first()
            if permiso:
                objetos.append(permiso)
        grupo.permissions.set(objetos)
        grupos[rol] = grupo
    return grupos


def rol_de(user):
    nombres = set(user.groups.values_list("name", flat=True))
    for rol, nombre in NOMBRE_GRUPO.items():
        if nombre in nombres:
            return rol
    if user.is_superuser:
        return ADMINISTRADOR
    if hasattr(user, "operario") and user.operario:
        return TRABAJADOR
    return None


def asignar_rol(user, rol):
    grupos = asegurar_grupos()
    user.groups.remove(*grupos.values())
    user.groups.add(grupos[rol])
    # El editor de rutas de Catálogos pide staff; solo el Administrador lo es (y el superusuario)
    user.is_staff = user.is_superuser or rol == ADMINISTRADOR
    user.save(update_fields=["is_staff"])


def administradores_activos():
    return User.objects.filter(is_active=True).filter(is_superuser=True) | \
        User.objects.filter(is_active=True, groups__name=NOMBRE_GRUPO[ADMINISTRADOR])


def nombre_persona(datos):
    return f"{datos.get('first_name', '')} {datos.get('last_name', '')}".strip()


def persona_para(user, nombre):
    """La persona con ese nombre que aún no tenga cuenta (aunque esté inactiva); si no hay, se crea."""
    existente = Operario.objects.filter(usuario__isnull=True, nombre__iexact=nombre).first() \
        or Operario.objects.filter(usuario=user).first()
    if existente:
        return existente
    return Operario.objects.create(nombre=nombre)


def sugerir_usuario(nombre):
    """«Ángel Pérez» → «angel.perez» (sin acentos ni espacios), sin repetir."""
    import unicodedata
    base = unicodedata.normalize("NFD", nombre.lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    base = ".".join("".join(c for c in parte if c.isalnum()) for parte in base.split()) or "usuario"
    base = base.strip(".")[:140] or "usuario"
    candidato, n = base, 2
    while User.objects.filter(username__iexact=candidato).exists():
        candidato, n = f"{base}{n}", n + 1
    return candidato


# ---------------------------------------------------------------- formularios

def _clases(form):
    for campo in form.fields.values():
        clase = "form-select" if isinstance(campo.widget, forms.Select) else "form-control"
        campo.widget.attrs.setdefault("class", clase)


class UsuarioForm(forms.Form):
    """Alta y edición. En la edición no se piden contraseñas (hay un botón aparte)."""

    username = forms.CharField(
        label="Usuario", max_length=150,
        help_text="Con este nombre entra. Sin espacios: letras, números y . _ -",
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "none", "placeholder": "ej. ernesto"}),
    )
    first_name = forms.CharField(label="Nombre", max_length=150, widget=forms.TextInput(attrs={"placeholder": "ej. Ernesto"}))
    last_name = forms.CharField(label="Apellido", max_length=150, required=False)
    rol = forms.ChoiceField(label="Rol", choices=ROLES.items(), widget=forms.RadioSelect)
    persona = forms.ModelChoiceField(
        label="Persona de Catálogos", queryset=Operario.objects.none(), required=False,
        help_text="Trabajador: si la dejas vacía, se crea sola con su nombre (o se liga a la que ya se llame así).",
    )
    password1 = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repite la contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        libres = Operario.objects.filter(activo=True, usuario__isnull=True)
        if usuario and hasattr(usuario, "operario"):
            libres = libres | Operario.objects.filter(pk=usuario.operario.pk)
        self.fields["persona"].queryset = libres.order_by("orden", "nombre")
        self.fields["persona"].empty_label = "— ninguna —"
        if usuario:
            del self.fields["password1"]
            del self.fields["password2"]
        _clases(self)
        self.fields["rol"].widget.attrs.pop("class", None)

    def clean_username(self):
        nombre = self.cleaned_data["username"].strip()
        try:
            User.username_validator(nombre)
        except ValidationError:
            raise ValidationError("Solo letras, números y . _ - (sin espacios).")
        existe = User.objects.filter(username__iexact=nombre)
        if self.usuario:
            existe = existe.exclude(pk=self.usuario.pk)
        if existe.exists():
            raise ValidationError("Ya hay un usuario con ese nombre.")
        return nombre

    def clean(self):
        datos = super().clean()
        # Trabajador sin persona elegida: se crea sola con su nombre, salvo que ese nombre ya sea de otro usuario
        if datos.get("rol") == TRABAJADOR and not datos.get("persona") and datos.get("first_name"):
            ocupada = Operario.objects.filter(nombre__iexact=nombre_persona(datos), usuario__isnull=False)
            if self.usuario:
                ocupada = ocupada.exclude(usuario=self.usuario)
            if ocupada.exists():
                self.add_error("first_name", f"Ya hay una persona «{nombre_persona(datos)}» con otra cuenta: "
                                             "agrega el apellido para distinguirla.")
        if self.usuario and datos.get("rol") != ADMINISTRADOR and rol_de(self.usuario) == ADMINISTRADOR \
                and not self.usuario.is_superuser and administradores_activos().distinct().count() <= 1:
            self.add_error("rol", "Es el único administrador: primero da de alta otro.")
        uno, dos = datos.get("password1"), datos.get("password2")
        if "password1" in self.fields and uno and dos:
            if uno != dos:
                self.add_error("password2", "Las contraseñas no coinciden.")
            else:
                provisional = User(username=datos.get("username", ""), first_name=datos.get("first_name", ""))
                try:
                    password_validation.validate_password(uno, provisional)
                except ValidationError as e:
                    self.add_error("password1", e)
        return datos

    @transaction.atomic
    def guardar(self):
        datos = self.cleaned_data
        user = self.usuario or User()
        user.username = datos["username"]
        user.first_name = datos["first_name"].strip()
        user.last_name = datos.get("last_name", "").strip()
        if not self.usuario:
            user.set_password(datos["password1"])
        user.save()
        asignar_rol(user, datos["rol"])

        # Persona de Catálogos: el trabajador siempre tiene una (se crea sola si no se eligió)
        persona = datos.get("persona")
        if not persona and datos["rol"] == TRABAJADOR:
            persona = persona_para(user, nombre_persona(datos))
        anterior = Operario.objects.filter(usuario=user).exclude(pk=getattr(persona, "pk", None))
        anterior.update(usuario=None)
        if persona:
            persona.usuario = user
            persona.activo = user.is_active
            persona.save(update_fields=["usuario", "activo"])
        return user


class ContrasenaForm(forms.Form):
    password1 = forms.CharField(label="Contraseña nueva", strip=False,
                                widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repite la contraseña", strip=False,
                                widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}))

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario

    def clean(self):
        datos = super().clean()
        uno, dos = datos.get("password1"), datos.get("password2")
        if uno and dos:
            if uno != dos:
                self.add_error("password2", "Las contraseñas no coinciden.")
            else:
                try:
                    password_validation.validate_password(uno, self.usuario)
                except ValidationError as e:
                    self.add_error("password1", e)
        return datos


# ---------------------------------------------------------------- vistas

solo_administra = permission_required(GESTIONAR, raise_exception=True)


@solo_administra
def lista(request):
    asegurar_grupos()
    usuarios = list(User.objects.prefetch_related("groups").select_related("operario").order_by("-is_active", "username"))
    for u in usuarios:
        u.rol_clave = rol_de(u)
        u.rol_nombre = ROLES.get(u.rol_clave, "Sin rol")
        u.persona = getattr(u, "operario", None) if hasattr(u, "operario") else None
    activos = [u for u in usuarios if u.is_active]
    sin_cuenta = Operario.objects.filter(usuario__isnull=True, activo=True).order_by("orden", "nombre")
    return render(request, "core/usuarios/lista.html", {
        "usuarios": usuarios,
        "sin_cuenta": sin_cuenta,
        "conteo": {
            "activos": len(activos),
            "administradores": sum(1 for u in activos if u.rol_clave == ADMINISTRADOR),
            "captura": sum(1 for u in activos if u.rol_clave == CAPTURA),
            "trabajadores": sum(1 for u in activos if u.rol_clave == TRABAJADOR),
            "bajas": len(usuarios) - len(activos),
        },
    })


@solo_administra
def nuevo(request):
    inicial = {"rol": TRABAJADOR}
    # «Crear usuario» desde una persona sin cuenta: ya viene su nombre y su persona
    persona_id = request.GET.get("persona", "")
    persona = Operario.objects.filter(pk=persona_id, usuario__isnull=True).first() if persona_id.isdigit() else None
    if persona:
        partes = persona.nombre.split(" ", 1)
        inicial.update({"first_name": partes[0], "last_name": partes[1] if len(partes) > 1 else "",
                        "persona": persona, "username": sugerir_usuario(persona.nombre)})
    form = UsuarioForm(request.POST or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        user = form.guardar()
        messages.success(request, f"Usuario «{user.username}» dado de alta como {ROLES[form.cleaned_data['rol']]}.")
        return redirect("core:usuarios")
    return render(request, "core/usuarios/form.html", {
        "form": form, "titulo": "Alta de usuario", "roles": DESCRIPCION_ROL,
    })


@solo_administra
def editar(request, pk):
    user = get_object_or_404(User, pk=pk)
    persona = user.operario if hasattr(user, "operario") else None
    inicial = {
        "username": user.username, "first_name": user.first_name, "last_name": user.last_name,
        "rol": rol_de(user) or CAPTURA, "persona": persona,
    }
    form = UsuarioForm(request.POST or None, initial=inicial, usuario=user)
    if request.method == "POST" and form.is_valid():
        form.guardar()
        messages.success(request, f"Usuario «{user.username}» actualizado.")
        return redirect("core:usuarios")
    return render(request, "core/usuarios/form.html", {
        "form": form, "titulo": f"Editar · {user.username}", "usuario": user, "roles": DESCRIPCION_ROL,
    })


@solo_administra
def contrasena(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = ContrasenaForm(request.POST or None, usuario=user)
    if request.method == "POST" and form.is_valid():
        user.set_password(form.cleaned_data["password1"])
        user.save(update_fields=["password"])
        if user == request.user:
            update_session_auth_hash(request, user)  # no lo saca de su propia sesión
        messages.success(request, f"Contraseña de «{user.username}» cambiada.")
        return redirect("core:usuarios")
    return render(request, "core/usuarios/contrasena.html", {"form": form, "usuario": user})


@require_POST
@solo_administra
def baja(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "No puedes darte de baja a ti mismo.")
    elif rol_de(user) == ADMINISTRADOR and administradores_activos().exclude(pk=user.pk).distinct().count() == 0:
        messages.error(request, "Es el único administrador activo: primero da de alta otro.")
    else:
        user.is_active = False
        user.save(update_fields=["is_active"])
        # Su persona deja de salir en Designación para asignarle tareas
        Operario.objects.filter(usuario=user).update(activo=False)
        messages.success(request, f"«{user.username}» dado de baja: ya no puede entrar ni recibir tareas. Su historial se conserva.")
    return redirect("core:usuarios")


@require_POST
@solo_administra
def reactivar(request, pk):
    user = get_object_or_404(User, pk=pk)
    user.is_active = True
    user.save(update_fields=["is_active"])
    Operario.objects.filter(usuario=user).update(activo=True)
    messages.success(request, f"«{user.username}» reactivado: ya puede entrar otra vez.")
    return redirect("core:usuarios")
