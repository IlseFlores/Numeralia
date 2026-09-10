"""
Fichas KPI de la fila superior del dashboard: activaciones por SIMAJ y eventos
extraordinarios. Reciben los DataFrames comparativos y devuelven componentes
de Dash; no leen de Google Sheets.

Los estilos ``_KPI_*`` los comparten también algunas tablas y tarjetas que
por ahora siguen en main.py, así que se exportan desde aquí.

Salieron de main.py (Sección 6) en el Paso 2 del refactor.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
from dash import html

from numeralia.reporte.formato import _MESES_NOMBRE, _to_num
from numeralia.reporte.tema import (
    COLOR_2026,
    COLOR_GRIS_100,
    COLOR_GRIS_MUTE,
    SEVERIDAD_TINTES as _SEVERIDAD_TINTES,
)

# Estilo compartido por las tres fichas de la fila superior, para que queden
# de la misma altura y con el mismo marco aunque su contenido sea distinto.
# El acento es aqua (el color de 2026) porque estas fichas reportan solo el
# año en curso; el azul marino se reserva para donde sí se compara con 2025.
_KPI_CONTENEDOR = {
    'backgroundColor': '#ffffff', 'border': f'1px solid {COLOR_GRIS_100}',
    'borderRadius': '12px', 'padding': '0', 'flex': '1', 'minWidth': '260px',
    'borderTop': f'4px solid {COLOR_2026}', 'display': 'flex', 'flexDirection': 'column',
    'overflow': 'hidden',
    # Sombra en dos capas: una difusa y amplia que despega la tarjeta del
    # fondo, y otra corta y apretada que le da el filo.
    'boxShadow': '0 1px 2px rgba(70,80,85,0.06), 0 6px 16px rgba(70,80,85,0.08)',
}

_KPI_TITULO = {
    'color': COLOR_2026, 'fontSize': '14px', 'fontWeight': '800',
    'textTransform': 'uppercase', 'letterSpacing': '0.06em',
    'padding': '14px 20px 12px',
}

# Zona de datos (columnas) y pie de total, con su propio respiro.
_KPI_CUERPO = {'flex': '1', 'padding': '0 20px 14px'}

# Pie con un tinte aqua muy diluido, para que la franja pertenezca a la misma
# familia de color que el acento superior en vez de ser un gris neutro.
_KPI_PIE = {
    'backgroundColor': '#f2fbf9', 'borderTop': '1px solid #dcf1ec',
    'padding': '12px 20px',
}


def _kpi_dato(etiqueta: str, valor, color_punto: str = None):
    """
    Un dato suelto de ficha KPI: cifra grande arriba, etiqueta abajo, con un
    punto del color de severidad. Se usa dentro de las columnas de la ficha,
    centrado, para que dos datos lado a lado se lean parejos.
    """
    encabezado = []
    if color_punto:
        encabezado.append(html.Span(style={
            'display': 'inline-block', 'width': '9px', 'height': '9px',
            'borderRadius': '50%', 'backgroundColor': color_punto,
            'marginRight': '7px', 'flexShrink': '0',
        }))
    encabezado.append(html.Span(etiqueta, style={
        'color': COLOR_GRIS_MUTE, 'fontSize': '14px', 'fontWeight': '600',
        'lineHeight': '1.3',
    }))

    return html.Div([
        html.Div(str(valor), style={
            'color': COLOR_2026, 'fontWeight': '800', 'fontSize': '34px',
            'lineHeight': '1', 'marginBottom': '7px',
        }),
        html.Div(encabezado, style={
            'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center',
        }),
    ], style={'textAlign': 'center'})


def _periodo_corte() -> str:
    """
    'Registro del 1 de enero al 8 de septiembre del 2026' — el rango que cubren
    los datos. El corte es el día anterior, igual que _fecha_encabezado: el
    dashboard refleja datos cerrados al día previo.
    """
    utc_minus_6 = timezone(timedelta(hours=-6))
    ayer = datetime.now(utc_minus_6) - timedelta(days=1)
    return (f"Registro del 1 de enero al {ayer.day} de "
            f"{_MESES_NOMBRE[ayer.month].lower()} del {ayer.year}")


def _kpi_total(etiqueta: str, valor):
    """
    Encabezado de la ficha: sustituye al título. La etiqueta va en el aqua de
    2026 (el mismo color que tenían los títulos 'Episodios/Eventos Activados'
    que reemplaza); la cifra —el número más importante— se queda en gris
    oscuro para no perderse sobre el tinte aqua diluido del recuadro.

    Debajo de la etiqueta, en letra muy chica, el periodo que cubren los datos.

    Ocupa todo el ancho (la tarjeta tiene padding 0 y overflow hidden), con
    un filo abajo que lo separa del desglose.
    """
    return html.Div([
        html.Div([
            html.Span(etiqueta, style={
                'color': COLOR_2026, 'fontSize': '14px', 'fontWeight': '800',
                'textTransform': 'uppercase', 'letterSpacing': '0.06em',
            }),
            html.Div(_periodo_corte(), style={
                'color': COLOR_GRIS_MUTE, 'fontSize': '9.5px', 'fontWeight': '600',
                'letterSpacing': '0', 'marginTop': '2px',
                'fontFamily': 'Montserrat, sans-serif', 'textTransform': 'none',
            }),
        ]),
        html.Span(str(valor), style={
            'color': '#173d4c', 'fontWeight': '800', 'fontSize': '32px', 'lineHeight': '1',
        }),
    ], style={**_KPI_PIE, 'borderBottom': '1px solid #dcf1ec',
              'padding': '14px 20px',
              'display': 'flex', 'justifyContent': 'space-between',
              'alignItems': 'center', 'gap': '12px'})


def _kpi_activaciones_simaj(df_episodios: pd.DataFrame, col_2026: str):
    """
    Ficha 'Activaciones por SIMAJ': solo datos 2026. El total encabeza la
    ficha (en lugar del título) y el desglose queda debajo: precontingencias
    a la izquierda, contingencias por fase a la derecha.

    Las fases se leen de la tabla de Episodios, así que si en el futuro las
    Fases II o III  dejan de estar en cero, aparecen solas sin tocar el código.
    """
    col_label = df_episodios.columns[0]

    def _valor(prefijo_busqueda: str):
        m = df_episodios[df_episodios[col_label].astype(str).str.strip() == prefijo_busqueda]
        if m.empty:
            return 0
        return int(_to_num(m.iloc[0][col_2026]) or 0)

    precont = _valor('Precontingencias atmosféricas:')
    fases = [
        ('Fase I',   _valor('Contingencias atmosféricas Fase I:'),   _SEVERIDAD_TINTES[2]),
        ('Fase II',  _valor('Contingencias atmosféricas Fase II:'),  _SEVERIDAD_TINTES[3]),
        ('Fase III', _valor('Contingencias atmosféricas Fase III:'), _SEVERIDAD_TINTES[4]),
    ]

    total_fila = df_episodios[
        df_episodios[col_label].astype(str).str.strip().str.lower() == 'episodios totales']
    total = int(_to_num(total_fila.iloc[0][col_2026]) or 0) if not total_fila.empty else 0

    # Fase I siempre; II y III se suman solas en cuanto registren su primer
    # evento. Si hay más de una, se acomodan lado a lado.
    fases_visibles = [f for i, f in enumerate(fases) if i == 0 or f[1] > 0]
    col_contingencias = html.Div(
        [_kpi_dato(nombre, valor, color) for nombre, valor, color in fases_visibles],
        style={'display': 'flex', 'gap': '14px', 'justifyContent': 'center'},
    )

    return html.Div([
        # El encabezado de la ficha ES el total (antes iba el título
        # 'Episodios Activados'): _kpi_total lo pinta en el aqua de 2026 sobre
        # el recuadro azul bajito.
        _kpi_total('Episodios Totales', total),
        html.Div(html.Div([
            html.Div(_kpi_dato('Precontingencias', precont, _SEVERIDAD_TINTES[1]),
                     style={'flex': '1', 'minWidth': '0'}),
            # Línea vertical que separa precontingencias de contingencias.
            html.Div(style={'width': '1px', 'backgroundColor': COLOR_GRIS_100,
                            'alignSelf': 'stretch'}),
            html.Div([
                col_contingencias,
                html.Div('Contingencias', style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '13px', 'fontWeight': '600',
                    'textAlign': 'center', 'marginTop': '6px',
                }),
            ], style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '14px', 'alignItems': 'center',
                  'height': '100%'}), style={**_KPI_CUERPO, 'paddingTop': '18px'}),
    ], style=_KPI_CONTENEDOR)


def _kpi_alertas_emergencias(df_alertas: pd.DataFrame, col_2026: str):
    """
    Ficha de eventos extraordinarios: solo datos 2026, con la misma
    estructura visual que Activaciones por SIMAJ.
    """
    col_label = df_alertas.columns[0]

    def _valor(prefijo: str):
        m = df_alertas[df_alertas[col_label].astype(str).str.strip().str.lower().str.startswith(prefijo)]
        if m.empty:
            return 0
        return int(_to_num(m.iloc[0][col_2026]) or 0)

    alertas = _valor('alerta')
    emergencias = _valor('emergencia')
    total = _valor('total')

    return html.Div([
        # El encabezado ES el total (antes: título 'Eventos activados').
        _kpi_total('Eventos Totales', total),
        html.Div(html.Div([
            html.Div(_kpi_dato('Alertas', alertas, '#FFB300'),
                     style={'flex': '1', 'minWidth': '0'}),
            html.Div(style={'width': '1px', 'backgroundColor': COLOR_GRIS_100,
                            'alignSelf': 'stretch'}),
            html.Div(_kpi_dato('Emergencias', emergencias, '#FF0000'),
                     style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '14px', 'alignItems': 'center',
                  'height': '100%'}), style={**_KPI_CUERPO, 'paddingTop': '18px'}),
    ], style=_KPI_CONTENEDOR)
