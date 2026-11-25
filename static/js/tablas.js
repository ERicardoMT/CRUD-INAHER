// ocultar las columnas elegidas y barra de scroll horizontal también arriba.
// Sirve para cualquier <table data-tabla="nombre">. Renglones especiales:
//   data-franja      → encabezado de grupo: se ordena dentro de cada grupo
//   data-anexo       → renglón que se despliega: viaja pegado al de arriba
//   data-fila-ancha  → una sola celda a lo ancho: no se le ocultan columnas
(() => {
    function leer(tipo, clave, defecto) {
        try { return JSON.parse(window[tipo].getItem(clave)) ?? defecto; } catch { return defecto; }
    }
    function guardar(tipo, clave, valor) {
        try { window[tipo].setItem(clave, JSON.stringify(valor)); } catch { /* navegador sin memoria */ }
    }
    const texto = (th) => th.textContent.replace(/\s+/g, " ").trim();
    const elegible = (th) => texto(th) && !th.querySelector("input, button");

    // Valor para ordenar: lo elegido en listas y casillas; fechas y números como tales (512 < 5129, 23/11 < 07/12)
    function valor(celda) {
        if (!celda) return null;
        if (celda.dataset.orden !== undefined) return celda.dataset.orden === "" ? null : Number(celda.dataset.orden);
        const control = celda.querySelector("select, textarea, input:not([type=checkbox])");
        const casilla = celda.querySelector("input[type=checkbox]");
        let t = control ? (control.tagName === "SELECT" ? control.selectedOptions[0]?.text : control.value)
            : casilla ? (casilla.checked ? "1" : "0") : celda.textContent;
        t = (t || "").replace(/\s+/g, " ").trim();
        if (!t || t === "—") return null;
        const fecha = t.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
        if (fecha) return (fecha[3].length === 2 ? 2000 + Number(fecha[3]) : Number(fecha[3])) * 10000 + Number(fecha[2]) * 100 + Number(fecha[1]);
        const numero = t.replace(/[#$,%\s]/g, "");
        return /^-?\d+(\.\d+)?$/.test(numero) ? parseFloat(numero) : t.toLowerCase();
    }

    function comparar(a, b) {
        if (a === null) return b === null ? 0 : 1;   // vacíos siempre al final
        if (b === null) return -1;
        if (typeof a === "number" && typeof b === "number") return a - b;
        if (typeof a === "number") return -1;
        if (typeof b === "number") return 1;
        return a.localeCompare(b, "es", { numeric: true });
    }

    function ordenarCuerpo(cuerpo, columna, sentido) {
        const tramos = [];
        let tramo = { franja: null, bloques: [] };
        [...cuerpo.rows].forEach((fila) => {
            if (fila.hasAttribute("data-franja")) {
                tramos.push(tramo);
                tramo = { franja: fila, bloques: [] };
            } else if (fila.hasAttribute("data-anexo") && tramo.bloques.length) {
                tramo.bloques[tramo.bloques.length - 1].filas.push(fila);
            } else {
                tramo.bloques.push({ filas: [fila], v: valor(fila.cells[columna]), i: tramo.bloques.length });
            }
        });
        tramos.push(tramo);
        const marco = document.createDocumentFragment();
        tramos.forEach((t) => {
            if (t.franja) marco.append(t.franja);
            t.bloques.sort((x, y) => (x.v === null || y.v === null ? comparar(x.v, y.v) : comparar(x.v, y.v) * sentido) || x.i - y.i);
            t.bloques.forEach((b) => marco.append(...b.filas));
        });
        cuerpo.append(marco);
    }

    document.querySelectorAll("table[data-tabla]").forEach((tabla) => {
        const nombre = tabla.dataset.tabla;
        const cuerpo = tabla.tBodies[0];
        const encabezados = tabla.tHead ? [...tabla.tHead.rows[0].cells] : [];
        if (!cuerpo || !encabezados.length) return;

        // ----- 1 · ordenar con clic en el encabezado
        let orden = leer("sessionStorage", `orden:${nombre}`, null);
        const observador = new MutationObserver(() => aplicarOrden());   // la tabla se vuelve a dibujar (Designación)
        function aplicarOrden() {
            const th = orden && encabezados.find((x) => texto(x) === orden.columna);
            encabezados.forEach((x) => x.removeAttribute("aria-sort"));
            if (!th) return;
            th.setAttribute("aria-sort", orden.sentido > 0 ? "ascending" : "descending");
            observador.disconnect();
            ordenarCuerpo(cuerpo, th.cellIndex, orden.sentido);
            observador.observe(cuerpo, { childList: true });
        }
        encabezados.filter(elegible).forEach((th) => {
            th.dataset.ordenable = "";
            th.tabIndex = 0;
            const clic = () => {
                const columna = texto(th);
                orden = { columna, sentido: orden && orden.columna === columna ? -orden.sentido : 1 };
                guardar("sessionStorage", `orden:${nombre}`, orden);
                aplicarOrden();
            };
            th.addEventListener("click", clic);
            th.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); clic(); }
            });
        });
        observador.observe(cuerpo, { childList: true });
        aplicarOrden();

        // ----- 2 · ocultar columnas: se marcan en la lista y "Ocultar columnas" las esconde
        const control = document.querySelector(`[data-columnas-de="${nombre}"]`);
        if (control) {
            const estilo = document.head.appendChild(document.createElement("style"));
            const lista = control.querySelector("[data-columnas-lista]");
            const interruptor = control.querySelector("[data-ocultar-columnas]");
            const cuantas = control.querySelector("[data-columnas-cuantas]");
            const elegidas = new Set(leer("localStorage", `columnas:${nombre}`, []));
            interruptor.checked = leer("localStorage", `columnas-ocultas:${nombre}`, false);
            const pintar = () => {
                const celdas = `table[data-tabla="${nombre}"] tr:not([data-fila-ancha]) >`;
                estilo.textContent = interruptor.checked
                    ? encabezados.filter((th) => elegidas.has(texto(th)))
                        .map((th) => `${celdas} :nth-child(${th.cellIndex + 1}) { display: none !important; }`).join("\n")
                    : "";
                cuantas.textContent = elegidas.size ? `(${elegidas.size})` : "";
            };
            encabezados.filter(elegible).forEach((th) => {
                const etiqueta = document.createElement("label");
                etiqueta.className = "dropdown-item d-flex align-items-center gap-2";
                const casilla = document.createElement("input");
                casilla.type = "checkbox";
                casilla.className = "form-check-input mt-0";
                casilla.checked = elegidas.has(texto(th));
                casilla.addEventListener("change", () => {
                    if (casilla.checked) elegidas.add(texto(th));
                    else elegidas.delete(texto(th));
                    guardar("localStorage", `columnas:${nombre}`, [...elegidas]);
                    pintar();
                });
                etiqueta.append(casilla, texto(th));
                lista.append(etiqueta);
            });
            interruptor.addEventListener("change", () => {
                guardar("localStorage", `columnas-ocultas:${nombre}`, interruptor.checked);
                pintar();
            });
            pintar();
        }

        // ----- 3 · barra de scroll horizontal también arriba
        const caja = tabla.closest(".table-responsive");
        if (!caja) return;
        const barra = document.createElement("div");
        barra.className = "scroll-arriba";
        barra.setAttribute("aria-hidden", "true");
        const relleno = barra.appendChild(document.createElement("div"));
        caja.before(barra);
        const medir = () => {
            relleno.style.width = `${tabla.scrollWidth}px`;
            barra.hidden = tabla.scrollWidth <= caja.clientWidth + 1;
        };
        new ResizeObserver(medir).observe(tabla);
        new ResizeObserver(medir).observe(caja);
        barra.addEventListener("scroll", () => { if (caja.scrollLeft !== barra.scrollLeft) caja.scrollLeft = barra.scrollLeft; });
        caja.addEventListener("scroll", () => { if (barra.scrollLeft !== caja.scrollLeft) barra.scrollLeft = caja.scrollLeft; });
        medir();
    });
})();