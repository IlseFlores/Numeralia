"""
Episodios (Precontingencias/Contingencias) + IMECA máximo: lee las hojas
fuente 2025/2026, cuenta episodios por tipo y contaminante, compara ambos
años al mismo periodo del calendario y escribe el resultado en Sheets.

Salió de main.py (Sección 4) en el Paso 5 del refactor.
"""

import re
from datetime import datetime, timedelta
from typing import Dict

import pandas as pd
from gspread_dataframe import set_with_dataframe

from numeralia.reporte.formato import _sin_acentos
from numeralia.sheets import _df_nativo, _worksheet_a_df

_MESES_ES_A_NUM = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}


def _parse_spanish_date(date_str):
    """
    Convierte fechas en español escritas a mano a datetime.

    Es deliberadamente tolerante, porque en las hojas conviven formatos muy
    distintos y antes cualquier variante se descartaba en silencio (devolvía
    NaT) y esa fila desaparecía de los conteos. Acepta, entre otros:

        jueves, 1 de enero de 2026, 6:00
        Miércoles 29 de abril de 2026 7:00      (sin comas)
        Viernes 8 de mayo de 2026 12:00 hor     (con texto de sobra al final)
        sábado, 2 de mayo de 2026               (sin hora -> 00:00)
        MARTES, 19 DE MAYO DE 2026, 18:00       (mayúsculas, con acentos)

    Lo único indispensable es el patrón 'día de mes de año'; la hora es
    opcional y se ignora cualquier texto adicional.
    """
    if not isinstance(date_str, str):
        return pd.NaT

    texto = _sin_acentos(date_str).lower()

    m = re.search(r'(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})', texto)
    if not m:
        return pd.NaT

    dia, mes_texto, anio = m.groups()
    mes = _MESES_ES_A_NUM.get(mes_texto)
    if mes is None:
        return pd.NaT

    # La hora se busca DESPUÉS de la fecha, para no confundirse con algún
    # número que venga antes. Si no hay, se asume medianoche.
    h = re.search(r'(\d{1,2}):(\d{2})', texto[m.end():])
    hora, minuto = (int(h.group(1)), int(h.group(2))) if h else (0, 0)

    try:
        return pd.Timestamp(int(anio), mes, int(dia), min(hora, 23), min(minuto, 59))
    except ValueError:
        return pd.NaT


_MESES_EN_A_ES = {
    "January":"enero","February":"febrero","March":"marzo","April":"abril",
    "May":"mayo","June":"junio","July":"julio","August":"agosto",
    "September":"septiembre","October":"octubre","November":"noviembre","December":"diciembre",
}


def _fecha_es(fecha: datetime) -> str:
    s = fecha.strftime("%d de %B")
    for en, es in _MESES_EN_A_ES.items():
        s = s.replace(en, es)
    return s


def _contar_episodios(df: pd.DataFrame) -> Dict[str, int]:
    """Cuenta episodios por tipo de evento y contaminante."""
    resultados = {}
    contaminante = df['Contaminante'].str.strip().str.replace(' ', '', regex=False)
    evento = df['Evento'].str.strip()

    mask_pre = evento == 'PreContingencia Atmosférica'
    resultados['Precontingencias atmosféricas:'] = int(mask_pre.sum())
    resultados['   Precontingencias declaradas por Ozono'] = int((mask_pre & (contaminante == 'O3')).sum())
    resultados['   Precontingencias declaradas por PM10'] = int((mask_pre & (contaminante == 'PM10')).sum())
    resultados['   Precontingencias declaradas por PM2.5'] = int((mask_pre & (contaminante == 'PM2.5')).sum())

    mask_f1 = evento == 'Contingencia Atmosférica Fase I'
    resultados['Contingencias atmosféricas Fase I:'] = int(mask_f1.sum())
    resultados['   Contingencias declaradas por Ozono'] = int((mask_f1 & (contaminante == 'O3')).sum())
    resultados['   Contingencias declaradas por PM10'] = int((mask_f1 & (contaminante == 'PM10')).sum())
    resultados['   Contingencias declaradas por PM2.5'] = int((mask_f1 & (contaminante == 'PM2.5')).sum())

    mask_f2 = evento == 'Contingencia Atmosférica Fase II'
    resultados['Contingencias atmosféricas Fase II:'] = int(mask_f2.sum())

    mask_f3 = evento == 'Contingencia Atmosférica Fase III'
    resultados['Contingencias atmosféricas Fase III:'] = int(mask_f3.sum())

    resultados['Episodios Totales'] = len(df)
    return resultados


def cargar_episodios(gc, url_fuente_2025: str, url_fuente_2026: str):
    """Lee las hojas fuente 2025/2026 de episodios y devuelve los DataFrames + spreadsheets abiertos."""
    sh_2025 = gc.open_by_url(url_fuente_2025)
    df_2025 = _worksheet_a_df(sh_2025.worksheet("Episodios 2025"))

    sh_2026 = gc.open_by_url(url_fuente_2026)
    df_2026 = _worksheet_a_df(sh_2026.worksheet("Nuevo episodios 2026"))

    df_2025_ = df_2025.iloc[:, 0:17].copy()
    df_2026_ = df_2026.iloc[:, 0:9].copy()

    df_2025_['Dia de inicio'] = pd.to_datetime(df_2025_['Dia de inicio'], dayfirst=True, errors='coerce')
    df_2025_['IMECA'] = pd.to_numeric(df_2025_['IMECA'], errors='coerce')

    df_2026_['Inicio'] = df_2026_['Inicio'].apply(_parse_spanish_date)
    df_2026_['IMECA'] = pd.to_numeric(df_2026_['IMECA'], errors='coerce')

    return df_2025_, df_2026_, sh_2025, sh_2026


def _corte_mismo_periodo(anio: int) -> datetime:
    """
    Fecha límite del criterio 'mismo periodo del calendario' para el año dado:
    del 1 de enero de ese año hasta el mismo día/mes que ayer (hoy - 1 día).
    Es el mismo criterio que ya se usaba (en línea) para Episodios; se deja
    aquí como función reutilizable para poder aplicarlo también a Alertas y,
    en años futuros, a cualquier comparación año-actual-parcial vs año(s)
    anteriores completos, sin tener que reescribir la lógica: solo se llama
    _corte_mismo_periodo(el_año_que_sea).
    """
    ayer = datetime.now() - timedelta(days=1)
    return datetime(anio, ayer.month, ayer.day, 23, 59, 59)


def calcular_comparativo_episodios(df_2025_: pd.DataFrame, df_2026_: pd.DataFrame) -> pd.DataFrame:
    """Compara episodios activados 2025 vs 2026 en el mismo periodo del calendario (1 ene -> ayer)."""
    ayer = datetime.now() - timedelta(days=1)
    dia_ayer = ayer.day

    corte_2025 = _corte_mismo_periodo(2025)
    corte_2026 = _corte_mismo_periodo(2026)

    df_2025_parcial = df_2025_[df_2025_['Dia de inicio'] <= corte_2025]

    # Igual que en Alertas: una fecha ilegible no debe hacer desaparecer el
    # episodio del conteo. Se conserva y se avisa para corregir la hoja.
    sin_fecha_26 = df_2026_['Inicio'].isna()
    if sin_fecha_26.any():
        print(f"AVISO: {int(sin_fecha_26.sum())} episodio(s) de 2026 tienen fecha de inicio "
              f"ilegible; se cuentan de todos modos.")
    df_2026_parcial = df_2026_[sin_fecha_26 | (df_2026_['Inicio'] <= corte_2026)]

    res_2025 = _contar_episodios(df_2025_parcial)
    res_2026 = _contar_episodios(df_2026_parcial)

    fecha_str_ayer = _fecha_es(ayer)
    mes_nombre_ayer = fecha_str_ayer.split(" de ")[1]

    comparativo = pd.DataFrame({
        'Episodios activados': list(res_2025.keys()),
        f'2025 (1 ene - {dia_ayer} {mes_nombre_ayer})': list(res_2025.values()),
        f'2026 (1 ene - {dia_ayer} {mes_nombre_ayer})': list(res_2026.values()),
    }).set_index('Episodios activados')

    print(f"Comparativa al mismo periodo: 1 de enero al {fecha_str_ayer} (día de ayer)")
    print(f"  2025 filtrado: {len(df_2025_parcial)} episodios (de {len(df_2025_)} totales)")
    print(f"  2026 filtrado: {len(df_2026_parcial)} episodios (de {len(df_2026_)} totales)")

    return comparativo


def calcular_imeca_maximo(df_2025_: pd.DataFrame, df_2026_: pd.DataFrame) -> pd.DataFrame:
    """IMECA máximo registrado en el año para 2025 y 2026 (sin filtrar por periodo)."""
    max_imeca_2025 = df_2025_['IMECA'].max()
    df_max_2025 = df_2025_[df_2025_['IMECA'] == max_imeca_2025].copy()
    df_max_2025['_dt'] = pd.to_datetime(
        df_max_2025['Dia de inicio'].astype(str) + ' ' + df_max_2025['Hora de inicio'].astype(str),
        errors='coerce'
    )
    row_2025 = df_max_2025.sort_values('_dt').iloc[0]

    max_imeca_2026 = df_2026_['IMECA'].max()
    df_max_2026 = df_2026_[df_2026_['IMECA'] == max_imeca_2026].copy()
    row_2026 = df_max_2026.sort_values('Inicio').iloc[0]

    fecha_max_2025 = pd.Timestamp(row_2025['Dia de inicio']).strftime('%d/%m/%Y')
    hora_max_2025 = str(row_2025['Hora de inicio'])

    inicio_max_2026 = pd.Timestamp(row_2026['Inicio'])
    fecha_max_2026 = inicio_max_2026.strftime('%d/%m/%Y')
    hora_max_2026 = inicio_max_2026.strftime('%I:%M %p')

    imeca_max = pd.DataFrame({
        '2025': [max_imeca_2025, row_2025['Contaminante'], row_2025['Estación'], fecha_max_2025, hora_max_2025],
        '2026': [max_imeca_2026, row_2026['Contaminante'], row_2026['Estación'], fecha_max_2026, hora_max_2026],
    }, index=['IMECA Máximo del año', 'Contaminante', 'Estación', 'Fecha', 'Hora'])
    imeca_max.index.name = 'Periodo anual comparativo'

    return imeca_max


def run_episodios(gc, spreadsheet_destino, url_fuente_2025: str, url_fuente_2026: str,
                   hoja_episodios: str = "Episodios", hoja_imeca: str = "IMECA MAXIMO"):
    """Calcula Episodios + IMECA máximo y los escribe en el spreadsheet destino."""
    df_2025_, df_2026_, sh_2025, sh_2026 = cargar_episodios(gc, url_fuente_2025, url_fuente_2026)

    comparativo_parcial = calcular_comparativo_episodios(df_2025_, df_2026_)
    imeca_max = calcular_imeca_maximo(df_2025_, df_2026_)

    # _df_nativo antes de escribir: gspread no sabe serializar tipos de NumPy.
    ws_ep = spreadsheet_destino.worksheet(hoja_episodios)
    ws_ep.clear()
    set_with_dataframe(ws_ep, _df_nativo(comparativo_parcial.reset_index()), include_index=False)
    print(f"OK: Episodios actualizados en '{hoja_episodios}'.")

    ws_im = spreadsheet_destino.worksheet(hoja_imeca)
    ws_im.clear()
    set_with_dataframe(ws_im, _df_nativo(imeca_max.reset_index()))
    print(f"OK: IMECA máximo actualizado en '{hoja_imeca}'.")

    # Se regresan sh_2025 / sh_2026 para que Alertas reutilice la misma conexión
    # (son los mismos spreadsheets fuente, solo cambian de pestaña).
    return sh_2025, sh_2026
