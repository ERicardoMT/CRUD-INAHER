/* Formulario Registrar / Editar pedido */
(function () {
    "use strict";

    const form = document.getElementById("formPedido");
    if (!form) return;

    // ----- Partidas (un renglón por partida, como en el SAE) -----
    const lista = document.getElementById("partidasLista");
    const plantilla = document.getElementById("partidaVacia");
    const totalForms = form.querySelector('input[name="partidas-TOTAL_FORMS"]');
    const cantidadTotal = document.getElementById("cantidadTotal");

    const filasVisibles = () => Array.from(lista.querySelectorAll(".partida-row:not(.d-none)"));
    const campo = (fila, clase) => fila.querySelector(clase);

    function recalcularTotal() {
        cantidadTotal.textContent = filasVisibles().reduce(
            (suma, fila) => suma + (parseInt(campo(fila, ".js-partida-cant").value, 10) || 0),
            0
        );
    }

    function agregarPartida() {
        const indice = Number(totalForms.value);
        lista.insertAdjacentHTML("beforeend", plantilla.innerHTML.replace(/__prefix__/g, indice));
        totalForms.value = indice + 1;
        const fila = lista.lastElementChild;
        campo(fila, ".js-partida-cant").focus();
        recalcularTotal();
    }

    function quitarPartida(fila) {
        // Se marca DELETE en vez de borrar el nodo para no desordenar los índices del formset
        fila.querySelector('input[name$="-DELETE"]').checked = true;
        fila.classList.add("d-none");
        if (!filasVisibles().length) agregarPartida();
        recalcularTotal();
    }

    document.getElementById("btnAgregarPartida").addEventListener("click", agregarPartida);

    lista.addEventListener("click", (e) => {
        const boton = e.target.closest(".js-quitar-partida");
        if (boton) quitarPartida(boton.closest(".partida-row"));
    });

    lista.addEventListener("input", (e) => {
        if (e.target.matches(".js-partida-cant")) recalcularTotal();
    });

    // Enter: Cant → Descripción → siguiente renglón (o uno nuevo)
    lista.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        const fila = e.target.closest(".partida-row");
        if (!fila) return;
        e.preventDefault();

        if (e.target.matches(".js-partida-cant")) {
            campo(fila, ".js-partida-desc").focus();
            return;
        }
        const filas = filasVisibles();
        const siguiente = filas[filas.indexOf(fila) + 1];
        if (siguiente) campo(siguiente, ".js-partida-cant").focus();
        else agregarPartida();
    });

    recalcularTotal();

    // ----- Número de pedido: verificación en vivo -----
    const numero = document.getElementById("id_numero");
    const ayudaNumero = document.getElementById("ayuda-numero");
    let espera;

    numero.addEventListener("input", () => {
        clearTimeout(espera);
        const valor = numero.value.trim();
        ayudaNumero.textContent = "";
        if (!valor) return;

        espera = setTimeout(async () => {
            const url = new URL(form.dataset.numeroUrl, window.location.origin);
            url.searchParams.set("numero", valor);
            if (form.dataset.pedidoId) url.searchParams.set("excluir", form.dataset.pedidoId);

            try {
                const datos = await (await fetch(url)).json();
                if (numero.value.trim() !== valor) return;
                ayudaNumero.textContent = datos.disponible ? "✓ disponible" : datos.mensaje;
                ayudaNumero.classList.toggle("text-success", datos.disponible);
                ayudaNumero.classList.toggle("text-danger", !datos.disponible);
            } catch {
                ayudaNumero.textContent = "";
            }
        }, 300);
    });

    // ----- Cliente: autorrelleno con los ya capturados; si no existe, se agrega -----
    const cliente = document.getElementById("id_cliente_nombre");
    const ayudaCliente = document.getElementById("ayuda-cliente_nombre");
    const clientes = new Set(
        Array.from(document.querySelectorAll("#clientes-lista option"), (o) => o.value.toLowerCase())
    );

    function avisarClienteNuevo() {
        const valor = cliente.value.trim();
        ayudaCliente.textContent =
            valor && !clientes.has(valor.toLowerCase())
                ? `+ Se agregará “${valor}” como cliente nuevo al guardar.`
                : "";
    }

    cliente.addEventListener("input", avisarClienteNuevo);
    avisarClienteNuevo();

    // ----- Detenido: escribir el motivo enciende la bandera -----
    const detenido = document.getElementById("id_detenido");
    const motivo = document.getElementById("id_detenido_por");

    motivo.addEventListener("input", () => {
        if (motivo.value.trim()) detenido.checked = true;
    });
    detenido.addEventListener("change", () => {
        if (detenido.checked) motivo.focus();
    });
})();
