# Pipeline Calidad del Aire — SEMADET

Pipeline completo (Cruda → Procesada → Analítica) + Episodios + IMECA Máximo +
Alertas + Dashboard (Dash), todo en una sola corrida. Lee y escribe en Google
Sheets y levanta un dashboard web local con el mapa comparativo de estaciones.

Este archivo cubre la instalación y ejecución **como script `.py`** (fuera de
Colab). Si vas a usarlo en Google Colab, las instrucciones están en el
encabezado de [`pipeline_completo.py`](pipeline_completo.py).

## Requisitos

- Python 3.9 o superior (probado con 3.13).
- Una cuenta de servicio de Google con acceso a Sheets API y Drive API.
- Acceso de red a Google Sheets y a los tiles de mapa de CARTO (para el mapa
  del dashboard).

## 1. Instalar dependencias

Desde esta carpeta, crea un entorno virtual e instala los paquetes:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

En Windows, activa el entorno con `venv\Scripts\activate` en vez del
`source venv/bin/activate`.

`pip install -e ".[dev]"` instala las dependencias **y** el paquete
`numeralia` en modo editable, que es lo que permite hacer
`from numeralia.dominio import ias` desde cualquier carpeta. El
`requirements.txt` se conserva para despliegues que solo necesiten las
dependencias.

## 2. Crear la cuenta de servicio de Google (una sola vez)

1. Entra a [Google Cloud Console](https://console.cloud.google.com/) y crea
   un proyecto (o usa uno existente).
2. Activa **Google Sheets API** y **Google Drive API** para ese proyecto.
3. Ve a **IAM y administración → Cuentas de servicio → Crear cuenta de
   servicio**.
4. En la cuenta creada, entra a la pestaña **Claves → Agregar clave → JSON**
   y descarga el archivo.

## 3. Configurar las credenciales (`.env`)

1. Copia la plantilla:

   ```bash
   cp .env.example .env
   ```

2. Abre el JSON descargado en el paso anterior y copia cada campo a su
   variable correspondiente en `.env` (`GOOGLE_PROJECT_ID`,
   `GOOGLE_PRIVATE_KEY`, `GOOGLE_CLIENT_EMAIL`, etc.).

   **Ojo con `GOOGLE_PRIVATE_KEY`**: va entre comillas, en una sola línea,
   conservando los `\n` literales tal como aparecen en el JSON — el código
   los convierte a saltos de línea reales al leerlos. No los edites a mano.

3. Borra el archivo `.json` descargado una vez que copiaste sus valores al
   `.env`: sus datos ya viven ahí, protegidos por `.gitignore`.

4. Completa las 4 URLs de hojas de cálculo al final del `.env`:
   `URL_DESTINO`, `URL_FUENTE_2025`, `URL_FUENTE_2026`, `URL_RESUMEN_MENSUAL`.

Alternativas (si no quieres usar `.env`):
- Poner todo el JSON en una sola variable `GOOGLE_CREDENCIALES_JSON`.
- Renombrar el JSON descargado a `credenciales.json` y dejarlo junto al
  script (el código lo busca automáticamente si no encuentra nada en el
  entorno).

## 4. Dar acceso a las hojas de cálculo

Esto es lo que más se olvida y causa un error 403:

1. Abre tu credencial (`.env` o `credenciales.json`) y copia el valor de
   `client_email` (algo como `robot@proyecto.iam.gserviceaccount.com`).
2. Comparte ese correo con permiso:
   - **Hoja destino** → Editor (ahí escribe el pipeline).
   - **Fuente 2025** → Lector.
   - **Fuente 2026** → Lector.
   - **Resumen MENSUAL** → Lector.

## 5. Logos del encabezado (opcional)

Crea una carpeta `logos/` junto al script con estos dos archivos dentro:

```
logos/logo simaj (1).png
logos/SemadetGobJal_transp (1).png
```

Si faltan, el dashboard se levanta igual, solo sin esos logos (la consola
avisa la ruta exacta donde los buscó).

## 6. Ejecutar

Con el entorno virtual activado:

```bash
python pipeline_completo.py          # usa el año actual
python pipeline_completo.py 2026     # fuerza un año específico
```

Esto valida la hoja Cruda, calcula IAS/NOM, escribe Procesada, acumula en
Analítica, recalcula Episodios + IMECA Máximo + Alertas, y levanta el
dashboard con los datos ya frescos en:

```
http://127.0.0.1:8050
```

Corre desatendido (sin preguntar nada por consola) — el año se toma del
sistema o del argumento, así que también puede lanzarse desde una tarea
programada.

**En Windows**, la consola usa `cp1252` y el script imprime emojis en los
mensajes de avance, así que arranca con `UnicodeEncodeError` si no fuerzas
UTF-8:

```bash
PYTHONUTF8=1 python pipeline_completo.py
```

En PowerShell es `$env:PYTHONUTF8 = "1"` antes de lanzarlo. En una tarea
programada, defínelo como variable de entorno del sistema.

Para correr solo el pipeline de datos sin abrir el dashboard, desde una
sesión de Python:

```python
from pipeline_completo import run_full_pipeline
acumulado = run_full_pipeline(lanzar_dashboard=False)
```

## Correr los tests

```bash
python -m pytest
```

En Windows, `PYTHONUTF8=1 python -m pytest`.

Los tests cubren la lógica normativa: cortes del IAS, NowCast, redondeo y
cumplimiento diario. Hay además dos suites de seguridad del refactor:

- `test_equivalencia.py` compara el paquete contra `pipeline_completo.py`.
- `test_golden.py` compara contra una salida capturada **antes** de empezar
  a mover código (`tests/datos/golden_prerefactor.pkl`). Ese archivo debe
  versionarse: es la referencia de que los números del reporte no cambiaron.

## Estructura de archivos

El proyecto está a medio migrar de un solo script a un paquete por capas.
`pipeline_completo.py` sigue siendo el punto de entrada, pero la lógica de
cálculo y la configuración ya viven en `src/numeralia/`.

```
.
├── pipeline_completo.py       # Punto de entrada (en migración)
├── pyproject.toml             # Paquete y dependencias
├── requirements.txt           # Dependencias sueltas (despliegue)
├── .env.example               # Plantilla de configuración
├── .env                       # Tus credenciales reales (NO se comparte)
├── logos/                     # Logos del encabezado (opcional)
├── src/numeralia/
│   ├── config.py              # ÚNICO lugar que lee el entorno
│   ├── dominio/               # Cálculo puro — no importa gspread ni dash
│   │   ├── nom172.py          #   rangos del IAS y cumplimiento NOM
│   │   ├── ias.py             #   índice diario y contaminante dominante
│   │   ├── nowcast.py         #   NowCast y redondeo comercial
│   │   └── suficiencia.py     #   criterios de datos suficientes
│   └── reporte/
│       └── tema.py            # Paleta, plantilla Plotly, estilos
├── tests/
└── venv/
```

La regla que sostiene la estructura: **`dominio/` no importa `gspread` ni
`dash`**. Si cambia la norma, se toca un módulo; si cambia Google o el
dashboard, no se toca nada del cálculo.

### Qué falta migrar

1. `reporte/` — sacar el PDF de dentro de `build_dash_app` (780 líneas) y
   partir layout, componentes y callbacks.
2. `ingesta/` — `autenticar`, `ValidadorCalidadAire`, lectura de Sheets.
3. `transformacion/` — tabla diaria, numeralia, episodios, alertas.
4. Eliminar los años escritos a mano: quedan literales `2025`/`2026` en la
   capa de reporte que deben salir de `Config.anio` y `Config.anio_previo`.

## Problemas comunes

- **Error 403 al correr el pipeline**: la cuenta de servicio no tiene acceso
  a alguna de las 4 hojas. Revisa el paso 4.
- **Falla al firmar / autenticar**: revisa que `GOOGLE_PRIVATE_KEY` en el
  `.env` conserve los `\n` literales y esté entre comillas, en una sola
  línea.
- **El mapa del dashboard no muestra las estaciones**: verifica que la hoja
  `Analitica` tenga las columnas `Latitud` y `Longitud` con valores
  numéricos por estación.
- **El mapa no aparece en el PDF**: instala `kaleido`
  (`pip install kaleido`). Sin él, el resto del PDF se genera igual, solo
  sin la foto del mapa.
