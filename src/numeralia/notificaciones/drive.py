"""
Sube el PDF combinado a Drive, en una carpeta por mes ('10 Octubre',
'11 Noviembre'...) dentro de una carpeta raíz.

Usa el MISMO token OAuth2 que ya autentica el envío de correo (ver
numeralia.notificaciones.gmail) — token_gmail.json, generado con
scripts/autorizar_gmail.py —, ahora con el alcance de Drive agregado. No la
cuenta de servicio: las cuentas de servicio no tienen cuota de
almacenamiento propia y no pueden crear archivos nuevos en un Drive normal
(solo en Shared Drives), así que la carpeta de Drive tiene que quedar a
nombre de la misma persona que manda el correo.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from numeralia.notificaciones._oauth import ALCANCES

log = logging.getLogger(__name__)

_MESES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre',
    12: 'Diciembre',
}


def _nombre_carpeta_mes(fecha_corte: date) -> str:
    """'10 Octubre', con el mes siempre a dos dígitos ('01 Enero')."""
    return f"{fecha_corte.month:02d} {_MESES[fecha_corte.month]}"


def _credenciales(ruta_token: Path) -> Credentials:
    if not ruta_token.exists():
        raise FileNotFoundError(
            f"No existe {ruta_token}. Corre scripts/autorizar_gmail.py."
        )
    credenciales = Credentials.from_authorized_user_file(str(ruta_token), ALCANCES)
    if credenciales.expired and credenciales.refresh_token:
        credenciales.refresh(Request())
        ruta_token.write_text(credenciales.to_json())
    return credenciales


def _buscar_o_crear_carpeta(servicio, nombre: str, carpeta_padre_id: str) -> str:
    """Devuelve el id de la subcarpeta `nombre` dentro de `carpeta_padre_id`, creándola si no existe."""
    consulta = (
        f"name = '{nombre}' and '{carpeta_padre_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    resultado = servicio.files().list(q=consulta, fields='files(id, name)').execute()
    encontradas = resultado.get('files', [])
    if encontradas:
        return encontradas[0]['id']

    log.info("Carpeta '%s' no existía en Drive; se crea.", nombre)
    carpeta = servicio.files().create(
        body={
            'name': nombre,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [carpeta_padre_id],
        },
        fields='id',
    ).execute()
    return carpeta['id']


def subir_reporte(ruta_pdf: Path, carpeta_raiz_id: str, fecha_corte: date,
                  ruta_token: Path) -> str:
    """
    Sube `ruta_pdf` a la carpeta del mes de `fecha_corte` dentro de
    `carpeta_raiz_id` (creando esa carpeta de mes si hace falta). Devuelve
    el link para ver el archivo en Drive.
    """
    credenciales = _credenciales(ruta_token)
    servicio = build('drive', 'v3', credentials=credenciales)

    carpeta_mes_id = _buscar_o_crear_carpeta(
        servicio, _nombre_carpeta_mes(fecha_corte), carpeta_raiz_id)

    try:
        archivo = servicio.files().create(
            body={'name': ruta_pdf.name, 'parents': [carpeta_mes_id]},
            media_body=MediaFileUpload(str(ruta_pdf), mimetype='application/pdf'),
            fields='id, webViewLink',
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Drive rechazó la subida: {e}") from e

    log.info("Subido a Drive: %s", archivo.get('webViewLink'))
    return archivo.get('webViewLink', '')
