// Ventanas FACTURADO / PAGADO: el contenido viene del servidor y se guarda sin salir de la página.
(() => {
    const modalEl = document.getElementById("ventana");
    if (!modalEl) return;
    const contenido = modalEl.querySelector(".modal-content");
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

    async function cargar(url, opciones = {}) {
        const respuesta = await fetch(url, { headers: { "X-Requested-With": "fetch" }, ...opciones });
        if (respuesta.status === 204) {          // guardado: recarga con los mismos filtros y página
            window.location.reload();
            return;
        }
        contenido.innerHTML = await respuesta.text();
        contenido.querySelector("[autofocus]")?.focus();
    }

    document.addEventListener("click", (evento) => {
        const boton = evento.target.closest("[data-ventana]");
        if (!boton) return;
        evento.preventDefault();
        contenido.innerHTML = '<div class="modal-body text-center text-muted py-5">Cargando…</div>';
        modal.show();
        cargar(boton.dataset.ventana);
    });

    // Guardar, Quitar pago y Quitar factura: el botón pulsado decide a dónde se manda
    contenido.addEventListener("submit", (evento) => {
        evento.preventDefault();
        const form = evento.target;
        const url = evento.submitter?.getAttribute("formaction") || form.action;
        cargar(url, { method: "POST", body: new FormData(form, evento.submitter) });
    });
})();

// Buscador del Archivo: contesta mientras escribes dónde está cada pedido.
(() => {
    const entrada = document.querySelector("[data-buscar-url]");
    const lista = document.getElementById("archivo-sugerencias");
    if (!entrada || !lista) return;
    let espera;
    let peticion;

    entrada.addEventListener("input", () => {
        clearTimeout(espera);
        const texto = entrada.value.trim();
        if (texto.length < 2) {
            lista.hidden = true;
            return;
        }
        espera = setTimeout(async () => {
            peticion?.abort();
            peticion = new AbortController();
            try {
                const url = `${entrada.dataset.buscarUrl}?q=${encodeURIComponent(texto)}`;
                const respuesta = await fetch(url, { signal: peticion.signal });
                lista.innerHTML = await respuesta.text();
                lista.hidden = false;
            } catch (error) {
                if (error.name !== "AbortError") lista.hidden = true;
            }
        }, 250);
    });

    entrada.addEventListener("keydown", (evento) => {
        if (evento.key === "Escape") lista.hidden = true;
    });
    document.addEventListener("click", (evento) => {
        if (!evento.target.closest(".archivo-buscador")) lista.hidden = true;
    });
})();
