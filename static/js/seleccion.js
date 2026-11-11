function toggleSelectAllPedidos(master) {
    document.querySelectorAll(".pedido-select-check").forEach((cb) => { cb.checked = master.checked; });
}

function enviarSeleccion(accion, nuevaVentana = false) {
    const checks = document.querySelectorAll(".pedido-select-check:checked");
    if (checks.length === 0) {
        alert("Selecciona al menos un pedido marcando la casilla ☑ de la izquierda.");
        return;
    }
    const form = document.getElementById("formSeleccion");
    form.action = accion;
    form.target = nuevaVentana ? "_blank" : "";
    form.submit();
}

