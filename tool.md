# Page Mapper Tool — Herramienta de Diagnóstico para Navegación

## ¿Qué es esto?

Un script que genera un **mapa accionable** de cualquier página web. Se usa como fallback cuando el bot no puede encontrar o interactuar con un elemento.

## ¿Cuándo usarla?

Ejecuta `page-mapper.js` cuando:

1. **No encuentras un selector** — el elemento no aparece con el selector esperado
2. **Un click no funciona** — el botón existe pero no responde (overlay, modal, iframe)
3. **La página cambió** — después de una acción el DOM se actualizó y los selectores previos ya no sirven
4. **Timeout esperando un elemento** — llevas más de 5 segundos sin encontrarlo

## Flujo de uso

```
Intento normal → FALLA → Ejecutar page-mapper.js → Leer mapa → Reintentar con selectores del mapa
```

### Comando

```bash
node tools/page-mapper.js [url_o_página_actual]
```

Si ya tienes una instancia de Playwright corriendo, úsalo como función:

```javascript
const { mapPage } = require('./tools/page-mapper');
const mapa = await mapPage(page); // page = instancia de Playwright
```

## ¿Qué genera?

Un JSON con 4 secciones:

### 1. `accionables` — Elementos con los que se puede interactuar

```json
{
  "accionables": [
    {
      "tipo": "button",
      "texto": "Agregar al carrito",
      "selector_texto": "button:has-text('Agregar al carrito')",
      "selector_role": "button[name='Agregar al carrito']",
      "selector_testid": "[data-testid='add-to-cart']",
      "visible": true,
      "habilitado": true,
      "dentro_de_iframe": false
    }
  ]
}
```

### 2. `obstaculos` — Cosas que pueden estar bloqueando la interacción

```json
{
  "obstaculos": [
    {
      "tipo": "modal",
      "selector": ".modal-overlay",
      "visible": true,
      "accion_sugerida": "Cerrar modal antes de continuar — buscar botón de cierre dentro del modal"
    },
    {
      "tipo": "cookie-banner",
      "selector": "#cookie-consent",
      "visible": true,
      "accion_sugerida": "Aceptar cookies para desbloquear interacción"
    }
  ]
}
```

### 3. `formularios` — Estructura de forms en la página

```json
{
  "formularios": [
    {
      "id": "checkout-form",
      "campos": [
        {"nombre": "email", "tipo": "email", "selector": "#email", "requerido": true},
        {"nombre": "password", "tipo": "password", "selector": "#password", "requerido": true}
      ],
      "boton_submit": "button[type='submit']:has-text('Continuar')"
    }
  ]
}
```

### 4. `navegacion` — Links y rutas disponibles

```json
{
  "navegacion": [
    {"texto": "Mi cuenta", "href": "/account", "selector": "a:has-text('Mi cuenta')"},
    {"texto": "Carrito", "href": "/cart", "selector": "[data-testid='cart-link']"}
  ]
}
```

## Reglas para Claude Code

1. **NO leas HTML crudo cuando estés atascado.** Ejecuta el mapper primero.
2. **Prioridad de selectores:** usa `selector_testid` > `selector_role` > `selector_texto` (en ese orden de robustez).
3. **Si hay obstáculos:** resuélvelos ANTES de reintentar la acción original.
4. **Si el elemento no aparece en el mapa:** probablemente no está renderizado aún. Espera a que la página termine de cargar o busca si requiere scroll/interacción previa.
5. **Después de cada navegación o acción que cambie la página**, considera re-ejecutar el mapper si el siguiente paso falla.

## Ubicación esperada

```
proyecto/
├── tools/
│   └── page-mapper.js    ← El script (debe ser creado)
├── TOOL.md                ← Este archivo
├── CLAUDE.md              ← Contexto principal del proyecto
└── TASKS.md               ← Tareas activas
```

## Instrucción para Claude Code: Crear el script

Cuando necesites crear `tools/page-mapper.js`, debe:

1. Recibir una instancia de `page` de Playwright
2. Extraer el **accessibility tree** con `page.accessibility.snapshot()`
3. Extraer elementos interactivos con selectores múltiples (role, text, testid)
4. Detectar obstáculos comunes (modals, overlays, banners, iframes)
5. Mapear formularios con sus campos y validaciones
6. Retornar el JSON estructurado descrito arriba
7. Opcionalmente guardar el mapa en `tools/output/page-map-{timestamp}.json`

### Detección de obstáculos — lógica clave

```javascript
// Pseudocódigo para detectar qué bloquea la interacción
async function detectarObstaculos(page) {
  const obstaculos = [];

  // Modals/overlays visibles
  const modals = await page.$$eval(
    '[class*="modal"], [class*="overlay"], [class*="popup"], [role="dialog"]',
    els => els.filter(el => el.offsetParent !== null).map(el => ({
      tipo: 'modal',
      selector: el.getAttribute('id') ? `#${el.id}` : `.${el.className.split(' ')[0]}`,
      visible: true
    }))
  );

  // Cookie banners
  const cookies = await page.$$eval(
    '[class*="cookie"], [class*="consent"], [id*="cookie"]',
    els => els.filter(el => el.offsetParent !== null).map(el => ({
      tipo: 'cookie-banner',
      selector: el.getAttribute('id') ? `#${el.id}` : `.${el.className.split(' ')[0]}`,
      visible: true
    }))
  );

  // Iframes que pueden contener contenido
  const iframes = await page.$$eval('iframe', els => els.map(el => ({
    tipo: 'iframe',
    src: el.src,
    selector: el.getAttribute('id') ? `#${el.id}` : 'iframe'
  })));

  return [...modals, ...cookies, ...iframes];
}
```

## Ejemplo de uso en un flujo real

```javascript
// En tu test/bot de Playwright:
const { mapPage } = require('./tools/page-mapper');

// Intento normal
try {
  await page.click('button:has-text("Comprar")');
} catch (error) {
  // FALLBACK: ejecutar mapper
  console.log('⚠️ Elemento no encontrado. Ejecutando page-mapper...');
  const mapa = await mapPage(page);

  // Buscar obstáculos
  if (mapa.obstaculos.length > 0) {
    console.log('🚧 Obstáculos detectados:', mapa.obstaculos);
    // Resolver obstáculos primero
    for (const obs of mapa.obstaculos) {
      if (obs.tipo === 'modal' || obs.tipo === 'cookie-banner') {
        const cerrar = await page.$(`${obs.selector} button, ${obs.selector} [class*="close"]`);
        if (cerrar) await cerrar.click();
      }
    }
  }

  // Buscar el botón en los accionables del mapa
  const boton = mapa.accionables.find(a => a.texto.includes('Comprar'));
  if (boton) {
    await page.click(boton.selector_testid || boton.selector_role || boton.selector_texto);
  }
}
```