"""
Arma y manda el reporte diario de calidad del aire.

Descarga los 3 PDF del dashboard en producción, los fusiona en uno solo, deja
una copia en Descargas y lo manda por correo. Es lo que dispara el DAG de
Airflow todos los días; también se puede correr a mano para probar:
python -m numeralia.notificaciones.reporte_diario
    
"""

from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import gspread

from numeralia.config import Config, cargar_dotenv
from numeralia.ingesta.auth import autenticar
from numeralia.notificaciones.dashboard_pdf import descargar_pdfs_dashboard, fusionar_pdfs
from numeralia.notificaciones.gmail import enviar_correo
from numeralia.transformacion.ias_nom import fecha_acumulada

log = logging.getLogger(__name__)

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
    sello = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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
    return (fecha_acumulada(spreadsheet, fecha_corte.year, fecha_corte)
            and fecha_acumulada(spreadsheet, anio_previo, fecha_corte_previa))


def generar_reporte_diario(config: Config, carpeta_temporal: Path) -> Path:
    """Descarga los 3 PDF y los fusiona. Devuelve la ruta del PDF combinado."""
    rutas = descargar_pdfs_dashboard(config.url_dashboard_reporte, carpeta_temporal)
    destino = Path(config.carpeta_descargas) / _nombre_reporte(_fecha_corte())
    return fusionar_pdfs(rutas, destino)


def enviar_reporte_diario(config: Config, ruta_token_gmail: Path) -> Path | None:
    """
    Genera el PDF combinado y lo manda por correo. Devuelve la ruta del PDF,
    o None si el reporte de esa fecha de corte ya se había mandado antes (el
    DAG en el servidor y una corrida a mano el mismo día no se pisan).
    """
    fecha_corte = _fecha_corte()
    gc = autenticar()
    spreadsheet = gc.open_by_url(config.url_destino)

    if _ya_enviado(spreadsheet, fecha_corte.date()):
        log.info("El reporte del %s ya se había enviado antes; no se manda "
                 "de nuevo.", fecha_corte.date())
        return None

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
    return ruta_pdf


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    cargar_dotenv()
    _config = Config.desde_env()
    _raiz = Path(__file__).resolve().parents[3]
    _ruta = enviar_reporte_diario(_config, _raiz / 'token_gmail.json')
    if _ruta is None:
        print("No se mandó nada: el reporte de hoy ya se había enviado antes.")
    else:
        print(f"Reporte enviado. Copia guardada en: {_ruta}")
