# Tareas - Bot Automatización Belcorp GA4

## Contexto general

- El bot se ejecuta contra entornos de prueba (ej: `sb2revamp2.somosbelcorp.com`) que cambian frecuentemente
- Los CUVs (códigos de producto) cambian cada campaña — nada que dependa de un CUV fijo será válido a futuro
- Hay al menos 6 tipos diferentes de productos en PDP, cada uno con distinto flujo para agregar al carrito
- Los selectores CSS pueden variar entre entornos; el bot usa fallbacks y detección dinámica (`map_pdp`)
- Distinguir bloqueante de **bot** (selector roto, lógica errónea) de bloqueante de **ambiente** (stock, sección inexistente)

---

## Resultado de ejecución — última validación (2026-03-29)

> Ejecutar con: `python3 bot.py` (desktop) o `python3 bot.py --mobile` (mobile)
> El bot imprime el resultado de cada flujo. Copiar aquí después de cada sesión.

### Desktop — `sb2revamp2.somosbelcorp.com`

| # | Flujo | Resultado | Causa si falla |
|---|-------|-----------|----------------|
| 1 | Ésika PLP + PDP | ✅ PLP / ⚠️ PDP sin_boton | PDP llegó pero sin botón — producto agotado en este env |
| 2 | Fragancias PLP + PDP | ✅ PLP / ⏭️ PDP ya_agregado | Correcto — ya estaba en carrito |
| 3 | Carrusel Gana+ | ⚠️ PLP ok / PDP no encontrado | Todos los slides ya agregados en este env |
| 4 | Pedido | ⚠️ Parcial | Selección 3 opciones → btn disabled (stock 0 en opciones) |
| 5 | Buscador checkout | ✅ | |
| 6 | Search PLP | ✅ | |
| 7 | Mini buscador | ✅ | `cantidad_variable` detectado y manejado |
| 8 | Liquidación | ❌ BOT | Nueva UI del portal — artículos no encontrados, modals en cascada |
| 9 | Festivales PLP | ❌ AMBIENTE | URL `/festivales` no existe en esta campaña |
| 10 | Festivales carrusel | ❌ AMBIENTE | Misma razón que F9 |
| 11 | Carrusel home | ⚠️ Parcial | Todos los productos ya agregados en env de prueba |

**Leyenda**: ✅ Completo · ⚠️ Parcial (completó lo posible) · ❌ BOT (bloqueante del código) · ❌ AMBIENTE (limitación del env de prueba)

### Mobile — pendiente de re-validar con el nuevo env

---

## Flujos de compra — Desktop (1280x800)

| # | Flujo | Función |
|---|-------|---------|
| 1 | Ésika – PLP agregar directo + PDP | `flujo_1_esika` |
| 2 | Categorías Fragancias – PLP + PDP | `flujo_2_categorias` |
| 3 | Carruseles Gana+ – directo + PDP | `flujo_3_carrusel_gana` |
| 4 | Pedido – Lo más vendido + Ofertas recomendadas | `flujo_4_pedido` |
| 5 | Buscador de checkout | `flujo_5_buscador_checkout` |
| 6 | Buscador (search PLP) | `flujo_6_search_plp` |
| 7 | Mini buscador | `flujo_7_mini_buscador` |
| 8 | Liquidación PLP | `flujo_8_liquidacion` |
| 9 | Festivales PLP | `flujo_9_festivales_plp` |
| 10 | Festivales carrusel premios | `flujo_10_festivales_carrusel` |
| 11 | Carrusel de home | `flujo_11_carrusel_home` |

## Flujos de compra — Mobile (390x844)

| # | Flujo | Notas |
|---|-------|-------|
| M1 | Ésika – PLP + PDP | JS click Gana+ + image click PDP |
| M2 | Categorías Fragancias | Mismo mecanismo que M1 |
| M3 | Carruseles Gana+ | TargetClosedError — recovery automático |
| M4 | Pedido | Selección obligatoria funciona |
| M5 | Buscador checkout | JS click `btnAgregarDePedido` oculto |
| M6 | Search PLP | Enter fallback + `abrir_buscador_header` |
| M7 | Mini buscador | Mobile redirige a `/buscador` |
| M8 | Liquidación PLP | Image click PDP (sin hover) |
| M9 | Festivales PLP | Image click PDP |
| M10 | Festivales carrusel | `div.redireccionarFicha` |
| M11 | Carrusel home | Fallback image click |

---

## Pendientes

| # | Tarea | Prioridad | Estado | Descripción |
|---|-------|-----------|--------|-------------|
| P10 | Flujo 8 — Liquidación nueva UI | Alta | 🔧 En progreso | La nueva UI del portal usa React con CSS-in-JS, sin `article[data-card-cuv]`. Múltiples modals en cascada bloquean el contenido. `cerrar_popups` mejorado, falta detectar el selector correcto de artículos en la nueva UI. |
| P11 | Flujo 1 PDP `sin_boton` | Media | Pendiente | Cuando `map_pdp` retorna `sin_boton` sin haber intentado agregar, loguear más contexto (URL, texto visible) para distinguir agotado de error de selector. |
| P12 | **Limpiar carrito antes de ejecutar** | Alta | ✅ Hecho | `limpiar_carrito()` navega a Pedido y elimina productos en loop hasta vaciar. Corre automáticamente al inicio de cada ejecución. Pendiente: validar selectores del botón Eliminar en el env de prueba. |
| P13 | **Output de estado de flujos** | Alta | ✅ Hecho | `guardar_status_flujos()` genera `tools/output/flow_status_<ts>.json` con estado (completo/parcial/error), causa y duración de cada flujo. Imprime tabla resumen en consola al finalizar. |
| P7 | Explorador de PDPs (`explorar_pdps.py`) | Alta | 🔧 En progreso | Recorre secciones, captura fingerprints y clasifica tipos de producto. Falta: fix de URL de PDP (`/Detalles/Evento/...` no `/ficha/`), manejo de sesión durante navegación. |
| P8 | Actualizar `map_pdp()` con tipos reales | Alta | Pendiente | Con resultados del explorador, cubrir los ~6 tipos: simple, selección de tono, arma tu oferta, cantidad mínima, cantidad variable, agotado. |
| P9 | `pdp_agregar()` para todos los tipos | Alta | Parcial | `simple`, `seleccion_multi`, `cantidad_variable`, `cantidad_minima` implementados. Pendiente: validar en ambiente con stock real. |
| P4 | Interceptar datos backend | Media | Pendiente | `page.on("response")` para capturar POSTs a APIs de pedido/carrito. |
| P5 | Mejorar output analytics por flujo | Media | Pendiente | Separar por flujo + resumen con conteo por evento. |

## Completados

| # | Tarea | Descripción |
|---|-------|-------------|
| P1 | `config.json` | URL base, CUVs, search terms, país, device |
| P2 | Estabilizar M3 | `ir_a_gana` usa `page.goto(href)` |
| P3 | Skip productos agregados | `producto_ya_agregado()` unifica 5 patrones |
| P3b | Selectores multi-entorno | Fallbacks de placeholders, JS href, `.first` |
| P3c | Re-login automático | `verificar_sesion()` antes de cada flujo |
| P3d | `map_pdp()` — detección dinámica | Reemplaza `_detectar_tipo_pdp()`, detecta 6 tipos en tiempo real; `pdp_agregar()` actúa según el mapa |
| P3e | Login con país | `BELCORP_COUNTRY` en `.env` → `#ddlPais` |
| P3f | `_navegar_via_link()` | Busca links por keyword en href/label/texto — robusto ante cambios de URL |
| P6 | Pre-mapeo productos | Integrado en explorador (P7) |

## Herramientas

| Herramienta | Estado | Descripción |
|-------------|--------|-------------|
| `bot.py` | ✅ Funcional | 11 flujos desktop + 11 mobile |
| `tools/explorar_pdps.py` | 🔧 En progreso | Explorador de PDPs — cataloga tipos de producto |
| `tools/page_mapper.py` | ✅ | Mapea accionables, obstáculos, formularios |
| `capturar_selectores.py` | ✅ | Captura interactiva de selectores CSS |
