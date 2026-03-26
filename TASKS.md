# Tareas - Bot Automatización Belcorp GA4

## Flujos de compra — Desktop (1280x800)

| # | Flujo | Estado | Notas |
|---|-------|--------|-------|
| 1 | Ésika – PLP agregar directo + PDP | ✅ Completo | `flujo_1_esika` |
| 2 | Categorías Fragancias – PLP + PDP | ✅ Completo | `flujo_2_categorias` |
| 3 | Carruseles Gana+ – directo + PDP | ✅ Completo | `flujo_3_carrusel_gana` |
| 4 | Pedido – Lo más vendido + Ofertas recomendadas | ✅ Completo | `flujo_4_pedido` — selección obligatoria + JS click |
| 5 | Buscador de checkout | ✅ Completo | `flujo_5_buscador_checkout` — CUV configurable + ofertas similares + agregar directo |
| 6 | Buscador (search PLP) | ✅ Completo | `flujo_6_search_plp` — busca término configurable, click "VER MÁS RESULTADOS" → PLP estándar |
| 7 | Mini buscador | ✅ Completo | `flujo_7_mini_buscador` — busca en modal, agrega directo + refresca → PDP via href |
| 8 | Liquidación PLP | ✅ Completo | `flujo_8_liquidacion` — navega desde home, PLP estándar con hover→"Ver detalle" |
| 9 | Festivales PLP | ✅ Completo | `flujo_9_festivales_plp` — navega desde home, PLP estándar |
| 10 | Festivales carrusel premios | ✅ Completo | `flujo_10_festivales_carrusel` — agregar premio + ir a PDP de otro premio via `div.redireccionarFicha` |
| 11 | Carrusel de home | ✅ Completo | `flujo_11_carrusel_home` — swiper "Las mejores ofertas", agregar directo + hover→"Ver detalle"→PDP |

## Flujos de compra — Mobile (390x844)

| # | Flujo | Estado | Notas |
|---|-------|--------|-------|
| M1 | Ésika – PLP agregar directo + PDP | ✅ Completo | Login fallback + JS click Gana+ + image click PDP |
| M2 | Categorías Fragancias – PLP + PDP | ✅ Completo | Mismo mecanismo que M1 |
| M3 | Carruseles Gana+ – directo + PDP | ⚠️ Inestable | Browser crash (TargetClosedError) en `ir_a_gana` — recovery automático agregado |
| M4 | Pedido – Lo más vendido + Ofertas recomendadas | ✅ Completo | Selección obligatoria funciona en mobile |
| M5 | Buscador de checkout | ✅ Completo | JS click en `btnAgregarDePedido` oculto + `txtCuvConsultaMobile` fallback |
| M6 | Buscador (search PLP) | ✅ Completo | Enter como fallback cuando "VER MÁS RESULTADOS" no visible + `abrir_buscador_header` |
| M7 | Mini buscador | ✅ Completo | Mobile redirige a `/buscador` → `a#btnAgregalo` + "VER MÁS RESULTADOS" → PLP |
| M8 | Liquidación PLP | ✅ Completo | PLP estándar, image click PDP (sin hover) |
| M9 | Festivales PLP | ✅ Completo | PLP estándar, image click PDP |
| M10 | Festivales carrusel premios | ✅ Completo | Playwright locator + `div.redireccionarFicha` |
| M11 | Carrusel de home | ✅ Completo | Swiper + hover→"Ver detalle" con fallback image click |

### Notas mobile
- Flag `--mobile` cambia viewport a 390x844 (emula iPhone 13)
- `abrir_buscador_header()` — helper que abre búsqueda en desktop y mobile (ícono search fallback)
- `plp_ir_a_pdp` — fallback image click para mobile (no hay hover)
- `ir_a_gana` — JS click para bypass drawer-mask + fallback URL directa
- `flujo_5` — JS click en `btnAgregarDePedido` oculto en mobile
- `flujo_7` — mobile redirige a `/buscador` (PLP completa) en vez de modal overlay
- Recovery automático: si el browser crashea, recrea contexto y reloguea
- Page mapper + screenshots para debug autónomo

## Próximos pasos

| # | Tarea | Prioridad | Descripción |
|---|-------|-----------|-------------|
| P1 | `config.json` — URL base + inputs configurables | Alta | Sacar URL hardcoded (`somosbelcorp.com` x14), CUVs, términos de búsqueda y credenciales a un archivo `config.json` fácil de editar. Actualmente usa env vars (`BELCORP_CUV`, `BELCORP_SEARCH`, `BELCORP_MINI_SEARCH`) |
| P2 | Estabilizar M3 mobile | Alta | Browser crash (TargetClosedError) al navegar a Gana+ por tercera vez consecutiva — revisar navegación agresiva en `ir_a_gana` |
| P3 | Skip productos ya agregados (unificar) | Alta | Existe lógica parcial (`caja_producto_agregado`, `div.agregado`, `btn_elegido`, `input-number`) pero no es consistente en todos los flujos. Unificar en helper reutilizable |
| P4 | Interceptar datos backend | Media | Capturar requests/responses POST a APIs de pedido/carrito (`page.on("response")`) para tener evidencia de lo que se envía al servidor |
| P5 | Mejorar output analytics por flujo | Media | Ya tiene campo `flow` + sufijo `_mobile`, pero mejorar formato: separar por flujo en archivos individuales, agregar resumen con conteo por evento |
| P6 | Pre-mapeo de productos disponibles | Media | Escanear catálogo antes de ejecutar flujos para saber qué productos están disponibles y evitar bloqueos por falta de stock o productos ya agregados |

## Herramientas

| Herramienta | Estado | Descripción |
|-------------|--------|-------------|
| `capturar_selectores.py` | ✅ Completo | Captura interactiva de selectores CSS en modo desktop |
| `bot.py` | ✅ Funcional | Motor principal, 11 flujos desktop + 10/11 mobile completos |
| `debug_screenshot` | ✅ Completo | Screenshots en todos los bloques except |
| `debug_completo` | ✅ Completo | Screenshot + page mapper automático en except blocks |
| `tools/page_mapper.py` | ✅ Completo | Mapea accionables, obstáculos, formularios — se activa en bloqueos |

## Fixes aplicados (historial)

- **2026-03-12**: `pdp_agregar` — JS click en `btn-aplicar-seleccion.active` para evitar reset por `add_locator_handler`
- **2026-03-12**: `pdp_agregar` — scroll + JS click en botón principal agregar (`a#btnAgregalo`)
- **2026-03-12**: `ofertas_ir_a_pdp` + `ofertas_agregar_directo` — separación de funciones para carrusel vertical
- **2026-03-12**: `capturar_selectores.py` — modo desktop (1280x800) + login automático
- **2026-03-12**: `debug_screenshot` agregado a todos los except blocks restantes
- **2026-03-19**: `flujo_5_buscador_checkout` — búsqueda por CUV, ofertas similares (skip agregados), agregar directo con `input#btnAgregarDePedido`
- **2026-03-19**: `flujo_6_search_plp` — buscador header con `input[placeholder='Buscar ofertas']`, type() con delay, `a.search-modal-more-results`
- **2026-03-19**: `flujo_7_mini_buscador` — busca "vibranza", agrega desde modal `div.product-searched-container`, refresca y navega a PDP via `a.image-button-detail-link` href
- **2026-03-19**: `flujo_8_liquidacion` — navega via `a[aria-label="Liquidaciones"]`, PLP estándar
- **2026-03-19**: `flujo_9_festivales_plp` — navega via `a[aria-label="FESTIVAL TOTAL PEDIDO"]`, PLP estándar
- **2026-03-19**: `plp_ir_a_pdp` mejorado — fallback con hover→"Ver detalle" para PLPs donde todos los botones dicen "Agregar", skip productos ya agregados empezando desde idx+1
- **2026-03-19**: `ejecutar_flujo_plp` — agrega refresh entre agregar directo e ir a PDP para DOM actualizado
- **2026-03-25**: `flujo_10_festivales_carrusel` — resuelto: botón se renderiza dinámicamente, Playwright locator `span:has-text("Agregar")` funciona donde `querySelector` no. Agregado ir a PDP via `div.redireccionarFicha`
- **2026-03-25**: `tools/page_mapper.py` — herramienta de diagnóstico automático, integrada en `debug_completo()` para except blocks
- **2026-03-25**: `debug_completo` — nueva función que combina screenshot + page mapper para diagnóstico completo en bloqueos
- **2026-03-26**: Mobile M1-M11 — adaptación completa: `abrir_buscador_header()`, JS click `btnAgregarDePedido`, Enter fallback search, `/buscador` PLP mobile, image click PDP, recovery automático browser crash
