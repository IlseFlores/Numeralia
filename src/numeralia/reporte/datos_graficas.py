"""
Preparación de datos para las gráficas del dashboard que se dibujan en el
navegador (ECharts) y para las fichas de eventos/episodios activos.

Todas estas funciones reciben un DataFrame y devuelven estructuras planas
(dict / list) serializables a JSON, listas para un ``dcc.Store``. No tocan
Dash. El dibujo lo hace assets/dashboard.js.

Salieron de main.py (Sección 6) en el Paso 2 del refactor.
"""

import pandas as pd

from numeralia.reporte.formato import _buscar_columna, _sin_acentos, _to_num
from numeralia.reporte.tema import (
    COLOR_2025,
    COLOR_2026,
    COLOR_BLANCO,
    COLOR_GRIS_MUTE,
    COLOR_TEXT,
    ESCALA_ANIO_ACTUAL,
    ESCALA_ANIO_PREVIO,
    ESCALA_EPISODIOS_ANIO_ACTUAL,
    ESCALA_EPISODIOS_ANIO_PREVIO,
)

# Ozono usa el mismo tono claro que las alertas de ese año.
_COLOR_ALERTA_25 = ESCALA_ANIO_PREVIO[0]   # azul marino muy claro
_COLOR_ALERTA_26 = ESCALA_ANIO_ACTUAL[0]   # aqua muy claro

# Etiqueta de grupo de la tabla de Episodios -> nivel de severidad.
_EPISODIOS_ENCABEZADOS = {
    'Precontingencias atmosféricas:':          1,
    'Contingencias atmosféricas Fase I:':      2,
    'Contingencias atmosféricas Fase II:':     3,
    'Contingencias atmosféricas Fase III:':    4,
}

_ORDEN_CONTAMINANTES = ('Ozono', 'PM10', 'PM2.5')

# Nombre de evento (hoja episodios 2026) -> nivel de severidad.
_EVENTO_SEVERIDAD = {
    'PreContingencia Atmosférica':        1,
    'Contingencia Atmosférica Fase I':    2,
    'Contingencia Atmosférica Fase II':   3,
    'Contingencia Atmosférica Fase III':  4,
}


def _episodios_por_contaminante(df: pd.DataFrame, anio_col: str, severidad: int):
    """
    Devuelve [(contaminante, valor), ...] de las subcategorías que cuelgan del
    grupo de severidad indicado (1 = precontingencias, 2 = Fase I, …).

    Se recorre la tabla de arriba a abajo llevando cuenta del grupo activo,
    en vez de buscar los nombres exactos de las subfilas, porque en la hoja
    esas filas vienen indentadas con espacios y su texto cambia entre grupos.
    """
    col_label = df.columns[0]
    grupo_actual = 0
    datos = []
    for _, row in df.iterrows():
        etiqueta = str(row[col_label]).strip()
        sev = _EPISODIOS_ENCABEZADOS.get(etiqueta, 0)
        if sev:
            grupo_actual = sev
            continue
        if etiqueta.lower().startswith('episodios totales') or grupo_actual != severidad:
            continue

        norm = _sin_acentos(etiqueta).lower()
        if 'ozono' in norm:
            contaminante = 'Ozono'
        elif 'pm10' in norm:
            contaminante = 'PM10'
        elif 'pm2.5' in norm or 'pm25' in norm:
            contaminante = 'PM2.5'
        else:
            continue

        datos.append((contaminante, int(_to_num(row[anio_col]) or 0)))
    return datos


def _datos_grafica_episodios(df: pd.DataFrame, col_2025: str, col_2026: str,
                              severidad: int, titulo: str) -> dict:
    """
    Empaqueta lo que la gráfica de ECharts necesita para un grupo de
    severidad. Se devuelve como diccionario plano (serializable a JSON) para
    mandarlo al navegador en un dcc.Store; el dibujo lo arma el callback
    clientside, que es donde vive ECharts.
    """
    datos_25 = dict(_episodios_por_contaminante(df, col_2025, severidad))
    datos_26 = dict(_episodios_por_contaminante(df, col_2026, severidad))
    contaminantes = list(_ORDEN_CONTAMINANTES)

    _escala_25 = list(reversed(ESCALA_EPISODIOS_ANIO_PREVIO))
    _escala_26 = list(ESCALA_EPISODIOS_ANIO_ACTUAL)
    # El Ozono usa el mismo tono claro que las alertas de ese año.
    _escala_25[0] = _COLOR_ALERTA_25
    _escala_26[0] = _COLOR_ALERTA_26

    return {
        'titulo': titulo,
        # Los títulos van en el negro de texto del reporte, no en el color de
        # severidad: esa lectura ya la da la tabla comparativa de al lado.
        'color_titulo': COLOR_TEXT,
        'anios': ['2025', '2026'],
        # Colores de cada año, en el mismo orden que 'anios'. Las barras y los
        # totales se pintan con estos; la severidad se queda en el título.
        'colores_anio': [COLOR_2025, COLOR_2026],
        # Un tono por contaminante, dentro del color de cada año. El índice
        # de la serie elige el tono; el del año elige la escala.
        # El apilado va de suave (Ozono, índice 0) a fuerte (PM2.5, índice 2):
        #   - 2025: la escala original va de oscuro a claro, así que se invierte.
        #   - 2026: la escala original ya va de claro a oscuro, se usa tal cual.
        # Ozono = tono claro de alertas; PM10/PM2.5 = degradado del año.
        'escalas_anio': [_escala_25, _escala_26],
        # Color del texto de cada segmento, por año y por contaminante.
        #   Ozono: color gris como en las gráficas de Alertas.
        #   PM10/PM2.5: blanco sobre fondos medios/oscuros.
        'colores_texto_anio': [
            [
                {'nombre': COLOR_GRIS_MUTE, 'valor': COLOR_GRIS_MUTE},  # Ozono – tono claro
                {'nombre': COLOR_BLANCO, 'valor': COLOR_BLANCO},   # PM10  – tono medio
                {'nombre': COLOR_BLANCO, 'valor': COLOR_BLANCO},   # PM2.5 – tono oscuro
            ],
            [
                # Gris (no aqua): el aqua sobre el tono claro de Ozono casi no
                # se leía. Mismo criterio que Ozono 2025 y que las Alertas.
                {'nombre': COLOR_GRIS_MUTE, 'valor': COLOR_GRIS_MUTE},  # Ozono 2026 – tono claro
                {'nombre': COLOR_BLANCO, 'valor': COLOR_BLANCO},   # PM10  – tono medio
                {'nombre': COLOR_BLANCO, 'valor': COLOR_BLANCO},   # PM2.5 – tono oscuro
            ],
        ],
        'series': [
            {'nombre': c,
             'datos': [datos_25.get(c, 0), datos_26.get(c, 0)]}
            for c in contaminantes
        ],
        'totales': [sum(datos_25.values()), sum(datos_26.values())],
    }


def _datos_barras_alertas(df_alertas: pd.DataFrame) -> dict:
    """
    Extrae alertas y emergencias por año del DataFrame comparativo para
    pasarlos como JSON al clientside_callback de ECharts.
    """
    col_label, col_2025, col_2026 = df_alertas.columns[0], df_alertas.columns[1], df_alertas.columns[2]

    def _val(prefix, col):
        m = df_alertas[df_alertas[col_label].str.strip().str.lower().str.startswith(prefix.lower())]
        return int(_to_num(m.iloc[0][col]) or 0) if not m.empty else 0

    return {
        'alertas_25':     _val('alerta', col_2025),
        'emergencias_25': _val('emergencia', col_2025),
        'alertas_26':     _val('alerta', col_2026),
        'emergencias_26': _val('emergencia', col_2026),
        # Colores de relleno
        'color_a25': _COLOR_ALERTA_25,
        'color_e25': COLOR_2025,
        'color_a26': _COLOR_ALERTA_26,
        'color_e26': COLOR_2026,
        # Alertas (fondo tenue): texto gris oscuro para legibilidad
        # Emergencias (fondo pleno): texto blanco
        'texto_a25': COLOR_GRIS_MUTE,
        'texto_e25': COLOR_BLANCO,
        'texto_a26': COLOR_GRIS_MUTE,
        'texto_e26': COLOR_BLANCO,
    }


def _eventos_activos_2026(df_alertas_2026: pd.DataFrame):
    """
    Un evento se considera ACTIVO si las columnas A (No) a H (Inicio) tienen
    dato (la fila es real, no un renglón vacío de la plantilla) y la columna
    'Fecha termino' está vacía. En cuanto 'Fecha termino' tenga dato, el
    evento desaparece de la ficha. Devuelve lista de dicts con tipo='alerta'.
    """
    cols = list(df_alertas_2026.columns)
    if len(cols) < 8:
        return []

    cols_a_h = cols[0:8]         # A (No) ... H (Inicio)
    col_inicio = cols[7]         # H
    col_termino = _buscar_columna(cols, 'termino', 'fin')
    if col_termino is None:
        return []

    col_municipio = _buscar_columna(cols, 'municipio')
    col_incidente = _buscar_columna(cols, 'incidente')
    col_fase = _buscar_columna(cols, 'fase decretada', 'fase')

    activos = []
    for _, row in df_alertas_2026.iterrows():
        fila_llena = all(str(row[c]).strip() != '' for c in cols_a_h)
        termino_vacio = str(row[col_termino]).strip() == ''
        if fila_llena and termino_vacio:
            fase = str(row[col_fase]).strip() if col_fase else ''
            activos.append({
                'tipo': 'alerta',
                'fase': fase,
                'inicio': str(row[col_inicio]).strip(),
                'municipio': str(row[col_municipio]).strip() if col_municipio else '',
                'incidente': str(row[col_incidente]).strip() if col_incidente else '',
            })
    return activos


def _episodios_activos_raw(df_episodios_2026: pd.DataFrame):
    """
    Un episodio en 'Nuevo episodios 2026' se considera ACTIVO si:
      - La primera columna (No) tiene dato (fila real, no plantilla vacía).
      - La columna 'Estado' existe y contiene 'activo' (sin importar mayúsculas),
        O bien no hay columna Estado pero la columna 'Fin' está vacía.

    Se limita la búsqueda de 'Fin' a columnas hasta 'Estado' para evitar
    coincidencias con otros nombres que contengan 'fin' (ej. 'Definición').
    Devuelve lista de dicts con tipo='episodio' y severidad.
    """
    cols = list(df_episodios_2026.columns)
    if not cols:
        return []

    col_no = cols[0]
    col_evento = _buscar_columna(cols, 'evento')
    col_municipio = _buscar_columna(cols, 'municipio')
    col_contaminante = _buscar_columna(cols, 'contaminante')
    col_estacion = _buscar_columna(cols, 'estacion', 'estación')
    col_estado = _buscar_columna(cols, 'estado')

    # Limitar búsqueda de 'Fin' al rango hasta Estado (como la bitácora)
    if col_estado:
        idx_estado = cols.index(col_estado)
        cols_hasta_estado = cols[0:idx_estado + 1]
    else:
        cols_hasta_estado = cols
    col_fin = _buscar_columna(cols_hasta_estado, 'fin')

    # Sin ninguna señal de terminación no podemos determinar si está activo
    if col_fin is None and col_estado is None:
        return []

    activos = []
    for _, row in df_episodios_2026.iterrows():
        # Fila vacía de plantilla: la columna No está vacía
        if str(row[col_no]).strip() == '':
            continue

        # Criterio de actividad:
        # 1) Si hay columna Estado → 'activo' en su valor
        # 2) Si no, caer en Fin vacío
        if col_estado:
            val_estado = _sin_acentos(str(row[col_estado])).strip().lower()
            es_activo = 'activo' in val_estado
        else:
            es_activo = str(row[col_fin]).strip() == ''

        if es_activo:
            evento_texto = str(row[col_evento]).strip() if col_evento else ''
            severidad = _EVENTO_SEVERIDAD.get(evento_texto, 0)
            activos.append({
                'tipo': 'episodio',
                'evento': evento_texto,
                'severidad': severidad,
                'municipio': str(row[col_municipio]).strip() if col_municipio else '',
                'contaminante': str(row[col_contaminante]).strip() if col_contaminante else '',
                'estacion': str(row[col_estacion]).strip() if col_estacion else '',
            })
    return activos
