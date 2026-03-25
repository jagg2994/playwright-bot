"""
Page Mapper — Diagnóstico automático cuando el bot se bloquea.

Genera un mapa JSON de elementos accionables, obstáculos y formularios
de la página actual. Se usa como fallback en bloques except.

Uso:
    from tools.page_mapper import map_page
    mapa = map_page(page)
"""

import json
import os
from datetime import datetime


def map_page(page, guardar=True) -> dict:
    """
    Extrae un mapa completo de la página actual:
    - accionables: botones, links, inputs visibles
    - obstaculos: modals, overlays, popups, iframes
    - formularios: forms con sus campos
    - navegacion: links disponibles
    """
    mapa = page.evaluate("""
        () => {
            const resultado = {
                url: location.href,
                titulo: document.title,
                accionables: [],
                obstaculos: [],
                formularios: [],
                navegacion: []
            };

            // ── Accionables: botones, inputs, links clicables ──
            const selectores_accionables = [
                'button', 'a[href]', 'input[type="button"]', 'input[type="submit"]',
                '[role="button"]', '[onclick]', '[class*="btn"]', '[class*="agregar"]',
                '[class*="add"]', '[class*="elegir"]'
            ];
            const vistos = new Set();

            for (const sel of selectores_accionables) {
                for (const el of document.querySelectorAll(sel)) {
                    const rect = el.getBoundingClientRect();
                    const visible = rect.width > 0 && rect.height > 0 &&
                                    el.offsetParent !== null &&
                                    getComputedStyle(el).visibility !== 'hidden';

                    const id_unico = el.outerHTML.substring(0, 200);
                    if (vistos.has(id_unico)) continue;
                    vistos.add(id_unico);

                    const texto = (el.innerText || el.value || '').trim().substring(0, 80);
                    if (!texto && !el.id && !el.getAttribute('aria-label')) continue;

                    const clases = el.className && typeof el.className === 'string'
                        ? el.className.trim().substring(0, 120) : '';

                    // Construir selectores
                    let selector_id = el.id ? `#${el.id}` : null;
                    let selector_clase = null;
                    if (clases) {
                        const cls_principales = clases.split(/\\s+/).filter(c => c.length > 2).slice(0, 3);
                        if (cls_principales.length > 0) {
                            selector_clase = el.tagName.toLowerCase() + '.' + cls_principales.join('.');
                        }
                    }
                    let selector_texto = texto
                        ? `${el.tagName.toLowerCase()}:has-text('${texto.substring(0, 40)}')`
                        : null;
                    let selector_aria = el.getAttribute('aria-label')
                        ? `[aria-label="${el.getAttribute('aria-label')}"]`
                        : null;
                    let selector_data = null;
                    for (const attr of el.attributes) {
                        if (attr.name.startsWith('data-') && attr.name !== 'data-slick-index') {
                            selector_data = `[${attr.name}="${attr.value}"]`;
                            break;
                        }
                    }

                    resultado.accionables.push({
                        tipo: el.tagName.toLowerCase(),
                        texto: texto,
                        visible: visible,
                        habilitado: !el.disabled,
                        selector_id: selector_id,
                        selector_clase: selector_clase,
                        selector_aria: selector_aria,
                        selector_data: selector_data,
                        selector_texto: selector_texto,
                        rect: { top: Math.round(rect.top), left: Math.round(rect.left) }
                    });
                }
            }

            // ── Obstáculos: modals, overlays, popups ──
            const sels_obstaculos = [
                '[class*="modal"]', '[class*="overlay"]', '[class*="popup"]',
                '[role="dialog"]', '[class*="cookie"]', '[class*="consent"]',
                '[class*="alert"]', '[class*="banner"]'
            ];
            const obs_vistos = new Set();

            for (const sel of sels_obstaculos) {
                for (const el of document.querySelectorAll(sel)) {
                    const rect = el.getBoundingClientRect();
                    const visible = rect.width > 0 && rect.height > 0 &&
                                    el.offsetParent !== null;
                    if (!visible) continue;

                    const id_unico = (el.id || el.className || '').substring(0, 100);
                    if (obs_vistos.has(id_unico)) continue;
                    obs_vistos.add(id_unico);

                    const selector = el.id ? `#${el.id}` :
                        (el.className && typeof el.className === 'string'
                            ? '.' + el.className.trim().split(/\\s+/)[0]
                            : sel);

                    const btn_cerrar = el.querySelector(
                        '[class*="close"], [class*="cerrar"], [aria-label="Close"], button'
                    );

                    resultado.obstaculos.push({
                        tipo: sel.includes('modal') ? 'modal' :
                              sel.includes('overlay') ? 'overlay' :
                              sel.includes('popup') ? 'popup' :
                              sel.includes('cookie') ? 'cookie-banner' : 'otro',
                        selector: selector,
                        texto: (el.innerText || '').trim().substring(0, 100),
                        btn_cerrar: btn_cerrar ? {
                            selector: btn_cerrar.id ? `#${btn_cerrar.id}` :
                                btn_cerrar.className ? '.' + btn_cerrar.className.trim().split(/\\s+/)[0] : 'button',
                            texto: (btn_cerrar.innerText || '').trim().substring(0, 30)
                        } : null
                    });
                }
            }

            // ── Iframes ──
            for (const iframe of document.querySelectorAll('iframe')) {
                resultado.obstaculos.push({
                    tipo: 'iframe',
                    selector: iframe.id ? `#${iframe.id}` : 'iframe',
                    src: (iframe.src || '').substring(0, 200)
                });
            }

            // ── Formularios ──
            for (const form of document.querySelectorAll('form')) {
                const campos = [];
                for (const input of form.querySelectorAll('input, select, textarea')) {
                    if (input.type === 'hidden') continue;
                    campos.push({
                        nombre: input.name || input.id || '',
                        tipo: input.type || input.tagName.toLowerCase(),
                        selector: input.id ? `#${input.id}` :
                            (input.name ? `[name="${input.name}"]` : null),
                        requerido: input.required,
                        valor: (input.value || '').substring(0, 50)
                    });
                }
                if (campos.length === 0) continue;

                const submit = form.querySelector('button[type="submit"], input[type="submit"]');
                resultado.formularios.push({
                    id: form.id || form.action || '',
                    campos: campos,
                    boton_submit: submit ? (submit.innerText || submit.value || '').trim() : null
                });
            }

            // ── Navegación: links principales ──
            const nav_vistos = new Set();
            for (const a of document.querySelectorAll('a[href]')) {
                const href = a.getAttribute('href');
                if (!href || href === '#' || href.startsWith('javascript:')) continue;
                const texto = (a.innerText || '').trim().substring(0, 60);
                if (!texto || nav_vistos.has(href)) continue;
                nav_vistos.add(href);

                const rect = a.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;
                if (!visible) continue;

                resultado.navegacion.push({
                    texto: texto,
                    href: href,
                    selector_aria: a.getAttribute('aria-label')
                        ? `a[aria-label="${a.getAttribute('aria-label')}"]` : null
                });
            }

            // Limitar resultados para no saturar
            resultado.accionables = resultado.accionables.slice(0, 80);
            resultado.navegacion = resultado.navegacion.slice(0, 40);

            return resultado;
        }
    """)

    if guardar:
        os.makedirs("tools/output", exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = f"tools/output/page-map-{ts}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=2, ensure_ascii=False)
        print(f"   🗺️  Mapa guardado: {path}")

    return mapa


def print_map_summary(mapa: dict) -> None:
    """Imprime un resumen legible del mapa."""
    print(f"\n   🗺️  PAGE MAP — {mapa.get('url', '?')}")
    print(f"   Título: {mapa.get('titulo', '?')}")

    # Obstáculos
    obs = mapa.get("obstaculos", [])
    if obs:
        print(f"\n   🚧 OBSTÁCULOS ({len(obs)}):")
        for o in obs:
            cerrar = f" → cerrar: {o['btn_cerrar']['selector']}" if o.get('btn_cerrar') else ""
            print(f"      - [{o['tipo']}] {o['selector']} {o.get('texto', '')[:50]}{cerrar}")

    # Accionables relevantes (solo visibles y habilitados)
    accs = [a for a in mapa.get("accionables", []) if a.get("visible") and a.get("habilitado")]
    if accs:
        print(f"\n   🎯 ACCIONABLES VISIBLES ({len(accs)}):")
        for a in accs[:25]:
            sel = a.get("selector_id") or a.get("selector_clase") or a.get("selector_data") or "?"
            print(f"      - [{a['tipo']}] \"{a['texto'][:40]}\" → {sel}")

    # Formularios
    forms = mapa.get("formularios", [])
    if forms:
        print(f"\n   📝 FORMULARIOS ({len(forms)}):")
        for f in forms:
            print(f"      - {f['id'][:40]} ({len(f['campos'])} campos)")


def map_and_diagnose(page, context: str = "") -> dict:
    """
    Función principal para usar como fallback en except blocks.
    Mapea la página, imprime resumen y retorna el mapa.
    """
    print(f"\n   🔍 PAGE MAPPER — Diagnosticando bloqueo{' en ' + context if context else ''}...")
    mapa = map_page(page, guardar=True)
    print_map_summary(mapa)
    return mapa
