"""Tests de los derivados de color del tema."""

import pytest

from numeralia.reporte.tema import (
    COLOR_ANIO_ACTUAL,
    COLOR_ANIO_PREVIO,
    ESCALA_ANIO_ACTUAL,
    ESCALA_ANIO_PREVIO,
    ESCALA_EPISODIOS_ANIO_PREVIO,
    _luminancia,
    escala_serie,
    escala_serie_oscura,
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

    def test_un_color_ya_claro_llega_hasta_su_tono_pleno(self):
        # El aqua tiene luminancia 0.62, por encima del mínimo: su tono más
        # oscuro puede ser el color tal cual.
        assert escala_serie(COLOR_ANIO_ACTUAL, n=3)[-1] == COLOR_ANIO_ACTUAL.lower()

    def test_un_color_oscuro_se_topa_antes_de_llegar_al_pleno(self):
        # El azul marino no: su tono más oscuro se queda en la luminancia
        # mínima para no tragarse la etiqueta de encima.
        mas_oscuro = escala_serie(COLOR_ANIO_PREVIO, n=3)[-1]
        assert mas_oscuro != COLOR_ANIO_PREVIO.lower()
        assert _luminancia(mas_oscuro) == pytest.approx(0.6, abs=0.02)

    def test_un_solo_tono_es_el_mas_oscuro_permitido(self):
        solo = escala_serie("#191970", n=1)
        assert len(solo) == 1
        assert _luminancia(solo[0]) == pytest.approx(0.6, abs=0.02)

    def test_cero_tonos_es_un_error(self):
        with pytest.raises(ValueError):
            escala_serie("#191970", n=0)

    def test_las_dos_escalas_del_reporte_tienen_tres_tonos(self):
        assert len(ESCALA_ANIO_PREVIO) == len(ESCALA_ANIO_ACTUAL) == 3


class TestEscalaSerieOscura:
    """
    Contraparte de ``escala_serie``: arranca en el color pleno y aclara, para
    rellenos oscuros con la etiqueta en blanco encima.
    """

    def test_devuelve_los_tonos_pedidos(self):
        assert len(escala_serie_oscura("#191970", n=3)) == 3
        assert len(escala_serie_oscura("#191970", n=5)) == 5

    def test_el_primer_tono_es_el_color_de_marca_sin_mezclar(self):
        # Es lo que hace que la barra del año previo se reconozca de un golpe
        # de vista; la escala clara no lo lograba.
        assert escala_serie_oscura(COLOR_ANIO_PREVIO)[0] == COLOR_ANIO_PREVIO.lower()

    def test_va_de_oscuro_a_claro(self):
        lums = [_luminancia(c) for c in escala_serie_oscura("#191970", n=4)]
        assert lums == sorted(lums)

    def test_el_piso_limita_cuanto_aclara(self):
        # Con un piso más alto, el tono final conserva más color y queda más
        # oscuro. Es el parámetro que se subió de 0.5 a 0.62 porque el tono
        # claro se tragaba la etiqueta blanca.
        claro = escala_serie_oscura(COLOR_ANIO_PREVIO, piso=0.5)[-1]
        oscuro = escala_serie_oscura(COLOR_ANIO_PREVIO, piso=0.62)[-1]
        assert _luminancia(oscuro) < _luminancia(claro)

    def test_un_solo_tono_es_el_color_pleno(self):
        assert escala_serie_oscura("#191970", n=1) == ["#191970"]

    def test_cero_tonos_es_un_error(self):
        with pytest.raises(ValueError):
            escala_serie_oscura("#191970", n=0)

    def test_los_tonos_son_distinguibles_entre_si(self):
        lums = [_luminancia(c) for c in ESCALA_EPISODIOS_ANIO_PREVIO]
        for a, b in zip(lums, lums[1:]):
            assert b - a >= 0.10

    def test_la_escala_de_episodios_usa_el_piso_por_omision(self):
        assert ESCALA_EPISODIOS_ANIO_PREVIO == escala_serie_oscura(COLOR_ANIO_PREVIO)
