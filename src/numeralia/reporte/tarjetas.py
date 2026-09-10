"""
Tarjetas del dashboard: encabezado institucional, serie mensual, IMECA
máximo, ficha de eventos activos y las dos bitácoras. Reciben datos y
devuelven componentes de Dash.

Salieron de main.py (Sección 6) en el Paso 2 del refactor.
"""

import base64
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dash import dcc, html

from numeralia.config import Config
from numeralia.reporte.figuras import _fig_serie_buena_mensual
from numeralia.reporte.formato import (
    _MESES_NOMBRE,
    _buscar_columna,
    _clasificar_imeca,
    _fecha_encabezado,
    _fecha_mes_abreviado,
    _formatear_hora,
    _ordenar_por_no_desc,
)
from numeralia.reporte.kpis import _KPI_CONTENEDOR, _KPI_CUERPO, _KPI_TITULO
from numeralia.reporte.tablas import _tabla_paginada
from numeralia.reporte.tema import (
    ALTO_LOGO,
    CARD_STYLE,
    COLOR_2025,
    COLOR_2026,
    COLOR_GRIS,
    COLOR_GRIS_100,
    COLOR_GRIS_MUTE,
    LOGO_SEMADET,
    LOGO_SIMAJ,
    NOMBRE_CARPETA_LOGOS,
    SEVERIDAD_TINTES as _SEVERIDAD_TINTES,
)

CONFIG = Config.desde_env()

# Raíz del repositorio (…/src/numeralia/reporte/tarjetas.py -> parents[3]).
_RAIZ_REPO = Path(__file__).resolve().parents[3]


def _icono_descarga(btn_id: str):
    """Botón con ícono SVG de descarga (flecha hacia abajo con bandeja)."""
    return html.Button(
        html.Img(src='data:image/svg+xml;utf8,'
                 '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" '
                 'fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
                 '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
                 '<polyline points="7 10 12 15 17 10"/>'
                 '<line x1="12" y1="15" x2="12" y2="3"/></svg>',
                 style={'width': '18px', 'height': '18px'}),
        id=btn_id, n_clicks=0,
        style={'backgroundColor': COLOR_GRIS, 'border': 'none', 'borderRadius': '50%',
               'width': '34px', 'height': '34px', 'display': 'flex', 'alignItems': 'center',
               'justifyContent': 'center', 'cursor': 'pointer', 'padding': '0'},
    )


def _carpetas_logos():
    """
    Lugares donde puede vivir la carpeta de logos, en orden de preferencia:
    la raíz del repositorio, la carpeta de trabajo, y Drive (solo si ya está
    montado — nunca se monta aquí, para no interrumpir con permisos).
    """
    candidatas = [
        _RAIZ_REPO / NOMBRE_CARPETA_LOGOS,
        Path.cwd() / NOMBRE_CARPETA_LOGOS,
    ]

    drive = Path('/content/drive/MyDrive')
    if drive.exists():
        candidatas.append(drive / NOMBRE_CARPETA_LOGOS)
    return candidatas


def _logo_src(nombre_archivo: str):
    """
    Devuelve el logo como data URI listo para html.Img, o None si no está.

    Se convierte a data URI (y no se pasa la ruta tal cual) para que la
    imagen viaje dentro del HTML: así aparece también al generar el PDF, sin
    depender de que el servidor de Dash la siga sirviendo.
    """
    for carpeta in _carpetas_logos():
        ruta = carpeta / nombre_archivo
        if ruta.exists():
            datos = base64.b64encode(ruta.read_bytes()).decode('ascii')
            return f'data:image/png;base64,{datos}'

    buscadas = ' | '.join(str(c) for c in _carpetas_logos())
    print(f"Nota: Logo '{nombre_archivo}' no encontrado. Se buscó en: {buscadas}")
    return None


def _encabezado_reporte():
    """
    Encabezado del reporte: logo SIMAJ a la izquierda, título centrado con la
    fecha debajo, logo SEMADET/Gobierno de Jalisco a la derecha, y al final
    la introducción.

    Los tres bloques de la fila usan flex con el mismo ancho base, así el
    título queda centrado respecto a la página aunque los logos tengan
    anchos distintos.
    """
    src_simaj = _logo_src(LOGO_SIMAJ)
    src_semadet = _logo_src(LOGO_SEMADET)

    def _celda_logo(src, alineacion, clase_imagen=None):
        contenido = html.Img(src=src, className=clase_imagen, style={
            'height': ALTO_LOGO, 'width': 'auto', 'display': 'block',
            # Sin maxWidth la imagen conserva su ancho natural y se sale de
            # la celda cuando la ventana se angosta.
            'maxWidth': '100%', 'objectFit': 'contain',
        }) if src else None
        return html.Div(contenido, style={
            'flex': '1 1 0', 'display': 'flex', 'alignItems': 'center',
            'justifyContent': alineacion, 'minWidth': '0',
        })

    return html.Div([
        # Fila de logos + título
        html.Div([
            _celda_logo(src_simaj, 'flex-start', 'logo-simaj'),
            html.Div([
                html.H1('Reporte Diario de Calidad del Aire', className='titulo-reporte', style={
                    'margin': '0', 'fontSize': '32px', 'fontWeight': '700',
                    'color': '#111C51', 'textAlign': 'center', 'lineHeight': '1.15',
                }),
                html.Div(_fecha_encabezado(), className='fecha-reporte', style={
                    'color': COLOR_2026, 'fontSize': '20px', 'fontWeight': '600',
                    'textAlign': 'center', 'marginTop': '8px',
                }),
            ], style={'flex': '2 1 0', 'display': 'flex', 'alignItems': 'center',
                      'justifyContent': 'center', 'padding': '0 24px',
                      'flexDirection': 'column', 'minWidth': '0'}),
            _celda_logo(src_semadet, 'flex-end'),
        ], className='fila-encabezado', style={'display': 'flex', 'alignItems': 'center',
                  'gap': '24px', 'marginBottom': '22px'}),

        # Introducción
        html.P(
            'El Reporte Diario de Calidad del Aire permite conocer cómo se ha comportado '
            'la calidad del aire al día señalado en el encabezado. ',
            style={'color': COLOR_GRIS_MUTE, 'fontSize': '17px', 'lineHeight': '1.6',
                   'textAlign': 'center', 'maxWidth': '1000px', 'margin': '0 auto'},
        ),
    ], style={'marginBottom': '32px'})


def _card_serie_mensual_2025(df_resumen: pd.DataFrame):
    hoy = datetime.now()
    corte = hoy.replace(day=1) - timedelta(days=1)
    mes_actual = _MESES_NOMBRE[corte.month]
    año_actual = corte.year
    dia_corte = corte.day
    return html.Div([
        html.Div([
            'Acumulado Mensual de Días con Buena o Aceptable Calidad del Aire ',
            html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
            '-',
            html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
        ], style={'color': '#111C51', 'fontWeight': '700', 'fontSize': '18px', 'marginBottom': '4px'}),
        html.Div([
            f'Acumulado mensual de días en los que la calidad del aire fue buena o aceptable según '
            f'el Índice Aire y Salud (NOM-172-SEMARNAT-2023), considerando el valor más alto '
            f'registrado por el SIMAJ. Corte al {dia_corte} de {mes_actual} de {año_actual}. Consulta la información histórica en ',
            html.A('mide.jalisco.gob.mx', href='https://mide.jalisco.gob.mx', target='_blank',
                   style={'color': COLOR_2026, 'textDecoration': 'underline'}),
        ], style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        # La figura no se le pasa directo a la gráfica: vive en este Store y
        # un callback clientside la adapta al ancho de la pantalla antes de
        # dibujarla (en celular le quita el cintillo de pastillas, que a ese
        # ancho mide 5 px y queda ilegible). Así hay un solo escritor de
        # 'figure' y el refresco periódico no pisa esa adaptación.
        dcc.Store(id='figura-serie-base',
                  data=_fig_serie_buena_mensual(df_resumen).to_plotly_json()),
        # El alto vive aquí y no en la figura para que las medias queries lo
        # puedan achicar; 'responsive' hace que Plotly siga al contenedor.
        dcc.Graph(id='grafico-serie-mensual', className='grafica-serie-mensual',
                  style={'height': '330px'},
                  config={'displayModeBar': False, 'responsive': True}),
        dcc.Interval(id='refrescar-serie-mensual',
                     interval=CONFIG.refresco_mensual_seg * 1000, n_intervals=0),
    ], style={**CARD_STYLE, 'marginBottom': '20px'})


def _card_imeca(df_imeca: pd.DataFrame):
    d = df_imeca.set_index(df_imeca.columns[0])

    def _get(anio, campo):
        return d.loc[campo, anio] if campo in d.index and anio in d.columns else '—'

    def _bloque_anio(anio, color):
        valor = _get(anio, 'IMECA Máximo del año')
        return html.Div([
            html.Div(anio, style={'color': color, 'fontWeight': '800', 'fontSize': '15px',
                                   'letterSpacing': '0.04em', 'textTransform': 'uppercase',
                                   'marginBottom': '4px'}),
            # Fila interna: número+badge a la izquierda, metadata a la derecha
            html.Div([
                # Columna izquierda: número grande + badge
                html.Div([
                    html.Div(str(valor), style={'color': COLOR_GRIS_MUTE, 'fontSize': '42px',
                                                'fontWeight': '800', 'lineHeight': '1'}),
                    html.Div(_clasificar_imeca(valor), style={
                        'display': 'inline-block', 'backgroundColor': color, 'color': '#ffffff',
                        'borderRadius': '999px', 'padding': '2px 12px',
                        'fontSize': '13px', 'fontWeight': '700', 'marginTop': '6px',
                    }),
                ], style={'display': 'flex', 'flexDirection': 'column',
                          'alignItems': 'flex-start', 'marginRight': '20px',
                          'flexShrink': '0'}),
                # Columna derecha: metadata
                html.Div([
                    html.Div([html.Span('Contaminante  ', style={'color': COLOR_GRIS_MUTE}),
                              html.B(_get(anio, 'Contaminante'), style={'color': '#173d4c'})]),
                    html.Div([html.Span('Estación  ', style={'color': COLOR_GRIS_MUTE}),
                              html.B(_get(anio, 'Estación'), style={'color': '#173d4c'})]),
                    html.Div([html.Span('Fecha  ', style={'color': COLOR_GRIS_MUTE}),
                              html.B(_fecha_mes_abreviado(_get(anio, 'Fecha')),
                                     style={'color': '#173d4c'})]),
                    html.Div([html.Span('Hora  ', style={'color': COLOR_GRIS_MUTE}),
                              html.B(_formatear_hora(_get(anio, 'Hora')), style={'color': '#173d4c'})]),
                ], style={'fontSize': '14px', 'display': 'grid', 'gap': '4px',
                          'alignContent': 'center'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'alignItems': 'center'}),
        ], className='bloque-imeca-anio', style={'flex': '1', 'padding': '14px 22px',
                  'borderLeft': f'4px solid {color}', '--color-acento': color})

    return html.Div([
        html.Div('IMECA Máximo Registrado', style={'color': '#111C51', 'fontWeight': '700',
                                                     'fontSize': '17px', 'marginBottom': '4px'}),
        html.Div('Valor más alto del índice en el año',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '14px', 'marginBottom': '12px'}),
        # 'fila-imeca': en celular se apila en columna (ver
        # assets/responsive_movil.css) y, como 2025 va primero en el DOM, se
        # invierte con 'column-reverse' para que 2026 —el año en curso—
        # quede arriba.
        html.Div([_bloque_anio('2025', COLOR_2025), _bloque_anio('2026', COLOR_2026)],
                  className='fila-imeca',
                  style={'display': 'flex', 'border': f'1px solid {COLOR_GRIS_100}',
                         'borderRadius': '12px', 'overflow': 'hidden'}),
    ])


def _card_eventos_activos(eventos_alertas, eventos_episodios=None):
    """
    Ficha de episodios/alertas activos, como tercera tarjeta KPI.
    - eventos_alertas: lista de dicts de _eventos_activos_2026() (hoja alertas).
    - eventos_episodios: lista de dicts de _episodios_activos_raw() (hoja episodios).
    Ambas listas se muestran juntas. Las alertas usan color amarillo/rojo según
    la Fase Decretada; los episodios usan SEVERIDAD_TINTES según su nivel.
    """
    todos = list(eventos_alertas or []) + list(eventos_episodios or [])

    if not todos:
        cuerpo = html.Div(
            'Sin episodios ni eventos activos al momento.',
            style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'textAlign': 'center',
                   'padding': '18px 0'},
        )
    else:
        fichas = []
        for i, ev in enumerate(todos):
            es_ultimo = i == len(todos) - 1
            tipo = ev.get('tipo', 'alerta')

            if tipo == 'alerta':
                fase = ev.get('fase', '').lower()
                color_badge = '#FC3508' if 'emergencia' in fase else '#FFB300'
                texto_badge = ev.get('fase') or 'Alerta'
                texto_claro_badge = 'emergencia' in fase
                descripcion = ev.get('incidente', '')
                detalle = f"en el municipio de {ev['municipio']}" if ev.get('municipio') else ''
                subtexto = None
            else:
                sev = ev.get('severidad', 0)
                color_badge = _SEVERIDAD_TINTES.get(sev, '#FFB300')
                texto_badge = ev.get('evento') or 'Episodio activo'
                texto_claro_badge = sev >= 2
                descripcion = None
                detalle = f"en el municipio de {ev['municipio']}" if ev.get('municipio') else ''
                contaminante = ev.get('contaminante', '') or None
                estacion = ev.get('estacion', '') or None

            fichas.append(html.Div([
                html.Div(texto_badge, style={
                    'backgroundColor': color_badge,
                    'color': '#ffffff' if texto_claro_badge else COLOR_GRIS_MUTE,
                    'display': 'inline-block',
                    'padding': '4px 12px', 'borderRadius': '6px', 'fontWeight': '700',
                    'fontSize': '13px', 'marginBottom': '6px',
                }),
                html.Div(descripcion, style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'fontWeight': '600',
                }) if tipo == 'alerta' and descripcion else None,
                html.Div(detalle, style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '14px',
                }) if detalle else None,
                html.Div(f'Estación: {estacion}', style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '14px',
                }) if tipo == 'episodio' and estacion else None,
                html.Div(f'Contaminante: {contaminante}', style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '14px',
                }) if tipo == 'episodio' and contaminante else None,
            ], style={
                'marginBottom': '0' if es_ultimo else '10px',
                'paddingBottom': '0' if es_ultimo else '10px',
                'textAlign': 'center',
                'borderBottom': 'none' if es_ultimo else f'1px solid {COLOR_GRIS_100}',
            }))
        cuerpo = html.Div(fichas)

    return html.Div([
        html.Div('Episodios o Eventos Activos', style=_KPI_TITULO),
        html.Div(cuerpo, style={**_KPI_CUERPO, 'display': 'flex',
                                 'flexDirection': 'column', 'justifyContent': 'center'}),
    ], style=_KPI_CONTENEDOR)


def _card_bitacora_alertas(df_alertas_2026_raw: pd.DataFrame):
    """Bitácora de 'NUEVO alertas 2026' (columnas A a K menos D, E, F e I)."""
    cols_a_k = list(df_alertas_2026_raw.columns)[0:11]
    cols_mostrar = [c for i, c in enumerate(cols_a_k) if i not in (3, 4, 5, 8)]
    df = _ordenar_por_no_desc(df_alertas_2026_raw[cols_mostrar])

    col_fase = _buscar_columna(cols_mostrar, 'fase decretada', 'fase')
    mapa_color = {'Alerta': '#FFB300', 'Emergencia': '#FC3508'} if col_fase else None

    return html.Div([
        html.Div([
            html.Div([
                'Registro de Eventos (Alertas y Emergencias) ',
                html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
            ], id='bitacora-alertas-header',
                     className='bitacora-titulo',
                     n_clicks=0,
                     style={'flex': '1', 'color': '#111C51', 'fontWeight': '700',
                            'fontSize': '18px'}),
            _icono_descarga('btn-pdf-alertas'),
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
                  'marginBottom': '4px'}),
        html.Div('Eventos extraordinarios decretados de acuerdo con el Plan de Respuesta a Emergencias y Contingencias Atmosféricas (PRECA) del Estado de Jalisco.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        html.Div([
            html.Div(
                _tabla_paginada(df, 'tabla-bitacora-alertas', columna_color=col_fase, mapa_color=mapa_color,
                                texto_claro_valores=('Emergencia',)),
                style={'position': 'relative'}),
            html.Div('Se muestran los últimos 10 registros. Para consultar el listado completo, '
'utiliza el ícono ubicado en la esquina superior derecha, o desplázate entre '
'registros mediante las flechas de la esquina inferior derecha.',
                      style={'marginTop': '6px',
                             'color': COLOR_GRIS_MUTE, 'fontSize': '11px'}),
        ], className='bitacora-contenido'),
        dcc.Download(id='descarga-pdf-alertas'),
    ], id='bitacora-alertas-wrapper', className='bitacora-cerrada',
       style={**CARD_STYLE, 'position': 'relative', 'marginBottom': '20px'}), df


def _card_bitacora_episodios(df_episodios_2026_raw: pd.DataFrame):
    """Bitácora completa de 'Nuevo episodios 2026', columnas hasta 'Estado', sin 'Fin'."""
    cols_totales = list(df_episodios_2026_raw.columns)
    col_estado = _buscar_columna(cols_totales, 'estado')
    if col_estado is not None:
        cols_mostrar = cols_totales[0:cols_totales.index(col_estado) + 1]
    else:
        cols_mostrar = cols_totales
    col_fin = _buscar_columna(cols_mostrar, 'fin')
    if col_fin:
        cols_mostrar = [c for c in cols_mostrar if c != col_fin]
    df = _ordenar_por_no_desc(df_episodios_2026_raw[cols_mostrar])
    cols = list(df.columns)

    col_evento = _buscar_columna(cols, 'evento')
    mapa_color = None
    texto_claro = ()
    if col_evento:
        mapa_color = {
            'PreContingencia Atmosférica': '#FFB300',
            'Contingencia Atmosférica Fase I': '#EF6C00',
            'Contingencia Atmosférica Fase II': '#DC143C',
            'Contingencia Atmosférica Fase III': '#4B0082',
        }
        texto_claro = ('Contingencia Atmosférica Fase I', 'Contingencia Atmosférica Fase II',
                        'Contingencia Atmosférica Fase III')

    return html.Div([
        html.Div([
            html.Div([
                'Registro de Episodios (Precontingencias y Contingencias) ',
                html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
            ], id='bitacora-episodios-header',
                     className='bitacora-titulo',
                     n_clicks=0,
                     style={'flex': '1', 'color': '#173d4c', 'fontWeight': '700',
                            'fontSize': '18px'}),
            _icono_descarga('btn-pdf-episodios'),
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
                  'marginBottom': '4px'}),
        html.Div('Episodios decretados de acuerdo con el Plan de Respuesta a Emergencias y Contingencias Atmosféricas (PRECA) del Estado de Jalisco.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        html.Div([
            html.Div(
                _tabla_paginada(df, 'tabla-bitacora-episodios', columna_color=col_evento, mapa_color=mapa_color,
                                texto_claro_valores=texto_claro),
                style={'position': 'relative'}),
            html.Div('Se muestran los últimos 10 registros. Para consultar el listado completo, '
'utiliza el ícono ubicado en la esquina superior derecha, o desplázate entre '
'registros mediante las flechas de la esquina inferior derecha.',
                      style={'marginTop': '6px',
                             'color': COLOR_GRIS_MUTE, 'fontSize': '11px'}),
        ], className='bitacora-contenido'),
        dcc.Download(id='descarga-pdf-episodios'),
    ], id='bitacora-episodios-wrapper', className='bitacora-cerrada',
       style={**CARD_STYLE, 'position': 'relative', 'marginBottom': '20px'}), df
