"""
DAG del reporte diario de calidad del aire.

En vez de mandar el correo a una hora fija del reloj, un sensor espera a que
termine la actualización de la mañana: revisa la hoja 'Acumuladas' hasta que
el día de ayer quede registrado para AMBOS años que compara el reporte (el
actual y el anterior). Solo entonces descarga los 3 PDF del dashboard, los
fusiona y manda el correo — una vez, porque el DAG corre una vez al día y el
sensor no vuelve a pasar una vez que ya avanzó.

Ver numeralia.notificaciones.reporte_diario para la lógica real; este
archivo solo la cuelga de un calendario.

PAUSADO A PROPÓSITO (schedule=None) desde el 7 de octubre de 2026: un correo
automático salió con los datos del día anterior en vez del actual (ver
numeralia.notificaciones.reporte_diario — ya se corrigió la causa, pero se
decidió no reactivar el disparo automático hasta tener un servidor propio,
sin depender de terceros para vigilarlo de cerca). Mientras tanto, el DAG
sigue existiendo y se puede correr A MANO desde la interfaz de Airflow
(botón "Trigger DAG") para probar.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

# Ruta DENTRO del contenedor de Airflow (ver airflow/docker-compose.yml):
# ahí se montan el .env y el token de Gmail generados en el repo.
RAIZ_NUMERALIA = Path('/opt/numeralia')
TOKEN_GMAIL = RAIZ_NUMERALIA / 'token_gmail.json'


def _acumulado_listo(**_context) -> bool:
    from numeralia.config import Config, cargar_dotenv
    from numeralia.notificaciones.reporte_diario import datos_listos_para_enviar

    cargar_dotenv(RAIZ_NUMERALIA)
    config = Config.desde_env()
    return datos_listos_para_enviar(config)


def _enviar_reporte(**_context) -> None:
    from numeralia.config import Config, cargar_dotenv
    from numeralia.notificaciones.reporte_diario import enviar_reporte_diario

    cargar_dotenv(RAIZ_NUMERALIA)
    config = Config.desde_env()
    ruta = enviar_reporte_diario(config, TOKEN_GMAIL)
    print(f"Reporte enviado. Copia en: {ruta}")


with DAG(
    dag_id='reporte_diario_calidad_aire',
    description=('Espera a que termine la actualización de la mañana y '
                 'manda el reporte diario por correo.'),
    # None = no se dispara solo; queda disponible para correrlo a mano
    # desde la interfaz mientras tanto. Antes: '0 6 * * *' (hora en que
    # empezaba a REVISAR si ya estaba lista la data, no la hora de envío).
    schedule=None,
    start_date=datetime(2026, 9, 1),
    catchup=False,
    max_active_runs=1,
    default_args={'owner': 'semadet', 'retries': 0},
    tags=['semadet', 'calidad-aire'],
) as dag:

    esperar_actualizacion = PythonSensor(
        task_id='esperar_actualizacion_acumulado',
        python_callable=_acumulado_listo,
        poke_interval=timedelta(minutes=5),
        timeout=timedelta(hours=6),
        mode='reschedule',  # libera el worker entre revisadas; no es un poke apretado
    )

    enviar_reporte = PythonOperator(
        task_id='enviar_reporte_diario',
        python_callable=_enviar_reporte,
    )

    esperar_actualizacion >> enviar_reporte
