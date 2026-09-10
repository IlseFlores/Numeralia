"""
Ensamblado del dashboard (numeralia.reporte.app).

No había ningún test que construyera la app entera. Este lo hace con datos
sintéticos y deja que Dash valide el layout y los callbacks (ids duplicados,
outputs inexistentes, etc.).
"""

import os

import pandas as pd
import pytest

from numeralia.reporte.app import build_dash_app


@pytest.fixture(scope="module")
def datos():
    meses = ["Enero", "Febrero", "Marzo"]
    return {
        "episodios": pd.DataFrame(
            [
                ["Precontingencias atmosféricas:", 10, 4],
                ["Contingencias atmosféricas Fase I:", 3, 1],
                ["Contingencias atmosféricas Fase II:", 0, 0],
                ["Contingencias atmosféricas Fase III:", 0, 0],
                ["Episodios totales", 13, 5],
            ],
            columns=["Episodios activados", "2025", "2026"],
        ),
        "alertas": pd.DataFrame(
            [["Alerta", 3, 5], ["Emergencia", 1, 2], ["Total", 4, 7]],
            columns=["Categoría", "2025", "2026"],
        ),
        "imeca": pd.DataFrame({
            "Campo": ["IMECA Máximo del año", "Contaminante", "Estación", "Fecha", "Hora"],
            "2025": [148, "O3", "Miravalle", "12/05/2025", "15:00:00"],
            "2026": [95, "PM10", "Las Pintas", "03/03/2026", "9:00 a.m."],
        }),
        "alertas_2026_raw": pd.DataFrame(columns=[
            "No", "Fase Decretada", "c", "d", "e", "f", "g", "Inicio",
            "Fecha termino", "Municipio (Origen)", "Incidente"]),
        "episodios_2026_raw": pd.DataFrame(columns=[
            "No", "Evento", "Municipio", "Contaminante", "Estacion", "Estado", "Fin"]),
        "resumen_mensual": pd.DataFrame(
            [{"AÑO": a, "MES": m, "GLOBAL": 5} for a in (2025, 2026) for m in meses]),
        "acumulado": pd.DataFrame({
            "Estación": ["AGU", "CEN"],
            "Latitud": [20.6, 20.67], "Longitud": [-103.4, -103.35],
            "2025: Días con mala calidad": [10, 20],
            "2026: Días con mala calidad": [5, 25],
            "2025: Días con buena a aceptable": [100, 90],
            "2026: Días con buena a aceptable": [120, 85],
            "2025: Días sin dato": [3, 2], "2026: Días sin dato": [1, 1],
        }),
    }


@pytest.fixture(scope="module")
def app(datos):
    return build_dash_app(datos=datos)


def test_construye_y_valida_layout_y_callbacks(app):
    # Dash valida ids duplicados, outputs inexistentes y demás al montar.
    app._setup_server()
    assert app.callback_map  # se registraron callbacks


def test_los_assets_apuntan_a_la_raiz_del_repo(app):
    assert os.path.isfile(os.path.join(app.config.assets_folder, "dashboard.js"))


def test_sin_gc_no_registra_los_callbacks_de_refresco(app):
    # Los dos callbacks que releen de Sheets solo se registran si hay conexión.
    salidas = {str(k) for k in app.callback_map}
    assert not any("ficha-eventos-activos" in s for s in salidas)
