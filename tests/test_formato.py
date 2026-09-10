"""
Helpers puros de formato de la capa de reporte (numeralia.reporte.formato).

Salieron de main.py en el Paso 2 del refactor; antes solo se probaban de
rebote a través de las tarjetas del dashboard.
"""

import pandas as pd
import pytest

from numeralia.reporte import formato


class TestToNum:
    def test_convierte_texto_con_coma(self):
        assert formato._to_num("1,234") == 1234.0

    def test_devuelve_none_si_no_es_numero(self):
        assert formato._to_num("abc") is None
        assert formato._to_num(None) is None


class TestSinAcentos:
    def test_quita_acentos_y_conserva_lo_demas(self):
        assert formato._sin_acentos("Águilas Ñ") == "Aguilas N"


class TestBuscarColumna:
    def test_encuentra_por_fragmento_sin_acentos(self):
        cols = ["Fecha Término", "Municipio (Origen)"]
        assert formato._buscar_columna(cols, "termino") == "Fecha Término"

    def test_devuelve_none_si_no_hay(self):
        assert formato._buscar_columna(["A", "B"], "zzz") is None


class TestNormalizarMes:
    @pytest.mark.parametrize("entrada,esperado", [
        ("Enero", (1, "Enero")),
        ("febrero", (2, "Febrero")),
        ("MARZO", (3, "Marzo")),
        ("4", (4, "Abril")),
        ("13", (None, "13")),
        ("no es mes", (None, "no es mes")),
    ])
    def test_casos(self, entrada, esperado):
        assert formato._normalizar_mes(entrada) == esperado


class TestFechaMesAbreviado:
    def test_convierte_formato_esperado(self):
        assert formato._fecha_mes_abreviado("01/02/2026") == "01/Feb/2026"

    def test_devuelve_tal_cual_si_no_encaja(self):
        assert formato._fecha_mes_abreviado("ayer") == "ayer"


class TestFormatearHora:
    @pytest.mark.parametrize("entrada,esperado", [
        ("14:05:00", "2:05 p.m."),
        ("9:30 a.m.", "9:30 a.m."),
        ("00:00", "12:00 a.m."),
    ])
    def test_casos(self, entrada, esperado):
        assert formato._formatear_hora(entrada) == esperado

    def test_devuelve_tal_cual_lo_no_reconocido(self):
        assert formato._formatear_hora("sin hora") == "sin hora"


class TestClasificarImeca:
    @pytest.mark.parametrize("valor,cat", [
        (None, "Sin dato"),
        (40, "Buena"),
        (80, "Aceptable"),
        (120, "Mala"),
        (180, "Muy mala"),
        (250, "Extremadamente mala"),
    ])
    def test_cortes(self, valor, cat):
        assert formato._clasificar_imeca(valor) == cat


class TestSiguienteClasesBitacoras:
    def test_alterna_solo_la_del_trigger(self):
        r = formato._siguiente_clases_bitacoras(
            "bitacora-alertas-header", "bitacora-cerrada", "bitacora-cerrada")
        assert r == ("bitacora-abierta", "bitacora-cerrada")

    def test_trigger_desconocido_no_cambia_nada(self):
        r = formato._siguiente_clases_bitacoras("otro", "bitacora-abierta", "bitacora-cerrada")
        assert r == ("bitacora-abierta", "bitacora-cerrada")


class TestOrdenarPorNoDesc:
    def test_ordena_desc_y_descarta_vacias(self):
        df = pd.DataFrame({"No": ["1", "3", "", "2"], "x": ["a", "b", "c", "d"]})
        out = formato._ordenar_por_no_desc(df)
        assert list(out["No"]) == ["3", "2", "1"]

    def test_df_vacio_pasa_de_largo(self):
        df = pd.DataFrame({"No": [], "x": []})
        assert formato._ordenar_por_no_desc(df).empty
