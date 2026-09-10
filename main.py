# ============================================================================
# PIPELINE COMPLETO — Calidad del Aire SEMADET
# Numeralia (Cruda -> Procesada -> Analítica) + Episodios + IMECA Máximo +
# Alertas + Dashboard (Dash), todo en una sola corrida.
#
# CÓMO USARLO EN COLAB
# ---------------------------------------------------------------------------
# 1) En la PRIMERAAAA celda de tu notebook (una sola vez por sesión), instala
#    las dependencias que no vienen por defecto en Colab:
#
#       %pip install gspread-dataframe dash fpdf2 kaleido -q
#
#    (fpdf2 se usa para los PDF de las dos bitacoras. kaleido genera la foto
#     fija del mapa que va en el PDF del dashboard: sin el, todo funciona
#     igual pero el mapa sale vacio en el PDF. El resto del PDF lo arma el
#     navegador con html2canvas + jsPDF, que se cargan por CDN.)
#
# 1.b) LOGOS DEL ENCABEZADO: viven en una carpeta 'logos' dentro de tu Google
#    Drive, en la raiz de "Mi unidad":
#
#       MyDrive/logos/logo simaj (1).png            -> esquina superior izquierda
#       MyDrive/logos/SemadetGobJal_transp (1).png  -> esquina superior derecha
#
#    El codigo NO monta Drive solo (para no interrumpir pidiendo permisos),
#    asi que si es una sesion nueva corre esto antes en una celda aparte:
#
#       from google.colab import drive
#       drive.mount('/content/drive')
#
#    Si falta algun logo, el dashboard se levanta igual, solo sin ese logo, y
#    la consola imprime la ruta exacta donde lo busco.
#
# 2) Pega este archivo completo en la SIGUIENTE celda y ejecútala (esto solo
#    define funciones, no corre nada todavía).
#
# 3) En una tercera celda, dispara todo con una sola línea:
#
#       acumulado = run_full_pipeline()
#
#    Esto: valida Cruda, calcula IAS/NOM, escribe Procesada, acumula en
#    Analítica, recalcula Episodios + IMECA Máximo + Alertas, y al final
#    levanta el dashboard del mapa con los datos ya frescos.
#
#    Si solo quieres correr el pipeline de datos sin abrir el dashboard:
#
#       acumulado = run_full_pipeline(lanzar_dashboard=False)
#
# ============================================================================
# CÓMO USARLO COMO ARCHIVO .py (fuera de Colab)
# ---------------------------------------------------------------------------
# El mismo archivo sirve en los dos lados; lo único que cambia es cómo se
# autentica con Google. En Colab hay una persona que autoriza en una ventana;
# en un .py no la hay, así que se usa una CUENTA DE SERVICIO: un usuario
# "robot" que tiene sus propias llaves en un archivo JSON.
#
# 1) Dependencias:
#
#       pip install gspread gspread-dataframe google-auth pandas numpy \
#                   openpyxl dash plotly fpdf2 kaleido python-dotenv
#
# 2) Crear la cuenta de servicio (una sola vez):
#      a. Entra a https://console.cloud.google.com/ y crea un proyecto.
#      b. Activa "Google Sheets API" y "Google Drive API".
#      c. IAM y administración -> Cuentas de servicio -> Crear.
#      d. En la cuenta creada: pestaña CLAVES -> Agregar clave -> JSON.
#
# 2.b) Pasar las llaves al .env (recomendado):
#      Copia .env.example como .env y vacía ahí los campos del JSON. Después
#      BORRA el archivo .json descargado: su contenido ya vive en el .env,
#      que está protegido por .gitignore.
#
#      Ojo con GOOGLE_PRIVATE_KEY: va entre comillas, en una sola línea, y
#      conservando los \n literales tal como vienen en el JSON.
#
#      Si prefieres seguir con el archivo, también funciona: renómbralo a
#      credenciales.json y ponlo junto a este .py. El código intenta primero
#      el .env y si no encuentra nada, busca el archivo.
#
# 3) Darle acceso a las hojas (esto es lo que más se olvida):
#      Abre credenciales.json, copia el valor de "client_email" (algo como
#      robot@proyecto.iam.gserviceaccount.com) y comparte con ese correo las
#      cuatro hojas de cálculo que usa el pipeline:
#         · Hoja destino  -> permiso EDITOR (aquí escribe)
#         · Fuente 2025   -> Lector
#         · Fuente 2026   -> Lector
#         · Resumen MENSUAL -> Lector
#      Sin esto, el pipeline falla con un error 403 de permisos.
#
# 4) Logos: crea una carpeta 'logos' junto al .py con los dos PNG dentro.
#
# 5) Correr:
#
#       python main.py          # usa el año actual
#       python main.py 2026     # fuerza un año
#
#    El dashboard queda en http://127.0.0.1:8050
#
#    Nota: corriendo como .py el año NO se pregunta por consola, se toma del
#    sistema o del argumento. Así el pipeline puede correr desatendido, por
#    ejemplo desde una tarea programada.
# ============================================================================

import os
import re
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd
import gspread
from google.auth import default
from gspread.http_client import BackOffHTTPClient
from gspread_dataframe import set_with_dataframe

warnings.filterwarnings('ignore')


# ============================================================================
# SECCIÓN 0: AUTENTICACIÓN Y UTILIDADES DE ENTORNO
# ============================================================================

def _en_colab() -> bool:
    """Devuelve True si se está ejecutando en Google Colab."""
    try:
        import google.colab  # noqa: F401
        return True
    except ImportError:
        return False


# ── Configuración y secretos ────────────────────────────────────────────────
#
# Nada sensible vive dentro de este archivo: las llaves de la cuenta de
# servicio y las URLs de las hojas se leen de variables de entorno, que a su
# vez se cargan de un archivo .env que NO se sube al repositorio. Así el
# código se puede versionar y compartir sin exponer credenciales.
#
# Ver .env.example para la plantilla.

# La carga del .env, el armado de las credenciales y la busqueda del archivo
# JSON viven ahora en numeralia.config, que es el unico lugar que lee el
# entorno. Aqui solo se reexportan los nombres que el resto del archivo usa.
from numeralia.config import (                                    # noqa: E402
    CAMPOS_CUENTA_SERVICIO as _CAMPOS_CUENTA_SERVICIO,
    cargar_dotenv as _cargar_dotenv,
    credenciales_desde_env as _credenciales_desde_env,
    ruta_credenciales as _ruta_credenciales,
)

# Antes que nada, la salida en UTF-8: este módulo imprime emojis en sus
# mensajes de avance y la consola de Windows es cp1252. Va aquí, y no solo en
# el CLI, para que también funcione al importarlo desde una sesión de Python.
from numeralia.sheets import (                                     # noqa: E402
    _df_a_valores_sheet,
    _df_nativo,
    _worksheet_a_df,
)
from numeralia.consola import forzar_utf8                          # noqa: E402

forzar_utf8()

_ruta_env = _cargar_dotenv()
if _ruta_env:
    print(f"[config] Configuracion cargada de {_ruta_env}")

ARCHIVO_CREDENCIALES = os.getenv('GOOGLE_CREDENCIALES_ARCHIVO', 'credenciales.json')


def autenticar() -> gspread.Client:
    """
    Devuelve el cliente de gspread, eligiendo el método que corresponde al
    entorno, en este orden:

      1. Cuenta de servicio desde variables de entorno (.env). Es la vía
         recomendada: las llaves no quedan en un archivo del proyecto.
      2. Cuenta de servicio desde archivo JSON, si no hay nada en el entorno.
      3. Autorización interactiva de Colab.
      4. Credencial por defecto del sistema (Google Cloud, Cloud Run, etc.).

    El orden importa: las cuentas de servicio van primero para que, si están
    configuradas, nunca se abra un diálogo de permisos — eso es lo que
    permite que el pipeline corra desatendido.

    Todos los caminos usan BackOffHTTPClient: Google limita las lecturas a 60
    por minuto y una corrida completa gasta cerca de la mitad, así que basta
    con que el dashboard esté abierto refrescándose para toparse con un 429 a
    media corrida. Este cliente reintenta solo, con esperas crecientes, en vez
    de tirar el pipeline.
    """
    desde_env = _credenciales_desde_env()
    if desde_env is not None:
        print(f"Autenticando con cuenta de servicio desde el entorno "
              f"({desde_env['client_email']})")
        return gspread.service_account_from_dict(
            desde_env, http_client=BackOffHTTPClient)

    ruta = _ruta_credenciales()
    if ruta is not None:
        print(f"Autenticando con cuenta de servicio: {ruta.name}")
        return gspread.service_account(
            filename=str(ruta), http_client=BackOffHTTPClient)

    if _en_colab():
        from google.colab import auth
        auth.authenticate_user()
        creds, _ = default()
        return gspread.authorize(creds, http_client=BackOffHTTPClient)

    print("Nota: no hay credenciales en el entorno ni archivo de cuenta de servicio; "
          "se usará la credencial por defecto del sistema.")
    creds, _ = default()
    return gspread.authorize(creds, http_client=BackOffHTTPClient)


# ============================================================================
# SECCIÓN 1: VALIDADOR ENVISTA -> BD
# ============================================================================

class ValidadorCalidadAire:
    """Clase principal para validación de datos de calidad del aire."""

    def __init__(self):
        self.mapeo_estaciones = {
            'Atemajac':        'ATM',
            'Counrty':         'COU',
            'Estación Centro': 'CEN',
            'Las Aguilas':     'AGU',
            'Las Pintas':      'PIN',
            'Loma Dorada':     'LDO',
            'Miravalle':       'MIR',
            'Oblatos':         'OBL',
            'Santa Anita':     'SAN',
            'Santa Fe':        'SFE',
            'Santa Margarita': 'SMT',
            'Tlaquepaque':     'TLA',
            'Vallarta':        'VAL',
        }

        self.mapeo_parametros = {
            'TempInt':   'IT',
            'TempExt':   'ET',
            'Radiación': 'RS',
            'Radidacion':'RS',
            'IUV':       'UVI',
            'PRECIP':    'PP',
            'Presion':   'ATM',
            'O3': 'O3', 'NO': 'NO', 'NO2': 'NO2', 'NOX': 'NOX',
            'SO2': 'SO2', 'CO': 'CO', 'PM10': 'PM10', 'PM2.5': 'PM2.5',
            'RH': 'RH', 'WS': 'WS', 'WD': 'WD',
        }

        self.decimales = {
            'O3': 3, 'NO': 3, 'NO2': 3, 'NOX': 3, 'SO2': 3, 'CO': 2,
            'PM10': 0, 'PM2.5': 0, 'IT': 2, 'ET': 2, 'RH': 1,
            'WS': 1, 'WD': 1, 'PP': 2, 'ATM': 1, 'RS': 1, 'UVI': 2,
        }

        self.rangos = {
            'O3':   {'min': -0.003, 'max': 0.400, 'limite_deteccion': 0.001},
            'SO2':  {'min': -0.003, 'max': 0.400, 'limite_deteccion': 0.001},
            'NO2':  {'min': -0.003, 'max': 0.400, 'limite_deteccion': 0.001},
            'NO':   {'min': -0.003, 'max': 0.400, 'limite_deteccion': 0.001},
            'NOX':  {'min': -0.006, 'max': 0.400, 'limite_deteccion': 0.006},
            'CO':   {'min': -0.04,  'max': 45,    'limite_deteccion': 0.04},
            'PM10': {'min': 0,      'max': 950},
            'PM2.5':{'min': 0,      'max': 950},
            'ET':   {'min': -5,     'max': 50},
            'IT':   {'min': 0,      'max': 50},
            'RH':   {'min': 0,      'max': 100},
            'WS':   {'min': 0,      'max': 50},
            'WD':   {'min': 0,      'max': 360},
            'PP':   {'min': 0,      'max': 10},
            'ATM':  {'min': 500,    'max': 760},
            'RS':   {'min': 0,      'max': 2000},
            'UVI':  {'min': 0,      'max': 300},
        }

        self.banderas = {
            'NoData':  'ND', 'InVld':    'IO', 'Zero':    'IC',
            'Span':    'IC', 'OutCal':   'IC', 'Alarm':   'IF',
            'WarmUp':  'IF', 'Maintain': 'IF', 'Above R': 'IR',
            'BelowR':  'IR', 'Calm':     'IO', '<Samp':   'IO',
            'OffScan': 'IO',
        }

        self.validar_por_temperatura = True

    # ------------------------------------------------------------------
    def _procesar_raw_envista(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        """
        Parseo del formato ENVISTA (Trs): fila 2 (índice 2) = estaciones,
        fila 3 (índice 3) = parámetros, datos desde la fila 5 (índice 5),
        primera columna = DateTime.
        """
        print(f"Datos raw cargados: {df_raw.shape}")

        estaciones = df_raw.iloc[2, :].values
        parametros = df_raw.iloc[3, :].values

        nuevas_columnas = ['DateTime']
        for i in range(1, len(estaciones)):
            if pd.notna(estaciones[i]) and pd.notna(parametros[i]):
                nuevas_columnas.append(f"{estaciones[i]}_{parametros[i]}")
            else:
                nuevas_columnas.append(f"Col_{i}")

        df_datos = df_raw.iloc[5:, :len(nuevas_columnas)].copy()
        df_datos.columns = nuevas_columnas
        df_datos = df_datos.reset_index(drop=True)

        df_datos['DateTime'] = pd.to_datetime(
            df_datos['DateTime'].astype(str).str.strip(),
            format='%d-%m-%y %I:%M %p',
            errors='coerce'
        )
        df_datos = df_datos.dropna(subset=['DateTime'])

        print(f"Datos procesados: {df_datos.shape}")
        print(f"Rango de fechas: {df_datos['DateTime'].min()} a {df_datos['DateTime'].max()}")
        return df_datos

    def cargar_y_procesar_envista(self, archivo_trs: str) -> pd.DataFrame:
        """Carga y procesa datos desde un archivo Excel ENVISTA (formato Trs)."""
        print(f"Cargando datos ENVISTA desde Excel: {archivo_trs}")
        try:
            df_raw = pd.read_excel(archivo_trs, sheet_name=0, header=None)
            return self._procesar_raw_envista(df_raw)
        except Exception as e:
            print(f"Error al cargar datos ENVISTA: {e}")
            return None

    def cargar_y_procesar_envista_desde_sheet(self, worksheet) -> pd.DataFrame:
        """Carga y procesa datos desde una hoja de Google Sheets ya abierta con gspread."""
        print(f"Cargando datos ENVISTA desde Google Sheets: '{worksheet.title}'")
        try:
            valores = worksheet.get_all_values()
            df_raw = pd.DataFrame(valores)
            df_raw = df_raw.replace('', np.nan)
            return self._procesar_raw_envista(df_raw)
        except Exception as e:
            print(f"Error al cargar datos ENVISTA desde Google Sheets: {e}")
            return None

    # ------------------------------------------------------------------
    def convertir_a_formato_base(self, df_envista: pd.DataFrame) -> pd.DataFrame:
        """Convierte el formato ENVISTA al formato base BD."""
        print("\nConvirtiendo a formato base...")

        columnas_bd = [
            'STATION', 'DATE', 'HOUR', 'O3', 'NO', 'NO2', 'NOX', 'SO2', 'CO',
            'PM10', 'PM2.5', 'IT', 'ET', 'RH', 'WS', 'WD', 'PP', 'ATM', 'RS', 'UVI',
        ]

        datos_convertidos = []

        for idx, fila in df_envista.iterrows():
            if idx % 100 == 0:
                print(f"  Procesando fila {idx}/{len(df_envista)}")

            fecha_hora = fila['DateTime']
            if pd.isna(fecha_hora):
                continue

            hora = fecha_hora.hour

            for estacion_completa, abrev_estacion in self.mapeo_estaciones.items():
                fila_base = {'STATION': abrev_estacion, 'DATE': fecha_hora, 'HOUR': hora}
                for param in columnas_bd[3:]:
                    fila_base[param] = None

                for col in df_envista.columns:
                    if col.startswith(estacion_completa + '_'):
                        parametro_envista = col.split('_', 1)[1]
                        parametro_base = self.mapeo_parametros.get(parametro_envista, parametro_envista)
                        if parametro_base in columnas_bd:
                            valor = fila[col]
                            if pd.notna(valor) and str(valor).strip() != '':
                                try:
                                    fila_base[parametro_base] = float(valor)
                                except (ValueError, TypeError):
                                    fila_base[parametro_base] = str(valor).strip()

                datos_convertidos.append(fila_base)

        if not datos_convertidos:
            print("No se pudieron convertir los datos.")
            return pd.DataFrame()

        df_convertido = pd.DataFrame(datos_convertidos)
        for col in columnas_bd:
            if col not in df_convertido.columns:
                df_convertido[col] = None
        df_convertido = (df_convertido[columnas_bd]
                         .sort_values(['STATION', 'DATE', 'HOUR'])
                         .reset_index(drop=True))

        print(f"\nDatos convertidos: {df_convertido.shape}")
        print(f"Estaciones: {sorted(df_convertido['STATION'].unique())}")
        print(f"Período: {df_convertido['DATE'].min()} a {df_convertido['DATE'].max()}")
        return df_convertido

    # ------------------------------------------------------------------
    def aplicar_banderas(self, df: pd.DataFrame) -> pd.DataFrame:
        """Mapea banderas ENVISTA a códigos internos y rellena vacíos con ND."""
        print("\nAplicando mapeo de banderas ENVISTA -> base...")
        df_flag = df.copy()
        cols_param = [c for c in df_flag.columns if c not in ['STATION', 'DATE', 'HOUR']]
        df_flag[cols_param] = df_flag[cols_param].replace(self.banderas)
        for col in cols_param:
            mask = df_flag[col].isna()
            if mask.any():
                self._marcar(df_flag, col, mask, 'ND')
        return df_flag

    # ------------------------------------------------------------------
    @staticmethod
    def _marcar(df: pd.DataFrame, columna: str, mask: pd.Series, codigo: str) -> None:
        """
        Escribe un código de bandera ('IR', 'ND', ...) en las filas de ``mask``.

        Las columnas de parámetros conviven con números y con códigos de texto,
        así que su tipo tiene que ser ``object``. Pandas 3 ya no las convierte
        solo al asignarles texto: si la columna llegó como ``float64`` —porque
        en esa corrida todos sus valores eran numéricos— la asignación lanza
        ``TypeError: Invalid value 'IR' for dtype 'float64'``. De ahí que la
        conversión vaya explícita y antes de escribir.
        """
        if df[columna].dtype != object:
            df[columna] = df[columna].astype(object)
        df.loc[mask, columna] = codigo

    # ------------------------------------------------------------------
    def validar_rangos(self, df: pd.DataFrame) -> pd.DataFrame:
        """Valida datos por rangos físicos establecidos."""
        print("\nAplicando validación por rangos...")
        df_val = df.copy()
        contadores = {'IR': 0, 'VZ': 0}

        for parametro, config in self.rangos.items():
            if parametro not in df_val.columns:
                continue
            valores_num = pd.to_numeric(df_val[parametro], errors='coerce')
            mask_num = valores_num.notna()
            if not mask_num.any():
                continue

            mask_fuera = mask_num & (
                (valores_num < config['min']) | (valores_num > config['max'])
            )
            if mask_fuera.any():
                self._marcar(df_val, parametro, mask_fuera, 'IR')
                contadores['IR'] += mask_fuera.sum()

            if 'limite_deteccion' in config and config['limite_deteccion'] is not None:
                mask_lim = (
                    mask_num
                    & (valores_num >= config['min'])
                    & (valores_num < config['limite_deteccion'])
                )
                if mask_lim.any():
                    df_val.loc[mask_lim, parametro] = config['limite_deteccion']
                    contadores['VZ'] += mask_lim.sum()

        print(f"Valores IR (fuera de rango): {contadores['IR']}")
        print(f"Valores VZ (límite detección): {contadores['VZ']}")
        return df_val

    # ------------------------------------------------------------------
    def aplicar_decimales(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aplica formato de decimales a valores numéricos."""
        df_fmt = df.copy()
        for parametro, dec in self.decimales.items():
            if parametro in df_fmt.columns:
                vals = pd.to_numeric(df_fmt[parametro], errors='coerce')
                mask = vals.notna()
                if mask.any():
                    df_fmt.loc[mask, parametro] = vals[mask].round(dec)
        return df_fmt

    # ------------------------------------------------------------------
    def crear_resumen_validacion(self, df: pd.DataFrame):
        """Crea resumen de banderas y estadísticas generales."""
        banderas_encontradas = {}
        cols_param = [c for c in df.columns if c not in ['STATION', 'DATE', 'HOUR']]
        flags_validos = set(self.banderas.values()) | {'IR', 'ND'}

        for col in cols_param:
            if df[col].dtype == 'object':
                for valor in df[col].unique():
                    if isinstance(valor, str) and valor in flags_validos:
                        banderas_encontradas[valor] = (
                            banderas_encontradas.get(valor, 0) + (df[col] == valor).sum()
                        )

        if banderas_encontradas:
            resumen = pd.DataFrame.from_dict(banderas_encontradas, orient='index', columns=['Cantidad'])
            descripciones = {
                'ND': 'Sin dato', 'IO': 'Dato inválido', 'IC': 'Calibración',
                'IF': 'Mantenimiento', 'IR': 'Fuera de rango',
            }
            resumen['Descripción'] = resumen.index.map(lambda x: descripciones.get(x, 'Bandera'))
            resumen = resumen.sort_values('Cantidad', ascending=False)
        else:
            resumen = pd.DataFrame({'Cantidad': [0], 'Descripción': ['Sin banderas']},
                                   index=['Sin_banderas'])

        dias_unicos = (len(df['DATE'].dt.date.unique())
                       if np.issubdtype(df['DATE'].dtype, np.datetime64)
                       else len(df['DATE'].unique()))

        estadisticas = pd.DataFrame({
            'Cantidad': [
                len(df),
                len(df['STATION'].unique()),
                dias_unicos,
                sum(pd.to_numeric(df[c], errors='coerce').notna().sum() for c in cols_param),
            ],
            'Descripción': ['Total registros', 'Estaciones', 'Días', 'Valores numéricos válidos'],
        }, index=['Total_Registros', 'Estaciones', 'Días', 'Valores_Válidos'])

        return resumen, estadisticas

    # ------------------------------------------------------------------
    def exportar_resultados(self, df_validado: pd.DataFrame, archivo_salida: str):
        """Exporta el BD validado a Excel (Data + resúmenes)."""
        print(f"\nExportando resultados a: {archivo_salida}")
        try:
            df_exp = self.aplicar_decimales(df_validado)
            cols_param = [c for c in df_exp.columns if c not in ['STATION', 'DATE', 'HOUR']]
            df_exp[cols_param] = df_exp[cols_param].fillna('ND')
            resumen_banderas, estadisticas = self.crear_resumen_validacion(df_exp)

            with pd.ExcelWriter(archivo_salida, engine='openpyxl') as writer:
                df_exp.to_excel(writer, sheet_name='Data', index=False)
                resumen_banderas.to_excel(writer, sheet_name='Resumen_Banderas', index=True)
                estadisticas.to_excel(writer, sheet_name='Estadísticas', index=True)
                config_df = pd.DataFrame({
                    'Parámetro': list(self.rangos.keys()),
                    'Mín': [r['min'] for r in self.rangos.values()],
                    'Máx': [r['max'] for r in self.rangos.values()],
                    'Decimales': [self.decimales.get(p, 0) for p in self.rangos.keys()],
                })
                config_df.to_excel(writer, sheet_name='Configuración', index=False)

            print("Exportación completada.")
            print(estadisticas)
        except Exception as e:
            print(f"Error al exportar: {e}")

    # ------------------------------------------------------------------
    def ejecutar_validacion_completa(self, archivo_trs: str, archivo_salida: str = None):
        """Proceso completo desde un Excel local: carga → conversión → banderas → rangos → exporta."""
        print("=" * 60)
        print("VALIDACIÓN COMPLETA DE DATOS DE CALIDAD DEL AIRE")
        print("=" * 60)

        df_envista = self.cargar_y_procesar_envista(archivo_trs)
        if df_envista is None or len(df_envista) == 0:
            print("Error: no se pudieron cargar los datos ENVISTA.")
            return None, None

        df_convertido = self.convertir_a_formato_base(df_envista)
        if len(df_convertido) == 0:
            print("Error: no se pudieron convertir los datos.")
            return None, None

        df_convertido = self.aplicar_banderas(df_convertido)
        df_validado   = self.validar_rangos(df_convertido)

        if archivo_salida is None:
            archivo_salida = f"Datos_Validados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        self.exportar_resultados(df_validado, archivo_salida)

        print("\n" + "=" * 60)
        print("PROCESO COMPLETADO EXITOSAMENTE")
        print("=" * 60)
        return df_validado, archivo_salida

    # ------------------------------------------------------------------
    def ejecutar_validacion_completa_desde_sheet(self, worksheet, archivo_salida: str = None):
        """Igual que ejecutar_validacion_completa, pero leyendo desde Google Sheets."""
        print("=" * 60)
        print("VALIDACIÓN COMPLETA DE DATOS DE CALIDAD DEL AIRE (Google Sheets)")
        print("=" * 60)

        df_envista = self.cargar_y_procesar_envista_desde_sheet(worksheet)
        if df_envista is None or len(df_envista) == 0:
            print("Error: no se pudieron cargar los datos ENVISTA.")
            return None, None

        df_convertido = self.convertir_a_formato_base(df_envista)
        if len(df_convertido) == 0:
            print("Error: no se pudieron convertir los datos.")
            return None, None

        df_convertido = self.aplicar_banderas(df_convertido)
        df_validado   = self.validar_rangos(df_convertido)

        if archivo_salida is None:
            archivo_salida = f"Datos_Validados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        self.exportar_resultados(df_validado, archivo_salida)

        print("\n" + "=" * 60)
        print("PROCESO COMPLETADO EXITOSAMENTE")
        print("=" * 60)
        return df_validado, archivo_salida


# ============================================================================
# SECCIÓN 2: FUNCIONES DE CÁLCULO IAS / NOM
# ============================================================================

# Toda esta seccion vive ahora en numeralia.dominio (calculo puro) y en
# numeralia.reporte.tema (colores). Se reexporta para no romper el resto del
# archivo mientras se migra la capa de presentacion.
from numeralia.dominio.nowcast import (                           # noqa: E402
    NowCast,
    rolling_8h,
    rolling_24h,
    round_half_up,
    serie_nowcast_por_estacion,
)
from numeralia.dominio.nom172 import (                            # noqa: E402
    CAT_ORDER,
    CAT_PUNTAJE,
    NOM_LIMITS,
    NOM_PRESETS,
    RANGOS,
    clasifica,
    select_nom_preset,
)
from numeralia.dominio.suficiencia import suf_min_yearly          # noqa: E402


# SECCIÓN 3: PIPELINE IAS / NOM
# ============================================================================

from numeralia.dominio.suficiencia import (                      # noqa: E402
    CONTAMINANTES as _CONTAMINANTES,
    INVALID_FLAGS as _INVALID_FLAGS,
    METEOROLOGIA as _METEOROLOGIA,
    SUF_MIN_HORAS as _SUF_MIN_HORAS,
)


def load_and_prepare_db(ruta_excel: str) -> Tuple[pd.DataFrame, int]:
    """Carga, limpia y prepara la base BD para los cálculos IAS/NOM."""
    ruta = Path(ruta_excel)
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró: {ruta_excel}")

    print("Cargando base de datos...")
    df = pd.read_excel(ruta_excel, sheet_name="Data", engine="openpyxl")
    df.columns = df.columns.str.strip().str.replace(' +', '_', regex=True)

    df['STATION'] = (df['STATION'].str.strip()
                     .apply(lambda x: re.sub(r'[^A-Za-z0-9 ]+', '', str(x)))
                     .str.strip())

    df.replace(_INVALID_FLAGS, np.nan, inplace=True)

    for c in _CONTAMINANTES + _METEOROLOGIA:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")

    if 'DATE' not in df.columns:
        raise KeyError("La base no tiene columna 'DATE'.")
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df = df.dropna(subset=["DATE"])
    df = df.sort_values(["STATION", "DATE"]).reset_index(drop=True)

    years, counts = np.unique(df["DATE"].dt.year.values, return_counts=True)
    anio = int(years[np.argmax(counts)])
    print(f"Base cargada: {ruta_excel} (año predominante: {anio})")
    return df, anio


def append_amg_station(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega la estación virtual AMG (máximo horario entre estaciones)."""
    if 'AMG' in df['STATION'].unique():
        df = df[df['STATION'] != 'AMG']

    max_hora = (df.groupby('DATE', observed=True)[_CONTAMINANTES]
                  .max(min_count=1).reset_index())
    amg = max_hora.copy()
    amg['STATION'] = 'AMG'
    for m in _METEOROLOGIA:
        if m in df.columns and m not in amg.columns:
            amg[m] = np.nan
    for col in df.columns:
        if col not in amg.columns:
            amg[col] = np.nan
    amg = amg[df.columns]

    return (pd.concat([df, amg], ignore_index=True)
              .sort_values(['STATION', 'DATE'])
              .reset_index(drop=True))


from numeralia.dominio.nom172 import (                            # noqa: E402
    redondear_por_nom as _round_by_nom,
)


def _daily_bounds(df_day: pd.DataFrame, pol: str):
    s = pd.to_numeric(df_day.get(pol, pd.Series(dtype=float)), errors="coerce")
    hv  = int(s.notna().sum())
    suf = hv >= _SUF_MIN_HORAS
    if not suf:
        return np.nan, np.nan, False, hv
    return (_round_by_nom(float(s.mean()), pol, "avg24"),
            _round_by_nom(float(s.max()),  pol, "max1h"),
            True, hv)


def _daily_max8h(df_day: pd.DataFrame, pol: str):
    col = f"{pol}_8H"
    if col not in df_day:
        return np.nan
    s = pd.to_numeric(df_day[col], errors="coerce").dropna()
    return np.nan if s.empty else _round_by_nom(float(s.max()), pol, "8h")


def _daily_nowcast_max(df_day: pd.DataFrame, pol: str):
    col = f"{pol}_NOWCAST"
    if col not in df_day:
        return np.nan
    s = pd.to_numeric(df_day[col], errors="coerce").dropna()
    return np.nan if s.empty else _round_by_nom(float(s.max()), pol, "nowcast")


def build_daily_table(dfh: pd.DataFrame) -> pd.DataFrame:
    dfh = dfh[dfh["STATION"] != "AMG"].copy()
    dfh["FECHA"] = pd.to_datetime(dfh["DATE"]).dt.date
    out = []
    for (est, fec), g in dfh.groupby(["STATION", "FECHA"], observed=True):
        row = {"STATION": est, "FECHA": pd.to_datetime(fec)}
        for pol in ['O3', 'NO2', 'SO2', 'CO', 'PM10', 'PM2.5']:
            if pol not in g.columns:
                continue
            avg24, mx1h, suf, hv = _daily_bounds(g, pol)
            row[f"{pol}_HORAS_VALIDAS"] = hv
            row[f"{pol}_AVG_24H"]       = avg24
            row[f"{pol}_MAX_1H"]        = mx1h
            row[f"{pol}_SUF_DIARIA"]    = bool(suf)
        row["O3_MAX_8H"]        = _daily_max8h(g, "O3")
        row["CO_MAX_8H"]        = _daily_max8h(g, "CO")
        row["PM10_NOWCAST_MAX"]  = _daily_nowcast_max(g, "PM10")
        row["PM2.5_NOWCAST_MAX"] = _daily_nowcast_max(g, "PM2.5")
        out.append(row)
    return (pd.DataFrame(out).sort_values(["STATION", "FECHA"]).reset_index(drop=True))


def rebuild_amg_from_daily(dfd: pd.DataFrame) -> pd.DataFrame:
    cols_max = [c for c in dfd.columns if c.endswith(("_AVG_24H","_MAX_1H","_MAX_8H","_NOWCAST_MAX"))]
    base = dfd.groupby("FECHA", observed=True)[cols_max].max(min_count=1).reset_index()
    amg  = base.copy()
    amg["STATION"] = "AMG"
    for pol in ["O3","NO2","SO2","CO","PM10","PM2.5"]:
        ref = (f"{pol}_MAX_8H"   if pol == "CO" else
               f"{pol}_AVG_24H"  if pol in ("PM10","PM2.5") else
               f"{pol}_MAX_1H")
        amg[f"{pol}_SUF_DIARIA"] = base[ref].notna().values.astype(bool)
    return amg[["STATION","FECHA"] + [c for c in amg.columns if c not in ["STATION","FECHA"]]]


from numeralia.dominio.nom172 import compute_nom_daily_flags      # noqa: E402
from numeralia.dominio.ias import (                                # noqa: E402
    IAS_SOURCE,
    ORDEN_DOM,
    compute_ias_daily,
)
from numeralia.dominio.nom172 import frac_rango as _frac_rango     # noqa: E402


# ── Constantes compartidas por los cálculos de numeralia ────────────────
_NOMERALIA_NOMBRE_A_COD = {
    'Águilas':'AGU', 'Vallarta':'VAL', 'Atemajac':'ATM', 'Country':'COU',
    'Santa Margarita':'SMT', 'Oblatos':'OBL', 'Centro':'CEN',
    'Loma Dorada':'LDO', 'Tlaquepaque':'TLA',
    'Pintas':'PIN', 'Santa Fe':'SFE', 'Santa Anita':'SAN', 'Miravalle':'MIR',
}
_NUMERALIA_CATS_MALA  = {"Mala","Muy mala","Extremadamente mala"}
_NUMERALIA_CATS_BUENA = {"Buena","Aceptable"}
_NUMERALIA_ZONAS = {
    'Poniente':['AGU','VAL'], 'Norte':['ATM','COU','SMT','OBL'],
    'Centro':['CEN'],         'Sureste':['LDO','TLA'],
    'Sur':['PIN','SFE','SAN','MIR'],
}
_NUMERALIA_ORDEN_FILAS = [
    ("Poniente", "Águilas",         "AGU"),
    ("Poniente", "Vallarta",         "VAL"),
    ("Norte",    "Atemajac",         "ATM"),
    ("Norte",    "Country",          "COU"),
    ("Norte",    "Santa Margarita",  "SMT"),
    ("Norte",    "Oblatos",          "OBL"),
    ("Centro",   "Centro",           "CEN"),
    ("Sureste",  "Loma Dorada",      "LDO"),
    ("Sureste",  "Tlaquepaque",      "TLA"),
    ("Sur",      "Pintas",           "PIN"),
    ("Sur",      "Santa Fe",         "SFE"),
    ("Sur",      "Santa Anita",      "SAN"),
    ("Sur",      "Miravalle",        "MIR"),
]


def _calcular_numeralia(dfd_all: pd.DataFrame, anio: int):
    """Calcula los conteos por estación y por zona que alimentan la numeralia."""
    dfd_est = dfd_all[dfd_all["STATION"] != "AMG"].copy()
    if "FECHA" in dfd_est.columns:
        dfd_est["_anio"] = pd.to_datetime(dfd_est["FECHA"]).dt.year
        dfd_est = dfd_est[dfd_est["_anio"] == anio]

    conteos = {}
    for est, g in dfd_est.groupby("STATION", observed=True):
        cats = g["IAS_GLOBAL_CAT_DIA"].dropna()
        malas    = int(cats.isin(_NUMERALIA_CATS_MALA).sum())
        buenas   = int(cats.isin(_NUMERALIA_CATS_BUENA).sum())
        sin_dato = max(0, len(g) - malas - buenas)
        conteos[est] = (malas, buenas, sin_dato)

    zona_totales = {}
    for zona, ests in _NUMERALIA_ZONAS.items():
        estaciones_zona = [(conteos.get(e, (0,0,0))[0], conteos.get(e, (0,0,0))[1])
                          for e in ests]
        if estaciones_zona:
            estacion_peor = max(estaciones_zona, key=lambda x: x[0])
            zona_totales[zona] = estacion_peor
        else:
            zona_totales[zona] = (0, 0)

    return conteos, zona_totales, dfd_est


def _tabla_numeralia(dfd_all: pd.DataFrame, anio: int) -> pd.DataFrame:
    """Arma el DataFrame de numeralia en el orden de _NUMERALIA_ORDEN_FILAS."""
    conteos, zona_totales, _ = _calcular_numeralia(dfd_all, anio)

    filas = []
    for zona, nombre_est, cod in _NUMERALIA_ORDEN_FILAS:
        malas, buenas, sin_dato = conteos.get(cod, (0, 0, 0))
        tot_mala, tot_buena = zona_totales.get(zona, (0, 0))
        filas.append({
            "Zona":                    zona,
            "Estación":                nombre_est,
            f"Días con mala calidad ({anio})":      malas,
            f"Días con buena o aceptable ({anio})": buenas,
            f"Días sin dato ({anio})":              sin_dato,
            "Total zona - mala":       tot_mala,
            "Total zona - buena/acep": tot_buena,
        })
    return pd.DataFrame(filas)


def exportar_numeralia_a_sheet(dfd_all: pd.DataFrame, anio: int, spreadsheet, hoja: str = "Procesada"):
    """Calcula la numeralia y la escribe en la pestaña `hoja` de la hoja de cálculo."""
    df_num = _tabla_numeralia(dfd_all, anio)

    worksheet = spreadsheet.worksheet(hoja)
    worksheet.clear()
    valores = _df_a_valores_sheet(df_num)
    worksheet.update(range_name="A1", values=valores)

    print(f"OK: Numeralia escrita en la hoja '{hoja}' ({len(df_num)} filas).")
    return df_num


def ejecutar_pipeline_ias(ruta_excel: str, spreadsheet=None, hoja_procesada: str = "Procesada"):
    """Carga la base BD, calcula IAS y NOM horario y diario, y exporta la numeralia a Sheets."""
    df, anio = load_and_prepare_db(ruta_excel)

    _fecha_max   = pd.to_datetime(df["DATE"]).max()
    print(f"Último dato en la base: {_fecha_max.date()}")

    df = append_amg_station(df)
    print("Estación virtual 'AMG' agregada.")

    print("\nCalculando promedios móviles...")
    if "HOUR" not in df.columns:
        df["HOUR"] = df["DATE"].dt.hour

    if "PM10" in df.columns:
        df["PM10_NOWCAST"] = (df.groupby("STATION", observed=True, group_keys=False)
                                .apply(lambda g: serie_nowcast_por_estacion(g, "PM10", 0)))
    if "PM2.5" in df.columns:
        df["PM2.5_NOWCAST"] = (df.groupby("STATION", observed=True, group_keys=False)
                                 .apply(lambda g: serie_nowcast_por_estacion(g, "PM2.5", 1)))

    for pol, fn, dec in [("PM10", rolling_24h, 0), ("PM2.5", rolling_24h, 0),
                         ("CO",   rolling_8h,  2), ("O3",   rolling_8h,  3)]:
        if pol in df.columns:
            sufijo = "24H" if pol in ("PM10","PM2.5") else "8H"
            df[f"{pol}_{sufijo}_RAW"] = (df.groupby("STATION", observed=True)[pol]
                                           .apply(fn).reset_index(level=0, drop=True))
            df[f"{pol}_{sufijo}"] = df[f"{pol}_{sufijo}_RAW"].apply(
                lambda v: round_half_up(v, dec))

    for pol, dec in [("O3",3),("NO2",3),("SO2",3),("CO",2)]:
        if pol in df.columns:
            df[f"{pol}_1H"] = df[pol].apply(lambda v: round_half_up(v, dec))

    print("Calculando IAS horario...")
    col_val = {}
    for k,v in [("PM10","PM10_NOWCAST"),("PM2.5","PM2.5_NOWCAST"),
                ("CO","CO_8H"),("O3","O3_1H"),("NO2","NO2_1H"),("SO2","SO2_1H")]:
        if v in df.columns:
            col_val[k] = v

    orden_h = ["PM2.5","O3","PM10","NO2","SO2","CO"]
    for pol, colv in col_val.items():
        df[f"IAS_{pol}_VALOR"] = df[colv]
        df[[f"IAS_{pol}_CAT", f"IAS_{pol}_SCORE"]] = df[colv].apply(
            lambda v: pd.Series(clasifica(v, pol)))

    score_cols_h = [f"IAS_{p}_SCORE" for p in orden_h if f"IAS_{p}_SCORE" in df.columns]
    if score_cols_h:
        dom_score = df[score_cols_h].max(axis=1)
        dom_pol   = pd.Series(index=df.index, dtype=object)
        dom_cat   = pd.Series(index=df.index, dtype=object)
        for pol in reversed(orden_h):
            col = f"IAS_{pol}_SCORE"
            if col not in df.columns:
                continue
            mask = (df[col] == dom_score) & dom_score.notna()
            dom_pol[mask] = pol
            dom_cat[mask] = df.loc[mask, f"IAS_{pol}_CAT"]
        df["IAS_GLOBAL_POL"]   = dom_pol
        df["IAS_GLOBAL_CAT"]   = dom_cat
        df["IAS_GLOBAL_SCORE"] = dom_score

    print("Calculando cumplimiento NOM horario...")
    def _c1h(v, lim):
        return None if pd.isna(v) else ("Si" if v <= lim else "No")

    if {"O3_1H","O3_8H"}.issubset(df.columns):
        df["NOM_O3_CUMPLE"] = df.apply(
            lambda r: None if (pd.isna(r["O3_1H"]) and pd.isna(r["O3_8H"])) else
                      ("Si" if (r["O3_1H"] <= NOM_LIMITS["O3"]["1H"] and
                                r["O3_8H"] <= NOM_LIMITS["O3"]["8H"]) else "No"), axis=1)
    if "NO2_1H" in df.columns:
        df["NOM_NO2_1H_CUMPLE"] = df["NO2_1H"].apply(lambda v: _c1h(v, NOM_LIMITS["NO2"]["1H"]))
    if "SO2_1H" in df.columns:
        df["NOM_SO2_1H_CUMPLE"] = df["SO2_1H"].apply(lambda v: _c1h(v, NOM_LIMITS["SO2"]["1H"]))
    if {"CO_1H","CO_8H"}.issubset(df.columns):
        df["NOM_CO_CUMPLE"] = df.apply(
            lambda r: None if (pd.isna(r["CO_1H"]) and pd.isna(r["CO_8H"])) else
                      ("Si" if (r["CO_1H"] <= NOM_LIMITS["CO"]["1H"] and
                                r["CO_8H"] <= NOM_LIMITS["CO"]["8H"]) else "No"), axis=1)
    if "PM10_24H" in df.columns:
        df["NOM_PM10_24H_CUMPLE"]  = df["PM10_24H"].apply(lambda v: _c1h(v, NOM_LIMITS["PM10"]["24H"]))
    if "PM2.5_24H" in df.columns:
        df["NOM_PM2.5_24H_CUMPLE"] = df["PM2.5_24H"].apply(lambda v: _c1h(v, NOM_LIMITS["PM2.5"]["24H"]))

    print("\nConstruyendo tabla diaria...")
    dfd       = build_daily_table(df)
    amg_daily = rebuild_amg_from_daily(dfd)
    dfd_all   = (pd.concat([dfd, amg_daily], ignore_index=True, sort=False)
                   .sort_values(["STATION","FECHA"]).reset_index(drop=True))

    _fecha_max_dia = pd.to_datetime(_fecha_max.date())
    dfd_all = dfd_all[pd.to_datetime(dfd_all["FECHA"]) <= _fecha_max_dia].copy()

    print("Calculando NOM diario...")
    dfd_all = compute_nom_daily_flags(dfd_all)
    print("Calculando IAS diario...")
    dfd_all = compute_ias_daily(dfd_all)

    exportar_numeralia_a_sheet(dfd_all, anio, spreadsheet, hoja_procesada)

    print("\n Pipeline IAS/NOM completado.")
    return dfd_all


def _anio_de_numeralia(numeralia: pd.DataFrame) -> Optional[int]:
    """
    Deduce el año leyendo los encabezados de la numeralia, que vienen como
    'Días con mala calidad (2025)'.
    """
    for c in numeralia.columns:
        m = re.search(r'\((\d{4})\)', str(c))
        if m:
            return int(m.group(1))
    return None


HOJA_CONTROL_ACUMULADO = "Acumuladas"


def _hoja_control(spreadsheet, nombre: str = HOJA_CONTROL_ACUMULADO):
    """
    Devuelve la pestaña donde se lleva registro de qué días ya se sumaron a
    'Analitica'. La crea vacía la primera vez.
    """
    try:
        return spreadsheet.worksheet(nombre)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=nombre, rows=400, cols=3)
        ws.update(range_name="A1", values=[["Año", "Fecha", "Registrado"]])
        print(f"Nota: Se creó la hoja de control '{nombre}' (estaba vacía: "
              f"se asume que no hay días acumulados todavía).")
        return ws


def _fechas_ya_acumuladas(spreadsheet, anio: int) -> set:
    """Fechas (date) de ese año que ya se sumaron a 'Analitica' en corridas previas."""
    filas = _hoja_control(spreadsheet).get_all_records()
    fechas = set()
    for fila in filas:
        try:
            if int(fila.get("Año", 0)) != anio:
                continue
        except (TypeError, ValueError):
            continue
        fecha = pd.to_datetime(fila.get("Fecha"), errors="coerce")
        if pd.notna(fecha):
            fechas.add(fecha.date())
    return fechas


def _registrar_fechas_acumuladas(spreadsheet, anio: int, fechas) -> None:
    """Anota las fechas recién sumadas para que la próxima corrida no las repita."""
    ws = _hoja_control(spreadsheet)
    sello = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ws.append_rows([[str(anio), f.strftime('%Y-%m-%d'), sello] for f in sorted(fechas)])


def actualizar_acumulado(spreadsheet, anio_actual: Optional[int] = None,
                          hoja_procesada: str = "Procesada",
                          hoja_analitica: str = "Analitica",
                          dfd_all: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Suma la numeralia del día (hoja 'Procesada') al acumulado histórico
    ('Analitica').

    El año NO se toma del reloj ni del parámetro: se lee de los encabezados
    de la numeralia, que a su vez salen del año predominante en los datos de
    'Cruda'. Esa es la única fuente de verdad — si Cruda trae datos de 2025,
    la numeralia dice 2025 y hay que sumarla a las columnas de 2025, sin
    importar en qué año estemos hoy. Cuando ambos no coincidían, el proceso
    tronaba buscando una columna inexistente.

    `anio_actual` se conserva solo para avisar si difiere de lo que traen
    los datos, porque casi siempre significa que Cruda no está actualizada.

    La suma es acumulativa, así que repetirla duplicaría los días. Para que
    volver a correr el pipeline sea inofensivo —algo que se hace todo el
    tiempo, aunque sea solo para ver el dashboard— se lleva registro de qué
    fechas ya se sumaron en la hoja 'Acumuladas'. Si `dfd_all` viene con la
    tabla diaria, solo se suman los días que no estén registrados; si no
    queda ninguno nuevo, no se escribe nada y el pipeline sigue derecho.
    """
    numeralia = pd.DataFrame(spreadsheet.worksheet(hoja_procesada).get_all_records())

    anio = _anio_de_numeralia(numeralia)
    if anio is None:
        raise ValueError(
            f"No se pudo deducir el año de la hoja '{hoja_procesada}'. "
            f"Se esperaban encabezados como 'Días con mala calidad (2026)'. "
            f"Columnas encontradas: {list(numeralia.columns)}")

    if anio_actual is not None and anio_actual != anio:
        print(f"AVISO: Los datos de '{hoja_procesada}' son del año {anio}, no de {anio_actual}. "
              f"Se actualizará el acumulado de {anio}.")
        print(f"  Si esperabas {anio_actual}, revisa que la hoja 'Cruda' tenga datos de ese año.")

    ws_analitica = spreadsheet.worksheet(hoja_analitica)
    acumulado = pd.DataFrame(ws_analitica.get_all_records())

    col_mala    = f"{anio}: Días con mala calidad"
    col_buena   = f"{anio}: Días con buena a aceptable"
    col_sindato = f"{anio}: Días sin dato"

    faltantes = [c for c in (col_mala, col_buena, col_sindato)
                 if c not in acumulado.columns]
    if faltantes:
        raise ValueError(
            f"A la hoja '{hoja_analitica}' le faltan estas columnas: {faltantes}. "
            f"Columnas que sí tiene: {list(acumulado.columns)}")

    # Solo se suman los días que no se hayan sumado antes. Sin la tabla diaria
    # no hay forma de saber de qué fechas habla la numeralia, así que en ese
    # caso se conserva el comportamiento de siempre.
    fechas_nuevas = None
    if dfd_all is not None and "FECHA" in dfd_all.columns:
        # Solo las fechas DEL AÑO detectado: la numeralia descarta las demás
        # (ver _calcular_numeralia), así que registrarlas diría que se sumaron
        # días que en realidad nunca se contaron. Pasa de verdad en el cambio
        # de año, cuando 'Cruda' trae el 31 de diciembre y el 1 de enero.
        _f = pd.to_datetime(dfd_all["FECHA"]).dropna()
        fechas_datos = {f.date() for f in _f[_f.dt.year == anio].unique()}
        ya_sumadas = _fechas_ya_acumuladas(spreadsheet, anio)
        fechas_nuevas = sorted(fechas_datos - ya_sumadas)

        if not fechas_nuevas:
            repetidas = ', '.join(f.strftime('%d/%b/%Y') for f in sorted(fechas_datos))
            print(f"Los días de 'Cruda' ({repetidas}) ya estaban sumados en "
                  f"'{hoja_analitica}'. No se suma nada; el resto del pipeline sigue igual.")
            return acumulado

        # Se recalcula la numeralia contando únicamente los días nuevos, para
        # que un 'Cruda' que trae días viejos y nuevos mezclados solo aporte
        # los que faltan.
        solo_nuevas = dfd_all[pd.to_datetime(dfd_all["FECHA"]).dt.date.isin(fechas_nuevas)]
        numeralia = _tabla_numeralia(solo_nuevas, anio)
        omitidas = len(fechas_datos) - len(fechas_nuevas)
        detalle = ', '.join(f.strftime('%d/%b') for f in fechas_nuevas)
        print(f"  Días nuevos a sumar: {len(fechas_nuevas)} ({detalle})"
              + (f"; {omitidas} ya estaban sumados y se omiten." if omitidas else "."))

    acumulado[col_mala]    = acumulado[col_mala]    + numeralia[f"Días con mala calidad ({anio})"]
    acumulado[col_buena]   = acumulado[col_buena]   + numeralia[f"Días con buena o aceptable ({anio})"]
    acumulado[col_sindato] = acumulado[col_sindato] + numeralia[f"Días sin dato ({anio})"]

    ws_analitica.clear()
    df_serializable = acumulado.astype(str).replace(["None", "NaN", "nan", "NaT", "<NA>"], "")
    datos_a_subir = [df_serializable.columns.values.tolist()] + df_serializable.values.tolist()
    ws_analitica.update(range_name="A1", values=datos_a_subir)

    # El registro va después de escribir: si algo truena antes, la fecha no
    # queda marcada y el próximo intento la vuelve a sumar, en vez de darla
    # por buena sin estarlo.
    if fechas_nuevas:
        _registrar_fechas_acumuladas(spreadsheet, anio, fechas_nuevas)

    print(f"OK: Acumulado actualizado en '{hoja_analitica}' para el año {anio}.")
    return acumulado


# ============================================================================
# SECCIÓN 4: EPISODIOS + IMECA MÁXIMO
# ============================================================================

_MESES_ES_A_NUM = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}


def _parse_spanish_date(date_str):
    """
    Convierte fechas en español escritas a mano a datetime.

    Es deliberadamente tolerante, porque en las hojas conviven formatos muy
    distintos y antes cualquier variante se descartaba en silencio (devolvía
    NaT) y esa fila desaparecía de los conteos. Acepta, entre otros:

        jueves, 1 de enero de 2026, 6:00
        Miércoles 29 de abril de 2026 7:00      (sin comas)
        Viernes 8 de mayo de 2026 12:00 hor     (con texto de sobra al final)
        sábado, 2 de mayo de 2026               (sin hora -> 00:00)
        MARTES, 19 DE MAYO DE 2026, 18:00       (mayúsculas, con acentos)

    Lo único indispensable es el patrón 'día de mes de año'; la hora es
    opcional y se ignora cualquier texto adicional.
    """
    if not isinstance(date_str, str):
        return pd.NaT

    texto = _sin_acentos(date_str).lower()

    m = re.search(r'(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})', texto)
    if not m:
        return pd.NaT

    dia, mes_texto, anio = m.groups()
    mes = _MESES_ES_A_NUM.get(mes_texto)
    if mes is None:
        return pd.NaT

    # La hora se busca DESPUÉS de la fecha, para no confundirse con algún
    # número que venga antes. Si no hay, se asume medianoche.
    h = re.search(r'(\d{1,2}):(\d{2})', texto[m.end():])
    hora, minuto = (int(h.group(1)), int(h.group(2))) if h else (0, 0)

    try:
        return pd.Timestamp(int(anio), mes, int(dia), min(hora, 23), min(minuto, 59))
    except ValueError:
        return pd.NaT


_MESES_EN_A_ES = {
    "January":"enero","February":"febrero","March":"marzo","April":"abril",
    "May":"mayo","June":"junio","July":"julio","August":"agosto",
    "September":"septiembre","October":"octubre","November":"noviembre","December":"diciembre",
}


def _fecha_es(fecha: datetime) -> str:
    s = fecha.strftime("%d de %B")
    for en, es in _MESES_EN_A_ES.items():
        s = s.replace(en, es)
    return s


def _contar_episodios(df: pd.DataFrame) -> Dict[str, int]:
    """Cuenta episodios por tipo de evento y contaminante."""
    resultados = {}
    contaminante = df['Contaminante'].str.strip().str.replace(' ', '', regex=False)
    evento = df['Evento'].str.strip()

    mask_pre = evento == 'PreContingencia Atmosférica'
    resultados['Precontingencias atmosféricas:'] = int(mask_pre.sum())
    resultados['   Precontingencias declaradas por Ozono'] = int((mask_pre & (contaminante == 'O3')).sum())
    resultados['   Precontingencias declaradas por PM10'] = int((mask_pre & (contaminante == 'PM10')).sum())
    resultados['   Precontingencias declaradas por PM2.5'] = int((mask_pre & (contaminante == 'PM2.5')).sum())

    mask_f1 = evento == 'Contingencia Atmosférica Fase I'
    resultados['Contingencias atmosféricas Fase I:'] = int(mask_f1.sum())
    resultados['   Contingencias declaradas por Ozono'] = int((mask_f1 & (contaminante == 'O3')).sum())
    resultados['   Contingencias declaradas por PM10'] = int((mask_f1 & (contaminante == 'PM10')).sum())
    resultados['   Contingencias declaradas por PM2.5'] = int((mask_f1 & (contaminante == 'PM2.5')).sum())

    mask_f2 = evento == 'Contingencia Atmosférica Fase II'
    resultados['Contingencias atmosféricas Fase II:'] = int(mask_f2.sum())

    mask_f3 = evento == 'Contingencia Atmosférica Fase III'
    resultados['Contingencias atmosféricas Fase III:'] = int(mask_f3.sum())

    resultados['Episodios Totales'] = len(df)
    return resultados


def cargar_episodios(gc, url_fuente_2025: str, url_fuente_2026: str):
    """Lee las hojas fuente 2025/2026 de episodios y devuelve los DataFrames + spreadsheets abiertos."""
    sh_2025 = gc.open_by_url(url_fuente_2025)
    df_2025 = _worksheet_a_df(sh_2025.worksheet("Episodios 2025"))

    sh_2026 = gc.open_by_url(url_fuente_2026)
    df_2026 = _worksheet_a_df(sh_2026.worksheet("Nuevo episodios 2026"))

    df_2025_ = df_2025.iloc[:, 0:17].copy()
    df_2026_ = df_2026.iloc[:, 0:9].copy()

    df_2025_['Dia de inicio'] = pd.to_datetime(df_2025_['Dia de inicio'], dayfirst=True, errors='coerce')
    df_2025_['IMECA'] = pd.to_numeric(df_2025_['IMECA'], errors='coerce')

    df_2026_['Inicio'] = df_2026_['Inicio'].apply(_parse_spanish_date)
    df_2026_['IMECA'] = pd.to_numeric(df_2026_['IMECA'], errors='coerce')

    return df_2025_, df_2026_, sh_2025, sh_2026


def _corte_mismo_periodo(anio: int) -> datetime:
    """
    Fecha límite del criterio 'mismo periodo del calendario' para el año dado:
    del 1 de enero de ese año hasta el mismo día/mes que ayer (hoy - 1 día).
    Es el mismo criterio que ya se usaba (en línea) para Episodios; se deja
    aquí como función reutilizable para poder aplicarlo también a Alertas y,
    en años futuros, a cualquier comparación año-actual-parcial vs año(s)
    anteriores completos, sin tener que reescribir la lógica: solo se llama
    _corte_mismo_periodo(el_año_que_sea).
    """
    ayer = datetime.now() - timedelta(days=1)
    return datetime(anio, ayer.month, ayer.day, 23, 59, 59)


def calcular_comparativo_episodios(df_2025_: pd.DataFrame, df_2026_: pd.DataFrame) -> pd.DataFrame:
    """Compara episodios activados 2025 vs 2026 en el mismo periodo del calendario (1 ene -> ayer)."""
    ayer = datetime.now() - timedelta(days=1)
    dia_ayer = ayer.day

    corte_2025 = _corte_mismo_periodo(2025)
    corte_2026 = _corte_mismo_periodo(2026)

    df_2025_parcial = df_2025_[df_2025_['Dia de inicio'] <= corte_2025]

    # Igual que en Alertas: una fecha ilegible no debe hacer desaparecer el
    # episodio del conteo. Se conserva y se avisa para corregir la hoja.
    sin_fecha_26 = df_2026_['Inicio'].isna()
    if sin_fecha_26.any():
        print(f"AVISO: {int(sin_fecha_26.sum())} episodio(s) de 2026 tienen fecha de inicio "
              f"ilegible; se cuentan de todos modos.")
    df_2026_parcial = df_2026_[sin_fecha_26 | (df_2026_['Inicio'] <= corte_2026)]

    res_2025 = _contar_episodios(df_2025_parcial)
    res_2026 = _contar_episodios(df_2026_parcial)

    fecha_str_ayer = _fecha_es(ayer)
    mes_nombre_ayer = fecha_str_ayer.split(" de ")[1]

    comparativo = pd.DataFrame({
        'Episodios activados': list(res_2025.keys()),
        f'2025 (1 ene - {dia_ayer} {mes_nombre_ayer})': list(res_2025.values()),
        f'2026 (1 ene - {dia_ayer} {mes_nombre_ayer})': list(res_2026.values()),
    }).set_index('Episodios activados')

    print(f"Comparativa al mismo periodo: 1 de enero al {fecha_str_ayer} (día de ayer)")
    print(f"  2025 filtrado: {len(df_2025_parcial)} episodios (de {len(df_2025_)} totales)")
    print(f"  2026 filtrado: {len(df_2026_parcial)} episodios (de {len(df_2026_)} totales)")

    return comparativo


def calcular_imeca_maximo(df_2025_: pd.DataFrame, df_2026_: pd.DataFrame) -> pd.DataFrame:
    """IMECA máximo registrado en el año para 2025 y 2026 (sin filtrar por periodo)."""
    max_imeca_2025 = df_2025_['IMECA'].max()
    df_max_2025 = df_2025_[df_2025_['IMECA'] == max_imeca_2025].copy()
    df_max_2025['_dt'] = pd.to_datetime(
        df_max_2025['Dia de inicio'].astype(str) + ' ' + df_max_2025['Hora de inicio'].astype(str),
        errors='coerce'
    )
    row_2025 = df_max_2025.sort_values('_dt').iloc[0]

    max_imeca_2026 = df_2026_['IMECA'].max()
    df_max_2026 = df_2026_[df_2026_['IMECA'] == max_imeca_2026].copy()
    row_2026 = df_max_2026.sort_values('Inicio').iloc[0]

    fecha_max_2025 = pd.Timestamp(row_2025['Dia de inicio']).strftime('%d/%m/%Y')
    hora_max_2025 = str(row_2025['Hora de inicio'])

    inicio_max_2026 = pd.Timestamp(row_2026['Inicio'])
    fecha_max_2026 = inicio_max_2026.strftime('%d/%m/%Y')
    hora_max_2026 = inicio_max_2026.strftime('%I:%M %p')

    imeca_max = pd.DataFrame({
        '2025': [max_imeca_2025, row_2025['Contaminante'], row_2025['Estación'], fecha_max_2025, hora_max_2025],
        '2026': [max_imeca_2026, row_2026['Contaminante'], row_2026['Estación'], fecha_max_2026, hora_max_2026],
    }, index=['IMECA Máximo del año', 'Contaminante', 'Estación', 'Fecha', 'Hora'])
    imeca_max.index.name = 'Periodo anual comparativo'

    return imeca_max


def run_episodios(gc, spreadsheet_destino, url_fuente_2025: str, url_fuente_2026: str,
                   hoja_episodios: str = "Episodios", hoja_imeca: str = "IMECA MAXIMO"):
    """Calcula Episodios + IMECA máximo y los escribe en el spreadsheet destino."""
    df_2025_, df_2026_, sh_2025, sh_2026 = cargar_episodios(gc, url_fuente_2025, url_fuente_2026)

    comparativo_parcial = calcular_comparativo_episodios(df_2025_, df_2026_)
    imeca_max = calcular_imeca_maximo(df_2025_, df_2026_)

    # _df_nativo antes de escribir: gspread no sabe serializar tipos de NumPy.
    ws_ep = spreadsheet_destino.worksheet(hoja_episodios)
    ws_ep.clear()
    set_with_dataframe(ws_ep, _df_nativo(comparativo_parcial.reset_index()), include_index=False)
    print(f"OK: Episodios actualizados en '{hoja_episodios}'.")

    ws_im = spreadsheet_destino.worksheet(hoja_imeca)
    ws_im.clear()
    set_with_dataframe(ws_im, _df_nativo(imeca_max.reset_index()))
    print(f"OK: IMECA máximo actualizado en '{hoja_imeca}'.")

    # Se regresan sh_2025 / sh_2026 para que Alertas reutilice la misma conexión
    # (son los mismos spreadsheets fuente, solo cambian de pestaña).
    return sh_2025, sh_2026


# ============================================================================
# SECCIÓN 5: ALERTAS
# ============================================================================

def _contar_alertas(df: pd.DataFrame) -> Dict[str, int]:
    resultados = {}
    fase = df['Fase Decretada'].str.strip()
    resultados['Alertas:'] = int((fase == 'Alerta').sum())
    resultados['Emergencias:'] = int((fase == 'Emergencia').sum())
    resultados['Total Alertas y Emergencias'] = resultados['Alertas:'] + resultados['Emergencias:']
    return resultados


def run_alertas(sh_2025, sh_2026, spreadsheet_destino, hoja_alertas: str = "ALERTAS"):
    """
    Calcula Alertas/Emergencias 2025 vs 2026 y las escribe en el spreadsheet
    destino. Igual que Episodios y Contingencias/Precontingencias, ambos años
    se recortan al MISMO periodo del calendario (1 de enero -> ayer) usando
    _corte_mismo_periodo(), así el 2025 no cuenta el año completo, solo hasta
    la fecha a la que ya vamos en 2026. El 2026 se recorta con el mismo
    criterio por consistencia (en la práctica ya no tiene filas más allá de
    "ayer"). Esto es genérico para años futuros: cuando 2026 sea el año
    histórico completo y 2027 el parcial, basta con que las hojas fuente
    sigan el mismo patrón de columnas.
    """
    df_2025_A = _worksheet_a_df(sh_2025.worksheet("Alertas 2025")).iloc[:, 0:14].copy()
    df_2026_A = _worksheet_a_df(sh_2026.worksheet("NUEVO alertas 2026")).iloc[:, 0:11].copy()
    total_2025, total_2026 = len(df_2025_A), len(df_2026_A)

    # Columna de fecha de inicio: se busca por nombre (sin acentos/mayúsculas)
    # en vez de asumir un nombre fijo, para no romper si la hoja cambia un
    # poco el encabezado.
    col_fecha_2025 = _buscar_columna(list(df_2025_A.columns), 'dia de inicio', 'fecha de inicio', 'fecha inicio')
    col_fecha_2026 = _buscar_columna(list(df_2026_A.columns), 'inicio')

    if col_fecha_2025 is not None:
        df_2025_A['_fecha_inicio'] = pd.to_datetime(df_2025_A[col_fecha_2025], dayfirst=True, errors='coerce')
        df_2025_A = df_2025_A[df_2025_A['_fecha_inicio'] <= _corte_mismo_periodo(2025)]
    else:
        print("AVISO: No se encontró columna de fecha de inicio en 'Alertas 2025'; "
              "no se aplicó el filtro de mismo periodo (se cuenta el año completo).")

    if col_fecha_2026 is not None:
        df_2026_A['_fecha_inicio'] = df_2026_A[col_fecha_2026].apply(_parse_spanish_date)

        # Las filas con fecha ilegible se CONSERVAN en vez de descartarse.
        # Antes se perdían en silencio y el conteo de 2026 salía más bajo de
        # lo real. Se avisa cuáles son para poder corregirlas en la hoja.
        sin_fecha = df_2026_A['_fecha_inicio'].isna() & (
            df_2026_A[col_fecha_2026].astype(str).str.strip() != '')
        if sin_fecha.any():
            print(f"AVISO: {int(sin_fecha.sum())} fila(s) de 'NUEVO alertas 2026' tienen una "
                  f"fecha que no se pudo interpretar; se cuentan de todos modos:")
            for v in df_2026_A.loc[sin_fecha, col_fecha_2026].astype(str).head(10):
                print(f"    · {v!r}")

        df_2026_A = df_2026_A[df_2026_A['_fecha_inicio'].isna()
                              | (df_2026_A['_fecha_inicio'] <= _corte_mismo_periodo(2026))]
    else:
        print("AVISO: No se encontró columna de fecha de inicio en 'NUEVO alertas 2026'; "
              "no se aplicó el filtro de mismo periodo (se cuenta el año completo).")

    alertas_2025 = _contar_alertas(df_2025_A)
    alertas_2026 = _contar_alertas(df_2026_A)

    fecha_str_ayer = _fecha_es(datetime.now() - timedelta(days=1))
    print(f"Comparativa de Alertas al mismo periodo: 1 de enero al {fecha_str_ayer} (día de ayer)")
    print(f"  2025 filtrado: {len(df_2025_A)} filas (de {total_2025} totales)")
    print(f"  2026 filtrado: {len(df_2026_A)} filas (de {total_2026} totales)")

    comparativo_alertas = pd.DataFrame({
        '2025': list(alertas_2025.values()),
        '2026': list(alertas_2026.values()),
    }, index=list(alertas_2025.keys()))
    comparativo_alertas.index.name = 'Categoría'

    ws = spreadsheet_destino.worksheet(hoja_alertas)
    ws.clear()
    set_with_dataframe(ws, _df_nativo(comparativo_alertas.reset_index()))
    print(f"OK: Alertas actualizadas en '{hoja_alertas}'.")


# ============================================================================
# SECCIÓN 6: DASHBOARD (Dash)
# ============================================================================
#
# Todo el dashboard vive ahora en numeralia.reporte (formato, figuras,
# datos_graficas, kpis, tablas, tarjetas y app) y en assets/dashboard.js.
# run_full_pipeline solo necesita estas tres piezas del ensamblado:

from numeralia.reporte.app import (                            # noqa: E402
    _leer_datos_de_sheets,
    build_dash_app,
    exportar_datos_dashboard,
)
# Los siguen usando _parse_spanish_date (Sección 4) y run_alertas (Sección 5).
from numeralia.reporte.formato import _buscar_columna, _sin_acentos  # noqa: E402


# ============================================================================
# SECCIÓN 7: ORQUESTADOR PRINCIPAL — un solo punto de entrada
# ============================================================================

# Las URLs se leen del .env. Los valores de aquí son solo el respaldo para
# que el archivo siga corriendo tal cual en Colab; en un repositorio
# conviene dejarlos vacíos y definir todo en el .env.
#
# Hoja destino: contiene Cruda, Procesada, Analitica, Episodios, IMECA MAXIMO, ALERTAS
# Las URLs se resuelven en numeralia.config a partir del .env. Los valores
# de respaldo se conservan para que el archivo siga corriendo tal cual en
# Colab, donde no hay .env.
from numeralia.config import Config                                # noqa: E402

CONFIG = Config.desde_env()

URL_DESTINO = CONFIG.urls.get('destino') or \
    "https://docs.google.com/spreadsheets/d/1NaEdWeSOME_UV2ucOrQav_LMPNihOVhmGOtSt-HCAkA/edit"
URL_FUENTE_2025 = CONFIG.urls.get('fuente_2025') or \
    "https://docs.google.com/spreadsheets/d/1e6iSYmEbRxWQiLnhEl3C1vpZsJ4TG-tTV9aU78-E-c4/edit"
URL_FUENTE_2026 = CONFIG.urls.get('fuente_2026') or \
    "https://docs.google.com/spreadsheets/d/1Kzr8qWd0cew_CF-KOvukmS6Qo4Ry9O6md_EBqtqWv4k/edit"
URL_RESUMEN_MENSUAL = CONFIG.urls.get('resumen_mensual') or \
    "https://docs.google.com/spreadsheets/d/1cAICszRtOI1j9ZDDyqhnekEEUXDNCJXJQYWU-xddzMs/edit"


def run_full_pipeline(anio_actual: Optional[int] = None, lanzar_dashboard: bool = True,
                       puerto: int = 8050,
                       exportar_json: Optional[str] = None) -> pd.DataFrame:
    """
    Corre TODO el pipeline de punta a punta con una sola llamada:
      1) Cruda -> validación -> IAS/NOM -> Procesada
      2) Procesada + Analítica -> acumulado actualizado en Analítica
      3) Episodios (2025 vs 2026, mismo periodo) + IMECA máximo
      4) Alertas / Emergencias (2025 vs 2026)
      5) (opcional) Levanta el dashboard con el acumulado fresco
    """
    gc = autenticar()
    spreadsheet_destino = gc.open_by_url(URL_DESTINO)

    print("\n========== 1) NUMERALIA (Cruda -> Procesada -> Analítica) ==========")
    worksheet_cruda = spreadsheet_destino.worksheet("Cruda")
    archivo_bd = os.path.join(str(Path.cwd()), f"BD_{datetime.now().year}.xlsx")

    validador = ValidadorCalidadAire()
    resultado, archivo_bd = validador.ejecutar_validacion_completa_desde_sheet(worksheet_cruda, archivo_bd)
    if resultado is None:
        raise RuntimeError("La validación ENVISTA falló. Proceso cancelado.")

    # La tabla diaria se conserva: trae la FECHA de cada día calculado, que es
    # lo que permite sumar a 'Analitica' solo los días que aún no se sumaron.
    dfd_all = ejecutar_pipeline_ias(archivo_bd, spreadsheet=spreadsheet_destino,
                                     hoja_procesada="Procesada")

    if anio_actual is None:
        anio_actual = int(input("Año actual: "))
    acumulado = actualizar_acumulado(spreadsheet_destino, anio_actual, dfd_all=dfd_all)

    print("\n========== 2) EPISODIOS + IMECA MÁXIMO ==========")
    sh_2025, sh_2026 = run_episodios(gc, spreadsheet_destino, URL_FUENTE_2025, URL_FUENTE_2026)

    print("\n========== 3) ALERTAS ==========")
    run_alertas(sh_2025, sh_2026, spreadsheet_destino)

    print("\n Pipeline completo terminado.")

    # Los datos del dashboard se leen una sola vez y se reutilizan para las
    # dos salidas: el JSON que consume el servidor y el dashboard local.
    datos_dashboard = None
    if exportar_json or lanzar_dashboard:
        datos_dashboard = _leer_datos_de_sheets(gc, spreadsheet_destino, acumulado)

    if exportar_json:
        exportar_datos_dashboard(datos_dashboard, exportar_json)

    if lanzar_dashboard:
        app = build_dash_app(gc, spreadsheet_destino, acumulado, datos=datos_dashboard)
        if _en_colab():
            # jupyter_mode solo existe dentro de un notebook; fuera truena.
            app.run(jupyter_mode='external', debug=False)
        else:
            print(f"\nDashboard en http://127.0.0.1:{puerto}  (Ctrl+C para detener)")
            app.run(host='0.0.0.0', port=puerto, debug=False)

    return acumulado


if __name__ == "__main__":
    # El punto de entrada del proyecto es numeralia.cli, no este archivo.
    # Aquí solo se le delega para que `python main.py` siga
    # funcionando igual que `python -m numeralia`, con los mismos argumentos
    # y el mismo arreglo de UTF-8 en Windows.
    import sys

    from numeralia.cli import main

    raise SystemExit(main(sys.argv[1:]))
