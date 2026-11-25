// Cargar ruta de pedido (regla 7 de Designación diaria v2).
// 1 · Pedido y partidas  2 · Preguntas  3 · Vista previa → se crean las tareas.
// El motor se llama UNA VEZ POR PARTIDA con el texto de esa partida: así cada partida
// toma su propio material (con el pedido completo, una partida galvanizada salía inox).
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        const modal = document.getElementById("modalCargarRuta");
        if (!modal) return;

        const motor = window.MotorRutasINAHER;
        const $ = function (id) { return document.getElementById(id); };
        const estado = $("estadoMotorRuta");
        const selectPedido = $("pedidoRuta");
        const paso1 = $("rutaPaso1"), paso2 = $("rutaPaso2"), paso3 = $("rutaPaso3");
        const btnSiguiente = $("btnRutaSiguiente"), btnAtras = $("btnRutaAtras");
        const etiquetaPaso = $("pasoRuta");
        const URLS = modal.dataset;

        const EMPAQUES = [
            ["chico", "Chico", "hasta 5 kg"],
            ["mediano", "Mediano", "hasta 10 kg"],
            ["grande", "Grande", "hasta 25 kg"],
            ["extra grande", "Extra grande", "más de 25 kg"],
        ];
        const PREGUNTAS = {
            tornillo: "¿Hay tornillo a la medida (comprado o en stock)?",
            anclaje: "¿Lleva barrenos de anclaje?",
            pad: "¿Lleva pad?",
            diametro: "No se leyó el diámetro del tornillo. Escríbelo (ej. 1/2, 5/8, M12). Vacío = 1/2",
            grande: "¿Es la medida grande?",
        };

        let paso = 1;
        let pedido = null;      // respuesta de api/ruta-pedido
        let partidas = [];      // [{id, cantidad, descripcion, tareas, marcada, lectura, respuestas, resultado}]
        let empaque = null;
        let vista = null;       // lo que se manda a guardar

        function escapar(v) {
            return String(v ?? "").replace(/[&<>"']/g, function (c) {
                return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
            });
        }
        function aviso(texto, tipo) {
            estado.textContent = texto;
            estado.className = `alert alert-${tipo || "secondary"} py-2`;
        }
        function irA(n) {
            paso = n;
            paso1.classList.toggle("d-none", n !== 1);
            paso2.classList.toggle("d-none", n !== 2);
            paso3.classList.toggle("d-none", n !== 3);
            etiquetaPaso.textContent = ["", "paso 1 de 3 · pedido y partidas", "paso 2 de 3 · preguntas", "paso 3 de 3 · vista previa"][n];
            btnAtras.textContent = n === 1 ? "Cancelar" : "Atrás";
            if (n === 1) btnAtras.setAttribute("data-bs-dismiss", "modal");
            else btnAtras.removeAttribute("data-bs-dismiss");
        }

        // ---------------------------------------------------------------- datos del motor
        fetch(URLS.jsonUrl)
            .then(function (r) {
                if (!r.ok) throw new Error("No se pudieron cargar los datos de rutas.");
                return r.json();
            })
            .then(function (datos) {
                motor.cargarDatos(datos);
                aviso("Elige el pedido. Se cargan las partidas marcadas.", "secondary");
            })
            .catch(function (e) { aviso(e.message, "danger"); });

        // ---------------------------------------------------------------- paso 1 · pedido y partidas
        function lecturaDe(texto) {
            try {
                const r = motor.rutaDePedido(texto, {});
                if (r.error) return { error: "Modelo no reconocido: corrige la partida en Pedidos o agrega las tareas a mano." };
                const p = r.partidas[0] || {};
                return { modelo: p.modelo, familia: p.familia, diametro: p.diametro, material: p.material, pad: p.pad, varias: r.partidas.length > 1 };
            } catch (e) {
                return { error: e.message };
            }
        }

        function pintarPartidas() {
            const filas = partidas.map(function (p, i) {
                const l = p.lectura;
                const leido = l.error
                    ? `<span class="text-danger small">${escapar(l.error)}</span>`
                    : `<strong>${escapar(l.modelo)}</strong> · ${escapar(l.familia)}<br>
                       <small>Ø ${escapar(l.diametro || "sin leer")} · <span class="badge ${l.material === "inox" ? "bg-info-subtle text-info-emphasis" : "bg-warning-subtle text-warning-emphasis"}">${l.material === "inox" ? "inox-304" : "fierro-galv"}</span>
                       ${l.pad === true ? " · con pad" : (l.pad === false ? " · sin pad" : "")}</small>`;
                const cargada = p.tareas
                    ? `<span class="badge bg-secondary-subtle text-secondary-emphasis">ya tiene ${p.tareas} tarea${p.tareas === 1 ? "" : "s"}</span>`
                    : `<span class="badge bg-light text-muted border">ruta sin cargar</span>`;
                return `<tr>
                    <td><input type="checkbox" class="form-check-input js-partida" data-i="${i}" ${p.marcada ? "checked" : ""} ${l.error ? "disabled" : ""} aria-label="Cargar partida ${i + 1}"></td>
                    <td class="text-end">${escapar(p.cantidad)}</td>
                    <td>${escapar(p.descripcion)}<br>${cargada}</td>
                    <td>${leido}</td>
                </tr>`;
            }).join("");
            $("partidasRuta").innerHTML = partidas.length ? `
                <div class="table-responsive"><table class="table table-sm align-middle">
                    <thead class="table-light"><tr><th></th><th class="text-end">Cant</th><th>Partida <small class="fw-normal text-muted">como se capturó en Pedidos</small></th><th>Lo que leyó el motor</th></tr></thead>
                    <tbody>${filas}</tbody>
                </table></div>
                <p class="small text-muted mb-0">Modelo, familia, Ø, material y pad los lee el motor del texto de cada partida. Si algo se leyó mal, corrige la partida en Pedidos.</p>`
                : `<p class="text-muted">Este pedido no tiene partidas.</p>`;
            $("partidasRuta").querySelectorAll(".js-partida").forEach(function (cb) {
                cb.addEventListener("change", function () {
                    partidas[Number(cb.dataset.i)].marcada = cb.checked;
                    btnSiguiente.disabled = !partidas.some(function (p) { return p.marcada; });
                });
            });
            btnSiguiente.disabled = !partidas.some(function (p) { return p.marcada; });
        }

        selectPedido.addEventListener("change", function () {
            reiniciar(false);
            if (!selectPedido.value) return;
            fetch(`${URLS.urlPedido}?pedido_id=${encodeURIComponent(selectPedido.value)}`)
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    pedido = d;
                    $("infoPedidoRuta").innerHTML = `${escapar(d.cantidad)} pzas · sale ${escapar(d.fecha_salida || "sin fecha")}
                        <span class="status-badge ${escapar(d.alerta_clase)}">${escapar(d.alerta)}</span><br>estatus ${escapar(d.estatus)}`;
                    partidas = d.partidas.map(function (p) {
                        const lectura = lecturaDe(p.descripcion);
                        // Ya cargada: viene sin marcar (cargarla otra vez pide confirmar)
                        return Object.assign({}, p, { lectura: lectura, marcada: !p.tareas && !lectura.error, respuestas: {} });
                    });
                    pintarPartidas();
                    aviso("Revisa las partidas marcadas y oprime Siguiente.", "secondary");
                })
                .catch(function () { aviso("No se pudo leer el pedido.", "danger"); });
        });

        // ---------------------------------------------------------------- paso 2 · preguntas
        function calcular() {
            // Una llamada por partida, con sus respuestas y el mismo empaque en todas
            let faltaEmpaque = false;
            partidas.filter(function (p) { return p.marcada; }).forEach(function (p) {
                const resp = Object.assign({}, p.respuestas, { empaque: empaque || undefined });
                p.resultado = motor.rutaDePedido(p.descripcion, resp);
                p.pendientes = (p.resultado.pendientes || []).filter(function (q) { return q !== "empaque"; });
                if ((p.resultado.pendientes || []).indexOf("empaque") >= 0 || tieneEmpaquetar(p.resultado)) faltaEmpaque = true;
            });
            return faltaEmpaque && !empaque;
        }

        function esEmpaquetarPedido(paso) {
            return paso.madre === "Empaquetar" && /^Empaquetar pedido/i.test(paso.detallada);
        }
        function tieneEmpaquetar(r) {
            return (r.pasos || []).some(esEmpaquetarPedido);
        }

        function radios(nombre, actual) {
            return `<div class="d-flex gap-3">
                <label class="form-check"><input class="form-check-input" type="radio" name="${nombre}" value="si" ${actual === true ? "checked" : ""}> Sí</label>
                <label class="form-check"><input class="form-check-input" type="radio" name="${nombre}" value="no" ${actual === false ? "checked" : ""}> No</label>
            </div>`;
        }

        function pintarPreguntas(faltaEmpaque) {
            let html = "";
            partidas.filter(function (p) { return p.marcada; }).forEach(function (p) {
                const i = partidas.indexOf(p);
                if (!p.pendientes.length) {
                    html += `<p class="small mb-2"><strong>${escapar(p.lectura.modelo)}</strong> · sin preguntas</p>`;
                    return;
                }
                html += `<div class="mb-3"><div class="fw-semibold text-primary small mb-1">${escapar(p.lectura.modelo)} · ${escapar(p.descripcion)}</div>`;
                p.pendientes.forEach(function (q) {
                    const nombre = `p${i}_${q}`;
                    const campo = q === "diametro"
                        ? `<input class="form-control form-control-sm" name="${nombre}" placeholder="Ej. 1/2, 5/8, M12" value="${escapar(p.respuestas.diametro || "")}">`
                        : radios(nombre, p.respuestas[q]);
                    html += `<div class="mb-2"><div class="small">${escapar(PREGUNTAS[q] || q)}</div>${campo}</div>`;
                });
                html += "</div>";
            });
            if (faltaEmpaque || empaque) {
                html += `<hr><div class="fw-semibold small mb-1">Paquete de todo el pedido</div>` + EMPAQUES.map(function (e) {
                    return `<label class="form-check"><input class="form-check-input" type="radio" name="empaque" value="${e[0]}" ${empaque === e[0] ? "checked" : ""}>
                        ${e[1]} <small class="text-muted">· ${e[2]}</small></label>`;
                }).join("") + `<small class="text-muted d-block mt-1">Si va emplayado, sube un tamaño.</small>`;
            }
            paso2.innerHTML = html;
        }

        function leerPreguntas() {
            let completas = true;
            partidas.filter(function (p) { return p.marcada; }).forEach(function (p) {
                const i = partidas.indexOf(p);
                p.pendientes.forEach(function (q) {
                    if (q === "diametro") {
                        const el = paso2.querySelector(`[name="p${i}_diametro"]`);
                        p.respuestas.diametro = el && el.value.trim() ? el.value.trim() : "1/2";
                        return;
                    }
                    const el = paso2.querySelector(`[name="p${i}_${q}"]:checked`);
                    if (el) p.respuestas[q] = el.value === "si";
                    else completas = false;
                });
            });
            const e = paso2.querySelector('[name="empaque"]:checked');
            if (paso2.querySelector('[name="empaque"]')) {
                if (e) empaque = e.value;
                else completas = false;
            }
            return completas;
        }

        function avanzarDesdePreguntas() {
            const faltaEmpaque = calcular();
            const pendientes = partidas.some(function (p) { return p.marcada && p.pendientes.length; });
            if (pendientes || faltaEmpaque) {
                pintarPreguntas(faltaEmpaque);
                irA(2);
                aviso("Contesta las preguntas que pide el motor para cada partida.", "secondary");
                btnSiguiente.disabled = false;
                return;
            }
            prepararVista();
        }

        // ---------------------------------------------------------------- paso 3 · vista previa
        function prepararVista() {
            const avisos = [];
            const grupos = [];
            let maquinaEmpaque = "";
            partidas.filter(function (p) { return p.marcada; }).forEach(function (p) {
                const r = p.resultado;
                if (r.error) { avisos.push(`${p.descripcion}: modelo no reconocido, no se carga.`); return; }
                // Se quita el "Empaquetar pedido …" de cada llamada: va uno solo para todo el pedido
                const pasos = (r.pasos || []).filter(function (x) {
                    if (esEmpaquetarPedido(x)) { maquinaEmpaque = maquinaEmpaque || x.maquina; return false; }
                    return true;
                }).map(function (x, k) {
                    return { orden: k + 1, madre: x.madre, detallada: x.detallada, maquina: x.maquina || "", opciones: x.opcionesMaquina || [], cantidad: p.cantidad };
                });
                if (!pasos.length) { avisos.push(`${p.descripcion}: la familia no tiene pasos con esas respuestas, no se carga.`); return; }
                const leido = p.lectura;
                grupos.push({ partida_id: p.id, titulo: `${leido.modelo} · Ø ${leido.diametro || "1/2"} · ${leido.material === "inox" ? "inox-304" : "fierro-galv"}${leido.pad ? " · con pad" : ""} · ${p.cantidad} pzas`, pasos: pasos });
            });

            let empaquetar = null;
            if (empaque && grupos.length) {
                const ultimo = Math.max.apply(null, grupos.map(function (g) { return g.pasos.length; }));
                const mq = motor.maquinasDe("Empaquetar");
                empaquetar = { orden: ultimo + 1, madre: "Empaquetar", detallada: `Empaquetar pedido ${empaque}`,
                    maquina: maquinaEmpaque || mq.preferida || "", opciones: mq.opciones || [], cantidad: pedido.cantidad };
            }
            vista = { grupos: grupos, empaquetar: empaquetar, avisos: avisos };

            if (!grupos.length) {
                aviso(avisos.join(" ") || "No hay pasos que cargar.", "warning");
                return;
            }

            // Min de cada paso con los tiempos vigentes del catálogo
            const todos = grupos.flatMap(function (g) { return g.pasos; }).concat(empaquetar ? [empaquetar] : []);
            fetch(URLS.urlMinutos, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": URLS.csrf, "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify(todos.map(function (x) { return { madre: x.madre, detallada: x.detallada, cantidad: x.cantidad }; })),
            })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    (d.minutos || []).forEach(function (m, k) { todos[k].minutos = m; });
                    pintarVista();
                })
                .catch(function () { pintarVista(); });
        }

        function selectorMaquina(x, clave) {
            const opciones = x.opciones.slice();
            if (x.maquina && opciones.indexOf(x.maquina) < 0) opciones.unshift(x.maquina);
            return `<select class="form-select form-select-sm js-maquina-ruta${x.maquina ? "" : " marca-rojo"}" data-clave="${clave}">
                <option value="">Elegir máquina</option>
                ${opciones.map(function (m) { return `<option value="${escapar(m)}" ${m === x.maquina ? "selected" : ""}>${escapar(m)}</option>`; }).join("")}
            </select>`;
        }

        function filaPaso(x, clave) {
            return `<tr>
                <td>${x.orden}</td>
                <td><strong>${escapar(x.madre)}</strong> › ${escapar(x.detallada)}</td>
                <td>${selectorMaquina(x, clave)}</td>
                <td class="text-end">${escapar(x.cantidad)}</td>
                <td class="text-end">${x.minutos === null || x.minutos === undefined ? "—" : x.minutos}</td>
            </tr>`;
        }

        function pintarVista() {
            let html = `<div class="table-responsive"><table class="table table-sm align-middle">
                <thead class="table-light"><tr><th>Paso</th><th>Operación madre › detallada</th><th style="min-width:200px">Máquina</th><th class="text-end">Cant</th><th class="text-end">Min</th></tr></thead><tbody>`;
            vista.grupos.forEach(function (g, gi) {
                html += `<tr class="table-light"><td colspan="5" class="fw-semibold small">Partida · ${escapar(g.titulo)} · ${g.pasos.length} pasos</td></tr>`;
                g.pasos.forEach(function (x, k) { html += filaPaso(x, `${gi}-${k}`); });
            });
            if (vista.empaquetar) {
                html += `<tr class="table-light"><td colspan="5" class="fw-semibold small">Todo el pedido</td></tr>` + filaPaso(vista.empaquetar, "E");
            }
            html += "</tbody></table></div>";
            if (vista.avisos.length) html += `<div class="alert alert-warning small">${vista.avisos.map(escapar).join("<br>")}</div>`;

            const todos = vista.grupos.flatMap(function (g) { return g.pasos; }).concat(vista.empaquetar ? [vista.empaquetar] : []);
            const minutos = todos.reduce(function (s, x) { return s + (x.minutos || 0); }, 0);
            const sinTiempo = todos.filter(function (x) { return x.minutos === null || x.minutos === undefined; }).length;
            html += `<p class="small text-muted mb-0">${todos.length} tareas · ${minutos} min · ${sinTiempo} sin tiempo · nacen sin persona y sin detalle. Nada se guarda hasta confirmar.</p>`;
            paso3.innerHTML = html;

            paso3.querySelectorAll(".js-maquina-ruta").forEach(function (sel) {
                sel.addEventListener("change", function () {
                    const clave = sel.dataset.clave;
                    const x = clave === "E" ? vista.empaquetar : vista.grupos[Number(clave.split("-")[0])].pasos[Number(clave.split("-")[1])];
                    x.maquina = sel.value;
                    sel.classList.toggle("marca-rojo", !sel.value);
                });
            });

            irA(3);
            btnSiguiente.textContent = `Agregar ${todos.length} tareas`;
            btnSiguiente.disabled = false;
            aviso("Revisa la vista previa. Las máquinas vacías quedan en rojo para escoger después.", "success");
        }

        function guardar(confirmar) {
            btnSiguiente.disabled = true;
            const limpio = function (x) { return { orden: x.orden, madre: x.madre, detallada: x.detallada, maquina: x.maquina }; };
            fetch(URLS.urlGuardar, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": URLS.csrf, "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({
                    pedido_id: pedido.id,
                    confirmar: Boolean(confirmar),
                    partidas: vista.grupos.map(function (g) { return { partida_id: g.partida_id, pasos: g.pasos.map(limpio) }; }),
                    empaquetar: vista.empaquetar ? limpio(vista.empaquetar) : null,
                }),
            })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d.ok) { window.location.href = d.url; return; }
                    if (d.confirmar) {
                        const lista = (d.repetidas || []).join("\n· ");
                        if (window.confirm(`Estas partidas ya tienen tareas cargadas:\n· ${lista}\n\n¿Cargarlas otra vez?`)) { guardar(true); return; }
                        btnSiguiente.disabled = false;
                        return;
                    }
                    aviso(d.error || "No se pudieron guardar las tareas.", "danger");
                    btnSiguiente.disabled = false;
                })
                .catch(function () { aviso("No se pudieron guardar las tareas.", "danger"); btnSiguiente.disabled = false; });
        }

        // ---------------------------------------------------------------- botones
        btnSiguiente.addEventListener("click", function () {
            try {
                if (paso === 1) {
                    partidas.forEach(function (p) { p.respuestas = {}; });
                    empaque = null;
                    avanzarDesdePreguntas();
                } else if (paso === 2) {
                    if (!leerPreguntas()) { aviso("Faltan respuestas.", "warning"); return; }
                    avanzarDesdePreguntas();
                } else if (paso === 3) {
                    guardar(false);
                }
            } catch (e) {
                aviso(e.message, "danger");
            }
        });

        btnAtras.addEventListener("click", function () {
            if (paso === 1) return;  // Cancelar: lo cierra Bootstrap
            btnSiguiente.textContent = "Siguiente";
            btnSiguiente.disabled = false;
            if (paso === 3 && paso2.innerHTML.trim()) irA(2);
            else irA(1);
        });

        function reiniciar(todo) {
            pedido = null; partidas = []; empaque = null; vista = null;
            paso2.innerHTML = paso3.innerHTML = "";
            $("partidasRuta").innerHTML = "";
            $("infoPedidoRuta").innerHTML = "";
            btnSiguiente.textContent = "Siguiente";
            btnSiguiente.disabled = true;
            irA(1);
            if (todo) selectPedido.value = "";
        }

        modal.addEventListener("hidden.bs.modal", function () { reiniciar(true); });
    });
})();
