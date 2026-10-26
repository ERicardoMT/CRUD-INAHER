from django.urls import reverse_lazy
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .models import Pedido
from .forms import PedidoForm


class PedidoListView(ListView):
    model = Pedido
    template_name = "pedidos/pedido_list.html"
    context_object_name = "pedidos"


class PedidoDetailView(DetailView):
    model = Pedido
    template_name = "pedidos/pedido_detail.html"
    context_object_name = "pedido"


class PedidoCreateView(CreateView):
    model = Pedido
    form_class = PedidoForm
    template_name = "pedidos/pedido_form.html"
    success_url = reverse_lazy("pedidos:lista")

    extra_context = {
        "titulo": "Registrar pedido",
        "subtitulo": "Ingresa la información del pedido.",
        "texto_boton": "Guardar pedido",
    }


class PedidoUpdateView(UpdateView):
    model = Pedido
    form_class = PedidoForm
    template_name = "pedidos/pedido_form.html"
    success_url = reverse_lazy("pedidos:lista")

    extra_context = {
        "titulo": "Editar pedido",
        "subtitulo": "Actualiza los datos del pedido.",
        "texto_boton": "Guardar cambios",
    }


class PedidoDeleteView(DeleteView):
    model = Pedido
    template_name = "pedidos/pedido_confirm_delete.html"
    context_object_name = "pedido"
    success_url = reverse_lazy("pedidos:lista")