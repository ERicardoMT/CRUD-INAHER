// Estudio de tiempos · ventana Nueva medición (página 4): las listas dependen de la madre, el material
// se llena solo, Empaquetar pide modelos y piezas, y el resultado en gris se calcula mientras se escribe.
(() => {
    const contenido = document.querySelector("#ventana .modal-content");
    if (!contenido) return;
    let operaciones = {};  // detallada → Usa HOY (la misma API que usa Designación diaria)

    const caja = () => contenido.querySelector("[data-medicion]");
    const campo = (nombre) => contenido.querySelector(`[name="${nombre}"]`);
    const poner = (clave, texto, clase = "") => {
        const el = contenido.querySelector(`[data-resultado="${clave}"]`);
        el.textContent = texto;
        el.className = clase;
    };
    // min:seg → segundos (regla 1: segundos de 00 a 59)
    const segundos = (texto) => {
        const partes = /^(\d{1,4}):(\d{1,2})$/.exec((texto || "").trim());
        return partes && Number(partes[2]) < 60 ? Number(partes[1]) * 60 + Number(partes[2]) : null;
    };
    // Como la hoja: el medio sube
    const redondea = (valor, lugares) => Math.sign(valor) * Math.round(Math.abs(valor) * 10 ** lugares + 1e-9) / 10 ** lugares;
    const conSigno = (n) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : "0");
    const esEmpaquetar = () => caja().dataset.empaquetar !== "" && campo("operacion_madre").value === caja().dataset.empaquetar;
    const llenar = (select, opciones) => select.replaceChildren(...opciones.map(([valor, texto]) => new Option(texto, valor)));

    async function cargarMadre(nuevaMadre) {
        const madre = campo("operacion_madre").value;
        const datos = madre
            ? await (await fetch(`${caja().dataset.api}?madre_id=${madre}`)).json()
            : { detalles: [], maquinas: [], maquina_sola: null };
        operaciones = Object.fromEntries(datos.detalles.map((d) => [String(d.id), d]));
        if (nuevaMadre) {
            llenar(campo("detallada"), [["", "— elegir —"], ...datos.detalles.map((d) => [d.id, d.nombre]), [caja().dataset.nueva, "No está: escribirla"]]);
            llenar(campo("maquina"), [["", "— elegir —"], ...datos.maquinas.map((m) => [m.id, m.nombre])]);
            if (datos.maquina_sola) campo("maquina").value = datos.maquina_sola;
        }
        actualizar();
    }

    // Regla 3: inox-304 → Inox; fierro-galv → Fierro; si no dice material, se queda como está
    function llenarMaterial() {
        const elegida = campo("detallada");
        const nombre = elegida.value === caja().dataset.nueva ? campo("detallada_nueva").value : elegida.selectedOptions[0]?.text || "";
        const material = nombre.includes("inox-304") ? "I" : nombre.includes("fierro-galv") ? "F" : null;
        if (material) campo("material").value = material;
    }

    function actualizar() {
        const empaque = esEmpaquetar();
        contenido.querySelectorAll("[data-solo-empaque]").forEach((el) => { el.hidden = !empaque; });
        contenido.querySelectorAll("[data-sin-empaque]").forEach((el) => { el.hidden = empaque; });
        contenido.querySelector("[data-nueva-caja]").hidden = campo("detallada").value !== caja().dataset.nueva;

        const piezasCampo = campo("muestra_piezas");
        piezasCampo.readOnly = empaque;
        if (empaque) {  // la muestra es la suma de las piezas de cada modelo
            const suma = [...contenido.querySelectorAll('[name="empaque_piezas"]')].reduce((s, el) => s + (Number(el.value) || 0), 0);
            piezasCampo.value = suma || "";
        }
        const piezas = Number(piezasCampo.value) || 0;
        const total = segundos(campo("muestra_tiempo_total").value);
        const uno = empaque ? null : segundos(campo("tiempo_1_pieza").value);
        const minutos = total !== null ? total / 60 : null;
        const teorico = uno && piezas ? redondea(uno / 60 * piezas, 1) : null;
        const dif = teorico && minutos !== null ? redondea(redondea((minutos - teorico) / teorico * 100, 1), 0) : null;
        const minPz = minutos !== null && piezas ? redondea(empaque ? minutos : minutos / piezas, 2) : null;
        const tolerancia = Number(caja().dataset.tolerancia);

        poner("teorico", teorico !== null ? teorico.toFixed(1) : "—");
        poner("dif", dif !== null ? `${conSigno(dif)} %` : "—", dif === null ? "" : Math.abs(dif) <= tolerancia ? "efic-ok" : "efic-baja");
        poner("minpz", minPz !== null ? minPz.toFixed(2) : "—");
        poner("minpieza", empaque && minutos !== null && piezas ? redondea(minutos / piezas, 2).toFixed(2) : "—");
        const hoy = operaciones[campo("detallada").value];
        poner("hoy", hoy?.usa_hoy != null ? hoy.usa_hoy.toFixed(2) : "—");
        poner("origen", hoy?.origen || "");
    }

    contenido.addEventListener("change", (evento) => {
        if (!caja()) return;
        if (evento.target.name === "operacion_madre") cargarMadre(true);
        if (evento.target.name === "detallada" || evento.target.name === "detallada_nueva") llenarMaterial();
        actualizar();
    });
    contenido.addEventListener("input", () => { if (caja()) actualizar(); });
    contenido.addEventListener("click", (evento) => {
        if (!caja()) return;
        if (evento.target.closest("[data-agregar-modelo]")) {
            const plantilla = contenido.querySelector("template[data-fila-modelo]");
            contenido.querySelector("[data-modelos]").append(plantilla.content.cloneNode(true));
        }
        const quitar = evento.target.closest("[data-quitar-modelo]");
        if (quitar && contenido.querySelectorAll("[data-modelos] [data-fila]").length > 1) quitar.closest("[data-fila]").remove();
        actualizar();
    });

    // El contenido de la ventana llega del servidor (archivo.js): al llegar el formulario se prepara
    new MutationObserver(() => {
        if (!caja()) return;
        actualizar();
        cargarMadre(false);
    }).observe(contenido, { childList: true });
})();