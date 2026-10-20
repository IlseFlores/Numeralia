"""
Autoriza UNA VEZ la cuenta que va a mandar el reporte diario por Gmail y
subir la copia a Drive.

Abre el navegador, pide iniciar sesión con la cuenta remitente y aceptar los
permisos de "enviar correo en tu nombre" y "ver y administrar tus archivos
de Drive". Al terminar guarda token_gmail.json con el refresh token:
numeralia.notificaciones.gmail y numeralia.notificaciones.drive lo usan
después sin volver a pedir login.

El de Drive es a propósito el alcance completo (no 'drive.file'): el reporte
se sube a una carpeta que YA EXISTE de antes y que no creó esta app, así que
hace falta poder ver y escribir en carpetas ajenas, no solo en lo que la
propia app vaya creando.

Requiere client_secret.json (el que se descarga al crear el OAuth Client ID
tipo "Aplicación de escritorio" en Google Cloud Console; la API de Drive
tiene que estar habilitada en ese mismo proyecto), junto a este script o su
ruta como primer argumento.

Uso:
    python scripts/autorizar_gmail.py [ruta/a/client_secret.json]
"""

from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from numeralia.notificaciones._oauth import ALCANCES

RAIZ = Path(__file__).resolve().parents[1]


def main() -> None:
    ruta_client_secret = (Path(sys.argv[1]) if len(sys.argv) > 1
                          else RAIZ / 'client_secret_gmail.json')
    if not ruta_client_secret.exists():
        sys.exit(
            f"No encontré {ruta_client_secret}.\n"
            "Descárgalo desde Google Cloud Console: APIs y servicios > "
            "Credenciales > el OAuth Client ID tipo 'Aplicación de escritorio'."
        )

    flujo = InstalledAppFlow.from_client_secrets_file(str(ruta_client_secret), ALCANCES)
    credenciales = flujo.run_local_server(port=0)

    ruta_token = RAIZ / 'token_gmail.json'
    ruta_token.write_text(credenciales.to_json())
    print(f"Listo. Token guardado en {ruta_token}")
    print("Guárdalo con cuidado: con él, cualquiera puede mandar correo y leer/escribir "
          "en tu Drive como tú.")


if __name__ == '__main__':
    main()
