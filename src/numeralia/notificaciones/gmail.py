"""
Envío de correo por la API de Gmail, autenticado con OAuth2.

La cuenta remitente es institucional (Google Workspace) y ahí Google no
ofrece "contraseñas de aplicación", así que en vez de guardar una
contraseña se guarda un refresh token: se genera una sola vez a mano, con
scripts/autorizar_gmail.py, y de ahí en adelante este módulo lo usa para
pedir un token de acceso nuevo cada vez que hace falta, sin volver a pedir
login.
"""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from pathlib import Path
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

# Alcance mínimo: solo mandar correo, no leer ni administrar la cuenta.
ALCANCE_ENVIO = ['https://www.googleapis.com/auth/gmail.send']


def _credenciales(ruta_token: Path) -> Credentials:
    if not ruta_token.exists():
        raise FileNotFoundError(
            f"No existe {ruta_token}. Corre scripts/autorizar_gmail.py una "
            "vez para generarlo."
        )
    credenciales = Credentials.from_authorized_user_file(str(ruta_token), ALCANCE_ENVIO)
    if credenciales.expired and credenciales.refresh_token:
        credenciales.refresh(Request())
        # El refresh token no cambia, pero el access token sí: se guarda de
        # vuelta para no tener que pedir uno nuevo en la próxima corrida.
        ruta_token.write_text(credenciales.to_json())
    return credenciales


def _armar_mensaje(remitente: str, destinatarios: Sequence[str], asunto: str,
                   cuerpo: str, adjuntos: Sequence[Path]) -> dict:
    mensaje = EmailMessage()
    mensaje['To'] = ', '.join(destinatarios)
    mensaje['From'] = remitente
    mensaje['Subject'] = asunto
    mensaje.set_content(cuerpo)

    for ruta in adjuntos:
        mensaje.add_attachment(
            ruta.read_bytes(), maintype='application', subtype='pdf',
            filename=ruta.name,
        )

    crudo = base64.urlsafe_b64encode(mensaje.as_bytes()).decode()
    return {'raw': crudo}


def enviar_correo(remitente: str, destinatarios: Sequence[str], asunto: str,
                  cuerpo: str, adjuntos: Sequence[Path], ruta_token: Path) -> str:
    """Envía el correo y devuelve el id que Gmail le asigna al mensaje."""
    credenciales = _credenciales(ruta_token)
    servicio = build('gmail', 'v1', credentials=credenciales)
    mensaje = _armar_mensaje(remitente, destinatarios, asunto, cuerpo, adjuntos)
    try:
        enviado = servicio.users().messages().send(userId='me', body=mensaje).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail rechazó el envío: {e}") from e
    log.info("Correo enviado, id=%s", enviado['id'])
    return enviado['id']
