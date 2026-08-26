"""Tests del NowCast y del redondeo comercial."""

import numpy as np
import pandas as pd
import pytest

from numeralia.dominio.nowcast import (
    FACTOR_PM10,
    FACTOR_PM25,
    NowCast,
    rolling_8h,
    rolling_24h,
    round_half_up,
    serie_nowcast_por_estacion,
)

PM10, PM25 = 0, 1


class TestRoundHalfUp:
    """El redondeo de la norma sube el 0.5; el de Python lo baja."""

    @pytest.mark.parametrize("valor, decimales, esperado", [
        (2.5, 0, 3.0),      # round() de Python daría 2
        (3.5, 0, 4.0),      # round() de Python daría 4 — aquí coincide
        (0.5, 0, 1.0),      # round() de Python daría 0
        (1.5, 0, 2.0),
        (0.125, 2, 0.13),
        (0.0585, 3, 0.059),
        (-2.5, 0, -3.0),    # simétrico: se aleja del cero
        (45.0, 0, 45.0),
    ])
    def test_medio_sube(self, valor, decimales, esperado):
        assert round_half_up(valor, decimales) == esperado

    def test_difiere_del_redondeo_bancario(self):
        # Esta es la razón de que la función exista.
        assert round(2.5) == 2
        assert round_half_up(2.5, 0) == 3.0

    @pytest.mark.parametrize("vacio", [None, np.nan, pd.NA])
    def test_sin_dato_devuelve_nan(self, vacio):
        assert np.isnan(round_half_up(vacio, 2))


class TestRollings:
    def test_8h_exige_seis_horas(self):
        s = pd.Series([1.0] * 5 + [np.nan] * 10)
        # Con solo 5 datos en la ventana no hay promedio.
        assert rolling_8h(s).iloc[4] is np.nan or pd.isna(rolling_8h(s).iloc[4])

    def test_8h_con_seis_horas_promedia(self):
        s = pd.Series([2.0] * 8)
        assert rolling_8h(s).iloc[5] == 2.0

    def test_24h_exige_dieciocho_horas(self):
        s = pd.Series([1.0] * 24)
        assert pd.isna(rolling_24h(s).iloc[16])   # 17 horas: insuficiente
        assert rolling_24h(s).iloc[17] == 1.0     # 18 horas: suficiente


class TestNowCast:
    def test_pocos_datos_recientes_devuelve_none(self, series_nowcast):
        # La norma exige 2 de las 3 horas más recientes.
        assert NowCast([10.0] * 9 + [None, None, None], PM10) is None
        assert NowCast([10.0] * 9 + [None, None, 5.0], PM10) is None

    def test_dos_de_tres_horas_recientes_basta(self):
        assert NowCast([10.0] * 9 + [None, 5.0, 7.0], PM10) is not None

    def test_todo_cero_devuelve_cero(self, series_nowcast):
        assert NowCast(series_nowcast["ceros"], PM10) == 0
        assert NowCast(series_nowcast["ceros"], PM25) == 0

    def test_serie_constante_aplica_solo_el_factor(self, series_nowcast):
        # Sin variación, el promedio ponderado es el propio valor: 100.
        # Lo único que queda es el factor de conversión.
        assert NowCast(series_nowcast["constante"], PM10) == int(
            round_half_up(100 * FACTOR_PM10, 0))
        assert NowCast(series_nowcast["constante"], PM25) == int(
            round_half_up(100 * FACTOR_PM25, 0))

    def test_pm10_y_pm25_difieren(self, series_nowcast):
        # 100 * 0.714 = 71.4 -> 71 ; 100 * 0.694 = 69.4 -> 69
        assert NowCast(series_nowcast["constante"], PM10) == 71
        assert NowCast(series_nowcast["constante"], PM25) == 69

    def test_pico_reciente_pesa_mas_que_el_promedio(self, series_nowcast):
        valores = series_nowcast["pico_reciente"]
        promedio_simple = sum(valores) / len(valores)
        # El NowCast existe justamente para no diluir un pico reciente en el
        # promedio del día.
        assert NowCast(valores, PM10) > promedio_simple * FACTOR_PM10

    def test_tolera_huecos(self, series_nowcast):
        assert NowCast(series_nowcast["con_huecos"], PM10) is not None

    def test_devuelve_entero(self, series_nowcast):
        for nombre, valores in series_nowcast.items():
            resultado = NowCast(valores, PM10)
            if resultado is not None:
                assert isinstance(resultado, int), nombre

    def test_nunca_supera_el_maximo_de_la_ventana(self, series_nowcast):
        # El factor de conversión es < 1 y el ponderado no puede exceder el
        # máximo, así que el resultado siempre queda por debajo.
        for nombre, valores in series_nowcast.items():
            resultado = NowCast(valores, PM10)
            validos = [v for v in valores if v is not None]
            if resultado is not None and validos:
                assert resultado <= max(validos), nombre


class TestSerieNowCastPorEstacion:
    def test_devuelve_una_fila_por_hora(self):
        df = pd.DataFrame({"PM10": [10.0] * 20})
        out = serie_nowcast_por_estacion(df, "PM10", PM10)
        assert len(out) == len(df)
        assert out.name == "PM10_NOWCAST"

    def test_primeras_horas_sin_dato_suficiente(self):
        df = pd.DataFrame({"PM10": [10.0] * 20})
        out = serie_nowcast_por_estacion(df, "PM10", PM10)
        # La primera hora sola no alcanza el mínimo de 2 valores. NowCast
        # devuelve None y pandas lo guarda como NaN en la serie.
        assert pd.isna(out.iloc[0])

    def test_conserva_el_indice(self):
        df = pd.DataFrame({"PM10": [10.0] * 5}, index=[10, 11, 12, 13, 14])
        out = serie_nowcast_por_estacion(df, "PM10", PM10)
        assert list(out.index) == [10, 11, 12, 13, 14]
