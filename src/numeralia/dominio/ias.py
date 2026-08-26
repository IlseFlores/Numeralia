"""
Índice Aire y Salud diario y contaminante dominante.

El IAS de un día es el del contaminante que salió peor. Cuando dos empatan en
categoría, gana el que esté más avanzado dentro de su rango; si aun así
empatan, decide el orden de ORDEN_DOM, que va del más dañino a la salud al
menos dañino.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .nom172 import RANGOS, clasifica, frac_rango
from .nowcast import round_half_up

# De qué columna sale el valor que se clasifica, por contaminante.
IAS_SOURCE = {
    "PM10":"PM10_AVG_24H", "PM2.5":"PM2.5_AVG_24H",
    "CO":"CO_MAX_8H",      "O3":"O3_MAX_1H",
    "NO2":"NO2_MAX_1H",    "SO2":"SO2_MAX_1H",
    "PM10_NOWCAST":"PM10_NOWCAST_MAX",
    "PM2.5_NOWCAST":"PM2.5_NOWCAST_MAX",
}

# Orden de desempate del contaminante dominante (de mayor a menor prioridad).
ORDEN_DOM = ["PM2.5","O3","PM10","NO2","SO2","CO"]

# Contaminantes que entran al cálculo del IAS global (los NOWCAST son
# informativos y no compiten por el dominante).
_FUENTES_GLOBALES = {
    "PM10":"PM10_AVG_24H", "PM2.5":"PM2.5_AVG_24H",
    "CO":"CO_MAX_8H",      "O3":"O3_MAX_1H",
    "NO2":"NO2_MAX_1H",    "SO2":"SO2_MAX_1H",
}

# Decimales de redondeo previo a clasificar. O3, NO2 y SO2 se clasifican con
# el valor tal cual, sin redondear.
_DECIMALES_IAS = {"PM10": 0, "PM2.5": 0, "PM10_NOWCAST": 0, "PM2.5_NOWCAST": 0, "CO": 2}


def _redondear_para_ias(serie: pd.Series, pol: str) -> pd.Series:
    if pol not in _DECIMALES_IAS:
        return serie
    dec = _DECIMALES_IAS[pol]
    return serie.apply(lambda v: np.nan if pd.isna(v) else float(round_half_up(v, dec)))


def compute_ias_daily(dfd: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega al DataFrame diario las columnas IAS por contaminante y el global:
    ``IAS_<pol>_CAT_DIA``, ``IAS_<pol>_SCORE_DIA``, ``IAS_<pol>_VALOR_DIA`` y
    ``IAS_GLOBAL_POL_DIA`` / ``_CAT_DIA`` / ``_SCORE_DIA``.
    """
    dfd = dfd.copy()

    for pol, vcol in IAS_SOURCE.items():
        if vcol not in dfd.columns:
            continue
        vals = _redondear_para_ias(dfd[vcol], pol)
        # Los NOWCAST se clasifican con los cortes de su contaminante base.
        pol_cls = pol if pol in RANGOS else pol.replace("_NOWCAST", "")
        dfd[[f"IAS_{pol}_CAT_DIA", f"IAS_{pol}_SCORE_DIA"]] = vals.apply(
            lambda v: pd.Series(clasifica(v, pol_cls)) if not pd.isna(v) else pd.Series([None, None])
        )

    for pol, vcol in _FUENTES_GLOBALES.items():
        if vcol in dfd.columns and f"IAS_{pol}_VALOR_DIA" not in dfd.columns:
            dfd[f"IAS_{pol}_VALOR_DIA"] = _redondear_para_ias(dfd[vcol], pol)

    def _dom(row):
        cand = []
        for pol in ORDEN_DOM:
            sc  = row.get(f"IAS_{pol}_SCORE_DIA", np.nan)
            val = row.get(f"IAS_{pol}_VALOR_DIA",  np.nan)
            cat = row.get(f"IAS_{pol}_CAT_DIA",    None)
            if pd.isna(sc):
                continue
            cand.append((pol, float(sc), frac_rango(val, pol, cat)))
        if not cand:
            return pd.Series([None, None, None],
                             index=["IAS_GLOBAL_POL_DIA","IAS_GLOBAL_CAT_DIA","IAS_GLOBAL_SCORE_DIA"])
        # Ordena por categoría, luego por avance dentro del rango, y al final
        # por prioridad del contaminante (negativo porque el sort es inverso).
        cand.sort(key=lambda t: (t[1], t[2], -ORDEN_DOM.index(t[0])), reverse=True)
        pol, sc, _ = cand[0]
        return pd.Series([pol, row.get(f"IAS_{pol}_CAT_DIA"), sc],
                         index=["IAS_GLOBAL_POL_DIA","IAS_GLOBAL_CAT_DIA","IAS_GLOBAL_SCORE_DIA"])

    dfd[["IAS_GLOBAL_POL_DIA","IAS_GLOBAL_CAT_DIA","IAS_GLOBAL_SCORE_DIA"]] = dfd.apply(_dom, axis=1)
    return dfd
