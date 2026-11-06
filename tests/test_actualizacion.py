"""Pruebas del #actualizar: el despachador que corre el pipeline y cambia la app."""

import threading
import time

from flask import Flask
from werkzeug.test import Client

from numeralia.reporte.actualizacion import Despachador


class _AppFalsa:
    """Imita una app de Dash: lo único que usa el despachador es ``.server``."""

    def __init__(self, texto):
        self.server = Flask(texto)
        self.server.add_url_rule('/reporte-diario/', 'inicio', lambda: texto)


def _esperar(despachador, estado, segundos=5):
    limite = time.time() + segundos
    while despachador.estado()['estado'] != estado and time.time() < limite:
        time.sleep(0.01)
    return despachador.estado()


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


def test_get_a_actualizar_no_dispara_nada():
    d = Despachador(_AppFalsa('viejo'), lambda: _AppFalsa('nuevo'),
                    ruta_base='/reporte-diario/')
    c = Client(d)
    assert c.get('/reporte-diario/_actualizar').status_code == 404
    assert d.estado()['estado'] == 'inactivo'
