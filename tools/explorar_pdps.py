"""
Explorador de PDPs — Recorre productos y cataloga los diferentes tipos de PDP.

Entra a N productos de distintas secciones, captura un "fingerprint" de cada PDP
(botones, selecciones, inputs de cantidad, textos de restricción) y guarda todo
en tools/output/pdp_catalog.json.

No agrega productos al carrito — solo observa y registra.

Uso:
    python3 tools/explorar_pdps.py               # explorar 30 productos
    python3 tools/explorar_pdps.py --max 50       # explorar 50 productos
    python3 tools/explorar_pdps.py --mobile       # explorar en modo mobile
"""
import os
import sys
import json
import argparse
from datetime import datetime

# Agregar raíz del proyecto al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from playwright.sync_api import sync_playwright

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)
BASE = CONFIG["base_url"].rstrip("/")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def login(page):
    """Login en el sitio."""
    page.goto(f"{BASE}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    pais = os.getenv(CONFIG["credentials"]["country_env"], "")
    if pais:
        try:
            page.select_option("#ddlPais", value=pais)
            page.wait_for_timeout(500)
        except Exception:
            pass
    page.fill("#txtUsuario", os.getenv(CONFIG["credentials"]["user_env"]))
    page.fill("#txtContrasenia", os.getenv(CONFIG["credentials"]["pass_env"]))
    page.click("#btnLogin")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(5000)
    print("✅ Login OK")


def verificar_sesion(page):
    """Re-login si la sesión expiró."""
    try:
        btn_login = page.locator("#btnLogin")
        if btn_login.count() and btn_login.is_visible(timeout=1000):
            print("   ⚠️  Sesión expirada — re-logueando...")
            login(page)
            return True
    except Exception:
        pass
    return False


# ── JS que captura el fingerprint de una PDP ─────────────────────────
FINGERPRINT_JS = """
() => {
    const r = {};

    // Botón principal (Agregar / Elegir opción / etc.)
    const btn = document.querySelector('a#btnAgregalo, button#btnAgregalo, a.btn_validar_alertas, button.btn_validar_alertas');
    if (btn) {
        r.boton = {
            texto: (btn.innerText || '').trim(),
            id: btn.id || null,
            clases: btn.className.substring(0, 120),
            deshabilitado: btn.classList.contains('btn_deshabilitado_ficha') || btn.hasAttribute('disabled'),
            visible: btn.offsetParent !== null
        };
    } else {
        r.boton = null;
    }

    // Selecciones obligatorias (tonos, arma tu oferta)
    const sels = document.querySelectorAll('button[btn-show-types-tones-modal]');
    r.selecciones = Array.from(sels).map(s => ({
        texto: (s.innerText || '').trim(),
        clases: s.className.substring(0, 80)
    }));

    // Inputs de cantidad visibles
    const allInputs = document.querySelectorAll('input');
    r.inputs_cantidad = [];
    for (const inp of allInputs) {
        if (inp.offsetParent === null) continue;
        const id = (inp.id || '').toLowerCase();
        const name = (inp.name || '').toLowerCase();
        const cls = (inp.className || '').toLowerCase();
        const type = inp.type || '';
        if (type === 'number' || id.includes('cantidad') || name.includes('cantidad') ||
            cls.includes('cantidad') || cls.includes('qty') || cls.includes('input-number')) {
            r.inputs_cantidad.push({
                id: inp.id, type: type, value: inp.value,
                min: inp.min || null, max: inp.max || null,
                clases: inp.className.substring(0, 60)
            });
        }
    }

    // Controles de +/- cantidad
    const rangos = document.querySelectorAll('.mas_rangos, .menos_rangos, .icon_remove, .btn-plus, .btn-minus, [class*="incrementar"], [class*="decrementar"]');
    r.controles_cantidad = rangos.length;

    // Textos clave de restricción
    const keywords = ['mínimo', 'minimo', 'unidades', 'und.', 'elige', 'seleccion',
                       'arma tu', 'agotado', 'no disponible', 'cantidad', 'máximo',
                       'maximo', 'obligatori', 'requerido', 'opción', 'opcion',
                       'color', 'tono', 'talla', 'set de', 'pack'];
    const textos = new Set();
    document.querySelectorAll('span, p, div, label, h3, h4, h5').forEach(el => {
        if (el.children.length > 5) return;
        const t = (el.innerText || '').trim();
        if (t.length > 3 && t.length < 120) {
            const tl = t.toLowerCase();
            for (const k of keywords) {
                if (tl.includes(k)) { textos.add(t); break; }
            }
        }
    });
    r.textos_restriccion = Array.from(textos).slice(0, 12);

    // Ya agregado
    const caja = document.querySelector('div.caja_producto_agregado');
    r.ya_agregado = caja ? caja.offsetParent !== null : false;

    // Nombre del producto
    const nombre = document.querySelector('h1.nombre_producto, h1, .nombre_producto, [class*="nombre_ficha"]');
    r.nombre = nombre ? (nombre.innerText || '').trim().substring(0, 80) : null;

    // CUV
    const cuv = document.querySelector('[data-card-cuv], [data-cuv], input[name*="CUV"]');
    r.cuv = cuv ? (cuv.getAttribute('data-card-cuv') || cuv.getAttribute('data-cuv') || cuv.value || null) : null;

    // Marca
    const marca = document.querySelector('.marca_producto, [class*="marca"]');
    r.marca = marca ? (marca.innerText || '').trim().substring(0, 30) : null;

    // Precio
    const precio = document.querySelector('.precio_ficha, .precio-producto, [class*="precio"]');
    r.precio = precio ? (precio.innerText || '').trim().substring(0, 30) : null;

    // Screenshot viewport dimensions
    r.url = window.location.href;

    return r;
}
"""


def recolectar_cuvs_plp(page, max_productos):
    """Recolecta CUVs, metadata y URLs de PDP de los articles en la PLP actual."""
    return page.evaluate("""(max) => {
        const arts = document.querySelectorAll('article[data-card-cuv]');
        return Array.from(arts).slice(0, max).map(a => {
            const btn = a.querySelector('[id*=btnAgregalo], [class*=agregalo], [class*=Agregalo]');
            // Extraer URL de la PDP
            const link = a.querySelector('a[href*="Detalles"], a[href*="ficha"], a.link_imagen, a.redireccionarFichaImg');
            let pdp_url = link ? link.href : null;
            if (!pdp_url) {
                // Buscar cualquier link dentro del article
                const anyLink = a.querySelector('a[href]');
                if (anyLink && anyLink.href.includes('/Detalles/')) pdp_url = anyLink.href;
            }
            return {
                cuv: a.getAttribute('data-card-cuv'),
                btn_texto: btn ? (btn.innerText || '').trim() : null,
                btn_clases: btn ? btn.className.substring(0, 80) : null,
                agotado: (a.className || '').includes('producto_agotado'),
                tiene_rangos: !!a.querySelector('.mas_rangos, .menos_rangos'),
                pdp_url: pdp_url
            };
        });
    }""", max_productos)


def navegar_a_pdp(page, cuv):
    """Navega a la PDP de un producto por CUV usando URL directa."""
    try:
        # Extraer URL de la PDP desde el article en la PLP (si estamos ahí)
        url_pdp = page.evaluate("""(cuv) => {
            const art = document.querySelector('article[data-card-cuv="' + cuv + '"]');
            if (!art) return null;
            const link = art.querySelector('a[href*="Detalles"], a[href*="ficha"], a.link_imagen');
            return link ? link.href : null;
        }""", cuv)

        if url_pdp:
            page.goto(url_pdp)
        else:
            page.goto(f"{BASE}/ficha/{cuv}")

        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        # Verificar que no nos redirigió a login
        if verificar_sesion(page):
            # Reintentar después de re-login
            page.goto(url_pdp or f"{BASE}/ficha/{cuv}")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

        # Verificar que estamos en una PDP real
        if "/Detalles/" in page.url or "/ficha/" in page.url.lower():
            return True

        # Puede que el CUV no tenga ficha propia
        return False
    except Exception as e:
        print(f"   ❌ Error navegando a PDP {cuv}: {e}")
        return False


def explorar(max_productos=30, mobile=False):
    """Recorre productos y cataloga sus PDPs."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)

        if mobile:
            device = p.devices[CONFIG["mobile"]["device"]]
            context = browser.new_context(**device)
            print(f"📱 Mobile: {CONFIG['mobile']['device']}")
        else:
            context = browser.new_context()

        page = context.new_page()
        login(page)

        catalogo = []
        secciones_visitadas = set()

        # Secciones a explorar
        secciones = [
            {"nombre": "Gana+ Esika", "url": f"{BASE}/Ofertas", "filtro": 'li[data-codigo="mar-esika"]'},
            {"nombre": "Gana+ LBel", "url": f"{BASE}/Ofertas", "filtro": 'li[data-codigo="mar-lbel"]'},
            {"nombre": "Gana+ Cyzone", "url": f"{BASE}/Ofertas", "filtro": 'li[data-codigo="mar-cyzone"]'},
            {"nombre": "Gana+ Fragancias", "url": f"{BASE}/Ofertas", "filtro": 'li[data-codigo="cat-fragancia"]'},
            {"nombre": "Gana+ Maquillaje", "url": f"{BASE}/Ofertas", "filtro": 'li[data-codigo="cat-maquillaje"]'},
            {"nombre": "Gana+ Cuidado Personal", "url": f"{BASE}/Ofertas", "filtro": 'li[data-codigo="cat-cuidado-personal"]'},
            {"nombre": "Liquidación", "url": f"{BASE}/liquidacion", "filtro": None},
        ]

        productos_explorados = 0
        cuvs_vistos = set()

        for seccion in secciones:
            if productos_explorados >= max_productos:
                break

            print(f"\n{'═'*50}")
            print(f"📍 {seccion['nombre']}")
            print(f"{'═'*50}")

            try:
                verificar_sesion(page)
                page.goto(seccion["url"])
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(3000)
                verificar_sesion(page)

                if seccion["filtro"]:
                    try:
                        page.click(seccion["filtro"])
                        page.wait_for_timeout(3000)
                    except Exception:
                        print(f"   ⚠️ No se encontró filtro {seccion['filtro']}")
                        continue
            except Exception as e:
                print(f"   ❌ Error navegando: {e}")
                continue

            # Guardar URL de la PLP para volver después
            plp_url = page.url

            # Recolectar productos de la PLP
            plp_productos = recolectar_cuvs_plp(page, 15)
            print(f"   📦 {len(plp_productos)} productos en PLP")

            # Registrar info de PLP de cada producto
            for prod in plp_productos:
                cuv = prod.get("cuv")
                if not cuv or cuv in cuvs_vistos:
                    continue
                if productos_explorados >= max_productos:
                    break

                cuvs_vistos.add(cuv)

                # Registrar fingerprint de PLP
                plp_fingerprint = {
                    "btn_texto": prod["btn_texto"],
                    "agotado": prod["agotado"],
                    "tiene_rangos": prod["tiene_rangos"],
                }

                # Si está agotado en PLP, registrar sin ir a PDP
                if prod["agotado"]:
                    catalogo.append({
                        "cuv": cuv,
                        "seccion": seccion["nombre"],
                        "plp": plp_fingerprint,
                        "pdp": None,
                        "tipo_detectado": "agotado",
                    })
                    productos_explorados += 1
                    print(f"   [{cuv}] ⊘ Agotado (PLP)")
                    continue

                # Navegar a PDP (URL directa)
                if not navegar_a_pdp(page, cuv):
                    print(f"   [{cuv}] ❌ No se pudo navegar a PDP")
                    # Volver a PLP para el siguiente
                    page.goto(plp_url)
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(2000)
                    continue

                # Capturar fingerprint de PDP
                try:
                    pdp_fp = page.evaluate(FINGERPRINT_JS)
                except Exception as e:
                    print(f"   [{cuv}] ❌ Error capturando PDP: {e}")
                    pdp_fp = {"error": str(e)}

                # Clasificar
                tipo = clasificar_pdp(plp_fingerprint, pdp_fp)

                catalogo.append({
                    "cuv": cuv,
                    "seccion": seccion["nombre"],
                    "plp": plp_fingerprint,
                    "pdp": pdp_fp,
                    "tipo_detectado": tipo,
                })
                productos_explorados += 1

                nombre = pdp_fp.get("nombre", "") or ""
                print(f"   [{cuv}] {tipo:20s} | {nombre[:40]}")

                # Volver a la PLP (URL directa, no go_back)
                page.goto(plp_url)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)

        browser.close()

        # Guardar catálogo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(OUTPUT_DIR, f"pdp_catalog_{timestamp}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(catalogo, f, indent=2, ensure_ascii=False)
        print(f"\n✅ {len(catalogo)} productos catalogados → {output_path}")

        # También guardar como latest
        latest_path = os.path.join(OUTPUT_DIR, "pdp_catalog_latest.json")
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(catalogo, f, indent=2, ensure_ascii=False)

        # Resumen
        imprimir_resumen(catalogo)

        return catalogo


def clasificar_pdp(plp, pdp):
    """Clasifica el tipo de PDP basado en los fingerprints."""
    if not pdp or pdp.get("error"):
        return "error"

    # Ya agregado
    if pdp.get("ya_agregado"):
        return "ya_agregado"

    boton = pdp.get("boton")
    selecciones = pdp.get("selecciones", [])
    inputs_cant = pdp.get("inputs_cantidad", [])
    controles = pdp.get("controles_cantidad", 0)
    textos = " ".join(pdp.get("textos_restriccion", [])).lower()

    if not boton:
        return "sin_boton"

    btn_texto = boton.get("texto", "").lower()
    btn_disabled = boton.get("deshabilitado", False)

    # Agotado
    if plp.get("agotado") or "agotado" in textos or "no disponible" in textos:
        return "agotado"

    # Ya agregado (desde PDP)
    if btn_disabled and len(selecciones) == 0:
        return "ya_agregado"

    # Con selección de tono/color
    if len(selecciones) > 0:
        if any("tono" in s.get("texto", "").lower() or "color" in s.get("texto", "").lower() for s in selecciones):
            return "seleccion_tono"
        if "arma tu" in textos or "elige" in textos:
            return "seleccion_arma_oferta"
        return "seleccion_otro"

    # Con control de cantidad (und. mínimas)
    if controles > 0 or len(inputs_cant) > 0 or plp.get("tiene_rangos"):
        if "mínimo" in textos or "minimo" in textos:
            return "cantidad_minima"
        return "cantidad_variable"

    # Botón dice "Elegir opción" → requiere selección en PDP
    if "elegir" in btn_texto or "opción" in btn_texto or "opcion" in btn_texto:
        return "requiere_seleccion"

    # Simple
    if "agregar" in btn_texto:
        return "simple"

    return "desconocido"


def imprimir_resumen(catalogo):
    """Imprime resumen agrupado por tipo."""
    print(f"\n{'═'*50}")
    print("📊 RESUMEN DE TIPOS DE PRODUCTO")
    print(f"{'═'*50}")

    tipos = {}
    for p in catalogo:
        t = p["tipo_detectado"]
        if t not in tipos:
            tipos[t] = []
        tipos[t].append(p["cuv"])

    for tipo, cuvs in sorted(tipos.items(), key=lambda x: -len(x[1])):
        pct = len(cuvs) / len(catalogo) * 100
        print(f"   {tipo:25s} {len(cuvs):3d} ({pct:5.1f}%)  CUVs: {', '.join(cuvs[:5])}{'...' if len(cuvs) > 5 else ''}")

    print(f"\n   Total: {len(catalogo)} productos")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explorador de PDPs — cataloga tipos de producto")
    parser.add_argument("--max", type=int, default=30, help="Máximo de productos a explorar (default: 30)")
    parser.add_argument("--mobile", "-m", action="store_true", help="Explorar en modo mobile")
    args = parser.parse_args()

    explorar(max_productos=args.max, mobile=args.mobile)
