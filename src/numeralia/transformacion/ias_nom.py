"""
Pipeline IAS/NOM: carga la BD validada, calcula los promedios móviles y las
categorías IAS/NOM (horario y diario), arma la numeralia por estación y la
escribe en Sheets, y suma el acumulado histórico sin duplicar días.

Salió de main.py (Secciones 2-3) en el Paso 5 del refactor.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import gspread
import numpy as np
import pandas as pd

from numeralia.dominio.ias import compute_ias_daily
from numeralia.dominio.nom172 import (
    NOM_LIMITS,
    clasifica,
    compute_nom_daily_flags,
    redondear_por_nom as _round_by_nom,
)
from numeralia.dominio.nowcast import (
    rolling_8h,
    rolling_24h,
    round_half_up,
    serie_nowcast_por_estacion,
)
from numeralia.dominio.suficiencia import (
    CONTAMINANTES as _CONTAMINANTES,
    INVALID_FLAGS as _INVALID_FLAGS,
    METEOROLOGIA as _METEOROLOGIA,
    SUF_MIN_HORAS as _SUF_MIN_HORAS,
)
from numeralia.sheets import _df_a_valores_sheet


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


def fecha_acumulada(spreadsheet, anio: int, fecha) -> bool:
    """
    True si ese día del año `anio` ya quedó sumado en 'Analitica' (aparece en
    la hoja de control 'Acumuladas'). La usa el sensor del reporte diario por
    correo para saber cuándo ya terminó la actualización de la mañana, en vez
    de mandarlo a una hora fija del reloj.
    """
    return pd.to_datetime(fecha).date() in _fechas_ya_acumuladas(spreadsheet, anio)
