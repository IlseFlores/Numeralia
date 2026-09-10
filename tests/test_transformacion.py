"""
Capa de transformación (numeralia.transformacion): pipeline IAS/NOM,
episodios y alertas.

Estas funciones nunca habían tenido test directo (solo se ejercitaban al
correr el pipeline completo contra Sheets). Aquí se cubren las piezas puras,
sin Google Sheets: los cálculos por día/estación/zona y los parsers de fecha.
"""

from datetime import datetime

import pandas as pd
import pytest

from numeralia.transformacion import alertas, episodios, ias_nom


class TestDailyBounds:
    def test_suficientes_horas_calcula_avg_y_max(self):
        df = pd.DataFrame({"O3": [0.01] * 20})
        avg24, max1h, suf, hv = ias_nom._daily_bounds(df, "O3")
        assert suf is True
        assert hv == 20
        assert avg24 == pytest.approx(0.01, abs=1e-6)
        assert max1h == pytest.approx(0.01, abs=1e-6)

    def test_pocas_horas_no_es_suficiente(self):
        df = pd.DataFrame({"O3": [0.01, 0.02]})
        avg24, max1h, suf, hv = ias_nom._daily_bounds(df, "O3")
        assert suf is False
        assert pd.isna(avg24) and pd.isna(max1h)

    def test_columna_ausente_no_truena(self):
        df = pd.DataFrame({"PM10": [10, 20]})
        _, _, suf, hv = ias_nom._daily_bounds(df, "O3")
        assert suf is False and hv == 0


class TestDailyMax:
    def test_max8h_toma_el_maximo_de_la_columna_8h(self):
        df = pd.DataFrame({"O3_8H": [0.03, 0.05, None]})
        assert ias_nom._daily_max8h(df, "O3") == pytest.approx(0.05, abs=1e-6)

    def test_max8h_sin_columna_es_nan(self):
        assert pd.isna(ias_nom._daily_max8h(pd.DataFrame({"X": [1]}), "O3"))

    def test_nowcast_max_toma_el_maximo(self):
        df = pd.DataFrame({"PM10_NOWCAST": [40, 55, None]})
        assert ias_nom._daily_nowcast_max(df, "PM10") == pytest.approx(55)


class TestCalcularNumeralia:
    def _dfd_all(self):
        filas = [
            {"STATION": "AGU", "FECHA": "2026-01-01", "IAS_GLOBAL_CAT_DIA": "Buena"},
            {"STATION": "AGU", "FECHA": "2026-01-02", "IAS_GLOBAL_CAT_DIA": "Mala"},
            {"STATION": "AGU", "FECHA": "2026-01-03", "IAS_GLOBAL_CAT_DIA": None},
            {"STATION": "VAL", "FECHA": "2026-01-01", "IAS_GLOBAL_CAT_DIA": "Muy mala"},
            {"STATION": "AMG", "FECHA": "2026-01-01", "IAS_GLOBAL_CAT_DIA": "Muy mala"},
        ]
        return pd.DataFrame(filas)

    def test_excluye_amg_y_cuenta_por_categoria(self):
        conteos, _, _ = ias_nom._calcular_numeralia(self._dfd_all(), 2026)
        assert conteos["AGU"] == (1, 1, 1)  # malas, buenas, sin_dato
        assert "AMG" not in conteos

    def test_zona_toma_la_estacion_con_mas_dias_malos(self):
        _, zonas, _ = ias_nom._calcular_numeralia(self._dfd_all(), 2026)
        assert zonas["Poniente"] == (1, 1)  # AGU (1 mala) vs VAL (1 mala) -> max empatado

    def test_tabla_numeralia_respeta_el_orden_de_filas(self):
        df = ias_nom._tabla_numeralia(self._dfd_all(), 2026)
        assert list(df["Estación"])[:2] == ["Águilas", "Vallarta"]
        assert "Días con mala calidad (2026)" in df.columns


class TestParseSpanishDate:
    @pytest.mark.parametrize("texto,esperado", [
        ("jueves, 1 de enero de 2026, 6:00", datetime(2026, 1, 1, 6, 0)),
        ("Miércoles 29 de abril de 2026 7:00", datetime(2026, 4, 29, 7, 0)),
        ("sábado, 2 de mayo de 2026", datetime(2026, 5, 2, 0, 0)),
        ("MARTES, 19 DE MAYO DE 2026, 18:00", datetime(2026, 5, 19, 18, 0)),
    ])
    def test_formatos_variados(self, texto, esperado):
        assert episodios._parse_spanish_date(texto) == pd.Timestamp(esperado)

    def test_texto_sin_fecha_da_nat(self):
        assert pd.isna(episodios._parse_spanish_date("sin fecha aquí"))

    def test_no_string_da_nat(self):
        assert pd.isna(episodios._parse_spanish_date(None))


class TestContarEpisodiosYAlertas:
    def test_contar_episodios_desglosa_por_contaminante(self):
        df = pd.DataFrame({
            "Evento": ["PreContingencia Atmosférica", "PreContingencia Atmosférica"],
            "Contaminante": ["O3", "PM10"],
        })
        r = episodios._contar_episodios(df)
        assert r["Precontingencias atmosféricas:"] == 2
        assert r["   Precontingencias declaradas por Ozono"] == 1
        assert r["Episodios Totales"] == 2

    def test_contar_alertas_separa_alerta_y_emergencia(self):
        df = pd.DataFrame({"Fase Decretada": ["Alerta", "Emergencia", "Alerta"]})
        r = alertas._contar_alertas(df)
        assert r == {"Alertas:": 2, "Emergencias:": 1, "Total Alertas y Emergencias": 3}


class TestCorteMismoPeriodo:
    def test_corte_cae_en_el_mismo_dia_y_mes_que_ayer(self):
        corte = episodios._corte_mismo_periodo(2025)
        assert corte.year == 2025
        assert (corte.hour, corte.minute, corte.second) == (23, 59, 59)
