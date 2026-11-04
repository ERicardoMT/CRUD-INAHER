(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", inicializar);

    function inicializar() {
        const modal = document.getElementById("modalCargarRuta");

        if (!modal) return;

        const selectPedido = document.getElementById("pedidoRuta");
        const btnAnalizar = document.getElementById("btnAnalizarRuta");
        const btnConfirmar = document.getElementById("btnConfirmarRuta");
        const panelPreguntas = document.getElementById("panelPreguntasRuta");
        const panelVista = document.getElementById("vistaPreviaRuta");
        const estado = document.getElementById("estadoMotorRuta");

        if (
            !selectPedido ||
            !btnAnalizar ||
            !btnConfirmar ||
            !panelPreguntas ||
            !panelVista ||
            !estado
        ) {
            console.error("Faltan elementos HTML del modal de rutas.");
            return;
        }

        const motor = window.MotorRutasINAHER;

        if (!motor) {
            mostrarError("No se encontró el motor de rutas.");
            return;
        }

        let estadoActual = {
            pedido: null,
            respuestas: { partidas: [] },
            resultado: null
        };

        btnAnalizar.disabled = true;
        btnConfirmar.disabled = true;

        const URL_DATOS = modal.dataset.jsonUrl;

        fetch(URL_DATOS)
            .then(function (respuesta) {
                if (!respuesta.ok) {
                    throw new Error("No se pudieron cargar los datos de rutas.");
                }

                return respuesta.json();
            })
            .then(function (datos) {
                motor.cargarDatos(datos);

                btnAnalizar.disabled = false;

                estado.textContent = "Motor de rutas listo.";
                estado.className = "alert alert-success py-2";
            })
            .catch(function (error) {
                mostrarError(error.message);
            });

        function escapar(valor) {
            return String(valor ?? "").replace(/[&<>"']/g, function (c) {
                return {
                    "&": "&amp;",
                    "<": "&lt;",
                    ">": "&gt;",
                    '"': "&quot;",
                    "'": "&#39;"
                }[c];
            });
        }

        function tieneRespuesta(clave, indice) {
            if (indice !== undefined) {
                const respuestas =
                    estadoActual.respuestas.partidas[indice] || {};

                return Object.prototype.hasOwnProperty.call(
                    respuestas,
                    clave
                );
            }

            return Object.prototype.hasOwnProperty.call(
                estadoActual.respuestas,
                clave
            );
        }

        function obtenerSiguientePregunta(resultado) {
            const pendientes = resultado.pendientes || [];

            // Primero resolver familia y modelo.
            for (const clave of ["familia", "modelo"]) {
                if (
                    pendientes.includes(clave) &&
                    !tieneRespuesta(clave)
                ) {
                    return {
                        clave: clave,
                        indice: undefined
                    };
                }
            }

            // Después resolver preguntas particulares de cada partida.
            (resultado.partidas || []).forEach(function () {});

            for (let i = 0; i < (resultado.partidas || []).length; i++) {
                const partida = resultado.partidas[i];

                for (const clave of partida.pendientes || []) {
                    if (
                        !tieneRespuesta(clave, i) &&
                        !tieneRespuesta(clave)
                    ) {
                        return {
                            clave: clave,
                            indice: i
                        };
                    }
                }
            }

            // Finalmente, preguntas globales como el empaque.
            for (const clave of pendientes) {
                if (["familia", "modelo"].includes(clave)) continue;

                if (!tieneRespuesta(clave)) {
                    return {
                        clave: clave,
                        indice: undefined
                    };
                }
            }

            return null;
        }

        function etiquetaPregunta(clave) {
            const etiquetas = {
                familia: "Selecciona la familia del producto",
                modelo: "Indica el modelo exacto",
                tornillo: "¿Hay tornillo a la medida, comprado o en stock?",
                pad: "¿Lleva pad?",
                diametro: "¿Cuál es el diámetro del tornillo?",
                empaque: "¿Qué tamaño de empaque corresponde al pedido?",
                grande: "¿El producto corresponde a la medida grande?"
            };

            return etiquetas[clave] || clave;
        }

        function renderizarPregunta(pregunta, resultado, mensajeError) {
            const clave = pregunta.clave;
            const indice = pregunta.indice;

            const esGlobal = indice === undefined;

            let descripcion = "";

            if (indice !== undefined) {
                descripcion = `
                    <p class="text-muted small">
                        Esta respuesta corresponde a la partida ${indice + 1}.
                    </p>
                `;
            }

            let campo = "";

            if (clave === "familia") {
                const opciones = resultado.familiasDisponibles || [];

                campo = `
                    <select class="form-select" id="respuestaRuta" required>
                        <option value="">Selecciona una familia</option>
                        ${opciones.map(function (f) {
                            return `
                                <option value="${escapar(f.familia)}">
                                    ${escapar(f.familia)}
                                </option>
                            `;
                        }).join("")}
                    </select>
                `;
            } else if (clave === "modelo") {
                const opciones = resultado.modelosDisponibles || [];

                campo = `
                    <input
                        class="form-control"
                        id="respuestaRuta"
                        list="modelosDisponiblesRuta"
                        maxlength="100"
                        placeholder="Ej. MT-2 o ETH-1"
                        autocomplete="off"
                        required
                    >
                    <datalist id="modelosDisponiblesRuta">
                        ${opciones.map(function (m) {
                            return `<option value="${escapar(m)}"></option>`;
                        }).join("")}
                    </datalist>
                    <small class="text-muted">
                        Puedes escribir el modelo exacto.
                    </small>
                `;
            } else if (clave === "empaque") {
                campo = `
                    <select class="form-select" id="respuestaRuta" required>
                        <option value="">Selecciona</option>
                        <option value="chico">Chico</option>
                        <option value="mediano">Mediano</option>
                        <option value="grande">Grande</option>
                    </select>
                `;
            } else if (
                ["tornillo", "pad", "grande"].includes(clave)
            ) {
                campo = `
                    <select class="form-select" id="respuestaRuta" required>
                        <option value="">Selecciona</option>
                        <option value="si">Sí</option>
                        <option value="no">No</option>
                    </select>
                `;
            } else if (clave === "diametro") {
                campo = `
                    <input
                        class="form-control"
                        id="respuestaRuta"
                        placeholder="Ej. 3/8, 1/2, 5/8 o M12"
                        autocomplete="off"
                    >
                    <small class="text-muted">
                        Si se deja vacío, el motor utiliza 1/2 pulgada.
                    </small>
                `;
            } else {
                mostrarError("Pregunta no reconocida: " + clave);
                return;
            }

            panelVista.innerHTML = "";
            btnConfirmar.disabled = true;

            panelPreguntas.innerHTML = `
                <div class="card border-0 bg-light">
                    <div class="card-body">
                        <h6 class="fw-bold mb-3">
                            ${escapar(etiquetaPregunta(clave))}
                        </h6>

                        ${mensajeError ? `
                            <div class="alert alert-danger py-2">
                                ${escapar(mensajeError)}
                            </div>
                        ` : ""}

                        ${descripcion}

                        <form id="formPreguntaRuta">
                            ${campo}

                            <div class="text-danger small mt-2" id="errorPreguntaRuta"></div>

                            <button
                                type="submit"
                                class="btn-inaher mt-3"
                            >
                                Continuar
                                <i class="bi bi-arrow-right"></i>
                            </button>
                        </form>
                    </div>
                </div>
            `;

            document.getElementById("formPreguntaRuta")
                .addEventListener("submit", function (event) {
                    event.preventDefault();

                    const control = document.getElementById("respuestaRuta");
                    let valor = control.value.trim();

                    if (!valor && clave !== "diametro") {
                        control.focus();
                        return;
                    }

                    if (clave === "diametro" && !valor) {
                        valor = "1/2";
                    } else if (
                        ["tornillo", "pad", "grande"].includes(clave)
                    ) {
                        valor = valor === "si";
                    }

                    if (esGlobal) {
                        estadoActual.respuestas[clave] = valor;
                    } else {
                        if (!estadoActual.respuestas.partidas[indice]) {
                            estadoActual.respuestas.partidas[indice] = {};
                        }

                        estadoActual.respuestas.partidas[indice][clave] = valor;
                    }

                    calcularRuta();
                });
        }

        function calcularRuta() {
            try {
                const resultado = motor.rutaDePedido(
                    estadoActual.pedido.descripcion,
                    estadoActual.respuestas
                );

                estadoActual.resultado = resultado;

                if (resultado.error && !resultado.pendientes.length) {
                    mostrarError(resultado.error);
                    return;
                }

                if (resultado.error) {
                    estado.textContent = resultado.error;
                    estado.className = "alert alert-warning py-2";
                }

                if (resultado.error && Array.isArray(resultado.pendientes)) {
                    if (resultado.pendientes.includes("familia")) {
                        delete estadoActual.respuestas.familia;
                        delete estadoActual.respuestas.modelo;
                    }

                    if (resultado.pendientes.includes("modelo")) {
                        delete estadoActual.respuestas.modelo;
                    }
                }

                const pregunta = obtenerSiguientePregunta(resultado);

                if (pregunta) {
                    renderizarPregunta(pregunta, resultado, resultado.error || "");
                    return;
                }

                if ((resultado.pendientes || []).length > 0) {
                    mostrarError(
                        "Quedan respuestas pendientes que el formulario no pudo resolver."
                    );
                    return;
                }

                if (!resultado.pasos || resultado.pasos.length === 0) {
                    mostrarError("El motor no generó operaciones.");
                    return;
                }

                renderizarVistaPrevia(resultado);

            } catch (error) {
                mostrarError(error.message);
            }
        }

        function renderizarVistaPrevia(resultado) {
            panelPreguntas.innerHTML = "";

            const pedido = estadoActual.pedido;

            estadoActual.maquinas = {};

            let html = `
                <div class="alert alert-success">
                    <strong>Ruta calculada correctamente.</strong>
                    <div class="small">
                        Pedido: ${escapar(pedido.numero)}
                        · ${escapar(pedido.descripcion)}
                    </div>
                </div>
            `;

            (resultado.partidas || []).forEach(function (partida, indice) {
                const cantidad = partida.cantidad ?? pedido.cantidad;

                const material = partida.material === "inox"
                    ? "Inoxidable"
                    : "Fierro galvanizado";

                const pad = partida.pad === true
                    ? "Con pad"
                    : (partida.pad === false
                        ? "Sin pad"
                        : "No definido / no aplica");

                const filas = (partida.pasos || []).map(function (paso, i) {
                    const clave = indice + "-" + i;

                    const opciones = Array.isArray(paso.opcionesMaquina)
                        ? paso.opcionesMaquina.slice()
                        : [];

                    if (
                        paso.maquina &&
                        !opciones.includes(paso.maquina)
                    ) {
                        opciones.unshift(paso.maquina);
                    }

                    let selectorMaquina = "";

                    if (opciones.length > 0) {
                        const seleccionada = paso.maquina || "";

                        if (seleccionada) {
                            estadoActual.maquinas[clave] = seleccionada;
                        }

                        selectorMaquina = `
                            <select
                                class="form-select form-select-sm js-maquina-ruta"
                                data-maquina-key="${clave}"
                            >
                                <option
                                    value=""
                                    ${!seleccionada ? "selected" : ""}
                                >
                                    Seleccionar máquina
                                </option>

                                ${opciones.map(function (maquina) {
                                    return `
                                        <option
                                            value="${escapar(maquina)}"
                                            ${maquina === seleccionada ? "selected" : ""}
                                        >
                                            ${escapar(maquina)}
                                        </option>
                                    `;
                                }).join("")}
                            </select>
                        `;
                    } else {
                        selectorMaquina = `
                            <span class="text-danger small js-maquina-sin-opciones">
                                Sin máquina configurada
                            </span>
                        `;
                    }

                    return `
                        <tr>
                            <td>${i + 1}</td>

                            <td>
                                <strong>${escapar(paso.madre)}</strong>

                                <div class="small text-muted">
                                    ${escapar(paso.detallada)}
                                </div>

                                ${paso.nota ? `
                                    <div class="small text-secondary">
                                        ${escapar(paso.nota)}
                                    </div>
                                ` : ""}
                            </td>

                            <td>
                                ${selectorMaquina}
                            </td>
                        </tr>
                    `;
                }).join("");

                html += `
                    <div class="card mb-3">
                        <div class="card-body">
                            <h6 class="fw-bold">
                                Partida ${indice + 1}: ${escapar(partida.modelo)}
                            </h6>

                            <div class="small text-muted mb-3">
                                ${escapar(partida.familia)}
                            </div>

                            <div class="row g-2 small mb-3">
                                <div class="col-6">
                                    <strong>Cantidad:</strong>
                                    ${escapar(cantidad)}
                                </div>

                                <div class="col-6">
                                    <strong>Diámetro:</strong>
                                    ${escapar(partida.diametro || "No indicado")}
                                </div>

                                <div class="col-6">
                                    <strong>Material:</strong>
                                    ${material}
                                </div>

                                <div class="col-6">
                                    <strong>Pad:</strong>
                                    ${pad}
                                </div>
                            </div>

                            <div class="table-responsive">
                                <table class="table table-sm table-bordered align-middle">
                                    <thead class="table-light">
                                        <tr>
                                            <th style="width: 55px;">Paso</th>
                                            <th>Operación</th>
                                            <th style="min-width: 220px;">Máquina</th>
                                        </tr>
                                    </thead>

                                    <tbody>
                                        ${filas}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                `;
            });

            html += `
                <div class="alert alert-warning small">
                    Los tiempos estándar se consultarán al conectar las operaciones
                    con los catálogos de Django. No se están inventando minutos.
                </div>

                <div class="alert alert-info small">
                    Esta versión permite revisar la ruta y seleccionar las máquinas,
                    pero todavía no guarda tareas en la base de datos.
                </div>
            `;

            panelVista.innerHTML = html;

            panelVista.querySelectorAll(".js-maquina-ruta")
                .forEach(function (select) {
                    select.addEventListener("change", function () {
                        const clave = this.dataset.maquinaKey;

                        if (this.value) {
                            estadoActual.maquinas[clave] = this.value;
                        } else {
                            delete estadoActual.maquinas[clave];
                        }

                        actualizarEstadoMaquinas(resultado);
                    });
                });

            actualizarEstadoMaquinas(resultado);

            btnConfirmar.disabled = true;
            btnConfirmar.title =
                "El guardado se habilitará después de validar la integración con Django.";
        }

        function actualizarEstadoMaquinas(resultado) {
            const selectores = Array.from(
                panelVista.querySelectorAll(".js-maquina-ruta")
            );

            const pendientes = selectores.filter(function (select) {
                return !select.value;
            }).length;

            const sinOpciones = panelVista.querySelectorAll(
                ".js-maquina-sin-opciones"
            ).length;

            if (pendientes || sinOpciones) {
                estado.textContent =
                    resultado.pasos.length +
                    " operaciones generadas. Faltan " +
                    (pendientes + sinOpciones) +
                    " selecciones de máquina.";

                estado.className = "alert alert-warning py-2";
            } else {
                estado.textContent =
                    resultado.pasos.length +
                    " operaciones generadas. Máquinas seleccionadas. Vista previa lista.";

                estado.className = "alert alert-success py-2";
            }
        }
        function mostrarError(mensaje) {
            estado.textContent = mensaje;
            estado.className = "alert alert-danger py-2";
        }

        function limpiar() {
            estadoActual = {
                pedido: null,
                respuestas: { partidas: [] },
                resultado: null
            };

            panelPreguntas.innerHTML = "";
            panelVista.innerHTML = "";

            btnConfirmar.disabled = true;
            btnConfirmar.title = "";
        }

        btnAnalizar.addEventListener("click", function () {
            const opcion = selectPedido.selectedOptions[0];

            if (!opcion || !opcion.value) {
                mostrarError("Selecciona un pedido.");
                return;
            }

            estadoActual = {
                pedido: {
                    id: opcion.value,
                    numero: opcion.dataset.numero || opcion.textContent.trim(),
                    descripcion: opcion.dataset.descripcion || "",
                    cantidad: Number(opcion.dataset.cantidad || 1)
                },
                respuestas: { partidas: [] },
                resultado: null
            };

            if (!estadoActual.pedido.descripcion) {
                mostrarError("El pedido no contiene una descripción válida.");
                return;
            }

            calcularRuta();
        });

        selectPedido.addEventListener("change", limpiar);

        modal.addEventListener("hidden.bs.modal", limpiar);
    }
})();