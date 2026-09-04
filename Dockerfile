FROM python:3.13-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 numeralia \
    && mkdir -p /app \
    && chown numeralia:numeralia /app

WORKDIR /app

# Las dependencias cambian menos que el código y quedan en una capa reutilizable.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=numeralia:numeralia . .
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

FROM base AS test

RUN pip install --no-cache-dir "pytest>=8"
USER numeralia
CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime

USER numeralia
EXPOSE 8050
CMD ["python", "-m", "numeralia"]
