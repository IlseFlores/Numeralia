"""
Arma y manda el reporte diario de calidad del aire.

Descarga los 3 PDF del dashboard en producción, los fusiona en uno solo, deja
una copia en Descargas y lo manda por correo. Es lo que dispara el DAG de
Airflow todos los días; también se puede correr a mano para probar:
python -m numeralia.notificaciones.reporte_diario
    
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import gspread
import requests
import urllib3

from numeralia.config import Config, cargar_dotenv
from numeralia.ingesta.auth import autenticar
from numeralia.notificaciones import drive as _drive
from numeralia.notificaciones.dashboard_pdf import descargar_pdfs_dashboard, fusionar_pdfs
from numeralia.notificaciones.gmail import enviar_correo
from numeralia.transformacion.ias_nom import fecha_acumulada

log = logging.getLogger(__name__)

# El dominio de prueba corre en un puerto no estándar (8443) con un
# certificado que no encaja con el host; igual que ignore_https_errors en
# dashboard_pdf.py, se ignora para esta sola revisión de texto.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# El DAG en el servidor y una corrida a mano en otra máquina no comparten
# disco, así que un archivo local no serviría para saber "ya se mandó hoy".
# Se registra en la misma hoja de cálculo que ya comparten ambos (por eso
# vive ahí y no en un archivo): quien mande primero deja la marca, y el que
# llegue después la ve y no reenvía.
HOJA_CONTROL_ENVIOS = "ReporteDiarioEnviado"


def _hoja_control_envios(spreadsheet):
    try:
        return spreadsheet.worksheet(HOJA_CONTROL_ENVIOS)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=HOJA_CONTROL_ENVIOS, rows=400, cols=2)
        ws.update(range_name="A1", values=[["Fecha de corte", "Enviado"]])
        return ws


def _ya_enviado(spreadsheet, fecha_corte: date) -> bool:
    filas = _hoja_control_envios(spreadsheet).get_all_records()
    objetivo = fecha_corte.strftime('%Y-%m-%d')
    return any(str(f.get("Fecha de corte")) == objetivo for f in filas)


def _marcar_enviado(spreadsheet, fecha_corte: date) -> None:
    # datetime.now() a secas toma la hora del sistema donde corre el proceso
    # (en el servidor, UTC) — con eso la columna "Enviado" quedaba 6 horas
    # adelantada de la hora real de Jalisco. Mismo huso que _fecha_corte().
    utc_menos_6 = timezone(timedelta(hours=-6))
    sello = datetime.now(utc_menos_6).strftime('%Y-%m-%d %H:%M:%S')
    _hoja_control_envios(spreadsheet).append_row(
        [fecha_corte.strftime('%Y-%m-%d'), sello])

_MESES = {
    1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio',
    7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre',
    12: 'diciembre',
}


def _fecha_corte() -> datetime:
    """
    El día que cubren los datos: el anterior al de hoy, en hora de Jalisco.
    Mismo criterio que usa el propio dashboard (ver _periodo_corte en
    main.py): los datos reflejan lo cerrado al día previo, no el de hoy.
    """
    utc_menos_6 = timezone(timedelta(hours=-6))
    return datetime.now(utc_menos_6) - timedelta(days=1)


def _nombre_reporte(fecha_corte: datetime) -> str:
    return (f"{fecha_corte.year}.{fecha_corte.month:02d}.{fecha_corte.day:02d} "
            "Reporte Diario CA.pdf")


def _cuerpo_correo(fecha_corte: datetime) -> str:
    return (
        "Buen día,\n\n"
        f"Adjunto el archivo correspondiente del Reporte diario al día "
        f"{fecha_corte.day} de {_MESES[fecha_corte.month]} de {fecha_corte.year} "
        "disponible en la página aire.jalisco.gob.mx en el menú de Reporte "
        "Diario.\n\n"
        "Quedo atenta a cualquier comentario u observación.\n\n"
        "Saludos."
    )


def datos_listos_para_enviar(config: Config) -> bool:
    """
    True cuando la actualización de la mañana ya terminó: cuando en la hoja
    'Acumuladas' ya quedó registrado el mismo día-mes de `fecha_corte`, tanto
    para el año en curso como para el anterior (el reporte compara ambos).

    Se usa como condición del sensor de Airflow en vez de una hora fija del
    reloj, porque a qué hora termina la actualización varía de un día a otro.
    """
    fecha_corte = _fecha_corte().date()
    anio_previo = fecha_corte.year - 1
    try:
        fecha_corte_previa = fecha_corte.replace(year=anio_previo)
    except ValueError:
        # 29 de febrero: el año anterior casi nunca es bisiesto también.
        fecha_corte_previa = fecha_corte.replace(year=anio_previo, day=28)

    gc = autenticar()
    spreadsheet = gc.open_by_url(config.url_destino)
    if not (fecha_acumulada(spreadsheet, fecha_corte.year, fecha_corte)
            and fecha_acumulada(spreadsheet, anio_previo, fecha_corte_previa)):
        return False

    # 'Acumuladas' se actualiza AL PRINCIPIO del pipeline de la mañana; el
    # dashboard en vivo (el que descarga_pdfs_dashboard va a fotografiar)
    # recién se refresca hasta que ese pipeline termina del todo y el
    # proceso se reinicia con los datos nuevos. Sin esta segunda revisión,
    # el sensor daba luz verde en esa ventana intermedia y el reporte salía
    # con los datos del día anterior aunque 'Acumuladas' ya dijera "listo".
    fecha_texto = (f"{fecha_corte.day} DE {_MESES[fecha_corte.month].upper()} "
                   f"DEL {fecha_corte.year}")
    return _dashboard_muestra_fecha(config.url_dashboard_reporte, fecha_texto)


def _dashboard_muestra_fecha(url: str, fecha_texto: str) -> bool:
    """
    True si el dashboard ya contiene la fecha de corte esperada, p.ej.
    '6 DE OCTUBRE DEL 2026'. Confirma que el PROCESO del dashboard ya se
    reinició con los datos de hoy.

    Dash no manda el layout ya armado en el HTML inicial —lo arma el
    navegador con JS a partir de un JSON que pide aparte—, así que la
    página normal no sirve para esto sin un navegador de por medio. El
    endpoint interno '_dash-layout' sí trae ese JSON directo del servidor,
    así que una petición HTTP simple basta, sin Playwright.
    """
    url_layout = url.rstrip('/') + '/_dash-layout'
    try:
        respuesta = requests.get(url_layout, timeout=20, verify=False)
        respuesta.raise_for_status()
    except requests.RequestException as e:
        log.info("No se pudo revisar la fecha del dashboard (%s); se "
                 "reintenta en el siguiente poke.", e)
        return False
    return fecha_texto in respuesta.text


def generar_reporte_diario(config: Config, carpeta_temporal: Path) -> Path:
    """Descarga los 3 PDF y los fusiona. Devuelve la ruta del PDF combinado."""
    rutas = descargar_pdfs_dashboard(config.url_dashboard_reporte, carpeta_temporal)
    destino = Path(config.carpeta_descargas) / _nombre_reporte(_fecha_corte())
    return fusionar_pdfs(rutas, destino)


def ruta_token_gmail(raiz: Path) -> Path:
    """
    Dónde está el token de Gmail/Drive.

    Si el .env trae ``GMAIL_TOKEN_JSON`` (el contenido de token_gmail.json
    en una sola línea), se escribe a un archivo temporal y se usa ese: así
    el contenedor del dashboard no necesita montar el archivo. Si no, se usa
    ``raiz/token_gmail.json`` como siempre.

    Se reescribe en cada llamada a propósito: gmail.py guarda ahí el token
    de acceso renovado, pero lo que vale es el refresh token del .env.
    """
    contenido = os.getenv('GMAIL_TOKEN_JSON', '').strip()
    if not contenido:
        return raiz / 'token_gmail.json'
    try:
        json.loads(contenido)
    except ValueError as e:
        raise ValueError(
            "GMAIL_TOKEN_JSON en el .env no es un JSON válido; pega el "
            "contenido de token_gmail.json en una sola línea.") from e
    ruta = Path(tempfile.gettempdir()) / 'numeralia_token_gmail.json'
    ruta.write_text(contenido, encoding='utf-8')
    try:
        ruta.chmod(0o600)
    except OSError:
        pass
    return ruta


def _fecha_larga(fecha: date) -> str:
    return f"{fecha.day} de {_MESES[fecha.month]} de {fecha.year}"


def enviar_reporte_diario_con_motivo(config: Config,
                                     ruta_token_gmail: Path) -> tuple[Path | None, str]:
    """
    Igual que :func:`enviar_reporte_diario`, pero además devuelve un texto
    para mostrarle a quien lo pidió (lo usa #notificacion en el dashboard):
    si se mandó, o por qué no.
    """
    fecha_corte = _fecha_corte()
    fecha = _fecha_larga(fecha_corte.date())
    gc = autenticar()
    spreadsheet = gc.open_by_url(config.url_destino)

    if _ya_enviado(spreadsheet, fecha_corte.date()):
        log.info("El reporte del %s ya se había enviado antes; no se manda "
                 "de nuevo.", fecha_corte.date())
        return None, (f"El reporte del {fecha} ya se había enviado; "
                      "no se mandó de nuevo.")

    if not datos_listos_para_enviar(config):
        log.info("Los datos del %s todavía no están listos (o el dashboard "
                 "no se ha actualizado); no se manda nada por ahora. "
                 "Vuelve a intentarlo más tarde.", fecha_corte.date())
        return None, (f"Los datos del {fecha} todavía no están en el "
                      "dashboard; no se mandó nada. Corre #actualizar y "
                      "vuelve a intentarlo.")

    ruta_pdf = _generar_y_enviar(config, ruta_token_gmail, fecha_corte, spreadsheet)
    total = len(config.destinatarios_reporte) + len(config.copia_reporte)
    return ruta_pdf, (f"Reporte del {fecha} enviado a {total} "
                      f"destinatario{'s' if total != 1 else ''}.")


def enviar_reporte_diario(config: Config, ruta_token_gmail: Path) -> Path | None:
    """
    Genera el PDF combinado y lo manda por correo. Devuelve la ruta del PDF,
    o None si no se mandó nada — ya sea porque ese reporte ya se había
    enviado antes (el DAG en el servidor y una corrida a mano el mismo día
    no se pisan), o porque los datos de hoy todavía no están listos.

    Esta misma revisión de "¿ya está listo?" la usa el sensor del DAG antes
    de llegar aquí, pero se repite aquí para que correrlo A MANO (por
    ejemplo python -m numeralia.notificaciones.reporte_diario) tenga la
    misma protección: sin esto, correrlo temprano —antes de que el
    dashboard termine de actualizarse— mandaría el reporte con los datos
    del día anterior, el mismo bug que ya pasó una vez con el envío
    automático.
    """
    ruta_pdf, _motivo = enviar_reporte_diario_con_motivo(config, ruta_token_gmail)
    return ruta_pdf


def _generar_y_enviar(config: Config, ruta_token_gmail: Path,
                      fecha_corte: datetime, spreadsheet) -> Path:
    """Arma el PDF, lo manda, marca la fecha y lo sube a Drive."""
    with tempfile.TemporaryDirectory(prefix='reporte_ca_') as carpeta_temporal:
        ruta_pdf = generar_reporte_diario(config, Path(carpeta_temporal))

        enviar_correo(
            remitente=config.remitente_reporte,
            destinatarios=config.destinatarios_reporte,
            asunto=(f"Reporte Diario de Calidad del Aire — "
                    f"{fecha_corte.day:02d}/{fecha_corte.month:02d}/{fecha_corte.year}"),
            cuerpo=_cuerpo_correo(fecha_corte),
            adjuntos=[ruta_pdf],
            ruta_token=ruta_token_gmail,
            copia=config.copia_reporte,
        )

    # Se marca DESPUÉS de mandarlo: si algo truena antes, la fecha no queda
    # marcada y el siguiente intento sí reenvía, en vez de darlo por bueno
    # sin estarlo (mismo criterio que _registrar_fechas_acumuladas).
    _marcar_enviado(spreadsheet, fecha_corte.date())

    if config.drive_carpeta_id:
        # Un tropiezo subiendo a Drive (permiso no compartido, cuota...) no
        # debe tirar todo lo de arriba: el correo ya salió, que es lo que
        # de verdad importa. Se deja constancia en el log y ya.
        try:
            _drive.subir_reporte(ruta_pdf, config.drive_carpeta_id,
                                 fecha_corte.date(), ruta_token_gmail)
        except Exception as e:
            log.warning("No se pudo subir el reporte a Drive: %s", e)

    return ruta_pdf


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    cargar_dotenv()
    _config = Config.desde_env()
    _raiz = Path(__file__).resolve().parents[3]
    _ruta = enviar_reporte_diario(_config, ruta_token_gmail(_raiz))
    if _ruta is None:
        print("No se mandó nada — revisa el mensaje de arriba para saber por qué "
              "(ya se había enviado, o los datos todavía no están listos).")
    else:
        print(f"Reporte enviado. Copia guardada en: {_ruta}")
