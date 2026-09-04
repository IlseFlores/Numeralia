"""Configuración que afecta el arranque del dashboard."""

from types import SimpleNamespace

import pytest

from numeralia import cli
from numeralia.config import Config, normalizar_ruta_base


@pytest.mark.parametrize(
    ('valor', 'esperado'),
    [
        ('', '/'),
        ('/', '/'),
        ('reporte-diario', '/reporte-diario/'),
        ('/reporte-diario', '/reporte-diario/'),
        (' /reporte-diario/ ', '/reporte-diario/'),
    ],
)
def test_normaliza_ruta_base(valor, esperado):
    assert normalizar_ruta_base(valor) == esperado


@pytest.mark.parametrize('valor', ['https://ejemplo.test/reporte', '/ruta?x=1', '/ruta#x'])
def test_ruta_base_rechaza_urls_y_fragmentos(valor):
    with pytest.raises(ValueError, match='NUMERALIA_RUTA_BASE'):
        normalizar_ruta_base(valor)


def test_cli_respeta_anio_y_puerto_del_entorno(monkeypatch):
    llamada = {}
    pipeline = SimpleNamespace(
        run_full_pipeline=lambda **opciones: llamada.update(opciones)
    )
    monkeypatch.setenv('NUMERALIA_ANIO', '2031')
    monkeypatch.setenv('NUMERALIA_PUERTO', '8123')
    monkeypatch.setattr(cli, '_cargar_pipeline', lambda: pipeline)

    assert cli.main([]) == 0
    assert llamada['anio_actual'] == 2031
    assert llamada['puerto'] == 8123


def test_config_lee_ruta_base_del_entorno(monkeypatch):
    monkeypatch.setenv('NUMERALIA_RUTA_BASE', 'reporte-diario')
    assert Config.desde_env().ruta_base_dashboard == '/reporte-diario/'
