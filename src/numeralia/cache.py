"""
Caché con vencimiento para las lecturas de Google Sheets.

El dashboard refresca dos fichas por intervalo. Sin caché, cada pestaña
abierta multiplica las lecturas: dos pestañas son el doble de peticiones a
la API, aunque pidan exactamente lo mismo y en el mismo segundo. Con la
cuota de Sheets (peticiones por minuto y por usuario) eso se traduce en
errores 429 y fichas que se quedan en blanco.

Aquí las lecturas se comparten: la primera trae el dato, las siguientes lo
reusan hasta que vence.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Tuple


class CacheTemporal:
    """
    Guarda valores por clave durante un número de segundos.

    Es seguro entre hilos porque el servidor de desarrollo de Flask atiende
    peticiones en paralelo: dos pestañas pueden pedir lo mismo a la vez.
    """

    def __init__(self) -> None:
        self._datos: Dict[Any, Tuple[float, Any]] = {}
        self._candado = threading.Lock()

    def obtener(self, clave: Any, segundos: float, calcular: Callable[[], Any]) -> Any:
        """
        Devuelve el valor de ``clave``, calculándolo solo si no está o venció.

        ``calcular`` se llama fuera del candado: es una petición de red y
        bloquear a las demás pestañas mientras dura no ayudaría en nada. Eso
        permite que dos hilos calculen lo mismo si entran a la vez —cosa que
        no rompe nada, solo desperdicia una lectura la primera vez.
        """
        ahora = time.monotonic()
        with self._candado:
            entrada = self._datos.get(clave)
            if entrada is not None and ahora - entrada[0] < segundos:
                return entrada[1]

        valor = calcular()

        with self._candado:
            self._datos[clave] = (time.monotonic(), valor)
        return valor

    def limpiar(self, clave: Any = None) -> None:
        """Olvida una clave, o todas si no se pasa ninguna."""
        with self._candado:
            if clave is None:
                self._datos.clear()
            else:
                self._datos.pop(clave, None)

    def __len__(self) -> int:
        with self._candado:
            return len(self._datos)


# Caché compartida por todo el proceso. Una sola, para que las pestañas se
# beneficien entre sí en vez de tener cada una la suya.
cache_sheets = CacheTemporal()
