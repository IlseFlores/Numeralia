"""Tests de los cortes de la NOM-172 y del cumplimiento diario."""

import numpy as np
import pandas as pd
import pytest

from numeralia.dominio.nom172 import (
    CAT_ORDER,
    CAT_PUNTAJE,
    NOM_PRESETS,
    RANGOS,
    clasifica,
    compute_nom_daily_flags,
    frac_rango,
    redondear_por_nom,
    select_nom_preset,
)


class TestRangos:
    def test_todos_los_contaminantes_cubren_las_cinco_categorias(self):
        for pol, tramos in RANGOS.items():
            cats = [c for _, _, c in tramos]
            assert cats == CAT_ORDER, pol

    def test_los_tramos_son_contiguos_y_sin_huecos(self):
        # El límite superior de un tramo debe ser el inferior del siguiente:
        # si hubiera un hueco, un valor quedaría sin categoría.
        for pol, tramos in RANGOS.items():
            for (_, hi, _), (lo_sig, _, _) in zip(tramos, tramos[1:]):
                assert hi == lo_sig, f"{pol}: hueco entre {hi} y {lo_sig}"

    def test_abierto_abajo_y_arriba(self):
        for pol, tramos in RANGOS.items():
            assert tramos[0][0] is None, pol   # sin piso
            assert tramos[-1][1] is None, pol  # sin techo


class TestClasifica:
    @pytest.mark.parametrize("valor, esperado", [
        (0,     "Buena"),
        (44.9,  "Buena"),
        (45,    "Buena"),        # el corte pertenece a la categoría baja
        (45.1,  "Aceptable"),
        (50,    "Aceptable"),
        (50.1,  "Mala"),
        (132,   "Mala"),
        (132.1, "Muy mala"),
        (213,   "Muy mala"),
        (213.1, "Extremadamente mala"),
        (9999,  "Extremadamente mala"),
    ])
    def test_cortes_de_pm10(self, valor, esperado):
        assert clasifica(valor, "PM10")[0] == esperado

    @pytest.mark.parametrize("valor, esperado", [
        (0.058,  "Buena"),
        (0.0581, "Aceptable"),
        (0.090,  "Aceptable"),
        (0.0901, "Mala"),
        (0.175,  "Muy mala"),
        (0.176,  "Extremadamente mala"),
    ])
    def test_cortes_de_ozono(self, valor, esperado):
        assert clasifica(valor, "O3")[0] == esperado

    def test_el_corte_no_sube_de_categoria(self):
        # Regresión: 45 µg/m³ de PM10 es 'Buena', no 'Aceptable'. Es la
        # diferencia entre reportar un día bueno y uno regular.
        for pol, tramos in RANGOS.items():
            for lo, hi, cat in tramos:
                if hi is not None:
                    assert clasifica(hi, pol)[0] == cat, f"{pol} en {hi}"

    @pytest.mark.parametrize("vacio", [None, np.nan])
    def test_sin_dato_no_es_buena(self, vacio):
        # Un día sin medición NO debe contarse como día bueno.
        assert clasifica(vacio, "PM10") == (None, None)

    def test_puntaje_acompana_a_la_categoria(self):
        cat, score = clasifica(200, "PM10")
        assert cat == "Muy mala"
        assert score == CAT_PUNTAJE["Muy mala"] == 4

    def test_puntajes_crecen_con_la_severidad(self):
        assert [CAT_PUNTAJE[c] for c in CAT_ORDER] == [1, 2, 3, 4, 5]


class TestFracRango:
    def test_mitad_del_rango(self):
        # PM10 'Aceptable' va de 45 a 50; 47.5 está a la mitad.
        assert frac_rango(47.5, "PM10", "Aceptable") == pytest.approx(0.5)

    def test_extremos(self):
        assert frac_rango(45.0, "PM10", "Aceptable") == pytest.approx(0.0)
        assert frac_rango(50.0, "PM10", "Aceptable") == pytest.approx(1.0)

    def test_categoria_sin_techo_es_uno(self):
        assert frac_rango(9999, "PM10", "Extremadamente mala") == 1.0

    def test_categoria_sin_piso_es_cero(self):
        assert frac_rango(10, "PM10", "Buena") == 0.0

    @pytest.mark.parametrize("valor, cat", [(None, "Mala"), (np.nan, "Mala"), (50, None)])
    def test_sin_dato_es_cero(self, valor, cat):
        assert frac_rango(valor, "PM10", cat) == 0.0


class TestRedondearPorNom:
    @pytest.mark.parametrize("valor, pol, esperado", [
        (0.05849, "O3",    0.058),
        (0.10649, "NO2",   0.106),
        (0.03549, "SO2",   0.035),
        (5.005,   "CO",    5.01),
        (45.5,    "PM10",  46.0),
        (14.5,    "PM2.5", 15.0),
    ])
    def test_decimales_por_contaminante(self, valor, pol, esperado):
        assert redondear_por_nom(valor, pol) == esperado

    def test_contaminante_desconocido_pasa_sin_tocar(self):
        assert redondear_por_nom(1.23456, "NOX") == 1.23456

    def test_nan_se_conserva(self):
        assert np.isnan(redondear_por_nom(np.nan, "PM10"))


class TestPresets:
    def test_2026_es_mas_estricto_que_2024(self):
        l24, _ = select_nom_preset(2024)
        l26, _ = select_nom_preset(2026)
        assert l26["PM10"]["24H"] < l24["PM10"]["24H"]
        assert l26["PM2.5"]["24H"] < l24["PM2.5"]["24H"]
        assert l26["O3"]["8H"] < l24["O3"]["8H"]

    def test_ano_no_soportado_avisa_cuales_hay(self):
        with pytest.raises(ValueError, match="2024"):
            select_nom_preset(2030)

    def test_cada_preset_trae_ambos_juegos_de_limites(self):
        for anio, preset in NOM_PRESETS.items():
            assert "NOM_LIMITS" in preset, anio
            assert "LIMITES_ANUALES" in preset, anio


class TestCumplimientoDiario:
    def test_dia_dentro_de_norma_cumple(self, tabla_diaria):
        out = compute_nom_daily_flags(tabla_diaria)
        assert out.loc[0, "NOM_O3_CUMPLE"] == "Si"
        assert out.loc[0, "NOM_GLOBAL_CUMPLE"] == "Si"

    def test_sin_datos_suficientes_no_se_evalua(self, tabla_diaria):
        # Los mismos valores que la fila 0, pero sin horas suficientes:
        # el resultado es None, NO 'No'. Un día incompleto no reprueba.
        out = compute_nom_daily_flags(tabla_diaria)
        # pandas guarda el None como NaN al meterlo en la columna; lo que
        # importa es que NO sea 'Si' ni 'No'.
        assert pd.isna(out.loc[1, "NOM_O3_CUMPLE"])
        assert out.loc[1, "NOM_O3_CUMPLE"] not in ("Si", "No")
        assert pd.isna(out.loc[1, "NOM_GLOBAL_CUMPLE"])

    def test_excedencia_reprueba(self, tabla_diaria):
        # Fila 2: O3 de 8 h en 0.060, por encima del límite 2026 de 0.051.
        out = compute_nom_daily_flags(tabla_diaria)
        assert out.loc[2, "NOM_O3_CUMPLE"] == "No"
        assert out.loc[2, "NOM_GLOBAL_CUMPLE"] == "No"

    def test_fila_sin_ningun_dato_queda_en_none(self, tabla_diaria):
        out = compute_nom_daily_flags(tabla_diaria)
        assert pd.isna(out.loc[3, "NOM_GLOBAL_CUMPLE"])
        assert out.loc[3, "NOM_GLOBAL_CUMPLE"] not in ("Si", "No")

    def test_el_criterio_de_2024_es_mas_permisivo(self, tabla_diaria):
        # El mismo O3 de 0.060 cumple con el límite 2024 (0.060) y no con el
        # de 2026 (0.051). Prueba que el preset se puede inyectar.
        limites_2024, _ = select_nom_preset(2024)
        out = compute_nom_daily_flags(tabla_diaria, nom_limits=limites_2024)
        assert out.loc[2, "NOM_O3_CUMPLE"] == "Si"

    def test_un_solo_contaminante_fuera_tumba_el_global(self, tabla_diaria):
        out = compute_nom_daily_flags(tabla_diaria)
        # Fila 2 tiene PM10 en 200 (sobre el límite de 50) además del O3.
        assert out.loc[2, "NOM_PM10_CUMPLE"] == "No"
        assert out.loc[2, "NOM_GLOBAL_CUMPLE"] == "No"

    def test_no_modifica_el_dataframe_original(self, tabla_diaria):
        columnas_antes = list(tabla_diaria.columns)
        compute_nom_daily_flags(tabla_diaria)
        assert list(tabla_diaria.columns) == columnas_antes
