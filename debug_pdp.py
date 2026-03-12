"""
Debug script para diagnosticar el flujo de selección de ofertas en PDP.
Navega hasta que hagas pause(), luego ejecuta paso a paso cada selector
y guarda screenshots + logs para ver exactamente dónde falla.
"""
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

SCREENSHOTS_DIR = "debug_screenshots"

def screenshot(page, nombre):
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    path = f"{SCREENSHOTS_DIR}/{nombre}.png"
    page.screenshot(path=path)
    print(f"   📸 Screenshot: {path}")


def diagnosticar_pdp(page):
    print("\n" + "═"*60)
    print("DIAGNÓSTICO PDP – FLUJO DE SELECCIÓN DE OFERTAS")
    print("═"*60)

    # ── PASO 0: Estado general de la página ────────────────────────
    print(f"\n🌐 URL actual: {page.url}")
    screenshot(page, "00_estado_inicial")

    # ── PASO 1: ¿Producto ya agregado? ─────────────────────────────
    print("\n[PASO 1] Inspeccionando div[data-txt_agregado]...")
    elementos = page.query_selector_all("div[data-txt_agregado]")
    print(f"   → Cantidad de elementos encontrados: {len(elementos)}")

    for i, el in enumerate(elementos):
        visible    = el.is_visible()
        texto      = el.inner_text().strip()
        attr_val   = el.get_attribute("data-txt_agregado")
        display    = el.evaluate("e => window.getComputedStyle(e).display")
        clase      = el.get_attribute("class") or ""
        print(f"\n   Elemento {i+1}:")
        print(f"     visible          : {visible}")
        print(f"     display          : {display}")
        print(f"     texto            : '{texto}'")
        print(f"     data-txt_agregado: '{attr_val}'")
        print(f"     class            : '{clase}'")

    screenshot(page, "01_data_txt_agregado_estado")
    print("\n   → (Continuando diagnóstico sin detener el flujo...)")

    # ── PASO 2: Botones de selección obligatoria ───────────────────
    SELECTOR_MODALES = 'button.tono_select_opt.nobg[btn-show-types-tones-modal]'
    print(f"\n[PASO 2] Buscando botones de modal: {SELECTOR_MODALES}")
    modales = page.query_selector_all(SELECTOR_MODALES)
    print(f"   → Encontrados: {len(modales)} botón(es)")

    if len(modales) == 0:
        print("   ℹ️  Sin selecciones obligatorias — producto simple")
        screenshot(page, "02_sin_modales")
    else:
        for i, btn in enumerate(modales):
            texto_btn = btn.inner_text().strip()
            visible    = btn.is_visible()
            enabled    = btn.is_enabled()
            print(f"   Botón {i+1}: texto='{texto_btn}' | visible={visible} | enabled={enabled}")

        screenshot(page, "02_botones_modal_detectados")

        # ── PASO 3: Iterar cada modal ──────────────────────────────
        for i, btn_modal in enumerate(modales):
            print(f"\n[PASO 3.{i+1}] Abriendo modal {i+1}/{len(modales)}...")
            try:
                btn_modal.scroll_into_view_if_needed(timeout=3000)
                btn_modal.click()
                page.wait_for_timeout(1000)
                screenshot(page, f"03_{i+1}_modal_abierto")
            except Exception as e:
                print(f"   ❌ Error al abrir modal {i+1}: {e}")
                continue

            # Buscar opciones button[btn-eligelo]
            print(f"   Buscando opciones button[btn-eligelo]...")
            opciones = page.query_selector_all("button[btn-eligelo]")
            print(f"   → Encontradas: {len(opciones)} opción(es)")

            if len(opciones) == 0:
                print("   ❌ No se encontraron opciones en el modal")
                screenshot(page, f"03_{i+1}_sin_opciones")
                continue

            for j, opt in enumerate(opciones[:5]):  # máximo 5 para el log
                texto_opt = opt.inner_text().strip()
                visible_opt = opt.is_visible()
                enabled_opt = opt.is_enabled()
                print(f"      Opción {j+1}: texto='{texto_opt}' | visible={visible_opt} | enabled={enabled_opt}")

            # Click en la primera opción
            print(f"   → Haciendo click en primera opción...")
            try:
                opciones[0].click()
                page.wait_for_timeout(600)
                screenshot(page, f"03_{i+1}_opcion_seleccionada")
                print(f"   ✅ Opción seleccionada")
            except Exception as e:
                print(f"   ❌ Error al seleccionar opción: {e}")
                continue

            # Buscar botón confirmar
            print(f"   Buscando button#btn-aplicar-seleccion...")
            confirmar_all = page.query_selector_all("button#btn-aplicar-seleccion")
            print(f"   → Encontrados: {len(confirmar_all)} botón(es) confirmar")
            for k, c in enumerate(confirmar_all):
                clases   = c.get_attribute("class") or ""
                visible_c = c.is_visible()
                enabled_c = c.is_enabled()
                print(f"      Confirmar {k+1}: class='{clases}' | visible={visible_c} | enabled={enabled_c}")

            confirmar_activo = page.query_selector("button#btn-aplicar-seleccion.active")
            if confirmar_activo:
                print(f"   ✅ Botón confirmar ACTIVO encontrado → haciendo click")
                try:
                    confirmar_activo.click()
                    page.wait_for_timeout(700)
                    screenshot(page, f"03_{i+1}_confirmado")
                    print(f"   ✅ Modal {i+1} confirmado")
                except Exception as e:
                    print(f"   ❌ Error al confirmar: {e}")
            else:
                print(f"   ⚠️  Botón confirmar NO está activo todavía (falta clase .active)")
                screenshot(page, f"03_{i+1}_confirmar_inactivo")

    # ── PASO 4: Botón agregar final ────────────────────────────────
    print(f"\n[PASO 4] Verificando botón final de agregar...")
    SELECTOR_BTN = "a#btnAgregalo"
    btn_final = page.query_selector(SELECTOR_BTN)

    if not btn_final:
        print(f"   ❌ No se encontró {SELECTOR_BTN}")
        screenshot(page, "04_sin_btn_agregar")
        return

    clases_btn   = btn_final.get_attribute("class") or ""
    texto_btn    = btn_final.inner_text().strip()
    visible_btn  = btn_final.is_visible()
    enabled_btn  = btn_final.is_enabled()
    deshabilitado = "btn_deshabilitado_ficha" in clases_btn

    print(f"   texto   : '{texto_btn}'")
    print(f"   clases  : '{clases_btn}'")
    print(f"   visible : {visible_btn}")
    print(f"   enabled : {enabled_btn}")
    print(f"   deshabilitado (clase): {deshabilitado}")
    screenshot(page, "04_btn_agregar_estado")

    if deshabilitado:
        print("   ⚠️  El botón TIENE la clase btn_deshabilitado_ficha → NO se puede agregar aún")
    else:
        print("   ✅ Botón habilitado → haciendo click")
        btn_final.click()
        page.wait_for_timeout(2000)
        screenshot(page, "04_producto_agregado")
        print("   ✅ Producto agregado")


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context()
        page = context.new_page()

        # Login
        print("➡️  Login...")
        page.goto("https://www.somosbelcorp.com/")
        page.fill("#txtUsuario", os.getenv("BELCORP_USER"))
        page.fill("#txtContrasenia", os.getenv("BELCORP_PASS"))
        page.click("#btnLogin")
        page.wait_for_selector('li.menu-item >> text="Gana+"', timeout=15000)
        print("✅ Login OK")

        print("\n" + "─"*60)
        print("👉 Navega manualmente hasta la PDP con selección de ofertas")
        print("   Cuando estés en la PDP correcta, cierra el inspector")
        print("─"*60)
        page.pause()  # ← Aquí navegas manualmente a la PDP problemática

        # Diagnóstico
        diagnosticar_pdp(page)

        print("\n" + "═"*60)
        print("✅ Diagnóstico completado")
        print(f"   Screenshots guardados en: ./{SCREENSHOTS_DIR}/")
        print("═"*60)

        input("\nPresiona Enter para cerrar el navegador...")
        browser.close()


if __name__ == "__main__":
    run()
