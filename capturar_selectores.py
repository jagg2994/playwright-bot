"""
capturar_selectores.py
======================
Herramienta de debug interactivo: hace login con las credenciales del .env,
abre el navegador y captura en consola el selector exacto de cada elemento
que el usuario clickea manualmente.

Uso:
    python capturar_selectores.py

Por cada click verás en consola:
  - tag, id, clases, atributos relevantes
  - selector CSS sugerido
  - texto visible del elemento
  - URL actual

Presiona Ctrl+C para salir.
"""

import os
import sys
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

JS_LISTENER = """
() => {
    if (window.__capturadorActivo) return;
    window.__capturadorActivo = true;
    window.__capturas = window.__capturas || [];

    document.addEventListener('click', function(e) {
        const el = e.target;

        function buildSelector(node) {
            let sel = node.tagName.toLowerCase();
            if (node.id) sel += '#' + node.id;
            if (node.className && typeof node.className === 'string') {
                node.className.trim().split(/\\s+/).forEach(c => { sel += '.' + c; });
            }
            const attrs = ['btn-eligelo','btn-show-types-tones-modal','btn-elegido',
                           'add-type-tone','data-item-tag','data-grupo','data-cuv',
                           'header-title','header-selected-quantity'];
            attrs.forEach(a => {
                if (node.hasAttribute(a)) sel += '[' + a + '="' + node.getAttribute(a) + '"]';
            });
            return sel;
        }

        function getAttrs(node) {
            const result = {};
            for (const a of node.attributes) {
                if (a.name === 'class') continue;
                if (a.name.startsWith('data-') || ['id','href','type','src',
                    'btn-eligelo','btn-show-types-tones-modal','header-title',
                    'header-selected-quantity','data-item-tag'].includes(a.name)) {
                    result[a.name] = a.value.substring(0, 100);
                }
            }
            return result;
        }

        window.__capturas.push({
            tag:      el.tagName.toLowerCase(),
            id:       el.id || '',
            classes:  typeof el.className === 'string' ? el.className.trim() : '',
            attrs:    getAttrs(el),
            selector: buildSelector(el),
            text:     (el.innerText || el.textContent || '').trim().substring(0, 80),
            href:     el.href || '',
            url:      window.location.href
        });
    }, true);
}
"""


def login(page) -> None:
    print("➡️  Login...")
    page.goto("https://www.somosbelcorp.com/")
    page.fill("#txtUsuario", os.getenv("BELCORP_USER"))
    page.fill("#txtContrasenia", os.getenv("BELCORP_PASS"))
    page.click("#btnLogin")
    page.wait_for_selector('li.menu-item >> text="Gana+"', timeout=15000)
    print("✅ Login OK\n")


def poll_clicks(page):
    try:
        capturas = page.evaluate(
            "() => { const c = window.__capturas || []; window.__capturas = []; return c; }"
        )
    except Exception:
        return

    for c in capturas:
        print("\n" + "─" * 64)
        print(f"  TAG      {c['tag']}")
        if c['id']:
            print(f"  ID       #{c['id']}")
        if c['classes']:
            print(f"  CLASES   {c['classes']}")
        if c['text']:
            print(f"  TEXTO    \"{c['text']}\"")
        if c['href']:
            print(f"  HREF     {c['href'][:80]}")
        for k, v in (c.get('attrs') or {}).items():
            if k != 'id':
                print(f"  {k.upper():<14} {v}")
        print(f"  SELECTOR {c['selector']}")
        print(f"  URL      {c['url'][:80]}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Reinstalar el listener en cada navegación
        page.on("load", lambda: _inject(page))
        page.on("framenavigated", lambda frame: _inject(page) if frame == page.main_frame else None)

        login(page)
        _inject(page)

        print("═" * 64)
        print("  CAPTURADOR ACTIVO — clickea lo que quieras analizar")
        print("  Ctrl+C para salir")
        print("═" * 64)

        try:
            while True:
                page.wait_for_timeout(600)
                poll_clicks(page)
        except KeyboardInterrupt:
            print("\nCaptura finalizada.")
        finally:
            browser.close()


def _inject(page):
    try:
        page.evaluate(JS_LISTENER)
    except Exception:
        pass


if __name__ == "__main__":
    main()
