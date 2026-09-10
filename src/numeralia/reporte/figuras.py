"""
Figuras de Plotly del dashboard: el mapa comparativo por estación y la serie
de tiempo mensual acumulada. Reciben un DataFrame y devuelven un
``go.Figure`` / ``px`` — no leen de Google Sheets.

Salieron de main.py (Sección 6) en el Paso 2 del refactor.
"""

import base64

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from numeralia.reporte.formato import (
    BUENA_25,
    BUENA_26,
    MALA_25,
    MALA_26,
    _MESES_NOMBRE,
    _normalizar_mes,
)
from numeralia.reporte.tema import (
    COLOR_2025,
    COLOR_2026,
    COLOR_BAD,
    COLOR_GOOD,
    PLOTLY_TEMPLATE,
)


def _tendencia_buena(row) -> str:
    """Misma lógica que la columna 'Tendencia' de tu reporte en PDF: compara
    los días con buena/aceptable calidad, no los de mala calidad."""
    delta = row[BUENA_26] - row[BUENA_25]
    if delta > 0:
        return '▲ mejora'
    if delta < 0:
        return '▼ empeora'
    return '● sin cambio'


def _fig_mapa(df: pd.DataFrame):
    d = df.copy()
    d['cambio_mala'] = d[MALA_26] - d[MALA_25]
    d['abs_cambio'] = d['cambio_mala'].abs()
    d['tendencia'] = d.apply(_tendencia_buena, axis=1)

    fig = px.scatter_map(
        d, lat='Latitud', lon='Longitud',
        color='cambio_mala', size='abs_cambio',
        color_continuous_scale=[[0, COLOR_GOOD], [0.5, '#d1d5db'], [1, COLOR_BAD]],
        range_color=[-d['abs_cambio'].max(), d['abs_cambio'].max()],
        hover_name='Estación',
        custom_data=[d[BUENA_26], d['Estación']],
        # Sin 'height': el alto lo pone el contenedor desde CSS, que es lo que
        # permite achicarlo en tablet y celular sin tocar Python. La imagen
        # para el PDF se genera aparte con medidas explícitas
        # (_fig_a_base64), así que no depende de esto.
        size_max=30, zoom=10.3,
        labels={'cambio_mala': 'Cambio días mala calidad'},
    )
    # Etiquetas de nombre sobre cada burbuja + hover con días buena/aceptable.
    # mode='markers+text' agrega el texto directamente al trace sin crear
    # uno adicional, lo que mantiene un solo curveNumber en hoverData.
    fig.update_traces(
        text=d['Estación'].tolist(),
        textposition='top center',
        textfont=dict(size=12, color='#2d3436', weight='bold'),
        mode='markers+text',
        hovertemplate="<b>%{customdata[1]}</b><br>Días buena/aceptable 2026: %{customdata[0]}<extra></extra>",
    )

    # Centro explícito: el auto-fit de plotly.js para el trace 'map' (maplibre)
    # no siempre calcula el centro a partir de los datos, y sin esto el mapa
    # cae en lat=0/lon=0 (medio del océano) en vez de Jalisco.
    fig.update_layout(map_style='carto-positron', template=PLOTLY_TEMPLATE,
                       coloraxis_showscale=False,
                       map=dict(center=dict(lat=d['Latitud'].mean(), lon=d['Longitud'].mean())),
                       margin=dict(l=0, r=0, t=10, b=0))
    return fig


def _fig_a_base64(fig, ancho: int = 1000, alto: int = 520):
    """
    Renderiza una figura de Plotly a PNG desde Python (con kaleido) y la
    devuelve como data URI.

    Esto existe por el mapa: en el navegador se dibuja con WebGL y su canvas
    no se puede leer de forma confiable —el buffer se vacía tras pintar y los
    mosaicos de CARTO vienen de otro dominio, lo que lo "contamina"—, así que
    capturarlo desde JavaScript falla. Generando la imagen aquí, del lado del
    servidor, el PDF recibe una foto fija del mapa sin depender de nada del
    navegador.

    Si kaleido no está instalado devuelve None y el PDF cae al método de
    captura por JavaScript, que puede o no funcionar.
    """
    try:
        datos = fig.to_image(format='png', width=ancho, height=alto, scale=1.5)
        return 'data:image/png;base64,' + base64.b64encode(datos).decode('ascii')
    except Exception as e:
        print(f"Nota: No se pudo pre-generar la imagen del mapa para el PDF: {e}")
        print("  Instala kaleido si quieres el mapa en el PDF:  %pip install kaleido -q")
        return None


def _fig_serie_buena_mensual(df_resumen: pd.DataFrame):
    """
    Serie de tiempo mensual ACUMULADA (2025 azul marino vs 2026 aqua) de días
    con buena/aceptable calidad IAS. Lee columnas A-C de 'Resumen MENSUAL'
    por posición (AÑO, MES, GLOBAL BUENA O ACEPTABLE IAS).

    La línea es acumulada: cada mes muestra el total del año hasta ese mes,
    por eso nunca baja. Los meses que aún no tienen dato en Sheets se cortan
    al final, así la línea de 2026 se extiende sola conforme se capturan.

    Arriba de la gráfica va un cintillo con dos pastillas por mes (2026
    encima, 2025 debajo) con el acumulado de cada año. Las pastillas se
    dibujan como 'shapes' con trazado propio porque las anotaciones de
    Plotly no admiten esquinas redondeadas ni ancho fijo; el número va
    encima como anotación sin fondo.
    """
    cols = list(df_resumen.columns)
    fig = go.Figure()
    if len(cols) < 3:
        fig.update_layout(template=PLOTLY_TEMPLATE,
                           margin=dict(l=60, r=20, t=20, b=50))
        return fig

    col_anio, col_mes, col_buena = cols[0], cols[1], cols[2]
    base = df_resumen[[col_anio, col_mes, col_buena]].copy()
    base['_anio'] = pd.to_numeric(base[col_anio], errors='coerce')
    base[['_mes_num', '_mes_nombre']] = base[col_mes].apply(lambda v: pd.Series(_normalizar_mes(v)))
    base['_valor'] = pd.to_numeric(base[col_buena], errors='coerce')
    base = base.dropna(subset=['_mes_num'])

    anotaciones = []
    figuras = []
    ALTURA_CINTILLO = {2026: 1.22, 2025: 1.08}

    ANCHO_PASTILLA = 0.12      # en unidades de categoría (medio ancho)
    ALTO_PASTILLA = 0.05       # en fracción del alto del lienzo
    # El radio va en las mismas unidades mixtas que la pastilla, así que para
    # que la curva se vea igual en las cuatro esquinas hay que convertirlo a
    # píxeles por separado en cada eje: una unidad de categoría mide
    # ancho_del_área/12 px y una de 'paper' mide el alto de la figura (330 px).
    # Con RADIO_X = 0.10 el radio se comía el 83% del medio ancho, no quedaba
    # tramo recto en los lados y la pastilla salía abombada en vez de
    # rectangular.
    RADIO_X, RADIO_Y = 0.055, 0.016

    def _pastilla(cx, cy, color):
        """Rectángulo con esquinas redondeadas, en coordenadas mixtas:
        X en unidades del eje categórico, Y en fracción del lienzo."""
        x0, x1 = cx - ANCHO_PASTILLA, cx + ANCHO_PASTILLA
        y0, y1 = cy - ALTO_PASTILLA, cy + ALTO_PASTILLA
        return dict(
            type='path', xref='x', yref='paper', layer='above',
            path=(f'M {x0 + RADIO_X},{y0} L {x1 - RADIO_X},{y0} '
                  f'Q {x1},{y0} {x1},{y0 + RADIO_Y} '
                  f'L {x1},{y1 - RADIO_Y} Q {x1},{y1} {x1 - RADIO_X},{y1} '
                  f'L {x0 + RADIO_X},{y1} Q {x0},{y1} {x0},{y1 - RADIO_Y} '
                  f'L {x0},{y0 + RADIO_Y} Q {x0},{y0} {x0 + RADIO_X},{y0} Z'),
            fillcolor=color, line=dict(width=0),
        )

    # Hasta qué mes llega la gráfica: el último mes con dato en 2026.
    # Cuando el mes siguiente tenga registro, el rango crece automáticamente.
    # Si 2026 no tiene ningún dato aún, se muestran todos los meses.
    d_2026_check = base[(base['_anio'] == 2026) & base['_valor'].notna()]
    ultimo_mes_2026 = int(d_2026_check['_mes_num'].max()) if not d_2026_check.empty else 12

    for anio, color in [(2025, COLOR_2025), (2026, COLOR_2026)]:
        # Solo se incluyen los meses hasta el último con dato en 2026
        d = base[
            (base['_anio'] == anio) &
            base['_valor'].notna() &
            (base['_mes_num'] <= ultimo_mes_2026)
        ].sort_values('_mes_num')
        if d.empty:
            continue
        # cumsum() convierte el valor mensual en acumulado del año a la fecha.
        d = d.assign(_acumulado=d['_valor'].cumsum())
        fig.add_trace(go.Scatter(
            x=d['_mes_nombre'], y=d['_acumulado'],
            mode='lines+markers',
            name=str(anio),
            line=dict(color=color, width=4, shape='linear'),
            marker=dict(color=color, size=10, line=dict(color='#ffffff', width=1)),
            hovertemplate=f'%{{y}} días acumulados <br> hasta %{{x}} {anio}<extra></extra>',
        ))

        alto = ALTURA_CINTILLO[anio]
        for mes_num, mes, acumulado in zip(d['_mes_num'], d['_mes_nombre'], d['_acumulado']):
            # El eje X es categórico y el categoryarray de abajo fija que el
            # mes N viva en la posición N-1, que es lo que ubica la pastilla.
            figuras.append(_pastilla(int(mes_num) - 1, alto, color))
            anotaciones.append(dict(
                x=mes, xref='x',
                y=alto, yref='paper',
                text=f'<b>{int(acumulado)}</b>',
                showarrow=False, font=dict(size=13, color='#ffffff'),
                # Sin el anclaje explícito, Plotly pega la anotación al borde
                # y el número queda cortado a media pastilla.
                xanchor='center', yanchor='middle', yshift=0,
            ))

    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        # El alto lo pone el contenedor desde CSS (ver .grafica-serie-mensual
        # en assets/responsive.css). Ojo: el cintillo se posiciona en fracción
        # del lienzo ('paper'), así que su alto en píxeles sigue al del
        # contenedor — que es justo lo que queremos.
        margin=dict(l=60, r=20, t=95, b=50),
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.30, xanchor='right', x=1,
                    font=dict(size=14)),
        annotations=anotaciones,
        shapes=figuras,
        plot_bgcolor='#ffffff',
        paper_bgcolor='#ffffff',
        yaxis=dict(title=dict(text='Días acumulados', standoff=14), rangemode='tozero',
                    showgrid=True, gridcolor='#eef0f3', zeroline=False, showline=False,
                    ticks='', automargin=True, tickfont=dict(size=14)),
        xaxis=dict(title=None, showgrid=False, zeroline=False, showline=True,
                    linecolor='#d7dbe2', ticks='', automargin=True, tickfont=dict(size=14),
                    categoryorder='array',
                    # El eje se extiende solo hasta el último mes con dato en 2026
                    categoryarray=[_MESES_NOMBRE[i] for i in range(1, ultimo_mes_2026 + 1)]),
    )
    return fig
