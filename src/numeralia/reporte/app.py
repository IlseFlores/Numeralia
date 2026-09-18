"""
Ensamblado del dashboard de Dash: junta tarjetas, tablas, figuras y callbacks
en una app lista para servir.

``build_dash_app`` se llama de dos formas:
  · build_dash_app(gc, spreadsheet_destino, acumulado)  -> lee de Google Sheets
  · build_dash_app(datos=...)                           -> usa un dict ya cargado
    (el JSON de ``exportar_datos_dashboard``, en el servidor)

Salió de main.py (Sección 6) en el Paso 3 del refactor.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dash import (
    ClientsideFunction,
    Dash,
    Input,
    Output,
    State,
    callback_context,
    dcc,
    html,
)

from numeralia.cache import cache_sheets
from numeralia.config import Config
from numeralia.reporte.datos_graficas import (
    _datos_barras_alertas,
    _datos_grafica_episodios,
    _episodios_activos_raw,
    _eventos_activos_2026,
)
from numeralia.reporte.figuras import _fig_a_base64, _fig_mapa, _fig_serie_buena_mensual
from numeralia.reporte.formato import (
    _fecha_archivo, _fecha_encabezado, _siguiente_clases_bitacoras,
)
from numeralia.reporte.kpis import _kpi_activaciones_simaj, _kpi_alertas_emergencias
from numeralia.reporte.pdf import DescargaPDF, registrar_descargas
from numeralia.reporte.tablas import (
    _detalle_placeholder,
    _tabla_alertas,
    _tabla_detalle_estacion,
    _tabla_episodios,
    _tabla_parametros,
)
from numeralia.reporte.tarjetas import (
    _card_bitacora_alertas,
    _card_bitacora_episodios,
    _card_eventos_activos,
    _card_imeca,
    _card_serie_mensual_2025,
    _encabezado_reporte,
    _icono_descarga,
)
from numeralia.reporte.tema import (
    ALTO_GRAFICA_EPISODIOS,
    CARD_STYLE,
    COLOR_2025,
    COLOR_2026,
    COLOR_BG,
    COLOR_GRIS,
    COLOR_GRIS_100,
    COLOR_GRIS_MUTE,
    COLOR_MUTED,
    COLOR_TEXT,
    LOGO_SEMADET,
    LOGO_SIMAJ,
    NOMBRE_CARPETA_LOGOS,
)
from numeralia.sheets import _df_nativo, _worksheet_a_df

CONFIG = Config.desde_env()


def _raiz_repo() -> Path:
    """
    Ruta a la raíz del repositorio (donde viven 'assets/' y 'logos/').

    'Path(__file__).resolve().parents[3]' asume que este archivo vive en
    <repo>/src/numeralia/reporte/app.py, lo cual solo es cierto con una
    instalación editable (``pip install -e .``, como en el entorno de
    desarrollo). Con una instalación real (``pip install .``, como hace el
    Dockerfile) el paquete se copia dentro de site-packages y esos mismos
    4 niveles caen en el directorio de Python, no en el repo — 'assets/'
    y 'logos/' quedan invisibles y el dashboard se levanta sin
    dashboard.js ni logos, sin avisar.

    Por eso se prueban dos candidatas, en orden, y se usa la primera que
    de verdad tenga 'assets/dashboard.js' adentro:
      1. 4 niveles arriba de este archivo (instalación editable).
      2. El directorio de trabajo (el Dockerfile hace WORKDIR /app y copia
         ahí todo el repo antes de instalar el paquete, así que en
         producción CONFIG.cwd() = la raíz del repo).
    """
    candidatas = [Path(__file__).resolve().parents[3], Path.cwd()]
    for candidata in candidatas:
        if (candidata / "assets" / "dashboard.js").exists():
            return candidata
    print(f"Nota: no se encontró 'assets/dashboard.js' en ninguna de estas rutas: "
          f"{[str(c) for c in candidatas]}. Los callbacks clientside del "
          f"dashboard (mapa, PDF, gráficas) no van a funcionar.")
    return candidatas[-1]


_RAIZ_REPO = _raiz_repo()
_ASSETS = _RAIZ_REPO / "assets"

# Respaldo para que el archivo siga corriendo tal cual en Colab; en un
# repositorio los valores reales llegan del .env (Config.urls).
URL_FUENTE_2026 = CONFIG.urls.get("fuente_2026") or     "https://docs.google.com/spreadsheets/d/1Kzr8qWd0cew_CF-KOvukmS6Qo4Ry9O6md_EBqtqWv4k/edit"
URL_RESUMEN_MENSUAL = CONFIG.urls.get("resumen_mensual") or     "https://docs.google.com/spreadsheets/d/1cAICszRtOI1j9ZDDyqhnekEEUXDNCJXJQYWU-xddzMs/edit"


_TABLAS_DASHBOARD = (
    'episodios', 'alertas', 'imeca',
    'alertas_2026_raw', 'episodios_2026_raw',
    'resumen_mensual', 'acumulado',
)


def _leer_datos_de_sheets(gc, spreadsheet_destino, acumulado: pd.DataFrame) -> dict:
    """Lee de Google Sheets todo lo que el dashboard necesita."""
    sh_fuente_2026 = gc.open_by_url(URL_FUENTE_2026)
    sh_resumen_mensual = gc.open_by_url(URL_RESUMEN_MENSUAL)

    return {
        'episodios':          pd.DataFrame(spreadsheet_destino.worksheet("Episodios").get_all_records()),
        'alertas':            pd.DataFrame(spreadsheet_destino.worksheet("ALERTAS").get_all_records()),
        'imeca':              pd.DataFrame(spreadsheet_destino.worksheet("IMECA MAXIMO").get_all_records()),
        'alertas_2026_raw':   _worksheet_a_df(sh_fuente_2026.worksheet("NUEVO alertas 2026")),
        'episodios_2026_raw': _worksheet_a_df(sh_fuente_2026.worksheet("Nuevo episodios 2026")),
        'resumen_mensual':    _worksheet_a_df(sh_resumen_mensual.worksheet("Resumen MENSUAL")),
        'acumulado':          acumulado,
    }


def exportar_datos_dashboard(datos: dict, ruta: str = 'datos_dashboard.json') -> str:
    """
    Escribe a un JSON todo lo que el dashboard necesita para dibujarse.

    Este es el puente Colab -> servidor: Colab corre el pipeline y genera
    este archivo; el servidor solo lo lee. Así la parte visual no necesita
    credenciales de Google ni acceso a las hojas.

    Las tablas se guardan como listas de diccionarios (orient='records'),
    que es el formato más estable para reconstruirlas después. Se incluye
    la fecha de generación para poder mostrar qué tan frescos son los datos.
    """
    paquete = {
        'generado': datetime.now().isoformat(timespec='seconds'),
        'tablas': {nombre: _df_nativo(datos[nombre]).to_dict(orient='records')
                   for nombre in _TABLAS_DASHBOARD},
    }

    ruta_p = Path(ruta)
    ruta_p.write_text(json.dumps(paquete, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"OK: Datos del dashboard exportados a {ruta_p.resolve()} "
          f"({ruta_p.stat().st_size / 1024:.0f} KB)")
    return str(ruta_p.resolve())


def cargar_datos_dashboard(ruta: str = 'datos_dashboard.json') -> dict:
    """Reconstruye el diccionario de DataFrames a partir del JSON exportado."""
    ruta_p = Path(ruta)
    if not ruta_p.exists():
        raise FileNotFoundError(
            f"No se encontró {ruta_p.resolve()}. Genera el archivo desde Colab con "
            f"run_full_pipeline(exportar_json='datos_dashboard.json').")

    paquete = json.loads(ruta_p.read_text(encoding='utf-8'))
    print(f"Datos del dashboard leídos de {ruta_p.name} "
          f"(generados el {paquete.get('generado', '?')})")

    return {nombre: pd.DataFrame(filas)
            for nombre, filas in paquete['tablas'].items()}


def build_dash_app_desde_json(ruta: str = 'datos_dashboard.json') -> Dash:
    """
    Arma el dashboard leyendo el JSON en vez de Google Sheets. Es el punto de
    entrada para el servidor.
    """
    return build_dash_app(datos=cargar_datos_dashboard(ruta))


def build_dash_app(gc=None, spreadsheet_destino=None, acumulado: pd.DataFrame = None,
                    datos: dict = None) -> Dash:
    """
    Construye la app de Dash: KPIs + Episodios + Alertas/Emergencias +
    IMECA Máximo + serie mensual + mapa + bitácoras.

    Se puede llamar de dos formas:
      · build_dash_app(gc, spreadsheet_destino, acumulado)  -> lee de Sheets
      · build_dash_app(datos=...)                           -> usa un dict ya
        cargado (por ejemplo desde el JSON, en el servidor)

    Cuando no hay `gc`, los callbacks que refrescan desde Sheets cada 20s se
    desactivan: sin credenciales no hay a quién preguntarle. El dashboard
    muestra la foto del JSON, que es justo lo que se espera en el servidor.
    """
    if datos is None:
        datos = _leer_datos_de_sheets(gc, spreadsheet_destino, acumulado)

    df_episodios          = datos['episodios']
    df_alertas            = datos['alertas']
    df_imeca              = datos['imeca']
    df_alertas_2026_raw   = datos['alertas_2026_raw']
    df_episodios_2026_raw = datos['episodios_2026_raw']
    df_resumen_mensual    = datos['resumen_mensual']
    acumulado             = datos['acumulado']

    eventos_activos_2026 = _eventos_activos_2026(df_alertas_2026_raw)
    episodios_activos_2026 = _episodios_activos_raw(df_episodios_2026_raw)
    hay_conexion_sheets = gc is not None

    col_2025_ep = df_episodios.columns[1]
    col_2026_ep = df_episodios.columns[2]
    col_2026_al = df_alertas.columns[2]

    # Fila superior: las tres fichas solo con datos 2026. La tercera
    # (Episodios activos) se actualiza sola cada 20s con su callback.
    kpis = html.Div([
        _kpi_activaciones_simaj(df_episodios, col_2026_ep),
        _kpi_alertas_emergencias(df_alertas, col_2026_al),
        html.Div(id='ficha-eventos-activos',
                 children=_card_eventos_activos(eventos_activos_2026, episodios_activos_2026),
                 style={'flex': '1', 'minWidth': '260px', 'display': 'flex'}),
        dcc.Interval(id='refrescar-eventos',
                     interval=CONFIG.refresco_eventos_seg * 1000, n_intervals=0),
    ], className='fila-apilable', style={'display': 'flex', 'gap': '16px', 'flexWrap': 'wrap',
              'alignItems': 'stretch', 'marginBottom': '20px'})

    episodios_card = html.Div([
        html.Div([
            'Comparativo de Episodios de mala calidad del Aire ',
            html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
            '-',
            html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
        ], style={'color': '#111C51', 'fontWeight': '700', 'fontSize': '18px', 'marginBottom': '4px'}),
        html.Div('Episodios decretados de acuerdo con el Plan de Respuesta a Emergencias y Contingencias Atmosféricas (PRECA) del Estado de Jalisco.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        html.Div([
            html.Div([_tabla_episodios(df_episodios)],
                     style={'flex': '1 1 380px', 'minWidth': '340px'}),
            # Contenedores vacíos que ECharts llena desde el callback
            # clientside. La altura va aquí porque ECharts necesita que el
            # div ya tenga tamaño antes de inicializarse.
            html.Div([
                # La altura (ALTO_GRAFICA_EPISODIOS) deja la pareja de barras
                # emparejada con la tabla de la izquierda cuando su acordeón
                # está colapsado. El flex-grow 2 (contra el 1 de la tabla)
                # reparte el ancho sobrante a favor de las gráficas, para que
                # las barras salgan más anchas y quepan las etiquetas.
                html.Div(id='echart-precontingencias',
                         style={'flex': '1', 'minWidth': '320px', 'height': ALTO_GRAFICA_EPISODIOS}),
                html.Div(id='echart-contingencias-f1',
                         style={'flex': '1', 'minWidth': '320px', 'height': ALTO_GRAFICA_EPISODIOS}),
            ], className='fila-apilable', style={'flex': '2 1 460px', 'minWidth': '650px',
                      'display': 'flex', 'gap': '2px', 'alignItems': 'stretch'}),
        ], className='fila-apilable', style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap',
                  'alignItems': 'stretch'}),

        # Destino de descarte del callback que dibuja las gráficas.
        dcc.Store(id='echarts-dibujado'),
        dcc.Store(id='datos-echarts-episodios', data={
            'precontingencias': _datos_grafica_episodios(
                df_episodios, col_2025_ep, col_2026_ep, 1, 'Precontingencias atmosféricas'),
            'contingencias_f1': _datos_grafica_episodios(
                df_episodios, col_2025_ep, col_2026_ep, 2, 'Contingencias Fase I'),
            # Valores que antes se interpolaban dentro de la cadena de JS y
            # ahora viajan como datos (los lee assets/dashboard.js).
            'gris': COLOR_GRIS,
            'alto_grafica': ALTO_GRAFICA_EPISODIOS,
        }),
    ], style={**CARD_STYLE, 'marginBottom': '20px'})

    alertas_card = html.Div([
        html.Div([
            'Comparativo de Alertas y Emergencias ',
            html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
            '-',
            html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
        ], style={'color': '#111C51', 'fontWeight': '700', 'fontSize': '18px', 'marginBottom': '4px'}),
        html.Div('Episodios derivados de eventos extraordinarios de acuerdo con el Plan de Respuesta a Emergencias y Contingencias Atmosféricas (PRECA) del Estado de Jalisco.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        # Tabla izquierda + barras horizontales derechas en el mismo cuadro
        html.Div([
            # Mitad izquierda: tabla comparativa
            html.Div(
                [_tabla_alertas(df_alertas)],
                style={'flex': '1 1 420px', 'minWidth': '340px'},
            ),
            # Mitad derecha: dos barras horizontales apiladas (una por año)
            html.Div([
                html.Div(id='echart-barras-alertas-25',
                         style={'flex': '1', 'minHeight': '100px'}),
                html.Div(id='echart-barras-alertas-26',
                         style={'flex': '1', 'minHeight': '100px'}),
            ], style={'flex': '1 1 400px', 'minWidth': '690px',
                      'display': 'flex', 'flexDirection': 'column', 'gap': '6px',
                      'alignSelf': 'stretch'}),
        ], className='fila-apilable',
           style={'display': 'flex', 'gap': '20px',
                  'flexWrap': 'wrap', 'alignItems': 'stretch'}),
        # Datos para ECharts (se consumen en el clientside_callback)
        dcc.Store(id='datos-barras-alertas',
                  data=_datos_barras_alertas(df_alertas)),
        dcc.Store(id='barras-alertas-dibujado'),
    ], style={**CARD_STYLE, 'flex': '1', 'minWidth': '320px', 'marginBottom': '20px'})

    imeca_card = html.Div([_card_imeca(df_imeca)], style={**CARD_STYLE, 'marginBottom': '20px'})

    acumulado_idx = acumulado.set_index('Estación')

    # Foto fija del mapa, generada aquí en Python. El callback del PDF la usa
    # en vez de intentar capturar el mapa interactivo desde el navegador.
    fig_mapa = _fig_mapa(acumulado)
    mapa_estatico_src = _fig_a_base64(fig_mapa, ancho=1000, alto=520)

    if mapa_estatico_src is None:
        # Segundo intento sin los mosaicos del mapa base. Si kaleido no logra
        # descargar el estilo de CARTO (sin red, bloqueado o versión vieja de
        # kaleido), un fondo blanco sí se renderiza: se pierden las calles
        # pero quedan las burbujas y los nombres de estación, que es lo que
        # el PDF necesita mostrar.
        print("  Reintentando la imagen del mapa sin el mapa base…")
        fig_sin_mosaicos = _fig_mapa(acumulado)
        fig_sin_mosaicos.update_layout(map_style='white-bg')
        mapa_estatico_src = _fig_a_base64(fig_sin_mosaicos, ancho=1000, alto=520)

    if mapa_estatico_src:
        print("OK: Imagen del mapa lista para el PDF.")

    mapa_card = html.Div([
        html.Div([
            'Comparativo en días de Calidad del Aire ',
            html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
            ' vs ',
            html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
            ' por estación de monitoreo',
        ], style={'color': '#111C51', 'fontWeight': '700', 'fontSize': '18px', 'marginBottom': '4px'}),
        html.Div([
            html.Div([
                dcc.Graph(id='mapa-grafico', figure=fig_mapa,
                          className='grafica-mapa', style={'height': '480px'},
                          config={'responsive': True}),
                # Oculta en pantalla; el callback del PDF la muestra en lugar
                # del mapa interactivo justo antes de capturar.
                # Fuera del flujo del documento (no solo display:none) para
                # que no ocupe espacio ni la dibuje html2canvas.
                html.Img(id='mapa-estatico', src=mapa_estatico_src,
                         style={'position': 'absolute', 'width': '1px',
                                'height': '1px', 'opacity': '0',
                                'pointerEvents': 'none', 'left': '-9999px'}),
                # Dispara, una sola vez al cargar, el ajuste de zoom del mapa
                # en celular (ver clientside_callback correspondiente). No
                # tiene otro propósito: Dash exige un Input real y la figura
                # no vive en un Store como la de la serie mensual.
                dcc.Store(id='mapa-cargado', data=True),
                # Destino de descarte de ese mismo callback (dibuja
                # directamente con Plotly.relayout y no devuelve nada útil,
                # pero Dash exige una salida).
                dcc.Store(id='mapa-zoom-ajustado'),
            ], style={'flex': '2', 'minWidth': '320px'}),
            html.Div([
                # Encabezado del panel: título y aclaración van juntos como un
                # bloque, separados del contenido por una línea. Sin esa
                # división, la aclaración y el texto de abajo competían por
                # ser lo mismo y el panel se veía desalineado.
                html.Div([
                    html.Div('Detalle por estación', style={
                        'color': '#173d4c', 'fontWeight': '700',
                        'fontSize': '16px', 'marginBottom': '4px'}),
                    html.Div('Categoría acorde con el Índice Aire y Salud de la NOM-172-SEMARNAT-2023',
                             style={'color': COLOR_GRIS_MUTE, 'fontSize': '13px',
                                    'lineHeight': '1.45'}),
                ], style={'borderBottom': f'1px solid {COLOR_GRIS_100}',
                          'paddingBottom': '12px', 'marginBottom': '4px'}),
                html.Div(id='mapa-detalle', children=_detalle_placeholder()),
            ], className='panel-detalle-mapa',
               style={'flex': '1', 'minWidth': '260px',
                      'borderLeft': f'1px solid {COLOR_GRIS_100}', 'paddingLeft': '20px'}),
        ], className='fila-apilable', style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap'}),
        html.P([
            "El color y tamaño de cada burbuja representan el ",
            html.B([
                "cambio en días de buena calidad (",
                html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
                ' vs ',
                html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
                ')',
            ]),
            " por estación: ",
            html.Span("aqua", style={'color': COLOR_2026, 'fontWeight': '700'}),
            " = tuvo más días de buena calidad que el año pasado, ",
            html.Span("gris", style={'color': COLOR_2025, 'fontWeight': '700'}),
            " = tuvo menos; entre más grande la burbuja, mayor el cambio. "
            "Pasa el cursor sobre una estación para ver el comparativo completo en el panel de la derecha.",
        ], style={'color': COLOR_MUTED, 'fontSize': '14px', 'marginTop': '14px', 'marginBottom': '0'}),
    ], style={**CARD_STYLE, 'marginBottom': '20px'})

    bitacora_alertas_card, df_bitacora_alertas = _card_bitacora_alertas(df_alertas_2026_raw)
    bitacora_episodios_card, df_bitacora_episodios = _card_bitacora_episodios(df_episodios_2026_raw)

    parametros_card = html.Div(
        _tabla_parametros(),
        style={**CARD_STYLE, 'marginBottom': '20px'})

    # El meta 'viewport' es lo que hace que un teléfono renderice a su ancho
    # real. Sin él asume 980px y luego encoge la página entera, así que el
    # reporte se ve diminuto por más medias queries que se escriban.
    app = Dash(__name__, assets_folder=str(_ASSETS),
               url_base_pathname=CONFIG.ruta_base_dashboard, meta_tags=[
        {'name': 'viewport', 'content': 'width=device-width, initial-scale=1'},
    ])
    app.title = 'Reporte Diario de Calidad del Aire 2026'

    # CSS global + de impresión. Los cortes responsive viven aparte, en
    # assets/responsive.css, que Dash sirve solo por estar en esa carpeta.
    #
    #  · min-width solo durante la captura: antes era fijo en html/body y el
    #    dashboard nunca se angostaba de 1280px, así que en una ventana chica
    #    aparecía scroll horizontal en vez de reacomodarse. Se conserva la
    #    idea original —el PDF debe salir con el layout de escritorio— pero
    #    limitada al momento de la foto, mediante la clase que pone el
    #    callback de descarga.
    #  · print-color-adjust: exact -> obliga al navegador a imprimir los
    #    fondos de color, que por defecto omite para ahorrar tinta.
    app.index_string = '''<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&display=swap" rel="stylesheet">
    {%css%}
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script>
      if (typeof echarts !== 'undefined') {
        echarts.registerTheme('montserrat', {textStyle: {fontFamily: 'Montserrat, sans-serif'}});
      }
    </script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
    <style>
      * {
        font-family: 'Montserrat', sans-serif !important;
      }
      html, body {
        margin: 0;
      }
      /* Paginación de tablas bitácora más pequeña */
      .previous-next-container,
      .previous-next-container * {
        font-size: 10px !important;
      }
      .previous-next-container button {
        width: 20px !important;
        height: 20px !important;
        padding: 0 !important;
      }
      .previous-next-container button svg {
        width: 10px !important;
        height: 10px !important;
      }
      /* Ancho de escritorio forzado mientras html2canvas toma la foto, para
         que el PDF salga igual desde un celular que desde una computadora.
         La clase la pone y la quita el callback de descarga. */
      body.capturando-pdf,
      body.capturando-pdf #react-entry-point {
        min-width: 1280px;
      }
      /* Durante la captura del PDF el título baja debajo de los logos,
         igual que en escritorio. */
      body.capturando-pdf .fila-encabezado,
      body.capturando-pdf .fila-encabezado > div:first-child,
      body.capturando-pdf .fila-encabezado > div:last-child {
        align-items: flex-start !important;
      }
      body.capturando-pdf .fila-encabezado .titulo-reporte {
        margin-top: 92px !important;
      }
      @media print {
        @page { size: A4 portrait; margin: 5mm; }
        /* La impresión con Ctrl+P también va en el layout de escritorio. Antes
           lo heredaba del min-width global; al hacerlo responsive hay que
           repetirlo aquí, o imprimir desde una ventana angosta saldría con las
           tarjetas apiladas. */
        html, body, #react-entry-point {
          min-width: 1280px !important;
        }
        html, body {
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
          background: #ffffff !important;
        }
        * {
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
        }
        button, .previous-next-container, .dash-spreadsheet-menu {
          display: none !important;
        }
        #react-entry-point > div { padding: 0 !important; }
        .dash-graph, table {
          break-inside: avoid;
          page-break-inside: avoid;
        }
      }
    </style>
  </head>
  <body>
    {%app_entry%}
    <footer>
      {%config%}
      {%scripts%}
      {%renderer%}
    </footer>
  </body>
</html>'''

    app.layout = html.Div([
        # Botón de descarga en su propia fila, para no descentrar el título
        # ni competir con los logos.
        html.Div(_icono_descarga('btn-pdf-dashboard'),
                 style={'display': 'flex', 'justifyContent': 'flex-end', 'marginBottom': '8px'}),

        # Los tres bloques corresponden a las tres páginas del PDF: el
        # callback de descarga captura cada uno por separado y le da su
        # propia hoja, en vez de cortar a ciegas una imagen larguísima.
        # Visualmente no cambian nada — son contenedores sin estilo.
        html.Div([
            _encabezado_reporte(),
            kpis,
            episodios_card,
            html.Div([alertas_card], className='fila-apilable',
                     style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap'}),
        ], id='pdf-pagina-1'),

        html.Div([
            _card_serie_mensual_2025(df_resumen_mensual),
            mapa_card,
            imeca_card,
        ], id='pdf-pagina-2'),

        html.Div([
            bitacora_episodios_card,
            bitacora_alertas_card,
            parametros_card,
        ], id='pdf-pagina-3'),
    ], className='lienzo-reporte', style={
        'backgroundColor': COLOR_BG,
        'minHeight': '100vh',
        'padding': '28px 36px',
        'fontFamily': 'Montserrat, sans-serif',
        'color': COLOR_TEXT,
    })

    @app.callback(Output('mapa-detalle', 'children'), Input('mapa-grafico', 'hoverData'))
    def _actualizar_detalle_estacion(hover_data):
        if not hover_data or 'points' not in hover_data or not hover_data['points']:
            return _detalle_placeholder()
        punto = next((p for p in hover_data['points'] if p.get('curveNumber') == 0),
                      hover_data['points'][0])
        # Con mode='markers+text' el campo donde Plotly mete el nombre puede
        # variar entre versiones (hovertext, text, customdata). Se prueban
        # todos para que funcione sin importar la versión de Plotly/Colab.
        estacion = punto.get('hovertext')
        if estacion not in acumulado_idx.index:
            estacion = punto.get('text')
        if estacion not in acumulado_idx.index:
            cd = punto.get('customdata')
            if cd and len(cd) > 1:
                estacion = cd[1]
        if estacion not in acumulado_idx.index:
            return _detalle_placeholder()
        return _tabla_detalle_estacion(estacion, acumulado_idx.loc[estacion])

    # En celular las bitácoras largas empiezan colapsadas y se abren al tocar el
    # título. En escritorio la regla simplemente no aplica, así que el estado de
    # la clase no afecta la visibilidad.
    @app.callback(
        Output('bitacora-alertas-wrapper', 'className'),
        Output('bitacora-episodios-wrapper', 'className'),
        Input('bitacora-alertas-header', 'n_clicks'),
        Input('bitacora-episodios-header', 'n_clicks'),
        State('bitacora-alertas-wrapper', 'className'),
        State('bitacora-episodios-wrapper', 'className'),
        prevent_initial_call=True
    )
    def _toggle_bitacoras(n_alertas, n_episodios, clase_alertas, clase_episodios):
        trigger = callback_context.triggered[0]['prop_id'].split('.')[0] if callback_context.triggered else None
        return _siguiente_clases_bitacoras(trigger, clase_alertas, clase_episodios)

    # Estos dos callbacks releen de Sheets cada 20s. Solo se registran si hay
    # conexión: en el servidor, que trabaja con el JSON, no hay credenciales
    # de Google y el dashboard muestra la foto del archivo.
    if hay_conexion_sheets:
        def _leer_hoja_cacheada(url: str, hoja: str, segundos: int) -> pd.DataFrame:
            """
            Lee una pestaña de Sheets reusando el resultado entre pestañas del
            navegador. Sin esto, N pestañas abiertas son N lecturas por tick.
            """
            return cache_sheets.obtener(
                (url, hoja), segundos,
                lambda: _worksheet_a_df(gc.open_by_url(url).worksheet(hoja)))

        @app.callback(Output('ficha-eventos-activos', 'children'),
                      Input('refrescar-eventos', 'n_intervals'))
        def _refrescar_eventos_activos(_n):
            # Así, un cambio en 'Fecha termino' se refleja sin volver a correr
            # todo el pipeline de Python.
            df_alertas_fresco = _leer_hoja_cacheada(
                URL_FUENTE_2026, "NUEVO alertas 2026", CONFIG.refresco_eventos_seg)
            df_episodios_fresco = _leer_hoja_cacheada(
                URL_FUENTE_2026, "Nuevo episodios 2026", CONFIG.refresco_eventos_seg)
            return _card_eventos_activos(
                _eventos_activos_2026(df_alertas_fresco),
                _episodios_activos_raw(df_episodios_fresco),
            )

        # Escribe al Store y no a la gráfica: quien dibuja es el callback
        # clientside de abajo, que es el que sabe el ancho de la pantalla.
        @app.callback(Output('figura-serie-base', 'data'),
                      Input('refrescar-serie-mensual', 'n_intervals'))
        def _refrescar_serie_mensual(_n):
            df_fresco = _leer_hoja_cacheada(
                URL_RESUMEN_MENSUAL, "Resumen MENSUAL", CONFIG.refresco_mensual_seg)
            return _fig_serie_buena_mensual(df_fresco).to_plotly_json()

    # ── Descarga de las bitácoras en PDF ──────────────────────────────────
    #
    # La generación vive en numeralia.reporte.pdf: armar un PDF con fpdf2 no
    # tiene por qué estar anidado dentro de la función que construye la app.
    _ruta_logo_simaj = os.path.join(str(_RAIZ_REPO),
                                    NOMBRE_CARPETA_LOGOS, LOGO_SIMAJ)
    _ruta_logo_semadet = os.path.join(str(_RAIZ_REPO),
                                      NOMBRE_CARPETA_LOGOS, LOGO_SEMADET)
    registrar_descargas(app, [
        DescargaPDF(
            df=df_bitacora_alertas,
            titulo='Alertas y Emergencias Atmosféricas 2026',
            subtitulo='Eventos extraordinarios decretados de acuerdo con el Plan de Respuesta a Emergencias y Contingencias Atmosféricas (PRECA) del Estado de Jalisco.\nCORTE AL ' + _fecha_encabezado(),
            archivo=f'{_fecha_archivo()}_Eventos.pdf',
            boton_id='btn-pdf-alertas',
            descarga_id='descarga-pdf-alertas',
            logo_izq=_ruta_logo_simaj,
            logo_der=_ruta_logo_semadet,
        ),
        DescargaPDF(
            df=df_bitacora_episodios,
            titulo='Episodios de Mala calidad del aire',
            subtitulo='Episodios decretados de acuerdo con el Plan de Respuesta a Emergencias y Contingencias Atmosféricas (PRECA) del Estado de Jalisco.\nCORTE AL ' + _fecha_encabezado(),
            archivo=f'{_fecha_archivo()}_Episodios.pdf',
            boton_id='btn-pdf-episodios',
            descarga_id='descarga-pdf-episodios',
            logo_izq=_ruta_logo_simaj,
            logo_der=_ruta_logo_semadet,
        ),
    ])

    # ── Gráficas de episodios con ECharts ─────────────────────────────────
    #
    # ECharts se carga por CDN (ver index_string) y se dibuja desde el
    # navegador, no desde Python. El renderer va en 'svg' a propósito: el de
    # canvas, que es el predeterminado, no se captura bien al generar el PDF.
    app.clientside_callback(
        ClientsideFunction(namespace='dashboard', function_name='barrasEpisodios'),
        Output('echarts-dibujado', 'data'),
        Input('datos-echarts-episodios', 'data'),
    )

    # ── Acordeón de la tabla comparativa de episodios ────────────────────
    #
    # Los grupos 1 (Precontingencias) y 2 (Contingencias Fase I) tienen sub-filas
    # en la tabla; el toggle alterna display:none ↔ table-row-group y rota la
    # flecha ▶ ↔ ▼. Usa paridad de n_clicks: impar=abierto, par=cerrado.
    app.clientside_callback(
        ClientsideFunction(namespace='dashboard', function_name='toggleAcordeonEpisodios'),
        Output('sub-episodios-1', 'style'),
        Output('sub-episodios-2', 'style'),
        Output('arrow-episodios-1', 'children'),
        Output('arrow-episodios-2', 'children'),
        Input('toggle-episodios-1', 'n_clicks'),
        Input('toggle-episodios-2', 'n_clicks'),
        prevent_initial_call=True,
    )

    # ── Barras horizontales Alertas / Emergencias ─────────────────────────
    #
    # Mismo estilo visual que las gráficas de episodios: esquinas redondeadas,
    # borde del color del año, rich text con nombre + valor en tamaños distintos,
    # y labelLayout: hideOverlap para segmentos angostos.
    # Dos barras, una por año. Tono tenue = Alertas; tono pleno = Emergencias.
    app.clientside_callback(
        ClientsideFunction(namespace='dashboard', function_name='barrasAlertas'),
        Output('barras-alertas-dibujado', 'data'),
        Input('datos-barras-alertas', 'data'),
    )

    # ── Serie mensual: cintillo de pastillas solo si hay ancho ───────────
    #
    # Las pastillas se dibujan con el ancho en unidades de categoría y el alto
    # en fracción del lienzo, así que al angostarse la gráfica el ancho encoge
    # y el alto no: en un teléfono quedan de 5 px de ancho por 33 de alto, con
    # un número de dos dígitos encima. En vez de deformarlas se quitan, y el
    # dato se sigue consultando al tocar cada punto.
    #
    # Se adapta aquí y no en Python porque el servidor no sabe el ancho de la
    # pantalla; y se hace clientside para no pagar un viaje al servidor cada
    # vez que alguien gira el teléfono.
    app.clientside_callback(
        ClientsideFunction(namespace='dashboard', function_name='cintilloSerieMensual'),
        Output('grafico-serie-mensual', 'figure'),
        Input('figura-serie-base', 'data'),
    )

    # ── Mapa: menos zoom en celular ───────────────────────────────────────
    #
    # El zoom de 10.3 con el que se genera el mapa (ver _fig_mapa) se pensó
    # para el ancho de escritorio; en un teléfono, con la mitad del espacio,
    # se ve demasiado cerca y cuesta ubicar las estaciones entre sí. Se ajusta
    # aquí y no en Python porque el servidor no sabe el ancho de la pantalla.
    #
    # Solo aplica en celular (<= 767px), no en tablet: en tablet el mapa ya
    # se ve bien tal cual. Por eso se compara contra window.innerWidth en vez
    # de reusar '--modo-compacto', que se enciende también en tablet.
    #
    # No afecta al PDF: la imagen del mapa que va en el PDF es la que genera
    # Python con kaleido (ver 'mapa-estatico'), siempre al zoom de escritorio,
    # y no pasa por este callback.
    app.clientside_callback(
        ClientsideFunction(namespace='dashboard', function_name='mapaZoom'),
        Output('mapa-zoom-ajustado', 'data'),
        Input('mapa-cargado', 'data'),
    )

    # ── PDF del dashboard: captura y descarga directa ────────────────────
    #
    # html2canvas fotografía el DOM y jsPDF arma el archivo, así el clic
    # descarga el PDF sin pasar por el diálogo de impresión.
    #
    # Cada bloque 'pdf-pagina-N' se captura por separado y ocupa una hoja,
    # escalado para caber completo. Así el corte entre páginas cae donde
    # queremos y no a la mitad de una tarjeta, y el mapa se reduce solo lo
    # necesario para el PDF sin afectar la pantalla.
    #
    # Antes de capturar hay que convertir las gráficas a imagen: html2canvas
    # no sabe leer el canvas WebGL de Plotly (el mapa saldría en blanco) ni
    # rasteriza confiablemente el SVG de ECharts.
    app.clientside_callback(
        ClientsideFunction(namespace='dashboard', function_name='descargarPdf'),
        Output('btn-pdf-dashboard', 'title'),
        Input('btn-pdf-dashboard', 'n_clicks'),
        State('datos-echarts-episodios', 'data'),
        prevent_initial_call=True,
    )

    return app

