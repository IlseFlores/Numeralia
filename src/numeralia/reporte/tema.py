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
COLOR_NEGRO  = '#000000'   # rótulos que van en negro pleno, no en el casi-negro
COLOR_BLANCO = '#ffffff'   # rótulos encima de un relleno oscuro

# ── Paleta de marca ─────────────────────────────────────────────────────────
# Solo estos 3 colores; el resto son tintes/sombras derivados de ellos.
COLOR_GRIS         = '#999d9e'   # neutro / estructura
COLOR_ANIO_PREVIO  = '#465055'   # azul marino — año contra el que se compara 191970
COLOR_ANIO_ACTUAL  = '#4DC2B3'   # aqua/teal — año que se reporta

# Alias históricos. Se conservan mientras el dashboard siga nombrando los años
# a mano; al migrar la sección de reporte deben desaparecer.
COLOR_2025 = COLOR_ANIO_PREVIO
COLOR_2026 = COLOR_ANIO_ACTUAL

COLOR_GOOD = COLOR_ANIO_ACTUAL  # mapa: mejora (menos días de mala calidad)
COLOR_BAD  = COLOR_ANIO_PREVIO  # mapa: empeora (más días de mala calidad)

COLOR_GRIS_50   = '#f4f5f5'
COLOR_GRIS_100  = '#e6e8e9'
COLOR_GRIS_MUTE = '#70767c'   # gris de las explicaciones, un tono más oscuro


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



def hex_a_rgb(color_hex: str) -> tuple:
    """
    Convierte '#465055' a (70, 80, 85).

    fpdf2 pide los colores en tripletas de enteros, así que sin esto los
    colores del PDF terminan escritos a mano y se desincronizan del tema:
    fue exactamente lo que pasó cuando el gris tenue cambió de tono y el PDF
    se quedó con el viejo.
    """
    crudo = color_hex.lstrip('#')
    return tuple(int(crudo[i:i + 2], 16) for i in (0, 2, 4))


def _luminancia(color_hex: str) -> float:
    """Luminancia percibida de 0 (negro) a 1 (blanco)."""
    crudo = color_hex.lstrip('#')
    r, g, b = (int(crudo[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def escala_serie_oscura(color_hex: str, n: int = 3, piso: float = 0.62) -> list:
    """
    ``n`` tonos del mismo color arrancando en el color pleno, para rellenos
    oscuros con la etiqueta en blanco encima.

    Es la contraparte de ``escala_serie``: esa parte de un tinte casi blanco
    y oscurece, pensada para texto oscuro encima. Aquí el primer tono ES el
    color de marca sin mezclar y los siguientes se aclaran solo hasta
    ``piso``, que se queda alto a propósito — si la escala llegara a tintes
    claros, el texto blanco desaparecería en los últimos segmentos.

    Por eso el rango es corto: el compromiso es a favor de que la etiqueta se
    lea siempre, y de que el color del año se reconozca de inmediato.
    """
    if n < 1:
        raise ValueError(f"Se necesita al menos un tono, se pidieron {n}.")
    if n == 1:
        return [color_hex]

    paso = (1.0 - piso) / (n - 1)
    return [tinte(color_hex, 1.0 - paso * i) for i in range(n)]


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

# Escala del año previo en las barras de episodios: arranca en el azul marino
# pleno y se aclara hacia arriba, con las etiquetas en blanco encima. Así la
# barra del año previo se reconoce por su color de marca de un golpe de vista,
# que es justo lo que la escala clara no lograba.
#
# El piso queda en el 0.62 por omisión: deja los tres tonos con contraste
# 14.8 / 8.5 / 4.6 contra blanco, todos por encima del mínimo AA de 4.5.
# Antes era 0.5, que aclaraba más el tono de arriba pero lo dejaba en 3.2 y
# la etiqueta se perdía sobre él.
ESCALA_EPISODIOS_ANIO_PREVIO = escala_serie_oscura(COLOR_ANIO_PREVIO)

# Escala del año actual en esas mismas barras, más clara que la general. En
# esa gráfica el número de cada segmento va en el color pleno del año, y con
# la escala normal el tono más oscuro ES ese mismo color: el número quedaba
# aqua sobre aqua, invisible.
#
# El 0.87 no es arbitrario: deja el relleno más oscuro 0.25 de luminancia por
# encima del aqua del número, la misma holgura que el azul del año previo
# tiene contra su propio relleno. Así las dos barras se leen igual de bien.
# El costo es que los tres tonos del año actual quedan más parecidos entre
# sí; la leyenda es la que carga con distinguir los contaminantes.
ESCALA_EPISODIOS_ANIO_ACTUAL = escala_serie(COLOR_ANIO_ACTUAL, luminancia_minima=0.100)

# ── Severidad de episodios ──────────────────────────────────────────────────
# Precontingencia -> Fase I -> Fase II -> Fase III.
SEVERIDAD_TINTES = {
    1: '#FFB300',   # Precontingencia atmosférica
    2: '#EF6C00',   # Contingencia atmosférica Fase I
    3: '#FC3508',   # Contingencia atmosférica Fase II
    4: '#3d0082',   # Contingencia atmosférica Fase III
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
