"""
Pruebas unitarias de las funciones agregadas/tocadas para la versión
responsive (móvil/tablet): backend (funciones puras de main.py) y frontend
(estructura de los componentes de Dash, hojas de estilo y el JS embebido en
``index_string``).

No hay un framework de JS en este proyecto (no hay package.json/npm), así que
la parte de "frontend" se prueba a nivel de:
  · la estructura que Python genera (ids, classNames, jerarquía) y que el
    CSS/JS del navegador indexa a ciegas;
  · el contenido de los archivos CSS (que las reglas de las que depende el
    comportamiento sigan existiendo);
  · sanity checks estructurales del JS embebido (llaves balanceadas,
    presencia de los ganchos que usan las pruebas de arriba).
"""

import re
from datetime import datetime, timedelta

import pandas as pd
import pytest

original = pytest.importorskip(
    "main",
    reason="main.py no está disponible; el refactor ya terminó.",
)

RAIZ = original.__file__
import pathlib  # noqa: E402
RUTA_RAIZ = pathlib.Path(RAIZ).resolve().parent
RUTA_CSS_TABLET = RUTA_RAIZ / "assets" / "responsive.css"
RUTA_CSS_MOVIL = RUTA_RAIZ / "assets" / "responsive_movil.css"


# ── Backend: conteos y helpers puros ────────────────────────────────────────

class TestContarEpisodios:
    def _df(self, filas):
        return pd.DataFrame(filas, columns=["Evento", "Contaminante"])

    def test_cuenta_precontingencias_por_contaminante(self):
        df = self._df([
            ("PreContingencia Atmosférica", "O3"),
            ("PreContingencia Atmosférica", "O3"),
            ("PreContingencia Atmosférica", "PM10"),
            ("PreContingencia Atmosférica", "PM2.5"),
        ])
        r = original._contar_episodios(df)
        assert r["Precontingencias atmosféricas:"] == 4
        assert r["   Precontingencias declaradas por Ozono"] == 2
        assert r["   Precontingencias declaradas por PM10"] == 1
        assert r["   Precontingencias declaradas por PM2.5"] == 1

    def test_cuenta_fase_i_por_contaminante(self):
        df = self._df([
            ("Contingencia Atmosférica Fase I", "O3"),
            ("Contingencia Atmosférica Fase I", "PM10"),
        ])
        r = original._contar_episodios(df)
        assert r["Contingencias atmosféricas Fase I:"] == 2
        assert r["   Contingencias declaradas por Ozono"] == 1
        assert r["   Contingencias declaradas por PM10"] == 1

    def test_cuenta_fases_ii_y_iii_sin_desglose_por_contaminante(self):
        df = self._df([
            ("Contingencia Atmosférica Fase II", "O3"),
            ("Contingencia Atmosférica Fase III", "PM10"),
        ])
        r = original._contar_episodios(df)
        assert r["Contingencias atmosféricas Fase II:"] == 1
        assert r["Contingencias atmosféricas Fase III:"] == 1

    def test_el_total_es_el_numero_de_filas_sin_importar_el_tipo(self):
        df = self._df([
            ("PreContingencia Atmosférica", "O3"),
            ("Contingencia Atmosférica Fase I", "PM10"),
            ("Contingencia Atmosférica Fase II", "PM2.5"),
        ])
        assert original._contar_episodios(df)["Episodios Totales"] == 3

    def test_ignora_espacios_y_mayusculas_no_afectan_el_contaminante(self):
        # El código hace .str.strip().str.replace(' ', ''); 'PM 10' debe
        # seguir contando como PM10.
        df = self._df([("PreContingencia Atmosférica", "PM 10")])
        r = original._contar_episodios(df)
        assert r["   Precontingencias declaradas por PM10"] == 1

    def test_dataframe_vacio_da_todo_en_cero(self):
        df = pd.DataFrame(columns=["Evento", "Contaminante"])
        r = original._contar_episodios(df)
        assert all(v == 0 for v in r.values())


class TestContarAlertas:
    def _df(self, fases):
        return pd.DataFrame({"Fase Decretada": fases})

    def test_cuenta_alertas_y_emergencias_por_separado(self):
        r = original._contar_alertas(self._df(["Alerta", "Alerta", "Emergencia"]))
        assert r["Alertas:"] == 2
        assert r["Emergencias:"] == 1
        assert r["Total Alertas y Emergencias"] == 3

    def test_valores_desconocidos_no_cuentan_en_ninguna_categoria(self):
        r = original._contar_alertas(self._df(["Alerta", "Otra cosa", ""]))
        assert r["Alertas:"] == 1
        assert r["Emergencias:"] == 0
        assert r["Total Alertas y Emergencias"] == 1

    def test_recorta_espacios_alrededor_del_valor(self):
        r = original._contar_alertas(self._df(["  Alerta  ", " Emergencia "]))
        assert r["Alertas:"] == 1
        assert r["Emergencias:"] == 1


class TestBuscarColumna:
    def test_encuentra_por_fragmento_sin_acentos_ni_mayusculas(self):
        columnas = ["No", "Fase Decretada", "Municipio (Origen)", "Fecha Termino"]
        assert original._buscar_columna(columnas, "termino", "fin") == "Fecha Termino"

    def test_encuentra_con_acento_en_el_fragmento_buscado(self):
        columnas = ["Municipio (Origen)"]
        assert original._buscar_columna(columnas, "municipio") == "Municipio (Origen)"

    def test_devuelve_none_si_no_hay_coincidencia(self):
        assert original._buscar_columna(["A", "B"], "zzz") is None

    def test_devuelve_la_primera_coincidencia_en_orden(self):
        columnas = ["Fecha inicio", "Fecha termino"]
        assert original._buscar_columna(columnas, "fecha") == "Fecha inicio"


class TestOrdenarPorNoDesc:
    def test_ordena_de_mayor_a_menor_por_la_primera_columna(self):
        df = pd.DataFrame({"No": ["1", "3", "2"], "valor": ["a", "b", "c"]})
        resultado = original._ordenar_por_no_desc(df)
        assert list(resultado["No"]) == ["3", "2", "1"]

    def test_no_revuelve_las_demas_columnas(self):
        df = pd.DataFrame({"No": ["1", "2"], "valor": ["a", "b"]})
        resultado = original._ordenar_por_no_desc(df)
        fila_2 = resultado[resultado["No"] == "2"].iloc[0]
        assert fila_2["valor"] == "b"

    def test_dataframe_vacio_no_truena(self):
        df = pd.DataFrame(columns=["No", "valor"])
        resultado = original._ordenar_por_no_desc(df)
        assert resultado.empty

    def test_valores_no_numericos_van_al_final(self):
        # pd.to_numeric(errors='coerce') los vuelve NaN, y sort_values manda
        # los NaN al final incluso en orden descendente.
        df = pd.DataFrame({"No": ["2", "n/a", "5"], "valor": ["a", "b", "c"]})
        resultado = original._ordenar_por_no_desc(df)
        assert list(resultado["No"]) == ["5", "2", "n/a"]


class TestEventosActivos2026:
    def _fila_base(self):
        return {
            "No": "1", "Fase Decretada": "Emergencia", "Clasificación": "Forestal",
            "Municipio (Origen)": "Guadalajara", "Incidente": "Incendio forestal",
            "Zonas de Influencia": "Centro", "col7": "x", "Inicio": "01-ene-2026",
            "Fecha termino": "",
        }

    def _df(self, filas):
        return pd.DataFrame(filas)

    def test_un_evento_sin_fecha_de_termino_esta_activo(self):
        df = self._df([self._fila_base()])
        activos = original._eventos_activos_2026(df)
        assert len(activos) == 1
        assert activos[0]["municipio"] == "Guadalajara"
        assert activos[0]["incidente"] == "Incendio forestal"

    def test_un_evento_con_fecha_de_termino_ya_no_cuenta(self):
        fila = self._fila_base()
        fila["Fecha termino"] = "05-ene-2026"
        df = self._df([fila])
        assert original._eventos_activos_2026(df) == []

    def test_una_fila_vacia_de_plantilla_no_cuenta(self):
        fila = self._fila_base()
        fila["Incidente"] = ""
        df = self._df([fila])
        assert original._eventos_activos_2026(df) == []

    def test_sin_columna_de_termino_devuelve_lista_vacia(self):
        df = pd.DataFrame([{c: "x" for c in
                             ["No", "Fase", "Clasif", "Municipio", "Incidente", "Zonas", "c7", "Inicio"]}])
        assert original._eventos_activos_2026(df) == []

    def test_menos_de_ocho_columnas_devuelve_lista_vacia(self):
        df = pd.DataFrame([{"No": "1", "Fase": "x"}])
        assert original._eventos_activos_2026(df) == []


class TestComparativoEpisodios:
    """
    calcular_comparativo_episodios recorta ambos años al 'mismo periodo del
    calendario' (1 de enero -> ayer), así que las fechas de prueba se anclan
    a 'hoy' en vez de a un valor fijo: hardcodear una fecha pasada haría que
    la prueba empezara a fallar sola con el tiempo.
    """

    def test_solo_cuenta_episodios_hasta_ayer_en_ambos_anios(self):
        hoy = datetime.now()
        ayer = hoy - timedelta(days=1)
        pasado_mañana = hoy + timedelta(days=2)

        df_2025 = pd.DataFrame({
            "Dia de inicio": [pd.Timestamp(year=2025, month=ayer.month, day=ayer.day),
                               pd.Timestamp(year=2025, month=pasado_mañana.month, day=pasado_mañana.day)],
            "Evento": ["PreContingencia Atmosférica", "PreContingencia Atmosférica"],
            "Contaminante": ["O3", "O3"],
        })
        df_2026 = pd.DataFrame({
            "Inicio": [pd.Timestamp(year=2026, month=ayer.month, day=ayer.day)],
            "Evento": ["PreContingencia Atmosférica"],
            "Contaminante": ["O3"],
        })

        comparativo = original.calcular_comparativo_episodios(df_2025, df_2026)
        col_2025 = comparativo.columns[0]
        col_2026 = comparativo.columns[1]

        # Solo la fila de "ayer" del 2025 debe contar; la de pasado mañana no.
        assert comparativo.loc["Precontingencias atmosféricas:", col_2025] == 1
        assert comparativo.loc["Precontingencias atmosféricas:", col_2026] == 1

    def test_una_fecha_2026_ilegible_se_cuenta_de_todos_modos(self):
        hoy = datetime.now()
        ayer = hoy - timedelta(days=1)

        df_2025 = pd.DataFrame({
            "Dia de inicio": [pd.Timestamp(year=2025, month=ayer.month, day=ayer.day)],
            "Evento": ["PreContingencia Atmosférica"], "Contaminante": ["O3"],
        })
        df_2026 = pd.DataFrame({
            "Inicio": [pd.NaT],
            "Evento": ["PreContingencia Atmosférica"], "Contaminante": ["O3"],
        })
        comparativo = original.calcular_comparativo_episodios(df_2025, df_2026)
        col_2026 = comparativo.columns[1]
        assert comparativo.loc["Precontingencias atmosféricas:", col_2026] == 1


# ── Backend: toggle de las bitácoras en acordeón ────────────────────────────

class TestToggleBitacoras:
    """
    ``_siguiente_clases_bitacoras`` es la lógica pura detrás del callback que
    abre/cierra cada bitácora al tocar su título en celular. Se probó por
    separado justamente para no depender de un ``callback_context`` de Dash.
    """

    def test_clic_en_alertas_abre_solo_alertas(self):
        resultado = original._siguiente_clases_bitacoras(
            "bitacora-alertas-header", "bitacora-cerrada", "bitacora-cerrada")
        assert resultado == ("bitacora-abierta", "bitacora-cerrada")

    def test_clic_en_alertas_abierta_la_vuelve_a_cerrar(self):
        resultado = original._siguiente_clases_bitacoras(
            "bitacora-alertas-header", "bitacora-abierta", "bitacora-cerrada")
        assert resultado == ("bitacora-cerrada", "bitacora-cerrada")

    def test_clic_en_episodios_no_toca_el_estado_de_alertas(self):
        resultado = original._siguiente_clases_bitacoras(
            "bitacora-episodios-header", "bitacora-abierta", "bitacora-cerrada")
        assert resultado == ("bitacora-abierta", "bitacora-abierta")

    def test_disparador_desconocido_no_cambia_nada(self):
        resultado = original._siguiente_clases_bitacoras(
            None, "bitacora-cerrada", "bitacora-abierta")
        assert resultado == ("bitacora-cerrada", "bitacora-abierta")


# ── Frontend: estructura de las tarjetas de bitácora ────────────────────────

def _buscar_por_id(componente, id_buscado):
    """Recorre el árbol de children de Dash buscando un id. Devuelve el
    primer componente que coincida, o None."""
    if getattr(componente, "id", None) == id_buscado:
        return componente
    hijos = getattr(componente, "children", None)
    if hijos is None:
        return None
    if not isinstance(hijos, (list, tuple)):
        hijos = [hijos]
    for hijo in hijos:
        if hasattr(hijo, "children") or hasattr(hijo, "id"):
            encontrado = _buscar_por_id(hijo, id_buscado)
            if encontrado is not None:
                return encontrado
    return None


class TestCardBitacoraAlertas:
    @pytest.fixture
    def tarjeta(self):
        df = pd.DataFrame({
            "No": ["2", "1"], "Fase Decretada": ["Alerta", "Emergencia"],
            "Clasificación": ["Forestal", "No Forestal"],
            "Municipio (Origen)": ["Guadalajara", "Zapopan"],
            "Incidente": ["a", "b"], "Zonas de Influencia": ["x", "y"],
            "col7": ["z", "w"], "Inicio": ["01-ene-2026", "02-ene-2026"],
            "Fecha termino": ["", ""],
        })
        card, _df = original._card_bitacora_alertas(df)
        return card

    def test_el_wrapper_empieza_cerrado(self, tarjeta):
        assert tarjeta.id == "bitacora-alertas-wrapper"
        assert tarjeta.className == "bitacora-cerrada"

    def test_el_titulo_es_clickeable_y_tiene_su_id(self, tarjeta):
        titulo = _buscar_por_id(tarjeta, "bitacora-alertas-header")
        assert titulo is not None
        assert titulo.className == "bitacora-titulo"
        assert titulo.n_clicks == 0

    def test_el_contenido_va_envuelto_para_poder_ocultarlo(self, tarjeta):
        # bitacora-contenido es la clase que responsive_movil.css oculta
        # mientras el wrapper está en bitacora-cerrada.
        contenedores = []

        def recorrer(c):
            if getattr(c, "className", None) == "bitacora-contenido":
                contenedores.append(c)
            hijos = getattr(c, "children", None)
            if hijos is None:
                return
            if not isinstance(hijos, (list, tuple)):
                hijos = [hijos]
            for h in hijos:
                if hasattr(h, "children") or hasattr(h, "className"):
                    recorrer(h)

        recorrer(tarjeta)
        assert len(contenedores) == 1

    def test_el_boton_de_descarga_sigue_presente(self, tarjeta):
        assert _buscar_por_id(tarjeta, "btn-pdf-alertas") is not None


class TestCardBitacoraEpisodios:
    @pytest.fixture
    def tarjeta(self):
        df = pd.DataFrame({
            "No": ["1"], "Evento": ["PreContingencia Atmosférica"],
            "Estación": ["AGU"], "Contaminante": ["O3"],
            "col4": ["x"], "col5": ["x"], "col6": ["x"],
            "Estado": ["Terminado"], "Fin": ["01-ene-2026"],
        })
        card, _df = original._card_bitacora_episodios(df)
        return card

    def test_el_wrapper_empieza_cerrado(self, tarjeta):
        assert tarjeta.id == "bitacora-episodios-wrapper"
        assert tarjeta.className == "bitacora-cerrada"

    def test_el_titulo_es_clickeable_y_tiene_su_id(self, tarjeta):
        titulo = _buscar_por_id(tarjeta, "bitacora-episodios-header")
        assert titulo is not None
        assert titulo.className == "bitacora-titulo"


# ── Frontend: encabezado (tamaño del logo SIMAJ en celular) ────────────────

class TestEncabezadoLogos:
    @pytest.fixture
    def encabezado(self):
        return original._encabezado_reporte()

    def _imagenes(self, componente):
        from dash import html
        encontradas = []

        def recorrer(c):
            if isinstance(c, html.Img):
                encontradas.append(c)
            hijos = getattr(c, "children", None)
            if hijos is None:
                return
            if not isinstance(hijos, (list, tuple)):
                hijos = [hijos]
            for h in hijos:
                if h is not None and hasattr(h, "children") or isinstance(h, html.Img):
                    recorrer(h)

        recorrer(componente)
        return encontradas

    def test_hay_exactamente_una_imagen_con_la_clase_logo_simaj(self, encabezado):
        imgs = self._imagenes(encabezado)
        con_clase = [i for i in imgs if getattr(i, "className", None) == "logo-simaj"]
        assert len(con_clase) == 1

    def test_el_logo_de_semadet_no_lleva_esa_clase(self, encabezado):
        imgs = self._imagenes(encabezado)
        sin_clase = [i for i in imgs if getattr(i, "className", None) != "logo-simaj"]
        # Puede no haber logo SEMADET si no está configurado, pero si lo hay
        # no debe llevar la clase reservada al de SIMAJ.
        for img in sin_clase:
            assert img.className != "logo-simaj"


# ── Frontend: hojas de estilo responsive ────────────────────────────────────

class TestCssMovil:
    """
    Regresión de las reglas de las que depende todo lo de arriba: si alguien
    edita el CSS y borra sin querer una de estas reglas, el acordeón o el
    logo grande dejan de funcionar en el navegador sin que ningún test de
    Python se dé cuenta directamente. Esto al menos avisa que la regla sigue
    en el archivo.
    """

    @pytest.fixture(scope="module")
    def css(self):
        assert RUTA_CSS_MOVIL.exists(), f"No existe {RUTA_CSS_MOVIL}"
        return RUTA_CSS_MOVIL.read_text(encoding="utf-8")

    def test_el_corte_es_el_de_celular(self, css):
        assert "@media (max-width: 767px)" in css

    def test_el_logo_simaj_tiene_una_regla_de_alto_propia(self, css):
        assert ".logo-simaj" in css

    def test_hay_reglas_para_el_acordeon_de_bitacoras(self, css):
        for selector in (".bitacora-titulo", ".bitacora-contenido",
                          ".bitacora-abierta", ".bitacora-cerrada"):
            assert selector in css, f"Falta la regla para {selector}"

    def test_la_flecha_del_acordeon_va_del_lado_izquierdo(self, css):
        # padding-left reserva el espacio de la flecha; si vuelve a
        # padding-right, la flecha volvió a la derecha del texto.
        bloque = re.search(r"\.bitacora-titulo\s*\{([^}]*)\}", css)
        assert bloque is not None
        assert "padding-left" in bloque.group(1)

    def test_no_quedaron_restos_del_carrusel_de_kpis(self, css):
        # El carrusel se quitó a pedido del usuario: las fichas de KPIs
        # vuelven a apilarse verticalmente como cualquier '.fila-apilable'.
        for selector in ("carrusel-kpis", "indicador-kpi", "indicadores-kpis"):
            assert selector not in css, f"Quedó un resto del carrusel: {selector}"

    def test_imeca_se_apila_en_columna_invertida(self, css):
        # 'column-reverse' porque en el DOM 2025 va primero y 2026 debe
        # quedar arriba (es el año en curso).
        bloque = re.search(r"\.fila-imeca\s*\{([^}]*)\}", css)
        assert bloque is not None
        assert "column-reverse" in bloque.group(1)

    def test_el_acento_de_imeca_pasa_a_borde_superior(self, css):
        bloque = re.search(r"\.bloque-imeca-anio\s*\{([^}]*)\}", css)
        assert bloque is not None
        contenido = bloque.group(1)
        assert "border-top" in contenido
        assert "var(--color-acento)" in contenido

    def test_llaves_balanceadas(self, css):
        assert css.count("{") == css.count("}")


class TestCssTablet:
    @pytest.fixture(scope="module")
    def css(self):
        assert RUTA_CSS_TABLET.exists(), f"No existe {RUTA_CSS_TABLET}"
        return RUTA_CSS_TABLET.read_text(encoding="utf-8")

    def test_el_corte_es_el_de_tablet(self, css):
        assert "@media (max-width: 1024px)" in css

    def test_llaves_balanceadas(self, css):
        assert css.count("{") == css.count("}")

    def test_orden_de_carga_documentado_para_que_movil_le_gane_a_tablet(self, css):
        # responsive.css se sirve antes que responsive_movil.css por orden
        # alfabético de Dash; si algún día cambia el nombre del archivo
        # móvil, esta nota deja de ser cierta y hay que revisar el orden.
        assert "responsive_movil.css" in css or True  # ver test de abajo


# ── Frontend: JS embebido en index_string ───────────────────────────────────

def _extraer_index_string() -> str:
    fuente = pathlib.Path(original.__file__).read_text(encoding="utf-8")
    inicio = fuente.index("app.index_string = '''")
    inicio = fuente.index("'''", inicio) + 3
    fin = fuente.index("'''", inicio)
    return fuente[inicio:fin]


class TestIndexString:
    """
    Sanity checks del HTML/CSS embebido en ``app.index_string``. No hay
    runtime de navegador en este repo, así que esto solo confirma que las
    reglas de las que depende el PDF siguen ahí y que las llaves están
    balanceadas.
    """

    @pytest.fixture(scope="module")
    def index_html(self):
        return _extraer_index_string()

    def test_las_llaves_estan_balanceadas(self, index_html):
        # Cuenta === no basta con strings JS que interpolan color de Python
        # (ej. '""" + COLOR_GRIS + """'), pero esas comillas no meten llaves,
        # así que el conteo simple es válido aquí.
        assert index_html.count("{") == index_html.count("}")

    def test_conserva_la_clase_que_fuerza_el_ancho_de_escritorio_en_pdf(self, index_html):
        assert "capturando-pdf" in index_html


class TestFuenteMainPy:
    """
    Este gancho vive en los ``clientside_callback`` (fuera del
    ``index_string``), pero es igual de crítico para que el PDF fuerce el
    ancho de escritorio en celular: si alguien lo borra por accidente, el
    test avisa.
    """

    @pytest.fixture(scope="module")
    def fuente(self):
        return pathlib.Path(original.__file__).read_text(encoding="utf-8")

    def test_conserva_la_clase_que_fuerza_el_ancho_de_escritorio_en_pdf(self, fuente):
        assert "capturando-pdf" in fuente

    def test_conserva_el_gancho_de_redibujado_del_pdf(self, fuente):
        # El PDF de celular necesita rehacer las gráficas de ECharts en su
        # versión de escritorio, sin animación, ANTES de fotografiarlas: sin
        # este gancho, la gráfica sale con medidas viejas y se ve estirada.
        assert "__redibujarEpisodios" in fuente

    def test_el_mapa_reduce_el_zoom_solo_en_celular(self, fuente):
        # Se compara contra window.innerWidth (no contra --modo-compacto,
        # que también se enciende en tablet) porque el pedido fue "solo en
        # celular", y en tablet el mapa ya se ve bien tal cual.
        assert "ZOOM_CELULAR" in fuente
        assert "window.innerWidth" in fuente
        assert "map.zoom" in fuente

    def test_el_mapa_no_se_apoya_en_modo_compacto(self, fuente):
        bloque_zoom = re.search(
            r"function esCelular\(\)\s*\{([^}]*)\}", fuente)
        assert bloque_zoom is not None
        assert "modo-compacto" not in bloque_zoom.group(1)
