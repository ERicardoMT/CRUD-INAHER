// Designación diaria · tabla de tareas.
// Lo azul se guarda al salir de la casilla, sin botón Guardar. El servidor regresa
// la tabla, las tarjetas y la carga por persona ya recalculadas (mismas reglas que la impresión).
(function () {
    "use strict";

    const script = document.currentScript;
    const CFG = script ? script.dataset : {};

    function url(plantilla, id) {
        return plantilla.replace(/\/0\/(?=[^/]*\/?$)/, `/${id}/`);
    }

    function post(direccion, datos) {
        const cuerpo = new URLSearchParams(datos);
        cuerpo.append("orden", CFG.orden || "urgencia");
        return fetch(direccion, {
            method: "POST",
            headers: {
                "X-CSRFToken": CFG.csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: cuerpo,
        }).then(function (r) {
            return r.json().catch(function () { return { ok: false, error: "No se pudo guardar." }; });
        });
    }

    // ---------------------------------------------------------------- recargar fragmentos
    function aplicarFragmentos(datos, foco) {
        const cuerpo = document.getElementById("tablaItemsBody");
        if (datos.tabla !== undefined && cuerpo) cuerpo.innerHTML = datos.tabla;
        const tarjetas = document.getElementById("zonaTarjetas");
        if (datos.tarjetas !== undefined && tarjetas) tarjetas.innerHTML = datos.tarjetas;
        const carga = document.getElementById("zonaCarga");
        if (datos.carga !== undefined && carga) carga.innerHTML = datos.carga;
        filtrar();
        if (foco) {
            const fila = document.querySelector(`tr[data-id="${foco.id}"]`);
            const campo = fila && fila.querySelector(`[data-campo="${foco.campo}"]`);
            if (campo) campo.focus();
        }
    }

    function mostrarError(control, mensaje) {
        if (control && control.dataset.original !== undefined) {
            if (control.type === "checkbox") control.checked = control.dataset.original === "1";
            else control.value = control.dataset.original;
        }
        window.alert(mensaje || "No se pudo guardar.");
    }

    // ---------------------------------------------------------------- guardar un campo
    function recordar(control) {
        if (control.dataset.original === undefined) {
            control.dataset.original = control.type === "checkbox" ? (control.checked ? "1" : "0") : control.value;
        }
    }

    function guardarCampo(control) {
        const fila = control.closest("tr[data-id]");
        if (!fila || control.dataset.original === undefined || control.value === control.dataset.original) return;
        const id = fila.dataset.id;
        const campo = control.dataset.campo;
        control.disabled = true;
        // Si el usuario ya pasó a otra casilla, se le regresa el foco ahí después de recargar
        const siguiente = document.activeElement && document.activeElement.closest("tr[data-id]")
            ? { id: document.activeElement.closest("tr[data-id]").dataset.id, campo: document.activeElement.dataset.campo }
            : null;
        post(url(CFG.urlCampo, id), { campo: campo, valor: control.value })
            .then(function (datos) {
                control.disabled = false;
                if (!datos.ok) { mostrarError(control, datos.error); return; }
                aplicarFragmentos(datos, siguiente);
            })
            .catch(function () { control.disabled = false; mostrarError(control); });
    }

    function palomear(control) {
        const fila = control.closest("tr[data-id]");
        control.disabled = true;
        post(url(CFG.urlCheck, fila.dataset.id), {})
            .then(function (datos) {
                if (!datos.ok) { control.disabled = false; mostrarError(control, datos.error); return; }
                aplicarFragmentos(datos);
            })
            .catch(function () { control.disabled = false; mostrarError(control); });
    }

    document.addEventListener("focusin", function (e) {
        if (e.target.matches(".js-campo, .js-check")) recordar(e.target);
    });
    document.addEventListener("change", function (e) {
        if (e.target.matches(".js-check")) { palomear(e.target); return; }
        if (e.target.matches("select.js-campo")) guardarCampo(e.target);
    });
    document.addEventListener("focusout", function (e) {
        if (e.target.matches("input.js-campo")) guardarCampo(e.target);
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && e.target.matches("input.js-campo")) { e.preventDefault(); e.target.blur(); }
        if (e.key === "Escape" && e.target.matches("input.js-campo") && e.target.dataset.original !== undefined) {
            e.target.value = e.target.dataset.original;
            e.target.blur();
        }
    });

    // ---------------------------------------------------------------- buscar y ocultar palomeadas (solo vista)
    function sinAcentos(texto) {
        return String(texto || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    }

    function filtrar() {
        const buscador = document.getElementById("buscarTareas");
        const ocultar = document.getElementById("ocultarPalomeadas");
        const texto = sinAcentos(buscador ? buscador.value.trim() : "");
        let visibles = 0;
        document.querySelectorAll("#tablaItemsBody tr[data-id]").forEach(function (tr) {
            const ver = (!texto || tr.dataset.buscar.indexOf(texto) >= 0) && !(ocultar && ocultar.checked && tr.dataset.hecho === "1");
            tr.hidden = !ver;
            if (ver) visibles += 1;
        });
        document.querySelectorAll("#tablaItemsBody tr[data-franja]").forEach(function (franja) {
            const filas = Array.from(document.querySelectorAll(`#tablaItemsBody tr[data-id][data-grupo="${franja.dataset.grupo}"]`));
            const vistas = filas.filter(function (tr) { return !tr.hidden; }).length;
            const hechas = filas.filter(function (tr) { return tr.dataset.hecho === "1"; }).length;
            franja.hidden = !vistas;
            const texto = franja.querySelector(".franja-conteo");
            if (texto) {
                texto.textContent = vistas === filas.length
                    ? `${hechas} de ${filas.length} tarea${filas.length === 1 ? "" : "s"}`
                    : `mostrando ${vistas} de ${filas.length} tareas`;
            }
        });
        const conteo = document.getElementById("conteoVisible");
        if (conteo) {
            const total = document.querySelectorAll("#tablaItemsBody tr[data-id]").length;
            conteo.textContent = visibles === total ? `${total} tareas` : `${visibles} de ${total} tareas a la vista`;
        }
    }

    ["buscarTareas", "ocultarPalomeadas"].forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.addEventListener("input", filtrar);
        if (el) el.addEventListener("change", filtrar);
    });

    // ---------------------------------------------------------------- tareas marcadas
    function marcadas() {
        return Array.from(document.querySelectorAll(".item-select-check:checked")).filter(function (cb) {
            return !cb.closest("tr").hidden;
        });
    }

    window.toggleSelectAllItems = function (maestra) {
        document.querySelectorAll("#tablaItemsBody tr[data-id]").forEach(function (tr) {
            const cb = tr.querySelector(".item-select-check");
            if (cb && !tr.hidden) cb.checked = maestra.checked;
        });
    };

    function enviarSeleccion(accion, extra) {
        const form = document.getElementById("formSeleccion");
        form.querySelectorAll("input[name=item_ids]").forEach(function (el) { el.remove(); });
        marcadas().forEach(function (cb) {
            const oculto = document.createElement("input");
            oculto.type = "hidden";
            oculto.name = "item_ids";
            oculto.value = cb.value;
            form.appendChild(oculto);
        });
        Object.keys(extra || {}).forEach(function (k) { form.querySelector(`[name=${k}]`).value = extra[k]; });
        form.action = accion;
        form.submit();
    }

    window.quitarMarcadas = function () {
        const n = marcadas().length;
        if (!n) { window.alert("Marca al menos una tarea con la casilla de la izquierda."); return; }
        if (window.confirm(`¿Quitar ${n} tarea(s) de hoy? Se borran (no van al Archivo). Tendrás 10 segundos para deshacer.`)) {
            enviarSeleccion(CFG.urlQuitar);
        }
    };

    window.abrirAsignar = function () {
        const n = marcadas().length;
        if (!n) { window.alert("Marca al menos una tarea con la casilla de la izquierda."); return; }
        document.getElementById("cuantasAsignar").textContent = n;
        bootstrap.Modal.getOrCreateInstance(document.getElementById("modalAsignar")).show();
    };

    window.confirmarAsignar = function () {
        enviarSeleccion(CFG.urlAsignar, { quien: document.getElementById("quienAsignar").value });
    };

    // ---------------------------------------------------------------- Deshacer (10 s)
    const aviso = document.getElementById("avisoDeshacer");
    if (aviso) {
        let segundos = Number(aviso.dataset.segundos || 10);
        const contador = document.getElementById("segundosDeshacer");
        const reloj = window.setInterval(function () {
            segundos -= 1;
            if (contador) contador.textContent = Math.max(segundos, 0);
            if (segundos <= 0) { window.clearInterval(reloj); aviso.remove(); }
        }, 1000);
    }

    filtrar();
})();
