"""
Tarjetas del dashboard (numeralia.reporte.tarjetas).

_encabezado_reporte y las dos bitácoras ya se prueban en test_movil.py.
Aquí van las que faltaban: IMECA, eventos activos, serie mensual, el ícono de
descarga y la búsqueda de logos.
"""

import pandas as pd
from dash import html

from numeralia.reporte import tarjetas


def _texto(c):
    if isinstance(c, str):
        return c
    if isinstance(c, (list, tuple)):
        return " ".join(_texto(x) for x in c)
    hijos = getattr(c, "children", None)
    return _texto(hijos) if hijos is not None else ""


class TestIconoDescarga:
    def test_es_un_boton_con_el_id_dado(self):
        b = tarjetas._icono_descarga("btn-x")
        assert isinstance(b, html.Button)
        assert b.id == "btn-x"


class TestLogoSrc:
    def test_logo_inexistente_devuelve_none(self):
        assert tarjetas._logo_src("no-existe-jamas.png") is None

    def test_carpetas_incluye_la_raiz_del_repo(self):
        rutas = [str(p) for p in tarjetas._carpetas_logos()]
        assert any(r.endswith("logos") for r in rutas)


class TestCardImeca:
    def test_construye_con_los_dos_anios(self):
        df = pd.DataFrame({
            "Campo": ["IMECA Máximo del año", "Contaminante", "Estación", "Fecha", "Hora"],
            "2025": [148, "O3", "Miravalle", "12/05/2025", "15:00:00"],
            "2026": [95, "PM10", "Las Pintas", "03/03/2026", "9:00 a.m."],
        })
        comp = tarjetas._card_imeca(df)
        t = _texto(comp)
        assert "IMECA Máximo Registrado" in t
        assert "148" in t and "95" in t
        assert "Feb" not in t  # 12/05 -> 12/May
        assert "12/May/2025" in t


class TestCardEventosActivos:
    def test_sin_eventos_muestra_el_vacio(self):
        t = _texto(tarjetas._card_eventos_activos([], []))
        assert "Sin episodios ni eventos activos" in t

    def test_lista_alertas_y_episodios_juntos(self):
        alertas = [{"tipo": "alerta", "fase": "Emergencia", "incidente": "Incendio",
                    "municipio": "Zapopan"}]
        episodios = [{"tipo": "episodio", "evento": "Contingencia Atmosférica Fase I",
                      "severidad": 2, "municipio": "Guadalajara", "estacion": "Centro",
                      "contaminante": "O3"}]
        t = _texto(tarjetas._card_eventos_activos(alertas, episodios))
        assert "Incendio" in t and "Zapopan" in t
        assert "Centro" in t and "O3" in t


class TestCardSerieMensual:
    def test_construye_y_trae_el_store_y_la_grafica(self):
        meses = ["Enero", "Febrero", "Marzo"]
        df = pd.DataFrame([{"AÑO": a, "MES": m, "GLOBAL": 5}
                           for a in (2025, 2026) for m in meses])
        comp = tarjetas._card_serie_mensual_2025(df)
        ids = []

        def _walk(c):
            cid = getattr(c, "id", None)
            if cid:
                ids.append(cid)
            hijos = getattr(c, "children", None)
            if isinstance(hijos, (list, tuple)):
                for h in hijos:
                    _walk(h)

        _walk(comp)
        assert "figura-serie-base" in ids
        assert "grafico-serie-mensual" in ids
