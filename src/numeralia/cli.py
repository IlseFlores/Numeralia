"""
Punto de entrada del proyecto.

Este es el archivo que manda: se corre con ``python -m numeralia`` (o con el
comando ``numeralia``). Lo que hace por dentro va a ir cambiando conforme
avance la migración, pero el comando de afuera ya no cambia.

Hoy la orquestación todavía vive en ``main.py``, en la raíz del
repositorio, así que este módulo lo carga y le delega. Esa dependencia hacia
la raíz es un puente temporal: cuando ``run_full_pipeline`` se mude al
paquete, ``_cargar_pipeline`` desaparece y el resto de este archivo queda
igual.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Optional, Sequence

from numeralia.config import Config
from numeralia.consola import forzar_utf8


def _cargar_pipeline():
    """
    Devuelve el módulo con la orquestación (``main``).

    Puente temporal hacia la raíz del repositorio mientras dura la migración.
    """
    # Si el usuario corrió `python main.py`, ese módulo ya está
    # cargado como __main__: reutilizarlo evita importarlo una segunda vez
    # bajo otro nombre y ejecutar todo su código de módulo por duplicado.
    principal = sys.modules.get('__main__')
    if hasattr(principal, 'run_full_pipeline'):
        return principal

    raiz = Path(__file__).resolve().parents[2]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))

    try:
        # Por importlib y no `import main`: este módulo ya tiene una función
        # llamada main() y el nombre chocaría.
        return importlib.import_module('main')
    except ImportError as e:
        raise SystemExit(
            f"No se pudo cargar main.py desde {raiz}.\n"
            f"Corre el comando desde la carpeta del proyecto. Detalle: {e}"
        )


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='numeralia',
        description='Pipeline y reporte de calidad del aire (SEMADET / SIMAJ).',
        epilog='Sin argumentos: usa el año del sistema y abre el dashboard.',
    )
    parser.add_argument(
        'anio', nargs='?', type=int, default=None,
        help='Año que se reporta. Por omisión, el del sistema.')
    parser.add_argument(
        '--sin-dashboard', action='store_true',
        help='Solo corre el pipeline de datos, sin levantar el dashboard.')
    parser.add_argument(
        '--puerto', type=int, default=None,
        help='Puerto del dashboard (por omisión NUMERALIA_PUERTO o 8050).')
    parser.add_argument(
        '--exportar-json', metavar='RUTA', default=None,
        help='Escribe los datos del dashboard a un JSON en esa ruta.')
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    forzar_utf8()
    args = _construir_parser().parse_args(argv)

    config = Config.desde_env()
    anio = args.anio if args.anio is not None else config.anio
    puerto = args.puerto if args.puerto is not None else config.puerto_dashboard

    pipeline = _cargar_pipeline()
    pipeline.run_full_pipeline(
        anio_actual=anio,
        lanzar_dashboard=not args.sin_dashboard,
        puerto=puerto,
        exportar_json=args.exportar_json,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
