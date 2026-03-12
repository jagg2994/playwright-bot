# Belcorp Analytics Bot

Playwright bot que automatiza flujos de compra en `somosbelcorp.com` y captura los eventos GA4 disparados por cada acción, generando un archivo JSON como evidencia.

---

## Requisitos

- Python 3.10+
- [Playwright](https://playwright.dev/python/) con Chromium instalado
- Dependencias Python:

```bash
pip install playwright python-dotenv pytz
playwright install chromium
```

---

## Configuración

Crea un archivo `.env` en la raíz del proyecto:

```env
BELCORP_USER=tu_usuario
BELCORP_PASS=tu_contraseña
```

---

## Estructura del proyecto

```
playwright-bot/
├── bot.py                  # Script principal con todos los flujos automatizados
├── diagnostico.py          # Herramienta: captura HTML de productos para analizar selectores
├── debug_pdp.py            # Herramienta: diagnóstico paso a paso del flujo PDP
├── debug/                  # Screenshots automáticos en caso de error (generado en runtime)
├── eventos_analytics.json  # Output: eventos GA4 capturados por el bot
├── .env                    # Credenciales (no commitear)
└── README.md
```

---

## Uso

### Ejecutar el bot principal

```bash
python bot.py
```

Abre el navegador (modo visible) y ejecuta todos los flujos en secuencia. Al finalizar guarda `eventos_analytics.json`.

### Herramientas de diagnóstico

```bash
# Capturar HTML de productos para inspeccionar selectores
python diagnostico.py
# → genera diagnostico_productos.html (abrir en navegador)

# Diagnosticar flujo PDP paso a paso con screenshots
python debug_pdp.py
# → pausa para que navegues manualmente a la PDP, luego ejecuta diagnóstico
# → guarda screenshots en debug_screenshots/
```

---

## Flujos automatizados

### Flujo 1 — Ésika (Marcas)
1. Login → Gana+ → Ésika
2. Agregar un producto directo desde PLP (botón `Agregar`)
3. Ir a PDP de otro producto (botón `Ver detalle`) → agregar desde PDP

### Flujo 2 — Categorías (Fragancias)
1. Gana+ → Fragancias
2. Agregar un producto directo desde PLP (botón `Agregar`)
3. Ir a PDP de otro producto → agregar desde PDP

### Flujo 3 — Carruseles Gana+
1. Gana+ (home)
2. Recorrer carruseles slide a slide → agregar primer producto con botón `Agregar`
3. Desde el siguiente slide → ir a PDP → agregar desde PDP

### Flujo 4 — Carruseles Pedido
1. Ir a pedido (checkout)
2. **Lo más vendido (venta_2):** agregar directo desde carrusel → ir a PDP por link de card → agregar desde PDP → volver
3. **Ofertas recomendadas para ti (venta_1):** buscar slide con botón `Agregar directo` → volver al slide 0 → navegar a PDP → agregar desde PDP → volver

---

## Regla clave de interacción (PLP / carruseles)

| Texto del botón `a#btnAgregalo` | Comportamiento |
|----------------------------------|----------------|
| `"Agregar"` | Agrega directo al pedido, se queda en la misma página |
| Cualquier otro texto (`"Ver detalle"`, etc.) | Navega a la PDP del producto |

Esta distinción se detecta en runtime leyendo el `.inner_text()` del selector `a#btnAgregalo`.

---

## Flujo PDP con selección obligatoria

Cuando el botón de la PDP dice **"Elegir opción"** o **"Elegir oferta"**, es necesario "armar la oferta" antes de poder agregar al pedido. Hay dos variantes:

### Variante A — Selección de atributo (color/tono)
- 1 botón `button.tono_select_opt.nobg[btn-show-types-tones-modal]`
- Abre modal con opciones de color/tono (`button[btn-eligelo]`)
- Se selecciona 1 opción → el título del modal cambia a **"¡Listo!"**
- Se confirma con `button#btn-aplicar-seleccion`

### Variante B — Arma tu oferta (N productos)
- 1 o N botones `button.tono_select_opt.nobg[btn-show-types-tones-modal]`
- Cada botón abre modal con productos disponibles (`button[btn-eligelo]`)
- Se seleccionan productos uno a uno hasta que el título diga **"¡Listo!"**
- Se confirma con `button#btn-aplicar-seleccion`
- Al completar todos los slots → el botón de la PDP cambia a **"Agregar al pedido"**

### Lógica implementada en `pdp_agregar`
```
Por cada botón de selección obligatoria:
  1. Click → abre modal
  2. Por cada opción disponible (button[btn-eligelo]):
       - Click en la opción
       - Esperar 600ms
       - Si "¡Listo!" es visible en el modal → break (requisito cumplido)
  3. Click en button#btn-aplicar-seleccion (siempre visible cuando hay selección)

Botón principal:
  - Intenta a#btnAgregalo.btn_validar_alertas (selector estándar)
  - Fallback: button/a con texto "Agregar al pedido" o "Agregar"
```

---

## Selectores clave

### PLP / Carruseles estándar
| Elemento | Selector |
|----------|----------|
| Botón universal de producto | `a#btnAgregalo` |
| Botón PDP (único en PDP) | `a#btnAgregalo.btn_validar_alertas` |
| Botón deshabilitado en PDP | `a#btnAgregalo.btn_deshabilitado_ficha` |
| Producto ya agregado | `div.caja_producto_agregado` (chequear `is_visible()`) |
| Carrusel contenedor | `div.contenedor_carrusel.slick-slider[data-seccion-productos]` |
| Slide activo del carrusel | `article.slick-current` |
| Flecha siguiente del carrusel | `.nextArrow.slick-arrow` |

### Selección obligatoria (PDP)
| Elemento | Selector |
|----------|----------|
| Botones de selección (slot) | `button.tono_select_opt.nobg[btn-show-types-tones-modal]` |
| Opciones dentro del modal | `button[btn-eligelo]` |
| Botón confirmar selección | `button#btn-aplicar-seleccion` |
| Señal de requisito cumplido | texto `¡Listo!` visible en el modal |

### Carrusel vertical "Ofertas recomendadas para ti" (venta_1)
| Elemento | Selector |
|----------|----------|
| Contenedor | `#divListadoEstrategia` o `.content_carrusel_ofertas` |
| Botón agregar directo | `a.boton_Agregalo_home.boton_Agregalo_home_pase_pedido` |
| Botón elegir opción | `[data-item-tag="agregar"] .ctn-elige-opcion` |
| Flecha siguiente | `button.next-flecha-dorada, button.slick-next` |

### Alertas y popups
| Elemento | Selector |
|----------|----------|
| Alerta general ("Entendido") | `#alertDialogMensajesGenerales` |
| Botón cerrar alerta | `fd-button.btn__close` dentro de la alerta |

---

## Output

El archivo `eventos_analytics.json` contiene un array de eventos GA4 con la estructura:

```json
[
  {
    "event": "ga4.trackEvent",
    "eventName": "add_to_cart",
    "eventParams": {
      "flow": "esika_plp_pdp_flow",
      "currency": "COP",
      "timestamp": 1739000000,
      "timestamp_readable": "2025-02-08 10:30:00",
      "items": [
        {
          "item_id": "12345",
          "item_name": "Nombre del producto",
          "item_brand": "Ésika",
          "price": "89900",
          "quantity": "1"
        }
      ]
    }
  }
]
```

### Eventos capturados

| Evento | Descripción |
|--------|-------------|
| `page_view` | Carga de página |
| `view_item_list` | Visualización de PLP o carrusel |
| `select_item` | Click en un producto |
| `view_item` | Carga de PDP |
| `add_to_cart` | Producto agregado al pedido |
| `view_popup` | Apertura de modal de selección |
| `select_content` | Selección de opción en modal |

---

## Notas técnicas

- El bot usa la **API síncrona** de Playwright (`sync_playwright`)
- Los eventos GA4 se interceptan escuchando requests POST a `*/collect*`
- Screenshots de debug se guardan automáticamente en `debug/` cuando ocurre un error (nombre + timestamp)
- Las PDPs con selección obligatoria detectan el requisito cumplido leyendo el texto **"¡Listo!"** en el título del modal (aparece cuando se alcanza la cantidad mínima requerida)
- En las PDPs hay múltiples `a#btnAgregalo` (producto principal + sección de recomendaciones). Se usa `.btn_validar_alertas` para apuntar únicamente al botón del producto
- `#alertDialogMensajesGenerales` puede aparecer durante el flujo de selección; se maneja con `_cerrar_alerta_general()` llamado explícitamente (no con handler automático, para no interferir con los modales de selección)
