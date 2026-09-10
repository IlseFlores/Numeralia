"""
Tablas del dashboard: detalle por estación (panel del mapa), comparativo de
episodios con acordeón, comparativo de alertas, parámetros del SIMAJ y la
tabla paginada de las bitácoras.

Reciben DataFrames y devuelven componentes de Dash; no leen de Google Sheets.

Salieron de main.py (Sección 6) en el Paso 2 del refactor.
"""

import pandas as pd
from dash import dash_table, html

from numeralia.reporte.datos_graficas import _EPISODIOS_ENCABEZADOS
from numeralia.reporte.formato import (
    BUENA_25,
    BUENA_26,
    MALA_25,
    MALA_26,
    SINDATO_25,
    SINDATO_26,
)
from numeralia.reporte.kpis import _KPI_PIE
from numeralia.reporte.tema import (
    COLOR_2025,
    COLOR_2026,
    COLOR_GRIS_50,
    COLOR_GRIS_100,
    COLOR_GRIS_MUTE,
    SEVERIDAD_TINTES as _SEVERIDAD_TINTES,
)


def _detalle_placeholder():
    """
    Estado vacío del panel: se centra vertical y horizontalmente en el
    espacio que queda bajo el encabezado, para que no se lea como si fuera
    otra línea más de la aclaración de arriba.
    """
    return html.Div(
        html.Div('Pasa el cursor sobre una estación del mapa '
                 'para ver su comparativo 2025 vs 2026.',
                 style={'maxWidth': '220px', 'lineHeight': '1.5'}),
        style={'color': COLOR_GRIS_MUTE, 'fontSize': '14px', 'textAlign': 'center',
               'minHeight': '180px', 'display': 'flex',
               'alignItems': 'center', 'justifyContent': 'center'},
    )


def _tabla_detalle_estacion(estacion: str, row: pd.Series):
    """Tabla real (no tooltip) con los años como columnas, para el panel lateral del mapa."""
    filas_datos = [
        ('Días buena / aceptable', row[BUENA_25], row[BUENA_26]),
        ('Días con mala calidad', row[MALA_25], row[MALA_26]),
        ('Días sin dato', row[SINDATO_25], row[SINDATO_26]),
    ]

    encabezado = html.Tr([
        html.Th('', style={'backgroundColor': COLOR_GRIS_50, 'padding': '8px 10px'}),
        html.Th('2025', style={'backgroundColor': COLOR_2025, 'color': '#fff', 'padding': '8px 10px'}),
        html.Th('2026', style={'backgroundColor': COLOR_2026, 'color': '#fff', 'padding': '8px 10px'}),
    ])
    filas = [
        html.Tr([
            html.Td(label, style={'padding': '7px 10px', 'color': COLOR_GRIS_MUTE, 'fontSize': '15px',
                                   'backgroundColor': COLOR_GRIS_50}),
            html.Td(v25, style={'padding': '7px 10px', 'textAlign': 'center', 'fontWeight': '700',
                                 'color': COLOR_GRIS_MUTE}),
            html.Td(v26, style={'padding': '7px 10px', 'textAlign': 'center', 'fontWeight': '700',
                                 'color': COLOR_GRIS_MUTE}),
        ])
        for label, v25, v26 in filas_datos
    ]

    return html.Div([
        html.Div(estacion, style={'fontWeight': '800', 'color': COLOR_GRIS_MUTE, 'fontSize': '18px',
                                   'marginBottom': '10px'}),
        html.Div(
            html.Table([html.Thead(encabezado), html.Tbody(filas)],
                       style={'width': '100%', 'borderCollapse': 'collapse'}),
            className='tabla-scroll',
        style={'borderRadius': '10px', 'overflow': 'hidden', 'border': f'1px solid {COLOR_GRIS_100}'}
        ),
        # html.Div(f'Tendencia 2025 vs 2026: {_tendencia_buena(row)}', style={
        #     'color': COLOR_GRIS_MUTE, 'fontSize': '14px', 'marginTop': '10px'}),
    ])


def _tabla_episodios(df: pd.DataFrame):
    """
    Tabla comparativa de episodios con acordeón:
    - Los encabezados de grupo (Precontingencias, Fase I…) son siempre visibles.
    - Las sub-filas (declaradas por Ozono/PM10/PM2.5) empiezan ocultas y se
      despliegan al hacer clic en el encabezado de su grupo.
    - Los grupos que no tienen sub-filas en los datos (Fase II, III) se
      muestran como filas normales sin flecha ni toggle.
    El gráfico de barras queda a la derecha con altura fija ALTO_GRAFICA_EPISODIOS.
    """
    col_label, col_2025, col_2026 = df.columns[0], df.columns[1], df.columns[2]

    # ── Primera pasada: agrupar filas por severidad ───────────────────────────
    grupos = []          # [{'sev': int, 'row': Series, 'subs': [Series, …]}, …]
    fila_totales = None
    grupo_actual = None

    for _, row in df.iterrows():
        etiqueta = str(row[col_label]).strip()
        es_total = etiqueta.lower().startswith('episodios totales')
        sev = _EPISODIOS_ENCABEZADOS.get(etiqueta, 0)

        if es_total:
            fila_totales = row
        elif sev:
            grupo_actual = {'sev': sev, 'row': row, 'subs': []}
            grupos.append(grupo_actual)
        elif grupo_actual is not None:
            grupo_actual['subs'].append(row)

    # ── Helpers de estilo ─────────────────────────────────────────────────────
    def _num(base): return {**base, 'padding': '8px 14px', 'textAlign': 'center'}
    def _lbl(base, indent=False): return {
        **base, 'padding': '8px 14px', 'textAlign': 'left',
        'paddingLeft': '34px' if indent else '14px',
        'fontSize': '15px' if indent else '14px',
        'fontWeight': base.get('fontWeight', '400') if indent else base.get('fontWeight', '700'),
    }

    # ── Segunda pasada: construir tbodies ─────────────────────────────────────
    tbodies = []
    for g in grupos:
        sev = g['sev']
        row = g['row']
        etiqueta = str(row[col_label]).strip()
        texto_claro = sev >= 2
        base = {
            'backgroundColor': _SEVERIDAD_TINTES[sev],
            'color': '#ffffff' if texto_claro else '#173d4c',
            'fontWeight': '700',
        }
        tiene_subs = bool(g['subs'])

        # Celda de etiqueta con flecha opcional
        contenido_lbl = ([
            html.Span('▶', id=f'arrow-episodios-{sev}',
                      style={'marginRight': '8px', 'fontSize': '10px',
                             'display': 'inline-block'}),
        ] if tiene_subs else []) + [etiqueta]

        celda_lbl = html.Td(
            contenido_lbl,
            style={**_lbl(base), 'cursor': 'pointer' if tiene_subs else 'default'},
        )

        # Fila encabezado: clickeable solo si tiene sub-filas
        kwargs_hdr = dict(id=f'toggle-episodios-{sev}', n_clicks=0) if tiene_subs else {}
        header_tr = html.Tr(
            [celda_lbl,
             html.Td(row[col_2025], style=_num(base)),
             html.Td(row[col_2026], style=_num(base))],
            **kwargs_hdr,
        )
        tbodies.append(html.Tbody([header_tr]))

        # Sub-filas en un tbody aparte, inicialmente oculto
        if tiene_subs:
            sub_base = {'backgroundColor': '#ffffff', 'color': COLOR_GRIS_MUTE}
            sub_trs = [
                html.Tr([
                    html.Td(str(sr[col_label]).strip(), style=_lbl(sub_base, indent=True)),
                    html.Td(sr[col_2025], style=_num(sub_base)),
                    html.Td(sr[col_2026], style=_num(sub_base)),
                ])
                for sr in g['subs']
            ]
            tbodies.append(html.Tbody(sub_trs,
                                      id=f'sub-episodios-{sev}',
                                      style={'display': 'none'}))

    # Fila de totales: mismo fondo aqua diluido y color de letra que los KPI.
    if fila_totales is not None:
        base_tot = {**_KPI_PIE, 'color': '#173d4c'}
        tbodies.append(html.Tbody([html.Tr([
            html.Td(str(fila_totales[col_label]).strip(), style=_lbl(base_tot)),
            html.Td(fila_totales[col_2025], style={**_num(base_tot), 'fontWeight': '800'}),
            html.Td(fila_totales[col_2026], style={**_num(base_tot), 'fontWeight': '800'}),
        ])]))

    encabezado = html.Thead(html.Tr([
        html.Th('Episodios activados', style={'backgroundColor': '#e8edef', 'color': '#173d4c',
                                               'padding': '10px 14px', 'textAlign': 'left'}),
        html.Th('2025', style={'backgroundColor': COLOR_2025, 'color': '#fff', 'padding': '10px 14px'}),
        html.Th('2026', style={'backgroundColor': COLOR_2026, 'color': '#fff', 'padding': '10px 14px'}),
    ]))

    return html.Div(
        html.Table([encabezado] + tbodies,
                   style={'width': '100%', 'borderCollapse': 'collapse'}),
        className='tabla-scroll',
        style={'borderRadius': '10px', 'overflow': 'hidden', 'border': f'1px solid {COLOR_GRIS_100}'}
    )


def _tabla_alertas(df: pd.DataFrame):
    col_label, col_2025, col_2026 = df.columns[0], df.columns[1], df.columns[2]

    filas = []
    for _, row in df.iterrows():
        etiqueta = str(row[col_label]).strip()
        es_total = etiqueta.lower().startswith('total')
        es_emergencia = etiqueta.lower().startswith('emergencia')

        if es_total:
            # Mismo fondo aqua diluido y color de letra que los KPI.
            estilo = {**_KPI_PIE, 'color': '#173d4c'}
        elif es_emergencia:
            estilo = {'backgroundColor': '#FC3508', 'color': '#ffffff'}
        else:
            estilo = {'backgroundColor': '#FFB300', 'color': '#173d4c'}

        filas.append(html.Tr([
            html.Td(etiqueta.rstrip(':'), style={**estilo, 'padding': '10px 14px', 'textAlign': 'left',
                                                  'fontWeight': '700'}),
            html.Td(row[col_2025], style={**estilo, 'padding': '10px 14px', 'textAlign': 'center',
                                           'fontWeight': '800'}),
            html.Td(row[col_2026], style={**estilo, 'padding': '10px 14px', 'textAlign': 'center',
                                           'fontWeight': '800'}),
        ]))

    encabezado = html.Tr([
        html.Th('Categoría', style={'backgroundColor': '#e8edef', 'color': '#173d4c',
                                     'padding': '10px 14px', 'textAlign': 'left'}),
        html.Th('2025', style={'backgroundColor': COLOR_2025, 'color': '#fff', 'padding': '10px 14px'}),
        html.Th('2026', style={'backgroundColor': COLOR_2026, 'color': '#fff', 'padding': '10px 14px'}),
    ])

    return html.Div(
        html.Table([html.Thead(encabezado), html.Tbody(filas)],
                    style={'width': '100%', 'borderCollapse': 'collapse'}),
        className='tabla-scroll',
        style={'borderRadius': '10px', 'overflow': 'hidden', 'border': f'1px solid {COLOR_GRIS_100}'}
    )


def _tabla_parametros():
    """Tabla de parámetros medidos por el SIMAJ."""
    parametros = [
        (html.Span(['O', html.Sub('3')], style={'fontWeight': '700'}), 'Ozono'),
        (html.Span(['N', 'O', html.Sub('2')], style={'fontWeight': '700'}), 'Dióxido de nitrógeno'),
        (html.Span(['S', 'O', html.Sub('2')], style={'fontWeight': '700'}), 'Bióxido de azufre'),
        (html.Span(['C', 'O'], style={'fontWeight': '700'}), 'Monóxido de carbono'),
        (html.Span(['P', 'M', html.Sub('10')], style={'fontWeight': '700'}), 'Partículas menores a 10 micrómetros'),
        (html.Span(['P', 'M', html.Sub('2.5')], style={'fontWeight': '700'}), 'Partículas menores a 2.5 micrómetros'),
    ]
    filas = [
        html.Tr([
            html.Td(formula, style={
                'padding': '8px 12px', 'textAlign': 'center',
                'borderBottom': f'1px solid {COLOR_GRIS_100}',
                'color': COLOR_GRIS_MUTE, 'fontSize': '13px',
            }),
            html.Td(desc, style={
                'padding': '8px 12px', 'textAlign': 'left',
                'borderBottom': f'1px solid {COLOR_GRIS_100}',
                'color': COLOR_GRIS_MUTE, 'fontSize': '13px',
            }),
        ])
        for formula, desc in parametros
    ]
    encabezado = html.Thead(html.Tr([
        html.Th('Parámetros', colSpan=2, style={
            'backgroundColor': '#e8edef', 'color': '#173d4c',
            'padding': '8px 12px', 'textAlign': 'center',
            'fontWeight': '700', 'fontSize': '13px',
        }),
    ]))
    return html.Div(
        html.Table([encabezado, html.Tbody(filas)],
                   style={'width': '100%', 'borderCollapse': 'collapse'}),
        style={
            'borderRadius': '10px', 'overflow': 'hidden',
            'border': f'1px solid {COLOR_GRIS_100}',
            'maxWidth': '500px', 'margin': '0 auto',
        }
    )


def _tabla_paginada(df: pd.DataFrame, id_tabla: str, columna_color: str = None,
                     mapa_color: dict = None, texto_claro_valores: tuple = ()):
    """
    Tabla tipo hoja de cálculo con paginación nativa de Dash. Si se da
    columna_color + mapa_color, colorea solo la celda de esa columna según el
    valor, igual que en el Excel.
    """
    columnas = list(df.columns)
    style_data_conditional = []
    if columna_color and mapa_color:
        for valor, color in mapa_color.items():
            texto = '#ffffff' if valor in texto_claro_valores else '#173d4c'
            style_data_conditional.append({
                'if': {'filter_query': f'{{{columna_color}}} = "{valor}"', 'column_id': columna_color},
                'backgroundColor': color,
                'color': texto,
                'fontWeight': '700',
            })

    return dash_table.DataTable(
        id=id_tabla,
        columns=[{'name': c.replace('\n', ' '), 'id': c} for c in columnas],
        data=df.to_dict('records'),
        page_action='native',
        page_size=10,
        sort_action='native',
        style_table={'overflowX': 'auto'},
        style_header={'backgroundColor': '#e8edef', 'color': '#173d4c', 'fontWeight': '700',
                      'textAlign': 'left', 'padding': '8px 10px', 'border': 'none'},
        style_cell={'padding': '8px 10px', 'fontFamily': 'Montserrat, sans-serif', 'fontSize': '15px',
                    'color': COLOR_GRIS_MUTE, 'textAlign': 'left', 'minWidth': '90px', 'maxWidth': '240px',
                    'overflow': 'hidden', 'textOverflow': 'ellipsis', 'border': f'1px solid {COLOR_GRIS_100}'},
        style_data_conditional=style_data_conditional,
        style_as_list_view=True,
    )
