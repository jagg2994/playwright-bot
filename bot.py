"""
Bot de automatización Belcorp – Captura de eventos GA4.

Ejecuta tres flujos de compra en somosbelcorp.com usando Playwright e intercepta
las peticiones POST a Google Analytics 4 para generar evidencia de los eventos
disparados (add_to_cart, view_item, select_item, etc.).

Uso:
    python bot.py

Output:
    eventos_analytics.json  — array de eventos GA4 con flow, timestamp e items.
"""
import os
import sys
import argparse
from datetime import datetime
import pytz
import urllib.parse
import json
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

# ── Contexto global del flujo activo (se adjunta a cada evento GA4 capturado) ──
current_flow = None

# ── Carpeta de debug ──────────────────────────────────────────────────
DEBUG_DIR = "debug"
os.makedirs(DEBUG_DIR, exist_ok=True)


def debug_screenshot(page, nombre: str) -> str:
    """
    Guarda un screenshot del estado actual del navegador en debug/<nombre>_<ts>.png.
    Retorna la ruta del archivo guardado.
    Usar en bloques except para facilitar el diagnóstico de fallos.
    """
    ts = datetime.now().strftime("%H%M%S")
    path = os.path.join(DEBUG_DIR, f"{nombre}_{ts}.png")
    try:
        page.screenshot(path=path)
        print(f"   📸 Screenshot guardado: {path}")
    except Exception:
        print(f"   ⚠️  No se pudo guardar screenshot: {path}")
    return path


def set_flow(name: str) -> None:
    """Actualiza el nombre del flujo activo para etiquetar los eventos GA4."""
    global current_flow
    current_flow = name


# ── Identificadores de flujo (usados como valor del campo "flow" en el JSON) ──
FLOW_ESIKA_PLP_PDP     = "esika_plp_pdp_flow"
FLOW_GANA_CATEGORIAS_1 = "gana_categorias_1_flow"
FLOW_GANA_CARRUSEL1    = "gana+_carrusele1_flow"
FLOW_PEDIDO_CARRUSELES = "pedido_carruseles_flow"
FLOW_BUSCADOR_CHECKOUT = "buscador_checkout_flow"

# ── Configuración por país ───────────────────────────────────────────
# CUV para buscar en el buscador de checkout (cambiar según el país)
CUV_CHECKOUT = os.getenv("BELCORP_CUV", "10989")

# ── Selectores de botones de cierre de popup (orden de prioridad) ──────
SELECTORES_POPUP = [
    "button.cerrar-modal",
    "button.btn-cerrar",
    "button.close",
    "a.close",
    "[class*='popup'] [class*='close']",
    "[class*='modal'] [class*='close']",
    "[class*='overlay'] [class*='close']",
    "button[aria-label='Cerrar']",
    "button[aria-label='cerrar']",
    "button[aria-label='Close']",
    "[data-dismiss='modal']",
    ".boton-cerrar",
    "#btnCerrarModal",
]


# ══════════════════════════════════════════════════════════════════════
# GA4 Parser
# ══════════════════════════════════════════════════════════════════════
def parse_ga4_post_data(post_data: str) -> list:
    """
    Parsea el body de una petición POST a GA4 Measurement Protocol.

    El body contiene múltiples eventos separados por newline, cada uno
    codificado como query string. Extrae solo los eventos relevantes
    (add_to_cart, view_item_list, etc.) y sus items de producto (pr<N>).

    Args:
        post_data: Cuerpo crudo de la petición POST a */collect*.

    Returns:
        Lista de dicts con keys: name, currency, timestamp,
        timestamp_readable, parameters, items.
    """
    eventos = []
    bloques = post_data.split("\n")
    eventos_deseados = {
        "add_to_cart", "view_item_list", "select_item",
        "view_item", "view_popup", "page_view", "select_content"
    }
    for bloque in bloques:
        params = urllib.parse.parse_qs(bloque)
        name = params.get("en", [None])[0]
        if name not in eventos_deseados:
            continue

        ts = int(datetime.now().timestamp())
        tz_col = pytz.timezone("America/Bogota")
        ts_readable = datetime.fromtimestamp(ts, tz=tz_col).strftime("%Y-%m-%d %H:%M:%S")

        currency = params.get("cu", ["COP"])[0].strip()

        raw_params = {}
        for k, v in params.items():
            if k in {"en", "cu"} or re.fullmatch(r"pr\d+", k):
                continue
            nuevo_key = k
            if k.startswith("epn."):
                nuevo_key = k.split(".", 1)[1]
            elif k.startswith("ep."):
                nuevo_key = k.split(".", 1)[1]
            raw_params[nuevo_key] = v[0] if len(v) == 1 else v

        items = []
        pr_keys = sorted(
            [k for k in params if re.fullmatch(r"pr\d+", k)],
            key=lambda x: int(x[2:])
        )
        for pr_key in pr_keys:
            raw = params[pr_key][0]
            partes = raw.split("~")
            item = {}
            for p in partes:
                pref = p[:2]
                val  = p[2:]
                if pref == "id":   item["item_id"]        = val
                elif pref == "nm": item["item_name"]      = val
                elif pref == "lp": item["index"]          = int(val) + 1
                elif pref == "ln": item["item_list_name"] = val
                elif pref == "li": item["item_list_id"]   = val
                elif pref == "br": item["item_brand"]     = val
                elif pref == "ca": item["item_category"]  = val
                elif pref.startswith("c") and pref[1:].isdigit():
                    idx = pref[1:]
                    key_cat = f"item_category{idx}"
                    item[key_cat] = val.split("::", 1)[1].strip() if "::" in val else val
                elif pref == "va": item["item_variant"]  = val
                elif pref == "af": item["affiliation"]   = val
                elif pref == "pr": item["price"]         = val
                elif pref == "ds": item["discount"]      = val
                elif pref == "qt": item["quantity"]      = val
            items.append(item)

        eventos.append({
            "name": name,
            "currency": currency,
            "timestamp": ts,
            "timestamp_readable": ts_readable,
            "parameters": raw_params,
            "items": items
        })

    return eventos


# ══════════════════════════════════════════════════════════════════════
# Utilidad: tipo de botón
# ══════════════════════════════════════════════════════════════════════
def _btn_texto(elemento):
    """
    Devuelve el texto del a#btnAgregalo dentro del elemento dado,
    o None si no existe / no es visible.
    """
    btn = elemento.query_selector("a#btnAgregalo")
    if btn and btn.is_visible():
        return btn.inner_text().strip()
    return None


# ══════════════════════════════════════════════════════════════════════
# Navegación general
# ══════════════════════════════════════════════════════════════════════
def login(page) -> None:
    """Navega a la home, rellena credenciales y espera a que cargue el menú principal."""
    print("➡️  Login...")
    page.goto("https://www.somosbelcorp.com/")
    page.fill("#txtUsuario", os.getenv("BELCORP_USER"))
    page.fill("#txtContrasenia", os.getenv("BELCORP_PASS"))
    page.click("#btnLogin")
    page.wait_for_selector('li.menu-item >> text="Gana+"', timeout=15000)
    print("✅ Login OK")


# ══════════════════════════════════════════════════════════════════════
# Manejo de popups
# ══════════════════════════════════════════════════════════════════════
def cerrar_popups(page) -> None:
    """
    Intenta cerrar cualquier popup/modal visible probando los selectores
    conocidos en orden. Útil para llamar manualmente tras una navegación.
    """
    for selector in SELECTORES_POPUP:
        try:
            btn = page.locator(selector).first
            if btn.count() and btn.is_visible(timeout=300):
                btn.click()
                print(f"   🚫 Popup cerrado ({selector})")
                page.wait_for_timeout(400)
                return
        except Exception:
            continue


def registrar_handler_popups(page) -> None:
    """
    Registra handlers automáticos con add_locator_handler: Playwright los
    dispara internamente cada vez que el selector se vuelve visible durante
    cualquier acción, sin necesidad de llamadas manuales.
    """
    for selector in SELECTORES_POPUP:
        try:
            page.add_locator_handler(
                page.locator(selector).first,
                lambda loc: loc.click() if loc.is_visible() else None
            )
        except Exception:
            continue
    print("   🔔 Handlers de popup registrados")


def ir_a_pedido(page) -> None:
    """Navega directamente a la sección de Pedido (checkout) y espera los carruseles."""
    print("➡️  Ir a Pedido...")
    page.goto("https://www.somosbelcorp.com/Pedido")
    page.wait_for_selector("div.contenedor_carrusel.slick-slider[data-seccion-productos]", timeout=15000)
    print("✅ En Pedido")


def ir_a_gana(page) -> None:
    """
    Hace clic en el ítem 'Gana+' del menú principal.
    En mobile abre primero el menú hamburguesa si el ítem no es visible.
    """
    print("➡️  Ir a Gana+...")
    # Si el menú está oculto (mobile), abrirlo primero
    menu_item = page.locator('li.menu-item >> text="Gana+"')
    if not menu_item.is_visible():
        hamburger = page.locator("button.menu-hamburguesa, button[aria-label*='menú' i], .navbar-toggler, #btnMenuMobile").first
        if hamburger.count() and hamburger.is_visible():
            hamburger.click()
            page.wait_for_timeout(600)
    page.wait_for_selector('li.menu-item >> text="Gana+"', timeout=10000)
    page.click('li.menu-item >> text="Gana+"')
    page.wait_for_timeout(3000)
    print("✅ En Gana+")


def click_categoria_esika(page) -> None:
    """Selecciona el filtro de marca Ésika y espera a que cargue la PLP."""
    print("➡️  Categoría Ésika...")
    page.wait_for_selector('li[data-codigo="mar-esika"]', timeout=10000)
    page.click('li[data-codigo="mar-esika"]')
    page.wait_for_selector("#FichasProductosBuscador article", timeout=10000)
    print("✅ PLP Ésika cargada")


def click_categorias(page) -> None:
    """Selecciona el filtro de categoría Fragancias y espera a que cargue la PLP."""
    print("➡️  Categoría Fragancias...")
    page.wait_for_selector('li[data-codigo="cat-fragancia"]', timeout=10000)
    page.click('li[data-codigo="cat-fragancia"]')
    page.wait_for_selector("#FichasProductosBuscador article", timeout=10000)
    print("✅ PLP Fragancias cargada")


# ══════════════════════════════════════════════════════════════════════
# PLP – Agregar directo (botón dice exactamente "Agregar")
# ══════════════════════════════════════════════════════════════════════
def plp_agregar_directo(page):
    """
    Recorre los artículos de la PLP y hace clic en el primer
    a#btnAgregalo cuyo texto sea exactamente "Agregar".
    Retorna el índice (1-based) del producto clickeado, o None.
    """
    print("🛒 PLP → buscando producto con botón 'Agregar'...")
    try:
        page.wait_for_selector("#FichasProductosBuscador article", timeout=10000)
        productos = page.query_selector_all("#FichasProductosBuscador article")
        for idx, prod in enumerate(productos, 1):
            # Skip si ya fue agregado en un flujo anterior (y es visible)
            caja = prod.query_selector("div.caja_producto_agregado")
            if caja and caja.is_visible():
                print(f"   ⏭️  Producto {idx} ya fue agregado → skip")
                continue
            texto = _btn_texto(prod)
            if texto and texto.lower() == "agregar":
                print(f"   ✅ Producto {idx} → clic en 'Agregar'")
                prod.query_selector("a#btnAgregalo").click()
                page.wait_for_timeout(2000)
                return idx
        print("   ❌ No se encontró producto con botón 'Agregar' en PLP")
    except Exception as e:
        debug_screenshot(page, "plp_agregar_directo")
        print(f"   ❌ Error en plp_agregar_directo: {e}")
    return None


# ══════════════════════════════════════════════════════════════════════
# PLP – Ir a PDP (el botón dice CUALQUIER COSA distinta a "Agregar")
# ══════════════════════════════════════════════════════════════════════
def plp_ir_a_pdp(page, skip_index=None):
    """
    Recorre la PLP y hace clic en el primer a#btnAgregalo cuyo texto
    NO sea "Agregar" (p.ej. "Ver detalle"). Ese clic navega a la PDP.
    Retorna el índice clickeado o None.
    """
    print("🔗 PLP → buscando producto para ir a PDP...")
    try:
        page.wait_for_selector("#FichasProductosBuscador article", timeout=10000)
        productos = page.query_selector_all("#FichasProductosBuscador article")
        for idx, prod in enumerate(productos, 1):
            if idx == skip_index:
                continue
            texto = _btn_texto(prod)
            if texto and texto.lower() != "agregar":
                print(f"   ✅ Producto {idx} → clic en '{texto}' → navegando a PDP")
                prod.query_selector("a#btnAgregalo").click()
                page.wait_for_timeout(3000)
                return idx
        print("   ❌ No se encontró producto para ir a PDP")
    except Exception as e:
        debug_screenshot(page, "plp_ir_a_pdp")
        print(f"   ❌ Error en plp_ir_a_pdp: {e}")
    return None


# ══════════════════════════════════════════════════════════════════════
# PDP – helpers
# ══════════════════════════════════════════════════════════════════════
def _cerrar_alerta_general(page) -> bool:
    """
    Cierra #alertDialogMensajesGenerales si está visible (p.ej. "Entendido").
    Retorna True si había alerta y fue cerrada.
    A diferencia de los handlers automáticos, este helper se llama de forma
    explícita para que no interfiera con modales de selección.
    """
    try:
        alerta = page.locator("#alertDialogMensajesGenerales")
        if alerta.is_visible(timeout=400):
            btn = alerta.locator("fd-button, button").first
            if btn.count() and btn.is_visible():
                btn.click()
                page.wait_for_timeout(400)
                print("      ⚠️  Alerta general cerrada")
                return True
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════════════════════
# PDP – Agregar al carrito
# ══════════════════════════════════════════════════════════════════════
def pdp_agregar(page):
    """
    Agrega el producto desde la PDP actual.

    Flujo:
      1. Si btn_deshabilitado_ficha existe sin selecciones pendientes → skip.
      2. Selecciones obligatorias (button.tono_select_opt / "Arma tu oferta"):
           Por cada botón de selección:
             - Click para abrir modal
             - Clic en button[btn-eligelo] uno a uno hasta que
               button#btn-aplicar-seleccion.active se active
             - Confirmar (con reintento si aparece alerta general)
      3. Clic en a#btnAgregalo.btn_validar_alertas.
         Si el botón aún dice "Elegir oferta"/"Elegir opción" significa que
         no se completaron todas las selecciones; se intenta igual y se avisa.
    Retorna True si se procesó, False si se saltó.
    """
    print("🛍️  PDP → agregando al carrito...")
    try:
        # 1) ¿Ya fue agregado?
        btn_deshabilitado = page.query_selector("a#btnAgregalo.btn_deshabilitado_ficha")
        modales_pendientes = page.locator(
            'button.tono_select_opt.nobg[btn-show-types-tones-modal]'
        ).count()
        if btn_deshabilitado and btn_deshabilitado.is_visible() and modales_pendientes == 0:
            print("   ⏭️  Producto ya agregado en pedido anterior → skip")
            return False

        # 2) Selecciones obligatorias (una por cada slot de "Arma tu oferta" o
        #    por cada atributo obligatorio como tono/color).
        selection_btns = page.locator(
            'button.tono_select_opt.nobg[btn-show-types-tones-modal]'
        )
        total_selecciones = selection_btns.count()

        if total_selecciones > 0:
            print(f"   🎯 {total_selecciones} selección(es) obligatoria(s)")
            for i in range(total_selecciones):
                btn_sel = selection_btns.nth(i)
                print(f"   📋 Abriendo selección {i+1}/{total_selecciones}...")
                btn_sel.scroll_into_view_if_needed(timeout=3000)
                btn_sel.click()
                page.wait_for_timeout(800)
                _cerrar_alerta_general(page)

                # Esperar opciones del modal
                opciones = page.locator("button[btn-eligelo]")
                try:
                    opciones.first.wait_for(state="visible", timeout=6000)
                except Exception:
                    print(f"      ⚠️  Modal sin opciones para selección {i+1} → skip")
                    _cerrar_alerta_general(page)
                    continue

                # Leer la cantidad requerida desde el título del modal
                # h3[header-title] → texto "Elige X opción(es)"
                requeridos = 1
                try:
                    import re
                    titulo = page.locator("h3[header-title]")
                    if titulo.count():
                        texto_titulo = titulo.first.inner_text().strip()
                        match = re.search(r'\d+', texto_titulo)
                        if match:
                            requeridos = int(match.group())
                            print(f"      📌 '{texto_titulo}' → seleccionar {requeridos}")
                except Exception:
                    pass

                # Clickear button[btn-eligelo] directamente.
                # No re-clickear los ya seleccionados (tienen clase btn_deshabilitado).
                opciones = page.locator("button[btn-eligelo]:not(.btn_deshabilitado)")
                seleccionados = 0
                for j in range(opciones.count()):
                    if seleccionados >= requeridos:
                        break
                    opt = opciones.nth(j)
                    if not opt.is_visible():
                        continue
                    opt.click()
                    seleccionados += 1
                    page.wait_for_timeout(1000)
                    # Debug: mostrar clase actual del botón confirmar para diagnóstico
                    try:
                        clase_btn = page.locator("button#btn-aplicar-seleccion").first.get_attribute("class") or ""
                        print(f"      ✔️  Opción {seleccionados}/{requeridos} seleccionada → btn class: '{clase_btn}'")
                    except Exception:
                        print(f"      ✔️  Opción {seleccionados}/{requeridos} seleccionada")

                # El botón se activa (.active) justo después de seleccionar, pero
                # wait_for dispara los locator handlers que lo resetean.
                # Usamos JS directo para hacer click sin activar handlers de Playwright.
                clicked = page.evaluate("""
                    () => {
                        const btn = document.querySelector('button#btn-aplicar-seleccion.active');
                        if (btn) { btn.click(); return true; }
                        return false;
                    }
                """)
                if clicked:
                    print(f"      ✔️  Selección {i+1} confirmada")
                    page.wait_for_timeout(1200)
                    _cerrar_alerta_general(page)
                else:
                    clase_final = page.locator("button#btn-aplicar-seleccion").first.get_attribute("class") or "no encontrado"
                    print(f"      ⚠️  Botón Aplicar no activo — clase: '{clase_final}'")

        # 3) Clic en botón principal de la PDP
        #    JS scroll + click para evitar que add_locator_handler interfiera.
        page.wait_for_timeout(1000)
        resultado = page.evaluate("""
            () => {
                const btn = document.querySelector('a#btnAgregalo.btn_validar_alertas');
                if (!btn) return {ok: false, error: 'no encontrado'};
                btn.scrollIntoView({block: 'center'});
                const texto = (btn.innerText || '').trim();
                const deshabilitado = btn.classList.contains('btn_deshabilitado_ficha');
                if (deshabilitado) return {ok: false, error: 'deshabilitado', texto: texto};
                btn.click();
                return {ok: true, texto: texto};
            }
        """)
        if resultado.get("ok"):
            print(f"   Botón PDP: '{resultado.get('texto', '')}'")
            page.wait_for_timeout(3500)
            _cerrar_alerta_general(page)
            print("   ✅ Agregado desde PDP")
            return True
        else:
            print(f"   ⚠️  Botón PDP: {resultado.get('error', 'desconocido')} — texto: '{resultado.get('texto', '')}'")
            return False

    except Exception as e:
        debug_screenshot(page, "pdp_agregar")
        print(f"   ❌ Error en pdp_agregar: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
# Carrusel – Agregar directo (botón dice exactamente "Agregar")
# ══════════════════════════════════════════════════════════════════════
def carrusel_agregar_directo(page, start_ci=0):
    """
    Recorre los carruseles (desde start_ci) slide a slide buscando el primer
    a#btnAgregalo con texto "Agregar" y lo clickea.
    Retorna (ci, si) con el carrusel e índice de slide, o (None, None).
    """
    print("🎠 Carrusel → buscando producto con botón 'Agregar'...")
    carruseles = page.locator("div.contenedor_carrusel.slick-slider[data-seccion-productos]")
    total = carruseles.count()
    print(f"   {total} carruseles detectados")

    for ci in range(start_ci, total):
        root = carruseles.nth(ci)
        try:
            root.scroll_into_view_if_needed(timeout=2000)
        except:
            pass
        next_btn = root.locator(".nextArrow.slick-arrow").first
        si = 0

        while True:
            slide = root.locator("article.slick-current")
            try:
                slide.wait_for(state="attached", timeout=2000)
            except Exception:
                break

            # Skip si ya fue agregado en un flujo anterior (y es visible)
            caja_loc = slide.locator("div.caja_producto_agregado")
            if caja_loc.count() and caja_loc.is_visible():
                print(f"   ⏭️  Carrusel {ci+1}, slide {si+1} ya agregado → skip")
            else:
                btn = slide.locator("a#btnAgregalo")
                if btn.count() and btn.is_visible():
                    texto = btn.inner_text().strip()
                    if texto.lower() == "agregar":
                        print(f"   ✅ Carrusel {ci+1}, slide {si+1} → 'Agregar' → click")
                        btn.click()
                        page.wait_for_timeout(3000)
                        return ci, si

            # Avanzar slide
            try:
                if not next_btn.is_visible():
                    break
                next_btn.click()
                page.wait_for_timeout(600)
                si += 1
            except Exception:
                break

        print(f"   ⚠️  Carrusel {ci+1}: no encontré botón 'Agregar'")

    print("   ❌ Ningún carrusel tiene botón 'Agregar'")
    return None, None


# ══════════════════════════════════════════════════════════════════════
# Carrusel – Ir a PDP (botón dice CUALQUIER COSA distinta a "Agregar")
# ══════════════════════════════════════════════════════════════════════
def carrusel_ir_a_pdp(page, start_ci=0, start_si=0):
    """
    Desde la posición (start_ci, start_si+1) recorre carruseles buscando
    un a#btnAgregalo con texto distinto a "Agregar".
    Ese clic navega a la PDP del producto.
    Retorna (ci, si) o (None, None).
    """
    print("🔗 Carrusel → buscando producto para ir a PDP...")
    carruseles = page.locator("div.contenedor_carrusel.slick-slider[data-seccion-productos]")
    total = carruseles.count()

    for ci in range(start_ci, total):
        root = carruseles.nth(ci)
        try:
            root.scroll_into_view_if_needed(timeout=2000)
        except:
            pass
        next_btn = root.locator(".nextArrow.slick-arrow").first

        # En el mismo carrusel del inicio, avanzamos desde start_si+1
        if ci == start_ci:
            page.evaluate(f"""
                () => {{
                    const s = document.querySelectorAll(
                        'div.contenedor_carrusel.slick-slider[data-seccion-productos]'
                    )[{ci}];
                    if (window.jQuery && s) window.jQuery(s).slick('slickGoTo', {start_si + 1});
                }}
            """)
            page.wait_for_timeout(600)
            si = start_si + 1
        else:
            si = 0

        for _ in range(20):
            slide = root.locator("article.slick-current")
            try:
                slide.wait_for(state="attached", timeout=2000)
            except Exception:
                break

            btn = slide.locator("a#btnAgregalo")
            if btn.count() and btn.is_visible():
                texto = btn.inner_text().strip()
                if texto.lower() != "agregar":
                    print(f"   ✅ Carrusel {ci+1}, slide {si+1} → '{texto}' → navegando a PDP")
                    btn.click()
                    page.wait_for_timeout(3000)
                    return ci, si

            # Avanzar slide
            try:
                if not next_btn.is_visible():
                    break
                next_btn.click()
                page.wait_for_timeout(600)
                si += 1
            except Exception:
                break

        print(f"   ⚠️  Carrusel {ci+1}: no encontré producto para PDP")

    print("   ❌ No se encontró producto en carrusel para ir a PDP")
    return None, None


# ══════════════════════════════════════════════════════════════════════
# Pedido – Carrusel "Lo más vendido" (venta_2)
# ══════════════════════════════════════════════════════════════════════
def lo_mas_vendido_ir_a_pdp(page, start_si=1):
    """
    En el carrusel 'Lo más vendido' todos los botones dicen 'Agregar',
    por lo que no se puede usar carrusel_ir_a_pdp. En su lugar, avanza
    al slide indicado y hace clic en el link del card del producto para
    navegar a la PDP.
    Retorna True si navigó a PDP, False si no encontró link.
    """
    print("🔗 Lo más vendido → buscando card para ir a PDP...")
    try:
        carruseles = page.locator("div.contenedor_carrusel.slick-slider[data-seccion-productos]")
        if not carruseles.count():
            print("   ❌ No se encontró el carrusel Lo más vendido")
            return False

        root = carruseles.first
        root.scroll_into_view_if_needed(timeout=2000)

        # Avanzar al slide start_si
        if start_si > 0:
            page.evaluate(f"""
                () => {{
                    const s = document.querySelector(
                        'div.contenedor_carrusel.slick-slider[data-seccion-productos]'
                    );
                    if (window.jQuery && s) window.jQuery(s).slick('slickGoTo', {start_si});
                }}
            """)
            page.wait_for_timeout(700)

        slide = root.locator("article.slick-current")
        slide.wait_for(state="attached", timeout=3000)

        # Buscar el link del card que NO sea el botón #btnAgregalo
        link = slide.locator("a:not(#btnAgregalo)").first
        if link.count() and link.is_visible():
            href = link.get_attribute("href") or ""
            print(f"   ✅ Card link encontrado → {href[:60]}… → click")
            link.click()
            page.wait_for_timeout(3000)
            return True

        print("   ❌ No se encontró link de card en Lo más vendido")
    except Exception as e:
        debug_screenshot(page, "lo_mas_vendido_ir_a_pdp")
        print(f"   ❌ Error en lo_mas_vendido_ir_a_pdp: {e}")
    return False


# ══════════════════════════════════════════════════════════════════════
# Pedido – Carrusel vertical "Ofertas recomendadas para ti" (venta_1)
# ══════════════════════════════════════════════════════════════════════
def ofertas_ir_a_pdp(page) -> bool:
    """
    Carrusel vertical 'Ofertas recomendadas': navega al slide 0 y hace
    click en a[data-item-tag='verdetalle'] para entrar a la PDP.
    Retorna True si navegó, False si falló.
    """
    print("💡 Ofertas recomendadas → ir a PDP...")
    try:
        contenedor = page.locator("#divListadoEstrategia, .content_carrusel_ofertas").first
        contenedor.wait_for(state="visible", timeout=10000)
        contenedor.scroll_into_view_if_needed(timeout=2000)

        # Volver al slide 0
        page.evaluate("""
            () => {
                const s = document.querySelector('#divListadoEstrategia')
                       || document.querySelector('.content_carrusel_ofertas');
                if (window.jQuery && s) window.jQuery(s).slick('slickGoTo', 0);
            }
        """)
        page.wait_for_timeout(700)

        slide0 = contenedor.locator("div.ctn-estrategia.slick-current, div.slick-slide.slick-current").first
        slide0.wait_for(state="attached", timeout=3000)

        ver_detalle = slide0.locator("a[data-item-tag='verdetalle']").first
        if ver_detalle.count() and ver_detalle.is_visible():
            print("   ✅ Navegando a PDP via a[data-item-tag='verdetalle']")
            ver_detalle.click()
            page.wait_for_timeout(3000)
            return True

        print("   ❌ No se encontró a[data-item-tag='verdetalle']")
    except Exception as e:
        debug_screenshot(page, "ofertas_ir_a_pdp")
        print(f"   ❌ Error en ofertas_ir_a_pdp: {e}")
    return False


def ofertas_agregar_directo(page) -> bool:
    """
    Carrusel vertical 'Ofertas recomendadas': recorre slides buscando
    a.boton_Agregalo_home con texto 'Agregar' y lo clickea directamente.
    Importante: scoped a #divListadoEstrategia para no confundir con
    el carrusel horizontal.
    Retorna True si agregó, False si no encontró.
    """
    print("💡 Ofertas recomendadas → agregar directo...")
    try:
        # Buscar contenedor del carrusel vertical
        contenedor = page.locator("#divListadoEstrategia").first
        if not contenedor.count():
            contenedor = page.locator(".content_carrusel_ofertas").first
        if not contenedor.count():
            print("   ❌ No se encontró contenedor del carrusel vertical")
            debug_screenshot(page, "ofertas_no_contenedor")
            return False

        contenedor.wait_for(state="visible", timeout=10000)
        contenedor.scroll_into_view_if_needed(timeout=2000)
        page.wait_for_timeout(1000)

        # Debug: contar botones "Agregar" visibles en todo el contenedor
        todos_btns = contenedor.locator("a.boton_Agregalo_home.boton_Agregalo_home_pase_pedido")
        total_btns = todos_btns.count()
        print(f"   📊 Botones a.boton_Agregalo_home encontrados en contenedor: {total_btns}")

        # Si hay algún botón visible directamente, usarlo (sin depender de slides)
        for bi in range(total_btns):
            btn = todos_btns.nth(bi)
            if btn.is_visible():
                texto = btn.inner_text().strip()
                print(f"   📋 Botón {bi+1}/{total_btns} visible → texto: '{texto}'")
                if "agregar" in texto.lower():
                    btn.scroll_into_view_if_needed(timeout=2000)
                    print(f"   ✅ Botón '{texto}' → click")
                    btn.click()
                    page.wait_for_timeout(3000)
                    return True

        # Si no hay visible, navegar slides con flechas
        next_btn = contenedor.locator("button.next-flecha-dorada, button.slick-next").first
        print(f"   🔄 Navegando slides (flecha visible: {next_btn.count() and next_btn.is_visible()})")

        for si in range(20):
            try:
                if not next_btn.count() or not next_btn.is_visible():
                    break
                next_btn.click()
                page.wait_for_timeout(800)
            except Exception:
                break

            # Después de avanzar, buscar botón visible
            for bi in range(todos_btns.count()):
                btn = todos_btns.nth(bi)
                if btn.is_visible():
                    texto = btn.inner_text().strip()
                    print(f"   📋 Slide {si+2} → botón texto: '{texto}'")
                    if "agregar" in texto.lower():
                        btn.scroll_into_view_if_needed(timeout=2000)
                        print(f"   ✅ '{texto}' → click")
                        btn.click()
                        page.wait_for_timeout(3000)
                        return True

        print("   ⚠️  No se encontró botón 'Agregar' en Ofertas recomendadas")
        debug_screenshot(page, "ofertas_sin_agregar")
    except Exception as e:
        debug_screenshot(page, "ofertas_agregar_directo")
        print(f"   ❌ Error en ofertas_agregar_directo: {e}")
    return False


# ══════════════════════════════════════════════════════════════════════
# Patrones genéricos reutilizables
# ══════════════════════════════════════════════════════════════════════
def ejecutar_flujo_plp(page, flow_name: str, label: str, navegar_fn) -> None:
    """
    Patrón estándar PLP:
      1. navegar_fn(page)  — lleva al listado
      2. Agregar directo desde PLP (botón "Agregar")
      3. Ir a PDP de otro producto → agregar → volver
    """
    print("\n" + "═"*50)
    print(f"FLUJO: {label}")
    print("═"*50)
    set_flow(flow_name)

    navegar_fn(page)
    cerrar_popups(page)

    idx = plp_agregar_directo(page)
    cerrar_popups(page)

    idx_pdp = plp_ir_a_pdp(page, skip_index=idx)
    if idx_pdp:
        cerrar_popups(page)
        pdp_agregar(page)
        page.go_back()
        page.wait_for_selector("#FichasProductosBuscador article", timeout=10000)


def ejecutar_flujo_carrusel(page, flow_name: str, label: str, navegar_fn) -> None:
    """
    Patrón estándar carrusel (1 carrusel):
      1. navegar_fn(page)  — lleva a la página con carruseles
      2. Agregar directo desde carrusel (botón "Agregar")
      3. Ir a PDP desde el siguiente slide → agregar
    """
    print("\n" + "═"*50)
    print(f"FLUJO: {label}")
    print("═"*50)
    set_flow(flow_name)

    navegar_fn(page)
    cerrar_popups(page)

    ci, si = carrusel_agregar_directo(page)
    cerrar_popups(page)

    if ci is not None:
        ci2, _ = carrusel_ir_a_pdp(page, start_ci=ci, start_si=si)
        if ci2 is not None:
            cerrar_popups(page)
            pdp_agregar(page)
        else:
            print("⚠️  No se encontró producto en carrusel para PDP")
    else:
        print("⚠️  No se pudo agregar desde carrusel")


def ejecutar_flujo_carrusel_doble(page, flow_name: str, label: str, navegar_fn) -> None:
    """
    Patrón doble carrusel (ej. Pedido):
      Ejecuta el patrón carrusel para el carrusel 0, luego para el carrusel 1.
      Si el segundo carrusel no tiene "Agregar", va directo a PDP.
    """
    print("\n" + "═"*50)
    print(f"FLUJO: {label}")
    print("═"*50)
    set_flow(flow_name)

    navegar_fn(page)
    cerrar_popups(page)

    wait_carrusel = lambda: page.wait_for_selector(
        "div.contenedor_carrusel.slick-slider[data-seccion-productos]", timeout=10000
    )

    # ── Carrusel 0 ──────────────────────────────────────────
    print("\n--- Carrusel 0 ---")
    ci0, si0 = carrusel_agregar_directo(page, start_ci=0)
    cerrar_popups(page)

    if ci0 is not None:
        ci0b, _ = carrusel_ir_a_pdp(page, start_ci=ci0, start_si=si0)
        if ci0b is not None:
            cerrar_popups(page)
            pdp_agregar(page)
            page.go_back()
            wait_carrusel()
        else:
            print("⚠️  Carrusel 0: no se encontró producto para PDP")
    else:
        print("⚠️  Carrusel 0: no se pudo agregar directo")

    # ── Carrusel 1 ──────────────────────────────────────────
    start1 = (ci0 + 1) if ci0 is not None else 1
    print(f"\n--- Carrusel {start1} ---")
    ci1, si1 = carrusel_agregar_directo(page, start_ci=start1)
    cerrar_popups(page)

    if ci1 is not None:
        ci1b, _ = carrusel_ir_a_pdp(page, start_ci=ci1, start_si=si1)
        if ci1b is not None:
            cerrar_popups(page)
            pdp_agregar(page)
            page.go_back()
            wait_carrusel()
        else:
            print("⚠️  Carrusel 1: no se encontró producto para PDP")
    else:
        print("   ℹ️  Sin 'Agregar' en carrusel 1 → yendo directo a PDP")
        ci1b, _ = carrusel_ir_a_pdp(page, start_ci=start1, start_si=-1)
        if ci1b is not None:
            cerrar_popups(page)
            pdp_agregar(page)
            page.go_back()
            wait_carrusel()
        else:
            print("⚠️  Carrusel 1: no se encontró producto para PDP")


# ══════════════════════════════════════════════════════════════════════
# Flujos individuales
# ══════════════════════════════════════════════════════════════════════
def flujo_1_esika(page) -> None:
    """Flujo 1 · Ésika – PLP agregar directo + ir a PDP + agregar desde PDP."""
    def navegar(p):
        ir_a_gana(p)
        click_categoria_esika(p)
    ejecutar_flujo_plp(page, FLOW_ESIKA_PLP_PDP, "Ésika – PLP + PDP", navegar)


def flujo_2_categorias(page) -> None:
    """Flujo 2 · Categorías Fragancias – PLP agregar directo + ir a PDP + agregar desde PDP."""
    def navegar(p):
        ir_a_gana(p)
        click_categorias(p)
    ejecutar_flujo_plp(page, FLOW_GANA_CATEGORIAS_1, "Categorías Fragancias – PLP + PDP", navegar)


def flujo_3_carrusel_gana(page) -> None:
    """Flujo 3 · Carruseles Gana+ – agregar directo + ir a PDP + agregar desde PDP."""
    ejecutar_flujo_carrusel(page, FLOW_GANA_CARRUSEL1, "Carruseles Gana+ – directo + PDP", ir_a_gana)


def flujo_4_pedido(page) -> None:
    """
    Flujo 4 · Carruseles Pedido.
    - Lo más vendido (venta_2): agregar directo + ir a PDP por card link + agregar PDP
    - Ofertas recomendadas (venta_1): ir a PDP por botón del card + agregar PDP
    """
    print("\n" + "═"*50)
    print("FLUJO 4: Pedido – Lo más vendido + Ofertas recomendadas")
    print("═"*50)
    set_flow(FLOW_PEDIDO_CARRUSELES)

    ir_a_pedido(page)
    cerrar_popups(page)

    # ── Carrusel "Lo más vendido" (venta_2) ───────────────────
    print("\n--- Lo más vendido (venta_2) ---")
    ci_mv, si_mv = carrusel_agregar_directo(page, start_ci=0)
    cerrar_popups(page)

    if ci_mv is not None:
        # Todos los slides tienen "Agregar" → ir a PDP via link del card
        navegado = lo_mas_vendido_ir_a_pdp(page, start_si=si_mv + 1)
        if navegado:
            cerrar_popups(page)
            pdp_agregar(page)
            page.go_back()
            page.wait_for_selector(
                "div.contenedor_carrusel.slick-slider[data-seccion-productos]",
                timeout=10000
            )
        else:
            print("⚠️  Lo más vendido: no se pudo ir a PDP")
    else:
        print("⚠️  Lo más vendido: no se encontró producto con botón 'Agregar'")

    # ── Carrusel "Ofertas recomendadas para ti" (venta_1) ─────
    # Orden: 1) ir a PDP via VER DETALLE → agregar → volver
    #        2) agregar directo desde el carrusel (botón "Agregar")
    print("\n--- Ofertas recomendadas para ti (venta_1) ---")
    if ofertas_ir_a_pdp(page):
        cerrar_popups(page)
        pdp_agregar(page)
        page.go_back()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)
        cerrar_popups(page)
    else:
        print("⚠️  Ofertas recomendadas: no se pudo ir a PDP")

    ofertas_agregar_directo(page)
    cerrar_popups(page)


def flujo_5_buscador_checkout(page) -> None:
    """
    Flujo 5 · Buscador de checkout.
    Ingresa un CUV en el buscador, espera que cargue el producto,
    y agrega una oferta similar con botón 'Agrégalo'.
    """
    print("\n" + "═"*50)
    print(f"FLUJO 5: Buscador de checkout (CUV: {CUV_CHECKOUT})")
    print("═"*50)
    set_flow(FLOW_BUSCADOR_CHECKOUT)

    ir_a_pedido(page)
    cerrar_popups(page)

    # 1) Ingresar CUV en el buscador (desktop)
    print(f"🔍 Ingresando CUV: {CUV_CHECKOUT}...")
    page.wait_for_timeout(2000)
    buscador = page.locator("input.txtCuvConsultaDesktop")
    buscador.wait_for(state="visible", timeout=10000)
    buscador.scroll_into_view_if_needed(timeout=3000)
    page.wait_for_timeout(1000)
    buscador.click()
    buscador.type(CUV_CHECKOUT, delay=150)
    page.wait_for_timeout(4000)
    print("   ✅ CUV ingresado, esperando resultado...")

    # 3) Buscar en ofertas similares un producto no agregado y clickearlo via JS
    print("🛍️  Buscando oferta similar no agregada...")
    try:
        cards = page.locator("li.producto_recomendado.slick-active")
        cards.first.wait_for(state="attached", timeout=10000)
        page.wait_for_timeout(1000)

        resultado = page.evaluate("""
            () => {
                const cards = document.querySelectorAll('li.producto_recomendado.slick-active');
                for (let i = 0; i < cards.length; i++) {
                    const card = cards[i];
                    const agregado = card.querySelector('div.agregado.product-add');
                    if (agregado && agregado.offsetParent !== null) continue;
                    const btn = card.querySelector('a.boton_Agregalo_home.btn_producto_recomendado_agregalo');
                    if (btn) {
                        btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        return { index: i, found: true };
                    }
                }
                return { found: false };
            }
        """)

        if resultado["found"]:
            idx = resultado["index"]
            page.wait_for_timeout(1000)
            # JS click para evitar interferencia de locator handlers
            clicked = page.evaluate("""
                (idx) => {
                    const cards = document.querySelectorAll('li.producto_recomendado.slick-active');
                    const btn = cards[idx].querySelector('a.boton_Agregalo_home.btn_producto_recomendado_agregalo');
                    if (btn) { btn.click(); return true; }
                    return false;
                }
            """, idx)
            if clicked:
                print(f"   ✅ Oferta {idx+1}: 'Agrégalo' → click")
                page.wait_for_timeout(3000)
                cerrar_popups(page)
                print("   ✅ Oferta similar agregada desde buscador de checkout")
            else:
                print("   ⚠️  No se pudo hacer click en el botón")
        else:
            print("   ⚠️  No se encontró oferta similar disponible para agregar")
    except Exception as e:
        debug_screenshot(page, "buscador_checkout_ofertas")
        print(f"   ❌ Error buscando oferta similar: {e}")

    # 4) Refrescar, re-ingresar CUV y agregar con botón "Agregar" del buscador
    print("\n🔄 Refrescando página para agregar producto directo...")
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    cerrar_popups(page)

    print(f"🔍 Re-ingresando CUV: {CUV_CHECKOUT}...")
    buscador2 = page.locator("input.txtCuvConsultaDesktop")
    buscador2.wait_for(state="visible", timeout=10000)
    buscador2.scroll_into_view_if_needed(timeout=3000)
    page.wait_for_timeout(1000)
    buscador2.click()
    buscador2.type(CUV_CHECKOUT, delay=150)
    page.wait_for_timeout(4000)
    print("   ✅ CUV ingresado, esperando producto...")

    try:
        btn_agregar = page.locator("input#btnAgregarDePedido")
        btn_agregar.wait_for(state="visible", timeout=10000)
        btn_agregar.scroll_into_view_if_needed(timeout=3000)
        texto = btn_agregar.get_attribute("value") or "Agregar"
        print(f"   ✅ Botón '{texto}' encontrado → click")
        btn_agregar.click()
        page.wait_for_timeout(3000)
        cerrar_popups(page)
        print("   ✅ Producto agregado directo desde buscador de checkout")
    except Exception as e:
        debug_screenshot(page, "buscador_checkout_agregar")
        print(f"   ❌ Error agregando producto directo: {e}")


# ── Registro de flujos disponibles ────────────────────────────────────
FLUJOS = {
    "1": flujo_1_esika,
    "2": flujo_2_categorias,
    "3": flujo_3_carrusel_gana,
    "4": flujo_4_pedido,
    "5": flujo_5_buscador_checkout,
}


# ══════════════════════════════════════════════════════════════════════
# Guardado de eventos GA4
# ══════════════════════════════════════════════════════════════════════
def guardar_eventos(acumulado: list, output_file: str = "eventos_analytics.json") -> None:
    final_events = []
    for ev in acumulado:
        evp = {}
        evp.update(ev["parameters"])
        evp["currency"]           = ev["currency"]
        evp["items"]              = ev["items"]
        evp["timestamp"]          = ev["timestamp"]
        evp["timestamp_readable"] = ev["timestamp_readable"]
        evp["flow"]               = ev["flow"]
        final_events.append({
            "event":      "ga4.trackEvent",
            "eventName":  ev["name"],
            "eventParams": evp
        })

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_events, f, indent=2, ensure_ascii=False)

    print(f"\n✅ {len(final_events)} eventos guardados en {output_file}")


# ══════════════════════════════════════════════════════════════════════
# Punto de entrada
# ══════════════════���═══════════════════════════════════════════════════
def run(flujos_a_ejecutar: list, mobile: bool = False) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)

        if mobile:
            device = p.devices["iPhone 13"]
            context = browser.new_context(**device)
            print("📱 Modo mobile: iPhone 13")
        else:
            context = browser.new_context()

        page = context.new_page()
        acumulado = []

        def handle_request(req):
            if "collect" in req.url and req.method == "POST":
                data = req.post_data
                if data:
                    nuevos = parse_ga4_post_data(data)
                    suffix = "_mobile" if mobile else ""
                    for ev in nuevos:
                        ev["flow"] = (current_flow or "sin_flow") + suffix
                    acumulado.extend(nuevos)

        page.on("request", handle_request)
        registrar_handler_popups(page)
        login(page)

        for key in flujos_a_ejecutar:
            FLUJOS[key](page)

        output_file = "eventos_analytics_mobile.json" if mobile else "eventos_analytics.json"
        guardar_eventos(acumulado, output_file)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot de automatización Belcorp – GA4")
    parser.add_argument(
        "--flujo", "-f",
        nargs="+",
        choices=FLUJOS.keys(),
        metavar="N",
        help="Flujo(s) a ejecutar: 1, 2, 3, 4, 5 (por defecto: todos)"
    )
    parser.add_argument(
        "--mobile", "-m",
        action="store_true",
        help="Ejecutar en modo mobile (emula iPhone 13)"
    )
    args = parser.parse_args()

    seleccionados = args.flujo if args.flujo else list(FLUJOS.keys())
    modo = "mobile" if args.mobile else "desktop"
    print(f"▶️  Ejecutando flujo(s): {', '.join(seleccionados)} [{modo}]")
    run(seleccionados, mobile=args.mobile)
