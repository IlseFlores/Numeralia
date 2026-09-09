"""
Figuras del dashboard (numeralia.reporte.figuras).

test_dashboard.py ya cubre a fondo la geometría de _fig_serie_buena_mensual y
_fig_mapa a través de main; aquí solo se fija el nuevo punto de importación y
la lógica de _tendencia_buena, que antes no se probaba sola.
"""

import pandas as pd

from numeralia.reporte import figuras
from numeralia.reporte.formato import BUENA_25, BUENA_26, MALA_25, MALA_26


class TestTendenciaBuena:
    def test_mejora_empeora_igual(self):
        assert figuras._tendencia_buena({BUENA_25: 10, BUENA_26: 15}) == '▲ mejora'
        assert figuras._tendencia_buena({BUENA_25: 15, BUENA_26: 10}) == '▼ empeora'
        assert figuras._tendencia_buena({BUENA_25: 10, BUENA_26: 10}) == '● sin cambio'


class TestFigMapa:
    def test_construye_con_las_columnas_de_acumulado(self):
        df = pd.DataFrame({
            'Estación': ['A', 'B'],
            'Latitud': [20.6, 20.7],
            'Longitud': [-103.3, -103.4],
            MALA_25: [10, 20],
            MALA_26: [5, 25],
            BUENA_25: [100, 90],
            BUENA_26: [120, 85],
        })
        fig = figuras._fig_mapa(df)
        assert fig.data  # al menos un trace


class TestFigSerieMensual:
    def test_rama_de_respaldo_sin_columnas(self):
        fig = figuras._fig_serie_buena_mensual(pd.DataFrame({'A': [1], 'B': [2]}))
        assert fig.layout.height is None
