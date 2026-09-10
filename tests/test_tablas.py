"""
Tablas del dashboard (numeralia.reporte.tablas).

Smoke tests: que construyan sin reventar y que la tabla de episodios arme el
acordeón (tbody oculto + flecha) para los grupos con sub-filas.
"""

import pandas as pd
from dash import dash_table, html

from numeralia.reporte import tablas
from numeralia.reporte.formato import BUENA_25, BUENA_26, MALA_25, MALA_26, SINDATO_25, SINDATO_26


def _ids(componente, acc=None):
    """Junta todos los `id` del árbol de componentes."""
    acc = acc if acc is not None else []
    cid = getattr(componente, "id", None)
    if cid:
        acc.append(cid)
    hijos = getattr(componente, "children", None)
    if isinstance(hijos, (list, tuple)):
        for h in hijos:
            _ids(h, acc)
    elif hijos is not None and not isinstance(hijos, str):
        _ids(hijos, acc)
    return acc


class TestTablaDetalleEstacion:
    def test_construye_con_las_tres_filas(self):
        row = pd.Series({
            BUENA_25: 100, BUENA_26: 120, MALA_25: 10, MALA_26: 5,
            SINDATO_25: 3, SINDATO_26: 2,
        })
        comp = tablas._tabla_detalle_estacion("Águilas", row)
        assert isinstance(comp, html.Div)


class TestTablaEpisodios:
    def _df(self):
        return pd.DataFrame(
            [
                ["Precontingencias atmosféricas:", 10, 4],
                ["   declaradas por Ozono", 6, 1],
                ["   declaradas por PM10", 4, 3],
                ["Contingencias atmosféricas Fase II:", 0, 0],
                ["Episodios totales", 10, 4],
            ],
            columns=["Episodios activados", "2025", "2026"],
        )

    def test_grupo_con_subfilas_arma_acordeon(self):
        ids = _ids(tablas._tabla_episodios(self._df()))
        assert "toggle-episodios-1" in ids
        assert "sub-episodios-1" in ids
        assert "arrow-episodios-1" in ids

    def test_grupo_sin_subfilas_no_tiene_toggle(self):
        ids = _ids(tablas._tabla_episodios(self._df()))
        assert "toggle-episodios-3" not in ids  # Fase II sin sub-filas


class TestTablaAlertasYParametros:
    def test_tabla_alertas_construye(self):
        df = pd.DataFrame(
            [["Alerta", 3, 5], ["Emergencia", 1, 2], ["Total", 4, 7]],
            columns=["Categoría", "2025", "2026"],
        )
        assert isinstance(tablas._tabla_alertas(df), html.Div)

    def test_tabla_parametros_construye(self):
        assert isinstance(tablas._tabla_parametros(), html.Div)


class TestTablaPaginada:
    def test_devuelve_datatable_y_colorea_por_valor(self):
        df = pd.DataFrame({"No": [1, 2], "Fase": ["Alerta", "Emergencia"]})
        t = tablas._tabla_paginada(
            df, "t-x", columna_color="Fase",
            mapa_color={"Alerta": "#FFB300", "Emergencia": "#FC3508"},
            texto_claro_valores=("Emergencia",),
        )
        assert isinstance(t, dash_table.DataTable)
        assert len(t.style_data_conditional) == 2
