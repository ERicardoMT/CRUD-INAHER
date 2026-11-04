/* =====================================================================
   INAHER · Motor de rutas de producción (JavaScript puro, sin Google)
   ---------------------------------------------------------------------
   Reproduce exactamente lo que hace "INAHER › Cargar ruta en HOY" del
   pizarrón (Designación Diaria V3) pero sin hojas de cálculo:

      const motor = require('./motor_rutas_inaher.js');
      const r = motor.rutaDePedido("50 MT-2 de 3/8 x 2 galv con pad", { tornillo:false, empaque:"chico" });

   Devuelve la lista de pasos (operación madre › operación detallada,
   máquina preferida y opciones, condición y nota) por partida, y qué
   preguntas faltan por responder (si falta alguna, regresa `pendientes`
   y hay que volver a llamar con la respuesta).

   Los datos (familias, rutas, operaciones, máquinas) viven en
   datos_rutas_inaher.json y se generan desde el pizarrón; este archivo
   solo tiene la lógica. Probado contra los mismos 500 casos del
   pizarrón (ver validar_motor.js).

   Funciona en Node (require) y en navegador (window.MotorRutasINAHER).
   ===================================================================== */
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.MotorRutasINAHER = factory(); }
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ------------------------------------------------------------ datos
  var DATOS = null;
  function cargarDatos(d) { DATOS = d; return d; }
  function datos() {
    if (!DATOS) {
      if (typeof require === "function") { DATOS = require("./datos_rutas_inaher.json"); }
      else { throw new Error("Llama primero a cargarDatos(json) con el contenido de datos_rutas_inaher.json"); }
    }
    return DATOS;
  }

  // ------------------------------------------------- texto y medidas
  function norm(s) { return String(s).toLowerCase().replace(/á/g, "a").replace(/é/g, "e").replace(/í/g, "i").replace(/ó/g, "o").replace(/ú/g, "u").trim(); }
  var MM = { 6: 0.25, 8: 0.3125, 10: 0.375, 12: 0.5, 14: 0.5625, 16: 0.625, 18: 0.6875, 20: 0.75, 22: 0.8125, 24: 1, 27: 1.125, 30: 1.25, 36: 1.5 };
  var MATS = ["fierro-galv", "inox-304"];

  // "1/2", "1 1/4", "M12", "0.625" → pulgadas (número). null si no se entiende.
  function diamVal(s) {
    s = norm(String(s)).replace(/["”]/g, "").trim(); var m = s.match(/^m\s?(\d{1,2})$/); if (m) { return MM[Number(m[1])] || null; }
    var p = s.match(/^(\d+)\s+(\d+)\/(\d+)$/); if (p) { return Number(p[1]) + Number(p[2]) / Number(p[3]); }
    var q = s.match(/^(\d+)\/(\d+)$/); if (q) { return Number(q[1]) / Number(q[2]); }
    var n = s.match(/^(\d+(?:\.\d+)?)$/); if (n) { return Number(n[1]); } return null;
  }
  // Lee el diámetro del tornillo dentro del texto del pedido ("MT-2 de 3/8 x 2" → 0.375). null si no aparece.
  function parseDiam(txt) {
    var t = " " + norm(txt) + " ", m;
    m = t.match(/[^a-z0-9]m\s?(\d{1,2})(?!\d)/); if (m && MM[Number(m[1])]) { return MM[Number(m[1])]; }
    m = t.match(/[^\w\-\/\*\.](\d+\s+\d+\/\d+|\d+\/\d+|\d+(?:\.\d+)?)\s*["”]?\s*[x×]\s*\d/); if (m) { return diamVal(m[1]); }
    m = t.match(/[^\w\-\/\*\.](\d+\s+\d+\/\d+|\d+\/\d+)/); if (m) { return diamVal(m[1]); }
    m = t.match(/[^\w\-\/\*\.](\d+(?:\.\d+)?)\s*["”]/); if (m) { return diamVal(m[1]); }
    m = t.match(/[^\w\-\/\*\.]de ([12])(?![\d\/\.])(?!\s*(kg|pz|pza|piezas|mm|cm))/); if (m) { return Number(m[1]); }
    return null;
  }
  function esInox(t) { return /inox|acero 30[46]|t-?30[46]|ss ?30[46]/.test(norm(t)); }
  // true = dice "con pad", false = dice "sin pad", null = no dice nada (hay que preguntar)
  function padDe(t) { t = norm(t); return /sin pad/.test(t) ? false : (/\bpads?\b/.test(t) ? true : null); }
  function rangoDiam(d) { return d <= 0.376 ? "5/16-3/8 · M8-M10" : (d <= 0.626 ? "1/2-5/8 · M12-M16" : (d <= 1.001 ? "3/4-1\" · M20-M24" : "1 1/4-1 1/2 · M30-M36")); }
  function fmtDiam(d) { var t = { 0.25: "1/4", 0.3125: "5/16", 0.375: "3/8", 0.5: "1/2", 0.5625: "9/16", 0.625: "5/8", 0.6875: "11/16", 0.75: "3/4", 0.8125: "13/16", 0.875: "7/8", 1: "1\"", 1.125: "1 1/8", 1.25: "1 1/4", 1.5: "1 1/2" }; return t[d] || String(d); }
  // Cantidad escrita justo antes del modelo ("4 rebo y 6 scn" → 4 y 6)
  function cantAntes(t) { var m = String(t).match(/(?:^|,|;|\+|\by)\s*(\d{1,5})\s*(?:pzas?\.?|piezas?|pz\.?|jgos?\.?|juegos?)?\s*(?:de\s+)?$/i); return m ? Number(m[1]) : null; }

  // ----------------------------------------- detección de modelos
  // Busca en el texto del pedido los modelos de cada familia (los tokens
  // terminados en "-" son prefijos: "ETH-" reconoce ETH-1, ETH-4...).
  function detectarModelos(prod, fam) {
    var pn = norm(prod), out = [];
    fam.forEach(function (f) {
      String(f.modelos).split(",").map(function (x) { return norm(x); }).filter(function (x) { return x; }).forEach(function (t) {
        var pref = t.charAt(t.length - 1) === "-", src = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/-/g, "-?").replace(/ +/g, " ?"), re = new RegExp(src, "g"), mm;
        while ((mm = re.exec(pn))) {
          var idx = mm.index, len = mm[0].length; if (!len) { re.lastIndex++; continue; }
          var b = idx > 0 ? pn.charAt(idx - 1) : " ", a = pn.charAt(idx + len) || " ";
          var okB = !/[a-z0-9]/.test(b), okA = pref || !/[a-z0-9]/.test(a);
          if (okB && okA) { var modelo = t; if (pref) { var rest = pn.slice(idx + len).match(/^[a-z0-9\-\*\.]*/); modelo = t + (rest ? rest[0].replace(/^-/, "") : ""); } out.push({ familia: String(f.familia), token: t, modelo: modelo, pos: idx, fin: idx + len }); }
          re.lastIndex = idx + 1;
        }
      });
    });
    out.sort(function (x, y) { return x.pos - y.pos || (y.token.length - x.token.length); });
    var keep = []; out.forEach(function (h) { for (var k = 0; k < keep.length; k++) { if (h.pos < keep[k].fin && h.fin > keep[k].pos) { return; } } keep.push(h); });
    return keep;
  }

  // ------------------------------------------------- máquinas
  // Tipos de una madre: "Torno convencional / Torno CNC" → preferida + opciones.
  function maquinasDe(madre) {
    var D = datos(), md = D.madres.filter(function (m) { return m.madre === madre; })[0];
    if (!md) { return { preferida: "", opciones: [] }; }
    var tokens = String(md.tipos).split(" / ").map(function (x) { return x.trim(); }).filter(Boolean);
    var porTipo = {}, nombres = {};
    D.maquinas.forEach(function (m) { (porTipo[m.tipo] = porTipo[m.tipo] || []).push(m.maquina); nombres[m.maquina] = m.tipo; });
    var opciones = [];
    tokens.forEach(function (t) { if (nombres[t]) { opciones.push(t); } (porTipo[t] || []).forEach(function (m) { if (opciones.indexOf(m) < 0) { opciones.push(m); } }); });
    var t0 = tokens[0] || "", pref = nombres[t0] ? t0 : ((porTipo[t0] || []).length === 1 ? porTipo[t0][0] : "");
    return { preferida: pref, opciones: opciones };
  }

  // ------------------------------------------------- condiciones
  // Lenguaje de la columna "Condición" de Rutas, separado por ";":
  //   tornillo=si|no   ¿hay tornillo a la medida (comprado o en stock)?  → pregunta
  //   pad              lleva pad → se lee del pedido ("con pad"); si no dice, pregunta
  //   grande=si|no     (ya no se usa; se dejó por compatibilidad)      → pregunta
  //   stock=si|no      siempre se toma como "sí" (la base existe; el lote CNC se agrega a mano)
  //   d>=5/8  d<=3/4 d>1 d<1/2 d=1/2   diámetro del tornillo (pulgadas; M12 etc. se convierten)
  //   mat=fierro|inox  material (inox si el pedido dice inox / acero 304 / 316)
  //   modelo=MT-2,MTA  modelo exacto; "MTA-" = prefijo; modelo!=X = distinto de
  function enLista(modelo, lst, neg) {
    var m = norm(modelo).replace(/\s+/g, ""), ok = false;
    lst.split(",").forEach(function (x) { x = norm(x).replace(/\s+/g, ""); if (!x) { return; } if (x === m || (x.charAt(x.length - 1) === "-" && m.indexOf(x) === 0)) { ok = true; } });
    return neg ? !ok : ok;
  }
  // ctx = {d, mat, pad, modelo, resp:{tornillo,grande}, pendientes:[]}
  function cumple(cond, ctx) {
    cond = String(cond || "").trim(); if (!cond) { return true; }
    var partes = cond.split(";").map(function (p) { return norm(p); }).filter(Boolean);
    partes.sort(function (a, b) { var qa = /^(tornillo|grande|stock|pad)/.test(a) ? 1 : 0, qb = /^(tornillo|grande|stock|pad)/.test(b) ? 1 : 0; return qa - qb; });
    function pregunta(k) {
      if (k === "stock") { return true; }
      if (ctx.resp[k] === undefined || ctx.resp[k] === null) { if (ctx.pendientes.indexOf(k) < 0) { ctx.pendientes.push(k); } return false; }
      return !!ctx.resp[k];
    }
    function diam() { if (ctx.d === null) { if (ctx.resp.diametro !== undefined && ctx.resp.diametro !== null) { ctx.d = diamVal(ctx.resp.diametro) || 0.5; } else { if (ctx.pendientes.indexOf("diametro") < 0) { ctx.pendientes.push("diametro"); } return 0.5; } } return ctx.d; }
    return partes.every(function (p) {
      var m;
      if (p === "pad") { if (ctx.pad === null) { ctx.pad = pregunta("pad"); } return ctx.pad === true; }
      if ((m = p.match(/^(tornillo|grande|stock)\s*=\s*(si|sí|no)$/))) { var want = (m[2] !== "no"); return pregunta(m[1]) === want; }
      if ((m = p.match(/^d\s*(>=|<=|>|<|=)\s*(.+)$/))) {
        var v = diamVal(m[2]), d = diam(); if (v === null) { return true; }
        return m[1] === ">=" ? d >= v - 0.001 : (m[1] === "<=" ? d <= v + 0.001 : (m[1] === ">" ? d > v + 0.001 : (m[1] === "<" ? d < v - 0.001 : Math.abs(d - v) < 0.001)));
      }
      if ((m = p.match(/^mat\s*=\s*(fierro|inox)$/))) { return ctx.mat === m[1]; }
      if ((m = p.match(/^modelo\s*(!?=)\s*(.+)$/))) { return enLista(ctx.modelo, m[2], m[1] === "!="); }
      return true;
    });
  }

  // ------------------------------------------------- ruta de un pedido
  /**
   * rutaDePedido(textoPedido, respuestas)
   *   textoPedido : la columna Producto del pedido, tal cual ("50 MT-2 de 3/8 x 2 galv con pad")
   *   respuestas  : { empaque: "chico"|"mediano"|"grande",      ← una por pedido
   *                   partidas: [ {tornillo:true/false, pad:true/false, diametro:"1/2"}, ... ] }
   *                 (también se acepta {tornillo, pad, diametro} en la raíz: aplica a todas las partidas)
   * Devuelve { familias, partidas:[{modelo, familia, diametro, material, pad, cantidad, pendientes:[], pasos:[...]}],
   *            pendientes:[...], empaque, pasos: lista plana en el orden de HOY }
   * Si pendientes trae algo (p. ej. ["tornillo"]), hay que preguntar eso y volver a llamar.
   */
  function rutaDePedido(prod, respuestas) {
    var D = datos(); respuestas = respuestas || {};
    var hits = detectarModelos(prod, D.familias);
    if (!hits.length) {
      var familiasDisponibles = D.familias.map(function (f) {
        return { familia: f.familia, descripcion: f.descripcion };
      });

      if (!respuestas.familia) {
        return {
          familias: "",
          partidas: [],
          pendientes: ["familia"],
          pasos: [],
          familiasDisponibles: familiasDisponibles,
          error: "No reconozco el modelo"
        };
      }

      var familiaManual = D.familias.filter(function (f) {
        return norm(f.familia) === norm(respuestas.familia);
      })[0];

      if (!familiaManual) {
        return {
          familias: "",
          partidas: [],
          pendientes: ["familia"],
          pasos: [],
          familiasDisponibles: familiasDisponibles,
          error: "La familia seleccionada no es válida"
        };
      }

      var modelosDisponibles = String(familiaManual.modelos)
        .split(",")
        .map(function (x) { return x.trim(); })
        .filter(Boolean);

      var modeloManual = String(respuestas.modelo || "").trim();

      if (!modeloManual) {
        return {
          familias: familiaManual.familia,
          partidas: [],
          pendientes: ["modelo"],
          pasos: [],
          modelosDisponibles: modelosDisponibles,
          error: "Selecciona o escribe el modelo exacto del pedido"
        };
      }

      var modeloNorm = norm(modeloManual).replace(/\s+/g, "");

      var tokenModelo = modelosDisponibles.filter(function (token) {
        var tokenNorm = norm(token).replace(/\s+/g, "");

        return tokenNorm.charAt(tokenNorm.length - 1) === "-"
          ? modeloNorm.indexOf(tokenNorm) === 0
          : modeloNorm === tokenNorm;
      })[0];

      if (!tokenModelo) {
        return {
          familias: familiaManual.familia,
          partidas: [],
          pendientes: ["modelo"],
          pasos: [],
          modelosDisponibles: modelosDisponibles,
          error: "El modelo no pertenece a la familia seleccionada. Verifica el modelo o la familia."
        };
      }

      hits = [{
        familia: familiaManual.familia,
        token: tokenModelo,
        modelo: modeloManual,
        pos: 0,
        fin: 0
      }];
    }
    hits.forEach(function (h, k) { h.finTxt = k + 1 < hits.length ? hits[k + 1].pos : prod.length; var t = prod.slice(h.pos, h.finTxt); h.firma = [h.modelo, h.familia, parseDiam(t), esInox(t), padDe(t)].join("|"); h.q = cantAntes(prod.slice(k ? hits[k - 1].fin : 0, h.pos)); });
    var vistos = {}, suma = {}; hits.forEach(function (h) { suma[h.firma] = (suma[h.firma] === undefined) ? h.q : ((suma[h.firma] === null || h.q === null) ? null : suma[h.firma] + h.q); });
    hits = hits.filter(function (h) { if (vistos[h.firma]) { return false; } vistos[h.firma] = 1; return true; });
    var todas = hits.length > 1 && hits.every(function (h) { return suma[h.firma] !== null; });
    var multi = hits.length > 1, pn = norm(prod), pendientes = [], partidas = [], planos = [];
    hits.forEach(function (hit, k) {
      var rt = D.rutas.filter(function (r) { return norm(r.familia) === norm(hit.familia); });
      var tramo = prod.slice(hit.pos, hit.finTxt), pT = padDe(tramo);
      var rp = (respuestas.partidas && respuestas.partidas[k]) || {};
      var resp = { tornillo: rp.tornillo !== undefined ? rp.tornillo : respuestas.tornillo, grande: rp.grande !== undefined ? rp.grande : respuestas.grande, pad: rp.pad !== undefined ? rp.pad : respuestas.pad, diametro: rp.diametro !== undefined ? rp.diametro : respuestas.diametro };
      var ctx = { d: parseDiam(tramo), mat: esInox(tramo) ? "inox" : "fierro", pad: (pT !== null ? pT : (multi ? null : padDe(pn))), modelo: hit.modelo, resp: resp, pendientes: [] };
      var pasos = rt.filter(function (r) { return cumple(r.condicion, ctx); });
      if (multi) { pasos = pasos.filter(function (p) { return String(p.detallada).indexOf("{empaque}") < 0; }); }
      if (ctx.d === null && pasos.some(function (p) { return String(p.detallada).indexOf("{rango}") >= 0; })) { if (resp.diametro !== undefined && resp.diametro !== null) { ctx.d = diamVal(resp.diametro) || 0.5; } else if (ctx.pendientes.indexOf("diametro") < 0) { ctx.pendientes.push("diametro"); } }
      var rango = ctx.d !== null ? rangoDiam(ctx.d) : "1/2-5/8 · M12-M16", matN = ctx.mat === "inox" ? MATS[1] : MATS[0];
      var emp = respuestas.empaque || null;
      if (!multi && pasos.some(function (p) { return String(p.detallada).indexOf("{empaque}") >= 0; }) && !emp) { if (pendientes.indexOf("empaque") < 0) { pendientes.push("empaque"); } }
      function res(s) { return String(s).split("{rango}").join(rango).split("{mat}").join(matN).split("{empaque}").join(emp || "chico"); }
      var lista = pasos.map(function (p, i) { var mq = maquinasDe(p.madre); return { orden: i + 1, madre: p.madre, detallada: res(p.detallada), maquina: mq.preferida, opcionesMaquina: mq.opciones, condicion: p.condicion, nota: p.nota }; });
      ctx.pendientes.forEach(function (q) { if (pendientes.indexOf(q) < 0) { pendientes.push(q); } });
      partidas.push({ modelo: hit.modelo.toUpperCase(), familia: hit.familia, diametro: ctx.d !== null ? fmtDiam(ctx.d) : null, material: ctx.mat, pad: ctx.pad, cantidad: todas ? suma[hit.firma] : null, pendientes: ctx.pendientes, pasos: lista });
      planos = planos.concat(lista.map(function (p) { return Object.assign({ partida: k + 1, modelo: hit.modelo.toUpperCase() }, p); }));
    });
    // Varias partidas: un solo Empaquetar al final, para todo el pedido
    if (multi) {
      var re = D.rutas.filter(function (r) { return String(r.detallada).indexOf("{empaque}") >= 0; })[0];
      if (re) { var emp2 = respuestas.empaque || null; if (!emp2 && pendientes.indexOf("empaque") < 0) { pendientes.push("empaque"); }
        var mq = maquinasDe(re.madre); var pasoE = { partida: hits.length, modelo: partidas[partidas.length - 1].modelo, orden: partidas[partidas.length - 1].pasos.length + 1, madre: re.madre, detallada: String(re.detallada).split("{empaque}").join(emp2 || "chico"), maquina: mq.preferida, opcionesMaquina: mq.opciones, condicion: "", nota: "Un solo empaque para todo el pedido" };
        partidas[partidas.length - 1].pasos.push(pasoE); planos.push(pasoE); }
    }
    return { familias: partidas.map(function (p) { return p.familia; }).filter(function (x, i, a) { return a.indexOf(x) === i; }).join(" + "), partidas: partidas, pendientes: pendientes, empaque: respuestas.empaque || null, pasos: planos };
  }

  // Preguntas en el mismo orden y con el mismo texto que el pizarrón
  var PREGUNTAS = {
    tornillo: "¿Hay tornillo a la medida (comprado o en stock)?",
    pad: "¿Lleva pad?",
    diametro: "No pude leer el diámetro del tornillo. Escríbelo (ej. 1/2, 5/8, 1 1/4, M12). Vacío = 1/2",
    empaque: "¿Paquete chico, mediano o grande para TODO el pedido?",
    grande: "(ya no se pregunta: va por modelo y diámetro)",
    familia: "No reconozco el modelo. ¿Qué familia es?",
    modelo: "Indica el modelo exacto del pedido dentro de la familia seleccionada."
  };

  return { cargarDatos: cargarDatos, rutaDePedido: rutaDePedido, detectarModelos: detectarModelos, parseDiam: parseDiam, diamVal: diamVal, esInox: esInox, padDe: padDe, rangoDiam: rangoDiam, fmtDiam: fmtDiam, maquinasDe: maquinasDe, cumple: cumple, norm: norm, PREGUNTAS: PREGUNTAS, MATS: MATS };
}));
