"""Tests de los derivados de color del tema."""

import pytest

from numeralia.reporte.tema import (
    COLOR_ANIO_ACTUAL,
    COLOR_ANIO_PREVIO,
    ESCALA_ANIO_ACTUAL,
    ESCALA_ANIO_PREVIO,
    _luminancia,
    color_texto,
    color_textura,
    escala_serie,
    tinte,
)


class TestTinte:
    def test_sin_color_es_blanco(self):
        assert tinte("#191970", 0.0) == "#ffffff"

    def test_todo_el_color_se_conserva(self):
        assert tinte("#191970", 1.0) == "#191970"

    def test_aclara_hacia_blanco(self):
        assert _luminancia(tinte("#191970", 0.5)) > _luminancia("#191970")

    def test_acepta_hex_con_mayusculas(self):
        assert tinte("#4DC2B3", 1.0) == "#4dc2b3"

    def test_devuelve_hex_de_seis_digitos(self):
        salida = tinte("#191970", 0.37)
        assert salida.startswith("#") and len(salida) == 7


class TestLuminancia:
    @pytest.mark.parametrize("color, esperado", [("#000000", 0.0), ("#ffffff", 1.0)])
    def test_extremos(self, color, esperado):
        assert _luminancia(color) == pytest.approx(esperado)

    def test_el_azul_marino_es_oscuro(self):
        assert _luminancia(COLOR_ANIO_PREVIO) < 0.3

    def test_el_aqua_es_claro(self):
        assert _luminancia(COLOR_ANIO_ACTUAL) > 0.5


class TestColorTextura:
    def test_un_color_ya_claro_no_se_toca(self):
        # El aqua del año actual se lee bien detrás de una etiqueta tal cual.
        assert color_textura(COLOR_ANIO_ACTUAL) == COLOR_ANIO_ACTUAL

    def test_un_color_oscuro_se_aclara(self):
        # El azul marino en pleno se traga el texto que lleva encima.
        assert color_textura(COLOR_ANIO_PREVIO) != COLOR_ANIO_PREVIO

    def test_alcanza_la_luminancia_minima(self):
        for color in ("#000000", "#191970", "#8B0000"):
            assert _luminancia(color_textura(color, 0.6)) == pytest.approx(0.6, abs=0.02)


    def test_conserva_el_matiz(self):
        # Aclarar no debe volver gris el color: el azul sigue siendo el canal
        # más alto del azul marino aclarado.
        crudo = color_textura(COLOR_ANIO_PREVIO).lstrip("#")
        r, g, b = (int(crudo[i:i + 2], 16) for i in (0, 2, 4))
        assert b > r and b > g


class TestEscalaSerie:
    """La escala reemplazó a las tramas para distinguir los contaminantes."""

    def test_devuelve_los_tonos_pedidos(self):
        assert len(escala_serie("#191970", n=3)) == 3
        assert len(escala_serie("#191970", n=5)) == 5

    def test_va_de_claro_a_oscuro(self):
        lums = [_luminancia(c) for c in escala_serie("#191970", n=4)]
        assert lums == sorted(lums, reverse=True)

    def test_todos_los_tonos_dejan_leer_la_etiqueta(self):
        # La etiqueta va en gris #465055 (luminancia 0.30); ningún tono debe
        # acercarse tanto como para tragársela.
        for color in (COLOR_ANIO_PREVIO, COLOR_ANIO_ACTUAL, "#000000"):
            for tono in escala_serie(color, n=3, luminancia_minima=0.6):
                assert _luminancia(tono) >= 0.59

    def test_los_tonos_son_distinguibles_entre_si(self):
        # Si dos tonos quedan casi iguales, el lector no puede separar los
        # contaminantes: es justo lo que pasaba con las tramas.
        for escala in (ESCALA_ANIO_PREVIO, ESCALA_ANIO_ACTUAL):
            lums = [_luminancia(c) for c in escala]
            for a, b in zip(lums, lums[1:]):
                assert a - b >= 0.10

    def test_el_tono_mas_oscuro_respeta_el_tope(self):
        assert escala_serie(COLOR_ANIO_ACTUAL, n=3)[-1] == color_textura(COLOR_ANIO_ACTUAL).lower()

    def test_un_solo_tono_es_el_mas_oscuro_permitido(self):
        assert escala_serie("#191970", n=1) == [color_textura("#191970")]

    def test_cero_tonos_es_un_error(self):
        with pytest.raises(ValueError):
            escala_serie("#191970", n=0)

    def test_las_dos_escalas_del_reporte_tienen_tres_tonos(self):
        assert len(ESCALA_ANIO_PREVIO) == len(ESCALA_ANIO_ACTUAL) == 3


def _contraste_sobre_blanco(color_hex: str) -> float:
    """Razón de contraste WCAG contra fondo blanco."""
    crudo = color_hex.lstrip("#")
    canales = []
    for i in (0, 2, 4):
        c = int(crudo[i:i + 2], 16) / 255
        canales.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    lum = 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2]
    return 1.05 / (lum + 0.05)


class TestColorTexto:
    """Los colores de severidad son de relleno; como texto hay que oscurecerlos."""

    def test_el_ambar_original_no_se_lee_sobre_blanco(self):
        # 1.79:1, muy por debajo del 4.5:1 que pide WCAG AA. Es la razón de
        # que este helper exista.
        assert _contraste_sobre_blanco("#FFB300") < 2.0

    @pytest.mark.parametrize("severidad", ["#FFB300", "#EF6C00"])
    def test_el_color_ajustado_cumple_wcag_aa(self, severidad):
        assert _contraste_sobre_blanco(color_texto(severidad)) >= 4.5

    def test_un_color_ya_oscuro_no_se_toca(self):
        # El morado de Fase III ya contrasta de sobra.
        assert color_texto("#4B0082") == "#4B0082"

    def test_conserva_el_tono(self):
        # Oscurecer no debe virar el ámbar hacia otro color: los canales
        # mantienen su proporción (rojo > verde > azul).
        crudo = color_texto("#FFB300").lstrip("#")
        r, g, b = (int(crudo[i:i + 2], 16) for i in (0, 2, 4))
        assert r > g > b
        assert b == 0

    def test_alcanza_la_luminancia_pedida(self):
        for color in ("#FFB300", "#EF6C00", "#ffff00"):
            assert _luminancia(color_texto(color, 0.42)) == pytest.approx(0.42, abs=0.02)
