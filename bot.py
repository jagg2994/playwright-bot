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
from tools.page_mapper import map_and_diagnose

load_dotenv()

# ── Configuración desde config.json ────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as _f:
    CONFIG = json.load(_f)

BASE_URL = CONFIG["base_url"]

# Selector de artículos en PLP — soporta entorno antiguo y nuevo
PLP_ARTICLE = "#FichasProductosBuscador article, article[data-card-cuv]"


class SinProductosError(Exception):
    """Sección sin productos disponibles en este entorno/campaña."""
    pass


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


def debug_completo(page, nombre: str) -> dict:
    """
    Screenshot + Page Mapper. Usa esto en except blocks para diagnóstico completo.
    """
    debug_screenshot(page, nombre)
    try:
        return map_and_diagnose(page, context=nombre)
    except Exception:
        print("   ⚠️  Page mapper falló")
        return {}


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
FLOW_SEARCH_PLP        = "search_plp_flow"
FLOW_MINI_BUSCADOR     = "mini_buscador_flow"
FLOW_LIQUIDACION       = "liquidacion_plp_flow"
FLOW_FESTIVALES_PLP    = "festivales_plp_flow"
FLOW_FESTIVALES_CARRUSEL = "festivales_carrusel_flow"
FLOW_CARRUSEL_HOME       = "carrusel_home_flow"

# ── Configuración de inputs (desde config.json, con fallback a env vars) ──
CUV_CHECKOUT = os.getenv("BELCORP_CUV", CONFIG["inputs"]["cuv_checkout"])
SEARCH_TERM = os.getenv("BELCORP_SEARCH", CONFIG["inputs"]["search_term"])
MINI_SEARCH_TERM = os.getenv("BELCORP_MINI_SEARCH", CONFIG["inputs"]["mini_search_term"])

# ── Selectores de botones de cierre de popup (orden de prioridad) ──────
SELECTORES_POPUP = [
    # Botones close genéricos (clase/atributo)
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
    # Textos de dismiss en el nuevo portal
    "button:has-text('Entendido')",
    "button:has-text('Entiendo')",
    "button:has-text('Aceptar')",
    "button:has-text('Si, acepto')",
    "button:has-text('No, gracias')",
    "button:has-text('Mantengo mis ofertas')",
    "button:has-text('No, mantener')",
    "a:has-text('CERRAR')",
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
def verificar_sesion(page) -> bool:
    """Detecta si la sesión expiró (redirigido a login). Si sí, re-loguea."""
    try:
        # Si el formulario de login es visible, la sesión expiró
        btn_login = page.locator("#btnLogin")
        if btn_login.count() and btn_login.is_visible(timeout=1000):
            print("   ⚠️  Sesión expirada — re-logueando...")
            login(page)
            return True
    except Exception:
        pass
    return False


def login(page) -> None:
    """Navega a la home, rellena credenciales y espera a que cargue el menú principal."""
    print("➡️  Login...")
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1000)

    # Seleccionar país
    pais = os.getenv(CONFIG["credentials"]["country_env"], "")
    if pais:
        page.select_option("#ddlPais", value=pais)
        page.wait_for_timeout(500)
        print(f"   🌎 País seleccionado: {pais}")

    page.fill("#txtUsuario", os.getenv(CONFIG["credentials"]["user_env"]))
    page.fill("#txtContrasenia", os.getenv(CONFIG["credentials"]["pass_env"]))
    page.click("#btnLogin")
    # Esperar a que cargue la home post-login
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)
    print("✅ Login OK")


# ══════════════════════════════════════════════════════════════════════
# Manejo de popups
# ══════════════════════════════════════════════════════════════════════
def cerrar_popups(page, max_rondas=4) -> None:
    """
    Cierra todos los popups/modals visibles en rondas hasta que no quede ninguno.
    Útil tras una navegación donde aparecen múltiples modals en cascada.
    """
    for _ in range(max_rondas):
        cerrado_algo = False
        for selector in SELECTORES_POPUP:
            try:
                btn = page.locator(selector).first
                if btn.count() and btn.is_visible(timeout=200):
                    btn.click()
                    print(f"   🚫 Popup cerrado ({selector.split(':')[-1][:30]})")
                    page.wait_for_timeout(500)
                    cerrado_algo = True
                    break  # Reiniciar la ronda después de cada cierre
            except Exception:
                continue
        if not cerrado_algo:
            break  # No más popups visibles


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


def abrir_buscador_header(page):
    """Abre y retorna el input de búsqueda del header (desktop y mobile)."""
    buscador = page.locator("input[placeholder='Buscar ofertas']").first
    try:
        buscador.wait_for(state="visible", timeout=5000)
    except Exception:
        # Intentar con placeholders alternativos
        for placeholder in ["Buscar ofertas", "Buscar", "buscar"]:
            alt = page.locator(f"input[placeholder*='{placeholder}']").first
            try:
                alt.wait_for(state="visible", timeout=2000)
                return alt
            except Exception:
                continue
        # Mobile: puede requerir click en ícono de búsqueda para mostrar el campo
        icono = page.locator("a.search-icon, button.search-icon, [class*='search-icon'], [class*='search'] svg, [aria-label*='Buscar']").first
        if icono.count() and icono.is_visible():
            icono.click()
            page.wait_for_timeout(1500)
        buscador = page.locator("input[placeholder*='uscar']").first
        buscador.wait_for(state="visible", timeout=10000)
    return buscador


def _navegar_via_link(page, keywords, url_fallback=None):
    """
    Busca en el DOM un link que coincida con alguna keyword (en href, aria-label o texto),
    extrae su href y navega directamente. Robusto ante cambios de entorno.
    Retorna el href navegado, o None si falló.
    """
    href = page.evaluate("""(keywords) => {
        const kws = keywords.map(k => k.toLowerCase());
        const links = document.querySelectorAll('a[href]');
        // Primero links visibles
        for (const a of links) {
            if (a.offsetParent === null || !a.href) continue;
            const text  = (a.textContent || '').trim().toLowerCase();
            const label = (a.getAttribute('aria-label') || '').toLowerCase();
            const href  = (a.href || '').toLowerCase();
            if (kws.some(k => text.includes(k) || label.includes(k) || href.includes(k)))
                return a.href;
        }
        // Fallback: cualquier link aunque no visible
        for (const a of links) {
            if (!a.href) continue;
            const text  = (a.textContent || '').trim().toLowerCase();
            const label = (a.getAttribute('aria-label') || '').toLowerCase();
            const href  = (a.href || '').toLowerCase();
            if (kws.some(k => text.includes(k) || label.includes(k) || href.includes(k)))
                return a.href;
        }
        return null;
    }""", keywords)

    def _goto(url):
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2500)
        verificar_sesion(page)

    if href:
        _goto(href)
        return href
    elif url_fallback:
        _goto(url_fallback)
        return url_fallback
    return None


def ir_a_pedido(page) -> None:
    """Navega directamente a la sección de Pedido (checkout) y espera los carruseles."""
    print("➡️  Ir a Pedido...")
    page.goto(f"{BASE_URL}/Pedido")
    page.wait_for_selector("div.contenedor_carrusel.slick-slider[data-seccion-productos]", timeout=15000)
    print("✅ En Pedido")


def ir_a_gana(page) -> None:
    """
    Hace clic en el ítem 'Gana+' del menú principal.
    En mobile abre primero el menú hamburguesa si el ítem no es visible.
    """
    print("➡️  Ir a Gana+...")
    # Obtener href de Gana+ via JS (evita strict mode con múltiples matches)
    href = page.evaluate("""
        () => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                if (a.textContent.trim().includes('Gana+') && a.href && a.offsetParent !== null) {
                    return a.href;
                }
            }
            // Fallback: cualquier link con Gana+ aunque no visible
            for (const a of links) {
                if (a.textContent.trim().includes('Gana+') && a.href) {
                    return a.href;
                }
            }
            return null;
        }
    """)
    if href:
        page.goto(href)
        print(f"   ✅ Navegando a Gana+: {href}")
    else:
        page.goto(f"{BASE_URL}/Mobile/Ofertas")
        print("   ✅ Navegando a Gana+ via URL directa")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    print("✅ En Gana+")


def click_categoria_esika(page) -> None:
    """Selecciona el filtro de marca Ésika y espera a que cargue la PLP."""
    print("➡️  Categoría Ésika...")
    page.wait_for_selector('li[data-codigo="mar-esika"]', timeout=10000)
    page.click('li[data-codigo="mar-esika"]')
    page.wait_for_selector(PLP_ARTICLE, timeout=10000)
    print("✅ PLP Ésika cargada")


def click_categorias(page) -> None:
    """Selecciona el filtro de categoría Fragancias y espera a que cargue la PLP."""
    print("➡️  Categoría Fragancias...")
    page.wait_for_selector('li[data-codigo="cat-fragancia"]', timeout=10000)
    page.click('li[data-codigo="cat-fragancia"]')
    page.wait_for_selector(PLP_ARTICLE, timeout=10000)
    print("✅ PLP Fragancias cargada")


# ══════════════════════════════════════════════════════════════════════
# Helper: detectar si un producto ya fue agregado
# ══════════════════════════════════════════════════════════════════════
def producto_ya_agregado(elemento, modo="plp"):
    """
    Detecta si un producto ya fue agregado al pedido.
    Modos:
      - 'plp':       article de PLP (query_selector) → div.caja_producto_agregado
      - 'locator':   Playwright locator (slide/card) → div.caja_producto_agregado
      - 'carrusel_home': slide de swiper → div.input-number en product-actions
      - 'festival':  tarjeta festival → texto "Elegido" / div.btn_elegido
    Retorna True si ya está agregado.
    """
    try:
        if modo == "plp":
            # query_selector (ElementHandle)
            caja = elemento.query_selector("div.caja_producto_agregado")
            return caja is not None and caja.is_visible()
        elif modo == "locator":
            caja = elemento.locator("div.caja_producto_agregado")
            return caja.count() > 0 and caja.is_visible()
        elif modo == "carrusel_home":
            ya = elemento.locator("div.product-actions div.input-number")
            return ya.count() > 0
        elif modo == "festival":
            elegido = elemento.locator("text=Elegido")
            btn_elegido = elemento.locator("div.btn_elegido")
            return (elegido.count() > 0) or (btn_elegido.count() > 0)
    except Exception:
        pass
    return False


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
        try:
            page.wait_for_selector(PLP_ARTICLE, timeout=10000)
        except Exception:
            # La nueva UI del portal no usa article[data-card-cuv]; intentar cerrar
            # modals y buscar productos por botón "Agregar" directamente
            cerrar_popups(page)
            page.wait_for_timeout(1500)
            agregado = page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, a'));
                for (const b of btns) {
                    if ((b.innerText || '').trim().toLowerCase() === 'agregar'
                        && b.offsetParent !== null) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")
            if agregado:
                print("   ✅ Producto agregado via búsqueda JS directa (nueva UI)")
                page.wait_for_timeout(2000)
                return 1
            raise SinProductosError("Sección sin productos visibles en este entorno/campaña")

        productos = page.query_selector_all(PLP_ARTICLE)
        for idx, prod in enumerate(productos, 1):
            if producto_ya_agregado(prod, "plp"):
                print(f"   ⏭️  Producto {idx} ya fue agregado → skip")
                continue
            texto = _btn_texto(prod)
            if texto and texto.lower() == "agregar":
                print(f"   ✅ Producto {idx} → clic en 'Agregar'")
                btn = prod.query_selector("a#btnAgregalo, button#btnAgregalo, [class*='btnAgregar']")
                if btn:
                    btn.click()
                else:
                    page.evaluate("(el) => { const b = el.querySelector('[id*=btnAgregalo],[class*=btnAgregar]'); if(b) b.click(); }", prod)
                page.wait_for_timeout(2000)
                return idx
        print("   ❌ No se encontró producto con botón 'Agregar' en PLP")
    except Exception as e:
        debug_completo(page, "plp_agregar_directo")
        print(f"   ❌ Error en plp_agregar_directo: {e}")
    return None


# ══════════════════════════════════════════════════════════════════════
# PLP – Ir a PDP (el botón dice CUALQUIER COSA distinta a "Agregar")
# ══════════════════════════════════════════════════════════════════════
def plp_ir_a_pdp(page, skip_index=None):
    """
    Recorre la PLP y hace clic en el primer a#btnAgregalo cuyo texto
    NO sea "Agregar" (p.ej. "Ver detalle"). Ese clic navega a la PDP.
    Fallback: si todos dicen "Agregar", hace click en la imagen del producto
    (skip el ya agregado) para ir a PDP.
    Retorna el índice clickeado o None.
    """
    print("🔗 PLP → buscando producto para ir a PDP...")
    try:
        page.wait_for_selector(PLP_ARTICLE, timeout=10000)
        productos = page.query_selector_all(PLP_ARTICLE)

        # Empezar desde después del producto ya agregado
        start = skip_index if skip_index else 0
        for idx, prod in enumerate(productos, 1):
            if idx <= start:
                continue
            btn = prod.query_selector("a#btnAgregalo")
            if not btn:
                continue
            texto_btn = (btn.inner_text() or "").strip()
            if texto_btn.lower() != "agregar":
                print(f"   ⏭️  Producto {idx}: '{texto_btn}' → skip")
                continue
            # Producto con "Agregar" → intentar hover, luego fallback click en imagen
            art = page.locator(PLP_ARTICLE).nth(idx - 1)
            img = art.locator("img").first
            if img.count():
                img.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)
                img.hover()
                page.wait_for_timeout(1000)
            ver_detalle = art.locator("text=Ver detalle").first
            if ver_detalle.count() and ver_detalle.is_visible():
                print(f"   ✅ Producto {idx} → hover → 'Ver detalle' → PDP")
                ver_detalle.click()
                page.wait_for_timeout(3000)
                return idx
            # Fallback mobile: click directo en la imagen para ir a PDP
            link_img = art.locator("a.link_imagen, a:has(img)").first
            if link_img.count():
                href = link_img.get_attribute("href") or ""
                if href and not href.startswith("javascript"):
                    print(f"   ✅ Producto {idx} → click imagen → PDP ({href[:50]})")
                    link_img.click()
                    page.wait_for_timeout(3000)
                    return idx
            # Fallback: click en la imagen directamente
            if img.count():
                print(f"   ✅ Producto {idx} → click directo en img → PDP")
                img.click()
                page.wait_for_timeout(3000)
                return idx
            print(f"   ⏭️  Producto {idx}: no se pudo navegar a PDP → skip")

        print("   ❌ No se encontró producto para ir a PDP")
    except Exception as e:
        debug_completo(page, "plp_ir_a_pdp")
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
def map_pdp(page):
    """
    Mapea el estado actual de la PDP y retorna un dict de decisión.

    Tipos:
      ya_agregado     — producto ya en el pedido, nada que hacer
      simple          — click directo en Agregar
      seleccion_multi — requiere elegir opciones (tono, arma tu oferta)
      cantidad_minima — requiere alcanzar una cantidad mínima antes de agregar
      cantidad_variable — tiene controles +/- pero sin mínimo obligatorio
      agotado         — sin stock
      sin_boton       — no hay botón principal visible
    """
    return page.evaluate("""
        () => {
            // ── Botón principal ─────────────────────────────────────────
            const btn = document.querySelector(
                'a#btnAgregalo, button#btnAgregalo, a.btn_validar_alertas, button.btn_validar_alertas'
            );

            // ── Ya agregado ──────────────────────────────────────────────
            const cajaAgregado = document.querySelector('div.caja_producto_agregado');
            if (cajaAgregado && cajaAgregado.offsetParent !== null)
                return {tipo: 'ya_agregado', puede_agregar: false};

            if (!btn) return {tipo: 'sin_boton', puede_agregar: false};

            const texto  = (btn.innerText || '').trim();
            const disabled = btn.classList.contains('btn_deshabilitado_ficha')
                          || btn.classList.contains('disabled')
                          || btn.hasAttribute('disabled');

            // ── Selecciones obligatorias (tono, arma tu oferta) ─────────
            const selecciones = document.querySelectorAll('button[btn-show-types-tones-modal]');
            if (selecciones.length > 0)
                return {tipo: 'seleccion_multi', puede_agregar: true,
                        texto: texto, selecciones: selecciones.length};

            // ── Controles de cantidad (+/-) ──────────────────────────────
            const masBtn   = document.querySelector('.mas_rangos:not([disabled])');
            const menosBtn = document.querySelector('.menos_rangos:not([disabled])');
            const tieneControles = !!(masBtn || menosBtn);

            // Valor actual de cantidad
            const inputCantidad = document.querySelector(
                'input#txtCantidad, input.txt_cantidad_pedido_new, input[name*="Cantidad"]'
            );
            const cantidadActual = inputCantidad ? (parseInt(inputCantidad.value) || 1) : 1;

            // Detectar mínimo requerido desde textos visibles
            let cantidadMinima = 0;
            const bodyText = document.body.innerText || '';
            const mPatterns = [
                /m[íi]nimo[:\\s]+([0-9]+)/i,
                /([0-9]+)\\s+und(?:\\.|idades?)?\\s+m[íi]nimo/i,
                /m[íi]nimo\\s+de\\s+([0-9]+)/i,
                /compra\\s+m[íi]nima[:\\s]+([0-9]+)/i
            ];
            for (const pat of mPatterns) {
                const m = bodyText.match(pat);
                if (m) { cantidadMinima = parseInt(m[1]); break; }
            }

            if (tieneControles && cantidadMinima > 1)
                return {tipo: 'cantidad_minima', puede_agregar: true, texto: texto,
                        cantidad_minima: cantidadMinima, cantidad_actual: cantidadActual};

            if (tieneControles)
                return {tipo: 'cantidad_variable', puede_agregar: true, texto: texto,
                        cantidad_actual: cantidadActual};

            // ── Ya agregado (botón deshabilitado sin contexto de selección) ─
            if (disabled)
                return {tipo: 'ya_agregado', puede_agregar: false, texto: texto};

            // ── Simple ───────────────────────────────────────────────────
            return {tipo: 'simple', puede_agregar: true, texto: texto};
        }
    """)


# Alias de compatibilidad para código legacy
def _detectar_tipo_pdp(page):
    return map_pdp(page)


def _pdp_completar_selecciones(page):
    """Completa selecciones obligatorias (tonos, arma tu oferta, etc.)."""
    selection_btns = page.locator(
        'button.tono_select_opt[btn-show-types-tones-modal], button[btn-show-types-tones-modal]'
    )
    total_selecciones = selection_btns.count()
    if total_selecciones == 0:
        return True

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
            # Intentar cerrar modal si quedó abierto
            page.evaluate("() => { const m = document.querySelector('.modal.show, .modal.in'); if (m) m.style.display = 'none'; }")
            continue

        # Leer la cantidad requerida desde el título del modal
        requeridos = 1
        try:
            titulo = page.locator("h3[header-title]")
            if titulo.count():
                texto_titulo = titulo.first.inner_text().strip()
                match = re.search(r'\d+', texto_titulo)
                if match:
                    requeridos = int(match.group())
                    print(f"      📌 '{texto_titulo}' → seleccionar {requeridos}")
        except Exception:
            pass

        # Clickear opciones no seleccionadas
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
            try:
                clase_btn = page.locator("button#btn-aplicar-seleccion").first.get_attribute("class") or ""
                print(f"      ✔️  Opción {seleccionados}/{requeridos} seleccionada → btn class: '{clase_btn}'")
            except Exception:
                print(f"      ✔️  Opción {seleccionados}/{requeridos} seleccionada")

        # Confirmar via JS (evita que locator handlers reseteen el botón)
        clicked = page.evaluate("""
            () => {
                const btn = document.querySelector('button#btn-aplicar-seleccion.active');
                if (btn) { btn.click(); return true; }
                // Fallback: click aunque no tenga .active
                const btn2 = document.querySelector('button#btn-aplicar-seleccion');
                if (btn2 && !btn2.classList.contains('btn_deshabilitado_ficha')) { btn2.click(); return true; }
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

    return True


def _pdp_incrementar_cantidad(page, cantidad_objetivo, cantidad_actual=1):
    """Incrementa la cantidad al objetivo usando el botón + (.mas_rangos)."""
    clicks = max(0, cantidad_objetivo - cantidad_actual)
    if clicks == 0:
        return
    print(f"   📦 Incrementando cantidad: {cantidad_actual} → {cantidad_objetivo} ({clicks} clicks)")
    for _ in range(clicks):
        page.evaluate("""
            () => {
                const btn = document.querySelector('.mas_rangos:not([disabled])');
                if (btn) btn.click();
            }
        """)
        page.wait_for_timeout(300)
    page.wait_for_timeout(500)


def _pdp_click_agregar(page):
    """Click en botón principal Agregar de la PDP. Retorna True si ok."""
    page.wait_for_timeout(1000)
    resultado = page.evaluate("""
        () => {
            // Buscar botón principal con múltiples selectores
            const selectores = [
                'a#btnAgregalo.btn_validar_alertas',
                'a#btnAgregalo',
                'button#btnAgregalo',
                'a.btn_validar_alertas',
                'button.btn_validar_alertas'
            ];
            let btn = null;
            for (const sel of selectores) {
                btn = document.querySelector(sel);
                if (btn && btn.offsetParent !== null) break;
                btn = null;
            }
            if (!btn) return {ok: false, error: 'no encontrado'};
            btn.scrollIntoView({block: 'center'});
            const texto = (btn.innerText || '').trim();
            const deshabilitado = btn.classList.contains('btn_deshabilitado_ficha')
                               || btn.classList.contains('disabled')
                               || btn.hasAttribute('disabled');
            if (deshabilitado) return {ok: false, error: 'deshabilitado', texto: texto};
            btn.click();
            return {ok: true, texto: texto};
        }
    """)
    return resultado


def pdp_agregar(page):
    """
    Agrega el producto desde la PDP actual usando map_pdp() para decidir cómo actuar.

    Tipos manejados:
      ya_agregado      → skip (retorna False)
      sin_boton        → skip (retorna False)
      simple           → click directo en Agregar
      seleccion_multi  → completar selecciones, luego Agregar
      cantidad_minima  → incrementar cantidad al mínimo, luego Agregar
      cantidad_variable → click directo (cantidad por defecto es válida)
    """
    print("🛍️  PDP → agregando al carrito...")
    try:
        mapa = map_pdp(page)
        tipo = mapa.get("tipo", "sin_boton")
        print(f"   🔍 Tipo: {tipo} — '{mapa.get('texto', '')}'")

        # No hay nada que hacer
        if tipo in ("ya_agregado", "sin_boton"):
            print(f"   ⏭️  {tipo} → skip")
            return False

        # Completar selecciones obligatorias
        if tipo == "seleccion_multi":
            _pdp_completar_selecciones(page)

        # Incrementar cantidad al mínimo requerido
        elif tipo == "cantidad_minima":
            _pdp_incrementar_cantidad(
                page,
                mapa.get("cantidad_minima", 1),
                mapa.get("cantidad_actual", 1)
            )

        # Intentar click en botón principal
        resultado = _pdp_click_agregar(page)
        if resultado.get("ok"):
            print(f"   Botón PDP: '{resultado.get('texto', '')}'")
            page.wait_for_timeout(3500)
            _cerrar_alerta_general(page)
            print("   ✅ Agregado desde PDP")
            return True
        else:
            # Si falla, re-mapear y loguear el estado actual para diagnóstico
            mapa_post = map_pdp(page)
            print(f"   ⚠️  No se pudo agregar — estado post: {mapa_post.get('tipo')} | {resultado.get('error', '')}")
            return False

    except Exception as e:
        debug_completo(page, "pdp_agregar")
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

            if producto_ya_agregado(slide, "locator"):
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
        debug_completo(page, "ofertas_ir_a_pdp")
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

    # Refrescar para que el DOM refleje el producto ya agregado
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    cerrar_popups(page)

    idx_pdp = plp_ir_a_pdp(page, skip_index=idx)
    if idx_pdp:
        cerrar_popups(page)
        pdp_agregar(page)
        page.go_back()
        page.wait_for_selector(PLP_ARTICLE, timeout=10000)


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

    # 1) Ingresar CUV en el buscador (desktop o mobile)
    print(f"🔍 Ingresando CUV: {CUV_CHECKOUT}...")
    page.wait_for_timeout(2000)
    # Cerrar loading overlay si existe
    page.evaluate("""
        () => {
            document.querySelectorAll('.ui-widget-overlay, .loadingScreenWindow').forEach(el => {
                el.style.display = 'none';
            });
        }
    """)
    page.wait_for_timeout(1000)
    buscador = page.locator("input.txtCuvConsultaDesktop")
    try:
        buscador.wait_for(state="visible", timeout=5000)
    except Exception:
        # Mobile: usar input mobile
        buscador = page.locator("input.txtCuvConsultaMobile")
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
        debug_completo(page, "buscador_checkout_ofertas")
        print(f"   ❌ Error buscando oferta similar: {e}")

    # 4) Refrescar, re-ingresar CUV y agregar con botón "Agregar" del buscador
    print("\n🔄 Refrescando página para agregar producto directo...")
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    cerrar_popups(page)

    print(f"🔍 Re-ingresando CUV: {CUV_CHECKOUT}...")
    buscador2 = page.locator("input.txtCuvConsultaDesktop")
    try:
        buscador2.wait_for(state="visible", timeout=5000)
    except Exception:
        buscador2 = page.locator("input.txtCuvConsultaMobile")
        buscador2.wait_for(state="visible", timeout=10000)
    buscador2.scroll_into_view_if_needed(timeout=3000)
    page.wait_for_timeout(1000)
    buscador2.click()
    buscador2.type(CUV_CHECKOUT, delay=150)
    page.wait_for_timeout(4000)
    print("   ✅ CUV ingresado, esperando producto...")

    try:
        btn_agregar = page.locator("input#btnAgregarDePedido")
        try:
            btn_agregar.wait_for(state="visible", timeout=10000)
            btn_agregar.scroll_into_view_if_needed(timeout=3000)
            texto = btn_agregar.get_attribute("value") or "Agregar"
            print(f"   ✅ Botón '{texto}' encontrado → click")
            btn_agregar.click()
        except Exception:
            # Mobile: botón puede estar oculto — JS click directo
            print("   ⚠️ Botón no visible, intentando JS click...")
            resultado = page.evaluate("""
                () => {
                    const btn = document.querySelector('input#btnAgregarDePedido');
                    if (!btn) {
                        // Buscar alternativa mobile
                        const alt = document.querySelector('a.btn_producto_recomendado_agregalo, button[class*="agregar"], input[type="button"][value*="Agregar"]');
                        if (alt) { alt.click(); return {ok: true, alt: true}; }
                        return {ok: false};
                    }
                    btn.click();
                    return {ok: true, alt: false};
                }
            """)
            if resultado.get("ok"):
                print(f"   ✅ Producto agregado via JS click {'(alternativo)' if resultado.get('alt') else ''}")
            else:
                raise Exception("No se encontró botón agregar ni alternativa")
        page.wait_for_timeout(3000)
        cerrar_popups(page)
        print("   ✅ Producto agregado directo desde buscador de checkout")
    except Exception as e:
        debug_screenshot(page, "buscador_checkout_agregar")
        print(f"   ❌ Error agregando producto directo: {e}")


def flujo_6_search_plp(page) -> None:
    """
    Flujo 6 · Buscador (search PLP).
    Busca un término en el buscador del header, click en "VER MÁS RESULTADOS"
    para ir a la PLP de búsqueda, luego agregar directo + ir a PDP.
    """
    def navegar_search(p):
        print(f"🔍 Buscando '{SEARCH_TERM}' desde el header...")
        p.goto(f"{BASE_URL}/")
        p.wait_for_load_state("domcontentloaded")
        p.wait_for_timeout(2000)
        cerrar_popups(p)

        # Escribir en el buscador del header
        buscador = abrir_buscador_header(p)
        buscador.click()
        buscador.type(SEARCH_TERM, delay=150)
        p.wait_for_timeout(3000)

        # Click en "VER MÁS RESULTADOS"
        ver_mas = p.locator("a.search-modal-more-results")
        try:
            ver_mas.wait_for(state="visible", timeout=10000)
            print(f"   ✅ Click en 'VER MÁS RESULTADOS' → PLP de búsqueda")
            ver_mas.click()
        except Exception:
            # Mobile fallback: buscar cualquier link de "ver más" o presionar Enter
            ver_mas_alt = p.locator("text=VER MÁS RESULTADOS, text=Ver más resultados, a:has-text('resultado')").first
            if ver_mas_alt.count() and ver_mas_alt.is_visible():
                ver_mas_alt.click()
            else:
                print("   ⚠️ 'VER MÁS RESULTADOS' no visible, presionando Enter...")
                buscador.press("Enter")
        p.wait_for_timeout(3000)

    ejecutar_flujo_plp(page, FLOW_SEARCH_PLP, f"Buscador – '{SEARCH_TERM}' (search PLP)", navegar_search)


def flujo_7_mini_buscador(page) -> None:
    """
    Flujo 7 · Mini buscador.
    Busca un término en el buscador del header, agrega directo desde el modal
    de resultados, luego entra a PDP de otro producto y agrega desde ahí.
    """
    print("\n" + "═"*50)
    print(f"FLUJO 7: Mini buscador – '{MINI_SEARCH_TERM}'")
    print("═"*50)
    set_flow(FLOW_MINI_BUSCADOR)

    # 1) Ir al home y buscar
    print(f"🔍 Buscando '{MINI_SEARCH_TERM}' desde el header...")
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    cerrar_popups(page)

    buscador = abrir_buscador_header(page)
    buscador.click()
    buscador.type(MINI_SEARCH_TERM, delay=150)
    page.wait_for_timeout(3000)

    # 2) Agregar directo desde el modal de resultados
    print("🛒 Mini buscador → buscando producto con botón 'Agregar'...")
    modal_mode = True
    try:
        cards = page.locator("div.product-searched-container")
        cards.first.wait_for(state="visible", timeout=5000)
        agregado_idx = None

        for i in range(cards.count()):
            card = cards.nth(i)
            btn = card.locator("button.search-add-product")
            if btn.count() and btn.is_visible():
                texto = btn.inner_text().strip()
                if texto.lower() == "agregar":
                    print(f"   ✅ Producto {i+1} → '{texto}' → click")
                    btn.click()
                    page.wait_for_timeout(3000)
                    cerrar_popups(page)
                    print("   ✅ Agregado desde mini buscador")
                    agregado_idx = i
                    break

        if agregado_idx is None:
            print("   ⚠️  No se encontró producto con botón 'Agregar'")

    except Exception:
        # Mobile: mini buscador redirige a /buscador (página completa) en vez de modal
        modal_mode = False
        print("   ℹ️  Modal no disponible (mobile) — usando página de búsqueda")
        try:
            # Mobile /buscador usa a#btnAgregalo o div.seccion_agregar directamente
            btn = page.locator("a#btnAgregalo, div.seccion_agregar")
            btn.first.wait_for(state="visible", timeout=10000)
            texto_btn = btn.first.inner_text().strip()
            if texto_btn.lower() == "agregar":
                btn.first.scroll_into_view_if_needed(timeout=3000)
                btn.first.click()
                page.wait_for_timeout(3000)
                cerrar_popups(page)
                print(f"   ✅ Producto agregado → '{texto_btn}' (página búsqueda mobile)")
        except Exception as e2:
            debug_completo(page, "mini_buscador_agregar")
            print(f"   ❌ Error agregando desde mini buscador: {e2}")

    # 3) Refrescar, volver a buscar y entrar a PDP de un producto no agregado
    print("\n🔄 Refrescando para buscar producto e ir a PDP...")
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    cerrar_popups(page)

    buscador2 = abrir_buscador_header(page)
    buscador2.click()
    buscador2.type(MINI_SEARCH_TERM, delay=150)
    page.wait_for_timeout(3000)

    print("🔗 Mini buscador → buscando producto no agregado para ir a PDP...")
    try:
        if modal_mode:
            # Desktop: usar modal con product-searched-container
            cards = page.locator("div.product-searched-container")
            cards.first.wait_for(state="visible", timeout=10000)

            for i in range(cards.count()):
                card = cards.nth(i)
                btn = card.locator("button.search-add-product")
                if not (btn.count() and btn.is_visible()):
                    continue
                texto = btn.inner_text().strip()
                if texto.lower() != "agregar":
                    continue
                link_pdp = card.locator("a.image-button-detail-link")
                if link_pdp.count():
                    href = link_pdp.get_attribute("href")
                    if href:
                        print(f"   ✅ Producto {i+1} → navegando a PDP: {href}")
                        page.goto(f"{BASE_URL}{href}")
                        page.wait_for_load_state("domcontentloaded")
                        page.wait_for_timeout(2000)
                        cerrar_popups(page)
                        pdp_agregar(page)
                        break
            else:
                print("   ⚠️  No se encontró producto disponible para ir a PDP")
        else:
            # Mobile: redirige a /buscador — click "VER MÁS RESULTADOS" para ir a PLP estándar
            ver_mas = page.locator("a#BotonVerTodosResultados")
            try:
                ver_mas.wait_for(state="visible", timeout=5000)
                ver_mas.click()
                page.wait_for_timeout(3000)
                print("   ✅ Click 'VER MÁS RESULTADOS' → PLP")
            except Exception:
                pass
            # Intentar usar PLP estándar
            try:
                page.wait_for_selector(PLP_ARTICLE, timeout=10000)
                pdp_idx = plp_ir_a_pdp(page)
                if pdp_idx:
                    pdp_agregar(page)
                else:
                    print("   ⚠️  No se encontró producto para ir a PDP")
            except Exception:
                # Fallback: buscar link a ficha directamente
                link = page.locator("a[href*='/ficha/']").first
                if link.count():
                    href = link.get_attribute("href")
                    full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                    page.goto(full_url)
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(2000)
                    cerrar_popups(page)
                    print(f"   ✅ Navegando a PDP via link directo")
                    pdp_agregar(page)
                else:
                    print("   ⚠️  No se encontró producto para ir a PDP")

    except Exception as e:
        debug_completo(page, "mini_buscador_pdp")
        print(f"   ❌ Error navegando a PDP desde mini buscador: {e}")


def flujo_8_liquidacion(page) -> None:
    """
    Flujo 8 · Liquidación PLP.
    Navega a Liquidaciones desde el home, agrega directo + ir a PDP.
    """
    def navegar_liquidacion(p):
        print("➡️  Ir a Liquidaciones...")
        p.goto(f"{BASE_URL}/")
        p.wait_for_load_state("domcontentloaded")
        p.wait_for_timeout(2000)
        verificar_sesion(p)
        cerrar_popups(p)
        href = _navegar_via_link(p, ["liquidacion", "liquidación", "liquidaciones"],
                                 f"{BASE_URL.rstrip('/')}/liquidacion")
        p.wait_for_timeout(1500)
        cerrar_popups(p)
        print(f"✅ En Liquidaciones ({href})")

    ejecutar_flujo_plp(page, FLOW_LIQUIDACION, "Liquidación PLP", navegar_liquidacion)


def flujo_9_festivales_plp(page) -> None:
    """
    Flujo 9 · Festivales PLP.
    Navega a Festival desde el home, agrega directo + ir a PDP.
    """
    def navegar_festivales(p):
        print("➡️  Ir a Festivales...")
        p.goto(f"{BASE_URL}/")
        p.wait_for_load_state("domcontentloaded")
        p.wait_for_timeout(2000)
        verificar_sesion(p)
        cerrar_popups(p)
        href = _navegar_via_link(p, ["festival", "festivales"],
                                 f"{BASE_URL.rstrip('/')}/festivales")
        p.wait_for_timeout(1500)
        cerrar_popups(p)
        print(f"✅ En Festivales ({href})")

    ejecutar_flujo_plp(page, FLOW_FESTIVALES_PLP, "Festivales PLP", navegar_festivales)


def flujo_10_festivales_carrusel(page) -> None:
    """
    Flujo 10 · Carrusel de premios Festivales.
    Navega a Festival, busca el carrusel de premios y agrega uno disponible.
    """
    print("\n" + "═"*50)
    print("FLUJO 10: Festivales – Carrusel de premios")
    print("═"*50)
    set_flow(FLOW_FESTIVALES_CARRUSEL)

    print("➡️  Ir a Festivales desde el home...")
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    verificar_sesion(page)
    cerrar_popups(page)
    href = _navegar_via_link(page, ["festival", "festivales"],
                             f"{BASE_URL.rstrip('/')}/festivales")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    cerrar_popups(page)
    print(f"✅ En Festivales ({href})")

    # Buscar el carrusel de premios (está arriba de la PLP)
    print("🎁 Buscando carrusel de premios...")
    try:
        # Scroll arriba y esperar render completo
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(2000)

        # Scroll al contenedor padre para forzar render
        page.evaluate("""
            () => {
                const el = document.querySelector('.contenedor-landing-premio')
                         || document.querySelector('#contenedor-landing-premio-card');
                if (el) el.scrollIntoView({ block: 'center' });
            }
        """)
        page.wait_for_timeout(3000)

        # Debug: dump completo de clases dentro de las tarjetas
        debug_clases = page.evaluate("""
            () => {
                const tarjetas = document.querySelectorAll('.tarjeta.festival');
                return Array.from(tarjetas).map((t, i) => {
                    const divs = t.querySelectorAll('div');
                    const clases = Array.from(divs).map(d => d.className).filter(c => c);
                    return { tarjeta: i, total_divs: divs.length, clases: clases };
                });
            }
        """)
        for t in debug_clases:
            print(f"   🔍 Tarjeta {t['tarjeta']}: {t['total_divs']} divs")
            for c in t['clases']:
                print(f"      class=\"{c}\"")

        # Buscar botón con texto "Agregar" usando Playwright locator (no JS)
        result = None
        tarjetas = page.locator(".tarjeta.festival")
        total = tarjetas.count()
        print(f"   🔍 Tarjetas festival encontradas: {total}")

        for i in range(total):
            tarjeta = tarjetas.nth(i)
            # Buscar span con texto "Agregar" dentro de la tarjeta
            agregar_span = tarjeta.locator("span", has_text="Agregar")
            if agregar_span.count() > 0 and agregar_span.first.is_visible():
                # Click en el div padre del span
                agregar_span.first.scroll_into_view_if_needed(timeout=3000)
                agregar_span.first.click()
                result = {"action": "clicked", "texto": "Agregar"}
                print(f"   ✅ Click en 'Agregar' de tarjeta {i+1} via Playwright locator")
                break

            if producto_ya_agregado(tarjeta, "festival"):
                print(f"   ℹ️  Tarjeta {i+1} ya elegida")
                continue

        if not result:
            result = {"action": "all_elegidos", "total": total}

        if result.get("action") == "clicked":
            page.wait_for_timeout(3000)
            cerrar_popups(page)
            print(f"   ✅ Premio agregado desde carrusel de festivales ('{result['texto']}')")
        else:
            print(f"   ℹ️  Todos los premios ya fueron elegidos ({result.get('total')})")
    except Exception as e:
        debug_completo(page, "festivales_carrusel")
        print(f"   ❌ Error en carrusel de premios: {e}")

    # ── Parte 2: ir a PDP de otro premio disponible y agregar desde ahí ──
    print("\n🎁 Carrusel premios → ir a PDP de otro premio...")
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(1500)

        tarjetas = page.locator(".tarjeta.festival")
        total = tarjetas.count()
        pdp_ok = False

        for i in range(total):
            tarjeta = tarjetas.nth(i)
            if producto_ya_agregado(tarjeta, "festival"):
                print(f"   ℹ️  Tarjeta {i+1} ya elegida — saltar")
                continue

            agregar_span = tarjeta.locator("span", has_text="Agregar")
            if agregar_span.count() > 0 and agregar_span.first.is_visible():
                # Click en la zona redireccionarFicha para ir a PDP
                redir = tarjeta.locator("div.redireccionarFicha").first
                if redir.count():
                    redir.scroll_into_view_if_needed(timeout=3000)
                    redir.click()
                    page.wait_for_timeout(3000)
                    cerrar_popups(page)
                    print(f"   ✅ Navegando a PDP de premio tarjeta {i+1}")
                    pdp_ok = True
                    break

        if pdp_ok:
            pdp_agregar(page)
            page.go_back()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)
            cerrar_popups(page)
            print("   ✅ Regresó de PDP del premio")
        else:
            print("   ℹ️  No hay premios disponibles para ir a PDP")
    except Exception as e:
        debug_completo(page, "festivales_carrusel_pdp")
        print(f"   ❌ Error en PDP de premio: {e}")


def flujo_11_carrusel_home(page) -> None:
    """
    Flujo 11 · Carrusel "Las mejores ofertas" del home.
    Agrega un producto directo + ir a PDP de otro producto.
    """
    print("\n" + "═"*50)
    print("FLUJO 11: Carrusel de home – Las mejores ofertas")
    print("═"*50)
    set_flow(FLOW_CARRUSEL_HOME)

    print("➡️  Ir al home...")
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)
    cerrar_popups(page)

    # Scroll al carrusel "Las mejores ofertas"
    print("🛒 Buscando carrusel 'Las mejores ofertas'...")
    try:
        section = page.locator("section#offer-section")
        section.wait_for(state="attached", timeout=10000)
        section.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(2000)
        print("   ✅ Carrusel encontrado")
    except Exception as e:
        debug_completo(page, "carrusel_home")
        print(f"   ❌ No se encontró carrusel: {e}")
        return

    # ── Parte 1: agregar directo desde el carrusel ──
    print("\n🛒 Carrusel home → agregar producto directo...")
    agregado_idx = -1
    try:
        swiper = section.locator("div.swiper-wrapper").first
        slides = swiper.locator("> div")
        next_btn = section.locator("button[name='offer'].offer-swiper-button-next").first
        total = slides.count()
        print(f"   🔍 {total} slides encontrados")

        for i in range(min(total, 20)):
            slide = slides.nth(i)
            if producto_ya_agregado(slide, "carrusel_home"):
                continue

            btn_agregar = slide.locator("div.product-actions button span.pack-new-normal-text", has_text="Agregar")
            if btn_agregar.count() > 0:
                try:
                    btn_parent = slide.locator("div.product-actions button.solid.secondary").first
                    btn_parent.scroll_into_view_if_needed(timeout=3000)
                    btn_parent.click()
                    page.wait_for_timeout(2000)
                    cerrar_popups(page)
                    agregado_idx = i
                    print(f"   ✅ Producto slide {i+1} → 'Agregar' → click")
                    break
                except Exception:
                    pass

            # Navegar al siguiente slide si no encontramos
            try:
                if next_btn.is_visible():
                    next_btn.click()
                    page.wait_for_timeout(600)
            except Exception:
                break

        if agregado_idx < 0:
            print("   ⚠️  No se encontró producto disponible para agregar")
    except Exception as e:
        debug_completo(page, "carrusel_home_agregar")
        print(f"   ❌ Error agregando desde carrusel home: {e}")

    # ── Parte 2: ir a PDP de otro producto ──
    print("\n🔗 Carrusel home → ir a PDP de otro producto...")
    try:
        # Refrescar para actualizar estado
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)
        cerrar_popups(page)

        section = page.locator("section#offer-section")
        section.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(2000)

        swiper = section.locator("div.swiper-wrapper").first
        slides = swiper.locator("> div")
        next_btn = section.locator("button[name='offer'].offer-swiper-button-next").first
        total = slides.count()
        pdp_ok = False

        for i in range(min(total, 20)):
            slide = slides.nth(i)
            if producto_ya_agregado(slide, "carrusel_home"):
                continue
            if i == agregado_idx:
                continue

            if btn_agregar.count() > 0:
                # Hover sobre la imagen para mostrar "Ver detalle"
                img_container = slide.locator("div.product-image").first
                if img_container.count():
                    img_container.scroll_into_view_if_needed(timeout=3000)
                    img_container.hover()
                    page.wait_for_timeout(800)

                    ver_detalle = slide.locator("a.fade-button-link").first
                    if ver_detalle.count() and ver_detalle.is_visible():
                        ver_detalle.click()
                        page.wait_for_timeout(3000)
                        cerrar_popups(page)
                        print(f"   ✅ Slide {i+1} → hover → 'Ver detalle' → PDP")
                        pdp_ok = True
                        break

                    # Fallback: navegar via href directo (mobile no tiene hover)
                    link = slide.locator("a.fade-button-link, a[href*='/ficha/']").first
                    if link.count():
                        href = link.get_attribute("href")
                        if href:
                            full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                            page.goto(full_url)
                            page.wait_for_load_state("domcontentloaded")
                            page.wait_for_timeout(3000)
                            cerrar_popups(page)
                            print(f"   ✅ Slide {i+1} → navegación directa a PDP")
                            pdp_ok = True
                            break

                    # Fallback 2: click en imagen directamente (puede llevar a PDP)
                    img_link = slide.locator("a:has(img)").first
                    if img_link.count():
                        img_link.click()
                        page.wait_for_timeout(3000)
                        cerrar_popups(page)
                        print(f"   ✅ Slide {i+1} → click imagen → PDP")
                        pdp_ok = True
                        break

            # Siguiente slide
            try:
                if next_btn.is_visible():
                    next_btn.click()
                    page.wait_for_timeout(600)
            except Exception:
                break

        if pdp_ok:
            pdp_agregar(page)
            page.go_back()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)
            cerrar_popups(page)
            print("   ✅ Regresó de PDP del carrusel home")
        else:
            print("   ⚠️  No se encontró producto para ir a PDP")
    except Exception as e:
        debug_completo(page, "carrusel_home_pdp")
        print(f"   ❌ Error en PDP carrusel home: {e}")


# ── Registro de flujos disponibles ────────────────────────────────────
FLUJOS = {
    "1": flujo_1_esika,
    "2": flujo_2_categorias,
    "3": flujo_3_carrusel_gana,
    "4": flujo_4_pedido,
    "5": flujo_5_buscador_checkout,
    "6": flujo_6_search_plp,
    "7": flujo_7_mini_buscador,
    "8": flujo_8_liquidacion,
    "9": flujo_9_festivales_plp,
    "10": flujo_10_festivales_carrusel,
    "11": flujo_11_carrusel_home,
}


# ══════════════════════════════════════════════════════════════════════
# P12 — Limpiar carrito antes de ejecutar flujos
# ══════════════════════════════════════════════════════════════════════
def limpiar_carrito(page) -> int:
    """
    Navega al pedido y elimina todos los productos del carrito.
    Retorna la cantidad de productos eliminados.
    """
    print("\n🧹 Limpiando carrito antes de ejecutar flujos...")
    try:
        page.goto(f"{BASE_URL.rstrip('/')}/Pedido")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)
        verificar_sesion(page)
        cerrar_popups(page)

        eliminados = 0
        max_intentos = 30  # Evitar loop infinito

        for _ in range(max_intentos):
            # Buscar botón de eliminar producto (cualquier variante)
            eliminado = page.evaluate("""() => {
                const selectores = [
                    'button[id*="btnEliminar"]',
                    'button[class*="eliminar"]',
                    'a[class*="eliminar"]',
                    'button[title*="Eliminar"]',
                    'button[aria-label*="Eliminar"]',
                    'span[class*="eliminar"]',
                    '[class*="btn-delete"]',
                    '[class*="btn_eliminar"]',
                    'button:has-text("Eliminar")',
                ];
                for (const sel of selectores) {
                    const btns = document.querySelectorAll(sel);
                    for (const btn of btns) {
                        if (btn.offsetParent !== null) {
                            btn.click();
                            return sel;
                        }
                    }
                }
                return null;
            }""")

            if not eliminado:
                break  # No hay más productos

            print(f"   🗑️  Eliminando producto ({eliminado.split(':')[0][:30]})")
            page.wait_for_timeout(1500)
            cerrar_popups(page)  # Confirmar modal si aparece
            page.wait_for_timeout(1000)
            eliminados += 1

        if eliminados > 0:
            print(f"   ✅ {eliminados} producto(s) eliminado(s) del carrito")
        else:
            print("   ℹ️  Carrito ya estaba vacío")

        return eliminados

    except Exception as e:
        print(f"   ⚠️  Error limpiando carrito: {e}")
        return 0


# ══════════════════════════════════════════════════════════════════════
# P13 — Output de estado de flujos por ejecución
# ══════════════════════════════════════════════════════════════════════
def guardar_status_flujos(resultados: list, mobile: bool) -> str:
    """
    Guarda un resumen del resultado de cada flujo en flow_status_<timestamp>.json.
    También imprime una tabla resumen en consola.
    """
    os.makedirs("tools/output", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"tools/output/flow_status_{ts}.json"

    # Calcular totales
    total         = len(resultados)
    completos     = sum(1 for r in resultados if r["estado"] == "completo")
    parciales     = sum(1 for r in resultados if r["estado"] == "parcial")
    con_error     = sum(1 for r in resultados if r["estado"] == "error")
    sin_productos = sum(1 for r in resultados if r["estado"] == "sin_productos")

    output = {
        "timestamp": datetime.now(pytz.timezone("America/Lima")).isoformat(),
        "modo": "mobile" if mobile else "desktop",
        "env": BASE_URL,
        "resumen": {
            "total": total,
            "completos": completos,
            "parciales": parciales,
            "errores": con_error,
            "sin_productos": sin_productos,
        },
        "flujos": resultados,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Tabla en consola
    ICONOS = {"completo": "✅", "parcial": "⚠️ ", "error": "❌", "sin_productos": "⬜"}
    print(f"\n{'═'*60}")
    print(f"  RESUMEN DE EJECUCIÓN — {'MOBILE' if mobile else 'DESKTOP'}")
    print(f"{'═'*60}")
    for r in resultados:
        icono = ICONOS.get(r["estado"], "❓")
        dur = f"{r['duracion_s']:.0f}s" if r.get("duracion_s") else "—"
        causa = f" | {r['causa']}" if r.get("causa") else ""
        print(f"  {icono} Flujo {r['flujo']:>3}  {r['nombre'][:30]:<30} {dur:>4}{causa}")
    print(f"{'─'*60}")
    print(f"  ✅ {completos}  ⚠️ {parciales}  ❌ {con_error}  ⬜ {sin_productos} sin productos  — total {total}")
    print(f"  📄 Status guardado: {path}")
    print(f"{'═'*60}\n")

    return path


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
            device_name = CONFIG["mobile"]["device"]
            device = p.devices[device_name]
            context = browser.new_context(**device)
            print(f"📱 Modo mobile: {device_name}")
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

        # P12 — Limpiar carrito antes de ejecutar
        limpiar_carrito(page)

        # P13 — Tracking de resultados por flujo
        resultados_flujos = []

        NOMBRES_FLUJO = {
            "1": "Ésika PLP + PDP",
            "2": "Fragancias PLP + PDP",
            "3": "Carrusel Gana+",
            "4": "Pedido",
            "5": "Buscador checkout",
            "6": "Search PLP",
            "7": "Mini buscador",
            "8": "Liquidación PLP",
            "9": "Festivales PLP",
            "10": "Festivales carrusel",
            "11": "Carrusel home",
        }

        for key in flujos_a_ejecutar:
            t_inicio = datetime.now()
            resultado = {"flujo": key, "nombre": NOMBRES_FLUJO.get(key, key),
                         "estado": "completo", "causa": None, "duracion_s": None}
            try:
                verificar_sesion(page)
                FLUJOS[key](page)
            except SinProductosError as e:
                resultado["estado"] = "sin_productos"
                resultado["causa"] = str(e)
                print(f"\n   ⬜ FLUJO {key} sin productos en este entorno: {e}")
            except Exception as e:
                err_name = type(e).__name__
                resultado["estado"] = "error"
                resultado["causa"] = f"{err_name}: {str(e)[:120]}"
                print(f"\n   ❌ FLUJO {key} FALLÓ ({err_name}): {e}")
                # Si el browser/page murió, recrear
                if "TargetClosed" in err_name or "closed" in str(e).lower():
                    print("   🔄 Recreando página...")
                    try:
                        page.close()
                    except Exception:
                        pass
                    if mobile:
                        device = p.devices[CONFIG["mobile"]["device"]]
                        context = browser.new_context(**device)
                    else:
                        context = browser.new_context()
                    page = context.new_page()
                    page.on("request", handle_request)
                    registrar_handler_popups(page)
                    login(page)
            finally:
                resultado["duracion_s"] = (datetime.now() - t_inicio).total_seconds()
                resultados_flujos.append(resultado)

        output_file = CONFIG["output"]["mobile"] if mobile else CONFIG["output"]["desktop"]
        guardar_eventos(acumulado, output_file)
        guardar_status_flujos(resultados_flujos, mobile)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot de automatización Belcorp – GA4")
    parser.add_argument(
        "--flujo", "-f",
        nargs="+",
        choices=FLUJOS.keys(),
        metavar="N",
        help="Flujo(s) a ejecutar: 1-10 (por defecto: todos)"
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
