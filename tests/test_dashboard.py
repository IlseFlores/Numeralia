"""
Tests de la capa de reporte: estructura de los datos que se le mandan al
navegador y acoplamientos entre Python y el JavaScript del dashboard.

Los 327 tests del dominio cubren los números; nada cubría lo que sigue, que
es donde vive el riesgo real de la interfaz: estructuras que el JS indexa a
ciegas y constantes duplicadas entre Python y JS.
"""

import re

import pandas as pd
import pytest

from numeralia.reporte.tema import (
    COLOR_2025,
    COLOR_2026,
    COLOR_BLANCO,
    ESCALA_EPISODIOS_ANIO_ACTUAL,
    ESCALA_EPISODIOS_ANIO_PREVIO,
)

original = pytest.importorskip(
    "main",
    reason="main.py no está disponible; el refactor ya terminó.",
)


# ── Datos de la gráfica de episodios ────────────────────────────────────────

def _df_episodios():
    """
    Réplica mínima de la hoja 'Episodios': encabezados de severidad seguidos
    de sus subfilas por contaminante, que es como la lee
    ``_episodios_por_contaminante``.
    """
    filas = [
        ("Precontingencias atmosféricas:", 100, 40),
        ("   Precontingencias declaradas por Ozono", 60, 10),
        ("   Precontingencias declaradas por PM10", 30, 25),
        ("   Precontingencias declaradas por PM2.5", 10, 5),
        ("Contingencias atmosféricas Fase I:", 20, 8),
        ("   Contingencias declaradas por Ozono", 15, 0),
        ("   Contingencias declaradas por PM10", 5, 5),
        ("   Contingencias declaradas por PM2.5", 0, 3),
    ]
    return pd.DataFrame(filas, columns=["Episodios activados", "2025", "2026"])


@pytest.fixture
def datos_grafica():
    return original._datos_grafica_episodios(
        _df_episodios(), "2025", "2026", 1, "Precontingencias atmosféricas")


class TestDatosGraficaEpisodios:
    """
    El JS indexa ``colores_texto_anio[año][contaminante]`` sin comprobar
    nada: si la matriz no tiene la forma exacta, el color sale ``undefined``
    y la etiqueta se dibuja en negro por omisión, sin error en consola.
    """

    def test_una_lista_de_colores_por_anio(self, datos_grafica):
        assert len(datos_grafica["colores_texto_anio"]) == len(datos_grafica["anios"])

    def test_un_color_por_contaminante_en_cada_anio(self, datos_grafica):
        # Es el test que avisa si alguien agrega un cuarto contaminante a
        # _ORDEN_CONTAMINANTES y se olvida de la lista del año actual, que
        # está escrita a mano.
        esperados = len(datos_grafica["series"])
        for por_anio in datos_grafica["colores_texto_anio"]:
            assert len(por_anio) == esperados

    def test_cada_entrada_trae_nombre_y_valor(self, datos_grafica):
        for por_anio in datos_grafica["colores_texto_anio"]:
            for entrada in por_anio:
                assert set(entrada) == {"nombre", "valor"}

    def test_el_ozono_del_anio_previo_va_en_el_color_del_anio(self, datos_grafica):
        # Con la escala invertida, Ozono ocupa el tono más claro (índice 0).
        # Mismo patrón que PM2.5 en 2026: el color pleno del año como texto.
        assert datos_grafica["colores_texto_anio"][0][0] == {
            "nombre": COLOR_2025, "valor": COLOR_2025}

    def test_el_pm10_y_pm25_del_anio_previo_van_en_blanco(self, datos_grafica):
        # PM10 (índice 1) y PM2.5 (índice 2) tienen fondos medios/oscuros
        # y aguantan letra blanca.
        for entrada in datos_grafica["colores_texto_anio"][0][1:]:
            assert entrada == {"nombre": COLOR_BLANCO, "valor": COLOR_BLANCO}

    def test_el_ozono_del_anio_actual_va_en_el_color_del_anio(self, datos_grafica):
        # Ozono ocupa el tono más claro (índice 0). El blanco desaparecería
        # encima de ese tono casi blanco, así que va en el color pleno del año.
        ozono = datos_grafica["series"][0]["nombre"]
        assert ozono == "Ozono"
        assert datos_grafica["colores_texto_anio"][1][0] == {
            "nombre": COLOR_2026, "valor": COLOR_2026}

    def test_el_resto_del_anio_actual_va_en_blanco(self, datos_grafica):
        # PM10 (índice 1) y PM2.5 (índice 2) tienen fondos medios/oscuros
        # y aguantan letra blanca.
        for entrada in datos_grafica["colores_texto_anio"][1][1:]:
            assert entrada == {"nombre": COLOR_BLANCO, "valor": COLOR_BLANCO}

    def test_las_series_van_en_el_orden_de_apilado(self, datos_grafica):
        nombres = [s["nombre"] for s in datos_grafica["series"]]
        assert nombres == list(original._ORDEN_CONTAMINANTES)

    def test_una_escala_por_anio_con_un_tono_por_contaminante(self, datos_grafica):
        # El JS hace escalas_anio[j][i] con los mismos índices.
        assert len(datos_grafica["escalas_anio"]) == len(datos_grafica["anios"])
        for escala in datos_grafica["escalas_anio"]:
            assert len(escala) >= len(datos_grafica["series"])

    def test_los_totales_cuadran_con_las_series(self, datos_grafica):
        for j, total in enumerate(datos_grafica["totales"]):
            assert total == sum(s["datos"][j] for s in datos_grafica["series"])

    def test_un_color_por_anio(self, datos_grafica):
        assert len(datos_grafica["colores_anio"]) == len(datos_grafica["anios"])

    def test_separa_las_severidades(self):
        # La Fase I no debe arrastrar los números de las precontingencias.
        f1 = original._datos_grafica_episodios(
            _df_episodios(), "2025", "2026", 2, "Contingencias Fase I")
        assert f1["totales"] == [20, 8]

    def test_todo_es_serializable_a_json(self, datos_grafica):
        # Viaja al navegador dentro de un dcc.Store.
        import json
        json.dumps(datos_grafica)


# ── Legibilidad del texto sobre cada relleno ────────────────────────────────

def _contraste(color_a: str, color_b: str) -> float:
    """Contraste WCAG entre dos colores hex, de 1 (igual) a 21 (blanco/negro)."""
    def lineal(canal: int) -> float:
        c = canal / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def luminancia(color: str) -> float:
        crudo = color.lstrip("#")
        r, g, b = (int(crudo[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * lineal(r) + 0.7152 * lineal(g) + 0.0722 * lineal(b)

    la, lb = luminancia(color_a), luminancia(color_b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


class TestLegibilidadEpisodios:
    """
    El texto de cada segmento se eligió midiendo contraste, no a ojo. Si
    alguien mueve una escala, aquí se entera de a quién se lleva entre las
    patas.
    """

    def test_el_blanco_se_lee_en_los_tonos_con_letra_blanca_del_anio_previo(self):
        # Ozono (índice 2) usa el color pleno del año (no blanco), así que solo
        # se verifica el contraste de PM2.5 (índice 0) y PM10 (índice 1).
        # Ambos tienen contraste ≥ 4.5 con el color de fondo actual (#465055).
        for tono in ESCALA_EPISODIOS_ANIO_PREVIO[:2]:
            assert _contraste(COLOR_BLANCO, tono) >= 4.5

    def test_los_tonos_del_anio_previo_se_distinguen_entre_si(self):
        # La escala arranca en el azul marino pleno y aclara, así que el
        # contraste contra el blanco va bajando: 14.8 -> 8.5 -> 4.6.
        contrastes = [_contraste(COLOR_BLANCO, t) for t in ESCALA_EPISODIOS_ANIO_PREVIO]
        assert contrastes == sorted(contrastes, reverse=True)
        for a, b in zip(contrastes, contrastes[1:]):
            assert a - b >= 1.0

    def test_el_tono_del_ozono_del_anio_actual_es_casi_blanco(self):
        # Es la razón de que ahí el texto NO pueda ir en blanco. Si este test
        # empieza a fallar, el relleno se oscureció y conviene reconsiderar
        # el aqua del número (que hoy solo da 1.9 de contraste).
        assert _contraste(COLOR_BLANCO, ESCALA_EPISODIOS_ANIO_ACTUAL[0]) < 2.0


# ── Serie mensual: acoplamiento con el callback clientside ──────────────────

def _df_resumen_mensual(meses_2026: int = 7):
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
             "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    filas = [{"AÑO": anio, "MES": mes, "GLOBAL": 5}
             for anio, tope in ((2025, 12), (2026, meses_2026))
             for mes in meses[:tope]]
    return pd.DataFrame(filas)


@pytest.fixture
def figura_mensual():
    return original._fig_serie_buena_mensual(_df_resumen_mensual())


class TestFiguraSerieMensual:
    def test_hay_una_pastilla_y_una_anotacion_por_dato(self, figura_mensual):
        # El eje llega solo hasta el último mes con dato de 2026 (7 en el
        # fixture por defecto), así que ambos años tienen 7 puntos: 7+7=14.
        assert len(figura_mensual.layout.shapes) == 14
        assert len(figura_mensual.layout.annotations) == 14

    def test_las_pastillas_y_los_numeros_van_parejos(self, figura_mensual):
        assert len(figura_mensual.layout.shapes) == len(figura_mensual.layout.annotations)

    def test_el_cintillo_crece_con_los_meses_capturados(self):
        completa = original._fig_serie_buena_mensual(_df_resumen_mensual(meses_2026=12))
        assert len(completa.layout.shapes) == 24

    def test_el_margen_superior_aloja_el_cintillo(self, figura_mensual):
        # El callback clientside pisa este margen al quitar las pastillas. Si
        # cambia aquí, hay que revisar el valor que pone el JS (t: 34).
        assert figura_mensual.layout.margin.t == 95

    def test_la_leyenda_vive_arriba_del_cintillo(self, figura_mensual):
        # Por esto no basta con recortar el margen: la leyenda en y=1.30
        # quedaría fuera del lienzo. El JS la baja a 1.10.
        assert figura_mensual.layout.legend.y == pytest.approx(1.30)
        assert figura_mensual.layout.legend.y > 1.0

    def test_no_fija_el_ancho(self, figura_mensual):
        # Con un ancho fijo la gráfica no se adaptaría al contenedor.
        assert figura_mensual.layout.width is None

    def test_no_fija_el_alto(self, figura_mensual):
        # El alto lo manda el contenedor desde assets/responsive.css, que es
        # lo que permite achicarla en tablet y celular. Si alguien repone un
        # 'height' aquí, el CSS deja de tener efecto sin avisar.
        assert figura_mensual.layout.height is None

    def test_tampoco_lo_fija_la_version_sin_datos(self):
        # La rama de respaldo (hoja con menos de 3 columnas) también tiene que
        # dejar el alto al contenedor.
        vacia = original._fig_serie_buena_mensual(pd.DataFrame({"A": [1], "B": [2]}))
        assert vacia.layout.height is None

    def test_el_eje_llega_al_ultimo_mes_de_2026(self, figura_mensual):
        # El eje ya no muestra los 12 meses fijos: se extiende hasta el último
        # mes con dato en 2026. El fixture por defecto tiene 7 meses de 2026.
        assert len(figura_mensual.layout.xaxis.categoryarray) == 7


class TestGeometriaPastillas:
    """
    El ancho de la pastilla va en unidades de categoría y su alto en fracción
    del lienzo, así que al angostarse la gráfica el ancho encoge y el alto no.
    De ahí el umbral del callback clientside.

    Estos tests derivan el ancho de la figura REAL, no de una constante
    copiada: si alguien cambia ANCHO_PASTILLA, el umbral del JS queda mal y
    aquí se ve.

    La fórmula del umbral es: C ≥ 75 × N + 80, donde N = número de meses
    en el eje (len categoryarray). El JS la calcula dinámicamente. Con el
    fixture de 7 meses: UMBRAL = 75 × 7 + 80 = 605.
    """

    # El JS calcula este valor dinámicamente (75 × N + 80).
    # Con el fixture de 7 meses: 75 × 7 + 80 = 605.
    UMBRAL_JS = 605
    MINIMO_LEGIBLE = 18  # px que pide un número de dos dígitos a 13px

    def _ancho_pastilla_px(self, figura, ancho_contenedor: float) -> float:
        """Ancho en píxeles de una pastilla para un contenedor dado."""
        xs = [float(x) for x, _ in re.findall(
            r"(-?\d+\.?\d*),(-?\d+\.?\d*)", figura.layout.shapes[0].path)]
        ancho_categorias = max(xs) - min(xs)

        margenes = figura.layout.margin.l + figura.layout.margin.r
        categorias = len(figura.layout.xaxis.categoryarray)
        return ancho_categorias * (ancho_contenedor - margenes) / categorias

    def test_en_el_umbral_la_pastilla_es_legible(self, figura_mensual):
        assert self._ancho_pastilla_px(
            figura_mensual, self.UMBRAL_JS) >= self.MINIMO_LEGIBLE

    def test_en_pantalla_angosta_no_caben(self, figura_mensual):
        # Con 7 meses, el umbral es ~605px. Por debajo (ej. 550px) la pastilla
        # ya no cabe (0.24 × 470 / 7 ≈ 16px < 18px).
        assert self._ancho_pastilla_px(figura_mensual, 550) < self.MINIMO_LEGIBLE

    def test_en_un_celular_es_diminuta(self, figura_mensual):
        # A 300px: 0.24 × 220 / 7 ≈ 7.5px < 8px
        assert self._ancho_pastilla_px(figura_mensual, 300) < 8

    def test_en_escritorio_es_holgada(self, figura_mensual):
        assert self._ancho_pastilla_px(figura_mensual, 1170) >= 20

    def test_el_umbral_esta_justo_donde_deja_de_ser_legible(self, figura_mensual):
        # 60px por debajo del umbral (605 − 60 = 545): la pastilla ya no cabe.
        # 0.24 × (545 − 80) / 7 ≈ 15.9px < 18px.
        assert self._ancho_pastilla_px(
            figura_mensual, self.UMBRAL_JS - 60) < self.MINIMO_LEGIBLE


class TestTarjetaSerieMensual:
    """
    Cableado de la tarjeta. La figura va en un Store y la dibuja el callback
    clientside, para que haya un solo escritor de 'figure'.
    """

    @pytest.fixture
    def tarjeta(self):
        return original._card_serie_mensual_2025(_df_resumen_mensual())

    def _por_id(self, tarjeta, id_buscado):
        return next((c for c in tarjeta.children
                     if getattr(c, "id", None) == id_buscado), None)

    def test_estan_los_tres_componentes_que_usan_los_callbacks(self, tarjeta):
        for id_ in ("figura-serie-base", "grafico-serie-mensual",
                    "refrescar-serie-mensual"):
            assert self._por_id(tarjeta, id_) is not None

    def test_el_store_trae_la_figura_completa(self, tarjeta):
        # Con el fixture de 7 meses de 2026: 7 × 2 años = 14 pastillas.
        datos = self._por_id(tarjeta, "figura-serie-base").data
        assert len(datos["layout"]["shapes"]) == 14

    def test_la_grafica_no_trae_figura_propia(self, tarjeta):
        # Si la trajera, habría dos escritores de 'figure' y el refresco
        # periódico repondría las pastillas en el celular.
        grafica = self._por_id(tarjeta, "grafico-serie-mensual")
        assert getattr(grafica, "figure", None) is None

    def test_la_grafica_lleva_el_alto_y_la_clase_que_usa_el_css(self, tarjeta):
        grafica = self._por_id(tarjeta, "grafico-serie-mensual")
        assert grafica.className == "grafica-serie-mensual"
        assert grafica.style["height"] == "330px"

    def test_la_grafica_es_responsive(self, tarjeta):
        # Sin esto Plotly no sigue al contenedor y el alto del CSS no sirve.
        grafica = self._por_id(tarjeta, "grafico-serie-mensual")
        assert grafica.config["responsive"] is True


class TestFiguraMapa:
    """
    El mapa siguió el mismo camino que la serie mensual: el alto salió de la
    figura y ahora lo pone el contenedor.
    """

    @pytest.fixture
    def figura_mapa(self):
        df = pd.DataFrame({
            "Estación": ["AGU", "CEN", "TLA"],
            "Latitud": [20.62, 20.67, 20.64],
            "Longitud": [-103.42, -103.35, -103.44],
            original.MALA_25: [10, 20, 30],
            original.MALA_26: [5, 25, 30],
            original.BUENA_25: [100, 90, 80],
            original.BUENA_26: [120, 85, 80],
        })
        return original._fig_mapa(df)

    def test_no_fija_el_alto(self, figura_mapa):
        assert figura_mapa.layout.height is None

    def test_no_fija_el_ancho(self, figura_mapa):
        assert figura_mapa.layout.width is None
