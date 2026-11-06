"""
Actualización de la numeralia a pedido, sin reiniciar el contenedor.

El pipeline corre una vez al arrancar y el dashboard se queda con esa foto.
Para refrescarla basta con abrir la página con ``#actualizar`` al final:

    https://.../reporte-diario/#actualizar

El JavaScript de ``assets/dashboard.js`` ve el ``#actualizar``, pide aquí
que se corra el pipeline y espera a que termine para recargar la página.

Cómo se cambia la app en caliente: el servidor no sirve la app de Dash
directamente sino este ``Despachador``, que le pasa cada petición a la app
vigente. Al terminar el pipeline se arma una app nueva con los datos frescos
y se reemplaza de un golpe; las peticiones en curso terminan con la anterior.
Mientras el pipeline corre, el dashboard sigue sirviendo los datos de antes.

Rutas (bajo la ruta base del dashboard):
    POST  _actualizar          -> arranca el pipeline (si no está corriendo ya)
    GET   _actualizar/estado   -> {'estado': ..., 'mensaje': ..., ...}
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Optional

from werkzeug.wrappers import Request, Response

INACTIVO = 'inactivo'
CORRIENDO = 'corriendo'
LISTO = 'listo'
ERROR = 'error'


class Despachador:
    """
    Aplicación WSGI que delega en la app de Dash vigente y atiende las rutas
    de actualización.

    ``reconstruir`` corre el pipeline y devuelve la app nueva de Dash (o
    cualquier objeto con ``.server`` WSGI). Se ejecuta en un hilo aparte.
    """

    def __init__(self, app_inicial: Any, reconstruir: Callable[[], Any],
                 ruta_base: str = '/',
                 duracion_estimada: Optional[float] = None) -> None:
        """
        ``duracion_estimada`` (segundos) es lo que tardó la corrida del
        arranque; con ella la página dibuja una barra de avance aproximada.
        Cada actualización exitosa la reemplaza por su propia duración.
        """
        self._wsgi = app_inicial.server
        self._reconstruir = reconstruir
        base = ruta_base if ruta_base.endswith('/') else ruta_base + '/'
        self._ruta = base + '_actualizar'
        self._candado = threading.Lock()
        self._estado = {
            'estado': INACTIVO,
            'mensaje': '',
            'inicio': None,
            'fin': None,
            'duracion_estimada_seg': duracion_estimada,
        }
        self._t0: Optional[float] = None

    # ── Estado ────────────────────────────────────────────────────────────
    def estado(self) -> dict:
        with self._candado:
            datos = dict(self._estado)
            # El avance se mide con el reloj del servidor: el del navegador
            # puede ir desfasado y la barra saltaría.
            datos['transcurrido_seg'] = (
                round(time.monotonic() - self._t0, 1)
                if datos['estado'] == CORRIENDO and self._t0 is not None
                else None)
            return datos

    def _poner_estado(self, **cambios) -> None:
        with self._candado:
            self._estado.update(cambios)

    # ── Actualización ─────────────────────────────────────────────────────
    def iniciar(self) -> bool:
        """
        Arranca el pipeline en segundo plano. Devuelve False si ya había uno
        corriendo: dos a la vez escribirían las mismas hojas de Sheets.
        """
        with self._candado:
            if self._estado['estado'] == CORRIENDO:
                return False
            self._estado.update(estado=CORRIENDO, mensaje='',
                                inicio=_ahora(), fin=None)
            self._t0 = time.monotonic()
        threading.Thread(target=self._correr, name='numeralia-actualizar',
                         daemon=True).start()
        return True

    def _correr(self) -> None:
        print("\n========== #actualizar: corriendo el pipeline ==========")
        try:
            app_nueva = self._reconstruir()
        except Exception as e:  # noqa: BLE001 — cualquier falla se reporta a la página
            traceback.print_exc()
            self._poner_estado(estado=ERROR, mensaje=str(e) or type(e).__name__,
                               fin=_ahora())
            return
        # Asignar el atributo es atómico: la siguiente petición ya va a la nueva.
        self._wsgi = app_nueva.server
        self._poner_estado(estado=LISTO, mensaje='', fin=_ahora(),
                           duracion_estimada_seg=round(time.monotonic() - self._t0, 1))
        print("========== #actualizar: dashboard actualizado ==========\n")

    # ── WSGI ──────────────────────────────────────────────────────────────
    def __call__(self, environ, start_response):
        ruta = environ.get('PATH_INFO', '')
        if ruta == self._ruta or ruta.startswith(self._ruta + '/'):
            return self._atender(Request(environ))(environ, start_response)
        return self._wsgi(environ, start_response)

    def _atender(self, peticion: Request) -> Response:
        if peticion.path == self._ruta and peticion.method == 'POST':
            iniciado = self.iniciar()
            return _json({**self.estado(), 'iniciado': iniciado},
                         202 if iniciado else 409)
        if peticion.path == self._ruta + '/estado' and peticion.method == 'GET':
            return _json(self.estado())
        return Response('No encontrado', status=404)


def _ahora() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _json(datos: dict, status: int = 200) -> Response:
    return Response(json.dumps(datos, ensure_ascii=False), status=status,
                    mimetype='application/json',
                    headers={'Cache-Control': 'no-store'})


def servir(despachador: Despachador, host: str, puerto: int,
           threaded: Optional[bool] = True) -> None:
    """Levanta el servidor con el despachador en vez de la app de Dash sola."""
    from werkzeug.serving import run_simple
    run_simple(host, puerto, despachador, threaded=threaded,
               use_reloader=False, use_debugger=False)
