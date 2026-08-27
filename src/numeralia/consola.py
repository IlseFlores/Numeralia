"""
Salida por consola.

Vive aparte de ``cli.py`` porque ``main.py`` también lo necesita,
y hacer que ese archivo importe del CLI crearía un ciclo (el CLI ya lo importa
a él).
"""

from __future__ import annotations

import sys


def forzar_utf8() -> None:
    """
    Pone stdout y stderr en UTF-8.

    En Windows la consola usa cp1252 y el pipeline imprime emojis en sus
    mensajes de avance (🔐, ⚠, ✔), así que sin esto la corrida muere con
    UnicodeEncodeError antes de hacer nada útil. Se llama desde los dos
    puntos por donde se entra al programa —el CLI y el propio
    ``main``— para que valga igual si alguien importa el módulo
    a mano desde una sesión de Python.

    Es idempotente: llamarla dos veces no hace daño.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            # Salida redirigida a algo que no admite reconfiguración; no es
            # motivo para abortar la corrida.
            pass
