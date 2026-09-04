"""
Configuración central del proyecto.

Este módulo es el ÚNICO lugar donde se lee el entorno. Antes las llamadas a
``os.getenv`` estaban repartidas por el archivo (credenciales cerca del
inicio, URLs de hojas casi al final), así que para saber qué se podía
configurar había que leer las 3,849 líneas completas.

Sobre los años: el reporte compara un año contra el anterior. En vez de
escribir 2025 y 2026 por todo el código, aquí se derivan de un solo valor
(``NUMERALIA_ANIO`` o el año del sistema). Cambiar de año es cambiar una
variable de entorno, no editar el fuente.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Campos de la cuenta de servicio, tal como vienen en el JSON de Google.
CAMPOS_CUENTA_SERVICIO = (
    'type', 'project_id', 'private_key_id', 'private_key', 'client_email',
    'client_id', 'auth_uri', 'token_uri', 'auth_provider_x509_cert_url',
    'client_x509_cert_url', 'universe_domain',
)

# Sin estos tres no se puede firmar nada; el resto Google los completa.
_CAMPOS_MINIMOS = ('private_key', 'client_email', 'token_uri')


def normalizar_ruta_base(valor: str) -> str:
    """Normaliza el prefijo público de Dash (siempre con ``/`` a ambos lados)."""
    ruta = valor.strip()
    if not ruta or ruta == '/':
        return '/'
    if '://' in ruta or '?' in ruta or '#' in ruta:
        raise ValueError(
            'NUMERALIA_RUTA_BASE debe ser una ruta, por ejemplo /reporte-diario/.'
        )
    return f"/{ruta.strip('/')}/"


def cargar_dotenv(base: Optional[Path] = None) -> Optional[Path]:
    """
    Carga el archivo .env si existe. Se busca junto al paquete y en la carpeta
    de trabajo. Si python-dotenv no está instalado, se avisa y se sigue: en un
    servidor las variables suelen venir del sistema y no de un archivo.

    Devuelve la ruta cargada, o None si no se cargó ninguna.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    raiz = base or Path(__file__).resolve().parents[2]
    for ruta in (raiz / '.env', Path.cwd() / '.env'):
        if ruta.exists():
            load_dotenv(ruta)
            return ruta
    return None


def credenciales_desde_env() -> Optional[dict]:
    """
    Arma el diccionario de la cuenta de servicio a partir del entorno.

    Acepta dos formas:
      · GOOGLE_CREDENCIALES_JSON con el JSON completo en una sola variable.
      · Una variable por campo, con prefijo GOOGLE_ (GOOGLE_PRIVATE_KEY…).

    Devuelve None si no hay lo mínimo, para que la autenticación siga con los
    otros métodos en vez de tronar.
    """
    crudo = os.getenv('GOOGLE_CREDENCIALES_JSON')
    if crudo:
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError as e:
            raise ValueError(f"GOOGLE_CREDENCIALES_JSON no es un JSON válido: {e}")
    else:
        datos = {}
        for campo in CAMPOS_CUENTA_SERVICIO:
            valor = os.getenv(f'GOOGLE_{campo.upper()}')
            if valor:
                datos[campo] = valor

    if not all(datos.get(c) for c in _CAMPOS_MINIMOS):
        return None

    # En un .env la llave privada se escribe en una sola línea con '\n'
    # literales. Hay que devolverlos a saltos de línea reales o la firma
    # criptográfica falla con un error poco descriptivo.
    datos['private_key'] = datos['private_key'].replace('\n', '\n')
    datos.setdefault('type', 'service_account')
    return datos


def ruta_credenciales(nombre: Optional[str] = None) -> Optional[Path]:
    """Busca el archivo de credenciales junto al proyecto y en la carpeta actual."""
    nombre = nombre or os.getenv('GOOGLE_CREDENCIALES_ARCHIVO', 'credenciales.json')
    raiz = Path(__file__).resolve().parents[2]
    for ruta in (raiz / nombre, Path.cwd() / nombre):
        if ruta.exists():
            return ruta
    return None


@dataclass(frozen=True)
class Config:
    """
    Configuración efectiva de una corrida. Se construye con ``Config.desde_env()``.

    ``anio`` es el año que se reporta; ``anio_previo`` es contra el que se
    compara. Todo lo que antes era un literal 2026 debe salir de aquí.
    """

    anio: int
    urls: Dict[str, str] = field(default_factory=dict)
    puerto_dashboard: int = 8050
    ruta_base_dashboard: str = '/'
    carpeta_logos: str = 'logos'
    anio_criterio_nom: int = 2026
    # Cada cuánto vuelve a leer Sheets el dashboard. Iban en 20 segundos, que
    # con la cuota de la API se traduce en errores 429: son 6 lecturas por
    # minuto POR PESTAÑA abierta. Los episodios activos cambian en escala de
    # horas y el resumen mensual, de días.
    refresco_eventos_seg: int = 300
    refresco_mensual_seg: int = 1800

    @property
    def anio_previo(self) -> int:
        return self.anio - 1

    @property
    def url_destino(self) -> str:
        return self.urls['destino']

    @property
    def url_resumen_mensual(self) -> str:
        return self.urls['resumen_mensual']

    def url_fuente(self, anio: int) -> str:
        """URL de la hoja fuente de episodios/alertas para un año dado."""
        clave = f'fuente_{anio}'
        if clave not in self.urls:
            raise KeyError(
                f"No hay URL configurada para el año {anio}. "
                f"Define URL_FUENTE_{anio} en el .env."
            )
        return self.urls[clave]

    @classmethod
    def desde_env(cls, anio: Optional[int] = None) -> 'Config':
        cargar_dotenv()

        if anio is None:
            crudo = os.getenv('NUMERALIA_ANIO')
            anio = int(crudo) if crudo else datetime.now().year

        urls = {
            'destino': os.getenv('URL_DESTINO', ''),
            'resumen_mensual': os.getenv('URL_RESUMEN_MENSUAL', ''),
        }
        # Las fuentes se descubren por año: URL_FUENTE_2025, URL_FUENTE_2026,
        # URL_FUENTE_2027… sin tener que tocar el código cada enero.
        for clave, valor in os.environ.items():
            if clave.startswith('URL_FUENTE_') and valor:
                sufijo = clave[len('URL_FUENTE_'):]
                if sufijo.isdigit():
                    urls[f'fuente_{int(sufijo)}'] = valor

        return cls(
            anio=anio,
            urls=urls,
            puerto_dashboard=int(os.getenv('NUMERALIA_PUERTO', '8050')),
            ruta_base_dashboard=normalizar_ruta_base(
                os.getenv('NUMERALIA_RUTA_BASE', '/')
            ),
            carpeta_logos=os.getenv('NUMERALIA_CARPETA_LOGOS', 'logos'),
            anio_criterio_nom=int(os.getenv('NUMERALIA_CRITERIO_NOM', '2026')),
            refresco_eventos_seg=int(os.getenv('NUMERALIA_REFRESCO_EVENTOS', '300')),
            refresco_mensual_seg=int(os.getenv('NUMERALIA_REFRESCO_MENSUAL', '1800')),
        )

    def faltantes(self) -> list:
        """Lista de configuraciones obligatorias que están vacías."""
        problemas = []
        if not self.urls.get('destino'):
            problemas.append('URL_DESTINO')
        if not self.urls.get('resumen_mensual'):
            problemas.append('URL_RESUMEN_MENSUAL')
        for anio in (self.anio_previo, self.anio):
            if not self.urls.get(f'fuente_{anio}'):
                problemas.append(f'URL_FUENTE_{anio}')
        return problemas
