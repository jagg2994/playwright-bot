# Tareas - Bot Automatización Belcorp GA4

## Flujos de compra

| # | Flujo | Estado | Notas |
|---|-------|--------|-------|
| 1 | Ésika – PLP agregar directo + PDP | ✅ Completo | `flujo_1_esika` |
| 2 | Categorías Fragancias – PLP + PDP | ✅ Completo | `flujo_2_categorias` |
| 3 | Carruseles Gana+ – directo + PDP | ✅ Completo | `flujo_3_carrusel_gana` |
| 4 | Pedido – Lo más vendido + Ofertas recomendadas | ✅ Completo | `flujo_4_pedido` — selección obligatoria + JS click |
| 5 | Buscador de checkout | ✅ Completo | `flujo_5_buscador_checkout` — CUV configurable + ofertas similares + agregar directo |
| 6 | Buscador (search PLP) | ⬚ Pendiente | |
| 7 | Mini buscador | ⬚ Pendiente | |
| 8 | Liquidación PLP | ⬚ Pendiente | |
| 9 | Festivales PLP | ⬚ Pendiente | |
| 10 | Carrusel de home | ⬚ Pendiente | |

## Herramientas

| Herramienta | Estado | Descripción |
|-------------|--------|-------------|
| `capturar_selectores.py` | ✅ Completo | Captura interactiva de selectores CSS en modo desktop |
| `bot.py` | ✅ Funcional | Motor principal, 5 flujos implementados |
| `debug_screenshot` | ✅ Completo | Screenshots en todos los bloques except |

## Fixes aplicados (historial)

- **2026-03-12**: `pdp_agregar` — JS click en `btn-aplicar-seleccion.active` para evitar reset por `add_locator_handler`
- **2026-03-12**: `pdp_agregar` — scroll + JS click en botón principal agregar (`a#btnAgregalo`)
- **2026-03-12**: `ofertas_ir_a_pdp` + `ofertas_agregar_directo` — separación de funciones para carrusel vertical
- **2026-03-12**: `capturar_selectores.py` — modo desktop (1280x800) + login automático
- **2026-03-12**: `debug_screenshot` agregado a todos los except blocks restantes
- **2026-03-19**: `flujo_5_buscador_checkout` — búsqueda por CUV, ofertas similares (skip agregados), agregar directo con `input#btnAgregarDePedido`
