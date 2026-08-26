"""
Paleta, plantilla de Plotly y estilos de tarjeta del reporte.

Antes esto vivía en dos bloques lejanos: unos colores en la sección de
cálculo IAS (línea ~706) y el resto en la del dashboard (~1761). Aquí está
todo junto, que es lo que permite cambiar la identidad visual sin abrir el
código de cálculo.

Sobre los años: los colores oficiales son "año previo" y "año actual", no
2025 y 2026. Los alias con año siguen existiendo para no romper el código
que aún los usa, pero lo nuevo debe usar los nombres genéricos.
"""

from __future__ import annotations

import plotly.graph_objects as go

# ── Superficies y texto ─────────────────────────────────────────────────────
COLOR_BG     = '#ffffff'
COLOR_CARD   = '#ffffff'
COLOR_BORDER = '#e4e7ec'
COLOR_TEXT   = '#1a1d24'
COLOR_MUTED  = '#6b7280'

# ── Paleta de marca ─────────────────────────────────────────────────────────
# Solo estos 3 colores; el resto son tintes/sombras derivados de ellos.
COLOR_GRIS         = '#465055'   # neutro / estructura
COLOR_ANIO_PREVIO  = '#191970'   # azul marino — año contra el que se compara
COLOR_ANIO_ACTUAL  = '#4DC2B3'   # aqua/teal — año que se reporta

# Alias históricos. Se conservan mientras el dashboard siga nombrando los años
# a mano; al migrar la sección de reporte deben desaparecer.
COLOR_2025 = COLOR_ANIO_PREVIO
COLOR_2026 = COLOR_ANIO_ACTUAL

COLOR_GOOD = COLOR_ANIO_ACTUAL  # mapa: mejora (menos días de mala calidad)
COLOR_BAD  = COLOR_ANIO_PREVIO  # mapa: empeora (más días de mala calidad)

COLOR_GRIS_50   = '#f4f5f5'
COLOR_GRIS_100  = '#e6e8e9'
COLOR_GRIS_MUTE = '#8a9096'


def tinte(color_hex: str, proporcion: float = 0.12) -> str:
    """
    Mezcla un color de marca con blanco y devuelve el hex resultante.

    Sirve para los rellenos: la barra se pinta con el tinte claro y se
    contornea con el color pleno, así el color del año se lee sin que el
    texto de encima pierda contraste. ``proporcion`` es cuánto del color
    original queda (0.12 = 12% de color, 88% de blanco).
    """
    crudo = color_hex.lstrip('#')
    canales = (int(crudo[i:i + 2], 16) for i in (0, 2, 4))
    mezcla = (round(c * proporcion + 255 * (1 - proporcion)) for c in canales)
    return '#' + ''.join(f'{c:02x}' for c in mezcla)


# Rellenos claros de cada año, derivados de los colores de marca.
COLOR_ANIO_PREVIO_TINTE = tinte(COLOR_ANIO_PREVIO)
COLOR_ANIO_ACTUAL_TINTE = tinte(COLOR_ANIO_ACTUAL)


def _luminancia(color_hex: str) -> float:
    """Luminancia percibida de 0 (negro) a 1 (blanco)."""
    crudo = color_hex.lstrip('#')
    r, g, b = (int(crudo[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def color_textura(color_hex: str, luminancia_minima: float = 0.6) -> str:
    """
    Aclara un color solo lo necesario para que sirva de trama detrás de texto.

    Una trama diagonal densa en un color oscuro se traga la etiqueta que va
    encima. Los colores que ya son claros (el aqua del año actual) se
    devuelven sin tocar; los oscuros (el azul marino) se mezclan con blanco
    hasta alcanzar la luminancia mínima.
    """
    lum = _luminancia(color_hex)
    if lum >= luminancia_minima:
        return color_hex
    return tinte(color_hex, (1 - luminancia_minima) / (1 - lum))


# Color de la trama de cada año: legible detrás de las etiquetas de la barra.
COLOR_ANIO_PREVIO_TEXTURA = color_textura(COLOR_ANIO_PREVIO)
COLOR_ANIO_ACTUAL_TEXTURA = color_textura(COLOR_ANIO_ACTUAL)


def color_texto(color_hex: str, luminancia_maxima: float = 0.42) -> str:
    """
    Oscurece un color solo lo necesario para que sirva de texto sobre blanco.

    Los colores de severidad están pensados como RELLENO: el ámbar #FFB300
    tiene luminancia 0.71, así que como texto sobre blanco se ve lavado y
    apenas se lee. Escalar los tres canales por igual oscurece el color sin
    moverle el tono, porque conserva la proporción entre ellos.
    """
    lum = _luminancia(color_hex)
    if lum <= luminancia_maxima:
        return color_hex
    factor = luminancia_maxima / lum
    crudo = color_hex.lstrip('#')
    canales = (int(crudo[i:i + 2], 16) for i in (0, 2, 4))
    return '#' + ''.join(f'{round(c * factor):02x}' for c in canales)


def escala_serie(color_hex: str, n: int = 3, luminancia_minima: float = 0.6) -> list:
    """
    ``n`` tonos del mismo color, del más claro al más oscuro.

    Sirve para distinguir las subcategorías apiladas de una barra sin recurrir
    a tramas: cada segmento es un tono distinto del color de su año. El tono
    más oscuro se topa en ``luminancia_minima`` para que la etiqueta que va
    encima siga leyéndose, y por eso un color ya oscuro (el azul marino) da
    una escala más comprimida que uno claro (el aqua).

    Los tonos sobreviven a la impresión en blanco y negro, porque distinta
    luminancia se traduce en distinto gris.
    """
    if n < 1:
        raise ValueError(f"Se necesita al menos un tono, se pidieron {n}.")

    lum = _luminancia(color_hex)
    # Proporción de color del tono más oscuro que aún deja leer el texto.
    tope = 1.0 if lum >= luminancia_minima else (1 - luminancia_minima) / (1 - lum)
    piso = 0.14

    if n == 1:
        return [tinte(color_hex, tope)]
    paso = (tope - piso) / (n - 1)
    return [tinte(color_hex, piso + paso * i) for i in range(n)]


# Escalas de cada año, en el orden en que se apilan los contaminantes.
ESCALA_ANIO_PREVIO = escala_serie(COLOR_ANIO_PREVIO)
ESCALA_ANIO_ACTUAL = escala_serie(COLOR_ANIO_ACTUAL)

# ── Colores por categoría del IAS ───────────────────────────────────────────
# Nota: hoy el dashboard no los usa (dibuja por año, no por categoría). Se
# conservan porque son la codificación oficial de la NOM-172.
IAS_COLORS = {
    "Buena": "#2ecc71", "Aceptable": "#f1c40f",
    "Mala":  "#e67e22", "Muy mala":  "#e74c3c",
    "Extremadamente mala": "#8e44ad",
}
NOM_COLORS = {"Si": "#2ecc71", "No": "#e74c3c"}

# Paleta institucional previa. Sin uso actual en el reporte.
AZUL_SEMADET    = '#4DC283'
NARANJA_SEMADET = '#ff8300'
GRIS_SEMADET    = '#465055'

# ── Severidad de episodios ──────────────────────────────────────────────────
# Precontingencia -> Fase I -> Fase II -> Fase III.
SEVERIDAD_TINTES = {
    1: '#FFB300',   # Precontingencia atmosférica
    2: '#EF6C00',   # Contingencia atmosférica Fase I
    3: '#DC143C',   # Contingencia atmosférica Fase II
    4: '#4B0082',   # Contingencia atmosférica Fase III
}

# ── Plotly ──────────────────────────────────────────────────────────────────
PLOTLY_TEMPLATE = go.layout.Template(
    layout=dict(
        paper_bgcolor=COLOR_CARD,
        plot_bgcolor=COLOR_CARD,
        font=dict(family='Inter, Segoe UI, sans-serif', color=COLOR_TEXT, size=13),
        colorway=[COLOR_ANIO_ACTUAL, COLOR_ANIO_PREVIO, COLOR_GRIS],
        xaxis=dict(gridcolor='#eef0f3', zerolinecolor='#d7dbe2', linecolor='#d7dbe2'),
        yaxis=dict(gridcolor='#eef0f3', zerolinecolor='#d7dbe2', linecolor='#d7dbe2'),
        legend=dict(bgcolor='rgba(0,0,0,0)'),
        margin=dict(l=40, r=20, t=50, b=40),
    )
)

CARD_STYLE = {
    'backgroundColor': COLOR_CARD,
    'border': f'1px solid {COLOR_BORDER}',
    'borderRadius': '12px',
    'padding': '20px',
    # Misma sombra que las fichas KPI, para que todas las tarjetas del
    # dashboard se sientan del mismo material.
    'boxShadow': '0 1px 2px rgba(70,80,85,0.06), 0 6px 16px rgba(70,80,85,0.08)',
}

# ── Medidas ─────────────────────────────────────────────────────────────────
# Alto de las gráficas de episodios. Está igualado a la tabla comparativa que
# va a su izquierda (13 filas ≈ 450 px) para que las dos mitades del bloque
# terminen parejas.
ALTO_GRAFICA_EPISODIOS = '450px'


# ── Logos del encabezado ────────────────────────────────────────────────────
NOMBRE_CARPETA_LOGOS = 'logos'
LOGO_SIMAJ   = 'logo simaj (1).png'
LOGO_SEMADET = 'SemadetGobJal_transp (1).png'
ALTO_LOGO    = '77px'
