"""
Descarga los 3 PDF que produce el dashboard en vivo y los fusiona en uno solo.

Dos de esos PDF (Episodios, Alertas) los arma el servidor con fpdf2; el
tercero (Reporte_Calidad_del_Aire) lo arma el propio navegador con
html2canvas + jsPDF, fotografiando el DOM (ver assets/dashboard.js). No hay
una versión de ese tercero en Python puro, así que en vez de reimplementar
esa lógica aquí, un navegador headless hace exactamente lo que haría una
persona: entra al dashboard en producción, da clic en los tres botones y
recoge lo que el navegador descarga. Así el PDF que se manda por correo es
siempre el mismo que vería alguien que entrara a mano.
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfWriter

log = logging.getLogger(__name__)

_TIEMPO_CARGA_MS = 60_000
_TIEMPO_DESCARGA_MS = 60_000
# Tras 'networkidle' el mapa y las gráficas (Plotly/ECharts) todavía tardan
# en terminar de pintarse; sin esta espera el primer botón a veces
# fotografía el mapa vacío.
_ESPERA_RENDER_MS = 5_000

# En este orden se combinan al final: primero el reporte general del
# dashboard, luego episodios, luego alertas y emergencias.
_BOTONES_EN_ORDEN = (
    'btn-pdf-dashboard',   # Reporte_Calidad_del_Aire_<fecha>.pdf
    'btn-pdf-episodios',   # Episodios.pdf
    'btn-pdf-alertas',     # Alertas_y_Emergencias_2026.pdf
)


def descargar_pdfs_dashboard(url: str, carpeta_destino: Path) -> list[Path]:
    """
    Abre `url` en un Chromium headless, da clic en los tres botones de
    descarga EN ORDEN y devuelve las rutas de los PDF descargados, en ese
    mismo orden.
    """
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    rutas: list[Path] = []

    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        # ignore_https_errors: el dominio de prueba corre en un puerto no
        # estándar (8443); si el certificado no encaja con el host, que no
        # tumbe la descarga por eso.
        contexto = navegador.new_context(ignore_https_errors=True)
        pagina = contexto.new_page()
        try:
            pagina.goto(url, wait_until='networkidle', timeout=_TIEMPO_CARGA_MS)
            pagina.wait_for_timeout(_ESPERA_RENDER_MS)

            for boton_id in _BOTONES_EN_ORDEN:
                with pagina.expect_download(timeout=_TIEMPO_DESCARGA_MS) as info_descarga:
                    pagina.click(f'#{boton_id}')
                descarga = info_descarga.value
                ruta = carpeta_destino / descarga.suggested_filename
                descarga.save_as(ruta)
                rutas.append(ruta)
                log.info("Descargado %s", ruta.name)
        finally:
            navegador.close()

    return rutas


def fusionar_pdfs(rutas: list[Path], destino: Path) -> Path:
    """Concatena los PDF de `rutas`, en ese orden, en un solo archivo."""
    escritor = PdfWriter()
    for ruta in rutas:
        escritor.append(str(ruta))
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, 'wb') as f:
        escritor.write(f)
    return destino
