"""
Tareas a pedido desde la URL del dashboard, sin reiniciar el contenedor.

    https://.../reporte-diario/#actualizar    -> vuelve a correr el pipeline
    https://.../reporte-diario/#notificacion  -> manda el reporte diario por
                                                 correo (lo mismo que
                                                 python -m numeralia.notificaciones.reporte_diario)

El JavaScript de ``assets/actualizar.js`` ve el ``#...``, pide aquí que se
corra la tarea y muestra un aviso con barra de avance hasta que termina.

Cómo se cambia la app en caliente (#actualizar): el servidor no sirve la app
de Dash directamente sino este ``Despachador``, que le pasa cada petición a
la app vigente. Al terminar el pipeline se arma una app nueva con los datos
frescos y se reemplaza de un golpe; las peticiones en curso terminan con la
anterior. Mientras el pipeline corre, el dashboard sigue con los datos de
antes.

Solo corre una tarea a la vez: el pipeline escribe las hojas que la
notificación revisa, y la notificación fotografía el dashboard que el
pipeline está por reemplazar.

Rutas (bajo la ruta base del dashboard), con <tarea> = actualizar | notificacion:
    POST  _<tarea>          -> la arranca (409 si ya hay una corriendo)
    GET   _<tarea>/estado   -> {'estado': ..., 'mensaje': ..., ...}
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from werkzeug.wrappers import Request, Response

INACTIVO = 'inactivo'
CORRIENDO = 'corriendo'
LISTO = 'listo'
ERROR = 'error'

ACTUALIZAR = 'actualizar'
NOTIFICACION = 'notificacion'


class _Tarea:
    def __init__(self, nombre: str, funcion: Callable[[], Any],
                 duracion_estimada: Optional[float]) -> None:
        self.nombre = nombre
        self.funcion = funcion
        self.t0: Optional[float] = None
        self.estado: Dict[str, Any] = {
            'tarea': nombre,
            'estado': INACTIVO,
            'mensaje': '',
            'inicio': None,
            'fin': None,
            'duracion_estimada_seg': duracion_estimada,
        }


class Despachador:
    """
    Aplicación WSGI que delega en la app de Dash vigente y atiende las rutas
    de las tareas.

    ``reconstruir`` corre el pipeline y devuelve la app nueva de Dash (o
    cualquier objeto con ``.server`` WSGI).

    ``notificar`` (opcional) manda el reporte y devuelve el texto que se le
    muestra a quien lo pidió: "enviado", "ya se había enviado hoy"... Sin
    ella, ``#notificacion`` responde 404.

    ``duracion_estimada`` (segundos) es lo que tardó la corrida del
    arranque; con ella la página dibuja una barra de avance aproximada. Cada
    corrida exitosa de una tarea deja su propia duración como la siguiente
    estimación.
    """

    def __init__(self, app_inicial: Any, reconstruir: Callable[[], Any],
                 ruta_base: str = '/',
                 duracion_estimada: Optional[float] = None,
                 notificar: Optional[Callable[[], str]] = None) -> None:
        self._wsgi = app_inicial.server
        self._base = ruta_base if ruta_base.endswith('/') else ruta_base + '/'
        self._candado = threading.Lock()
        self._tareas: Dict[str, _Tarea] = {
            ACTUALIZAR: _Tarea(ACTUALIZAR, reconstruir, duracion_estimada),
        }
        if notificar is not None:
            self._tareas[NOTIFICACION] = _Tarea(NOTIFICACION, notificar, None)

    # ── Estado ────────────────────────────────────────────────────────────
    def estado(self, tarea: str = ACTUALIZAR) -> dict:
        with self._candado:
            t = self._tareas[tarea]
            datos = dict(t.estado)
            # El avance se mide con el reloj del servidor: el del navegador
            # puede ir desfasado y la barra saltaría.
            datos['transcurrido_seg'] = (
                round(time.monotonic() - t.t0, 1)
                if datos['estado'] == CORRIENDO and t.t0 is not None
                else None)
            ocupada = self._ocupada()
            datos['ocupado_por'] = ocupada.nombre if ocupada else None
            return datos

    def _ocupada(self) -> Optional[_Tarea]:
        """La tarea que está corriendo, si hay. Llamar con el candado tomado."""
        return next((t for t in self._tareas.values()
                     if t.estado['estado'] == CORRIENDO), None)

    def _terminar(self, t: _Tarea, **cambios) -> None:
        with self._candado:
            t.estado.update(fin=_ahora(), **cambios)

    # ── Correr ────────────────────────────────────────────────────────────
    def iniciar(self, tarea: str = ACTUALIZAR) -> bool:
        """
        Arranca la tarea en segundo plano. Devuelve False si ya había una
        corriendo (esa misma u otra).
        """
        with self._candado:
            if self._ocupada() is not None:
                return False
            t = self._tareas[tarea]
            t.estado.update(estado=CORRIENDO, mensaje='', inicio=_ahora(), fin=None)
            t.t0 = time.monotonic()
        threading.Thread(target=self._correr, args=(t,),
                         name=f'numeralia-{tarea}', daemon=True).start()
        return True

    def _correr(self, t: _Tarea) -> None:
        print(f"\n========== #{t.nombre}: inicia ==========")
        try:
            resultado = t.funcion()
        except Exception as e:  # noqa: BLE001 — cualquier falla se reporta a la página
            traceback.print_exc()
            self._terminar(t, estado=ERROR, mensaje=str(e) or type(e).__name__)
            return
        duracion = round(time.monotonic() - t.t0, 1)
        if t.nombre == ACTUALIZAR:
            # Asignar el atributo es atómico: la siguiente petición ya va a la nueva.
            self._wsgi = resultado.server
            mensaje = ''
        else:
            mensaje = str(resultado or '')
        self._terminar(t, estado=LISTO, mensaje=mensaje, duracion_estimada_seg=duracion)
        print(f"========== #{t.nombre}: terminó {mensaje} ==========\n")

    # ── WSGI ──────────────────────────────────────────────────────────────
    def __call__(self, environ, start_response):
        ruta = environ.get('PATH_INFO', '')
        for nombre in self._tareas:
            propia = self._base + '_' + nombre
            if ruta == propia or ruta.startswith(propia + '/'):
                return self._atender(Request(environ), nombre, propia)(
                    environ, start_response)
        return self._wsgi(environ, start_response)

    def _atender(self, peticion: Request, tarea: str, ruta: str) -> Response:
        if peticion.path == ruta and peticion.method == 'POST':
            iniciado = self.iniciar(tarea)
            return _json({**self.estado(tarea), 'iniciado': iniciado},
                         202 if iniciado else 409)
        if peticion.path == ruta + '/estado' and peticion.method == 'GET':
            return _json(self.estado(tarea))
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
