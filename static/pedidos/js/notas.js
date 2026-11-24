document.addEventListener("change", async (evento) => {
    const form = evento.target.closest("[data-nota-rapida]");
    if (!form) return;
    const estado = form.querySelector(".nota-rapida-estado");
    estado.className = "nota-rapida-estado";
    estado.textContent = "Guardando…";
    try {
        const respuesta = await fetch(form.action, {
            method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" },
        });
        const datos = await respuesta.json();
        estado.textContent = datos.ok ? "Guardado" : datos.error;
        estado.classList.add(datos.ok ? "is-ok" : "is-error");
    } catch {
        estado.textContent = "No se pudo guardar. Revisa tu conexión.";
        estado.classList.add("is-error");
    }
});