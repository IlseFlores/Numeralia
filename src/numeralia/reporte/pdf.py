"""
Generación de los PDF de bitácora (Alertas y Episodios).

Vivía anidado dentro de ``build_dash_app``, una función de 867 líneas que
construye una aplicación web: armar un PDF con fpdf2 no tiene nada que ver
con eso. Aquí las funciones son puras —reciben un DataFrame, devuelven la
ruta de un archivo— y se pueden probar sin levantar el dashboard.

Los colores salen de ``tema.py`` en vez de ir escritos como tripletas RGB:
así un cambio de paleta llega también al PDF, que es justo lo que no pasaba
antes.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd
from fpdf import FPDF
from fpdf.enums import XPos, YPos

try:
    from PIL import Image as _Image
except Exception:  # pragma: no cover - PIL siempre está disponible con fpdf2
    _Image = None

from .tema import COLOR_GRIS, COLOR_GRIS_MUTE, hex_a_rgb

# Medidas de la hoja, en milímetros.
MARGEN_PAGINA = 20
MARGEN_CELDA = 3
ANCHO_MAX_COLUMNA = 45
ANCHO_MIN_COLUMNA = 8
ALTO_FILA = 6
ALTO_ENCABEZADO = 7
TAMANO_LETRA_TABLA = 6
ALTO_LOGO_PDF = 12


def _ancho_logo(ruta: str, h: float) -> float:
    """Ancho proporcional a una altura fija, en milímetros."""
    if _Image is None or not os.path.exists(ruta):
        return 0.0
    try:
        with _Image.open(ruta) as img:
            ancho, alto = img.size
        return ancho * h / alto
    except Exception:
        return 0.0


def _sin_acentos_latin1(texto: str) -> str:
    """
    Sustituye lo que no cabe en latin-1, que es lo único que digiere fpdf2
    con las fuentes básicas. Sin esto, un carácter suelto tumba el PDF entero.
    """
    return texto.encode('latin-1', errors='replace').decode('latin-1')


def _recortar_al_ancho(pdf: FPDF, texto: str, ancho: float, holgura: float = 1) -> str:
    """Recorta por ancho real en mm, no por número de caracteres."""
    recortado = _sin_acentos_latin1(str(texto))
    while pdf.get_string_width(recortado) > ancho - holgura and len(recortado) > 1:
        recortado = recortado[:-1]
    return recortado


def anchos_proporcionales(pdf: FPDF, df: pd.DataFrame,
                          tamano_letra: int = TAMANO_LETRA_TABLA) -> list:
    """
    Reparte el ancho de la página entre las columnas, según su contenido.

    Se mide el ancho REAL del texto en mm (``get_string_width``) en vez de
    contar caracteres, porque no todos miden lo mismo. Además cada columna
    tiene un ancho MÍNIMO garantizado: sin eso, una columna corta como 'No'
    recibía tan poco espacio que el recorte le comía dígitos y '46' salía
    como '4'.
    """
    ancho_pagina = pdf.w - MARGEN_PAGINA

    # Medir SIEMPRE sobre el texto ya saneado: get_string_width codifica a
    # latin-1 por dentro y revienta con cualquier carácter que no quepa. Una
    # comilla curva o un guion largo —lo que mete Word al copiar y pegar—
    # bastaban para tumbar la descarga del PDF.
    valores = {c: [_sin_acentos_latin1(v) for v in df[c].astype(str)]
               for c in df.columns}

    # 1) Lo que necesitaría cada columna para no recortar nada.
    deseados = []
    for c in df.columns:
        pdf.set_font('Helvetica', 'B', tamano_letra)
        ancho = pdf.get_string_width(_sin_acentos_latin1(str(c)))
        pdf.set_font('Helvetica', '', tamano_letra)
        for v in valores[c]:
            ancho = max(ancho, pdf.get_string_width(v))
        deseados.append(min(ancho + MARGEN_CELDA, ANCHO_MAX_COLUMNA))

    # 2) Piso por columna: lo que ocupa su valor más largo, o el mínimo.
    pdf.set_font('Helvetica', '', tamano_letra)
    minimos = []
    for c in df.columns:
        mas_largo = max((pdf.get_string_width(v) for v in valores[c]), default=0)
        minimos.append(min(max(float(ANCHO_MIN_COLUMNA), mas_largo + MARGEN_CELDA),
                           ANCHO_MAX_COLUMNA))

    total = sum(deseados) or 1
    if total <= ancho_pagina:
        factor = ancho_pagina / total
        return [d * factor for d in deseados]

    # 3) No cabe todo: se respetan los mínimos y se reparte el sobrante.
    piso = sum(minimos)
    if piso >= ancho_pagina:
        return [ancho_pagina * (m / piso) for m in minimos]

    sobrante = ancho_pagina - piso
    extra_deseado = [max(0.0, d - m) for d, m in zip(deseados, minimos)]
    total_extra = sum(extra_deseado) or 1
    return [m + sobrante * (e / total_extra)
            for m, e in zip(minimos, extra_deseado)]


def generar_pdf_tabla(df: pd.DataFrame, titulo: str, subtitulo: str = '',
                      logo_izq: str | None = None, logo_der: str | None = None) -> str:
    """
    Escribe la tabla completa en un PDF horizontal y devuelve su ruta.

    El archivo queda en el directorio temporal del sistema; quien lo entrega
    (``dcc.send_file``) se encarga de servirlo.
    """
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    if logo_izq:
        ancho = _ancho_logo(logo_izq, ALTO_LOGO_PDF)
        if ancho:
            pdf.image(logo_izq, x=pdf.l_margin, y=pdf.t_margin,
                      h=ALTO_LOGO_PDF)
    if logo_der:
        ancho = _ancho_logo(logo_der, ALTO_LOGO_PDF)
        if ancho:
            pdf.image(logo_der, x=pdf.w - pdf.r_margin - ancho,
                      y=pdf.t_margin, h=ALTO_LOGO_PDF)

    # Deja un pequeño respiro entre los logos y el título/subtítulo.
    y_inicio_titulo = (pdf.t_margin + ALTO_LOGO_PDF + 3
                       if (logo_izq or logo_der) else pdf.t_margin)
    pdf.set_y(y_inicio_titulo)

    pdf.set_font('Helvetica', 'B', 14)
    pdf.set_text_color(*hex_a_rgb(COLOR_GRIS))
    pdf.cell(0, 10, _sin_acentos_latin1(titulo), align='C',
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if subtitulo:
        # Mismo gris tenue que el subtítulo de la tarjeta en el dashboard.
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(*hex_a_rgb(COLOR_GRIS_MUTE))
        pdf.multi_cell(0, 5, _sin_acentos_latin1(subtitulo), align='C')

    pdf.ln(3)

    cols = list(df.columns)
    anchos = anchos_proporcionales(pdf, df)

    def _encabezados():
        pdf.set_font('Helvetica', 'B', TAMANO_LETRA_TABLA)
        pdf.set_fill_color(*hex_a_rgb(COLOR_GRIS))
        pdf.set_text_color(255, 255, 255)
        for i, c in enumerate(cols):
            pdf.cell(anchos[i], ALTO_ENCABEZADO, _recortar_al_ancho(pdf, c, anchos[i]),
                     border=1, fill=True, align='C')
        pdf.ln()
        pdf.set_font('Helvetica', '', TAMANO_LETRA_TABLA)
        pdf.set_text_color(50, 50, 50)

    _encabezados()

    for _, row in df.iterrows():
        # Salto de página manual para poder repetir los encabezados arriba.
        if pdf.get_y() + ALTO_FILA > pdf.h - 15:
            pdf.add_page()
            _encabezados()
        for i, c in enumerate(cols):
            pdf.cell(anchos[i], ALTO_FILA,
                     _recortar_al_ancho(pdf, row[c], anchos[i], holgura=2),
                     border=1, align='C')
        pdf.ln()

    # mkstemp y no mktemp: este último está obsoleto y deja una ventana entre
    # que devuelve el nombre y que alguien lo crea.
    fd, ruta = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    pdf.output(ruta)
    return ruta


@dataclass(frozen=True)
class DescargaPDF:
    """Una bitácora descargable: qué tabla, con qué títulos y por qué botón."""

    df: pd.DataFrame
    titulo: str
    subtitulo: str
    archivo: str
    boton_id: str
    descarga_id: str
    logo_izq: str | None = None
    logo_der: str | None = None


def registrar_descargas(app, descargas: Sequence[DescargaPDF]) -> None:
    """
    Cuelga de ``app`` un callback por cada bitácora descargable.

    Antes eran dos callbacks casi idénticos escritos a mano; agregar una
    tercera bitácora era copiar y pegar. Aquí se declaran como datos.
    """
    from dash import Input, Output, dcc

    for descarga in descargas:
        def _hacer(d: DescargaPDF):
            # Fábrica para que cada callback capture SU descarga: sin esto,
            # todos se quedarían con la última del bucle.
            def _descargar(_n_clicks):
                ruta = generar_pdf_tabla(d.df, d.titulo, d.subtitulo,
                                          d.logo_izq, d.logo_der)
                return dcc.send_file(ruta, filename=d.archivo)
            return _descargar

        app.callback(
            Output(descarga.descarga_id, 'data'),
            Input(descarga.boton_id, 'n_clicks'),
            prevent_initial_call=True,
        )(_hacer(descarga))
