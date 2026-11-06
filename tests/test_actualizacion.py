"""Pruebas del #actualizar: el despachador que corre el pipeline y cambia la app."""

import threading
import time

import pytest

from flask import Flask
from werkzeug.test import Client

from numeralia.reporte.actualizacion import Despachador


class _AppFalsa:
    """Imita una app de Dash: lo único que usa el despachador es ``.server``."""

    def __init__(self, texto):
        self.server = Flask(texto)
        self.server.add_url_rule('/reporte-diario/', 'inicio', lambda: texto)


def _esperar(despachador, estado, segundos=5, tarea='actualizar'):
    limite = time.time() + segundos
    while despachador.estado(tarea)['estado'] != estado and time.time() < limite:
        time.sleep(0.01)
    return despachador.estado(tarea)


def test_sirve_la_app_vigente_y_la_cambia_al_terminar():
    d = Despachador(_AppFalsa('viejo'), lambda: _AppFalsa('nuevo'),
                    ruta_base='/reporte-diario/')
    c = Client(d)
    assert c.get('/reporte-diario/').get_data(as_text=True) == 'viejo'

    r = c.post('/reporte-diario/_actualizar')
    assert r.status_code == 202
    assert _esperar(d, 'listo')['estado'] == 'listo'
    assert c.get('/reporte-diario/').get_data(as_text=True) == 'nuevo'
    assert c.get('/reporte-diario/_actualizar/estado').get_json()['estado'] == 'listo'


def test_no_corre_dos_a_la_vez():
    soltar = threading.Event()

    def lento():
        soltar.wait(5)
        return _AppFalsa('nuevo')

    d = Despachador(_AppFalsa('viejo'), lento, ruta_base='/reporte-diario/')
    c = Client(d)
    assert c.post('/reporte-diario/_actualizar').status_code == 202
    assert c.post('/reporte-diario/_actualizar').status_code == 409
    # Mientras corre, el dashboard sigue con los datos de antes.
    assert c.get('/reporte-diario/').get_data(as_text=True) == 'viejo'
    soltar.set()
    assert _esperar(d, 'listo')['estado'] == 'listo'


def test_si_falla_conserva_la_app_anterior():
    def falla():
        raise RuntimeError('La validación ENVISTA falló')

    d = Despachador(_AppFalsa('viejo'), falla, ruta_base='/reporte-diario/')
    c = Client(d)
    c.post('/reporte-diario/_actualizar')
    estado = _esperar(d, 'error')
    assert estado['estado'] == 'error'
    assert 'ENVISTA' in estado['mensaje']
    assert c.get('/reporte-diario/').get_data(as_text=True) == 'viejo'
    # Tras un error se puede volver a intentar.
    assert c.post('/reporte-diario/_actualizar').status_code == 202


def test_reporta_avance_y_aprende_la_duracion():
    soltar = threading.Event()

    def lento():
        soltar.wait(5)
        return _AppFalsa('nuevo')

    d = Despachador(_AppFalsa('viejo'), lento, ruta_base='/reporte-diario/',
                    duracion_estimada=300)
    assert d.estado()['transcurrido_seg'] is None
    d.iniciar()
    time.sleep(0.05)
    e = d.estado()
    assert e['duracion_estimada_seg'] == 300
    assert e['transcurrido_seg'] >= 0
    soltar.set()
    e = _esperar(d, 'listo')
    # La estimación siguiente es lo que tardó esta corrida, no la del arranque.
    assert e['duracion_estimada_seg'] < 300
    assert e['transcurrido_seg'] is None


def test_notificacion_devuelve_el_mensaje_y_no_cambia_la_app():
    d = Despachador(_AppFalsa('viejo'), lambda: _AppFalsa('nuevo'),
                    ruta_base='/reporte-diario/',
                    notificar=lambda: 'Reporte del 5 de noviembre de 2026 enviado a 3 destinatarios.')
    c = Client(d)
    assert c.post('/reporte-diario/_notificacion').status_code == 202
    _esperar(d, 'listo', tarea='notificacion')
    e = c.get('/reporte-diario/_notificacion/estado').get_json()
    assert e['estado'] == 'listo'
    assert 'enviado a 3' in e['mensaje']
    assert c.get('/reporte-diario/').get_data(as_text=True) == 'viejo'


def test_una_tarea_a_la_vez():
    soltar = threading.Event()

    def lento():
        soltar.wait(5)
        return _AppFalsa('nuevo')

    d = Despachador(_AppFalsa('viejo'), lento, ruta_base='/reporte-diario/',
                    notificar=lambda: 'enviado')
    c = Client(d)
    assert c.post('/reporte-diario/_actualizar').status_code == 202
    r = c.post('/reporte-diario/_notificacion')
    assert r.status_code == 409
    assert r.get_json()['ocupado_por'] == 'actualizar'
    soltar.set()
    assert _esperar(d, 'listo')['estado'] == 'listo'


def test_sin_notificar_no_hay_ruta_de_notificacion():
    d = Despachador(_AppFalsa('viejo'), lambda: _AppFalsa('nuevo'),
                    ruta_base='/reporte-diario/')
    c = Client(d)
    # Cae a la app de Dash, que no conoce esa ruta.
    assert c.post('/reporte-diario/_notificacion').status_code in (404, 405)


def test_token_gmail_desde_el_env(monkeypatch, tmp_path):
    # El módulo importa Drive/Playwright; están en la imagen pero no siempre
    # en un venv local.
    pytest.importorskip('googleapiclient')
    pytest.importorskip('playwright')
    from numeralia.notificaciones.reporte_diario import ruta_token_gmail
    monkeypatch.delenv('GMAIL_TOKEN_JSON', raising=False)
    assert ruta_token_gmail(tmp_path) == tmp_path / 'token_gmail.json'

    monkeypatch.setenv('GMAIL_TOKEN_JSON', '{"refresh_token": "abc"}')
    ruta = ruta_token_gmail(tmp_path)
    assert ruta.read_text(encoding='utf-8') == '{"refresh_token": "abc"}'

    monkeypatch.setenv('GMAIL_TOKEN_JSON', 'no es json')
    with pytest.raises(ValueError, match='GMAIL_TOKEN_JSON'):
        ruta_token_gmail(tmp_path)


def test_get_a_actualizar_no_dispara_nada():
    d = Despachador(_AppFalsa('viejo'), lambda: _AppFalsa('nuevo'),
                    ruta_base='/reporte-diario/')
    c = Client(d)
    assert c.get('/reporte-diario/_actualizar').status_code == 404
    assert d.estado()['estado'] == 'inactivo'
