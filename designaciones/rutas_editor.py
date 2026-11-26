"""
Catálogos › Rutas de producción: editor propio (ya no se usa el admin de Django).

Familias (qué modelos reconoce el motor) y sus pasos (operación, condición, nota).
Los cambios aplican a las rutas que se carguen desde ese momento: lo ya cargado en
Designación no cambia. Lo lee el motor por /designacion/api/catalogo-rutas/.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import FamiliaRuta, OperacionMadre, PasoRuta

EDITAR_RUTAS = "designaciones.change_pasoruta"
editor = permission_required(EDITAR_RUTAS, raise_exception=True)


class FamiliaForm(forms.ModelForm):
    class Meta:
        model = FamiliaRuta
        fields = ["nombre", "modelos", "descripcion", "orden", "activa"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Nivelador con base troquelada (MT)"}),
            "modelos": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "MT-1, MT-2, MTA-"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "orden": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PasoForm(forms.ModelForm):
    class Meta:
        model = PasoRuta
        fields = ["orden", "madre", "detallada", "condicion", "nota", "activo"]
        widgets = {
            "orden": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "madre": forms.Select(attrs={"class": "form-select"}),
            "detallada": forms.TextInput(attrs={"class": "form-control", "placeholder": "Cortar varilla {rango} · {mat}"}),
            "condicion": forms.TextInput(attrs={"class": "form-control", "placeholder": "tornillo=no;d>=3/4"}),
            "nota": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, familia, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.familia = familia
        self.fields["madre"].queryset = OperacionMadre.objects.filter(activa=True).order_by("nombre")
        if self.instance.madre_id:
            self.fields["madre"].queryset |= OperacionMadre.objects.filter(pk=self.instance.madre_id)
        if not self.instance.pk:
            ultimo = familia.pasos.order_by("-orden").values_list("orden", flat=True).first() if familia.pk else None
            self.fields["orden"].initial = (ultimo or 0) + 1


# ---------------------------------------------------------------- familias

@editor
def lista(request):
    q = (request.GET.get("q") or "").strip()
    familias = FamiliaRuta.objects.annotate(
        pasos_activos=Count("pasos", filter=Q(pasos__activo=True)),
        pasos_total=Count("pasos"),
    ).order_by("orden", "nombre")
    if q:
        familias = familias.filter(Q(nombre__icontains=q) | Q(modelos__icontains=q) | Q(descripcion__icontains=q))
    familias = list(familias)
    return render(request, "designaciones/rutas/lista.html", {
        "familias": familias,
        "q": q,
        "activas": sum(1 for f in familias if f.activa),
        "total_pasos": PasoRuta.objects.filter(activo=True, familia__activa=True).count(),
    })


@editor
def familia_nueva(request):
    form = FamiliaForm(request.POST or None, initial={"activa": True, "orden": (FamiliaRuta.objects.count() + 1)})
    if request.method == "POST" and form.is_valid():
        familia = form.save()
        messages.success(request, f"Familia «{familia.nombre}» creada. Ahora agrega sus pasos.")
        return redirect("core:ruta_familia", pk=familia.pk)
    return render(request, "designaciones/rutas/familia.html", {"form": form, "familia": None})


@editor
def familia(request, pk):
    familia = get_object_or_404(FamiliaRuta, pk=pk)
    form = FamiliaForm(request.POST or None, instance=familia)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Familia «{familia.nombre}» guardada.")
        return redirect("core:ruta_familia", pk=familia.pk)
    pasos = familia.pasos.select_related("madre").order_by("orden", "pk")
    return render(request, "designaciones/rutas/familia.html", {"form": form, "familia": familia, "pasos": pasos})


# ---------------------------------------------------------------- pasos

@editor
def paso(request, familia_pk, pk=None):
    familia = get_object_or_404(FamiliaRuta, pk=familia_pk)
    instancia = get_object_or_404(PasoRuta, pk=pk, familia=familia) if pk else None
    form = PasoForm(request.POST or None, instance=instancia, familia=familia,
                    initial=None if instancia else {"activo": True})
    if request.method == "POST" and form.is_valid():
        guardado = form.save()
        messages.success(request, f"Paso {guardado.orden} guardado.")
        return redirect("core:ruta_familia", pk=familia.pk)
    return render(request, "designaciones/rutas/paso.html", {"form": form, "familia": familia, "paso": instancia})


@require_POST
@editor
def paso_activo(request, pk):
    """Prender o apagar un paso sin borrarlo (el motor deja de usarlo)."""
    paso = get_object_or_404(PasoRuta, pk=pk)
    paso.activo = not paso.activo
    paso.save(update_fields=["activo"])
    messages.success(request, f"Paso {paso.orden} {'activado' if paso.activo else 'desactivado'}.")
    return redirect("core:ruta_familia", pk=paso.familia_id)


@require_POST
@editor
def paso_quitar(request, pk):
    paso = get_object_or_404(PasoRuta, pk=pk)
    familia_pk, orden = paso.familia_id, paso.orden
    paso.delete()
    messages.success(request, f"Paso {orden} borrado. Lo ya cargado en Designación no cambia.")
    return redirect("core:ruta_familia", pk=familia_pk)
