"""
Preparación de datos para las gráficas del navegador
(numeralia.reporte.datos_graficas).

_datos_grafica_episodios, _eventos_activos_2026 y _episodios_activos_raw ya
están cubiertos a fondo por test_dashboard.py y test_movil.py. Aquí se cierran
los huecos: _episodios_por_contaminante y _datos_barras_alertas.
"""

import pandas as pd

from numeralia.reporte.datos_graficas import (
    _datos_barras_alertas,
    _episodios_por_contaminante,
)


def _df_episodios():
    filas = [
        ("Precontingencias atmosféricas:", 100, 40),
        ("   Precontingencias declaradas por Ozono", 60, 10),
        ("   Precontingencias declaradas por PM10", 30, 25),
        ("Contingencias atmosféricas Fase I:", 20, 8),
        ("   Contingencias declaradas por Ozono", 15, 0),
        ("Episodios totales", 120, 48),
    ]
    return pd.DataFrame(filas, columns=["Episodios activados", "2025", "2026"])


class TestEpisodiosPorContaminante:
    def test_solo_devuelve_las_subfilas_de_su_grupo(self):
        r = _episodios_por_contaminante(_df_episodios(), "2025", severidad=1)
        assert r == [("Ozono", 60), ("PM10", 30)]

    def test_otro_grupo_no_arrastra_datos(self):
        r = _episodios_por_contaminante(_df_episodios(), "2026", severidad=2)
        assert r == [("Ozono", 0)]

    def test_ignora_la_fila_de_totales(self):
        r = _episodios_por_contaminante(_df_episodios(), "2025", severidad=1)
        assert all(c != "Episodios totales" for c, _ in r)


class TestDatosBarrasAlertas:
    def test_extrae_por_ano_y_agrega_colores(self):
        df = pd.DataFrame(
            [["Alerta", 3, 5], ["Emergencia", 1, 2], ["Total", 4, 7]],
            columns=["Categoría", "2025", "2026"],
        )
        d = _datos_barras_alertas(df)
        assert (d["alertas_25"], d["emergencias_25"]) == (3, 1)
        assert (d["alertas_26"], d["emergencias_26"]) == (5, 2)
        # trae los 8 colores/textos que el JS indexa a ciegas
        for k in ("color_a25", "color_e25", "color_a26", "color_e26",
                  "texto_a25", "texto_e25", "texto_a26", "texto_e26"):
            assert isinstance(d[k], str) and d[k]

    def test_categoria_ausente_cuenta_como_cero(self):
        df = pd.DataFrame([["Alerta", 3, 5]], columns=["Categoría", "2025", "2026"])
        d = _datos_barras_alertas(df)
        assert d["emergencias_25"] == 0 and d["emergencias_26"] == 0
