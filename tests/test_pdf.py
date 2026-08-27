"""
Tests de la generación de PDF de bitácoras.

Estos tests no existían: el código vivía anidado dentro de ``build_dash_app``
y no había forma de llamarlo sin construir la aplicación entera.
"""

import os
from pathlib import Path

import pandas as pd
import pytest
from fpdf import FPDF

from numeralia.reporte.pdf import (
    ANCHO_MAX_COLUMNA,
    DescargaPDF,
    _recortar_al_ancho,
    _sin_acentos_latin1,
    anchos_proporcionales,
    generar_pdf_tabla,
)
from numeralia.reporte.tema import COLOR_GRIS, COLOR_GRIS_MUTE, hex_a_rgb


@pytest.fixture
def bitacora() -> pd.DataFrame:
    return pd.DataFrame({
        "No": [1, 2, 46],
        "Clasificación": ["Alerta", "Emergencia", "Alerta"],
        "Municipio (Origen)": ["Guadalajara", "Zapopan", "Tlaquepaque"],
        "Incidente": ["Incendio forestal en la zona alta del bosque", "Quema", "Humo"],
    })


@pytest.fixture
def pdf_vacio() -> FPDF:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    return pdf


class TestLatin1:
    def test_conserva_lo_que_cabe(self):
        assert _sin_acentos_latin1("Precontingencias atmosféricas") == \
            "Precontingencias atmosféricas"

    def test_sustituye_lo_que_no_cabe(self):
        # fpdf2 con fuentes básicas solo digiere latin-1: un carácter suelto
        # fuera de ese juego tumbaba el PDF entero.
        salida = _sin_acentos_latin1("PM2.5 → 25 µg ▲")
        salida.encode("latin-1")   # no debe lanzar

    def test_los_acentos_del_espanol_sobreviven(self):
        for palabra in ("Águilas", "Tlaquepaque", "atmosférica", "Ozono"):
            assert _sin_acentos_latin1(palabra) == palabra


class TestRecorte:
    def test_recorta_por_ancho_real_no_por_caracteres(self, pdf_vacio):
        pdf_vacio.set_font("Helvetica", "", 6)
        largo = "Incendio forestal en la zona alta del bosque de La Primavera"
        recortado = _recortar_al_ancho(pdf_vacio, largo, 20)
        assert pdf_vacio.get_string_width(recortado) <= 20

    def test_un_texto_corto_no_se_toca(self, pdf_vacio):
        pdf_vacio.set_font("Helvetica", "", 6)
        assert _recortar_al_ancho(pdf_vacio, "46", 30) == "46"

    def test_nunca_deja_la_celda_vacia(self, pdf_vacio):
        # Regresión: con un ancho absurdo, recortar hasta el final dejaría la
        # celda en blanco. Debe quedar al menos un carácter.
        pdf_vacio.set_font("Helvetica", "", 6)
        assert len(_recortar_al_ancho(pdf_vacio, "Guadalajara", 0.1)) >= 1

    def test_acepta_valores_no_texto(self, pdf_vacio):
        pdf_vacio.set_font("Helvetica", "", 6)
        assert _recortar_al_ancho(pdf_vacio, 46, 30) == "46"


class TestAnchos:
    def test_devuelve_un_ancho_por_columna(self, pdf_vacio, bitacora):
        assert len(anchos_proporcionales(pdf_vacio, bitacora)) == len(bitacora.columns)

    def test_ocupan_la_pagina_sin_desbordarla(self, pdf_vacio, bitacora):
        anchos = anchos_proporcionales(pdf_vacio, bitacora)
        assert sum(anchos) == pytest.approx(pdf_vacio.w - 20, abs=0.5)

    def test_ninguna_columna_acapara_cuando_no_cabe_todo(self, pdf_vacio):
        # El tope limita lo que una columna PIDE, no lo que acaba midiendo:
        # si sobra página, todas crecen en proporción para llenarla. El tope
        # importa cuando la demanda supera el ancho disponible.
        df = pd.DataFrame({f"col{i}": ["texto muy largo " * 8] for i in range(12)})
        for a in anchos_proporcionales(pdf_vacio, df):
            assert a <= ANCHO_MAX_COLUMNA + 0.001

    def test_con_pocas_columnas_se_reparte_toda_la_pagina(self, pdf_vacio, bitacora):
        anchos = anchos_proporcionales(pdf_vacio, bitacora)
        assert sum(anchos) == pytest.approx(pdf_vacio.w - 20, abs=0.5)
        assert all(a > 0 for a in anchos)

    def test_una_columna_corta_conserva_su_minimo(self, pdf_vacio):
        # Regresión: la columna 'No' recibía tan poco espacio que el recorte
        # le comía dígitos y '46' salía como '4'.
        df = pd.DataFrame({
            "No": [46],
            "Incidente": ["x" * 300],
            "Municipio": ["y" * 300],
            "Observaciones": ["z" * 300],
        })
        anchos = anchos_proporcionales(pdf_vacio, df)
        pdf_vacio.set_font("Helvetica", "", 6)
        assert _recortar_al_ancho(pdf_vacio, "46", anchos[0], holgura=2) == "46"

    def test_muchas_columnas_anchas_no_desbordan(self, pdf_vacio):
        df = pd.DataFrame({f"col{i}": ["texto largo " * 5] for i in range(20)})
        anchos = anchos_proporcionales(pdf_vacio, df)
        assert sum(anchos) <= pdf_vacio.w - 20 + 0.5

    def test_una_sola_columna(self, pdf_vacio):
        anchos = anchos_proporcionales(pdf_vacio, pd.DataFrame({"A": ["x"]}))
        assert len(anchos) == 1


class TestGeneracion:
    def test_produce_un_pdf_legible(self, bitacora, tmp_path):
        ruta = generar_pdf_tabla(bitacora, "Alertas 2026", "Subtítulo de prueba")
        try:
            datos = Path(ruta).read_bytes()
            assert datos.startswith(b"%PDF")
            assert len(datos) > 500
        finally:
            os.unlink(ruta)

    def test_funciona_sin_subtitulo(self, bitacora):
        ruta = generar_pdf_tabla(bitacora, "Solo título")
        try:
            assert Path(ruta).read_bytes().startswith(b"%PDF")
        finally:
            os.unlink(ruta)

    def test_una_tabla_larga_pagina(self, bitacora):
        # Debe repetir encabezados y no reventar al saltar de página.
        larga = pd.concat([bitacora] * 60, ignore_index=True)
        ruta = generar_pdf_tabla(larga, "Bitácora larga")
        try:
            assert Path(ruta).stat().st_size > 3000
        finally:
            os.unlink(ruta)

    def test_tolera_caracteres_fuera_de_latin1(self):
        df = pd.DataFrame({"Contaminante": ["PM2.5 ▲"], "Nota": ["25 µg/m³ →"]})
        ruta = generar_pdf_tabla(df, "Con símbolos ▲")
        try:
            assert Path(ruta).read_bytes().startswith(b"%PDF")
        finally:
            os.unlink(ruta)

    @pytest.mark.parametrize("bicho", ["’", "—", "→", "▲", "🔥"])
    def test_no_truena_con_caracteres_de_word(self, bicho):
        # Regresión: medir el ancho de columna llamaba a get_string_width con
        # el texto SIN sanear, y eso codifica a latin-1 por dentro. Una
        # comilla curva pegada desde Word tumbaba la descarga entera.
        df = pd.DataFrame({f"Columna {bicho}": [f"Incendio {bicho} en la zona"]})
        ruta = generar_pdf_tabla(df, f"Titulo {bicho}", f"Subtitulo {bicho}")
        try:
            assert Path(ruta).read_bytes().startswith(b"%PDF")
        finally:
            os.unlink(ruta)

    def test_cada_llamada_da_un_archivo_distinto(self, bitacora):
        a = generar_pdf_tabla(bitacora, "A")
        b = generar_pdf_tabla(bitacora, "B")
        try:
            assert a != b
        finally:
            os.unlink(a)
            os.unlink(b)


class TestColoresDelTema:
    def test_hex_a_rgb(self):
        assert hex_a_rgb("#465055") == (70, 80, 85)
        assert hex_a_rgb("ffffff") == (255, 255, 255)

    def test_el_pdf_usa_los_colores_del_tema(self):
        # Regresión: el gris tenue iba escrito como (138, 144, 150) dentro del
        # PDF, así que cuando el tema cambió de tono el PDF se quedó atrás.
        assert hex_a_rgb(COLOR_GRIS) == (70, 80, 85)
        assert hex_a_rgb(COLOR_GRIS_MUTE) != (138, 144, 150)


class TestDescargaPDF:
    def test_es_inmutable(self, bitacora):
        d = DescargaPDF(bitacora, "t", "s", "a.pdf", "btn", "dl")
        with pytest.raises(Exception):
            d.titulo = "otro"

    def test_lleva_todo_lo_que_el_callback_necesita(self, bitacora):
        d = DescargaPDF(bitacora, "t", "s", "a.pdf", "btn", "dl")
        assert (d.archivo, d.boton_id, d.descarga_id) == ("a.pdf", "btn", "dl")
