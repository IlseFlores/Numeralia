"""Tests de la caché con vencimiento de las lecturas de Sheets."""

import threading
import time

import pytest

from numeralia.cache import CacheTemporal, cache_sheets


@pytest.fixture
def cache():
    return CacheTemporal()


class TestReuso:
    def test_la_primera_vez_calcula(self, cache):
        assert cache.obtener("k", 60, lambda: "valor") == "valor"

    def test_la_segunda_vez_no_vuelve_a_calcular(self, cache):
        llamadas = []

        def leer():
            llamadas.append(1)
            return len(llamadas)

        assert cache.obtener("k", 60, leer) == 1
        assert cache.obtener("k", 60, leer) == 1
        # Esta es la razón de existir del módulo: N pestañas, una lectura.
        assert len(llamadas) == 1

    def test_claves_distintas_no_se_pisan(self, cache):
        assert cache.obtener("a", 60, lambda: 1) == 1
        assert cache.obtener("b", 60, lambda: 2) == 2
        assert cache.obtener("a", 60, lambda: 99) == 1

    def test_la_clave_puede_ser_una_tupla(self, cache):
        # Así se usa en el dashboard: (url, nombre de la pestaña).
        clave = ("https://…/abc", "NUEVO alertas 2026")
        assert cache.obtener(clave, 60, lambda: "df") == "df"
        assert cache.obtener(clave, 60, lambda: "otro") == "df"

    def test_guarda_valores_falsy(self, cache):
        # Una hoja vacía devuelve algo falsy y no por eso debe releerse.
        llamadas = []

        def leer():
            llamadas.append(1)
            return []

        cache.obtener("k", 60, leer)
        cache.obtener("k", 60, leer)
        assert len(llamadas) == 1


class TestVencimiento:
    def test_al_vencer_vuelve_a_leer(self, cache):
        llamadas = []

        def leer():
            llamadas.append(1)
            return len(llamadas)

        assert cache.obtener("k", 0.05, leer) == 1
        time.sleep(0.08)
        assert cache.obtener("k", 0.05, leer) == 2

    def test_vencimiento_cero_siempre_relee(self, cache):
        llamadas = []
        for _ in range(3):
            cache.obtener("k", 0, lambda: llamadas.append(1))
        assert len(llamadas) == 3


class TestLimpieza:
    def test_limpiar_una_clave(self, cache):
        cache.obtener("a", 60, lambda: 1)
        cache.obtener("b", 60, lambda: 2)
        cache.limpiar("a")
        assert len(cache) == 1
        assert cache.obtener("a", 60, lambda: 99) == 99

    def test_limpiar_todo(self, cache):
        cache.obtener("a", 60, lambda: 1)
        cache.obtener("b", 60, lambda: 2)
        cache.limpiar()
        assert len(cache) == 0

    def test_limpiar_una_clave_inexistente_no_truena(self, cache):
        cache.limpiar("no-existe")


class TestConcurrencia:
    def test_varios_hilos_no_corrompen_la_cache(self, cache):
        # El servidor atiende pestañas en paralelo: dos hilos pueden pedir lo
        # mismo a la vez sin que la caché quede inconsistente.
        resultados = []

        def trabajar(i):
            resultados.append(cache.obtener("compartida", 60, lambda: "unico"))

        hilos = [threading.Thread(target=trabajar, args=(i,)) for i in range(12)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        assert len(resultados) == 12
        assert set(resultados) == {"unico"}
        assert len(cache) == 1


def test_hay_una_cache_compartida_del_proceso():
    # El dashboard la usa para que las pestañas se beneficien entre sí.
    assert isinstance(cache_sheets, CacheTemporal)
