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
| 11 | Carrusel de home | ⬚ Pendiente | |

## Flujos de compra — Mobile (390x844)

| # | Flujo | Estado | Notas |
|---|-------|--------|-------|
| M1 | Ésika – PLP agregar directo + PDP | ⬚ Pendiente | Misma web responsive, posibles selectores mobile (`txtCuvConsultaMobile`) |
| M2 | Categorías Fragancias – PLP + PDP | ⬚ Pendiente | |
| M3 | Carruseles Gana+ – directo + PDP | ⬚ Pendiente | |
| M4 | Pedido – Lo más vendido + Ofertas recomendadas | ⬚ Pendiente | Verificar selección obligatoria en mobile |
| M5 | Buscador de checkout | ⬚ Pendiente | Input mobile: `input.txtCuvConsultaMobile` |
| M6 | Buscador (search PLP) | ⬚ Pendiente | |
| M7 | Mini buscador | ⬚ Pendiente | |
| M8 | Liquidación PLP | ⬚ Pendiente | Hover→"Ver detalle" puede no funcionar en mobile (no hay hover) |
| M9 | Festivales PLP | ⬚ Pendiente | |
| M10 | Festivales carrusel premios | ⬚ Pendiente | |
| M11 | Carrusel de home | ⬚ Pendiente | |

### Notas mobile
- Flag `--mobile` cambia viewport a 390x844
- Misma web responsive, mismos flujos
- Selectores que pueden cambiar: `txtCuvConsultaMobile` vs `txtCuvConsultaDesktop`, menú hamburguesa
- Hover no existe en mobile — `plp_ir_a_pdp` necesita alternativa (click directo en card/imagen)
- Page mapper + screenshots para debug autónomo

## Herramientas

| Herramienta | Estado | Descripción |
|-------------|--------|-------------|
| `capturar_selectores.py` | ✅ Completo | Captura interactiva de selectores CSS en modo desktop |
| `bot.py` | ✅ Funcional | Motor principal, 10 flujos desktop completos |
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
