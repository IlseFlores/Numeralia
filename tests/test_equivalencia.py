"""
Equivalencia entre el dominio extraído y el script original.

Esta es la red de seguridad del refactor: comprueba que
``numeralia.dominio`` produce exactamente los mismos números que
``pipeline_completo.py``. Mientras estas pruebas pasen, mover código no
cambió ningún resultado del reporte.

Cuando la migración termine y ``pipeline_completo.py` desaparezca, este
archivo se borra con él.
"""

import numpy as np
import pandas as pd
import pytest

from numeralia.dominio import ias, nom172, nowcast

original = pytest.importorskip(
    "pipeline_completo",
    reason="pipeline_completo.py no está disponible; el refactor ya terminó.",
)


VALORES = [0, 0.5, 1.5, 2.5, 45, 45.5, 47.5, 50, 132.4, 213.5, 0.0585, 0.1065, 5.005, 9999]


class TestRedondeo:
    @pytest.mark.parametrize("valor", VALORES)
    @pytest.mark.parametrize("decimales", [0, 2, 3])
    def test_round_half_up(self, valor, decimales):
        assert nowcast.round_half_up(valor, decimales) == original.round_half_up(valor, decimales)

    @pytest.mark.parametrize("valor", VALORES)
    @pytest.mark.parametrize("pol", ["O3", "NO2", "SO2", "CO", "PM10", "PM2.5", "NOX"])
    def test_redondeo_por_nom(self, valor, pol):
        nuevo    = nom172.redondear_por_nom(valor, pol, "avg24")
        anterior = original._round_by_nom(valor, pol, "avg24")
        assert nuevo == anterior


class TestClasificacion:
    @pytest.mark.parametrize("pol", ["PM10", "PM2.5", "O3", "NO2", "SO2", "CO"])
    def test_clasifica_en_todo_el_rango(self, pol):
        # Barrido denso alrededor de cada corte de la norma.
        cortes = [v for lo, hi, _ in nom172.RANGOS[pol] for v in (lo, hi) if v is not None]
        muestras = []
        for c in cortes:
            muestras += [c * 0.999, c, c * 1.001]
        muestras += [0, max(cortes) * 10]

        for v in muestras:
            assert nom172.clasifica(v, pol) == original.clasifica(v, pol), f"{pol} en {v}"

    @pytest.mark.parametrize("vacio", [None, np.nan])
    def test_clasifica_sin_dato(self, vacio):
        assert nom172.clasifica(vacio, "PM10") == original.clasifica(vacio, "PM10")

    @pytest.mark.parametrize("pol", ["PM10", "PM2.5", "O3"])
    def test_frac_rango(self, pol):
        for lo, hi, cat in nom172.RANGOS[pol]:
            for v in (lo, hi, 0, 1, 100):
                if v is None:
                    continue
                assert nom172.frac_rango(v, pol, cat) == pytest.approx(
                    original._frac_rango(v, pol, cat), nan_ok=True), f"{pol}/{cat} en {v}"


class TestNowCast:
    @pytest.fixture
    def series(self):
        rng = np.random.default_rng(20260826)
        casos = {
            "constante":  [100.0] * 12,
            "ceros":      [0.0] * 12,
            "creciente":  [float(v) for v in range(10, 130, 10)],
            "decreciente": [float(v) for v in range(120, 0, -10)],
            "huecos":     [10.0, None, 30.0, None, 50.0, 60.0,
                           None, 80.0, 90.0, None, 110.0, 120.0],
            "cola_vacia": [10.0] * 9 + [None, None, None],
        }
        for i in range(15):
            casos[f"aleatoria_{i}"] = [
                None if x < 0 else round(float(x), 1)
                for x in rng.normal(60, 40, 12)
            ]
        return casos

    @pytest.mark.parametrize("pm", [0, 1])
    def test_nowcast_identico(self, series, pm):
        for nombre, valores in series.items():
            assert nowcast.NowCast(valores, pm) == original.NowCast(valores, pm), nombre

    def test_serie_por_estacion_identica(self):
        rng = np.random.default_rng(7)
        df = pd.DataFrame({"PM10": [
            np.nan if x < 0 else round(float(x), 1) for x in rng.normal(50, 35, 60)
        ]})
        pd.testing.assert_series_equal(
            nowcast.serie_nowcast_por_estacion(df, "PM10", 0),
            original.serie_nowcast_por_estacion(df, "PM10", 0),
        )

    @pytest.mark.parametrize("fn", ["rolling_8h", "rolling_24h"])
    def test_rollings_identicos(self, fn):
        rng = np.random.default_rng(11)
        s = pd.Series([np.nan if x < 0 else float(x) for x in rng.normal(40, 30, 48)])
        pd.testing.assert_series_equal(getattr(nowcast, fn)(s), getattr(original, fn)(s))


class TestConstantes:
    def test_rangos_intactos(self):
        assert nom172.RANGOS == original.RANGOS

    def test_categorias_intactas(self):
        assert nom172.CAT_ORDER == original.CAT_ORDER
        assert nom172.CAT_PUNTAJE == original.CAT_PUNTAJE

    def test_presets_intactos(self):
        assert nom172.NOM_PRESETS == original.NOM_PRESETS

    def test_limites_activos_intactos(self):
        assert nom172.NOM_LIMITS == original.NOM_LIMITS
        assert nom172.LIMITES_ANUALES == original.LIMITES_ANUALES

    def test_fuentes_del_ias_intactas(self):
        assert ias.IAS_SOURCE == original.IAS_SOURCE
        assert ias.ORDEN_DOM == original.ORDEN_DOM

    def test_criterios_de_suficiencia_intactos(self):
        from numeralia.dominio import suficiencia
        assert suficiencia.SUF_MIN_HORAS == original._SUF_MIN_HORAS
        assert suficiencia.INVALID_FLAGS == original._INVALID_FLAGS
        assert suficiencia.CONTAMINANTES == original._CONTAMINANTES
        assert suficiencia.METEOROLOGIA == original._METEOROLOGIA
        for anio in (2024, 2025, 2026, 2028):
            assert suficiencia.suf_min_yearly(anio) == original.suf_min_yearly(anio)


def _tabla_sintetica(n: int = 120) -> pd.DataFrame:
    """Tabla diaria variada, con huecos, para comparar los cálculos completos."""
    rng = np.random.default_rng(31415)
    filas = []
    for i in range(n):
        def val(media, escala, dec, prob_nan=0.15):
            if rng.random() < prob_nan:
                return np.nan
            return round(float(abs(rng.normal(media, escala))), dec)

        filas.append({
            "STATION": f"E{i % 13:02d}",
            "FECHA": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
            "O3_MAX_1H": val(0.07, 0.04, 3), "O3_MAX_8H": val(0.05, 0.03, 3),
            "NO2_MAX_1H": val(0.06, 0.04, 3), "SO2_MAX_1H": val(0.04, 0.03, 3),
            "CO_MAX_1H": val(6, 5, 2), "CO_MAX_8H": val(4, 3, 2),
            "PM10_AVG_24H": val(60, 45, 0), "PM2.5_AVG_24H": val(22, 18, 0),
            "PM10_NOWCAST_MAX": val(60, 45, 0), "PM2.5_NOWCAST_MAX": val(22, 18, 0),
            "O3_SUF_DIARIA": bool(rng.random() > 0.2),
            "NO2_SUF_DIARIA": bool(rng.random() > 0.2),
            "SO2_SUF_DIARIA": bool(rng.random() > 0.2),
            "CO_SUF_DIARIA": bool(rng.random() > 0.2),
            "PM10_SUF_DIARIA": bool(rng.random() > 0.2),
            "PM2.5_SUF_DIARIA": bool(rng.random() > 0.2),
        })
    return pd.DataFrame(filas)


class TestCalculosCompletos:
    def test_cumplimiento_diario_identico(self):
        df = _tabla_sintetica()
        pd.testing.assert_frame_equal(
            nom172.compute_nom_daily_flags(df),
            original.compute_nom_daily_flags(df),
        )

    def test_ias_diario_identico(self):
        df = _tabla_sintetica()
        pd.testing.assert_frame_equal(
            ias.compute_ias_daily(df),
            original.compute_ias_daily(df),
        )

    def test_cadena_completa_identica(self):
        # El orden real del pipeline: primero cumplimiento, luego IAS.
        df = _tabla_sintetica()
        pd.testing.assert_frame_equal(
            ias.compute_ias_daily(nom172.compute_nom_daily_flags(df)),
            original.compute_ias_daily(original.compute_nom_daily_flags(df)),
        )
