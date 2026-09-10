"""
Autenticación con Google: elige cuenta de servicio (entorno o archivo),
autorización interactiva de Colab, o la credencial por defecto del sistema.

Salió de main.py (Sección 0) en el Paso 4 del refactor.
"""

import gspread
from google.auth import default
from gspread.http_client import BackOffHTTPClient

from numeralia.config import credenciales_desde_env as _credenciales_desde_env
from numeralia.config import ruta_credenciales as _ruta_credenciales


def _en_colab() -> bool:
    """Devuelve True si se está ejecutando en Google Colab."""
    try:
        import google.colab  # noqa: F401
        return True
    except ImportError:
        return False


def autenticar() -> gspread.Client:
    """
    Devuelve el cliente de gspread, eligiendo el método que corresponde al
    entorno, en este orden:

      1. Cuenta de servicio desde variables de entorno (.env). Es la vía
         recomendada: las llaves no quedan en un archivo del proyecto.
      2. Cuenta de servicio desde archivo JSON, si no hay nada en el entorno.
      3. Autorización interactiva de Colab.
      4. Credencial por defecto del sistema (Google Cloud, Cloud Run, etc.).

    El orden importa: las cuentas de servicio van primero para que, si están
    configuradas, nunca se abra un diálogo de permisos — eso es lo que
    permite que el pipeline corra desatendido.

    Todos los caminos usan BackOffHTTPClient: Google limita las lecturas a 60
    por minuto y una corrida completa gasta cerca de la mitad, así que basta
    con que el dashboard esté abierto refrescándose para toparse con un 429 a
    media corrida. Este cliente reintenta solo, con esperas crecientes, en vez
    de tirar el pipeline.
    """
    desde_env = _credenciales_desde_env()
    if desde_env is not None:
        print(f"Autenticando con cuenta de servicio desde el entorno "
              f"({desde_env['client_email']})")
        return gspread.service_account_from_dict(
            desde_env, http_client=BackOffHTTPClient)

    ruta = _ruta_credenciales()
    if ruta is not None:
        print(f"Autenticando con cuenta de servicio: {ruta.name}")
        return gspread.service_account(
            filename=str(ruta), http_client=BackOffHTTPClient)

    if _en_colab():
        from google.colab import auth
        auth.authenticate_user()
        creds, _ = default()
        return gspread.authorize(creds, http_client=BackOffHTTPClient)

    print("Nota: no hay credenciales en el entorno ni archivo de cuenta de servicio; "
          "se usará la credencial por defecto del sistema.")
    creds, _ = default()
    return gspread.authorize(creds, http_client=BackOffHTTPClient)
