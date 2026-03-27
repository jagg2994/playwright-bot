# Tareas - Bot Automatización Belcorp GA4

## Contexto general

- El bot se ejecuta contra entornos de prueba (ej: `sb2revamp2.somosbelcorp.com`) que cambian frecuentemente
- Los CUVs (códigos de producto) cambian cada campaña — nada que dependa de un CUV fijo será válido a futuro
- Hay al menos 6 tipos diferentes de productos en PDP, cada uno con distinto flujo para agregar al carrito
- Los selectores CSS pueden variar entre entornos; el bot usa fallbacks y detección dinámica para adaptarse

## Flujos de compra — Desktop (1280x800)

| # | Flujo | Estado | Función |
|---|-------|--------|---------|
| 1 | Ésika – PLP agregar directo + PDP | ✅ | `flujo_1_esika` |
| 2 | Categorías Fragancias – PLP + PDP | ✅ | `flujo_2_categorias` |
| 3 | Carruseles Gana+ – directo + PDP | ✅ | `flujo_3_carrusel_gana` |
| 4 | Pedido – Lo más vendido + Ofertas recomendadas | ✅ | `flujo_4_pedido` |
| 5 | Buscador de checkout | ✅ | `flujo_5_buscador_checkout` |
| 6 | Buscador (search PLP) | ✅ | `flujo_6_search_plp` |
| 7 | Mini buscador | ✅ | `flujo_7_mini_buscador` |
| 8 | Liquidación PLP | ✅ | `flujo_8_liquidacion` |
| 9 | Festivales PLP | ✅ | `flujo_9_festivales_plp` |
| 10 | Festivales carrusel premios | ✅ | `flujo_10_festivales_carrusel` |
| 11 | Carrusel de home | ✅ | `flujo_11_carrusel_home` |

## Flujos de compra — Mobile (390x844)

| # | Flujo | Estado | Notas |
|---|-------|--------|-------|
| M1 | Ésika – PLP + PDP | ✅ | JS click Gana+ + image click PDP |
| M2 | Categorías Fragancias | ✅ | Mismo mecanismo que M1 |
| M3 | Carruseles Gana+ | ⚠️ Inestable | TargetClosedError — recovery automático |
| M4 | Pedido | ✅ | Selección obligatoria funciona |
| M5 | Buscador checkout | ✅ | JS click `btnAgregarDePedido` oculto |
| M6 | Search PLP | ✅ | Enter fallback + `abrir_buscador_header` |
| M7 | Mini buscador | ✅ | Mobile redirige a `/buscador` |
| M8 | Liquidación PLP | ✅ | Image click PDP (sin hover) |
| M9 | Festivales PLP | ✅ | Image click PDP |
| M10 | Festivales carrusel | ✅ | `div.redireccionarFicha` |
| M11 | Carrusel home | ✅ | Fallback image click |

## Pendientes

| # | Tarea | Prioridad | Estado | Descripción |
|---|-------|-----------|--------|-------------|
| P7 | Explorador de PDPs (`explorar_pdps.py`) | Alta | 🔧 En progreso | Recorre secciones, visita PDPs, captura fingerprints (botones, selecciones, cantidades, restricciones) y clasifica tipos. Sirve para descubrir dinámicamente qué tipos de producto existen en cada campaña. **Problemas detectados**: sesión expira durante navegación, URLs de PDP son `/Detalles/Evento/...` (no `/ficha/`), `go_back()` no funciona bien con filtros de PLP. Fixes parciales aplicados, falta terminar y validar. |
| P8 | Actualizar `_detectar_tipo_pdp()` con tipos reales | Alta | Pendiente | Con los resultados del explorador, actualizar la clasificación en `bot.py` para cubrir los ~6 tipos: simple, selección de tono, arma tu oferta, cantidad mínima, cantidad variable, agotado, ya agregado. Actualmente solo detecta: simple, seleccion_multi, ya_agregado, desconocido. |
| P9 | Actualizar `pdp_agregar()` para todos los tipos | Alta | Pendiente | Que el bot sepa agregar productos de cada tipo detectado (ej: cantidad mínima → incrementar qty antes de agregar, arma tu oferta → seleccionar N opciones). |
| P4 | Interceptar datos backend | Media | Pendiente | Capturar requests/responses POST a APIs de pedido/carrito (`page.on("response")`) para evidencia de lo que se envía al servidor. |
| P5 | Mejorar output analytics por flujo | Media | Pendiente | Separar eventos por flujo en archivos individuales + resumen con conteo por evento. |

## Completados

| # | Tarea | Descripción |
|---|-------|-------------|
| P1 | `config.json` | URL base, CUVs, search terms, país, device — todo configurable |
| P2 | Estabilizar M3 | `ir_a_gana` usa `page.goto(href)` |
| P3 | Skip productos agregados | `producto_ya_agregado()` unifica 5 patrones |
| P3b | Selectores multi-entorno | Fallbacks de placeholders, JS href, `.first` en locators |
| P3c | Re-login automático | `verificar_sesion()` antes de cada flujo |
| P3d | Detección tipo PDP | `_detectar_tipo_pdp()` — clasificación inicial |
| P3e | Login con país | `BELCORP_COUNTRY` en `.env` → `#ddlPais` |
| P6 | Pre-mapeo productos | Integrado en explorador (P7) |

## Herramientas

| Herramienta | Estado | Descripción |
|-------------|--------|-------------|
| `bot.py` | ✅ Funcional | 11 flujos desktop + 11 mobile |
| `tools/explorar_pdps.py` | 🔧 En progreso | Explorador de PDPs — cataloga tipos de producto |
| `tools/page_mapper.py` | ✅ | Mapea accionables, obstáculos, formularios |
| `capturar_selectores.py` | ✅ | Captura interactiva de selectores CSS |
