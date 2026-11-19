// Agregar / editar tarea (regla 6):
// - Pedido → sus partidas; la partida propone su Cant (sin partida: el total del pedido).
// - Operación madre → solo sus detalladas y solo las máquinas de su tipo; con una sola opción se pone sola.
// - Tarea especial → pide Min estimado por pieza y nace en Tarea manual.
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        const $ = function (id) { return document.getElementById(id); };
        const pedido = $("id_pedido"), partida = $("id_partida"), cantidad = $("id_cantidad");
        const madre = $("id_operacion_madre"), detallada = $("id_operacion_detallada"), maquina = $("id_maquina");
        const cajaEspecial = $("boxMinEstimado"), minEstimado = $("id_min_estimado_pz");
        let totalPedido = null;

        function opcion(valor, texto, extra) {
            const o = document.createElement("option");
            o.value = valor;
            o.textContent = texto;
            Object.assign(o.dataset, extra || {});
            return o;
        }

        // ---------------- pedido y partida
        function cargarPartidas(proponer) {
            if (!pedido || !partida) return;
            const elegida = partida.value;
            const vacia = partida.options[0] ? partida.options[0].textContent : "Todo el pedido";
            partida.innerHTML = "";
            partida.appendChild(opcion("", vacia));
            totalPedido = null;
            if (!pedido.value) { if (proponer && cantidad && !cantidad.value) cantidad.value = ""; return; }
            fetch(`/designacion/api/pedido-info/?pedido_id=${encodeURIComponent(pedido.value)}`)
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    totalPedido = d.cantidad;
                    (d.partidas || []).forEach(function (p) {
                        const o = opcion(p.id, `${p.cantidad} · ${p.descripcion}`, { cantidad: p.cantidad });
                        if (String(p.id) === elegida) o.selected = true;
                        partida.appendChild(o);
                    });
                    if (proponer) proponerCantidad();
                })
                .catch(function () {});
        }

        function proponerCantidad() {
            if (!cantidad) return;
            const o = partida && partida.selectedOptions[0];
            if (o && o.dataset.cantidad) cantidad.value = o.dataset.cantidad;
            else if (totalPedido !== null) cantidad.value = totalPedido;
        }

        // ---------------- madre, detallada y máquina
        function cargarDetalladas(alCambiar) {
            if (!madre || !detallada) return;
            const elegida = detallada.value;
            const elegidaMaquina = maquina ? maquina.value : "";
            if (!madre.value) return;
            fetch(`/designacion/api/operaciones-detalladas/?madre_id=${encodeURIComponent(madre.value)}`)
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    detallada.innerHTML = "";
                    detallada.appendChild(opcion("", "---------"));
                    d.detalles.forEach(function (x) {
                        const o = opcion(x.id, x.nombre, { especial: x.especial ? "1" : "" });
                        if (String(x.id) === elegida) o.selected = true;
                        detallada.appendChild(o);
                    });
                    if (maquina) {
                        maquina.innerHTML = "";
                        maquina.appendChild(opcion("", "— elegir —"));
                        d.maquinas.forEach(function (m) {
                            const o = opcion(m.id, m.nombre);
                            if (String(m.id) === elegidaMaquina) o.selected = true;
                            maquina.appendChild(o);
                        });
                        // Vacía y con una sola opción: se pone sola
                        if (alCambiar && d.maquina_sola) maquina.value = String(d.maquina_sola);
                    }
                    revisarEspecial();
                })
                .catch(function () {});
        }

        function revisarEspecial() {
            if (!detallada || !cajaEspecial) return;
            const o = detallada.selectedOptions[0];
            const especial = Boolean(o && o.dataset.especial);
            cajaEspecial.classList.toggle("d-none", !especial);
            if (minEstimado) minEstimado.required = especial;
        }

        if (pedido) pedido.addEventListener("change", function () { cargarPartidas(true); });
        if (partida) partida.addEventListener("change", proponerCantidad);
        if (madre) madre.addEventListener("change", function () { cargarDetalladas(true); });
        if (detallada) detallada.addEventListener("change", revisarEspecial);

        // Al editar: dejar las listas filtradas desde el principio
        if (madre && madre.value) cargarDetalladas(false);
        if (pedido && pedido.value && partida && partida.options.length <= 1) cargarPartidas(false);
    });
})();
