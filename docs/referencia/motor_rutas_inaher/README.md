# INAHER · Motor de rutas de producción (JavaScript puro)

Paquete para el equipo de sistemas. Reproduce, sin Google Sheets, lo que hace el botón
**INAHER › Cargar ruta en HOY** del pizarrón *Designación Diaria V3*: a partir del texto
de un pedido devuelve los pasos de producción (operación madre › operación detallada),
la máquina preferida y las opciones, y qué preguntas hay que hacerle al usuario.

Generado el 2026-11-04 desde `Codigo_Pizarron_INAHER_v5.gs`. Validado contra los mismos
500 pedidos de prueba del pizarrón: **500/500 rutas idénticas** (`node validar_motor.js`).

## Archivos

| Archivo | Qué es |
|---|---|
| `motor_rutas_inaher.js` | La lógica. Sin dependencias. Node (`require`) o navegador (`window.MotorRutasINAHER`). |
| `datos_rutas_inaher.json` | Los datos: 15 familias (modelos), 219 pasos de ruta con su condición, operaciones, madres con tipos de máquina, máquinas. Se regenera desde el pizarrón cuando cambien las rutas. |
| `validar_motor.js` | Prueba contra el motor real (solo sirve dentro del proyecto del pizarrón). |
| `ejemplo.js` | Ejemplo de uso. |

## Uso

```js
const motor = require('./motor_rutas_inaher.js');

// 1) Primera llamada: el motor dice qué falta preguntar
let r = motor.rutaDePedido("50 MT-2 de 3/8 x 2 galv con pad", {});
r.pendientes   // → ["empaque", "tornillo"]

// 2) Se pregunta al usuario (textos en motor.PREGUNTAS) y se vuelve a llamar
r = motor.rutaDePedido("50 MT-2 de 3/8 x 2 galv con pad", { tornillo: false, empaque: "chico" });
r.pendientes   // → []
r.pasos        // → lista plana en el orden de HOY
```

Cada paso trae:

```js
{ partida: 1, modelo: "MT-2", orden: 1,
  madre: "Cortar en sierra cinta",
  detallada: "Cortar varilla 5/16-3/8 · M8-M10 · fierro-galv",
  maquina: "Sierra cinta universal",                       // preferida (vacía = el usuario debe escoger)
  opcionesMaquina: ["Sierra cinta universal","Sierra cinta vertical"],
  condicion: "tornillo=no", nota: "Solo si no hay tornillo a la medida" }
```

Y `r.partidas[i]` trae modelo, familia, diámetro, material (`fierro`/`inox`), pad y cantidad
(cuando el pedido trae varias partidas con cantidad: "4 rebo y 6 scn").

### Respuestas

```js
{ empaque: "chico" | "mediano" | "grande",          // una por pedido (Empaquetar se agrega una sola vez)
  tornillo: true/false, pad: true/false, diametro: "1/2",   // aplican a todas las partidas, o
  partidas: [ { tornillo: true, pad: false, diametro: "M12" }, { tornillo: false } ] }  // por partida
```

## Cómo decide la ruta (resumen de la especificación)

1. **Detecta los modelos** en el texto con la lista de modelos de cada familia
   (`familias[].modelos`; un token terminado en `-` es prefijo: `ETH-` reconoce ETH-1, ETH-4…).
   Si hay varios modelos, cada uno es una partida y el texto se parte en tramos.
2. **Lee del tramo** el diámetro (`3/8`, `M12`, `1 1/4`, `1"`), el material (inox si dice inox /
   acero 304 / 316, si no fierro-galv) y el pad (`con pad` / `sin pad`; si no dice, se pregunta).
3. **Filtra los pasos** de la familia (`rutas[]`, en orden) evaluando la columna `condicion`:

   | Condición | Significado |
   |---|---|
   | `tornillo=si` / `tornillo=no` | ¿Hay tornillo a la medida (comprado o en stock)? → **pregunta** |
   | `pad` | Lleva pad (del texto, o **pregunta**) |
   | `d>=5/8`, `d<=3/4`, `d>1`, `d<1/2`, `d=1/2` | Diámetro del tornillo en pulgadas (M8→5/16, M10→3/8, M12→1/2, M16→5/8, M20→3/4, M24→1"…). Si no se pudo leer y la ruta lo necesita → **pregunta** (vacío = 1/2) |
   | `mat=fierro` / `mat=inox` | Material |
   | `modelo=MT-2,MTA` / `modelo!=X` | Modelo exacto; `MTA-` = prefijo |
   | `stock=si` | Siempre verdadero (la base existe; el lote CNC se programa a mano) |
   | varias con `;` | Todas deben cumplirse |

4. **Sustituye** en el nombre de la operación: `{rango}` → rango del diámetro
   (`5/16-3/8 · M8-M10`, `1/2-5/8 · M12-M16`, `3/4-1" · M20-M24`, `1 1/4-1 1/2 · M30-M36`),
   `{mat}` → `fierro-galv` / `inox-304`, `{empaque}` → chico / mediano / grande.
5. **Empaquetar** va una sola vez por pedido, al final de la última partida.
6. **Máquina**: cada madre tiene en `madres[].tipos` sus tipos de máquina separados por ` / ` en
   orden de preferencia; el primero puede ser una máquina concreta (`Sierra cinta universal / Sierra cinta`).
   Si el primer dato tiene una sola máquina, se asigna sola; si hay varias opciones queda vacía
   para que el usuario escoja (en el pizarrón se pinta en rojo).

## Tiempos

Los tiempos estándar (minutos por pieza; Empaquetar por pedido) salen del estudio de tiempos de
Frida y Axel y viven en la pestaña Config del pizarrón (columnas M:O). No van en este paquete;
si los necesitan, se exportan aparte por operación detallada (madre › detallada).

## Mantenimiento

Cuando cambien las rutas en el pizarrón hay que regenerar `datos_rutas_inaher.json`
(lo hace Claude desde el proyecto; no se edita a mano). La lógica de `motor_rutas_inaher.js`
solo cambia si cambia el lenguaje de condiciones.
