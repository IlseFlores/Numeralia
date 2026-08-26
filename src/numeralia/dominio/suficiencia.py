"""
Criterios de suficiencia de datos.

Un promedio calculado con pocas horas válidas no es comparable con el límite
normativo. Estos criterios deciden cuándo un día (o un año) tiene datos
suficientes para evaluarse; cuando no los tiene, el resultado es None y no
'cumple', que es una distinción que importa en un reporte oficial.
"""

from __future__ import annotations

import calendar

# Contaminantes y variables meteorológicas que trae la base ENVISTA.
CONTAMINANTES = ['O3', 'NO', 'NO2', 'NOX', 'SO2', 'CO', 'PM10', 'PM2.5']
METEOROLOGIA  = ['IT', 'ET', 'RH', 'WS', 'WD', 'PP', 'ATM', 'RS', 'UVI']

# Banderas de ENVISTA que marcan un dato como inválido. La cadena vacía
# también cuenta: una celda en blanco no es un cero.
INVALID_FLAGS = ["IF", "IO", "IR", "ND", "VE", "SE", "NE", "IC", "VZ", ""]

# Horas válidas mínimas para dar por bueno un día (18 de 24 = 75%).
SUF_MIN_HORAS = 18

# Porcentaje mínimo de días válidos en el año (75%).
SUF_MIN_PCT_ANUAL = 0.75


def suf_min_yearly(year: int) -> int:
    """
    Días válidos mínimos para evaluar el cumplimiento anual: 75% del año,
    redondeado hacia arriba. Los bisiestos piden un día más.
    """
    return 275 if calendar.isleap(year) else 274


def dia_suficiente(horas_validas: int) -> bool:
    """True si el día tiene las horas válidas que exige la norma."""
    return horas_validas >= SUF_MIN_HORAS
