// Al elegir un pedido, el selector "Partida" muestra solo sus partidas.
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        const selectPedido = document.getElementById("id_pedido");
        const selectPartida = document.getElementById("id_partida");
        if (!selectPedido || !selectPartida) return;

        const etiquetaVacia = selectPartida.options[0] ? selectPartida.options[0].textContent : "Todo el pedido";

        function cargarPartidas() {
            const pedidoId = selectPedido.value;
            const seleccion = selectPartida.value;
            selectPartida.innerHTML = "";
            const vacia = document.createElement("option");
            vacia.value = "";
            vacia.textContent = etiquetaVacia;
            selectPartida.appendChild(vacia);
            if (!pedidoId) return;

            fetch(`/designacion/api/pedido-info/?pedido_id=${encodeURIComponent(pedidoId)}`)
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    (data.partidas || []).forEach(function (p) {
                        const opt = document.createElement("option");
                        opt.value = p.id;
                        opt.textContent = `${p.cantidad} · ${p.descripcion}`;
                        opt.dataset.cantidad = p.cantidad;
                        if (String(p.id) === seleccion) opt.selected = true;
                        selectPartida.appendChild(opt);
                    });
                })
                .catch(function () { /* sin partidas: queda "Todo el pedido" */ });
        }

        // Al elegir partida, la cantidad de la tarea toma la de la partida
        selectPartida.addEventListener("change", function () {
            const opt = selectPartida.selectedOptions[0];
            const cantidad = document.getElementById("id_cantidad");
            if (opt && opt.dataset.cantidad && cantidad) {
                cantidad.value = opt.dataset.cantidad;
                cantidad.dispatchEvent(new Event("input"));
            }
        });

        selectPedido.addEventListener("change", cargarPartidas);
    });
})();
