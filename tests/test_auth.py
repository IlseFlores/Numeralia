"""
Orden de autenticación (numeralia.ingesta.auth). Sin red ni credenciales
reales: se sustituyen los cuatro caminos y se comprueba cuál gana.
"""

from types import SimpleNamespace

from numeralia.ingesta import auth


def test_prefiere_cuenta_de_servicio_del_entorno(monkeypatch):
    llamadas = []
    monkeypatch.setattr(auth, "_credenciales_desde_env",
                         lambda: {"client_email": "robot@x.iam.gserviceaccount.com"})
    monkeypatch.setattr(auth, "_ruta_credenciales", lambda: (_ for _ in ()).throw(
        AssertionError("no debería consultarse: ya hubo credenciales del entorno")))
    monkeypatch.setattr(auth.gspread, "service_account_from_dict",
                         lambda datos, http_client: llamadas.append(("env", datos)) or "cliente")

    assert auth.autenticar() == "cliente"
    assert llamadas == [("env", {"client_email": "robot@x.iam.gserviceaccount.com"})]


def test_cae_a_archivo_de_credenciales_si_no_hay_entorno(monkeypatch):
    llamadas = []
    monkeypatch.setattr(auth, "_credenciales_desde_env", lambda: None)
    monkeypatch.setattr(auth, "_ruta_credenciales", lambda: SimpleNamespace(name="credenciales.json"))
    monkeypatch.setattr(auth.gspread, "service_account",
                         lambda filename, http_client: llamadas.append(("archivo", filename)) or "cliente")

    assert auth.autenticar() == "cliente"
    assert llamadas[0][0] == "archivo"


def test_sin_nada_configurado_usa_la_credencial_por_defecto(monkeypatch):
    monkeypatch.setattr(auth, "_credenciales_desde_env", lambda: None)
    monkeypatch.setattr(auth, "_ruta_credenciales", lambda: None)
    monkeypatch.setattr(auth, "_en_colab", lambda: False)
    monkeypatch.setattr(auth, "default", lambda: ("creds", "proyecto"))
    monkeypatch.setattr(auth.gspread, "authorize",
                         lambda creds, http_client: "cliente-por-defecto")

    assert auth.autenticar() == "cliente-por-defecto"


def test_en_colab_sin_credenciales_usa_autorizacion_interactiva(monkeypatch):
    import sys
    import types

    modulo_colab = types.ModuleType("google.colab")
    modulo_colab.auth = SimpleNamespace(authenticate_user=lambda: None)
    monkeypatch.setitem(sys.modules, "google.colab", modulo_colab)
    monkeypatch.setitem(sys.modules, "google.colab.auth", modulo_colab.auth)

    monkeypatch.setattr(auth, "_credenciales_desde_env", lambda: None)
    monkeypatch.setattr(auth, "_ruta_credenciales", lambda: None)
    monkeypatch.setattr(auth, "default", lambda: ("creds", "proyecto"))
    monkeypatch.setattr(auth.gspread, "authorize", lambda creds, http_client: "cliente-colab")

    assert auth.autenticar() == "cliente-colab"


def test_en_colab_detecta_el_modulo_disponible(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "google.colab", types.ModuleType("google.colab"))
    assert auth._en_colab() is True


def test_fuera_de_colab_devuelve_falso(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "google.colab", None)  # simula ImportError
    assert auth._en_colab() is False
