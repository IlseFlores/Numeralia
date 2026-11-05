# Instalación en el servidor Ubuntu

Cómo dejar Numeralia (el reporte diario) corriendo en el servidor Ubuntu
(22.04 o 24.04), junto al Validador de Calidad del Aire, el Padrón de
Ladrilleras y el formato de calibración.

> Esto es **aparte** del despliegue al droplet por releases
> (`.github/workflows/deploy.yml`, ver el README). Ese no cambia: aquí se usa
> `docker-compose.servidor.yml` encima del mismo `docker-compose.yml`.

Al terminar queda en:

- **Con dominio:** `https://<dominio>/reporte-diario/`
- **Sin dominio:** `http://<ip-del-servidor>:8083/reporte-diario/`

## Cómo queda armado

```
Internet ──HTTPS──> nginx del servidor ──/reporte-diario/──> 127.0.0.1:8083 ──> contenedor (Dash :8050)
                                                                                 └─ lee .env (Google + URL de hojas)
```

- Un contenedor con el pipeline y el tablero de Dash. **No usa MySQL**: lee y
  escribe en Google Sheets.
- La imagen se compila en el servidor desde el repositorio; no hace falta
  sesión en GHCR.
- El puerto se publica solo en `127.0.0.1`; nginx es la única entrada.
- Si nginx ya tiene un sitio para el dominio (el del Validador), se agrega ahí
  como carpeta y usa el mismo certificado.
- La carpeta es fija: `/reporte-diario/`.

| Puerto | Lo usa |
|---|---|
| 8080 | Tablero de aire |
| 8081 | Validador |
| 8082 | Padrón de Ladrilleras |
| **8083** | **Numeralia** |
| 8084 | Formato de calibración |

## Requisitos

- Un usuario con `sudo` en el servidor.
- Que el servidor pueda bajar el repositorio de GitHub sin pedir contraseña
  (para la actualización automática): una llave de despliegue o
  `git config --global credential.helper store` y un `git pull` hecho a mano.
- El `.env` con las credenciales de la cuenta de servicio de Google y las
  cuatro URL de hojas (README, pasos 2 y 3). Las hojas tienen que estar
  compartidas con el correo de la cuenta de servicio.
- Si se usa dominio: que ya apunte a la IP del servidor.

## Pasos

### 1. Clonar el repositorio

```bash
cd ~
git clone https://github.com/IlseFlores/Numeralia.git
cd Numeralia
```

### 2. Copiar el `.env`

El `.env` lleva la llave privada de Google, así que **no se versiona ni lo
genera el script**: se copia a mano desde una máquina donde ya funcione. Desde
tu computadora:

```bash
scp .env usuario@servidor:~/Numeralia/.env
```

Y en el servidor:

```bash
chmod 600 .env
```

Si no existe, el instalador crea uno desde `.env.example` y se detiene para
que lo llenes. También se detiene si todavía tiene valores de ejemplo.

### 3. Correr el instalador

Con dominio (lo normal):

```bash
bash scripts/servidor-ubuntu.sh --dominio inspeccionsemadet.jalisco.gob.mx --correo tu@correo.mx
```

Sin dominio, para probar por IP:

```bash
bash scripts/servidor-ubuntu.sh
```

Opciones:

| Opción | Para qué |
|---|---|
| `--dominio <nombre>` | Pone nginx delante con HTTPS (Let's Encrypt). |
| `--correo <correo>` | Correo para los avisos de Let's Encrypt. |
| `--puerto 8090` | Otro puerto si el 8083 está ocupado. |
| `--rama <rama>` | Rama que sigue la actualización automática (por omisión `main`). |
| `--sin-actualizacion` | No instala la actualización automática. |

El script se puede repetir. Lo que hace, en orden:

1. Instala Docker y el plugin compose (repositorio oficial de Docker).
2. Revisa `.env` y le agrega `COMPOSE_FILE` (para que `docker compose` use la
   superposición del servidor) y `NUMERALIA_PUBLICAR`.
3. Activa UFW con SSH, 80 y 443.
4. Compila la imagen, levanta el contenedor y espera a que quede sano.
   **La primera vez tarda varios minutos**: el pipeline procesa las hojas
   antes de abrir el tablero. El script espera hasta 15.
5. Con `--dominio`: configura nginx y saca el certificado si el sitio aún no
   tiene HTTPS.
6. Instala `numeralia-actualizar.timer`, que cada 3 minutos revisa GitHub.

### 4. Comprobar

Abre la dirección que imprime el script al final.

```bash
docker compose ps                    # debe decir (healthy)
docker compose logs -f numeralia     # bitácora del pipeline y del tablero
```

Como `.env` ya trae `COMPOSE_FILE`, estos comandos usan solos la
configuración del servidor; no hace falta escribir `-f`.

## Actualizaciones

Cada 3 minutos `scripts/actualizar.sh` revisa la rama en GitHub. Si hay
commits nuevos: los baja, recompila, levanta y espera a que quede sano (hasta
15 minutos). Si la versión nueva no levanta, **regresa sola a la anterior** y
no la reintenta hasta que llegue otro commit.

Mientras el pipeline corre después de una actualización, el tablero no
responde (son unos minutos).

```bash
journalctl -u numeralia-actualizar -f     # ver qué hizo
bash scripts/actualizar.sh                # forzar una revisión ahora
systemctl list-timers numeralia-actualizar.timer
```

No edites archivos del repositorio en el servidor: la actualización solo
avanza (`--ff-only`) y se detiene si encuentra cambios locales.

## Tareas comunes

**Cambiar algo del `.env`:**

```bash
nano .env
docker compose up -d      # recrea el contenedor con los valores nuevos
```

**Reiniciar / detener / reconstruir:**

```bash
docker compose restart numeralia
docker compose down
docker compose up -d --build
```

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| 502 Bad Gateway justo después de instalar o actualizar | El pipeline todavía está procesando. Espera y revisa `docker compose logs -f numeralia`. |
| El contenedor queda `unhealthy` | Casi siempre credenciales o permisos de las hojas. Revisa los logs; confirma que las hojas estén compartidas con `GOOGLE_CLIENT_EMAIL`. |
| `429 Quota exceeded` en los logs | Demasiadas lecturas a Sheets. Sube `NUMERALIA_REFRESCO_EVENTOS` / `NUMERALIA_REFRESCO_MENSUAL` en `.env`. |
| 404 fuera de `/reporte-diario/` | Es normal: Dash solo responde dentro de esa carpeta. |
| `docker compose` intenta bajar de GHCR | Falta `COMPOSE_FILE=docker-compose.yml:docker-compose.servidor.yml` en `.env`. Vuelve a correr el instalador. |

## Lo que no incluye

- El correo diario con Airflow (`airflow/`, `dags/`) no se instala aquí. Si se
  usa, `REPORTE_URL_DASHBOARD` en `.env` debe apuntar a
  `https://<dominio>/reporte-diario/`.

## Archivos de la instalación

| Archivo | Qué es |
|---|---|
| `docker-compose.servidor.yml` | Superposición: compila aquí, sin red externa, puerto en 127.0.0.1:8083. |
| `deploy/nginx/numeralia-ubicacion.conf` | La carpeta `/reporte-diario/` en nginx. |
| `deploy/nginx/numeralia.conf` | Sitio propio, solo si el dominio no tiene uno. |
| `scripts/servidor-ubuntu.sh` | Instalador. |
| `scripts/actualizar.sh` | Actualización automática con regreso a la versión anterior. |
