"""
Diagnóstico de tipos de oferta en Belcorp.
Navega por las secciones con productos y guarda el outerHTML
de cada article para identificar selectores por tipo de oferta.
"""
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

OUTPUT_FILE = "diagnostico_productos.html"

def login(page):
    page.goto("https://www.somosbelcorp.com/")
    page.fill("#txtUsuario", os.getenv("BELCORP_USER"))
    page.fill("#txtContrasenia", os.getenv("BELCORP_PASS"))
    page.click("#btnLogin")
    page.wait_for_selector('li.menu-item >> text="Gana+"', timeout=15000)
    print("✅ Login OK")

def capturar_articulos(page, seccion_nombre):
    """Extrae el outerHTML de cada article visible en la página actual."""
    resultados = []
    try:
        page.wait_for_selector("article", timeout=8000)
        articulos = page.query_selector_all("article")
        print(f"   📦 {len(articulos)} artículos encontrados en '{seccion_nombre}'")
        for i, art in enumerate(articulos[:10]):  # máximo 10 por sección
            html = art.inner_html()
            resultados.append({
                "seccion": seccion_nombre,
                "indice": i + 1,
                "html": html
            })
    except Exception as e:
        print(f"   ⚠️ No se encontraron artículos en '{seccion_nombre}': {e}")
    return resultados

def run():
    capturas = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context()
        page = context.new_page()

        login(page)

        # ── Sección 1: PLP Ésika ──────────────────────────────────────────
        print("\n🔍 Capturando PLP Ésika...")
        page.click('li.menu-item >> text="Gana+"')
        page.wait_for_selector('li[data-codigo="mar-esika"]', timeout=10000)
        page.click('li[data-codigo="mar-esika"]')
        page.wait_for_timeout(3000)
        capturas += capturar_articulos(page, "PLP_Esika")

        # ── Sección 2: PLP Fragancias (Categorías) ────────────────────────
        print("\n🔍 Capturando PLP Fragancias...")
        page.click('li.menu-item >> text="Gana+"')
        page.wait_for_selector('li[data-codigo="cat-fragancia"]', timeout=10000)
        page.click('li[data-codigo="cat-fragancia"]')
        page.wait_for_timeout(3000)
        capturas += capturar_articulos(page, "PLP_Fragancias")

        # ── Sección 3: Carruseles de Gana+ ────────────────────────────────
        print("\n🔍 Capturando artículos en carruseles Gana+...")
        page.click('li.menu-item >> text="Gana+"')
        page.wait_for_timeout(3000)

        carruseles = page.locator('div.contenedor_carrusel.slick-slider[data-seccion-productos]')
        total = carruseles.count()
        print(f"   🎠 {total} carruseles detectados")

        for ci in range(min(total, 3)):  # primeros 3 carruseles
            root = carruseles.nth(ci)
            root.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            slides = root.locator("article")
            count = slides.count()
            print(f"   Carrusel {ci+1}: {count} slides visibles")
            for si in range(min(count, 5)):  # primeros 5 slides por carrusel
                art = slides.nth(si)
                try:
                    html = art.inner_html()
                    capturas.append({
                        "seccion": f"Carrusel_{ci+1}_slide_{si+1}",
                        "indice": si + 1,
                        "html": html
                    })
                except:
                    pass

        browser.close()

    # ── Generar HTML de diagnóstico ────────────────────────────────────────
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Diagnóstico de productos</title>
<style>
  body { font-family: monospace; background: #111; color: #eee; padding: 20px; }
  h1   { color: #4fc; }
  h2   { color: #fa0; border-top: 1px solid #444; padding-top: 10px; margin-top: 30px; }
  h3   { color: #8df; }
  .card { background: #1e1e1e; border: 1px solid #333; border-radius: 6px;
          padding: 12px; margin: 10px 0; overflow-x: auto; }
  pre  { white-space: pre-wrap; word-break: break-all; font-size: 12px; }
</style>
</head>
<body>
<h1>Diagnóstico de tipos de oferta</h1>
""")

        seccion_actual = None
        for c in capturas:
            if c["seccion"] != seccion_actual:
                seccion_actual = c["seccion"]
                f.write(f"<h2>{seccion_actual}</h2>\n")

            f.write(f'<h3>Artículo #{c["indice"]}</h3>\n')
            f.write('<div class="card"><pre>')
            # Escapar HTML para mostrarlo como texto
            escaped = (c["html"]
                       .replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))
            f.write(escaped)
            f.write("</pre></div>\n")

        f.write("</body></html>")

    print(f"\n✅ Diagnóstico guardado en: {OUTPUT_FILE}")
    print("   Ábrelo en el navegador para inspeccionar el HTML de cada producto.")

if __name__ == "__main__":
    run()
