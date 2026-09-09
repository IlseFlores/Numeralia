"""
Helpers puros de formato para la capa de reporte: texto, fechas, meses y
números. No dependen de Dash ni de Google Sheets, así que se pueden probar
solos.

Salieron de main.py (Sección 6) en el Paso 2 del refactor; main.py los
reexporta mientras el resto del dashboard sigue ahí.
"""

import unicodedata
from datetime import datetime, timedelta, timezone

import pandas as pd

# Nombres de columna de la tabla 'acumulado' (la numeralia por estación). Los
# usan el mapa y la tabla de detalle; viven aquí para que ambos módulos los
# compartan sin depender el uno del otro.
MALA_25, MALA_26 = '2025: Días con mala calidad', '2026: Días con mala calidad'
BUENA_25, BUENA_26 = '2025: Días con buena a aceptable', '2026: Días con buena a aceptable'
SINDATO_25, SINDATO_26 = '2025: Días sin dato', '2026: Días sin dato'

_MESES_ORDEN = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
}
_MESES_NOMBRE = {v: k.capitalize() for k, v in _MESES_ORDEN.items()}

_MES_ABREV = {
    1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic',
}


def _to_num(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


def _sin_acentos(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn')


def _buscar_columna(columnas, *fragmentos):
    """Busca la primera columna cuyo nombre (sin acentos, en minúsculas) contenga
    alguno de los fragmentos dados. Devuelve None si no encuentra ninguna."""
    for c in columnas:
        norm = _sin_acentos(c).lower()
        if any(frag in norm for frag in fragmentos):
            return c
    return None


def _normalizar_mes(valor):
    """Acepta el mes como nombre en español (con/sin acentos, cualquier mayúscula)
    o como número 1-12; regresa (numero_mes, nombre_mes) o (None, valor) si no
    se reconoce."""
    s = _sin_acentos(valor).strip().lower()
    if s in _MESES_ORDEN:
        n = _MESES_ORDEN[s]
        return n, _MESES_NOMBRE[n]
    try:
        n = int(float(s))
        if 1 <= n <= 12:
            return n, _MESES_NOMBRE[n]
    except (ValueError, TypeError):
        pass
    return None, str(valor)


def _fecha_encabezado() -> str:
    """
    Fecha de ayer como '20 DE AGOSTO DEL 2026'.

    El dashboard refleja datos cerrados al día anterior, así que la fecha se
    calcula sola cada vez que se levanta. Se usa _MESES_NOMBRE en vez de
    strftime('%B') porque ese depende del locale y en Colab devolvería el
    mes en inglésssss.
    """
    utc_minus_6 = timezone(timedelta(hours=-6))
    ayer = datetime.now(utc_minus_6) - timedelta(days=1)
    return f"{ayer.day} DE {_MESES_NOMBRE[ayer.month].upper()} DEL {ayer.year}"


def _fecha_mes_abreviado(valor) -> str:
    """
    Convierte '01/02/2026' en '01/Feb/2026'.

    Se usa un diccionario propio en vez de strftime('%b') porque ese depende
    del locale: en Colab saldría en inglés. Si el texto no tiene el formato
    esperado se devuelve tal cual, para no romper la tarjeta.
    """
    texto = str(valor).strip()
    partes = texto.split('/')
    if len(partes) != 3:
        return texto
    dia, mes, anio = partes
    try:
        return f"{dia}/{_MES_ABREV[int(mes)]}/{anio}"
    except (ValueError, KeyError):
        return texto


def _formatear_hora(hora) -> str:
    """Deja la hora en formato H:MM a.m./p.m., sin segundos."""
    s = str(hora).strip().replace('.', '').lower()
    s = s.replace('p.m', ' PM').replace('a.m', ' AM')
    s = s.replace('pm', ' PM').replace('am', ' AM')
    for fmt in ('%I:%M:%S %p', '%I:%M %p', '%H:%M:%S', '%H:%M'):
        try:
            dt = datetime.strptime(s, fmt)
            h12 = dt.hour % 12 or 12
            ampm = 'a.m.' if dt.hour < 12 else 'p.m.'
            return f"{h12}:{dt.minute:02d} {ampm}"
        except ValueError:
            pass
    return str(hora)


def _clasificar_imeca(valor) -> str:
    v = _to_num(valor)
    if v is None:
        return "Sin dato"
    if v <= 50:
        return "Buena"
    if v <= 100:
        return "Aceptable"
    if v <= 150:
        return "Mala"
    if v <= 200:
        return "Muy mala"
    return "Extremadamente mala"


def _siguiente_clases_bitacoras(trigger: str, clase_alertas: str, clase_episodios: str):
    """
    Decide el nuevo par de clases ('bitacora-abierta'/'bitacora-cerrada') a
    partir de qué título disparó el clic. Vive separada del callback para
    poder probarla sin un contexto de Dash: el callback solo lee
    ``callback_context`` y le pasa el resultado a esta función.
    """
    if trigger == 'bitacora-alertas-header':
        clase_alertas = 'bitacora-cerrada' if clase_alertas == 'bitacora-abierta' else 'bitacora-abierta'
    elif trigger == 'bitacora-episodios-header':
        clase_episodios = 'bitacora-cerrada' if clase_episodios == 'bitacora-abierta' else 'bitacora-abierta'
    return clase_alertas, clase_episodios


def _ordenar_por_no_desc(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena por la columna 'No' (primera columna) de mayor a menor, si es numérica.
    Descarta filas vacías que suelen quedar al final de la hoja de cálculo."""
    if df.empty:
        return df
    col_no = df.columns[0]
    d = df.copy()
    d = d[d[col_no].notna() & d[col_no].astype(str).str.strip().ne('')]
    if d.empty:
        return d
    d['_no_num'] = pd.to_numeric(d[col_no], errors='coerce')
    d = d.sort_values('_no_num', ascending=False).drop(columns='_no_num')
    return d
