"""
Fichas KPI del dashboard (numeralia.reporte.kpis).

No había ningún test de estas fichas. Aquí van smoke tests: que construyan
sin reventar con datos realistas y con datos incompletos, más el formato de
_periodo_corte.
"""

import re

import pandas as pd
from dash import html

from numeralia.reporte import kpis


def _df_episodios():
    return pd.DataFrame(
        [
            ["Precontingencias atmosféricas:", 10, 4],
            ["Contingencias atmosféricas Fase I:", 3, 1],
            ["Contingencias atmosféricas Fase II:", 0, 0],
            ["Contingencias atmosféricas Fase III:", 0, 0],
            ["Episodios totales", 13, 5],
        ],
        columns=["Episodios activados", "2025", "2026"],
    )


def _df_alertas():
    return pd.DataFrame(
        [["Alerta", 3, 5], ["Emergencia", 1, 2], ["Total", 4, 7]],
        columns=["Categoría", "2025", "2026"],
    )


def _texto(componente) -> str:
    """Aplana el texto de un árbol de componentes de Dash."""
    if isinstance(componente, str):
        return componente
    if isinstance(componente, (list, tuple)):
        return " ".join(_texto(c) for c in componente)
    hijos = getattr(componente, "children", None)
    return _texto(hijos) if hijos is not None else ""


class TestPeriodoCorte:
    def test_formato(self):
        texto = kpis._periodo_corte()
        assert re.match(r"Registro del 1 de enero al \d{1,2} de [a-záéíóú]+ del \d{4}$", texto)


class TestKpiActivacionesSimaj:
    def test_construye_y_muestra_el_total(self):
        ficha = kpis._kpi_activaciones_simaj(_df_episodios(), "2026")
        assert isinstance(ficha, html.Div)
        t = _texto(ficha)
        assert "Precontingencias" in t and "Fase I" in t
        assert "5" in t  # total 2026

    def test_fases_en_cero_no_aparecen(self):
        t = _texto(kpis._kpi_activaciones_simaj(_df_episodios(), "2026"))
        assert "Fase II" not in t and "Fase III" not in t


class TestKpiAlertasEmergencias:
    def test_construye_y_muestra_alertas_y_emergencias(self):
        ficha = kpis._kpi_alertas_emergencias(_df_alertas(), "2026")
        assert isinstance(ficha, html.Div)
        t = _texto(ficha)
        assert "Alertas" in t and "Emergencias" in t

    def test_no_revienta_con_categorias_faltantes(self):
        df = pd.DataFrame([["Alerta", 1, 2]], columns=["Categoría", "2025", "2026"])
        assert isinstance(kpis._kpi_alertas_emergencias(df, "2026"), html.Div)
