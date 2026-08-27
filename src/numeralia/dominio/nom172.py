"""
NOM-172-SEMARNAT-2023: rangos del Índice Aire y Salud y límites de cumplimiento.

Los rangos son intervalos abiertos por la izquierda y cerrados por la derecha
— (lo, hi] — por eso ``clasifica`` compara con ``>`` y ``<=``. Un valor
exactamente igual al corte superior pertenece a la categoría BAJA, no a la
siguiente: 45 µg/m³ de PM10 es 'Buena', 45.1 ya es 'Aceptable'.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .nowcast import round_half_up

CAT_ORDER   = ["Buena", "Aceptable", "Mala", "Muy mala", "Extremadamente mala"]
CAT_PUNTAJE = {c: i + 1 for i, c in enumerate(CAT_ORDER)}

# Categorías agrupadas, como las reporta la numeralia.
CATS_BUENA = {"Buena", "Aceptable"}
CATS_MALA  = {"Mala", "Muy mala", "Extremadamente mala"}

# Cortes del IAS por contaminante: (límite_inferior, límite_superior, categoría).
# None en un extremo significa "sin límite por ese lado".
RANGOS = {
    "PM10":  [(None, 45,  "Buena"),  (45,  50,  "Aceptable"),
              (50,   132, "Mala"),   (132, 213, "Muy mala"),
              (213,  None,"Extremadamente mala")],
    "PM2.5": [(None, 15,  "Buena"),  (15,  25,  "Aceptable"),
              (25,   79,  "Mala"),   (79,  130, "Muy mala"),
              (130,  None,"Extremadamente mala")],
    "O3":    [(None, 0.058,"Buena"), (0.058,0.090,"Aceptable"),
              (0.090,0.135,"Mala"), (0.135,0.175,"Muy mala"),
              (0.175,None, "Extremadamente mala")],
    "NO2":   [(None, 0.053,"Buena"), (0.053,0.106,"Aceptable"),
              (0.106,0.160,"Mala"), (0.160,0.213,"Muy mala"),
              (0.213,None, "Extremadamente mala")],
    "SO2":   [(None, 0.035,"Buena"), (0.035,0.075,"Aceptable"),
              (0.075,0.185,"Mala"), (0.185,0.304,"Muy mala"),
              (0.304,None, "Extremadamente mala")],
    "CO":    [(None, 5.00,"Buena"),  (5.00,  9.00,"Aceptable"),
              (9.00, 12.00,"Mala"), (12.00,16.00,"Muy mala"),
              (16.00,None, "Extremadamente mala")],
}

# Decimales con los que la norma expresa cada contaminante. Redondear antes de
# comparar contra el corte es parte del criterio, no una cuestión de formato.
DECIMALES_NOM = {"O3": 3, "NO2": 3, "SO2": 3, "CO": 2, "PM10": 0, "PM2.5": 0}


def clasifica(valor, pol) -> Tuple[Optional[str], Optional[int]]:
    """
    Devuelve (categoría, puntaje) del IAS para un valor de un contaminante.
    (None, None) si el valor falta: sin dato NO es 'Buena'.
    """
    if valor is None or pd.isna(valor):
        return None, None
    for lo, hi, cat in RANGOS[pol]:
        if ((lo is None) or (valor > lo)) and ((hi is None) or (valor <= hi)):
            return cat, CAT_PUNTAJE[cat]
    return None, None


def frac_rango(valor, pol, cat) -> float:
    """
    Qué tan avanzado va el valor dentro de su categoría, de 0 a 1.

    Sirve para desempatar cuál contaminante domina el día cuando dos caen en
    la misma categoría: gana el que esté más arriba dentro de ella.
    """
    if valor is None or pd.isna(valor) or cat is None:
        return 0.0
    for lo, hi, c in RANGOS.get(pol, []):
        if c == cat:
            lo_v = float(lo) if lo is not None else -np.inf
            hi_v = float(hi) if hi is not None else np.inf
            if np.isfinite(lo_v) and np.isfinite(hi_v) and (hi_v - lo_v) > 0:
                return (valor - lo_v) / (hi_v - lo_v)
            return 1.0 if np.isinf(hi_v) else 0.0
    return 0.0


def redondear_por_nom(value, pol, kind=None):
    """Redondea al número de decimales con que la norma expresa el contaminante."""
    if pd.isna(value):
        return np.nan
    if pol in DECIMALES_NOM:
        return round_half_up(value, DECIMALES_NOM[pol])
    return value


# ── Límites de cumplimiento, por año de entrada en vigor ────────────────────
# La NOM-172 endurece sus límites por etapas. El preset elegido decide contra
# qué valores se evalúa el cumplimiento.
#
# OJO: solo se evalúa el cumplimiento DIARIO (NOM_LIMITS). Los valores de
# LIMITES_ANUALES están capturados de la norma pero ningún cálculo los usa
# todavía: falta implementar la evaluación anual, que además exige el
# criterio de suficiencia de suf_min_yearly (274/275 días válidos).
NOM_PRESETS: Dict[int, Dict[str, Dict]] = {
    2024: {
        "NOM_LIMITS": {
            "O3":   {"1H": 0.090, "8H": 0.060},
            "NO2":  {"1H": 0.106},
            "SO2":  {"1H": 0.075},
            "CO":   {"1H": 26.0,  "8H": 9.0},
            "PM10": {"24H": 60},
            "PM2.5":{"24H": 33},
        },
        "LIMITES_ANUALES": {
            "O3":    {"tipo": "max_1h",     "lim": 0.090},
            "NO2":   {"tipo": "prom_24h",   "lim": 0.021},
            "SO2":   {"tipo": "max_prom24", "lim": 0.040},
            "CO":    {"tipo": "max_1h",     "lim": 26.0},
            "PM10":  {"tipo": "prom_24h",   "lim": 28},
            "PM2.5": {"tipo": "prom_24h",   "lim": 10},
        },
    },
    2026: {
        "NOM_LIMITS": {
            "O3":   {"1H": 0.090, "8H": 0.051},
            "NO2":  {"1H": 0.106},
            "SO2":  {"1H": 0.075},
            "CO":   {"1H": 26.0,  "8H": 9.0},
            "PM10": {"24H": 50},
            "PM2.5":{"24H": 25},
        },
        "LIMITES_ANUALES": {
            "O3":    {"tipo": "max_1h",     "lim": 0.090},
            "NO2":   {"tipo": "prom_24h",   "lim": 0.021},
            "SO2":   {"tipo": "max_prom24", "lim": 0.040},
            "CO":    {"tipo": "max_1h",     "lim": 26.0},
            "PM10":  {"tipo": "prom_24h",   "lim": 20},
            "PM2.5": {"tipo": "prom_24h",   "lim": 10},
        },
    },
}


def select_nom_preset(year: int = 2026) -> Tuple[Dict, Dict]:
    """Devuelve (límites diarios, límites anuales) del criterio de ese año."""
    if year not in NOM_PRESETS:
        disponibles = ", ".join(str(a) for a in sorted(NOM_PRESETS))
        raise ValueError(f"Año no soportado: {year}. Disponibles: {disponibles}.")
    preset = NOM_PRESETS[year]
    return preset["NOM_LIMITS"], preset["LIMITES_ANUALES"]


# Criterio activo por omisión. Se puede cambiar con NUMERALIA_CRITERIO_NOM.
NOM_LIMITS, LIMITES_ANUALES = select_nom_preset(2026)


def compute_nom_daily_flags(dfd: pd.DataFrame, nom_limits: Optional[Dict] = None) -> pd.DataFrame:
    """
    Marca Si/No de cumplimiento diario por contaminante, y el global.

    ``None`` significa "no evaluable por falta de datos" y es distinto de
    "No cumple": un día sin suficientes horas no reprueba, se excluye.
    """
    limites = nom_limits if nom_limits is not None else NOM_LIMITS
    dfd = dfd.copy()

    def _cn(cond, valido):
        return None if not bool(valido) else ("Si" if bool(cond) else "No")

    if {"O3_MAX_1H","O3_MAX_8H"}.issubset(dfd.columns):
        dfd["NOM_O3_CUMPLE"] = dfd.apply(lambda r: _cn(
            (not pd.isna(r["O3_MAX_1H"]) and r["O3_MAX_1H"] <= limites["O3"]["1H"]) and
            (not pd.isna(r["O3_MAX_8H"]) and r["O3_MAX_8H"] <= limites["O3"]["8H"]),
            r.get("O3_SUF_DIARIA", False)), axis=1)
    if "NO2_MAX_1H" in dfd.columns:
        dfd["NOM_NO2_CUMPLE"] = dfd.apply(lambda r: _cn(
            not pd.isna(r["NO2_MAX_1H"]) and r["NO2_MAX_1H"] <= limites["NO2"]["1H"],
            r.get("NO2_SUF_DIARIA", False)), axis=1)
    if "SO2_MAX_1H" in dfd.columns:
        dfd["NOM_SO2_CUMPLE"] = dfd.apply(lambda r: _cn(
            not pd.isna(r["SO2_MAX_1H"]) and r["SO2_MAX_1H"] <= limites["SO2"]["1H"],
            r.get("SO2_SUF_DIARIA", False)), axis=1)
    if {"CO_MAX_1H","CO_MAX_8H"}.issubset(dfd.columns):
        dfd["NOM_CO_CUMPLE"] = dfd.apply(lambda r: _cn(
            (not pd.isna(r["CO_MAX_1H"]) and r["CO_MAX_1H"] <= limites["CO"]["1H"]) and
            (not pd.isna(r["CO_MAX_8H"]) and r["CO_MAX_8H"] <= limites["CO"]["8H"]),
            r.get("CO_SUF_DIARIA", False)), axis=1)
    if "PM10_AVG_24H" in dfd.columns:
        dfd["NOM_PM10_CUMPLE"] = dfd.apply(lambda r: _cn(
            not pd.isna(r["PM10_AVG_24H"]) and r["PM10_AVG_24H"] <= limites["PM10"]["24H"],
            r.get("PM10_SUF_DIARIA", False)), axis=1)
    if "PM2.5_AVG_24H" in dfd.columns:
        dfd["NOM_PM2.5_CUMPLE"] = dfd.apply(lambda r: _cn(
            not pd.isna(r["PM2.5_AVG_24H"]) and r["PM2.5_AVG_24H"] <= limites["PM2.5"]["24H"],
            r.get("PM2.5_SUF_DIARIA", False)), axis=1)
    if "PM10_NOWCAST_MAX" in dfd.columns:
        dfd["NOM_PM10_NOWCAST_CUMPLE"] = dfd.apply(lambda r: _cn(
            not pd.isna(r["PM10_NOWCAST_MAX"]) and r["PM10_NOWCAST_MAX"] <= limites["PM10"]["24H"],
            r.get("PM10_SUF_DIARIA", False)), axis=1)
    if "PM2.5_NOWCAST_MAX" in dfd.columns:
        dfd["NOM_PM2.5_NOWCAST_CUMPLE"] = dfd.apply(lambda r: _cn(
            not pd.isna(r["PM2.5_NOWCAST_MAX"]) and r["PM2.5_NOWCAST_MAX"] <= limites["PM2.5"]["24H"],
            r.get("PM2.5_SUF_DIARIA", False)), axis=1)

    nom_cols = ["NOM_O3_CUMPLE","NOM_NO2_CUMPLE","NOM_SO2_CUMPLE",
                "NOM_CO_CUMPLE","NOM_PM10_CUMPLE","NOM_PM2.5_CUMPLE"]
    dfd["NOM_GLOBAL_CUMPLE"] = dfd.apply(
        lambda r: (None if not any(r.get(c) in ("Si","No") for c in nom_cols)
                   else ("Si" if all(r.get(c) == "Si" for c in nom_cols if r.get(c) in ("Si","No"))
                         else "No")), axis=1)
    return dfd
