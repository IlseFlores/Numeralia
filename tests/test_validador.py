"""
Tests del validador ENVISTA, centrados en el tipo de las columnas.

Las columnas de parámetros conviven con números y con códigos de bandera de
texto ('IR', 'ND', ...), así que su tipo natural es ``object``. En pandas 2,
escribir texto en una columna numérica hacía que pandas la convirtiera sola
(con un FutureWarning); en pandas 3 —la versión que fija requirements.txt—
eso es un ``TypeError`` y el pipeline se caía en ``validar_rangos``.

La caída era intermitente, que es lo que la volvía difícil de ver: si algún
valor de la corrida venía como bandera de texto, la columna ya llegaba en
``object`` y la asignación pasaba sin problema. Solo tronaba cuando TODOS los
valores de esa columna eran numéricos.

Estos tests fijan las dos rutas para que el arreglo no se revierta por
accidente.
"""

import numpy as np
import pandas as pd
import pytest

original = pytest.importorskip(
    "main",
    reason="main.py no está disponible; el refactor ya terminó.",
)


@pytest.fixture
def validador():
    return original.ValidadorCalidadAire()


def _marco(valores, columna="O3"):
    """Marco mínimo con las 3 columnas de estructura y una de parámetro."""
    n = len(valores)
    return pd.DataFrame({
        "STATION": ["AGU"] * n,
        "DATE": pd.to_datetime(["2026-01-01"] * n),
        "HOUR": list(range(1, n + 1)),
        columna: valores,
    })


class TestMarcar:
    """
    ``_marcar`` es el punto único donde se escribe un código de bandera.
    Su única responsabilidad extra sobre un ``.loc[] =`` es garantizar que la
    columna admita texto.
    """

    def test_convierte_la_columna_numerica_antes_de_escribir(self, validador):
        df = _marco([1.0, 2.0, 3.0])
        assert df["O3"].dtype == "float64"

        validador._marcar(df, "O3", pd.Series([True, False, False]), "IR")

        assert df["O3"].dtype == object
        assert df["O3"].tolist() == ["IR", 2.0, 3.0]

    def test_una_columna_de_enteros_tambien_se_convierte(self, validador):
        # int64 falla igual que float64: el problema es que no es object.
        df = _marco([1, 2, 3])
        assert df["O3"].dtype == "int64"

        validador._marcar(df, "O3", pd.Series([False, True, False]), "ND")

        assert df["O3"].tolist() == [1, "ND", 3]

    def test_respeta_las_filas_fuera_de_la_mascara(self, validador):
        df = _marco([10.5, 20.5, 30.5])
        validador._marcar(df, "O3", pd.Series([True, False, True]), "IR")
        # El valor de en medio conserva su valor Y su tipo numérico.
        assert df["O3"].iloc[1] == 20.5
        assert isinstance(df["O3"].iloc[1], float)

    def test_una_columna_que_ya_es_object_se_escribe_igual(self, validador):
        # Es el caso que nunca falló, y tiene que seguir comportándose igual.
        df = _marco([1.0, "ND", 3.0])
        assert df["O3"].dtype == object

        validador._marcar(df, "O3", pd.Series([True, False, False]), "IR")

        assert df["O3"].tolist() == ["IR", "ND", 3.0]

    def test_dos_codigos_distintos_conviven_en_la_misma_columna(self, validador):
        df = _marco([1.0, 2.0, 3.0])
        validador._marcar(df, "O3", pd.Series([True, False, False]), "IR")
        validador._marcar(df, "O3", pd.Series([False, True, False]), "ND")
        assert df["O3"].tolist() == ["IR", "ND", 3.0]

    def test_no_altera_las_demas_columnas(self, validador):
        df = _marco([1.0, 2.0, 3.0])
        tipos_antes = {c: df[c].dtype for c in ("STATION", "DATE", "HOUR")}

        validador._marcar(df, "O3", pd.Series([True, True, True]), "IR")

        assert {c: df[c].dtype for c in ("STATION", "DATE", "HOUR")} == tipos_antes


class TestValidarRangos:
    """
    El caso que tumbaba el pipeline: una columna 100% numérica con algún valor
    fuera del rango físico.
    """

    def test_no_truena_con_una_columna_numerica_pura(self, validador):
        # Regresión directa de:
        #   TypeError: Invalid value 'IR' for dtype 'float64'
        df = _marco([0.05, 0.06, 999.0])
        salida = validador.validar_rangos(df)
        assert "IR" in salida["O3"].tolist()

    def test_marca_solo_lo_que_esta_fuera_de_rango(self, validador):
        # O3 admite de -0.003 a 0.400.
        df = _marco([0.200, 0.500, 0.100])
        salida = validador.validar_rangos(df)
        assert salida["O3"].tolist() == [0.200, "IR", 0.100]

    def test_los_extremos_del_rango_son_validos(self, validador):
        # La comparación es estricta (< min, > max), así que los topes entran.
        df = _marco([-0.003, 0.400])
        salida = validador.validar_rangos(df)
        assert "IR" not in salida["O3"].tolist()

    def test_no_cambia_el_tipo_si_no_hay_nada_que_marcar(self, validador):
        # Sin esta garantía, `_marcar` convertiría columnas a object de
        # gratis en cada corrida limpia.
        df = _marco([0.10, 0.20, 0.30])
        salida = validador.validar_rangos(df)
        assert salida["O3"].dtype == "float64"

    def test_el_limite_de_deteccion_sigue_funcionando(self, validador):
        # Bajo el límite de detección (0.001) el valor se sustituye por el
        # límite, no se marca como fuera de rango.
        df = _marco([0.0005, 0.2])
        salida = validador.validar_rangos(df)
        assert salida["O3"].iloc[0] == pytest.approx(0.001)
        assert salida["O3"].iloc[1] == pytest.approx(0.2)

    def test_cuenta_los_valores_marcados(self, validador, capsys):
        df = _marco([999.0, 999.0, 0.1])
        validador.validar_rangos(df)
        assert "Valores IR (fuera de rango): 2" in capsys.readouterr().out

    def test_una_columna_sin_numeros_no_se_toca(self, validador):
        df = _marco(["ND", "ND"])
        salida = validador.validar_rangos(df)
        assert salida["O3"].tolist() == ["ND", "ND"]

    def test_no_modifica_el_marco_original(self, validador):
        df = _marco([999.0, 0.1])
        validador.validar_rangos(df)
        assert df["O3"].tolist() == [999.0, 0.1]


class TestAplicarBanderas:
    """
    Misma trampa de tipos, en el otro extremo del validador. Aquí nunca se
    había manifestado porque hace falta que la columna sea numérica pura Y
    tenga huecos, pero el patrón era idéntico.
    """

    def test_rellena_los_huecos_de_una_columna_numerica(self, validador):
        df = _marco([np.nan, 7.0])
        assert df["O3"].dtype == "float64"

        salida = validador.aplicar_banderas(df)

        assert salida["O3"].tolist() == ["ND", 7.0]

    def test_traduce_las_banderas_de_envista(self, validador):
        df = _marco(["NoData", "Above R", "WarmUp"])
        salida = validador.aplicar_banderas(df)
        assert salida["O3"].tolist() == ["ND", "IR", "IF"]

    def test_no_cambia_el_tipo_si_no_hay_huecos(self, validador):
        df = _marco([1.0, 2.0])
        assert validador.aplicar_banderas(df)["O3"].dtype == "float64"

    def test_no_toca_las_columnas_de_estructura(self, validador):
        df = _marco([np.nan, 7.0])
        salida = validador.aplicar_banderas(df)
        assert salida["STATION"].tolist() == ["AGU", "AGU"]
        assert salida["HOUR"].tolist() == [1, 2]
