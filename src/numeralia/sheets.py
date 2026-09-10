"""
Puente Google Sheets <-> pandas: leer una worksheet como DataFrame y convertir
un DataFrame a algo que gspread pueda serializar.

Salieron de main.py (Secciones 0 y 3) en el Paso 3 del refactor. No importan
``gspread`` (reciben la worksheet ya abierta), así que se pueden probar con un
doble.
"""

import numpy as np
import pandas as pd


def _worksheet_a_df(ws) -> pd.DataFrame:
    """Lee todos los valores de una worksheet y arma un DataFrame (fila 1 = encabezados)."""
    valores = ws.get_all_values()
    headers, filas = valores[0], valores[1:]
    df = pd.DataFrame(filas, columns=headers)
    df.columns = df.columns.str.strip()
    return df


def _a_valor_nativo(v):
    """
    Convierte un valor de NumPy/pandas a un tipo nativo de Python.

    Hace falta porque las versiones recientes de gspread serializan a JSON
    con allow_nan=False y sin conversores para NumPy: un numpy.int64 —que es
    lo que devuelve .max() de pandas— truena con 'Object of type int64 is
    not JSON serializable'. En Colab no se nota porque trae versiones más
    permisivas, pero al correr como .py aparece.

    Los NaN se mandan como cadena vacía, que es como Sheets representa una
    celda sin dato.
    """
    if isinstance(v, np.generic):
        v = v.item()
    if v is None:
        return ''
    try:
        if isinstance(v, float) and pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    return v


def _df_nativo(df: pd.DataFrame) -> pd.DataFrame:
    """Copia del DataFrame con todos sus valores en tipos nativos de Python,
    lista para mandarse a Google Sheets."""
    d = df.copy()
    for c in d.columns:
        d[c] = d[c].map(_a_valor_nativo)
    return d


def _df_a_valores_sheet(df: pd.DataFrame):
    """Convierte un DataFrame a lista de listas apta para worksheet.update()."""
    df2 = df.copy()
    for col in df2.columns:
        df2[col] = df2[col].apply(
            lambda v: '' if pd.isna(v)
            else int(v) if isinstance(v, np.integer)
            else float(v) if isinstance(v, np.floating)
            else v
        )
    return [df2.columns.tolist()] + df2.values.tolist()
