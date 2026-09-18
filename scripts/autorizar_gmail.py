"""
Autoriza UNA VEZ la cuenta que va a mandar el reporte diario por Gmail.

Abre el navegador, pide iniciar sesión con la cuenta remitente y aceptar el
permiso de "enviar correo en tu nombre". Al terminar guarda token_gmail.json
con el refresh token: numeralia.notificaciones.gmail lo usa después sin
volver a pedir login.

Requiere client_secret.json (el que se descarga al crear el OAuth Client ID
tipo "Aplicación de escritorio" en Google Cloud Console), junto a este
script o su ruta como primer argumento.

Uso:
    python scripts/autorizar_gmail.py [ruta/a/client_secret.json]
"""

from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ALCANCE_ENVIO = ['https://www.googleapis.com/auth/gmail.send']
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

    flujo = InstalledAppFlow.from_client_secrets_file(str(ruta_client_secret), ALCANCE_ENVIO)
    credenciales = flujo.run_local_server(port=0)

    ruta_token = RAIZ / 'token_gmail.json'
    ruta_token.write_text(credenciales.to_json())
    print(f"Listo. Token guardado en {ruta_token}")
    print("Guárdalo con cuidado: con él, cualquiera puede mandar correo como tú.")


if __name__ == '__main__':
    main()
