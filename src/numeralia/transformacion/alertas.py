"""
Alertas y Emergencias: lee las hojas fuente 2025/2026, cuenta alertas y
emergencias recortadas al mismo periodo del calendario que Episodios, y
escribe el comparativo en Sheets.

Salió de main.py (Sección 5) en el Paso 5 del refactor.
"""

from datetime import datetime, timedelta
from typing import Dict

import pandas as pd
from gspread_dataframe import set_with_dataframe

from numeralia.reporte.formato import _buscar_columna
from numeralia.sheets import _df_nativo, _worksheet_a_df
from numeralia.transformacion.episodios import (
    _corte_mismo_periodo,
    _fecha_es,
    _parse_spanish_date,
)


def _contar_alertas(df: pd.DataFrame) -> Dict[str, int]:
    resultados = {}
    fase = df['Fase Decretada'].str.strip()
    resultados['Alertas:'] = int((fase == 'Alerta').sum())
    resultados['Emergencias:'] = int((fase == 'Emergencia').sum())
    resultados['Total Alertas y Emergencias'] = resultados['Alertas:'] + resultados['Emergencias:']
    return resultados


def run_alertas(sh_2025, sh_2026, spreadsheet_destino, hoja_alertas: str = "ALERTAS"):
    """
    Calcula Alertas/Emergencias 2025 vs 2026 y las escribe en el spreadsheet
    destino. Igual que Episodios y Contingencias/Precontingencias, ambos años
    se recortan al MISMO periodo del calendario (1 de enero -> ayer) usando
    _corte_mismo_periodo(), así el 2025 no cuenta el año completo, solo hasta
    la fecha a la que ya vamos en 2026. El 2026 se recorta con el mismo
    criterio por consistencia (en la práctica ya no tiene filas más allá de
    "ayer"). Esto es genérico para años futuros: cuando 2026 sea el año
    histórico completo y 2027 el parcial, basta con que las hojas fuente
    sigan el mismo patrón de columnas.
    """
    df_2025_A = _worksheet_a_df(sh_2025.worksheet("Alertas 2025")).iloc[:, 0:14].copy()
    df_2026_A = _worksheet_a_df(sh_2026.worksheet("NUEVO alertas 2026")).iloc[:, 0:11].copy()
    total_2025, total_2026 = len(df_2025_A), len(df_2026_A)

    # Columna de fecha de inicio: se busca por nombre (sin acentos/mayúsculas)
    # en vez de asumir un nombre fijo, para no romper si la hoja cambia un
    # poco el encabezado.
    col_fecha_2025 = _buscar_columna(list(df_2025_A.columns), 'dia de inicio', 'fecha de inicio', 'fecha inicio')
    col_fecha_2026 = _buscar_columna(list(df_2026_A.columns), 'inicio')

    if col_fecha_2025 is not None:
        df_2025_A['_fecha_inicio'] = pd.to_datetime(df_2025_A[col_fecha_2025], dayfirst=True, errors='coerce')
        df_2025_A = df_2025_A[df_2025_A['_fecha_inicio'] <= _corte_mismo_periodo(2025)]
    else:
        print("AVISO: No se encontró columna de fecha de inicio en 'Alertas 2025'; "
              "no se aplicó el filtro de mismo periodo (se cuenta el año completo).")

    if col_fecha_2026 is not None:
        df_2026_A['_fecha_inicio'] = df_2026_A[col_fecha_2026].apply(_parse_spanish_date)

        # Las filas con fecha ilegible se CONSERVAN en vez de descartarse.
        # Antes se perdían en silencio y el conteo de 2026 salía más bajo de
        # lo real. Se avisa cuáles son para poder corregirlas en la hoja.
        sin_fecha = df_2026_A['_fecha_inicio'].isna() & (
            df_2026_A[col_fecha_2026].astype(str).str.strip() != '')
        if sin_fecha.any():
            print(f"AVISO: {int(sin_fecha.sum())} fila(s) de 'NUEVO alertas 2026' tienen una "
                  f"fecha que no se pudo interpretar; se cuentan de todos modos:")
            for v in df_2026_A.loc[sin_fecha, col_fecha_2026].astype(str).head(10):
                print(f"    · {v!r}")

        df_2026_A = df_2026_A[df_2026_A['_fecha_inicio'].isna()
                              | (df_2026_A['_fecha_inicio'] <= _corte_mismo_periodo(2026))]
    else:
        print("AVISO: No se encontró columna de fecha de inicio en 'NUEVO alertas 2026'; "
              "no se aplicó el filtro de mismo periodo (se cuenta el año completo).")

    alertas_2025 = _contar_alertas(df_2025_A)
    alertas_2026 = _contar_alertas(df_2026_A)

    fecha_str_ayer = _fecha_es(datetime.now() - timedelta(days=1))
    print(f"Comparativa de Alertas al mismo periodo: 1 de enero al {fecha_str_ayer} (día de ayer)")
    print(f"  2025 filtrado: {len(df_2025_A)} filas (de {total_2025} totales)")
    print(f"  2026 filtrado: {len(df_2026_A)} filas (de {total_2026} totales)")

    comparativo_alertas = pd.DataFrame({
        '2025': list(alertas_2025.values()),
        '2026': list(alertas_2026.values()),
    }, index=list(alertas_2025.keys()))
    comparativo_alertas.index.name = 'Categoría'

    ws = spreadsheet_destino.worksheet(hoja_alertas)
    ws.clear()
    set_with_dataframe(ws, _df_nativo(comparativo_alertas.reset_index()))
    print(f"OK: Alertas actualizadas en '{hoja_alertas}'.")
