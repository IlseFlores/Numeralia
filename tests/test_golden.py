"""
Comparación contra una salida capturada ANTES del refactor.

El pickle ``tests/datos/golden_prerefactor.pkl`` se generó con el
``pipeline_completo.py`` original de 3,849 líneas, antes de extraer el
dominio. Estos tests aseguran que ninguna migración posterior cambie los
números del reporte.

A diferencia de ``test_equivalencia.py``, este archivo NO depende de que
``pipeline_completo.py`` siga existiendo: compara contra el paquete. Es el
que sobrevive cuando la migración termine.
"""

import pickle
from pathlib import Path

import pandas as pd
import pytest

from numeralia.dominio import ias, nom172

GOLDEN = Path(__file__).parent / "datos" / "golden_prerefactor.pkl"


@pytest.fixture(scope="module")
def golden():
    if not GOLDEN.exists():
        pytest.skip(f"No existe {GOLDEN.name}; regenéralo antes de migrar más código.")
    with open(GOLDEN, "rb") as f:
        return pickle.load(f)


@pytest.fixture(scope="module")
def tabla():
    from test_equivalencia import _tabla_sintetica
    return _tabla_sintetica(200)


def test_cumplimiento_nom_sin_cambios(golden, tabla):
    pd.testing.assert_frame_equal(nom172.compute_nom_daily_flags(tabla), golden["nom"])


def test_ias_diario_sin_cambios(golden, tabla):
    pd.testing.assert_frame_equal(ias.compute_ias_daily(tabla), golden["ias"])


def test_cadena_completa_sin_cambios(golden, tabla):
    pd.testing.assert_frame_equal(
        ias.compute_ias_daily(nom172.compute_nom_daily_flags(tabla)),
        golden["both"],
    )


@pytest.mark.parametrize("nombre", [
    "RANGOS", "NOM_LIMITS", "CAT_PUNTAJE", "NOM_PRESETS",
])
def test_constantes_de_la_norma_sin_cambios(golden, nombre):
    assert getattr(nom172, nombre) == golden["constantes"][nombre]


@pytest.mark.parametrize("nombre", ["IAS_SOURCE", "ORDEN_DOM"])
def test_constantes_del_ias_sin_cambios(golden, nombre):
    assert getattr(ias, nombre) == golden["constantes"][nombre]


@pytest.mark.parametrize("nombre", ["COLOR_2025", "COLOR_2026", "CARD_STYLE", "LOGO_SIMAJ"])
def test_tema_sin_cambios(golden, nombre):
    from numeralia.reporte import tema
    assert getattr(tema, nombre) == golden["constantes"][nombre]
