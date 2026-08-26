"""
NowCast y promedios móviles.

El NowCast es el estimador ponderado que la EPA usa para partículas cuando
todavía no cierra el día: pesa más las horas recientes cuando la
concentración cambia rápido. La implementación es sensible al redondeo, por
eso todo pasa por ``round_half_up`` y no por ``round()`` de Python, que usa
redondeo bancario (``round(2.5) == 2``) y produciría valores distintos.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence

import numpy as np
import pandas as pd

# Horas hacia atrás que mira el NowCast (12 horas incluyendo la actual).
VENTANA_NOWCAST = 12

# Factores de conversión de la EPA por tipo de partícula.
FACTOR_PM10 = 0.714
FACTOR_PM25 = 0.694


def round_half_up(value, ndigits):
    """Redondeo comercial (0.5 siempre sube), no el bancario de Python."""
    if value is None or pd.isna(value):
        return np.nan
    q = Decimal(str(value)).quantize(Decimal("1." + "0" * ndigits), rounding=ROUND_HALF_UP)
    return float(q)


def rolling_8h(series: pd.Series) -> pd.Series:
    """Promedio móvil de 8 horas; requiere al menos 6 horas válidas."""
    return series.rolling(8, min_periods=6).mean()


def rolling_24h(series: pd.Series) -> pd.Series:
    """Promedio móvil de 24 horas; requiere al menos 18 horas válidas."""
    return series.rolling(24, min_periods=18).mean()


def NowCast(valores: Sequence[Optional[float]], PM: int) -> Optional[int]:
    """
    Calcula el NowCast de una ventana de hasta 12 horas.

    ``valores`` va de la hora más antigua a la más reciente; None = dato
    inválido. ``PM`` es 0 para PM10 y cualquier otro valor para PM2.5.

    Devuelve None cuando no hay suficientes datos: la norma exige al menos 2
    de las 3 horas más recientes.
    """
    ultimas_3 = valores[-3:] if len(valores) >= 3 else valores
    if sum(1 for x in ultimas_3 if x is not None) < 2:
        return None

    valores_inv = valores[::-1]
    vals_indexados = []
    hora = 0
    for v in valores_inv:
        if v is not None:
            vals_indexados.append((float(v), hora))
        hora += 1

    if len(vals_indexados) < 2:
        return None

    solo_valores = [v for v, _ in vals_indexados]
    if all(v == 0 for v in solo_valores):
        return 0

    v_max = max(solo_valores)
    v_min = min(solo_valores)
    if v_max == 0:
        return 0

    # La tasa de cambio define qué tanto pesan las horas viejas. El piso de
    # 0.5 evita que un pico reciente borre por completo el resto del día.
    tasa   = round_half_up(1 - (v_max - v_min) / v_max, 2)
    factor = tasa if tasa >= 0.5 else 0.5

    num = den = 0.0
    for v, i in vals_indexados:
        peso = factor ** i
        num += v * peso
        den += peso

    if den == 0:
        return None

    pp = round_half_up(num / den, 0)
    pp = round_half_up(pp * (FACTOR_PM10 if PM == 0 else FACTOR_PM25), 0)
    return int(pp)


def serie_nowcast_por_estacion(df: pd.DataFrame, pol_col: str, pm_flag: int) -> pd.Series:
    """Aplica NowCast hora por hora sobre la serie de una estación."""
    s   = pd.to_numeric(df[pol_col], errors="coerce")
    out = []
    for idx in range(len(s)):
        ventana = s.iloc[max(0, idx - (VENTANA_NOWCAST - 1)): idx + 1]
        vals    = [None if pd.isna(v) else float(v) for v in ventana.tolist()]
        out.append(NowCast(vals, pm_flag))
    return pd.Series(out, index=df.index, name=f"{pol_col}_NOWCAST")
