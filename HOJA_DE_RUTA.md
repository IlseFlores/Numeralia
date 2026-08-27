# Hoja de ruta — cómo seguir el refactor

Este documento es para quien continúe partiendo `main.py`, con o sin ayuda de
una IA. Está escrito para leerse **antes** de tocar código.

El proyecto está a medio migrar: de un solo script de 3,849 líneas a un
paquete por capas. Lo que sigue explica dónde va cada cosa, cómo verificar que
no rompiste nada, y con qué trampas ya nos topamos.

---

## 1. Dónde estamos

| | Líneas |
|---|---:|
| `main.py` | **3,490** |
| `src/numeralia/` (el paquete) | ~1,200 |
| `tests/` | 327 pruebas |

Lo que ya salió del script: configuración, el cálculo de la norma
(NOM-172 / IAS / NowCast), el tema visual y la generación de PDF.

Lo que falta, y a dónde va:

| Qué queda en `main.py` | Líneas | Destino |
|---|---:|---|
| Capa de reporte (dashboard) | ~1,900 | `numeralia/reporte/` |
| Transformación (cálculo aplicado) | ~740 | `numeralia/transformacion/` |
| Ingesta (Sheets, Excel, validador) | ~550 | `numeralia/ingesta/` |
| Orquestación (`run_full_pipeline`) | 59 | `numeralia/pipeline.py` |

Las piezas más grandes que siguen dentro:

```
  738 líneas   build_dash_app        (línea 2654)
  373 líneas   ValidadorCalidadAire  (línea  237)
  110 líneas   _fig_serie_buena_mensual
  104 líneas   ejecutar_pipeline_ias
  100 líneas   actualizar_acumulado
```

Y dentro de `build_dash_app`, el bulto real son **383 líneas de JavaScript**
escritas dentro de cadenas de Python: dos `clientside_callback` de 196 y 187
líneas.

---

## 2. Las tres reglas que no se rompen

**1. `dominio/` no importa `gspread` ni `dash`.**
Es lo que permite probar la norma sin credenciales de Google ni navegador. Si
una función necesita leer una hoja, no es dominio: es ingesta.

**2. Las dependencias van del CLI hacia adentro.**
`cli.py` → `main.py` → paquete. La única flecha que apunta al revés es el
puente temporal `cli.py → main.py`, y desaparece cuando `run_full_pipeline`
se mude al paquete.

**3. Los números del reporte no cambian.**
`tests/test_golden.py` compara contra una salida capturada **antes** de mover
la primera línea (`tests/datos/golden_prerefactor.pkl`). Ese archivo se
versiona y **no se regenera** salvo que se decida a propósito cambiar un
cálculo. Si un cambio lo rompe, el cambio está mal — no el archivo.

---

## 3. Cómo verificar (hazlo después de CADA paso)

```bash
python -m pytest          # los 327 tests, ~2 segundos
python -m numeralia --help
```

Los tests cubren los **datos**, no la interfaz. Todo lo que toque el dashboard
hay que verlo en el navegador:

```bash
python -m numeralia --sin-dashboard   # OJO: esto SÍ escribe en Google Sheets
```

Para mirar el dashboard sin reescribir las hojas, usa un script que solo lea:

```python
import main as p, pandas as pd
gc = p.autenticar()
sh = gc.open_by_url(p.URL_DESTINO)
acumulado = pd.DataFrame(sh.worksheet("Analitica").get_all_records())
app = p.build_dash_app(gc, sh, acumulado, datos=p._leer_datos_de_sheets(gc, sh, acumulado))
app.run(host="127.0.0.1", port=8050)
```

**No te fíes de la consola del navegador**: su búfer no se limpia al recargar
y muestra errores de cargas anteriores. Para saber qué callbacks tiene la app
de verdad, pregúntale al servidor:

```js
fetch('/_dash-dependencies').then(r => r.json()).then(console.log)
```

---

## 4. Los pasos, en orden

Cada paso es independiente y cabe en una sesión. Hazlos de uno en uno,
corriendo los tests entre cada uno.

### Paso 1 — Sacar el JavaScript de `build_dash_app`

**El de mayor rendimiento: 383 de 738 líneas.**

Son dos `clientside_callback` con JS dentro de cadenas de Python: el que
dibuja las gráficas de ECharts (línea ~2993) y el que arma el PDF del
dashboard con html2canvas + jsPDF (línea ~3203).

Van a `src/numeralia/reporte/assets/` como archivos `.js` de verdad, o a un
`reporte/scripts.py` que solo tenga las cadenas. Lo primero es mejor: se
edita con resaltado de sintaxis y se puede revisar.

Ojo: el JS interpola colores de Python con `""" + COLOR_GRIS + """`. Al
sacarlo hay que pasar esos valores como datos (por un `dcc.Store`), no por
concatenación de cadenas.

Después de esto `build_dash_app` queda alrededor de 355 líneas.

### Paso 2 — Partir el layout en componentes

Las tarjetas ya están separadas dentro de la función:
`episodios_card` (33), `mapa_card` (49), y dos bloques más de 49 y 35.

Se mueven a `reporte/componentes/` como funciones que **reciben datos y
devuelven un componente de Dash**, sin leer nada.

Las funciones `_card_*`, `_kpi_*`, `_tabla_*` y `_fig_*` que hoy están sueltas
en `main.py` (~800 líneas) se van con ellas.

### Paso 3 — Los callbacks

Los que quedan van a `reporte/callbacks.py`, con el patrón que ya usa
`pdf.registrar_descargas`: una función `registrar_x(app, datos)` en vez de
decoradores sueltos dentro de una función gigante.

### Paso 4 — `ingesta/`

`autenticar`, `_worksheet_a_df`, `ValidadorCalidadAire` (373 líneas),
`load_and_prepare_db`, `exportar_numeralia_a_sheet`.

El validador es grande pero autocontenido: probablemente el corte más limpio
que queda.

### Paso 5 — `transformacion/`

`build_daily_table`, `rebuild_amg_from_daily`, `actualizar_acumulado`,
`ejecutar_pipeline_ias`, `run_episodios`, `run_alertas`, `_calcular_numeralia`.

### Paso 6 — Cerrar el círculo

Mover `run_full_pipeline` a `numeralia/pipeline.py`, borrar
`_cargar_pipeline` de `cli.py`, borrar `main.py` y borrar
`tests/test_equivalencia.py` (que existe solo para comparar contra él).

`tests/test_golden.py` **se queda**: no depende de `main.py`.

### Paso 7 — Los años escritos a mano

Quedan **~199 literales** `2025`/`2026` en la capa de reporte. Deben salir de
`Config.anio` y `Config.anio_previo`. Hazlo al final: es mecánico, pero toca
nombres de columna y textos, y conviene hacerlo cuando el código ya esté en
módulos chicos.

### Paso 8 — Cumplimiento anual de la NOM-172

No está implementado. Los límites están capturados en
`NOM_PRESETS[...]["LIMITES_ANUALES"]` pero ningún cálculo los usa. Requiere
además el criterio de suficiencia anual (`suf_min_yearly`: 274 o 275 días).
Es funcionalidad nueva, no refactor — decidan antes si la quieren.

---

## 5. Trampas de este código

Cosas con las que ya nos tropezamos. Vale la pena leerlas antes.

**Windows y los emojis.** La consola usa `cp1252` y el código imprime `✔`,
`⚠`, `🔐`. Sin UTF-8 forzado, el programa muere antes de hacer nada. Ya está
resuelto en `numeralia/consola.py`, pero si creas un script nuevo que importe
`main` por fuera del CLI, llama a `forzar_utf8()` primero.

**`None` se vuelve `NaN`.** En `compute_nom_daily_flags`, `None` significa
"día no evaluable" y es distinto de `"No"` (no cumple). Pero pandas lo guarda
como `NaN` al meterlo en la columna. Un filtro con `is None` falla en
silencio; usa `pd.isna()`.

**`get_string_width` codifica a latin-1 por dentro.** En el PDF, medir el
ancho de una columna con texto sin sanear tumbaba la descarga entera. Los
culpables típicos son la comilla curva `’` y el guion largo `—`, que es lo
que mete Word al copiar y pegar en las bitácoras. Ya está corregido en
`reporte/pdf.py`; si escribes código nuevo con fpdf2, sanea **antes** de
medir, no solo antes de dibujar.

**Quitar un import puede dejar un bloque vacío.** Si borras todos los nombres
de un `from x import (...)`, queda `from x import ()` y eso es un error de
sintaxis. Corre los tests después de cada limpieza.

**Los callbacks capturan variables de `build_dash_app`.** Por eso no se pueden
mover solos: hay que sacarlos como una función `registrar_x(app, datos)` que
reciba lo que necesitaban del cierre. Y si registras callbacks en un bucle,
usa una fábrica — si no, todos se quedan con la última vuelta (ver
`pdf.registrar_descargas`).

**La cuota de Google Sheets es real.** Reiniciar el dashboard varias veces
seguidas produce `429 Quota exceeded`. Se pasa solo. Las lecturas periódicas
ya pasan por `numeralia/cache.py`; no le quites la caché ni bajes los
intervalos de `NUMERALIA_REFRESCO_*` sin medir.

**La hoja `Acumuladas` no se borra.** `Analitica` guarda una suma acumulada;
`Acumuladas` registra qué días ya se sumaron para que volver a correr el
pipeline no los duplique. Si la borras, la siguiente corrida vuelve a sumar
todo.

**Buscar código muerto.** Antes de mover algo, comprueba si de verdad se usa:

```python
import ast, pathlib
arbol = ast.parse(pathlib.Path("main.py").read_text(encoding="utf-8"))
definidos = {n.name for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
usados = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
usados |= {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
print(definidos - usados)   # candidatos a huérfanos
```

Ojo: eso solo mira dentro de `main.py`. Revisa también `src/`, `tests/` y
`README.md` antes de borrar. Así casi se va `build_dash_app_desde_json`, que
parece muerta pero es el arranque sin credenciales de Google.

---

## 6. Si trabajas con una IA

Lo que funcionó en esta sesión:

- **Un paso por conversación.** "Saca el PDF de `build_dash_app`" da buen
  resultado; "termina el refactor" no.
- **Pídele que mida antes de mover.** Contar líneas y buscar referencias con
  el árbol sintáctico evita decisiones basadas en suposiciones.
- **Exige verificación, no promesas.** Que corra los tests y que abra el
  dashboard. "Debería funcionar" no es verificación.
- **Al mover código, que capture una salida de referencia antes** y la compare
  después. Así se hizo `test_golden.py`.
- **Que escriba tests de lo que mueve.** Sacar el PDF a su módulo destapó un
  bug de años justamente porque por fin se pudo probar.

Lo que **no** conviene pedirle:

- Renombrar el bulto en vez de partirlo (un `main2.py` con 3,000 líneas no
  mejora nada).
- Borrar código "que parece que no se usa" sin verificar fuera del archivo.
- Regenerar `golden_prerefactor.pkl` para que pasen los tests. Si ese archivo
  falla, el cálculo cambió y hay que entender por qué.

---

## 7. Pendientes que no son refactor

- **Revisar `Analitica`.** Se corrió el pipeline varias veces con la versión
  anterior a la hoja `Acumuladas`, así que puede tener días contados de más.
  Lo más limpio es restaurar desde el historial de versiones de Google Sheets.
- **La hoja `Cruda` trae datos de 2025** mientras el sistema reporta 2026. El
  pipeline avisa por consola en cada corrida.
- **No existe la carpeta `logos/`**, así que el encabezado va sin los dos
  logotipos. El dashboard funciona igual.
- **El PDF completo del dashboard no está verificado a fondo.** Las gráficas
  pasaron de 300 a 450 px de alto y eso pudo mover el acomodo. Vale la pena
  descargarlo y revisarlo.
