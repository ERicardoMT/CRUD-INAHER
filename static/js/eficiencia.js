// Min real: se guarda solo al salir de la casilla (Tab, clic fuera o Enter).
// El servidor regresa la fila y las tarjetas ya recalculadas; no se recarga la página.
(() => {
    const token = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
    if (!token) return;

    async function guardar(casilla) {
        const datos = new FormData();
        datos.append("min_real", casilla.value.trim());
        casilla.classList.remove("is-invalid");
        casilla.disabled = true;
        try {
            const respuesta = await fetch(casilla.dataset.url + window.location.search, {
                method: "POST",
                body: datos,
                headers: { "X-CSRFToken": token },
            });
            const json = await respuesta.json().catch(() => ({ error: "No se pudo guardar." }));
            if (!respuesta.ok) throw new Error(json.error || "No se pudo guardar.");
            casilla.closest("tr").outerHTML = json.fila;
            document.getElementById("efic-tarjetas").innerHTML = json.tarjetas;
        } catch (error) {
            casilla.disabled = false;
            casilla.classList.add("is-invalid");
            casilla.title = error.message;
        }
    }

    document.addEventListener("change", (evento) => {
        if (evento.target.matches(".efic-min-real")) guardar(evento.target);
    });
    document.addEventListener("keydown", (evento) => {
        if (evento.key === "Enter" && evento.target.matches(".efic-min-real")) {
            evento.preventDefault();
            evento.target.blur();
        }
    });
})();
