# Imagen de Airflow con las dependencias de numeralia y el Chromium de
# Playwright ya instalados, para correr el DAG del reporte diario.
#
# El contexto de build es la RAÍZ del repo (ver airflow/docker-compose.yml:
# `context: ..`), así que este Dockerfile ve requirements.txt, src/, etc.

FROM apache/airflow:2.10.5-python3.12

# El navegador queda en una ruta compartida: se instala como root (apt
# necesita permisos de root) pero lo usa el usuario 'airflow' en tiempo de
# corrida, y por default cada quien busca en su propio $HOME.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    && mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" \
    && chown -R airflow:0 "$PLAYWRIGHT_BROWSERS_PATH" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/numeralia
COPY --chown=airflow:root requirements.txt ./

USER airflow
# --constraint: Airflow fija versiones de varias librerías que también usa
# por dentro (requests, protobuf, attrs...). Sin esto, pip podría instalar
# una versión que choca con las que Airflow ya trae y el build truena a
# medias con un error de resolución de dependencias.
RUN pip install --no-cache-dir -r requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt"

# playwright install-deps también necesita apt, así que este paso sí corre
# como root; PLAYWRIGHT_BROWSERS_PATH ya apunta a la carpeta que se le dio a
# 'airflow' arriba, así que lo que se descargue aquí lo puede leer después.
USER root
RUN python -m playwright install --with-deps chromium
USER airflow

COPY --chown=airflow:root . .
RUN pip install --no-cache-dir --no-deps --no-build-isolation .
