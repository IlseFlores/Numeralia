"""Fixtures compartidas por los tests del dominio."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# El script original vive en la raíz del repo, fuera de src/. Los tests de
# equivalencia lo importan desde ahí para comparar contra él.
RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


@pytest.fixture
def tabla_diaria() -> pd.DataFrame:
    """
    Tabla diaria mínima con los casos que importan:
      · fila 0: todo dentro de norma y con datos suficientes
      · fila 1: los mismos valores pero SIN datos suficientes
      · fila 2: O3 fuera del límite de 8 horas
      · fila 3: sin ningún dato válido
    """
    return pd.DataFrame([
        {
            "STATION": "COU", "FECHA": pd.Timestamp("2026-01-01"),
            "O3_MAX_1H": 0.050, "O3_MAX_8H": 0.040, "O3_SUF_DIARIA": True,
            "NO2_MAX_1H": 0.030, "NO2_SUF_DIARIA": True,
            "SO2_MAX_1H": 0.010, "SO2_SUF_DIARIA": True,
            "CO_MAX_1H": 2.00, "CO_MAX_8H": 1.00, "CO_SUF_DIARIA": True,
            "PM10_AVG_24H": 30.0, "PM10_SUF_DIARIA": True,
            "PM2.5_AVG_24H": 10.0, "PM2.5_SUF_DIARIA": True,
        },
        {
            "STATION": "COU", "FECHA": pd.Timestamp("2026-01-02"),
            "O3_MAX_1H": 0.050, "O3_MAX_8H": 0.040, "O3_SUF_DIARIA": False,
            "NO2_MAX_1H": 0.030, "NO2_SUF_DIARIA": False,
            "SO2_MAX_1H": 0.010, "SO2_SUF_DIARIA": False,
            "CO_MAX_1H": 2.00, "CO_MAX_8H": 1.00, "CO_SUF_DIARIA": False,
            "PM10_AVG_24H": 30.0, "PM10_SUF_DIARIA": False,
            "PM2.5_AVG_24H": 10.0, "PM2.5_SUF_DIARIA": False,
        },
        {
            "STATION": "AGU", "FECHA": pd.Timestamp("2026-01-01"),
            "O3_MAX_1H": 0.080, "O3_MAX_8H": 0.060, "O3_SUF_DIARIA": True,
            "NO2_MAX_1H": 0.030, "NO2_SUF_DIARIA": True,
            "SO2_MAX_1H": 0.010, "SO2_SUF_DIARIA": True,
            "CO_MAX_1H": 2.00, "CO_MAX_8H": 1.00, "CO_SUF_DIARIA": True,
            "PM10_AVG_24H": 200.0, "PM10_SUF_DIARIA": True,
            "PM2.5_AVG_24H": 10.0, "PM2.5_SUF_DIARIA": True,
        },
        {
            "STATION": "PIN", "FECHA": pd.Timestamp("2026-01-01"),
            "O3_MAX_1H": np.nan, "O3_MAX_8H": np.nan, "O3_SUF_DIARIA": False,
            "NO2_MAX_1H": np.nan, "NO2_SUF_DIARIA": False,
            "SO2_MAX_1H": np.nan, "SO2_SUF_DIARIA": False,
            "CO_MAX_1H": np.nan, "CO_MAX_8H": np.nan, "CO_SUF_DIARIA": False,
            "PM10_AVG_24H": np.nan, "PM10_SUF_DIARIA": False,
            "PM2.5_AVG_24H": np.nan, "PM2.5_SUF_DIARIA": False,
        },
    ])


@pytest.fixture
def series_nowcast():
    """Series horarias representativas para probar NowCast."""
    return {
        "constante":     [100.0] * 12,
        "creciente":     [float(v) for v in range(10, 130, 10)],
        "pico_reciente": [5.0] * 9 + [200.0, 210.0, 220.0],
        "con_huecos":    [10.0, None, 30.0, None, 50.0, 60.0,
                          None, 80.0, 90.0, None, 110.0, 120.0],
        "ceros":         [0.0] * 12,
    }
