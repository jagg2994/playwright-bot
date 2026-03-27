# Bot Belcorp GA4 - Instrucciones de uso

## Requisitos previos

```bash
pip install playwright python-dotenv pytz
playwright install chromium
```

## Configuracion

### 1. Credenciales (`.env`)

Crear archivo `.env` en la raiz del proyecto:

```
BELCORP_USER=tu_usuario
BELCORP_PASS=tu_contraseña
BELCORP_COUNTRY=PE
```

Codigos de pais disponibles:

| Codigo | Pais |
|--------|------|
| `BO` | Bolivia |
| `CL` | Chile |
| `CO` | Colombia |
| `CR` | Costa Rica |
| `EC` | Ecuador |
| `SV` | El Salvador |
| `GT` | Guatemala |
| `MX` | Mexico |
| `PA` | Panama |
| `PE` | Peru |
| `PR` | Puerto Rico |
| `DO` | Republica Dominicana |

### 2. Parametros del bot (`config.json`)

Editar `config.json` para cambiar URL, productos de busqueda o dispositivo mobile:

```json
{
  "base_url": "https://www.somosbelcorp.com",
  "credentials": {
    "user_env": "BELCORP_USER",
    "pass_env": "BELCORP_PASS",
    "country_env": "BELCORP_COUNTRY"
  },
  "inputs": {
    "cuv_checkout": "10989",
    "search_term": "nitro",
    "mini_search_term": "vibranza"
  },
  "mobile": {
    "device": "iPhone 13"
  },
  "output": {
    "desktop": "eventos_analytics.json",
    "mobile": "eventos_analytics_mobile.json"
  }
}
```

| Campo | Descripcion |
|-------|-------------|
| `base_url` | URL del sitio a testear |
| `cuv_checkout` | Codigo CUV para el buscador de checkout (flujo 5) |
| `search_term` | Termino de busqueda para search PLP (flujo 6) |
| `mini_search_term` | Termino de busqueda para mini buscador (flujo 7) |
| `mobile.device` | Dispositivo Playwright a emular (ej: `iPhone 13`, `Pixel 5`) |

## Ejecucion

### Desktop - todos los flujos

```bash
python3 bot.py
```

### Desktop - flujos especificos

```bash
python3 bot.py --flujo 1 2 3
python3 bot.py -f 5 7 11
```

### Mobile - todos los flujos

```bash
python3 bot.py --mobile
```

### Mobile - flujos especificos

```bash
python3 bot.py --mobile --flujo 1 5 7
python3 bot.py -m -f 6 7
```

## Flujos disponibles

| # | Flujo | Descripcion |
|---|-------|-------------|
| 1 | Esika PLP + PDP | Gana+ > marca Esika > agregar directo + ir a PDP |
| 2 | Categorias Fragancias | Gana+ > categoria Fragancias > agregar directo + ir a PDP |
| 3 | Carruseles Gana+ | Gana+ > carrusel slick > agregar directo + ir a PDP |
| 4 | Pedido | Pedido > "Lo mas vendido" + "Ofertas recomendadas" > agregar + PDP |
| 5 | Buscador checkout | Pedido > ingresar CUV > ofertas similares + agregar directo |
| 6 | Search PLP | Home > buscador header > "VER MAS RESULTADOS" > PLP > agregar + PDP |
| 7 | Mini buscador | Home > buscador header > agregar desde modal + ir a PDP |
| 8 | Liquidacion PLP | Home > Liquidaciones > PLP > agregar + PDP |
| 9 | Festivales PLP | Home > Festivales > PLP > agregar + PDP |
| 10 | Festivales carrusel | Festivales > carrusel de premios > agregar premio + ir a PDP |
| 11 | Carrusel home | Home > "Las mejores ofertas" > agregar directo + ir a PDP |

## Output

| Archivo | Contenido |
|---------|-----------|
| `eventos_analytics.json` | Eventos GA4 capturados en modo desktop |
| `eventos_analytics_mobile.json` | Eventos GA4 capturados en modo mobile |
| `debug/*.png` | Screenshots automaticos cuando un flujo falla |
| `tools/output/*.json` | Mapas de pagina generados en bloqueos |

Cada evento en el JSON tiene un campo `flow` que indica de que flujo proviene (ej: `esika_plp_pdp_flow`, `buscador_checkout_flow_mobile`).

## Ejemplos de uso comun

```bash
# Probar solo el buscador de checkout en desktop
python3 bot.py -f 5

# Probar flujos de busqueda en mobile
python3 bot.py -m -f 6 7

# Probar todos los flujos de PLP
python3 bot.py -f 1 2 8 9

# Probar carruseles en mobile
python3 bot.py -m -f 3 10 11

# Ejecutar todo (desktop)
python3 bot.py

# Ejecutar todo (mobile)
python3 bot.py -m
```

## Solucion de problemas

- **El bot no encuentra productos**: Puede que todos ya esten agregados de ejecuciones anteriores. El bot automaticamente salta productos ya agregados.
- **TargetClosedError**: El bot tiene recovery automatico — recrea la sesion y continua con el siguiente flujo.
- **Screenshots en `debug/`**: Cuando un flujo falla se guarda screenshot + mapa de pagina para diagnostico.
- **Cambiar URL de prueba**: Editar `base_url` en `config.json`.
- **Cambiar productos de busqueda**: Editar `inputs` en `config.json`.
