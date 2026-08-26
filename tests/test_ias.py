"""Tests del Índice Aire y Salud diario y del contaminante dominante."""

import numpy as np
import pandas as pd
import pytest

from numeralia.dominio.ias import ORDEN_DOM, compute_ias_daily


def _fila(**valores) -> pd.DataFrame:
    """Arma una tabla diaria de una sola fila con los valores dados."""
    base = {
        "STATION": "COU", "FECHA": pd.Timestamp("2026-01-01"),
        "O3_MAX_1H": np.nan, "NO2_MAX_1H": np.nan, "SO2_MAX_1H": np.nan,
        "CO_MAX_8H": np.nan, "PM10_AVG_24H": np.nan, "PM2.5_AVG_24H": np.nan,
    }
    base.update(valores)
    return pd.DataFrame([base])


class TestColumnasGeneradas:
    def test_agrega_categoria_y_puntaje_por_contaminante(self):
        out = compute_ias_daily(_fila(PM10_AVG_24H=30.0))
        assert out.loc[0, "IAS_PM10_CAT_DIA"] == "Buena"
        assert out.loc[0, "IAS_PM10_SCORE_DIA"] == 1

    def test_agrega_el_global(self):
        out = compute_ias_daily(_fila(PM10_AVG_24H=200.0))
        for col in ("IAS_GLOBAL_POL_DIA", "IAS_GLOBAL_CAT_DIA", "IAS_GLOBAL_SCORE_DIA"):
            assert col in out.columns

    def test_no_modifica_el_original(self):
        df = _fila(PM10_AVG_24H=30.0)
        columnas_antes = list(df.columns)
        compute_ias_daily(df)
        assert list(df.columns) == columnas_antes


class TestContaminanteDominante:
    def test_gana_la_peor_categoria(self):
        # PM10 'Muy mala' (200) contra O3 'Buena' (0.05).
        out = compute_ias_daily(_fila(PM10_AVG_24H=200.0, O3_MAX_1H=0.050))
        assert out.loc[0, "IAS_GLOBAL_POL_DIA"] == "PM10"
        assert out.loc[0, "IAS_GLOBAL_CAT_DIA"] == "Muy mala"
        assert out.loc[0, "IAS_GLOBAL_SCORE_DIA"] == 4

    def test_empate_de_categoria_lo_rompe_el_avance_en_el_rango(self):
        # Ambos 'Aceptable': PM10 en 48 va al 60% de su rango (45-50);
        # PM2.5 en 16 va al 10% del suyo (15-25). Gana PM10.
        out = compute_ias_daily(_fila(PM10_AVG_24H=48.0, **{"PM2.5_AVG_24H": 16.0}))
        assert out.loc[0, "IAS_PM10_CAT_DIA"] == "Aceptable"
        assert out.loc[0, "IAS_PM2.5_CAT_DIA"] == "Aceptable"
        assert out.loc[0, "IAS_GLOBAL_POL_DIA"] == "PM10"

    def test_empate_total_lo_rompe_el_orden_de_dano(self):
        # PM10 en 48 y PM2.5 en 21: misma categoría y mismo 60% de avance.
        # Desempata ORDEN_DOM, donde PM2.5 va primero por ser más dañino.
        out = compute_ias_daily(_fila(PM10_AVG_24H=48.0, **{"PM2.5_AVG_24H": 21.0}))
        assert out.loc[0, "IAS_GLOBAL_POL_DIA"] == "PM2.5"

    def test_orden_de_dano_empieza_por_particulas_finas(self):
        assert ORDEN_DOM[0] == "PM2.5"

    def test_sin_ningun_dato_no_hay_dominante(self):
        out = compute_ias_daily(_fila())
        assert out.loc[0, "IAS_GLOBAL_POL_DIA"] is None
        assert out.loc[0, "IAS_GLOBAL_CAT_DIA"] is None

    def test_ignora_contaminantes_sin_dato(self):
        # Solo O3 tiene lectura: es el dominante aunque sea 'Buena'.
        out = compute_ias_daily(_fila(O3_MAX_1H=0.050))
        assert out.loc[0, "IAS_GLOBAL_POL_DIA"] == "O3"
        assert out.loc[0, "IAS_GLOBAL_CAT_DIA"] == "Buena"


class TestRedondeoPrevio:
    def test_pm10_se_clasifica_redondeado(self):
        # 44.5 redondea a 45, que sigue siendo 'Buena' (el corte es cerrado).
        assert compute_ias_daily(_fila(PM10_AVG_24H=44.5)).loc[0, "IAS_PM10_CAT_DIA"] == "Buena"
        # 45.5 redondea a 46: ya es 'Aceptable'.
        assert compute_ias_daily(_fila(PM10_AVG_24H=45.5)).loc[0, "IAS_PM10_CAT_DIA"] == "Aceptable"

    def test_ozono_se_clasifica_sin_redondear(self):
        # 0.0581 no se redondea a 0.058: cae en 'Aceptable'.
        assert compute_ias_daily(_fila(O3_MAX_1H=0.0581)).loc[0, "IAS_O3_CAT_DIA"] == "Aceptable"

    def test_valor_dia_queda_redondeado(self):
        out = compute_ias_daily(_fila(PM10_AVG_24H=45.5))
        assert out.loc[0, "IAS_PM10_VALOR_DIA"] == 46.0


class TestNowcastInformativo:
    def test_se_clasifica_con_los_cortes_del_contaminante_base(self):
        df = _fila(PM10_AVG_24H=30.0)
        df["PM10_NOWCAST_MAX"] = 200.0
        out = compute_ias_daily(df)
        assert out.loc[0, "IAS_PM10_NOWCAST_CAT_DIA"] == "Muy mala"

    def test_no_compite_por_el_dominante(self):
        # El NowCast es informativo: aunque sea peor, el global sigue saliendo
        # del promedio de 24 h.
        df = _fila(PM10_AVG_24H=30.0)
        df["PM10_NOWCAST_MAX"] = 200.0
        out = compute_ias_daily(df)
        assert out.loc[0, "IAS_GLOBAL_POL_DIA"] == "PM10"
        assert out.loc[0, "IAS_GLOBAL_CAT_DIA"] == "Buena"
