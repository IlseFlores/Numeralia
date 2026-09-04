# Pipeline Calidad del Aire — SEMADET

Pipeline completo (Cruda → Procesada → Analítica) + Episodios + IMECA Máximo +
Alertas + Dashboard (Dash), todo en una sola corrida. Lee y escribe en Google
Sheets y levanta un dashboard web local con el mapa comparativo de estaciones.

Este archivo cubre la instalación y ejecución **como script `.py`** (fuera de
Colab). Si vas a usarlo en Google Colab, las instrucciones están en el
encabezado de [`main.py`](main.py).

> **¿Vas a seguir el refactor?** Empieza por
> **[HOJA_DE_RUTA.md](HOJA_DE_RUTA.md)**: qué falta, en qué orden, cómo
> verificar cada paso y con qué trampas ya nos topamos.

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
python -m numeralia          # usa el año actual
python -m numeralia 2025     # fuerza un año específico
```

Opciones:

```bash
python -m numeralia --help
python -m numeralia 2025 --sin-dashboard          # solo datos, sin abrir el dashboard
python -m numeralia --puerto 8060                 # otro puerto
python -m numeralia --exportar-json datos.json    # vuelca los datos del dashboard
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

`python main.py` sigue funcionando y acepta los mismos
argumentos: delega en el mismo punto de entrada.

**Nota de Windows**: ya no hace falta `PYTHONUTF8=1`. El punto de entrada
pone la salida en UTF-8 por su cuenta, que es lo que antes hacía falta para
que los emojis de los mensajes de avance no tumbaran la corrida con
`UnicodeEncodeError` en consolas cp1252.

También hay un comando `numeralia` que la instalación registra. En equipos
con Control de aplicaciones de Windows activo, ese ejecutable puede quedar
bloqueado por no estar firmado; en ese caso usa `python -m numeralia`, que
hace exactamente lo mismo.

Para correr solo el pipeline de datos desde una sesión de Python:

```python
from main import run_full_pipeline
acumulado = run_full_pipeline(lanzar_dashboard=False)
```

## Desplegar en el servidor con Docker

`Dockerfile` y `docker-compose.yml` construyen la imagen y mantienen el
proceso activo. El dashboard queda preparado para publicarse en
`/reporte-diario/` a través del Nginx de Aire Jalisco; su puerto no se publica
directamente en el servidor.

### Cada release se despliega sola

Al publicar un release en GitHub, el workflow `deploy` corre los tests,
construye la imagen, la sube al registry y la activa en el servidor por SSH.
Si el healthcheck no alcanza el estado healthy en 20 minutos, el workflow
revierte el servicio a la versión que estaba corriendo. Para entregar una
versión nueva no hay que volver a entrar al servidor.

Cómo se libera una versión:

1. En el repositorio, pestaña Releases → `Draft a new release`. El tag debe
   seguir el formato `v1.2.3`; el workflow valida ese formato y rechaza
   cualquiera que no lo cumpla.
2. El release tiene que publicarse con `Publish release`: un borrador no
   dispara nada, tampoco editar uno ya publicado. El tag lo crea el propio
   GitHub al publicar (opción `Create a new tag`), o `gh release create` si
   se prefiere la línea de comandos. Ojo: hacer `git tag` y subirlo no
   basta; eso es un push común y corriente, el despliegue se activa solo
   con releases publicados.
3. El avance se sigue en la pestaña Actions, sobre el workflow `deploy`:
   primero validación, luego pruebas, luego la imagen y por último la
   activación en el servidor. El primer arranque tarda: la corrida inicial
   procesa las hojas de cálculo antes de abrir el tablero, por eso el portal
   puede tardar varios minutos en responder aunque el despliegue siga en
   verde.

La infraestructura del despliegue ya está configurada: el usuario de
despliegue en el servidor, su acceso al registry y los secretos y variables
en Actions. Liberar una versión no requiere modificar nada de eso.

Para volver a una versión anterior sin publicar nada: Actions → deploy →
`Run workflow`, indicando el tag de la release que se quiere regresar.

## Correr los tests

```bash
python -m pytest
```

En Windows, `PYTHONUTF8=1 python -m pytest`.

Los tests cubren la lógica normativa: cortes del IAS, NowCast, redondeo y
cumplimiento diario. Hay además dos suites de seguridad del refactor:

- `test_equivalencia.py` compara el paquete contra `main.py`.
- `test_golden.py` compara contra una salida capturada **antes** de empezar
  a mover código (`tests/datos/golden_prerefactor.pkl`). Ese archivo debe
  versionarse: es la referencia de que los números del reporte no cambiaron.

## Estructura de archivos

**El punto de entrada es `src/numeralia/cli.py`.** Es lo que corre
`python -m numeralia`; todo lo demás es biblioteca que él usa.

El proyecto está a medio migrar de un solo script a un paquete por capas, así
que la orquestación y el dashboard todavía viven en `main.py`, en
la raíz. El CLI le delega mientras dura la migración.

```
.
├── src/numeralia/
│   ├── cli.py             ← PUNTO DE ENTRADA. Argumentos, UTF-8, arranque.
│   ├── __main__.py           Hace posible `python -m numeralia`
│   ├── config.py             ÚNICO lugar que lee el entorno
│   ├── consola.py            Salida en UTF-8 (consolas cp1252 de Windows)
│   ├── cache.py              Caché con vencimiento para lecturas de Sheets
│   ├── dominio/              Cálculo puro — no importa gspread ni dash
│   │   ├── nom172.py           rangos del IAS y cumplimiento NOM
│   │   ├── ias.py              índice diario y contaminante dominante
│   │   ├── nowcast.py          NowCast y redondeo comercial
│   │   └── suficiencia.py      criterios de datos suficientes
│   └── reporte/
│       ├── tema.py           Paleta, plantilla Plotly, medidas
│       └── pdf.py            Bitácoras en PDF (fpdf2)
│
├── main.py                ← Resto sin migrar: orquestación, validador,
│                            lectura de Sheets y dashboard. Se encoge
│                            conforme avanzan los pasos de abajo.
│
├── HOJA_DE_RUTA.md           Qué falta migrar, en qué orden y cómo
├── pyproject.toml            Paquete, dependencias y comando `numeralia`
├── requirements.txt          Dependencias sueltas (despliegue)
├── .env.example              Plantilla de configuración
├── .env                      Tus credenciales reales (NO se comparte)
├── logos/                    Logos del encabezado (opcional)
├── tests/
└── venv/
```

Dos reglas sostienen la estructura:

1. **`dominio/` no importa `gspread` ni `dash`.** Si cambia la norma, se toca
   un módulo; si cambia Google o el dashboard, no se toca nada del cálculo.
2. **Las dependencias van del CLI hacia adentro.** La única excepción es el
   puente temporal `cli.py → main.py`, que desaparece cuando la
   orquestación se mude al paquete.

### Qué falta migrar

Los pasos concretos, con sus trampas, están en
**[HOJA_DE_RUTA.md](HOJA_DE_RUTA.md)** — léelo antes de tocar código. Aquí va
solo el resumen:

1. `reporte/` — el PDF ya salió (`pdf.py`); falta partir `build_dash_app`
   (740 líneas) en layout, componentes y callbacks.
2. `ingesta/` — `autenticar`, `ValidadorCalidadAire`, lectura de Sheets.
3. `transformacion/` — tabla diaria, numeralia, episodios, alertas.
4. Mover `run_full_pipeline` al paquete y quitar el puente de `cli.py`.
5. Eliminar los años escritos a mano: quedan **199 literales** `2025`/`2026`
   en la capa de reporte que deben salir de `Config.anio` y
   `Config.anio_previo`.
6. Implementar el cumplimiento **anual** de la NOM-172. Los límites están
   capturados en `NOM_PRESETS["…"]["LIMITES_ANUALES"]` pero ningún cálculo
   los usa: hoy solo se evalúa el cumplimiento diario.

## La hoja `Acumuladas` (no la borres)

`Analitica` guarda una suma acumulada, así que sumarle el mismo día dos veces
inflaría las cifras. Para que volver a correr el pipeline sea inofensivo, cada
fecha ya sumada queda registrada en una pestaña llamada **`Acumuladas`** de la
hoja destino.

El pipeline la crea solo la primera vez y avisa por consola. Si la borras, la
siguiente corrida la volverá a crear vacía y **sumará de nuevo todos los días**,
porque asume que no hay nada acumulado.

## Refresco del dashboard

Dos fichas se releen solas desde Google Sheets mientras el dashboard está
abierto. Los intervalos son configurables porque afectan directamente la cuota
de la API de Sheets:

| Variable | Por omisión | Qué refresca |
|---|---|---|
| `NUMERALIA_REFRESCO_EVENTOS` | 300 s (5 min) | Ficha de episodios activos |
| `NUMERALIA_REFRESCO_MENSUAL` | 1800 s (30 min) | Serie mensual acumulada |

Iban en 20 segundos, que son 6 lecturas por minuto **por pestaña abierta** y
producían errores `429 Quota exceeded`. Además, las lecturas pasan por una
caché compartida (`numeralia/cache.py`): varias pestañas abiertas a la vez
consumen una sola lectura, no una cada una.

## Problemas comunes

- **Error 403 al correr el pipeline**: la cuenta de servicio no tiene acceso
  a alguna de las 4 hojas. Revisa el paso 4.
- **Falla al firmar / autenticar**: revisa que `GOOGLE_PRIVATE_KEY` en el
  `.env` conserve los `\n` literales y esté entre comillas, en una sola
  línea.
- **El mapa del dashboard no muestra las estaciones**: verifica que la hoja
  `Analitica` tenga las columnas `Latitud` y `Longitud` con valores
  numéricos por estación.
- **`429 Quota exceeded` en la consola**: demasiadas lecturas a Sheets en poco
  tiempo. Suele pasar al reiniciar el dashboard varias veces seguidas. Se pasa
  solo; si es constante, sube `NUMERALIA_REFRESCO_EVENTOS` y
  `NUMERALIA_REFRESCO_MENSUAL`.
- **Las cifras de `Analitica` se ven infladas**: probablemente se corrió el
  pipeline varias veces con una versión anterior a la hoja de control
  `Acumuladas`. Restaura la hoja desde el historial de versiones de Google
  Sheets.
- **El mapa no aparece en el PDF**: instala `kaleido`
  (`pip install kaleido`). Sin él, el resto del PDF se genera igual, solo
  sin la foto del mapa.
