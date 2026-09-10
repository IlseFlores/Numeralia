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

warnings.filterwarnings('ignore')


# ============================================================================
# SECCIÓN 0: AUTENTICACIÓN Y UTILIDADES DE ENTORNO
# ============================================================================

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
from numeralia.consola import forzar_utf8                          # noqa: E402

forzar_utf8()

_ruta_env = _cargar_dotenv()
if _ruta_env:
    print(f"[config] Configuracion cargada de {_ruta_env}")

ARCHIVO_CREDENCIALES = os.getenv('GOOGLE_CREDENCIALES_ARCHIVO', 'credenciales.json')


from numeralia.ingesta.auth import _en_colab, autenticar             # noqa: E402


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


from numeralia.dominio.nom172 import (                            # noqa: E402
    redondear_por_nom as _round_by_nom,
)


from numeralia.dominio.nom172 import compute_nom_daily_flags      # noqa: E402
from numeralia.dominio.ias import (                                # noqa: E402
    IAS_SOURCE,
    ORDEN_DOM,
    compute_ias_daily,
)
from numeralia.dominio.nom172 import frac_rango as _frac_rango     # noqa: E402


# ── Constantes compartidas por los cálculos de numeralia ────────────────
# ============================================================================
# SECCIÓN 4: EPISODIOS + IMECA MÁXIMO
# ============================================================================

# ============================================================================
# SECCIÓN 5: ALERTAS
# ============================================================================

# ============================================================================
# SECCIÓN 6: DASHBOARD (Dash)
# ============================================================================
#
# Todo el dashboard vive ahora en numeralia.reporte (formato, figuras,
# datos_graficas, kpis, tablas, tarjetas y app) y en assets/dashboard.js.
# run_full_pipeline solo necesita estas tres piezas del ensamblado:

from numeralia.transformacion.alertas import run_alertas         # noqa: E402
from numeralia.transformacion.episodios import run_episodios     # noqa: E402
from numeralia.transformacion.ias_nom import (                   # noqa: E402
    actualizar_acumulado,
    ejecutar_pipeline_ias,
)
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
