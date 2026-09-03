# ============================================================================
# PIPELINE COMPLETO — Calidad del Aire SEMADET
# Numeralia (Cruda -> Procesada -> Analítica) + Episodios + IMECA Máximo +
# Alertas + Dashboard (Dash), todo en una sola corrida.
#
# CÓMO USARLO EN COLAB
# ---------------------------------------------------------------------------
# 1) En la PRIMERA celda de tu notebook (una sola vez por sesión), instala
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
import json
import base64
import shutil
import calendar
import warnings
import unicodedata
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Tuple, Optional

import numpy as np
import openpyxl
import pandas as pd
import gspread
from google.auth import default
from gspread.http_client import BackOffHTTPClient
from gspread_dataframe import set_with_dataframe

from dash import Dash, html, dcc, dash_table, Input, Output, State, callback_context
import plotly.express as px
import plotly.graph_objects as go

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
from numeralia.cache import cache_sheets                            # noqa: E402
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


def _worksheet_a_df(ws) -> pd.DataFrame:
    """Lee todos los valores de una worksheet y arma un DataFrame (fila 1 = encabezados)."""
    valores = ws.get_all_values()
    headers, filas = valores[0], valores[1:]
    df = pd.DataFrame(filas, columns=headers)
    df.columns = df.columns.str.strip()
    return df


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


def _a_valor_nativo(v):
    """
    Convierte un valor de NumPy/pandas a un tipo nativo de Python.

    Hace falta porque las versiones recientes de gspread serializan a JSON
    con allow_nan=False y sin conversores para NumPy: un numpy.int64 —que es
    lo que devuelve .max() de pandas— truena con 'Object of type int64 is
    not JSON serializable'. En Colab no se nota porque trae versiones más
    permisivas, pero al correr como .py aparece.

    Los NaN se mandan como cadena vacía, que es como Sheets representa una
    celda sin dato.
    """
    if isinstance(v, np.generic):
        v = v.item()
    if v is None:
        return ''
    try:
        if isinstance(v, float) and pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    return v


def _df_nativo(df: pd.DataFrame) -> pd.DataFrame:
    """Copia del DataFrame con todos sus valores en tipos nativos de Python,
    lista para mandarse a Google Sheets."""
    d = df.copy()
    for c in d.columns:
        d[c] = d[c].map(_a_valor_nativo)
    return d


def _df_a_valores_sheet(df: pd.DataFrame):
    """Convierte un DataFrame a lista de listas apta para worksheet.update()."""
    df2 = df.copy()
    for col in df2.columns:
        df2[col] = df2[col].apply(
            lambda v: '' if pd.isna(v)
            else int(v) if isinstance(v, np.integer)
            else float(v) if isinstance(v, np.floating)
            else v
        )
    return [df2.columns.tolist()] + df2.values.tolist()


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
# SECCIÓN 6: DASHBOARD (Dash) — mapa + Episodios + Alertas + IMECA Máximo
# ============================================================================

MALA_25, MALA_26     = '2025: Días con mala calidad', '2026: Días con mala calidad'
BUENA_25, BUENA_26   = '2025: Días con buena a aceptable', '2026: Días con buena a aceptable'
SINDATO_25, SINDATO_26 = '2025: Días sin dato', '2026: Días sin dato'

from numeralia.reporte.tema import (                              # noqa: E402
    CARD_STYLE,
    COLOR_BG,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_GOOD,
    COLOR_BAD,
    COLOR_GRIS,
    COLOR_GRIS_50,
    COLOR_GRIS_100,
    COLOR_GRIS_MUTE,
    COLOR_BLANCO,
    COLOR_MUTED,
    COLOR_NEGRO,
    COLOR_TEXT,
    COLOR_2025,
    COLOR_2026,
    ESCALA_ANIO_ACTUAL,
    ESCALA_ANIO_PREVIO,
    ESCALA_EPISODIOS_ANIO_ACTUAL,
    ESCALA_EPISODIOS_ANIO_PREVIO,
    PLOTLY_TEMPLATE,
    tinte,
    SEVERIDAD_TINTES as _SEVERIDAD_TINTES,
)

# Tono tenue (más claro) de cada año: sirve para las alertas en las barras
# del comparativo Alertas/Emergencias. El tono fuerte es el COLOR_202X pleno.
_COLOR_ALERTA_25 = ESCALA_ANIO_PREVIO[0]   # azul marino muy claro
_COLOR_ALERTA_26 = ESCALA_ANIO_ACTUAL[0]   # aqua muy claro


def _icono_descarga(btn_id: str):
    """Botón con ícono SVG de descarga (flecha hacia abajo con bandeja)."""
    return html.Button(
        html.Img(src='data:image/svg+xml;utf8,'
                 '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" '
                 'fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
                 '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
                 '<polyline points="7 10 12 15 17 10"/>'
                 '<line x1="12" y1="15" x2="12" y2="3"/></svg>',
                 style={'width': '18px', 'height': '18px'}),
        id=btn_id, n_clicks=0,
        style={'backgroundColor': COLOR_GRIS, 'border': 'none', 'borderRadius': '50%',
               'width': '34px', 'height': '34px', 'display': 'flex', 'alignItems': 'center',
               'justifyContent': 'center', 'cursor': 'pointer', 'padding': '0'},
    )


# ── Encabezado institucional (logos + título + introducción) ───────────────
#
# Los logos viven en MyDrive/logos. El código NO monta Drive por su cuenta,
# para no interrumpir con la ventana de permisos: si es una sesión nueva,
# corre drive.mount('/content/drive') en una celda aparte antes del pipeline.
from numeralia.reporte.pdf import DescargaPDF, registrar_descargas  # noqa: E402
from numeralia.reporte.tema import (                              # noqa: E402
    ALTO_GRAFICA_EPISODIOS,
    ALTO_LOGO,
    LOGO_SEMADET,
    LOGO_SIMAJ,
    NOMBRE_CARPETA_LOGOS,
)


def _carpetas_logos():
    """
    Lugares donde puede vivir la carpeta de logos, en orden de preferencia:
    junto al .py, en la carpeta de trabajo, y en Drive (solo si ya está
    montado — nunca se monta aquí, para no interrumpir con permisos).
    """
    candidatas = []
    try:
        candidatas.append(Path(__file__).parent / NOMBRE_CARPETA_LOGOS)
    except NameError:
        pass                                   # el código está pegado en una celda
    candidatas.append(Path.cwd() / NOMBRE_CARPETA_LOGOS)

    drive = Path('/content/drive/MyDrive')
    if drive.exists():
        candidatas.append(drive / NOMBRE_CARPETA_LOGOS)
    return candidatas


def _logo_src(nombre_archivo: str):
    """
    Devuelve el logo como data URI listo para html.Img, o None si no está.

    Se convierte a data URI (y no se pasa la ruta tal cual) para que la
    imagen viaje dentro del HTML: así aparece también al generar el PDF, sin
    depender de que el servidor de Dash la siga sirviendo.
    """
    for carpeta in _carpetas_logos():
        ruta = carpeta / nombre_archivo
        if ruta.exists():
            datos = base64.b64encode(ruta.read_bytes()).decode('ascii')
            return f'data:image/png;base64,{datos}'

    buscadas = ' | '.join(str(c) for c in _carpetas_logos())
    print(f"Nota: Logo '{nombre_archivo}' no encontrado. Se buscó en: {buscadas}")
    return None


def _fecha_encabezado() -> str:
    """
    Fecha de ayer como '20 DE AGOSTO DEL 2026'.

    El dashboard refleja datos cerrados al día anterior, así que la fecha se
    calcula sola cada vez que se levanta. Se usa _MESES_NOMBRE en vez de
    strftime('%B') porque ese depende del locale y en Colab devolvería el
    mes en inglés.
    """
    ayer = datetime.now() - timedelta(days=1)
    return f"{ayer.day} DE {_MESES_NOMBRE[ayer.month].upper()} DEL {ayer.year}"


def _encabezado_reporte():
    """
    Encabezado del reporte: logo SIMAJ a la izquierda, título centrado con la
    fecha debajo, logo SEMADET/Gobierno de Jalisco a la derecha, y al final
    la introducción.

    Los tres bloques de la fila usan flex con el mismo ancho base, así el
    título queda centrado respecto a la página aunque los logos tengan
    anchos distintos.
    """
    src_simaj = _logo_src(LOGO_SIMAJ)
    src_semadet = _logo_src(LOGO_SEMADET)

    def _celda_logo(src, alineacion, clase_imagen=None):
        contenido = html.Img(src=src, className=clase_imagen, style={
            'height': ALTO_LOGO, 'width': 'auto', 'display': 'block',
            # Sin maxWidth la imagen conserva su ancho natural y se sale de
            # la celda cuando la ventana se angosta.
            'maxWidth': '100%', 'objectFit': 'contain',
        }) if src else None
        return html.Div(contenido, style={
            'flex': '1 1 0', 'display': 'flex', 'alignItems': 'center',
            'justifyContent': alineacion, 'minWidth': '0',
        })

    return html.Div([
        # Fila de logos + título
        html.Div([
            _celda_logo(src_simaj, 'flex-start', 'logo-simaj'),
            html.Div([
                html.H1('Reporte Diario de Calidad del Aire', className='titulo-reporte', style={
                    'margin': '0', 'fontSize': '32px', 'fontWeight': '600',
                    'color': '#173d4c', 'textAlign': 'center', 'lineHeight': '1.15',
                }),
                html.Div(_fecha_encabezado(), className='fecha-reporte', style={
                    'color': COLOR_2026, 'fontSize': '20px', 'fontWeight': '600',
                    'textAlign': 'center', 'marginTop': '8px',
                }),
            ], style={'flex': '2 1 0', 'display': 'flex', 'alignItems': 'center',
                      'justifyContent': 'center', 'padding': '0 24px',
                      'flexDirection': 'column', 'minWidth': '0'}),
            _celda_logo(src_semadet, 'flex-end'),
        ], className='fila-encabezado', style={'display': 'flex', 'alignItems': 'center',
                  'gap': '24px', 'marginBottom': '22px'}),

        # Introducción
        html.P(
            'El Reporte Diario de Calidad del Aire presenta información acumulada '
            'al día señalado en el encabezado. Permite conocer cómo se ha comportado '
            'la calidad del aire.',
            style={'color': COLOR_GRIS_MUTE, 'fontSize': '17px', 'lineHeight': '1.6',
                   'textAlign': 'center', 'maxWidth': '1000px', 'margin': '0 auto'},
        ),
    ], style={'marginBottom': '32px'})


def _tendencia_buena(row) -> str:
    """Misma lógica que la columna 'Tendencia' de tu reporte en PDF: compara
    los días con buena/aceptable calidad, no los de mala calidad."""
    delta = row[BUENA_26] - row[BUENA_25]
    if delta > 0:
        return '▲ mejora'
    if delta < 0:
        return '▼ empeora'
    return '● sin cambio'


def _fig_mapa(df: pd.DataFrame):
    d = df.copy()
    d['cambio_mala'] = d[MALA_26] - d[MALA_25]
    d['abs_cambio'] = d['cambio_mala'].abs()
    d['tendencia'] = d.apply(_tendencia_buena, axis=1)

    fig = px.scatter_map(
        d, lat='Latitud', lon='Longitud',
        color='cambio_mala', size='abs_cambio',
        color_continuous_scale=[[0, COLOR_GOOD], [0.5, '#d1d5db'], [1, COLOR_BAD]],
        range_color=[-d['abs_cambio'].max(), d['abs_cambio'].max()],
        hover_name='Estación',
        custom_data=[d[BUENA_26], d['Estación']],
        # Sin 'height': el alto lo pone el contenedor desde CSS, que es lo que
        # permite achicarlo en tablet y celular sin tocar Python. La imagen
        # para el PDF se genera aparte con medidas explícitas
        # (_fig_a_base64), así que no depende de esto.
        size_max=30, zoom=10.3,
        labels={'cambio_mala': 'Cambio días mala calidad'},
    )
    # Etiquetas de nombre sobre cada burbuja + hover con días buena/aceptable.
    # mode='markers+text' agrega el texto directamente al trace sin crear
    # uno adicional, lo que mantiene un solo curveNumber en hoverData.
    fig.update_traces(
        text=d['Estación'].tolist(),
        textposition='top center',
        textfont=dict(size=12, color='#2d3436', weight='bold'),
        mode='markers+text',
        hovertemplate="<b>%{customdata[1]}</b><br>Días buena/aceptable 2026: %{customdata[0]}<extra></extra>",
    )

    # Centro explícito: el auto-fit de plotly.js para el trace 'map' (maplibre)
    # no siempre calcula el centro a partir de los datos, y sin esto el mapa
    # cae en lat=0/lon=0 (medio del océano) en vez de Jalisco.
    fig.update_layout(map_style='carto-positron', template=PLOTLY_TEMPLATE,
                       coloraxis_showscale=False,
                       map=dict(center=dict(lat=d['Latitud'].mean(), lon=d['Longitud'].mean())),
                       margin=dict(l=0, r=0, t=10, b=0))
    return fig


def _fig_a_base64(fig, ancho: int = 1000, alto: int = 520):
    """
    Renderiza una figura de Plotly a PNG desde Python (con kaleido) y la
    devuelve como data URI.

    Esto existe por el mapa: en el navegador se dibuja con WebGL y su canvas
    no se puede leer de forma confiable —el buffer se vacía tras pintar y los
    mosaicos de CARTO vienen de otro dominio, lo que lo "contamina"—, así que
    capturarlo desde JavaScript falla. Generando la imagen aquí, del lado del
    servidor, el PDF recibe una foto fija del mapa sin depender de nada del
    navegador.

    Si kaleido no está instalado devuelve None y el PDF cae al método de
    captura por JavaScript, que puede o no funcionar.
    """
    try:
        datos = fig.to_image(format='png', width=ancho, height=alto, scale=2)
        return 'data:image/png;base64,' + base64.b64encode(datos).decode('ascii')
    except Exception as e:
        print(f"Nota: No se pudo pre-generar la imagen del mapa para el PDF: {e}")
        print("  Instala kaleido si quieres el mapa en el PDF:  %pip install kaleido -q")
        return None


# ── Serie de tiempo mensual: días buena/aceptable calidad ──────────────────

_MESES_ORDEN = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
}
_MESES_NOMBRE = {v: k.capitalize() for k, v in _MESES_ORDEN.items()}


def _normalizar_mes(valor):
    """Acepta el mes como nombre en español (con/sin acentos, cualquier mayúscula)
    o como número 1-12; regresa (numero_mes, nombre_mes) o (None, valor) si no
    se reconoce."""
    s = _sin_acentos(valor).strip().lower()
    if s in _MESES_ORDEN:
        n = _MESES_ORDEN[s]
        return n, _MESES_NOMBRE[n]
    try:
        n = int(float(s))
        if 1 <= n <= 12:
            return n, _MESES_NOMBRE[n]
    except (ValueError, TypeError):
        pass
    return None, str(valor)


def _fig_serie_buena_mensual(df_resumen: pd.DataFrame):
    """
    Serie de tiempo mensual ACUMULADA (2025 azul marino vs 2026 aqua) de días
    con buena/aceptable calidad IAS. Lee columnas A-C de 'Resumen MENSUAL'
    por posición (AÑO, MES, GLOBAL BUENA O ACEPTABLE IAS).

    La línea es acumulada: cada mes muestra el total del año hasta ese mes,
    por eso nunca baja. Los meses que aún no tienen dato en Sheets se cortan
    al final, así la línea de 2026 se extiende sola conforme se capturan.

    Arriba de la gráfica va un cintillo con dos pastillas por mes (2026
    encima, 2025 debajo) con el acumulado de cada año. Las pastillas se
    dibujan como 'shapes' con trazado propio porque las anotaciones de
    Plotly no admiten esquinas redondeadas ni ancho fijo; el número va
    encima como anotación sin fondo.
    """
    cols = list(df_resumen.columns)
    fig = go.Figure()
    if len(cols) < 3:
        fig.update_layout(template=PLOTLY_TEMPLATE,
                           margin=dict(l=60, r=20, t=20, b=50))
        return fig

    col_anio, col_mes, col_buena = cols[0], cols[1], cols[2]
    base = df_resumen[[col_anio, col_mes, col_buena]].copy()
    base['_anio'] = pd.to_numeric(base[col_anio], errors='coerce')
    base[['_mes_num', '_mes_nombre']] = base[col_mes].apply(lambda v: pd.Series(_normalizar_mes(v)))
    base['_valor'] = pd.to_numeric(base[col_buena], errors='coerce')
    base = base.dropna(subset=['_mes_num'])

    anotaciones = []
    figuras = []
    ALTURA_CINTILLO = {2026: 1.22, 2025: 1.08}

    ANCHO_PASTILLA = 0.12      # en unidades de categoría (medio ancho)
    ALTO_PASTILLA = 0.05       # en fracción del alto del lienzo
    # El radio va en las mismas unidades mixtas que la pastilla, así que para
    # que la curva se vea igual en las cuatro esquinas hay que convertirlo a
    # píxeles por separado en cada eje: una unidad de categoría mide
    # ancho_del_área/12 px y una de 'paper' mide el alto de la figura (330 px).
    # Con RADIO_X = 0.10 el radio se comía el 83% del medio ancho, no quedaba
    # tramo recto en los lados y la pastilla salía abombada en vez de
    # rectangular.
    RADIO_X, RADIO_Y = 0.055, 0.016

    def _pastilla(cx, cy, color):
        """Rectángulo con esquinas redondeadas, en coordenadas mixtas:
        X en unidades del eje categórico, Y en fracción del lienzo."""
        x0, x1 = cx - ANCHO_PASTILLA, cx + ANCHO_PASTILLA
        y0, y1 = cy - ALTO_PASTILLA, cy + ALTO_PASTILLA
        return dict(
            type='path', xref='x', yref='paper', layer='above',
            path=(f'M {x0 + RADIO_X},{y0} L {x1 - RADIO_X},{y0} '
                  f'Q {x1},{y0} {x1},{y0 + RADIO_Y} '
                  f'L {x1},{y1 - RADIO_Y} Q {x1},{y1} {x1 - RADIO_X},{y1} '
                  f'L {x0 + RADIO_X},{y1} Q {x0},{y1} {x0},{y1 - RADIO_Y} '
                  f'L {x0},{y0 + RADIO_Y} Q {x0},{y0} {x0 + RADIO_X},{y0} Z'),
            fillcolor=color, line=dict(width=0),
        )

    # Hasta qué mes llega la gráfica: el último mes con dato en 2026.
    # Cuando el mes siguiente tenga registro, el rango crece automáticamente.
    # Si 2026 no tiene ningún dato aún, se muestran todos los meses.
    d_2026_check = base[(base['_anio'] == 2026) & base['_valor'].notna()]
    ultimo_mes_2026 = int(d_2026_check['_mes_num'].max()) if not d_2026_check.empty else 12

    for anio, color in [(2025, COLOR_2025), (2026, COLOR_2026)]:
        # Solo se incluyen los meses hasta el último con dato en 2026
        d = base[
            (base['_anio'] == anio) &
            base['_valor'].notna() &
            (base['_mes_num'] <= ultimo_mes_2026)
        ].sort_values('_mes_num')
        if d.empty:
            continue
        # cumsum() convierte el valor mensual en acumulado del año a la fecha.
        d = d.assign(_acumulado=d['_valor'].cumsum())
        fig.add_trace(go.Scatter(
            x=d['_mes_nombre'], y=d['_acumulado'],
            mode='lines+markers',
            name=str(anio),
            line=dict(color=color, width=4, shape='linear'),
            marker=dict(color=color, size=10, line=dict(color='#ffffff', width=1)),
            hovertemplate=f'%{{y}} días acumulados <br> hasta %{{x}} {anio}<extra></extra>',
        ))

        alto = ALTURA_CINTILLO[anio]
        for mes_num, mes, acumulado in zip(d['_mes_num'], d['_mes_nombre'], d['_acumulado']):
            # El eje X es categórico y el categoryarray de abajo fija que el
            # mes N viva en la posición N-1, que es lo que ubica la pastilla.
            figuras.append(_pastilla(int(mes_num) - 1, alto, color))
            anotaciones.append(dict(
                x=mes, xref='x',
                y=alto, yref='paper',
                text=f'<b>{int(acumulado)}</b>',
                showarrow=False, font=dict(size=13, color='#ffffff'),
                # Sin el anclaje explícito, Plotly pega la anotación al borde
                # y el número queda cortado a media pastilla.
                xanchor='center', yanchor='middle', yshift=0,
            ))

    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        # El alto lo pone el contenedor desde CSS (ver .grafica-serie-mensual
        # en assets/responsive.css). Ojo: el cintillo se posiciona en fracción
        # del lienzo ('paper'), así que su alto en píxeles sigue al del
        # contenedor — que es justo lo que queremos.
        margin=dict(l=60, r=20, t=95, b=50),
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.30, xanchor='right', x=1,
                    font=dict(size=14)),
        annotations=anotaciones,
        shapes=figuras,
        plot_bgcolor='#ffffff',
        paper_bgcolor='#ffffff',
        yaxis=dict(title=dict(text='Días acumulados', standoff=14), rangemode='tozero',
                    showgrid=True, gridcolor='#eef0f3', zeroline=False, showline=False,
                    ticks='', automargin=True, tickfont=dict(size=14)),
        xaxis=dict(title=None, showgrid=False, zeroline=False, showline=True,
                    linecolor='#d7dbe2', ticks='', automargin=True, tickfont=dict(size=14),
                    categoryorder='array',
                    # El eje se extiende solo hasta el último mes con dato en 2026
                    categoryarray=[_MESES_NOMBRE[i] for i in range(1, ultimo_mes_2026 + 1)]),
    )
    return fig


def _card_serie_mensual_2025(df_resumen: pd.DataFrame):
    hoy = datetime.now()
    corte = hoy.replace(day=1) - timedelta(days=1)
    mes_actual = _MESES_NOMBRE[corte.month]
    año_actual = corte.year
    dia_corte = corte.day
    return html.Div([
        html.Div([
            'Acumulado Mensual de Días con Buena o Aceptable Calidad del Aire ',
            html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
            '-',
            html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
        ], style={'color': '#173d4c', 'fontWeight': '700', 'fontSize': '18px', 'marginBottom': '4px'}),
        html.Div([
            f'Acumulado mensual de días en los que la calidad del aire fue buena o aceptable según '
            f'el Índice Aire y Salud (NOM-172-SEMARNAT-2023), considerando el valor más alto '
            f'registrado por el SIMAJ. Corte al {dia_corte} de {mes_actual} de {año_actual}. Consulta la información histórica en ',
            html.A('mide.jalisco.gob.mx', href='https://mide.jalisco.gob.mx', target='_blank',
                   style={'color': COLOR_2026, 'textDecoration': 'underline'}),
        ], style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        # La figura no se le pasa directo a la gráfica: vive en este Store y
        # un callback clientside la adapta al ancho de la pantalla antes de
        # dibujarla (en celular le quita el cintillo de pastillas, que a ese
        # ancho mide 5 px y queda ilegible). Así hay un solo escritor de
        # 'figure' y el refresco periódico no pisa esa adaptación.
        dcc.Store(id='figura-serie-base',
                  data=_fig_serie_buena_mensual(df_resumen).to_plotly_json()),
        # El alto vive aquí y no en la figura para que las medias queries lo
        # puedan achicar; 'responsive' hace que Plotly siga al contenedor.
        dcc.Graph(id='grafico-serie-mensual', className='grafica-serie-mensual',
                  style={'height': '330px'},
                  config={'displayModeBar': False, 'responsive': True}),
        dcc.Interval(id='refrescar-serie-mensual',
                     interval=CONFIG.refresco_mensual_seg * 1000, n_intervals=0),
    ], style={**CARD_STYLE, 'marginBottom': '20px'})


def _detalle_placeholder():
    """
    Estado vacío del panel: se centra vertical y horizontalmente en el
    espacio que queda bajo el encabezado, para que no se lea como si fuera
    otra línea más de la aclaración de arriba.
    """
    return html.Div(
        html.Div('Pasa el cursor sobre una estación del mapa '
                 'para ver su comparativo 2025 vs 2026.',
                 style={'maxWidth': '220px', 'lineHeight': '1.5'}),
        style={'color': COLOR_GRIS_MUTE, 'fontSize': '14px', 'textAlign': 'center',
               'minHeight': '180px', 'display': 'flex',
               'alignItems': 'center', 'justifyContent': 'center'},
    )


def _tabla_detalle_estacion(estacion: str, row: pd.Series):
    """Tabla real (no tooltip) con los años como columnas, para el panel lateral del mapa."""
    filas_datos = [
        ('Días con mala calidad', row[MALA_25], row[MALA_26]),
        ('Días buena / aceptable', row[BUENA_25], row[BUENA_26]),
        ('Días sin dato', row[SINDATO_25], row[SINDATO_26]),
    ]

    encabezado = html.Tr([
        html.Th('', style={'backgroundColor': COLOR_GRIS_50, 'padding': '8px 10px'}),
        html.Th('2025', style={'backgroundColor': COLOR_2025, 'color': '#fff', 'padding': '8px 10px'}),
        html.Th('2026', style={'backgroundColor': COLOR_2026, 'color': '#fff', 'padding': '8px 10px'}),
    ])
    filas = [
        html.Tr([
            html.Td(label, style={'padding': '7px 10px', 'color': COLOR_GRIS_MUTE, 'fontSize': '15px',
                                   'backgroundColor': COLOR_GRIS_50}),
            html.Td(v25, style={'padding': '7px 10px', 'textAlign': 'center', 'fontWeight': '700',
                                 'color': COLOR_GRIS_MUTE}),
            html.Td(v26, style={'padding': '7px 10px', 'textAlign': 'center', 'fontWeight': '700',
                                 'color': COLOR_GRIS_MUTE}),
        ])
        for label, v25, v26 in filas_datos
    ]

    return html.Div([
        html.Div(estacion, style={'fontWeight': '800', 'color': COLOR_GRIS_MUTE, 'fontSize': '18px',
                                   'marginBottom': '10px'}),
        html.Div(
            html.Table([html.Thead(encabezado), html.Tbody(filas)],
                       style={'width': '100%', 'borderCollapse': 'collapse'}),
            className='tabla-scroll',
        style={'borderRadius': '10px', 'overflow': 'hidden', 'border': f'1px solid {COLOR_GRIS_100}'}
        ),
        html.Div(f'Tendencia 2025 vs 2026: {_tendencia_buena(row)}', style={
            'color': COLOR_GRIS_MUTE, 'fontSize': '14px', 'marginTop': '10px'}),
    ])


# ── KPI cards ────────────────────────────────────────────────────────────

def _to_num(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


# Estilo compartido por las tres fichas de la fila superior, para que queden
# de la misma altura y con el mismo marco aunque su contenido sea distinto.
# El acento es aqua (el color de 2026) porque estas fichas reportan solo el
# año en curso; el azul marino se reserva para donde sí se compara con 2025.
_KPI_CONTENEDOR = {
    'backgroundColor': '#ffffff', 'border': f'1px solid {COLOR_GRIS_100}',
    'borderRadius': '12px', 'padding': '0', 'flex': '1', 'minWidth': '260px',
    'borderTop': f'4px solid {COLOR_2026}', 'display': 'flex', 'flexDirection': 'column',
    'overflow': 'hidden',
    # Sombra en dos capas: una difusa y amplia que despega la tarjeta del
    # fondo, y otra corta y apretada que le da el filo.
    'boxShadow': '0 1px 2px rgba(70,80,85,0.06), 0 6px 16px rgba(70,80,85,0.08)',
}

_KPI_TITULO = {
    'color': COLOR_2026, 'fontSize': '14px', 'fontWeight': '800',
    'textTransform': 'uppercase', 'letterSpacing': '0.06em',
    'padding': '14px 20px 12px',
}

# Zona de datos (columnas) y pie de total, con su propio respiro.
_KPI_CUERPO = {'flex': '1', 'padding': '0 20px 14px'}

# Pie con un tinte aqua muy diluido, para que la franja pertenezca a la misma
# familia de color que el acento superior en vez de ser un gris neutro.
_KPI_PIE = {
    'backgroundColor': '#f2fbf9', 'borderTop': '1px solid #dcf1ec',
    'padding': '12px 20px',
}


def _kpi_dato(etiqueta: str, valor, color_punto: str = None):
    """
    Un dato suelto de ficha KPI: cifra grande arriba, etiqueta abajo, con un
    punto del color de severidad. Se usa dentro de las columnas de la ficha,
    centrado, para que dos datos lado a lado se lean parejos.
    """
    encabezado = []
    if color_punto:
        encabezado.append(html.Span(style={
            'display': 'inline-block', 'width': '9px', 'height': '9px',
            'borderRadius': '50%', 'backgroundColor': color_punto,
            'marginRight': '7px', 'flexShrink': '0',
        }))
    encabezado.append(html.Span(etiqueta, style={
        'color': COLOR_GRIS_MUTE, 'fontSize': '14px', 'fontWeight': '600',
        'lineHeight': '1.3',
    }))

    return html.Div([
        html.Div(str(valor), style={
            'color': COLOR_2026, 'fontWeight': '800', 'fontSize': '34px',
            'lineHeight': '1', 'marginBottom': '7px',
        }),
        html.Div(encabezado, style={
            'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center',
        }),
    ], style={'textAlign': 'center'})


def _kpi_total(etiqueta: str, valor):
    """
    Pie de la ficha con el total, sobre la franja con tinte aqua. La cifra
    va en gris oscuro: como el fondo ya es aqua diluido, ponerla también en
    aqua la haría desaparecer, y siendo el número más importante de la ficha
    necesita el mayor contraste.
    """
    return html.Div([
        html.Span(etiqueta, style={
            'color': '#173d4c', 'fontSize': '15px', 'fontWeight': '700',
            'textTransform': 'uppercase', 'letterSpacing': '0.04em',
        }),
        html.Span(str(valor), style={
            'color': '#173d4c', 'fontWeight': '800', 'fontSize': '32px', 'lineHeight': '1',
        }),
    ], style={**_KPI_PIE, 'display': 'flex', 'justifyContent': 'space-between',
              'alignItems': 'center', 'gap': '12px'})


def _kpi_activaciones_simaj(df_episodios: pd.DataFrame, col_2026: str):
    """
    Ficha 'Activaciones por SIMAJ': solo datos 2026. Precontingencias a la
    izquierda, contingencias por fase a la derecha, y el total abajo.

    Las fases se leen de la tabla de Episodios, así que si en el futuro las
    Fases II o III dejan de estar en cero, aparecen solas sin tocar el código.
    """
    col_label = df_episodios.columns[0]

    def _valor(prefijo_busqueda: str):
        m = df_episodios[df_episodios[col_label].astype(str).str.strip() == prefijo_busqueda]
        if m.empty:
            return 0
        return int(_to_num(m.iloc[0][col_2026]) or 0)

    precont = _valor('Precontingencias atmosféricas:')
    fases = [
        ('Fase I',   _valor('Contingencias atmosféricas Fase I:'),   _SEVERIDAD_TINTES[2]),
        ('Fase II',  _valor('Contingencias atmosféricas Fase II:'),  _SEVERIDAD_TINTES[3]),
        ('Fase III', _valor('Contingencias atmosféricas Fase III:'), _SEVERIDAD_TINTES[4]),
    ]

    total_fila = df_episodios[
        df_episodios[col_label].astype(str).str.strip().str.lower() == 'episodios totales']
    total = int(_to_num(total_fila.iloc[0][col_2026]) or 0) if not total_fila.empty else 0

    # Fase I siempre; II y III se suman solas en cuanto registren su primer
    # evento. Si hay más de una, se acomodan lado a lado.
    fases_visibles = [f for i, f in enumerate(fases) if i == 0 or f[1] > 0]
    col_contingencias = html.Div(
        [_kpi_dato(nombre, valor, color) for nombre, valor, color in fases_visibles],
        style={'display': 'flex', 'gap': '14px', 'justifyContent': 'center'},
    )

    return html.Div([
        html.Div('Episodios Activados', style=_KPI_TITULO),
        html.Div(html.Div([
            html.Div(_kpi_dato('Precontingencias', precont, _SEVERIDAD_TINTES[1]),
                     style={'flex': '1', 'minWidth': '0'}),
            # Línea vertical que separa precontingencias de contingencias.
            html.Div(style={'width': '1px', 'backgroundColor': COLOR_GRIS_100,
                            'alignSelf': 'stretch'}),
            html.Div([
                col_contingencias,
                html.Div('Contingencias', style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '13px', 'fontWeight': '600',
                    'textAlign': 'center', 'marginTop': '6px',
                }),
            ], style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '14px', 'alignItems': 'center',
                  'height': '100%'}), style=_KPI_CUERPO),
        _kpi_total('Total de episodios Activados', total),
    ], style=_KPI_CONTENEDOR)


def _kpi_alertas_emergencias(df_alertas: pd.DataFrame, col_2026: str):
    """
    Ficha de eventos extraordinarios: solo datos 2026, con la misma
    estructura visual que Activaciones por SIMAJ.
    """
    col_label = df_alertas.columns[0]

    def _valor(prefijo: str):
        m = df_alertas[df_alertas[col_label].astype(str).str.strip().str.lower().str.startswith(prefijo)]
        if m.empty:
            return 0
        return int(_to_num(m.iloc[0][col_2026]) or 0)

    alertas = _valor('alerta')
    emergencias = _valor('emergencia')
    total = _valor('total')

    return html.Div([
        html.Div('Eventos activados', style=_KPI_TITULO),
        html.Div(html.Div([
            html.Div(_kpi_dato('Alertas', alertas, '#FCB308'),
                     style={'flex': '1', 'minWidth': '0'}),
            html.Div(style={'width': '1px', 'backgroundColor': COLOR_GRIS_100,
                            'alignSelf': 'stretch'}),
            html.Div(_kpi_dato('Emergencias', emergencias, '#FC3508'),
                     style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '14px', 'alignItems': 'center',
                  'height': '100%'}), style=_KPI_CUERPO),
        _kpi_total('Total de Eventos Activados', total),
    ], style=_KPI_CONTENEDOR)


# ── Tabla de Episodios (con jerarquía de severidad) ─────────────────────────

_EPISODIOS_ENCABEZADOS = {
    'Precontingencias atmosféricas:':          1,
    'Contingencias atmosféricas Fase I:':      2,
    'Contingencias atmosféricas Fase II:':     3,
    'Contingencias atmosféricas Fase III:':    4,
}


def _tabla_episodios(df: pd.DataFrame):
    """
    Tabla comparativa de episodios con acordeón:
    - Los encabezados de grupo (Precontingencias, Fase I…) son siempre visibles.
    - Las sub-filas (declaradas por Ozono/PM10/PM2.5) empiezan ocultas y se
      despliegan al hacer clic en el encabezado de su grupo.
    - Los grupos que no tienen sub-filas en los datos (Fase II, III) se
      muestran como filas normales sin flecha ni toggle.
    El gráfico de barras queda a la derecha con altura fija ALTO_GRAFICA_EPISODIOS.
    """
    col_label, col_2025, col_2026 = df.columns[0], df.columns[1], df.columns[2]

    # ── Primera pasada: agrupar filas por severidad ───────────────────────────
    grupos = []          # [{'sev': int, 'row': Series, 'subs': [Series, …]}, …]
    fila_totales = None
    grupo_actual = None

    for _, row in df.iterrows():
        etiqueta = str(row[col_label]).strip()
        es_total = etiqueta.lower().startswith('episodios totales')
        sev = _EPISODIOS_ENCABEZADOS.get(etiqueta, 0)

        if es_total:
            fila_totales = row
        elif sev:
            grupo_actual = {'sev': sev, 'row': row, 'subs': []}
            grupos.append(grupo_actual)
        elif grupo_actual is not None:
            grupo_actual['subs'].append(row)

    # ── Helpers de estilo ─────────────────────────────────────────────────────
    def _num(base): return {**base, 'padding': '8px 14px', 'textAlign': 'center'}
    def _lbl(base, indent=False): return {
        **base, 'padding': '8px 14px', 'textAlign': 'left',
        'paddingLeft': '34px' if indent else '14px',
        'fontSize': '15px' if indent else '14px',
        'fontWeight': base.get('fontWeight', '400') if indent else base.get('fontWeight', '700'),
    }

    # ── Segunda pasada: construir tbodies ─────────────────────────────────────
    tbodies = []
    for g in grupos:
        sev = g['sev']
        row = g['row']
        etiqueta = str(row[col_label]).strip()
        texto_claro = sev >= 2
        base = {
            'backgroundColor': _SEVERIDAD_TINTES[sev],
            'color': '#ffffff' if texto_claro else '#173d4c',
            'fontWeight': '700',
        }
        tiene_subs = bool(g['subs'])

        # Celda de etiqueta con flecha opcional
        contenido_lbl = ([
            html.Span('▶', id=f'arrow-episodios-{sev}',
                      style={'marginRight': '8px', 'fontSize': '10px',
                             'display': 'inline-block'}),
        ] if tiene_subs else []) + [etiqueta]

        celda_lbl = html.Td(
            contenido_lbl,
            style={**_lbl(base), 'cursor': 'pointer' if tiene_subs else 'default'},
        )

        # Fila encabezado: clickeable solo si tiene sub-filas
        kwargs_hdr = dict(id=f'toggle-episodios-{sev}', n_clicks=0) if tiene_subs else {}
        header_tr = html.Tr(
            [celda_lbl,
             html.Td(row[col_2025], style=_num(base)),
             html.Td(row[col_2026], style=_num(base))],
            **kwargs_hdr,
        )
        tbodies.append(html.Tbody([header_tr]))

        # Sub-filas en un tbody aparte, inicialmente oculto
        if tiene_subs:
            sub_base = {'backgroundColor': '#ffffff', 'color': COLOR_GRIS_MUTE}
            sub_trs = [
                html.Tr([
                    html.Td(str(sr[col_label]).strip(), style=_lbl(sub_base, indent=True)),
                    html.Td(sr[col_2025], style=_num(sub_base)),
                    html.Td(sr[col_2026], style=_num(sub_base)),
                ])
                for sr in g['subs']
            ]
            tbodies.append(html.Tbody(sub_trs,
                                      id=f'sub-episodios-{sev}',
                                      style={'display': 'none'}))

    # Fila de totales: mismo fondo aqua diluido y color de letra que los KPI.
    if fila_totales is not None:
        base_tot = {**_KPI_PIE, 'color': '#173d4c'}
        tbodies.append(html.Tbody([html.Tr([
            html.Td(str(fila_totales[col_label]).strip(), style=_lbl(base_tot)),
            html.Td(fila_totales[col_2025], style={**_num(base_tot), 'fontWeight': '800'}),
            html.Td(fila_totales[col_2026], style={**_num(base_tot), 'fontWeight': '800'}),
        ])]))

    encabezado = html.Thead(html.Tr([
        html.Th('Episodios activados', style={'backgroundColor': '#e8edef', 'color': '#173d4c',
                                               'padding': '10px 14px', 'textAlign': 'left'}),
        html.Th('2025', style={'backgroundColor': COLOR_2025, 'color': '#fff', 'padding': '10px 14px'}),
        html.Th('2026', style={'backgroundColor': COLOR_2026, 'color': '#fff', 'padding': '10px 14px'}),
    ]))

    return html.Div(
        html.Table([encabezado] + tbodies,
                   style={'width': '100%', 'borderCollapse': 'collapse'}),
        className='tabla-scroll',
        style={'borderRadius': '10px', 'overflow': 'hidden', 'border': f'1px solid {COLOR_GRIS_100}'}
    )


# ── Barras apiladas de episodios por contaminante ──────────────────────────
#
# Los tres contaminantes se distinguen por TONO dentro del color de su año:
# el más claro abajo, el más oscuro arriba. La escala la calcula
# numeralia.reporte.tema, que topa el tono oscuro para que la etiqueta de
# cada segmento siga leyéndose; como los tonos difieren en luminancia, la
# gráfica se sigue entendiendo impresa en blanco y negro.
#
# Orden de apilado, de abajo hacia arriba.
_ORDEN_CONTAMINANTES = ('Ozono', 'PM10', 'PM2.5')


def _episodios_por_contaminante(df: pd.DataFrame, anio_col: str, severidad: int):
    """
    Devuelve [(contaminante, valor), ...] de las subcategorías que cuelgan del
    grupo de severidad indicado (1 = precontingencias, 2 = Fase I, …).

    Se recorre la tabla de arriba a abajo llevando cuenta del grupo activo,
    en vez de buscar los nombres exactos de las subfilas, porque en la hoja
    esas filas vienen indentadas con espacios y su texto cambia entre grupos.
    """
    col_label = df.columns[0]
    grupo_actual = 0
    datos = []
    for _, row in df.iterrows():
        etiqueta = str(row[col_label]).strip()
        sev = _EPISODIOS_ENCABEZADOS.get(etiqueta, 0)
        if sev:
            grupo_actual = sev
            continue
        if etiqueta.lower().startswith('episodios totales') or grupo_actual != severidad:
            continue

        norm = _sin_acentos(etiqueta).lower()
        if 'ozono' in norm:
            contaminante = 'Ozono'
        elif 'pm10' in norm:
            contaminante = 'PM10'
        elif 'pm2.5' in norm or 'pm25' in norm:
            contaminante = 'PM2.5'
        else:
            continue

        datos.append((contaminante, int(_to_num(row[anio_col]) or 0)))
    return datos


def _datos_grafica_episodios(df: pd.DataFrame, col_2025: str, col_2026: str,
                              severidad: int, titulo: str) -> dict:
    """
    Empaqueta lo que la gráfica de ECharts necesita para un grupo de
    severidad. Se devuelve como diccionario plano (serializable a JSON) para
    mandarlo al navegador en un dcc.Store; el dibujo lo arma el callback
    clientside, que es donde vive ECharts.
    """
    datos_25 = dict(_episodios_por_contaminante(df, col_2025, severidad))
    datos_26 = dict(_episodios_por_contaminante(df, col_2026, severidad))
    contaminantes = list(_ORDEN_CONTAMINANTES)

    _escala_25 = list(reversed(ESCALA_EPISODIOS_ANIO_PREVIO))
    _escala_26 = list(ESCALA_EPISODIOS_ANIO_ACTUAL)
    # El Ozono usa el mismo tono claro que las alertas de ese año.
    _escala_25[0] = _COLOR_ALERTA_25
    _escala_26[0] = _COLOR_ALERTA_26

    return {
        'titulo': titulo,
        # Los títulos van en el negro de texto del reporte, no en el color de
        # severidad: esa lectura ya la da la tabla comparativa de al lado.
        'color_titulo': COLOR_TEXT,
        'anios': ['2025', '2026'],
        # Colores de cada año, en el mismo orden que 'anios'. Las barras y los
        # totales se pintan con estos; la severidad se queda en el título.
        'colores_anio': [COLOR_2025, COLOR_2026],
        # Un tono por contaminante, dentro del color de cada año. El índice
        # de la serie elige el tono; el del año elige la escala.
        # El apilado va de suave (Ozono, índice 0) a fuerte (PM2.5, índice 2):
        #   - 2025: la escala original va de oscuro a claro, así que se invierte.
        #   - 2026: la escala original ya va de claro a oscuro, se usa tal cual.
        # Ozono = tono claro de alertas; PM10/PM2.5 = degradado del año.
        'escalas_anio': [_escala_25, _escala_26],
        # Color del texto de cada segmento, por año y por contaminante.
        #   Ozono: color gris como en las gráficas de Alertas.
        #   PM10/PM2.5: blanco sobre fondos medios/oscuros.
        'colores_texto_anio': [
            [
                {'nombre': COLOR_GRIS_MUTE, 'valor': COLOR_GRIS_MUTE},  # Ozono – tono claro
                {'nombre': COLOR_BLANCO, 'valor': COLOR_BLANCO},   # PM10  – tono medio
                {'nombre': COLOR_BLANCO, 'valor': COLOR_BLANCO},   # PM2.5 – tono oscuro
            ],
            [
                {'nombre': COLOR_2026, 'valor': COLOR_2026},        # Ozono 2026 – tono claro
                {'nombre': COLOR_BLANCO, 'valor': COLOR_BLANCO},   # PM10  – tono medio
                {'nombre': COLOR_BLANCO, 'valor': COLOR_BLANCO},   # PM2.5 – tono oscuro
            ],
        ],
        'series': [
            {'nombre': c,
             'datos': [datos_25.get(c, 0), datos_26.get(c, 0)]}
            for c in contaminantes
        ],
        'totales': [sum(datos_25.values()), sum(datos_26.values())],
    }


# ── Tabla y gráficas de Alertas y Emergencias ───────────────────────────────

def _tabla_alertas(df: pd.DataFrame):
    col_label, col_2025, col_2026 = df.columns[0], df.columns[1], df.columns[2]

    filas = []
    for _, row in df.iterrows():
        etiqueta = str(row[col_label]).strip()
        es_total = etiqueta.lower().startswith('total')
        es_emergencia = etiqueta.lower().startswith('emergencia')

        if es_total:
            # Mismo fondo aqua diluido y color de letra que los KPI.
            estilo = {**_KPI_PIE, 'color': '#173d4c'}
        elif es_emergencia:
            estilo = {'backgroundColor': '#FC3508', 'color': '#ffffff'}
        else:
            estilo = {'backgroundColor': '#FCB308', 'color': '#173d4c'}

        filas.append(html.Tr([
            html.Td(etiqueta.rstrip(':'), style={**estilo, 'padding': '10px 14px', 'textAlign': 'left',
                                                  'fontWeight': '700'}),
            html.Td(row[col_2025], style={**estilo, 'padding': '10px 14px', 'textAlign': 'center',
                                           'fontWeight': '800'}),
            html.Td(row[col_2026], style={**estilo, 'padding': '10px 14px', 'textAlign': 'center',
                                           'fontWeight': '800'}),
        ]))

    encabezado = html.Tr([
        html.Th('Categoría', style={'backgroundColor': '#e8edef', 'color': '#173d4c',
                                     'padding': '10px 14px', 'textAlign': 'left'}),
        html.Th('2025', style={'backgroundColor': COLOR_2025, 'color': '#fff', 'padding': '10px 14px'}),
        html.Th('2026', style={'backgroundColor': COLOR_2026, 'color': '#fff', 'padding': '10px 14px'}),
    ])

    return html.Div(
        html.Table([html.Thead(encabezado), html.Tbody(filas)],
                    style={'width': '100%', 'borderCollapse': 'collapse'}),
        className='tabla-scroll',
        style={'borderRadius': '10px', 'overflow': 'hidden', 'border': f'1px solid {COLOR_GRIS_100}'}
    )


def _tabla_parametros():
    """Tabla de parámetros medidos por el SIMAJ."""
    parametros = [
        (html.Span(['O', html.Sub('3')], style={'fontWeight': '700'}), 'Ozono'),
        (html.Span(['N', 'O', html.Sub('2')], style={'fontWeight': '700'}), 'Óxidos de nitrógeno'),
        (html.Span(['S', 'O', html.Sub('2')], style={'fontWeight': '700'}), 'Bióxido de Azufre'),
        (html.Span(['C', 'O'], style={'fontWeight': '700'}), 'Monóxido de carbono'),
        (html.Span(['P', 'M', html.Sub('10')], style={'fontWeight': '700'}), 'Partículas menores a 10 micrómetros'),
        (html.Span(['P', 'M', html.Sub('2.5')], style={'fontWeight': '700'}), 'Partículas menores a 2.5 micrómetros'),
    ]
    filas = [
        html.Tr([
            html.Td(formula, style={
                'padding': '8px 12px', 'textAlign': 'center',
                'borderBottom': f'1px solid {COLOR_GRIS_100}',
                'color': COLOR_GRIS_MUTE, 'fontSize': '13px',
            }),
            html.Td(desc, style={
                'padding': '8px 12px', 'textAlign': 'left',
                'borderBottom': f'1px solid {COLOR_GRIS_100}',
                'color': COLOR_GRIS_MUTE, 'fontSize': '13px',
            }),
        ])
        for formula, desc in parametros
    ]
    encabezado = html.Thead(html.Tr([
        html.Th('Parámetros', colSpan=2, style={
            'backgroundColor': '#e8edef', 'color': '#173d4c',
            'padding': '8px 12px', 'textAlign': 'center',
            'fontWeight': '700', 'fontSize': '13px',
        }),
    ]))
    return html.Div(
        html.Table([encabezado, html.Tbody(filas)],
                   style={'width': '100%', 'borderCollapse': 'collapse'}),
        style={
            'borderRadius': '10px', 'overflow': 'hidden',
            'border': f'1px solid {COLOR_GRIS_100}',
            'maxWidth': '500px', 'margin': '0 auto',
        }
    )


def _datos_barras_alertas(df_alertas: pd.DataFrame) -> dict:
    """
    Extrae alertas y emergencias por año del DataFrame comparativo para
    pasarlos como JSON al clientside_callback de ECharts.
    """
    col_label, col_2025, col_2026 = df_alertas.columns[0], df_alertas.columns[1], df_alertas.columns[2]

    def _val(prefix, col):
        m = df_alertas[df_alertas[col_label].str.strip().str.lower().str.startswith(prefix.lower())]
        return int(_to_num(m.iloc[0][col]) or 0) if not m.empty else 0

    return {
        'alertas_25':     _val('alerta', col_2025),
        'emergencias_25': _val('emergencia', col_2025),
        'alertas_26':     _val('alerta', col_2026),
        'emergencias_26': _val('emergencia', col_2026),
        # Colores de relleno
        'color_a25': _COLOR_ALERTA_25,
        'color_e25': COLOR_2025,
        'color_a26': _COLOR_ALERTA_26,
        'color_e26': COLOR_2026,
        # Alertas (fondo tenue): texto gris oscuro para legibilidad
        # Emergencias (fondo pleno): texto blanco
        'texto_a25': COLOR_GRIS_MUTE,
        'texto_e25': COLOR_BLANCO,
        'texto_a26': COLOR_GRIS_MUTE,
        'texto_e26': COLOR_BLANCO,
    }


# ── Tarjeta de IMECA Máximo ──────────────────────────────────────────────

def _clasificar_imeca(valor) -> str:
    v = _to_num(valor)
    if v is None:
        return "Sin dato"
    if v <= 50:
        return "Buena"
    if v <= 100:
        return "Aceptable"
    if v <= 150:
        return "Mala"
    if v <= 200:
        return "Muy mala"
    return "Extremadamente mala"


_MES_ABREV = {
    1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic',
}


def _fecha_mes_abreviado(valor) -> str:
    """
    Convierte '01/02/2026' en '01/Feb/2026'.

    Se usa un diccionario propio en vez de strftime('%b') porque ese depende
    del locale: en Colab saldría en inglés. Si el texto no tiene el formato
    esperado se devuelve tal cual, para no romper la tarjeta.
    """
    texto = str(valor).strip()
    partes = texto.split('/')
    if len(partes) != 3:
        return texto
    dia, mes, anio = partes
    try:
        return f"{dia}/{_MES_ABREV[int(mes)]}/{anio}"
    except (ValueError, KeyError):
        return texto


def _formatear_hora(hora) -> str:
    """Deja la hora en formato H:MM a.m./p.m., sin segundos."""
    s = str(hora).strip().replace('.', '').lower()
    s = s.replace('p.m', ' PM').replace('a.m', ' AM')
    s = s.replace('pm', ' PM').replace('am', ' AM')
    for fmt in ('%I:%M:%S %p', '%I:%M %p', '%H:%M:%S', '%H:%M'):
        try:
            dt = datetime.strptime(s, fmt)
            h12 = dt.hour % 12 or 12
            ampm = 'a.m.' if dt.hour < 12 else 'p.m.'
            return f"{h12}:{dt.minute:02d} {ampm}"
        except ValueError:
            pass
    return str(hora)


def _card_imeca(df_imeca: pd.DataFrame):
    d = df_imeca.set_index(df_imeca.columns[0])

    def _get(anio, campo):
        return d.loc[campo, anio] if campo in d.index and anio in d.columns else '—'

    def _bloque_anio(anio, color):
        valor = _get(anio, 'IMECA Máximo del año')
        return html.Div([
            html.Div(anio, style={'color': color, 'fontWeight': '800', 'fontSize': '15px',
                                   'letterSpacing': '0.04em', 'textTransform': 'uppercase',
                                   'marginBottom': '4px'}),
            # Fila interna: número+badge a la izquierda, metadata a la derecha
            html.Div([
                # Columna izquierda: número grande + badge
                html.Div([
                    html.Div(str(valor), style={'color': COLOR_GRIS_MUTE, 'fontSize': '42px',
                                                'fontWeight': '800', 'lineHeight': '1'}),
                    html.Div(_clasificar_imeca(valor), style={
                        'display': 'inline-block', 'backgroundColor': color, 'color': '#ffffff',
                        'borderRadius': '999px', 'padding': '2px 12px',
                        'fontSize': '13px', 'fontWeight': '700', 'marginTop': '6px',
                    }),
                ], style={'display': 'flex', 'flexDirection': 'column',
                          'alignItems': 'flex-start', 'marginRight': '20px',
                          'flexShrink': '0'}),
                # Columna derecha: metadata
                html.Div([
                    html.Div([html.Span('Contaminante  ', style={'color': COLOR_GRIS_MUTE}),
                              html.B(_get(anio, 'Contaminante'), style={'color': '#173d4c'})]),
                    html.Div([html.Span('Estación  ', style={'color': COLOR_GRIS_MUTE}),
                              html.B(_get(anio, 'Estación'), style={'color': '#173d4c'})]),
                    html.Div([html.Span('Fecha  ', style={'color': COLOR_GRIS_MUTE}),
                              html.B(_fecha_mes_abreviado(_get(anio, 'Fecha')),
                                     style={'color': '#173d4c'})]),
                    html.Div([html.Span('Hora  ', style={'color': COLOR_GRIS_MUTE}),
                              html.B(_formatear_hora(_get(anio, 'Hora')), style={'color': '#173d4c'})]),
                ], style={'fontSize': '14px', 'display': 'grid', 'gap': '4px',
                          'alignContent': 'center'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'alignItems': 'center'}),
        ], className='bloque-imeca-anio', style={'flex': '1', 'padding': '14px 22px',
                  'borderLeft': f'4px solid {color}', '--color-acento': color})

    return html.Div([
        html.Div('IMECA Máximo Registrado', style={'color': '#173d4c', 'fontWeight': '700',
                                                     'fontSize': '17px', 'marginBottom': '4px'}),
        html.Div('Valor más alto del índice en el año, por contaminante y estación.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '14px', 'marginBottom': '12px'}),
        # 'fila-imeca': en celular se apila en columna (ver
        # assets/responsive_movil.css) y, como 2025 va primero en el DOM, se
        # invierte con 'column-reverse' para que 2026 —el año en curso—
        # quede arriba.
        html.Div([_bloque_anio('2025', COLOR_2025), _bloque_anio('2026', COLOR_2026)],
                  className='fila-imeca',
                  style={'display': 'flex', 'border': f'1px solid {COLOR_GRIS_100}',
                         'borderRadius': '12px', 'overflow': 'hidden'}),
    ])


# ── Ficha de Eventos Activos 2026 ───────────────────────────────────────────

def _sin_acentos(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn')


def _buscar_columna(columnas, *fragmentos):
    """Busca la primera columna cuyo nombre (sin acentos, en minúsculas) contenga
    alguno de los fragmentos dados. Devuelve None si no encuentra ninguna."""
    for c in columnas:
        norm = _sin_acentos(c).lower()
        if any(frag in norm for frag in fragmentos):
            return c
    return None


def _eventos_activos_2026(df_alertas_2026: pd.DataFrame):
    """
    Un evento se considera ACTIVO si las columnas A (No) a H (Inicio) tienen
    dato (la fila es real, no un renglón vacío de la plantilla) y la columna
    'Fecha termino' está vacía. En cuanto 'Fecha termino' tenga dato, el
    evento desaparece de la ficha. Devuelve lista de dicts con tipo='alerta'.
    """
    cols = list(df_alertas_2026.columns)
    if len(cols) < 8:
        return []

    cols_a_h = cols[0:8]         # A (No) ... H (Inicio)
    col_inicio = cols[7]         # H
    col_termino = _buscar_columna(cols, 'termino', 'fin')
    if col_termino is None:
        return []

    col_municipio = _buscar_columna(cols, 'municipio')
    col_incidente = _buscar_columna(cols, 'incidente')
    col_fase = _buscar_columna(cols, 'fase decretada', 'fase')

    activos = []
    for _, row in df_alertas_2026.iterrows():
        fila_llena = all(str(row[c]).strip() != '' for c in cols_a_h)
        termino_vacio = str(row[col_termino]).strip() == ''
        if fila_llena and termino_vacio:
            fase = str(row[col_fase]).strip() if col_fase else ''
            activos.append({
                'tipo': 'alerta',
                'fase': fase,
                'inicio': str(row[col_inicio]).strip(),
                'municipio': str(row[col_municipio]).strip() if col_municipio else '',
                'incidente': str(row[col_incidente]).strip() if col_incidente else '',
            })
    return activos


# Mapa de nombre de evento (hoja episodios 2026) a nivel de severidad
_EVENTO_SEVERIDAD = {
    'PreContingencia Atmosférica':        1,
    'Contingencia Atmosférica Fase I':    2,
    'Contingencia Atmosférica Fase II':   3,
    'Contingencia Atmosférica Fase III':  4,
}


def _episodios_activos_raw(df_episodios_2026: pd.DataFrame):
    """
    Un episodio en 'Nuevo episodios 2026' se considera ACTIVO si:
      - La primera columna (No) tiene dato (fila real, no plantilla vacía).
      - La columna 'Estado' existe y contiene 'activo' (sin importar mayúsculas),
        O bien no hay columna Estado pero la columna 'Fin' está vacía.
    
    Se limita la búsqueda de 'Fin' a columnas hasta 'Estado' para evitar
    coincidencias con otros nombres que contengan 'fin' (ej. 'Definición').
    Devuelve lista de dicts con tipo='episodio' y severidad.
    """
    cols = list(df_episodios_2026.columns)
    if not cols:
        return []

    col_no = cols[0]
    col_evento = _buscar_columna(cols, 'evento')
    col_municipio = _buscar_columna(cols, 'municipio')
    col_contaminante = _buscar_columna(cols, 'contaminante')
    col_estacion = _buscar_columna(cols, 'estacion', 'estación')
    col_estado = _buscar_columna(cols, 'estado')

    # Limitar búsqueda de 'Fin' al rango hasta Estado (como la bitácora)
    if col_estado:
        idx_estado = cols.index(col_estado)
        cols_hasta_estado = cols[0:idx_estado + 1]
    else:
        cols_hasta_estado = cols
    col_fin = _buscar_columna(cols_hasta_estado, 'fin')

    # Sin ninguna señal de terminación no podemos determinar si está activo
    if col_fin is None and col_estado is None:
        return []

    activos = []
    for _, row in df_episodios_2026.iterrows():
        # Fila vacía de plantilla: la columna No está vacía
        if str(row[col_no]).strip() == '':
            continue

        # Criterio de actividad:
        # 1) Si hay columna Estado → 'activo' en su valor
        # 2) Si no, caer en Fin vacío
        if col_estado:
            val_estado = _sin_acentos(str(row[col_estado])).strip().lower()
            es_activo = 'activo' in val_estado
        else:
            es_activo = str(row[col_fin]).strip() == ''

        if es_activo:
            evento_texto = str(row[col_evento]).strip() if col_evento else ''
            severidad = _EVENTO_SEVERIDAD.get(evento_texto, 0)
            activos.append({
                'tipo': 'episodio',
                'evento': evento_texto,
                'severidad': severidad,
                'municipio': str(row[col_municipio]).strip() if col_municipio else '',
                'contaminante': str(row[col_contaminante]).strip() if col_contaminante else '',
                'estacion': str(row[col_estacion]).strip() if col_estacion else '',
            })
    return activos


def _card_eventos_activos(eventos_alertas, eventos_episodios=None):
    """
    Ficha de episodios/alertas activos, como tercera tarjeta KPI.
    - eventos_alertas: lista de dicts de _eventos_activos_2026() (hoja alertas).
    - eventos_episodios: lista de dicts de _episodios_activos_raw() (hoja episodios).
    Ambas listas se muestran juntas. Las alertas usan color amarillo/rojo según
    la Fase Decretada; los episodios usan SEVERIDAD_TINTES según su nivel.
    """
    todos = list(eventos_alertas or []) + list(eventos_episodios or [])

    if not todos:
        cuerpo = html.Div(
            'Sin episodios activos por el momento.',
            style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'textAlign': 'center',
                   'padding': '18px 0'},
        )
    else:
        fichas = []
        for i, ev in enumerate(todos):
            es_ultimo = i == len(todos) - 1
            tipo = ev.get('tipo', 'alerta')

            if tipo == 'alerta':
                fase = ev.get('fase', '').lower()
                color_badge = '#FC3508' if 'emergencia' in fase else '#FCB308'
                texto_badge = ev.get('fase') or 'Alerta'
                texto_claro_badge = 'emergencia' in fase
                descripcion = ev.get('incidente', '')
                detalle = f"en el municipio de {ev['municipio']}" if ev.get('municipio') else ''
                subtexto = None
            else:
                sev = ev.get('severidad', 0)
                color_badge = _SEVERIDAD_TINTES.get(sev, '#FCB308')
                texto_badge = ev.get('evento') or 'Episodio activo'
                texto_claro_badge = sev >= 2
                descripcion = None
                detalle = f"en el municipio de {ev['municipio']}" if ev.get('municipio') else ''
                contaminante = ev.get('contaminante', '') or None
                estacion = ev.get('estacion', '') or None

            fichas.append(html.Div([
                html.Div(texto_badge, style={
                    'backgroundColor': color_badge,
                    'color': '#ffffff' if texto_claro_badge else COLOR_GRIS_MUTE,
                    'display': 'inline-block',
                    'padding': '4px 12px', 'borderRadius': '6px', 'fontWeight': '700',
                    'fontSize': '13px', 'marginBottom': '6px',
                }),
                html.Div(descripcion, style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'fontWeight': '600',
                }) if tipo == 'alerta' and descripcion else None,
                html.Div(detalle, style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '14px',
                }) if detalle else None,
                html.Div(f'Estación: {estacion}', style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '14px',
                }) if tipo == 'episodio' and estacion else None,
                html.Div(f'Contaminante: {contaminante}', style={
                    'color': COLOR_GRIS_MUTE, 'fontSize': '14px',
                }) if tipo == 'episodio' and contaminante else None,
            ], style={
                'marginBottom': '0' if es_ultimo else '10px',
                'paddingBottom': '0' if es_ultimo else '10px',
                'textAlign': 'center',
                'borderBottom': 'none' if es_ultimo else f'1px solid {COLOR_GRIS_100}',
            }))
        cuerpo = html.Div(fichas)

    return html.Div([
        html.Div('Episodios o Eventos Activos + Contingencias y Precontingencias', style=_KPI_TITULO),
        html.Div(cuerpo, style={**_KPI_CUERPO, 'display': 'flex',
                                 'flexDirection': 'column', 'justifyContent': 'center'}),
    ], style=_KPI_CONTENEDOR)


# ── Bitácoras completas (tablas paginadas) ──────────────────────────────────

def _siguiente_clases_bitacoras(trigger: str, clase_alertas: str, clase_episodios: str):
    """
    Decide el nuevo par de clases ('bitacora-abierta'/'bitacora-cerrada') a
    partir de qué título disparó el clic. Vive separada del callback para
    poder probarla sin un contexto de Dash: el callback solo lee
    ``callback_context`` y le pasa el resultado a esta función.
    """
    if trigger == 'bitacora-alertas-header':
        clase_alertas = 'bitacora-cerrada' if clase_alertas == 'bitacora-abierta' else 'bitacora-abierta'
    elif trigger == 'bitacora-episodios-header':
        clase_episodios = 'bitacora-cerrada' if clase_episodios == 'bitacora-abierta' else 'bitacora-abierta'
    return clase_alertas, clase_episodios


def _tabla_paginada(df: pd.DataFrame, id_tabla: str, columna_color: str = None,
                     mapa_color: dict = None, texto_claro_valores: tuple = ()):
    """
    Tabla tipo hoja de cálculo con paginación nativa de Dash. Si se da
    columna_color + mapa_color, colorea solo la celda de esa columna según el
    valor, igual que en el Excel.
    """
    columnas = list(df.columns)
    style_data_conditional = []
    if columna_color and mapa_color:
        for valor, color in mapa_color.items():
            texto = '#ffffff' if valor in texto_claro_valores else '#173d4c'
            style_data_conditional.append({
                'if': {'filter_query': f'{{{columna_color}}} = "{valor}"', 'column_id': columna_color},
                'backgroundColor': color,
                'color': texto,
                'fontWeight': '700',
            })

    return dash_table.DataTable(
        id=id_tabla,
        columns=[{'name': c.replace('\n', ' '), 'id': c} for c in columnas],
        data=df.to_dict('records'),
        page_action='native',
        page_size=10,
        sort_action='native',
        style_table={'overflowX': 'auto'},
        style_header={'backgroundColor': '#e8edef', 'color': '#173d4c', 'fontWeight': '700',
                      'textAlign': 'left', 'padding': '8px 10px', 'border': 'none'},
        style_cell={'padding': '8px 10px', 'fontFamily': 'Inter, Segoe UI, sans-serif', 'fontSize': '15px',
                    'color': COLOR_GRIS_MUTE, 'textAlign': 'left', 'minWidth': '90px', 'maxWidth': '240px',
                    'overflow': 'hidden', 'textOverflow': 'ellipsis', 'border': f'1px solid {COLOR_GRIS_100}'},
        style_data_conditional=style_data_conditional,
        style_as_list_view=True,
    )


def _ordenar_por_no_desc(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena por la columna 'No' (primera columna) de mayor a menor, si es numérica."""
    if df.empty:
        return df
    col_no = df.columns[0]
    d = df.copy()
    d['_no_num'] = pd.to_numeric(d[col_no], errors='coerce')
    d = d.sort_values('_no_num', ascending=False).drop(columns='_no_num')
    return d


def _card_bitacora_alertas(df_alertas_2026_raw: pd.DataFrame):
    """Bitácora de 'NUEVO alertas 2026' (columnas A a K menos D, E, F e I)."""
    cols_a_k = list(df_alertas_2026_raw.columns)[0:11]
    cols_mostrar = [c for i, c in enumerate(cols_a_k) if i not in (3, 4, 5, 8)]
    df = _ordenar_por_no_desc(df_alertas_2026_raw[cols_mostrar])

    col_fase = _buscar_columna(cols_mostrar, 'fase decretada', 'fase')
    mapa_color = {'Alerta': '#FCB308', 'Emergencia': '#FC3508'} if col_fase else None

    return html.Div([
        html.Div([
            html.Div([
                'Registro de Eventos (Alertas y Emergencias) ',
                html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
            ], id='bitacora-alertas-header',
                     className='bitacora-titulo',
                     n_clicks=0,
                     style={'flex': '1', 'color': '#173d4c', 'fontWeight': '700',
                            'fontSize': '18px'}),
            _icono_descarga('btn-pdf-alertas'),
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
                  'marginBottom': '4px'}),
        html.Div('Eventos extraordinarios decretados de acuerdo con el Programa de Reducción de Emisiones '
                  'Contaminantes a la Atmósfera (PRECA) vigente.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        html.Div([
            html.Div(
                _tabla_paginada(df, 'tabla-bitacora-alertas', columna_color=col_fase, mapa_color=mapa_color,
                                texto_claro_valores=('Emergencia',)),
                style={'position': 'relative'}),
            html.Div('Se muestran los últimos 10 registros, puedes descargar en el ícono de la '
                      'parte superior derecha o avanzar con las flechas en la parte inferior izquierda.',
                      style={'position': 'absolute', 'bottom': '12px', 'left': '10px',
                             'color': COLOR_GRIS_MUTE, 'fontSize': '11px', 'zIndex': 2}),
        ], className='bitacora-contenido'),
        dcc.Download(id='descarga-pdf-alertas'),
    ], id='bitacora-alertas-wrapper', className='bitacora-cerrada',
       style={**CARD_STYLE, 'position': 'relative', 'marginBottom': '20px'}), df


def _card_bitacora_episodios(df_episodios_2026_raw: pd.DataFrame):
    """Bitácora completa de 'Nuevo episodios 2026', columnas hasta 'Estado', sin 'Fin'."""
    cols_totales = list(df_episodios_2026_raw.columns)
    col_estado = _buscar_columna(cols_totales, 'estado')
    if col_estado is not None:
        cols_mostrar = cols_totales[0:cols_totales.index(col_estado) + 1]
    else:
        cols_mostrar = cols_totales
    col_fin = _buscar_columna(cols_mostrar, 'fin')
    if col_fin:
        cols_mostrar = [c for c in cols_mostrar if c != col_fin]
    df = _ordenar_por_no_desc(df_episodios_2026_raw[cols_mostrar])
    cols = list(df.columns)

    col_evento = _buscar_columna(cols, 'evento')
    mapa_color = None
    texto_claro = ()
    if col_evento:
        mapa_color = {
            'PreContingencia Atmosférica': '#FFB300',
            'Contingencia Atmosférica Fase I': '#EF6C00',
            'Contingencia Atmosférica Fase II': '#DC143C',
            'Contingencia Atmosférica Fase III': '#4B0082',
        }
        texto_claro = ('Contingencia Atmosférica Fase I', 'Contingencia Atmosférica Fase II',
                        'Contingencia Atmosférica Fase III')

    return html.Div([
        html.Div([
            html.Div([
                'Registro de Episodios (Precontingencias y Contingencias) ',
                html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
            ], id='bitacora-episodios-header',
                     className='bitacora-titulo',
                     n_clicks=0,
                     style={'flex': '1', 'color': '#173d4c', 'fontWeight': '700',
                            'fontSize': '18px'}),
            _icono_descarga('btn-pdf-episodios'),
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
                  'marginBottom': '4px'}),
        html.Div('Episodios decretados de acuerdo con el Programa de Reducción de Emisiones '
                  'Contaminantes a la Atmósfera (PRECA) vigente.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        html.Div([
            html.Div(
                _tabla_paginada(df, 'tabla-bitacora-episodios', columna_color=col_evento, mapa_color=mapa_color,
                                texto_claro_valores=texto_claro),
                style={'position': 'relative'}),
            html.Div('Se muestran los últimos 10 registros, puedes descargar en el ícono de la '
                      'parte superior derecha o avanzar con las flechas en la parte inferior izquierda.',
                      style={'position': 'absolute', 'bottom': '12px', 'left': '10px',
                             'color': COLOR_GRIS_MUTE, 'fontSize': '11px', 'zIndex': 2}),
        ], className='bitacora-contenido'),
        dcc.Download(id='descarga-pdf-episodios'),
    ], id='bitacora-episodios-wrapper', className='bitacora-cerrada',
       style={**CARD_STYLE, 'position': 'relative', 'marginBottom': '20px'}), df


# ── Recolección de datos y puente Colab → servidor ─────────────────────────
#
# El dashboard necesita seis tablas. Antes las leía él mismo de Sheets, lo
# que ataba la parte visual a tener credenciales de Google. Ahora la lectura
# vive en _leer_datos_de_sheets() y el dashboard solo recibe un diccionario
# de DataFrames, venga de donde venga: de Sheets (en Colab) o de un JSON
# (en el servidor).
#
# Nombres de las tablas dentro del diccionario y del JSON.
_TABLAS_DASHBOARD = (
    'episodios', 'alertas', 'imeca',
    'alertas_2026_raw', 'episodios_2026_raw',
    'resumen_mensual', 'acumulado',
)


def _leer_datos_de_sheets(gc, spreadsheet_destino, acumulado: pd.DataFrame) -> dict:
    """Lee de Google Sheets todo lo que el dashboard necesita."""
    sh_fuente_2026 = gc.open_by_url(URL_FUENTE_2026)
    sh_resumen_mensual = gc.open_by_url(URL_RESUMEN_MENSUAL)

    return {
        'episodios':          pd.DataFrame(spreadsheet_destino.worksheet("Episodios").get_all_records()),
        'alertas':            pd.DataFrame(spreadsheet_destino.worksheet("ALERTAS").get_all_records()),
        'imeca':              pd.DataFrame(spreadsheet_destino.worksheet("IMECA MAXIMO").get_all_records()),
        'alertas_2026_raw':   _worksheet_a_df(sh_fuente_2026.worksheet("NUEVO alertas 2026")),
        'episodios_2026_raw': _worksheet_a_df(sh_fuente_2026.worksheet("Nuevo episodios 2026")),
        'resumen_mensual':    _worksheet_a_df(sh_resumen_mensual.worksheet("Resumen MENSUAL")),
        'acumulado':          acumulado,
    }


def exportar_datos_dashboard(datos: dict, ruta: str = 'datos_dashboard.json') -> str:
    """
    Escribe a un JSON todo lo que el dashboard necesita para dibujarse.

    Este es el puente Colab -> servidor: Colab corre el pipeline y genera
    este archivo; el servidor solo lo lee. Así la parte visual no necesita
    credenciales de Google ni acceso a las hojas.

    Las tablas se guardan como listas de diccionarios (orient='records'),
    que es el formato más estable para reconstruirlas después. Se incluye
    la fecha de generación para poder mostrar qué tan frescos son los datos.
    """
    paquete = {
        'generado': datetime.now().isoformat(timespec='seconds'),
        'tablas': {nombre: _df_nativo(datos[nombre]).to_dict(orient='records')
                   for nombre in _TABLAS_DASHBOARD},
    }

    ruta_p = Path(ruta)
    ruta_p.write_text(json.dumps(paquete, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"OK: Datos del dashboard exportados a {ruta_p.resolve()} "
          f"({ruta_p.stat().st_size / 1024:.0f} KB)")
    return str(ruta_p.resolve())


def cargar_datos_dashboard(ruta: str = 'datos_dashboard.json') -> dict:
    """Reconstruye el diccionario de DataFrames a partir del JSON exportado."""
    ruta_p = Path(ruta)
    if not ruta_p.exists():
        raise FileNotFoundError(
            f"No se encontró {ruta_p.resolve()}. Genera el archivo desde Colab con "
            f"run_full_pipeline(exportar_json='datos_dashboard.json').")

    paquete = json.loads(ruta_p.read_text(encoding='utf-8'))
    print(f"Datos del dashboard leídos de {ruta_p.name} "
          f"(generados el {paquete.get('generado', '?')})")

    return {nombre: pd.DataFrame(filas)
            for nombre, filas in paquete['tablas'].items()}


def build_dash_app_desde_json(ruta: str = 'datos_dashboard.json') -> Dash:
    """
    Arma el dashboard leyendo el JSON en vez de Google Sheets. Es el punto de
    entrada para el servidor.
    """
    return build_dash_app(datos=cargar_datos_dashboard(ruta))


def build_dash_app(gc=None, spreadsheet_destino=None, acumulado: pd.DataFrame = None,
                    datos: dict = None) -> Dash:
    """
    Construye la app de Dash: KPIs + Episodios + Alertas/Emergencias +
    IMECA Máximo + serie mensual + mapa + bitácoras.

    Se puede llamar de dos formas:
      · build_dash_app(gc, spreadsheet_destino, acumulado)  -> lee de Sheets
      · build_dash_app(datos=...)                           -> usa un dict ya
        cargado (por ejemplo desde el JSON, en el servidor)

    Cuando no hay `gc`, los callbacks que refrescan desde Sheets cada 20s se
    desactivan: sin credenciales no hay a quién preguntarle. El dashboard
    muestra la foto del JSON, que es justo lo que se espera en el servidor.
    """
    if datos is None:
        datos = _leer_datos_de_sheets(gc, spreadsheet_destino, acumulado)

    df_episodios          = datos['episodios']
    df_alertas            = datos['alertas']
    df_imeca              = datos['imeca']
    df_alertas_2026_raw   = datos['alertas_2026_raw']
    df_episodios_2026_raw = datos['episodios_2026_raw']
    df_resumen_mensual    = datos['resumen_mensual']
    acumulado             = datos['acumulado']

    eventos_activos_2026 = _eventos_activos_2026(df_alertas_2026_raw)
    episodios_activos_2026 = _episodios_activos_raw(df_episodios_2026_raw)
    hay_conexion_sheets = gc is not None

    col_2025_ep = df_episodios.columns[1]
    col_2026_ep = df_episodios.columns[2]
    col_2026_al = df_alertas.columns[2]

    # Fila superior: las tres fichas solo con datos 2026. La tercera
    # (Episodios activos) se actualiza sola cada 20s con su callback.
    kpis = html.Div([
        _kpi_activaciones_simaj(df_episodios, col_2026_ep),
        _kpi_alertas_emergencias(df_alertas, col_2026_al),
        html.Div(id='ficha-eventos-activos',
                 children=_card_eventos_activos(eventos_activos_2026, episodios_activos_2026),
                 style={'flex': '1', 'minWidth': '260px', 'display': 'flex'}),
        dcc.Interval(id='refrescar-eventos',
                     interval=CONFIG.refresco_eventos_seg * 1000, n_intervals=0),
    ], className='fila-apilable', style={'display': 'flex', 'gap': '16px', 'flexWrap': 'wrap',
              'alignItems': 'stretch', 'marginBottom': '20px'})

    episodios_card = html.Div([
        html.Div([
            'Comparativo de Episodios de mala calidad del Aire ',
            html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
            '-',
            html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
        ], style={'color': '#173d4c', 'fontWeight': '700', 'fontSize': '18px', 'marginBottom': '4px'}),
        html.Div('Episodios decretados de acuerdo con el Programa de Reducción de Emisiones Contaminantes a la Atmósfera (PRECA) vigente.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        html.Div([
            html.Div([_tabla_episodios(df_episodios)],
                     style={'flex': '1 1 420px', 'minWidth': '340px'}),
            # Contenedores vacíos que ECharts llena desde el callback
            # clientside. La altura va aquí porque ECharts necesita que el
            # div ya tenga tamaño antes de inicializarse.
            html.Div([
                # La altura iguala a la de la tabla comparativa de la
                # izquierda (~450 px), para que las dos mitades del bloque
                # terminen a la misma altura en vez de dejar un hueco.
                html.Div(id='echart-precontingencias',
                         style={'flex': '1', 'minWidth': '340px', 'height': ALTO_GRAFICA_EPISODIOS}),
                html.Div(id='echart-contingencias-f1',
                         style={'flex': '1', 'minWidth': '340px', 'height': ALTO_GRAFICA_EPISODIOS}),
            ], className='fila-apilable', style={'flex': '1 1 400px', 'minWidth': '690px',
                      'display': 'flex', 'gap': '6px', 'alignItems': 'stretch'}),
        ], className='fila-apilable', style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap',
                  'alignItems': 'stretch'}),

        # Destino de descarte del callback que dibuja las gráficas.
        dcc.Store(id='echarts-dibujado'),
        dcc.Store(id='datos-echarts-episodios', data={
            'precontingencias': _datos_grafica_episodios(
                df_episodios, col_2025_ep, col_2026_ep, 1, 'Precontingencias atmosféricas'),
            'contingencias_f1': _datos_grafica_episodios(
                df_episodios, col_2025_ep, col_2026_ep, 2, 'Contingencias Fase I'),
        }),
    ], style={**CARD_STYLE, 'marginBottom': '20px'})

    alertas_card = html.Div([
        html.Div([
            'Comparativo de Alertas y Emergencias ',
            html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
            '-',
            html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
        ], style={'color': '#173d4c', 'fontWeight': '700', 'fontSize': '18px', 'marginBottom': '4px'}),
        html.Div('Episodios derivados de eventos extraordinarios, como incendios u otras fuentes '
                  'que pueden afectar la calidad del aire.',
                  style={'color': COLOR_GRIS_MUTE, 'fontSize': '15px', 'marginBottom': '14px'}),
        # Tabla izquierda + barras horizontales derechas en el mismo cuadro
        html.Div([
            # Mitad izquierda: tabla comparativa
            html.Div(
                [_tabla_alertas(df_alertas)],
                style={'flex': '1 1 420px', 'minWidth': '340px'},
            ),
            # Mitad derecha: dos barras horizontales apiladas (una por año)
            html.Div([
                html.Div(id='echart-barras-alertas-25',
                         style={'flex': '1', 'minHeight': '110px'}),
                html.Div(id='echart-barras-alertas-26',
                         style={'flex': '1', 'minHeight': '110px'}),
            ], style={'flex': '1 1 400px', 'minWidth': '610px',
                      'display': 'flex', 'flexDirection': 'column', 'gap': '6px',
                      'alignSelf': 'stretch',
                      'paddingLeft': '22px'}),
        ], className='fila-apilable',
           style={'display': 'flex', 'gap': '20px',
                  'flexWrap': 'wrap', 'alignItems': 'stretch'}),
        # Datos para ECharts (se consumen en el clientside_callback)
        dcc.Store(id='datos-barras-alertas',
                  data=_datos_barras_alertas(df_alertas)),
        dcc.Store(id='barras-alertas-dibujado'),
    ], style={**CARD_STYLE, 'flex': '1', 'minWidth': '320px', 'marginBottom': '20px'})

    imeca_card = html.Div([_card_imeca(df_imeca)], style={**CARD_STYLE, 'marginBottom': '20px'})

    acumulado_idx = acumulado.set_index('Estación')

    # Foto fija del mapa, generada aquí en Python. El callback del PDF la usa
    # en vez de intentar capturar el mapa interactivo desde el navegador.
    fig_mapa = _fig_mapa(acumulado)
    mapa_estatico_src = _fig_a_base64(fig_mapa, ancho=1000, alto=520)

    if mapa_estatico_src is None:
        # Segundo intento sin los mosaicos del mapa base. Si kaleido no logra
        # descargar el estilo de CARTO (sin red, bloqueado o versión vieja de
        # kaleido), un fondo blanco sí se renderiza: se pierden las calles
        # pero quedan las burbujas y los nombres de estación, que es lo que
        # el PDF necesita mostrar.
        print("  Reintentando la imagen del mapa sin el mapa base…")
        fig_sin_mosaicos = _fig_mapa(acumulado)
        fig_sin_mosaicos.update_layout(map_style='white-bg')
        mapa_estatico_src = _fig_a_base64(fig_sin_mosaicos, ancho=1000, alto=520)

    if mapa_estatico_src:
        print("OK: Imagen del mapa lista para el PDF.")

    mapa_card = html.Div([
        html.Div([
            'Comparativo en días de Calidad del Aire ',
            html.Span('2025', style={'color': COLOR_2025, 'fontWeight': '800'}),
            ' vs ',
            html.Span('2026', style={'color': COLOR_2026, 'fontWeight': '800'}),
            ' por estación de monitoreo',
        ], style={'color': '#173d4c', 'fontWeight': '700', 'fontSize': '18px', 'marginBottom': '4px'}),
        html.Div([
            html.Div([
                dcc.Graph(id='mapa-grafico', figure=fig_mapa,
                          className='grafica-mapa', style={'height': '480px'},
                          config={'responsive': True}),
                # Oculta en pantalla; el callback del PDF la muestra en lugar
                # del mapa interactivo justo antes de capturar.
                # Fuera del flujo del documento (no solo display:none) para
                # que no ocupe espacio ni la dibuje html2canvas.
                html.Img(id='mapa-estatico', src=mapa_estatico_src,
                         style={'position': 'absolute', 'width': '1px',
                                'height': '1px', 'opacity': '0',
                                'pointerEvents': 'none', 'left': '-9999px'}),
                # Dispara, una sola vez al cargar, el ajuste de zoom del mapa
                # en celular (ver clientside_callback correspondiente). No
                # tiene otro propósito: Dash exige un Input real y la figura
                # no vive en un Store como la de la serie mensual.
                dcc.Store(id='mapa-cargado', data=True),
                # Destino de descarte de ese mismo callback (dibuja
                # directamente con Plotly.relayout y no devuelve nada útil,
                # pero Dash exige una salida).
                dcc.Store(id='mapa-zoom-ajustado'),
            ], style={'flex': '2', 'minWidth': '320px'}),
            html.Div([
                # Encabezado del panel: título y aclaración van juntos como un
                # bloque, separados del contenido por una línea. Sin esa
                # división, la aclaración y el texto de abajo competían por
                # ser lo mismo y el panel se veía desalineado.
                html.Div([
                    html.Div('Detalle por estación', style={
                        'color': '#173d4c', 'fontWeight': '700',
                        'fontSize': '16px', 'marginBottom': '4px'}),
                    html.Div('Categoría acorde con el Índice Aire y Salud de la NOM-172-SEMARNAT-2023',
                             style={'color': COLOR_GRIS_MUTE, 'fontSize': '13px',
                                    'lineHeight': '1.45'}),
                ], style={'borderBottom': f'1px solid {COLOR_GRIS_100}',
                          'paddingBottom': '12px', 'marginBottom': '4px'}),
                html.Div(id='mapa-detalle', children=_detalle_placeholder()),
            ], className='panel-detalle-mapa',
               style={'flex': '1', 'minWidth': '260px',
                      'borderLeft': f'1px solid {COLOR_GRIS_100}', 'paddingLeft': '20px'}),
        ], className='fila-apilable', style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap'}),
        html.P([
            "El color y tamaño de cada burbuja representan el ",
            html.B("cambio en días de buena calidad (2026 vs 2025)"),
            " por estación: ",
            html.Span("aqua", style={'color': COLOR_2026, 'fontWeight': '700'}),
            " = tuvo más días de buena calidad que el año pasado (mejora), ",
            html.Span("gris", style={'color': COLOR_2025, 'fontWeight': '700'}),
            " = tuvo menos (empeora); entre más grande la burbuja, mayor el cambio. "
            "Pasa el cursor sobre una estación para ver el comparativo completo en el panel de la derecha.",
        ], style={'color': COLOR_MUTED, 'fontSize': '14px', 'marginTop': '14px', 'marginBottom': '0'}),
    ], style={**CARD_STYLE, 'marginBottom': '20px'})

    bitacora_alertas_card, df_bitacora_alertas = _card_bitacora_alertas(df_alertas_2026_raw)
    bitacora_episodios_card, df_bitacora_episodios = _card_bitacora_episodios(df_episodios_2026_raw)

    parametros_card = html.Div(
        _tabla_parametros(),
        style={**CARD_STYLE, 'marginBottom': '20px'})

    # El meta 'viewport' es lo que hace que un teléfono renderice a su ancho
    # real. Sin él asume 980px y luego encoge la página entera, así que el
    # reporte se ve diminuto por más medias queries que se escriban.
    app = Dash(__name__, meta_tags=[
        {'name': 'viewport', 'content': 'width=device-width, initial-scale=1'},
    ])
    app.title = 'Reporte Diario de Calidad del Aire 2026'

    # CSS global + de impresión. Los cortes responsive viven aparte, en
    # assets/responsive.css, que Dash sirve solo por estar en esa carpeta.
    #
    #  · min-width solo durante la captura: antes era fijo en html/body y el
    #    dashboard nunca se angostaba de 1280px, así que en una ventana chica
    #    aparecía scroll horizontal en vez de reacomodarse. Se conserva la
    #    idea original —el PDF debe salir con el layout de escritorio— pero
    #    limitada al momento de la foto, mediante la clase que pone el
    #    callback de descarga.
    #  · print-color-adjust: exact -> obliga al navegador a imprimir los
    #    fondos de color, que por defecto omite para ahorrar tinta.
    app.index_string = '''<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
    <style>
      html, body {
        margin: 0;
      }
      /* Ancho de escritorio forzado mientras html2canvas toma la foto, para
         que el PDF salga igual desde un celular que desde una computadora.
         La clase la pone y la quita el callback de descarga. */
      body.capturando-pdf,
      body.capturando-pdf #react-entry-point {
        min-width: 1280px;
      }
      @media print {
        @page { size: A4 portrait; margin: 5mm; }
        /* La impresión con Ctrl+P también va en el layout de escritorio. Antes
           lo heredaba del min-width global; al hacerlo responsive hay que
           repetirlo aquí, o imprimir desde una ventana angosta saldría con las
           tarjetas apiladas. */
        html, body, #react-entry-point {
          min-width: 1280px !important;
        }
        html, body {
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
          background: #ffffff !important;
        }
        * {
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
        }
        button, .previous-next-container, .dash-spreadsheet-menu {
          display: none !important;
        }
        #react-entry-point > div { padding: 0 !important; }
        .dash-graph, table {
          break-inside: avoid;
          page-break-inside: avoid;
        }
      }
    </style>
  </head>
  <body>
    {%app_entry%}
    <footer>
      {%config%}
      {%scripts%}
      {%renderer%}
    </footer>
  </body>
</html>'''

    app.layout = html.Div([
        # Botón de descarga en su propia fila, para no descentrar el título
        # ni competir con los logos.
        html.Div(_icono_descarga('btn-pdf-dashboard'),
                 style={'display': 'flex', 'justifyContent': 'flex-end', 'marginBottom': '8px'}),

        # Los tres bloques corresponden a las tres páginas del PDF: el
        # callback de descarga captura cada uno por separado y le da su
        # propia hoja, en vez de cortar a ciegas una imagen larguísima.
        # Visualmente no cambian nada — son contenedores sin estilo.
        html.Div([
            _encabezado_reporte(),
            kpis,
            episodios_card,
            html.Div([alertas_card], className='fila-apilable',
                     style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap'}),
        ], id='pdf-pagina-1'),

        html.Div([
            _card_serie_mensual_2025(df_resumen_mensual),
            mapa_card,
            imeca_card,
        ], id='pdf-pagina-2'),

        html.Div([
            bitacora_episodios_card,
            bitacora_alertas_card,
            parametros_card,
        ], id='pdf-pagina-3'),
    ], className='lienzo-reporte', style={
        'backgroundColor': COLOR_BG,
        'minHeight': '100vh',
        'padding': '28px 36px',
        'fontFamily': 'Inter, Segoe UI, sans-serif',
        'color': COLOR_TEXT,
    })

    @app.callback(Output('mapa-detalle', 'children'), Input('mapa-grafico', 'hoverData'))
    def _actualizar_detalle_estacion(hover_data):
        if not hover_data or 'points' not in hover_data or not hover_data['points']:
            return _detalle_placeholder()
        punto = next((p for p in hover_data['points'] if p.get('curveNumber') == 0),
                      hover_data['points'][0])
        # Con mode='markers+text' el campo donde Plotly mete el nombre puede
        # variar entre versiones (hovertext, text, customdata). Se prueban
        # todos para que funcione sin importar la versión de Plotly/Colab.
        estacion = punto.get('hovertext')
        if estacion not in acumulado_idx.index:
            estacion = punto.get('text')
        if estacion not in acumulado_idx.index:
            cd = punto.get('customdata')
            if cd and len(cd) > 1:
                estacion = cd[1]
        if estacion not in acumulado_idx.index:
            return _detalle_placeholder()
        return _tabla_detalle_estacion(estacion, acumulado_idx.loc[estacion])

    # En celular las bitácoras largas empiezan colapsadas y se abren al tocar el
    # título. En escritorio la regla simplemente no aplica, así que el estado de
    # la clase no afecta la visibilidad.
    @app.callback(
        Output('bitacora-alertas-wrapper', 'className'),
        Output('bitacora-episodios-wrapper', 'className'),
        Input('bitacora-alertas-header', 'n_clicks'),
        Input('bitacora-episodios-header', 'n_clicks'),
        State('bitacora-alertas-wrapper', 'className'),
        State('bitacora-episodios-wrapper', 'className'),
        prevent_initial_call=True
    )
    def _toggle_bitacoras(n_alertas, n_episodios, clase_alertas, clase_episodios):
        trigger = callback_context.triggered[0]['prop_id'].split('.')[0] if callback_context.triggered else None
        return _siguiente_clases_bitacoras(trigger, clase_alertas, clase_episodios)

    # Estos dos callbacks releen de Sheets cada 20s. Solo se registran si hay
    # conexión: en el servidor, que trabaja con el JSON, no hay credenciales
    # de Google y el dashboard muestra la foto del archivo.
    if hay_conexion_sheets:
        def _leer_hoja_cacheada(url: str, hoja: str, segundos: int) -> pd.DataFrame:
            """
            Lee una pestaña de Sheets reusando el resultado entre pestañas del
            navegador. Sin esto, N pestañas abiertas son N lecturas por tick.
            """
            return cache_sheets.obtener(
                (url, hoja), segundos,
                lambda: _worksheet_a_df(gc.open_by_url(url).worksheet(hoja)))

        @app.callback(Output('ficha-eventos-activos', 'children'),
                      Input('refrescar-eventos', 'n_intervals'))
        def _refrescar_eventos_activos(_n):
            # Así, un cambio en 'Fecha termino' se refleja sin volver a correr
            # todo el pipeline de Python.
            df_alertas_fresco = _leer_hoja_cacheada(
                URL_FUENTE_2026, "NUEVO alertas 2026", CONFIG.refresco_eventos_seg)
            df_episodios_fresco = _leer_hoja_cacheada(
                URL_FUENTE_2026, "Nuevo episodios 2026", CONFIG.refresco_eventos_seg)
            return _card_eventos_activos(
                _eventos_activos_2026(df_alertas_fresco),
                _episodios_activos_raw(df_episodios_fresco),
            )

        # Escribe al Store y no a la gráfica: quien dibuja es el callback
        # clientside de abajo, que es el que sabe el ancho de la pantalla.
        @app.callback(Output('figura-serie-base', 'data'),
                      Input('refrescar-serie-mensual', 'n_intervals'))
        def _refrescar_serie_mensual(_n):
            df_fresco = _leer_hoja_cacheada(
                URL_RESUMEN_MENSUAL, "Resumen MENSUAL", CONFIG.refresco_mensual_seg)
            return _fig_serie_buena_mensual(df_fresco).to_plotly_json()

    # ── Descarga de las bitácoras en PDF ──────────────────────────────────
    #
    # La generación vive en numeralia.reporte.pdf: armar un PDF con fpdf2 no
    # tiene por qué estar anidado dentro de la función que construye la app.
    _ruta_logo_simaj = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    NOMBRE_CARPETA_LOGOS, LOGO_SIMAJ)
    _ruta_logo_semadet = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      NOMBRE_CARPETA_LOGOS, LOGO_SEMADET)
    registrar_descargas(app, [
        DescargaPDF(
            df=df_bitacora_alertas,
            titulo='Alertas y Emergencias Atmosféricas 2026',
            subtitulo='Eventos extraordinarios decretados de acuerdo con el Programa de Reducción de Emisiones Contaminantes a la Atmósfera (PRECA) vigente.\nCORTE AL ' + _fecha_encabezado(),
            archivo='Alertas_y_Emergencias_2026.pdf',
            boton_id='btn-pdf-alertas',
            descarga_id='descarga-pdf-alertas',
            logo_izq=_ruta_logo_simaj,
            logo_der=_ruta_logo_semadet,
        ),
        DescargaPDF(
            df=df_bitacora_episodios,
            titulo='Episodios de Mala calidad del aire',
            subtitulo='Episodios decretados de acuerdo con el Programa de Reducción de Emisiones Contaminantes a la Atmósfera (PRECA) vigente.\nCORTE AL ' + _fecha_encabezado(),
            archivo='Episodios.pdf',
            boton_id='btn-pdf-episodios',
            descarga_id='descarga-pdf-episodios',
            logo_izq=_ruta_logo_simaj,
            logo_der=_ruta_logo_semadet,
        ),
    ])

    # ── Gráficas de episodios con ECharts ─────────────────────────────────
    #
    # ECharts se carga por CDN (ver index_string) y se dibuja desde el
    # navegador, no desde Python. El renderer va en 'svg' a propósito: el de
    # canvas, que es el predeterminado, no se captura bien al generar el PDF.
    app.clientside_callback(
        """
        function(datos) {
            if (!datos || typeof echarts === 'undefined') {
                return window.dash_clientside.no_update;
            }

            // Texturas por contaminante: el color queda reservado para la
            // severidad, así que los tres se distinguen por trama.
            // idxLeyenda elige de qué año toma su tono el cuadrito de la
            // leyenda: 0 = 2025 (azul marino), 1 = 2026 (aqua).
            function dibujar(idDiv, cfg, idxLeyenda, animar) {
                const el = document.getElementById(idDiv);
                if (!el) { return; }

                let chart = echarts.getInstanceByDom(el);
                if (!chart) { chart = echarts.init(el, null, {renderer: 'svg'}); }

                // Modo compacto para tablet y celular: tipografía y márgenes
                // internos más chicos, que es lo que permite bajar el alto de
                // la caja sin asfixiar los segmentos.
                //
                // Lo decide el CSS a través de la variable --modo-compacto (ver
                // assets/responsive.css), NO una medición del ancho: en
                // escritorio estas dos gráficas van en pareja y miden ~277px,
                // casi lo mismo que en tablet (~232px), así que cualquier
                // umbral de ancho agarraría también al escritorio. Ya se
                // intentó y salió mal.
                //
                // Se lee del body y no de :root para que la regla
                // .capturando-pdf pueda devolver la versión de escritorio
                // mientras se toma la foto del PDF.
                const compacta = getComputedStyle(document.body)
                                    .getPropertyValue('--modo-compacto').trim() === '1';
                el.dataset.compacta = String(compacta);

                // Todas las medidas que cambian entre los dos modos, juntas
                // para poder compararlas de un golpe de vista.
                const med = compacta
                    ? {nombre: 11, valor: 14, salto: 12, total: 14, distancia: 16,
                       titulo: 13, eje: 12, gridArriba: 40, gridAbajo: 22}
                    : {nombre: 10, valor: 14, salto: 10, total: 17, distancia: 22,
                       titulo: 15, eje: 14, gridArriba: 64, gridAbajo: 28};

                // El eje lo fija el año con más episodios, así que un
                // segmento chico ocupa la misma fracción por más alta que se
                // haga la gráfica. De ahí el alto mínimo de abajo.
                const maxTotal = Math.max.apply(null, cfg.totales) || 1;

                const series = cfg.series.map(function (s, i) {
                    return {
                        name: s.nombre,
                        type: 'bar',
                        stack: 'total',
                        barWidth: '48%',
                        // Sin esto, un valor de 2 sobre 162 se dibuja como una
                        // astilla de 4 px y no se ve. Cuesta algo de precisión
                        // proporcional en los segmentos chicos, pero el número
                        // va rotulado, así que el dato sigue siendo exacto.
                        // En compacto baja junto con la tipografía: 14px le
                        // bastan a un número de 13px.
                        barMinHeight: compacta ? 14 : 20,
                        // Este itemStyle es el que toma el cuadrito de la
                        // leyenda: lleva el tono del año que indique
                        // idxLeyenda, para que la leyenda se lea de claro a
                        // oscuro igual que la barra de ese año.
                        itemStyle: {
                            color: cfg.escalas_anio[idxLeyenda][i],
                            borderColor: cfg.colores_anio[idxLeyenda],
                            borderWidth: 1.2,
                            borderRadius: 4
                        },
                        label: {
                            show: true,
                            position: 'inside',
                            formatter: function (p) {
                                if (!p.value) { return ''; }
                                // Nombre y valor en una sola línea para evitar
                                // amontonamiento en segmentos pequeños.
                                return '{n|' + s.nombre + ':}{v| ' + p.value + '}';
                            },
                            // El color del texto lo decide el tono del relleno,
                            // que depende del año y del contaminante: hay tonos
                            // oscuros que piden letra blanca y claros que piden
                            // letra oscura. Aquí se usa el año de la leyenda;
                            // más abajo se reajusta por dato, que es donde se
                            // conoce el año real de cada barra.
                            rich: {
                                n: {fontSize: med.nombre, color: cfg.colores_texto_anio[idxLeyenda][i].nombre, lineHeight: med.salto, align: 'center'},
                                v: {fontSize: med.valor, fontWeight: 'bold', color: cfg.colores_texto_anio[idxLeyenda][i].valor, align: 'center'}
                            }
                        },
                        labelLayout: {hideOverlap: true},
                        emphasis: {focus: 'series'}
                    };
                });

                // Serie invisible de 0 que solo carga la etiqueta del total,
                // para no meter una caja encima de la barra.
                series.push({
                    name: 'total',
                    type: 'bar',
                    stack: 'total',
                    silent: true,
                    itemStyle: {color: 'transparent'},
                    // El total va en el color de su año, para que se lea
                    // junto con la barra que corona.
                    data: cfg.totales.map(function (_, j) {
                        return {value: 0, label: {color: cfg.colores_anio[j]}};
                    }),
                    label: {
                        show: true,
                        position: 'top',
                        formatter: function (p) { return cfg.totales[p.dataIndex]; },
                        fontSize: med.total,
                        fontWeight: 'bold',
                        backgroundColor: 'transparent',
                        borderWidth: 0,
                        padding: 0,
                        // 8 px alcanzaban cuando el segmento de arriba era una
                        // astilla; con el alto mínimo, la caja sube y el total
                        // se le encimaba.
                        distance: med.distancia
                    }
                });

                // Cada segmento toma el tono que le toca dentro de la escala
                // de su año: i elige el contaminante, j elige el año.
                cfg.series.forEach(function (s, i) {
                    series[i].data = s.datos.map(function (v, j) {
                        return {
                            // null y no 0: con 0, barMinHeight dibujaría una
                            // caja de 20 px para un contaminante que no activó
                            // ningún episodio.
                            value: v > 0 ? v : null,
                            itemStyle: {
                                color: cfg.escalas_anio[j][i],
                                borderColor: cfg.colores_anio[j],
                                // Ozono (índice 0) con opacidad un poco menor
                                // para que se vea más clarito sin cambiar tonos.
                                opacity: i === 0 ? 0.85 : 1
                            },
                            // El texto toma el color que le toca al tono de SU
                            // relleno, no al de la leyenda: en la misma gráfica
                            // conviven segmentos oscuros con letra blanca y
                            // claros con letra oscura.
                            label: {
                                rich: {
                                    n: {fontSize: med.nombre, color: cfg.colores_texto_anio[j][i].nombre, lineHeight: med.salto, align: 'center'},
                                    v: {fontSize: med.valor, fontWeight: 'bold', color: cfg.colores_texto_anio[j][i].valor, align: 'center'}
                                }
                            }
                        };
                    });
                });

                chart.setOption({
                    title: {
                        text: cfg.titulo,
                        left: 'center',
                        top: 4,
                        textStyle: {fontSize: med.titulo, fontWeight: 'bold', color: cfg.color_titulo}
                    },
                    grid: {left: 6, right: 6, top: med.gridArriba,
                           bottom: med.gridAbajo, containLabel: true},
                    tooltip: {
                        trigger: 'item',
                        formatter: function (p) {
                            const t = cfg.totales[p.dataIndex];
                            const pct = t ? (p.value / t * 100).toFixed(1) : 0;
                            return '<b>' + p.seriesName + '</b><br/>' +
                                   p.name + ': ' + p.value + ' episodios<br/>' +
                                   pct + '% de ' + t;
                        }
                    },
                    legend: {show: false},
                    xAxis: {
                        type: 'category',
                        data: cfg.anios,
                        axisLine: {show: false},
                        axisTick: {show: false},
                        axisLabel: {
                            fontSize: med.eje, fontWeight: 'bold',
                            // Cada año en su color, igual que el encabezado
                            // de la tabla comparativa.
                            color: function (valor, indice) {
                                return cfg.colores_anio[indice] || '""" + COLOR_GRIS + """';
                            }
                        }
                    },
                    yAxis: {type: 'value', show: false},
                    series: series,
                    animationDuration: animar === false ? 0 : 600
                }, true);

                chart.resize();
            }

            // Precontingencias con la leyenda en el azul de 2025 y Fase I con
            // la de 2026, para comparar las dos lecturas lado a lado.
            dibujar('echart-precontingencias', datos.precontingencias, 0);
            dibujar('echart-contingencias-f1', datos.contingencias_f1, 1);

            // El callback del PDF necesita rehacer estas gráficas en su versión
            // de escritorio ANTES de fotografiarlas, y 'dibujar' vive en este
            // cierre. Se expone para que pueda llamarla y esperarla, en vez de
            // disparar un 'resize' y adivinar cuánto tarda.
            window.__redibujarEpisodios = function (animar) {
                dibujar('echart-precontingencias', datos.precontingencias, 0, animar);
                dibujar('echart-contingencias-f1', datos.contingencias_f1, 1, animar);
            };

            // ECharts no se reajusta solo al cambiar el tamaño de la ventana:
            // conserva las medidas que tenía al inicializarse y el SVG se
            // deforma. Este listener le pide recalcular en cada resize. La
            // bandera evita registrarlo varias veces.
            //
            // resize() reajusta medidas pero NO vuelve a aplicar la opción, y
            // la opción sí depende del modo compacto (tipografías, márgenes,
            // barMinHeight). Así que al cruzar el breakpoint hay que redibujar;
            // mientras no se cruce basta con reajustar, que es mucho más barato
            // y no reinicia la animación.
            if (!window.__echartsResizeBound) {
                window.__echartsResizeBound = true;
                window.addEventListener('resize', function () {
                    const modo = getComputedStyle(document.body)
                                    .getPropertyValue('--modo-compacto').trim() === '1';
                    const graficas = [
                        ['echart-precontingencias', datos.precontingencias, 0],
                        ['echart-contingencias-f1', datos.contingencias_f1, 1]
                    ];
                    graficas.forEach(function (g) {
                        const el = document.getElementById(g[0]);
                        if (!el) { return; }
                        const instancia = echarts.getInstanceByDom(el);
                        if (!instancia) { return; }
                        if (el.dataset.compacta !== String(modo)) {
                            dibujar(g[0], g[1], g[2]);
                        } else {
                            instancia.resize();
                        }
                    });
                });
            }

            return window.dash_clientside.no_update;
        }
        """,
        # El callback dibuja en el navegador y no devuelve nada útil, pero
        # Dash exige una salida. Va a un Store de descarte: antes apuntaba a
        # 'title', que dcc.Store no tiene, y Dash lo rechazaba en cada carga.
        Output('echarts-dibujado', 'data'),
        Input('datos-echarts-episodios', 'data'),
    )

    # ── Acordeón de la tabla comparativa de episodios ────────────────────
    #
    # Los grupos 1 (Precontingencias) y 2 (Contingencias Fase I) tienen sub-filas
    # en la tabla; el toggle alterna display:none ↔ table-row-group y rota la
    # flecha ▶ ↔ ▼. Usa paridad de n_clicks: impar=abierto, par=cerrado.
    app.clientside_callback(
        """
        function(n1, n2) {
            const abierto  = 'table-row-group';
            const cerrado  = 'none';
            const toggle   = (n) => ({display: ((n || 0) % 2 === 1) ? abierto : cerrado});
            const flecha   = (n) => ((n || 0) % 2 === 1) ? '▼' : '▶';
            return [toggle(n1), toggle(n2), flecha(n1), flecha(n2)];
        }
        """,
        Output('sub-episodios-1', 'style'),
        Output('sub-episodios-2', 'style'),
        Output('arrow-episodios-1', 'children'),
        Output('arrow-episodios-2', 'children'),
        Input('toggle-episodios-1', 'n_clicks'),
        Input('toggle-episodios-2', 'n_clicks'),
        prevent_initial_call=True,
    )

    # ── Barras horizontales Alertas / Emergencias ─────────────────────────
    #
    # Mismo estilo visual que las gráficas de episodios: esquinas redondeadas,
    # borde del color del año, rich text con nombre + valor en tamaños distintos,
    # y labelLayout: hideOverlap para segmentos angostos.
    # Dos barras, una por año. Tono tenue = Alertas; tono pleno = Emergencias.
    app.clientside_callback(
        """
        function(datos) {
            if (!datos || typeof echarts === 'undefined') {
                return window.dash_clientside.no_update;
            }

            function dibujar(divId, anio,
                             valorA, valorE,
                             colorA, colorE,
                             textoA, textoE) {
                const el = document.getElementById(divId);
                if (!el) return;
                let c = echarts.getInstanceByDom(el);
                if (!c) c = echarts.init(el, null, {renderer: 'svg'});

                const total = (valorA || 0) + (valorE || 0) || 1;
                // Por debajo del 12 % del total el segmento es demasiado angosto
                // para mostrar el nombre; solo sale el número.
                const fracEstrecha = 0.12;

                c.setOption({
                    animation: false,
                    grid: {top: 8, bottom: 8, left: 8, right: 8, containLabel: true},
                    xAxis: {type: 'value', show: false},
                    yAxis: {
                        type: 'category',
                        data: [anio],
                        axisLabel: {color: colorE, fontWeight: 'bold', fontSize: 13},
                        axisTick: {show: false},
                        axisLine: {show: false}
                    },
                    series: [
                        {
                            // Alertas – segmento izquierdo
                            type: 'bar', stack: 'total',
                            data: [valorA],
                            barWidth: '72%',
                            barMinHeight: 20,
                            itemStyle: {
                                color: colorA,
                                borderColor: colorE,
                                borderWidth: 1.2,
                                borderRadius: 4
                            },
                            label: {
                                show: !!valorA,
                                position: 'inside',
                                formatter: function(p) {
                                    if (!p.value) return '';
                                    if (p.value / total < fracEstrecha) {
                                        return '{v|' + p.value + '}';
                                    }
                                    return '{n|Alertas}\\n{v|' + p.value + '}';
                                },
                                rich: {
                                    n: {fontSize: 11, color: textoA, lineHeight: 12, align: 'center'},
                                    v: {fontSize: 14, fontWeight: 'bold', color: textoA, align: 'center'}
                                }
                            },
                            labelLayout: {hideOverlap: true},
                            emphasis: {focus: 'series'}
                        },
                        {
                            // Emergencias – segmento derecho
                            type: 'bar', stack: 'total',
                            data: [valorE],
                            barWidth: '72%',
                            barMinHeight: 20,
                            itemStyle: {
                                color: colorE,
                                borderColor: colorE,
                                borderWidth: 1.2,
                                borderRadius: 4
                            },
                            label: {
                                show: !!valorE,
                                position: 'inside',
                                formatter: function(p) {
                                    if (!p.value) return '';
                                    if (p.value / total < fracEstrecha) {
                                        return '{v|' + p.value + '}';
                                    }
                                    return '{n|Emergencias}\\n{v|' + p.value + '}';
                                },
                                rich: {
                                    n: {fontSize: 11, color: textoE, lineHeight: 12, align: 'center'},
                                    v: {fontSize: 14, fontWeight: 'bold', color: textoE, align: 'center'}
                                }
                            },
                            labelLayout: {hideOverlap: true},
                            emphasis: {focus: 'series'}
                        }
                    ]
                });
            }

            dibujar('echart-barras-alertas-25', '2025',
                    datos.alertas_25, datos.emergencias_25,
                    datos.color_a25, datos.color_e25,
                    datos.texto_a25, datos.texto_e25);
            dibujar('echart-barras-alertas-26', '2026',
                    datos.alertas_26, datos.emergencias_26,
                    datos.color_a26, datos.color_e26,
                    datos.texto_a26, datos.texto_e26);
            return window.dash_clientside.no_update;
        }
        """,
        Output('barras-alertas-dibujado', 'data'),
        Input('datos-barras-alertas', 'data'),
    )

    # ── Serie mensual: cintillo de pastillas solo si hay ancho ───────────
    #
    # Las pastillas se dibujan con el ancho en unidades de categoría y el alto
    # en fracción del lienzo, así que al angostarse la gráfica el ancho encoge
    # y el alto no: en un teléfono quedan de 5 px de ancho por 33 de alto, con
    # un número de dos dígitos encima. En vez de deformarlas se quitan, y el
    # dato se sigue consultando al tocar cada punto.
    #
    # Se adapta aquí y no en Python porque el servidor no sabe el ancho de la
    # pantalla; y se hace clientside para no pagar un viaje al servidor cada
    # vez que alguien gira el teléfono.
    app.clientside_callback(
        """
        function(figuraBase) {
            if (!figuraBase) { return window.dash_clientside.no_update; }

            // Umbral propio de esta gráfica, distinto de los 768px del resto
            // del layout: aquí no manda el acomodo de las tarjetas sino la
            // geometría de la pastilla. Con C = ancho del contenedor y N meses
            // en el eje, la pastilla (0.24 categorías) mide
            // 0.24 × (C − 80) / N píxeles. Un número de dos dígitos a 13px
            // pide ~18px, de donde C ≥ 75 × N + 80.
            //
            // El número de meses es dinámico: crece de 1 a 12 conforme se van
            // capturando registros en 2026. Por eso el umbral se calcula aquí
            // a partir del categoryarray de la figura, en vez de fijarse a 980
            // (que era el valor para los 12 meses de un año completo).
            const nMeses = (figuraBase.layout && figuraBase.layout.xaxis &&
                            figuraBase.layout.xaxis.categoryarray)
                           ? figuraBase.layout.xaxis.categoryarray.length
                           : 12;
            const ANCHO_MINIMO_CINTILLO = 75 * nMeses + 80;

            // Se mide el contenedor y no la ventana por dos razones: es lo que
            // de verdad fija el tamaño de la pastilla, y durante la captura
            // del PDF el layout se ensancha a 1280px SIN que la ventana
            // cambie. Con window.innerWidth, un PDF descargado desde el
            // celular se iría sin cintillo.
            // El cintillo también necesita ALTO: su margen superior se lleva
            // 95px fijos, así que en una caja baja no cabe ni con ancho de
            // sobra. Sin esta guarda, el PDF sacado de un celular salía con la
            // gráfica achatada (ancho forzado a 1280 pero alto compacto).
            const ALTO_MINIMO_CINTILLO = 300;

            function anchoGrafica() {
                const el = document.getElementById('grafico-serie-mensual');
                // En el primer dibujo el nodo puede no estar medido todavía;
                // ahí se cae a la ventana, que peca de ancha y conserva el
                // cintillo en vez de quitarlo de más.
                return (el && el.clientWidth) ? el.clientWidth : window.innerWidth;
            }

            function altoGrafica() {
                const el = document.getElementById('grafico-serie-mensual');
                return (el && el.clientHeight) ? el.clientHeight : 999;
            }

            function cabeElCintillo() {
                return anchoGrafica() >= ANCHO_MINIMO_CINTILLO
                       && altoGrafica() >= ALTO_MINIMO_CINTILLO;
            }

            // El listener de abajo necesita la última figura buena; el
            // refresco periódico la reemplaza cada media hora.
            window.__serieBase = figuraBase;

            function adaptar(fig) {
                // Copia profunda: la figura del Store no se toca, porque es la
                // que se vuelve a usar cuando la pantalla se ensancha.
                const copia = JSON.parse(JSON.stringify(fig));
                if (cabeElCintillo()) { return copia; }

                copia.layout.shapes = [];
                copia.layout.annotations = [];
                // El margen superior de 95 px existía para dejarle lugar al
                // cintillo; sin él es un hueco. Y la leyenda vivía en y=1.30,
                // o sea arriba del cintillo: si solo se recorta el margen,
                // queda fuera del lienzo.
                copia.layout.margin = {l: 46, r: 12, t: 34, b: 50};
                copia.layout.legend = Object.assign({}, copia.layout.legend,
                                                    {y: 1.10, x: 0.5, xanchor: 'center'});
                return copia;
            }

            if (!window.__serieResizeBound) {
                window.__serieResizeBound = true;
                let cabiaAntes = cabeElCintillo();
                window.addEventListener('resize', function () {
                    const cabeAhora = cabeElCintillo();
                    // Solo al cruzar el umbral: redibujar en cada píxel del
                    // arrastre es caro y no cambia nada.
                    if (cabeAhora === cabiaAntes) { return; }
                    cabiaAntes = cabeAhora;
                    window.dash_clientside.set_props(
                        'grafico-serie-mensual',
                        {figure: adaptar(window.__serieBase)});
                });
            }

            return adaptar(figuraBase);
        }
        """,
        Output('grafico-serie-mensual', 'figure'),
        Input('figura-serie-base', 'data'),
    )

    # ── Mapa: menos zoom en celular ───────────────────────────────────────
    #
    # El zoom de 10.3 con el que se genera el mapa (ver _fig_mapa) se pensó
    # para el ancho de escritorio; en un teléfono, con la mitad del espacio,
    # se ve demasiado cerca y cuesta ubicar las estaciones entre sí. Se ajusta
    # aquí y no en Python porque el servidor no sabe el ancho de la pantalla.
    #
    # Solo aplica en celular (<= 767px), no en tablet: en tablet el mapa ya
    # se ve bien tal cual. Por eso se compara contra window.innerWidth en vez
    # de reusar '--modo-compacto', que se enciende también en tablet.
    #
    # No afecta al PDF: la imagen del mapa que va en el PDF es la que genera
    # Python con kaleido (ver 'mapa-estatico'), siempre al zoom de escritorio,
    # y no pasa por este callback.
    app.clientside_callback(
        """
        function(_disparo) {
            const UMBRAL_CELULAR = 767;
            const ZOOM_ESCRITORIO = 10.3;
            const ZOOM_CELULAR = 9.3;

            function esCelular() { return window.innerWidth <= UMBRAL_CELULAR; }

            function ajustar() {
                const zoom = esCelular() ? ZOOM_CELULAR : ZOOM_ESCRITORIO;
                Plotly.relayout('mapa-grafico', {'map.zoom': zoom});
            }

            if (!window.__mapaResizeBound) {
                window.__mapaResizeBound = true;
                let eraCelularAntes = esCelular();
                window.addEventListener('resize', function () {
                    const esCelularAhora = esCelular();
                    // Solo al cruzar el umbral, igual que con el cintillo de
                    // la serie mensual: no hace falta redibujar en cada
                    // píxel del arrastre.
                    if (esCelularAhora === eraCelularAntes) { return; }
                    eraCelularAntes = esCelularAhora;
                    ajustar();
                });
            }

            ajustar();
            return window.dash_clientside.no_update;
        }
        """,
        Output('mapa-zoom-ajustado', 'data'),
        Input('mapa-cargado', 'data'),
    )

    # ── PDF del dashboard: captura y descarga directa ────────────────────
    #
    # html2canvas fotografía el DOM y jsPDF arma el archivo, así el clic
    # descarga el PDF sin pasar por el diálogo de impresión.
    #
    # Cada bloque 'pdf-pagina-N' se captura por separado y ocupa una hoja,
    # escalado para caber completo. Así el corte entre páginas cae donde
    # queremos y no a la mitad de una tarjeta, y el mapa se reduce solo lo
    # necesario para el PDF sin afectar la pantalla.
    #
    # Antes de capturar hay que convertir las gráficas a imagen: html2canvas
    # no sabe leer el canvas WebGL de Plotly (el mapa saldría en blanco) ni
    # rasteriza confiablemente el SVG de ECharts.
    app.clientside_callback(
        """
        async function(n_clicks) {
            if (!n_clicks) { return window.dash_clientside.no_update; }
            if (typeof html2canvas === 'undefined' || typeof jspdf === 'undefined') {
                alert('No se pudieron cargar las librerias de PDF. Revisa tu conexion.');
                return window.dash_clientside.no_update;
            }

            const restaurar = [];

            // Sobrescrituras temporales de estilo en línea, para las
            // gráficas de episodios (ver más abajo). Se guarda [elemento,
            // propiedad, valor original] de cada una, para devolverlas tal
            // cual en el 'finally'.
            const overridesEpisodios = [];
            function forzarEstilo(el, prop, valor) {
                if (!el) { return; }
                overridesEpisodios.push([el, prop, el.style.getPropertyValue(prop)]);
                el.style.setProperty(prop, valor, 'important');
            }

            // El PDF tiene que salir con el layout de escritorio aunque se
            // descargue desde un celular: html2canvas fotografía el DOM vivo,
            // así que si la pantalla es angosta capturaría la versión apilada.
            // La clase impone los 1280px (regla .capturando-pdf del
            // index_string) solo durante la foto.
            //
            // El evento 'resize' es el que despierta a ECharts y a Plotly: los
            // dos escuchan window.resize y recalculan sus medidas solos. Sin
            // él, las gráficas se fotografían con el tamaño que tenían en la
            // pantalla chica aunque el contenedor ya sea más ancho. La espera
            // le da tiempo al navegador de rehacer el acomodo antes de que se
            // midan los contenedores con getBoundingClientRect.
            const anchoForzado = document.body.clientWidth < 1280;
            let overlay = null;
            if (anchoForzado) {
                // Forzar 1280px en el body NO cambia el ancho que ve un
                // '@media query': el viewport real sigue siendo el del
                // celular, así que el acordeón y el carrusel siguen activos
                // en la pantalla real mientras se prepara la foto. Sin este
                // overlay, el usuario ve la pantalla desbordarse y las
                // tarjetas armarse a medias durante ese instante.
                overlay = document.createElement('div');
                overlay.style.position = 'fixed';
                overlay.style.inset = '0';
                overlay.style.zIndex = '999999';
                overlay.style.backgroundColor = '#ffffff';
                overlay.style.display = 'flex';
                overlay.style.alignItems = 'center';
                overlay.style.justifyContent = 'center';
                overlay.style.fontFamily = 'Inter, Segoe UI, sans-serif';
                overlay.style.fontSize = '16px';
                overlay.style.color = '#465055';
                overlay.textContent = 'Generando PDF...';
                document.body.appendChild(overlay);

                document.body.classList.add('capturando-pdf');

                // La fila de la tabla + gráficas de episodios usa la misma
                // clase 'fila-apilable' que el resto de filas que sí se
                // apilan en celular. El resto del PDF sale bien porque
                // html2canvas vuelve a renderizar esas partes DENTRO de una
                // ventana virtual de 1280px (vía 'windowWidth'), donde el
                // '@media' de celular ya no aplica. Pero estas dos gráficas
                // NO pasan por esa ventana virtual: se convierten a imagen
                // ANTES, midiendo el DOM real — y el DOM real sigue viendo un
                // viewport angosto de verdad (forzar min-width en el body no
                // cambia lo que un '@media query' considera "la pantalla").
                // Ahí sigue activo '.fila-apilable { flex-direction: column }'
                // + '.fila-apilable > * { width: 100% }', así que la gráfica
                // que se mide termina con el ancho de TODA la fila en vez del
                // que le toca junto a la tabla. Se restituyen a mano, con
                // 'important', los mismos valores que trae cada una inline
                // en escritorio (ver el html.Div de episodios más arriba).
                const precontDiv = document.getElementById('echart-precontingencias');
                const contF1Div = document.getElementById('echart-contingencias-f1');
                const parejaGraficas = precontDiv && precontDiv.parentElement;
                const filaEpisodios = parejaGraficas && parejaGraficas.parentElement;
                const tablaEpisodios = filaEpisodios && Array.from(filaEpisodios.children)
                    .find(function (hijo) { return hijo !== parejaGraficas; });

                if (filaEpisodios) { forzarEstilo(filaEpisodios, 'flex-direction', 'row'); }
                if (parejaGraficas) {
                    forzarEstilo(parejaGraficas, 'flex-direction', 'row');
                    forzarEstilo(parejaGraficas, 'flex', '1 1 400px');
                    forzarEstilo(parejaGraficas, 'min-width', '380px');
                    forzarEstilo(parejaGraficas, 'width', 'auto');
                    // Las dos imágenes sustitutas quedan con un ancho fijo
                    // en píxeles (ver 'sustituir'); si el espacio disponible
                    // sobra, sin esto se pegan a la izquierda en vez de
                    // quedar centradas como pareja.
                    forzarEstilo(parejaGraficas, 'justify-content', 'center');
                }
                if (tablaEpisodios) {
                    forzarEstilo(tablaEpisodios, 'flex', '1 1 420px');
                    forzarEstilo(tablaEpisodios, 'min-width', '340px');
                    forzarEstilo(tablaEpisodios, 'width', 'auto');
                }
                [precontDiv, contF1Div].forEach(function (el) {
                    if (!el) { return; }
                    forzarEstilo(el, 'flex', '1');
                    forzarEstilo(el, 'min-width', '190px');
                    forzarEstilo(el, 'width', 'auto');
                    // Mismo problema que el ancho, y misma solución: el alto
                    // de 450px depende de que una regla externa le gane por
                    // especificidad a la del '@media' de celular, y esa
                    // carrera no siempre se resuelve antes de que
                    // 'chart.resize()' lea el tamaño del contenedor.
                    forzarEstilo(el, 'height', '""" + ALTO_GRAFICA_EPISODIOS + """');
                });

                // El 'resize' lo escuchan Plotly y el cintillo de la serie
                // mensual, que se reacomodan solos con él.
                window.dispatchEvent(new Event('resize'));
                // Las de ECharts NO se dejan al listener: se rehacen aquí,
                // explícitamente y sin animación. Confiar en el evento
                // significaba depender de que el redibujo terminara dentro de la
                // espera de abajo, y la animación dura 600ms — más que ella.
                if (typeof window.__redibujarEpisodios === 'function') {
                    window.__redibujarEpisodios(false);
                }
                await new Promise(res => setTimeout(res, 450));
            }

            // Cambia una gráfica por su imagen y espera a que el navegador
            // termine de decodificarla. Dos detalles importantes:
            //
            //  · Se espera a 'onload': sin eso, html2canvas alcanza a
            //    fotografiar la imagen todavía vacía.
            //  · La gráfica se SACA del DOM en vez de ocultarse. html2canvas
            //    clona y lee todos los <canvas> aunque estén ocultos, y el
            //    del mapa está "contaminado" por los iconos que carga desde
            //    unpkg.com sin permiso de origen cruzado; esa lectura falla
            //    y arruina la captura de toda esa zona.
            function sustituir(div, url, medidaExacta) {
                return new Promise(function (resolve) {
                    const img = document.createElement('img');

                    if (medidaExacta) {
                        // Medidas exactas en píxeles, tomadas del div justo
                        // antes de sacarlo del DOM. Es la única forma de
                        // garantizar que la imagen ocupe el mismo espacio que
                        // ocupaba la gráfica: dejarlo en manos de 'width:100%'
                        // + 'height:auto' significa confiar en que el ancho
                        // del contenedor no cambie entre que se mide el
                        // tamaño real (con la gráfica) y que se inserta la
                        // imagen (ya sin ella) — y en la práctica el 'flex'
                        // de alrededor sí se reacomoda entre esos dos
                        // momentos, lo que dejaba la imagen más angosta y,
                        // por 'height:auto', también más baja de lo debido.
                        img.style.width = medidaExacta.ancho + 'px';
                        img.style.height = medidaExacta.alto + 'px';
                        img.style.maxWidth = 'none';
                        img.style.flex = 'none';
                    } else {
                        // Ancho relativo al contenedor y alto automático: con el
                        // ancho en píxeles del nodo de Plotly la imagen se
                        // desbordaba unos pixeles y se encimaba con el panel de
                        // al lado. 'height: auto' conserva la proporción.
                        img.style.width = '100%';
                        img.style.maxWidth = '100%';
                        img.style.height = 'auto';

                        // El div que se retira puede ser un elemento flex: si
                        // la imagen no copia su 'flex', dos imágenes a
                        // width:100% piden cada una el ancho completo y se
                        // aprietan entre sí.
                        const estilo = getComputedStyle(div);
                        if (estilo.display !== 'none' && div.parentNode
                                && getComputedStyle(div.parentNode).display === 'flex') {
                            img.style.flex = estilo.flex;
                            img.style.minWidth = '0';
                            img.style.alignSelf = 'flex-start';
                        }
                    }
                    img.style.display = 'block';
                    img.style.boxSizing = 'border-box';
                    img.onload = function () { resolve(true); };
                    img.onerror = function () {
                        console.warn('La imagen sustituta no cargo');
                        resolve(false);
                    };
                    img.src = url;

                    const padre = div.parentNode;
                    padre.insertBefore(img, div.nextSibling);
                    padre.removeChild(div);
                    restaurar.push([div, img]);
                });
            }

            // Gráficas de Plotly (mapa y serie mensual).
            for (const id of ['mapa-grafico', 'grafico-serie-mensual']) {
                const contenedor = document.getElementById(id);
                if (!contenedor) {
                    console.warn('PDF: no existe el elemento ' + id);
                    continue;
                }

                // dcc.Graph pone el id en un contenedor EXTERNO; el nodo real
                // de Plotly (el que tiene _fullLayout y sabe exportarse) es un
                // hijo con la clase js-plotly-plot. Sin este paso el bucle
                // saltaba ambas gráficas en silencio.
                const div = contenedor._fullLayout
                            ? contenedor
                            : contenedor.querySelector('.js-plotly-plot');
                if (!div) {
                    console.warn('PDF: no se encontro el nodo de Plotly en ' + id);
                    continue;
                }

                const caja = div.getBoundingClientRect();
                const opciones = {
                    format: 'png',
                    width: Math.round(caja.width) || 900,
                    height: Math.round(caja.height) || 400,
                    scale: 2
                };
                let url = null;

                // El mapa trae su foto ya lista desde Python (kaleido). Se
                // usa esa: capturarlo desde el navegador no es confiable
                // porque su canvas es WebGL y los mosaicos vienen de otro
                // dominio.
                if (id === 'mapa-grafico') {
                    const estatico = document.getElementById('mapa-estatico');
                    if (estatico && estatico.src && estatico.src.indexOf('data:image') === 0) {
                        url = estatico.src;
                        console.log('PDF: usando la imagen del mapa generada en Python');
                    } else {
                        console.warn('PDF: NO hay imagen del mapa pre-generada. '
                                     + 'Revisa que kaleido este instalado y vuelve a correr '
                                     + 'la celda del codigo y run_full_pipeline().');
                    }
                }

                if (!url) {
                    try {
                        // Para las gráficas normales basta con forzar un
                        // redibujo y esperar dos frames antes de leer.
                        await Plotly.relayout(div, {});
                        await new Promise(res => requestAnimationFrame(() =>
                                                  requestAnimationFrame(res)));
                        url = await Plotly.toImage(div, opciones);
                    } catch (e) {
                        console.warn('Captura directa fallo en ' + id, e);
                    }
                }

                if (url) { await sustituir(div, url); }
            }

            // Gráficas de ECharts (barras de episodios). Las dos se miden y
            // se convierten a imagen ANTES de sustituir ninguna: si se
            // sustituyera una y LUEGO se midiera la otra, la primera ya
            // habría dejado de ser un elemento flex (la imagen tiene ancho
            // fijo), y eso le regala todo el espacio que sobra a la segunda
            // — que es justo por lo que una barra salía de un tamaño y la
            // otra de otro.
            const capturasEpisodios = [];
            for (const id of ['echart-precontingencias', 'echart-contingencias-f1']) {
                const div = document.getElementById(id);
                if (!div) { continue; }
                const inst = echarts.getInstanceByDom(div);
                if (!inst) { continue; }
                try {
                    // Se remide justo antes de fotografiar. Hace falta porque
                    // ECharts no remide solo: el PNG saldría con las medidas
                    // viejas y la imagen se vería estirada.
                    inst.resize();
                    await new Promise(res => requestAnimationFrame(() =>
                                              requestAnimationFrame(res)));
                    // Medida real del div EN ESTE MOMENTO, con la gráfica
                    // todavía puesta: es la que se le copia a la imagen
                    // sustituta, en vez de dejarla calcular su propio tamaño
                    // con 'width:100%' + 'height:auto' (ver 'sustituir').
                    const caja = div.getBoundingClientRect();
                    const url = inst.getDataURL({
                        type: 'png', pixelRatio: 2, backgroundColor: '#ffffff'
                    });
                    capturasEpisodios.push({div, url, ancho: caja.width, alto: caja.height});
                } catch (e) { console.warn('ECharts ' + id, e); }
            }
            for (const c of capturasEpisodios) {
                await sustituir(c.div, c.url, {ancho: c.ancho, alto: c.alto});
            }

            // Los botones no tienen sentido en el PDF.
            const botones = Array.from(document.querySelectorAll('button'));
            botones.forEach(b => { b.dataset.vis = b.style.visibility;
                                   b.style.visibility = 'hidden'; });

            await new Promise(res => setTimeout(res, 400));

            try {
                // Se capturan las tres páginas ANTES de armar el PDF, porque
                // la orientación de cada hoja se decide con la forma real de
                // su contenido (ver abajo) y eso hay que conocerlo desde la
                // primera página, no solo desde la segunda en adelante.
                const lienzos = [];
                for (const idPag of ['pdf-pagina-1', 'pdf-pagina-2', 'pdf-pagina-3']) {
                    const bloque = document.getElementById(idPag);
                    if (!bloque) { continue; }
                    lienzos.push(await html2canvas(bloque, {
                        scale: 2, backgroundColor: '#ffffff',
                        useCORS: true, logging: false,
                        windowWidth: bloque.scrollWidth,
                        windowHeight: bloque.scrollHeight
                    }));
                }

                const margenX = 8;
                const margenY = 5;
                let pdf = null;
                lienzos.forEach(function (lienzo) {
                    // Todas las hojas en vertical (A4 portrait), con el
                    // contenido alineado arriba para no dejar tanto espacio
                    // en blanco en la parte superior.
                    const orientacion = 'p';

                    if (!pdf) {
                        pdf = new jspdf.jsPDF(orientacion, 'mm', 'a4');
                    } else {
                        pdf.addPage('a4', orientacion);
                    }

                    const anchoPag = pdf.internal.pageSize.getWidth();
                    const altoPag = pdf.internal.pageSize.getHeight();
                    const anchoUtil = anchoPag - margenX * 2;
                    const altoUtil = altoPag - margenY * 2;

                    // Se escala por el lado que primero se topa con el borde,
                    // así el bloque cabe entero en la hoja sin salirse.
                    const escala = Math.min(anchoUtil / lienzo.width,
                                            altoUtil / lienzo.height);
                    const ancho = lienzo.width * escala;
                    const alto = lienzo.height * escala;

                    pdf.addImage(lienzo.toDataURL('image/png'), 'PNG',
                                 (anchoPag - ancho) / 2, margenY, ancho, alto);
                });

                if (!pdf) { throw new Error('No hay páginas que exportar.'); }

                const hoy = new Date().toISOString().slice(0, 10);
                pdf.save('Reporte_Calidad_del_Aire_' + hoy + '.pdf');
            } catch (e) {
                console.error('Error al generar el PDF', e);
                alert('No se pudo generar el PDF. Revisa la consola.');
            } finally {
                // Pase lo que pase, se devuelve el dashboard a su estado
                // interactivo: sin esto, un error a media captura lo dejaría
                // con imágenes estáticas hasta recargar.
                botones.forEach(b => { b.style.visibility = b.dataset.vis || ''; });
                // Se regresa cada gráfica a su lugar exacto: se reinserta
                // justo antes de su imagen sustituta y luego se quita esa.
                restaurar.forEach(([div, img]) => {
                    if (img.parentNode) { img.parentNode.insertBefore(div, img); }
                    img.remove();
                });
                // Y se devuelve la pantalla a su ancho real. El 'resize' final
                // es el que reacomoda las gráficas a la vista del teléfono;
                // sin él se quedan dibujadas a 1280px dentro de un contenedor
                // angosto.
                if (anchoForzado) {
                    // Todo lo forzado a mano (fila, anchos, alto) se quita
                    // ANTES del 'resize' de abajo, para que ese evento
                    // redibuje las gráficas ya con las medidas reales de
                    // celular en vez de las de escritorio.
                    overridesEpisodios.forEach(function (par) {
                        const [el, prop, valorOriginal] = par;
                        if (valorOriginal) {
                            el.style.setProperty(prop, valorOriginal);
                        } else {
                            el.style.removeProperty(prop);
                        }
                    });
                    document.body.classList.remove('capturando-pdf');
                    window.dispatchEvent(new Event('resize'));
                    if (typeof window.__redibujarEpisodios === 'function') {
                        window.__redibujarEpisodios(true);
                    }
                }
                if (overlay && overlay.parentNode) { overlay.remove(); }
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output('btn-pdf-dashboard', 'title'),
        Input('btn-pdf-dashboard', 'n_clicks'),
        prevent_initial_call=True,
    )

    return app


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
