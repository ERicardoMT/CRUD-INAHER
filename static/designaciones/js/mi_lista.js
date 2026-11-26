// «Mi lista de hoy» (celular). Palomear, anotar piezas y deshacer sin recargar:
// el servidor regresa la lista ya recalculada (mismas reglas que Designación).
(function () {
    "use strict";

    const app = document.getElementById("miLista");
    if (!app) return;
    const CFG = app.dataset;
    let abierta = null;      // id de la tarea abierta
    let espera = null;       // temporizador para guardar piezas

    function url(plantilla, id) {
        return plantilla.replace(/\/0\/(?=[^/]*\/?$)/, `/${id}/`);
    }

    function aviso(texto) {
        const caja = document.getElementById("mlAviso");
        caja.textContent = texto;
        caja.hidden = false;
        window.clearTimeout(aviso.t);
        aviso.t = window.setTimeout(function () { caja.hidden = true; }, 3500);
    }

    // La franja de cada grupo se pega justo debajo del encabezado fijo
    function medirEncabezado() {
        const encabezado = app.querySelector(".ml-encabezado");
        if (encabezado) document.documentElement.style.setProperty("--ml-alto-encabezado", `${encabezado.offsetHeight}px`);
    }

    function abrir(articulo, si) {
        const cuerpo = articulo.querySelector(".ml-tarea-cuerpo");
        const detalle = articulo.querySelector(".ml-abierta");
        if (!detalle || cuerpo.disabled) return;
        articulo.classList.toggle("is-abierta", si);
        cuerpo.setAttribute("aria-expanded", si ? "true" : "false");
        detalle.hidden = !si;
        abierta = si ? articulo.dataset.id : null;
    }

    function enviar(direccion, datos) {
        const cuerpo = new URLSearchParams(datos);
        cuerpo.append("ver", CFG.vista);
        return fetch(direccion, {
            method: "POST",
            headers: {
                "X-CSRFToken": CFG.csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: cuerpo,
        }).then(function (r) {
            if (r.status === 403 || r.redirected) throw new Error("Tu sesión terminó. Vuelve a entrar.");
            return r.json();
        }).then(function (d) {
            if (!d.ok) throw new Error(d.error || "No se pudo guardar.");
            const terminadasAbiertas = app.querySelector(".ml-terminadas[open]") !== null;
            app.innerHTML = d.lista;
            if (terminadasAbiertas) {
                const t = app.querySelector(".ml-terminadas");
                if (t) t.open = true;
            }
            medirEncabezado();
            const otra = abierta && app.querySelector(`.ml-tarea[data-id="${abierta}"]`);
            if (otra) abrir(otra, true);
        });
    }

    function guardarPiezas(articulo, valor) {
        window.clearTimeout(espera);
        espera = window.setTimeout(function () {
            enviar(url(CFG.urlPiezas, articulo.dataset.id), { piezas: valor })
                .catch(function (e) { aviso(e.message); });
        }, 700);
    }

    // «Ir a»: brinca al grupo y lo resalta, para que se note aunque toda la lista quepa en pantalla
    function irAGrupo(chip) {
        const destino = document.getElementById(chip.getAttribute("href").slice(1));
        if (!destino) return;
        const encabezado = app.querySelector(".ml-encabezado");
        const arriba = destino.getBoundingClientRect().top + window.scrollY - (encabezado ? encabezado.offsetHeight : 0) - 8;
        const suave = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.scrollTo({ top: Math.max(arriba, 0), behavior: suave ? "smooth" : "auto" });

        app.querySelectorAll(".ml-chip.is-elegido").forEach(function (c) { c.classList.remove("is-elegido"); });
        chip.classList.add("is-elegido");
        destino.classList.remove("is-resaltado");
        void destino.offsetWidth;  // reinicia la animación si se toca dos veces
        destino.classList.add("is-resaltado");
        window.clearTimeout(irAGrupo.t);
        irAGrupo.t = window.setTimeout(function () { destino.classList.remove("is-resaltado"); }, 1600);
    }

    app.addEventListener("click", function (e) {
        const chip = e.target.closest(".ml-chip");
        if (chip) {
            e.preventDefault();
            irAGrupo(chip);
            return;
        }

        const marcar = e.target.closest(".js-marcar");
        if (marcar) {
            const fila = marcar.closest("[data-id]");
            marcar.disabled = true;
            window.clearTimeout(espera);
            if (fila.dataset.id === abierta) abierta = null;
            enviar(url(CFG.urlMarcar, fila.dataset.id), { hecho: marcar.dataset.hecho })
                .then(function () {
                    if (marcar.dataset.hecho === "1") aviso("Tarea terminada. Puedes deshacerla en «Ya terminadas».");
                })
                .catch(function (err) { marcar.disabled = false; aviso(err.message); });
            return;
        }

        const paso = e.target.closest(".js-menos, .js-mas");
        if (paso) {
            const articulo = paso.closest(".ml-tarea");
            const campo = articulo.querySelector(".js-piezas");
            const maximo = Number(articulo.dataset.cantidad);
            const valor = Math.min(Math.max((Number(campo.value) || 0) + (paso.classList.contains("js-mas") ? 1 : -1), 0), maximo);
            campo.value = valor;
            guardarPiezas(articulo, valor);
            return;
        }

        const cuerpo = e.target.closest(".ml-tarea-cuerpo");
        if (cuerpo) {
            const articulo = cuerpo.closest(".ml-tarea");
            const yaAbierta = articulo.classList.contains("is-abierta");
            app.querySelectorAll(".ml-tarea.is-abierta").forEach(function (a) { abrir(a, false); });  // solo una a la vez
            abrir(articulo, !yaAbierta);
        }
    });

    app.addEventListener("change", function (e) {
        if (!e.target.matches(".js-piezas")) return;
        const articulo = e.target.closest(".ml-tarea");
        const maximo = Number(articulo.dataset.cantidad);
        const valor = Math.min(Math.max(parseInt(e.target.value, 10) || 0, 0), maximo);
        e.target.value = valor;
        guardarPiezas(articulo, valor);
    });

    window.addEventListener("resize", medirEncabezado);
    medirEncabezado();
})();
