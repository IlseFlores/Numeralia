#!/usr/bin/env bash
# Instala y arranca Numeralia (reporte diario) en el servidor Ubuntu (22.04 o 24.04),
# junto al Validador de Calidad del Aire y el Padrón de Ladrilleras.
#
#   bash scripts/servidor-ubuntu.sh --dominio inspeccionsemadet.jalisco.gob.mx --correo tu@correo.mx
#   bash scripts/servidor-ubuntu.sh                         # sin dominio: http://<servidor>:8083/reporte-diario/
#   bash scripts/servidor-ubuntu.sh --puerto 8090           # otro puerto si el 8083 está ocupado
#   bash scripts/servidor-ubuntu.sh --sin-actualizacion     # sin el paso 6
#
# Se corre con un usuario que tenga sudo, desde el repositorio ya clonado. Se
# puede repetir: cada paso revisa qué falta y no rehace lo que ya está.
#
# Esto NO reemplaza el despliegue del droplet por releases
# (.github/workflows/deploy.yml): usa docker-compose.servidor.yml encima del
# compose de siempre y compila la imagen aquí mismo.
#
# Qué hace:
#   1. Docker Engine y el plugin compose, del repositorio oficial de Docker.
#   2. .env: tiene que existir con las credenciales de Google y las URL de las
#      hojas (se copia a mano: lleva la llave privada). Le agrega COMPOSE_FILE
#      y NUMERALIA_PUBLICAR.
#   3. UFW: SSH y la web. Lo activa.
#   4. Compila la imagen y levanta el contenedor. El primer arranque procesa
#      las hojas antes de abrir el tablero: puede tardar varios minutos.
#   5. Con --dominio: nginx delante (en /reporte-diario/) y certificado.
#   6. Actualización automática: cada 3 minutos revisa la rama en GitHub y, si
#      hay cambios, los baja y recompila (scripts/actualizar.sh).

set -euo pipefail
trap 'echo "!! Falló la línea $LINENO: $BASH_COMMAND" >&2' ERR

DOMINIO=""
CORREO=""
PUERTO=8083
RAMA=main
ACTUALIZACION=si
while [ $# -gt 0 ]; do
  case "$1" in
    --dominio) DOMINIO="${2:?falta el dominio}"; shift 2 ;;
    --correo)  CORREO="${2:?falta el correo}"; shift 2 ;;
    --puerto)  PUERTO="${2:?falta el puerto}"; shift 2 ;;
    --rama)    RAMA="${2:?falta la rama}"; shift 2 ;;
    --sin-actualizacion) ACTUALIZACION=no; shift ;;
    -h|--help) sed -n '2,/^$/p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 1 ;;
  esac
done

cd "$(dirname "$0")/.."

paso() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
aviso() { printf '\033[33m!! %s\033[0m\n' "$*"; }

. /etc/os-release
if [ "${ID:-}" != "ubuntu" ]; then
  echo "Este script es para Ubuntu (encontré: ${PRETTY_NAME:-desconocido})." >&2
  exit 1
fi

# --- 1. Docker ----------------------------------------------------------------
paso "Docker"
if sudo docker compose version >/dev/null 2>&1; then
  echo "Ya instalado: $(sudo docker --version)"
else
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
fi
DUENO=$(stat -c %U .)
id -nG "$DUENO" | grep -qw docker || sudo usermod -aG docker "$DUENO"

# --- 2. .env ------------------------------------------------------------------
paso "Configuración (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  aviso "Creé .env desde .env.example. Llénalo con las credenciales de Google y las"
  aviso "URL de las hojas (README, paso 3) y vuelve a correr este script."
  exit 1
fi
if grep -q 'tu-proyecto-123456\|xxxxxxxxxxxxxxxxxxxx' .env; then
  aviso ".env todavía tiene valores de ejemplo (GOOGLE_* o URL_*). Llénalo y vuelve a correr."
  exit 1
fi

poner() {
  VALOR="$2" awk -v k="$1" 'BEGIN { v = ENVIRON["VALOR"] }
    index($0, k "=") == 1 { print k "=" v; hecho = 1; next }
    { print }
    END { if (!hecho) print k "=" v }' .env > .env.nuevo
  cat .env.nuevo > .env && rm .env.nuevo
}
valor() { sed -n "s|^$1=||p" .env | tail -n1; }

if [ -n "$DOMINIO" ]; then PUBLICAR="127.0.0.1:$PUERTO"; else PUBLICAR="$PUERTO"; fi
[ "$(valor COMPOSE_FILE)" = "docker-compose.yml:docker-compose.servidor.yml" ] \
  || poner COMPOSE_FILE docker-compose.yml:docker-compose.servidor.yml
grep -q '^NUMERALIA_PUBLICAR=' .env || poner NUMERALIA_PUBLICAR "$PUBLICAR"
if [ -n "$DOMINIO" ]; then
  case "$(valor NUMERALIA_PUBLICAR)" in
    127.0.0.1:*) ;;
    *) aviso "Con nginx delante conviene NUMERALIA_PUBLICAR=127.0.0.1:$PUERTO en .env; si no, el puerto queda abierto sin HTTPS." ;;
  esac
  PUERTO=$(valor NUMERALIA_PUBLICAR | sed -E 's|.*:||')
  # El correo del reporte descarga los PDF de esta dirección.
  [ "$(valor REPORTE_URL_DASHBOARD)" = "https://$DOMINIO/reporte-diario/" ] \
    || aviso "REPORTE_URL_DASHBOARD en .env no apunta a https://$DOMINIO/reporte-diario/ (solo importa si se usa el correo diario)."
fi
echo ".env listo."

# --- 3. Firewall --------------------------------------------------------------
paso "Firewall (UFW)"
command -v ufw >/dev/null 2>&1 || sudo apt-get install -y ufw
PUERTO_SSH=$(echo "${SSH_CONNECTION:-}" | awk '{print $4}')
if [ -z "$PUERTO_SSH" ]; then
  PUERTO_SSH=$( { sudo sshd -T 2>/dev/null || true; } | awk '$1=="port"{print $2; exit}')
fi
sudo ufw allow "${PUERTO_SSH:-22}/tcp" comment 'SSH'
if [ -n "$DOMINIO" ]; then
  sudo ufw allow 80/tcp comment 'HTTP (certbot y redirección)'
  sudo ufw allow 443/tcp comment 'HTTPS'
fi
sudo ufw --force enable
sudo ufw status

# --- 4. Contenedor ------------------------------------------------------------
paso "Contenedor"
sudo docker compose build numeralia
sudo docker compose up -d --remove-orphans

# El healthcheck da 10 minutos de gracia: la primera corrida procesa las hojas
# antes de abrir Dash. Se espera hasta 15.
printf 'Esperando a que el tablero quede sano (la primera vez tarda varios minutos)'
estado=ninguno
for _ in $(seq 1 300); do
  ID_APP=$(sudo docker compose ps -q numeralia 2>/dev/null || true)
  estado=$(sudo docker inspect -f '{{.State.Health.Status}}' "$ID_APP" 2>/dev/null || echo ninguno)
  [ "$estado" = healthy ] && break
  [ "$estado" = unhealthy ] && break
  printf '.'; sleep 3
done
echo
if [ "$estado" != healthy ]; then
  echo "El tablero no quedó sano ($estado). Últimas líneas:" >&2
  sudo docker compose logs --tail 40 numeralia >&2
  exit 1
fi
echo "Tablero sano."

# --- 5. nginx + HTTPS ---------------------------------------------------------
if [ -n "$DOMINIO" ]; then
  paso "nginx y certificado para $DOMINIO/reporte-diario/"
  sudo apt-get install -y nginx certbot python3-certbot-nginx

  sed -e "s|PUERTO|$PUERTO|g" deploy/nginx/numeralia-ubicacion.conf \
    | sudo tee /etc/nginx/snippets/numeralia.conf >/dev/null

  SITIO=""
  for f in /etc/nginx/sites-enabled/*; do
    [ -e "$f" ] || continue
    [ "$(readlink -f "$f")" = /etc/nginx/sites-available/numeralia ] && continue
    if sudo grep -qE "^[[:space:]]*server_name[^;]*[[:space:]]$DOMINIO([[:space:]]|;)" "$f"; then
      SITIO=$(readlink -f "$f"); break
    fi
  done

  if [ -n "$SITIO" ]; then
    echo "Agrego /reporte-diario/ al sitio existente $SITIO."
    sudo rm -f /etc/nginx/sites-enabled/numeralia
    if ! sudo grep -q 'include snippets/numeralia.conf;' "$SITIO"; then
      sudo cp "$SITIO" "$SITIO.antes-numeralia"
      sudo sed -i -E "/^[[:space:]]*server_name[^;]*[[:space:]]$DOMINIO([[:space:]]|;)/a\\    include snippets/numeralia.conf;   # Numeralia (reporte diario)" "$SITIO"
      echo "Respaldo en $SITIO.antes-numeralia."
    fi
  elif [ ! -f /etc/nginx/sites-available/numeralia ]; then
    sed "s|DOMINIO|$DOMINIO|" deploy/nginx/numeralia.conf \
      | sudo tee /etc/nginx/sites-available/numeralia >/dev/null
    sudo ln -sf /etc/nginx/sites-available/numeralia /etc/nginx/sites-enabled/numeralia
    sudo rm -f /etc/nginx/sites-enabled/default
    SITIO=/etc/nginx/sites-available/numeralia
  else
    SITIO=/etc/nginx/sites-available/numeralia
  fi
  sudo nginx -t
  sudo systemctl reload nginx

  if ! sudo grep -qE 'listen[^;]*443' "$SITIO"; then
    if [ -n "$CORREO" ]; then CUENTA=(-m "$CORREO"); else CUENTA=(--register-unsafely-without-email); fi
    sudo certbot --nginx -d "$DOMINIO" --redirect --agree-tos -n --keep-until-expiring "${CUENTA[@]}"
  fi
  URL="https://$DOMINIO/reporte-diario/"
else
  URL="http://$(hostname -I | awk '{print $1}'):$PUERTO/reporte-diario/"
fi

# --- 6. Actualización automática ---------------------------------------------
if [ "$ACTUALIZACION" = si ]; then
  paso "Actualización automática desde GitHub ($RAMA)"
  REPO=$(pwd)
  if sudo -H -u "$DUENO" env GIT_TERMINAL_PROMPT=0 git -C "$REPO" fetch -q origin "$RAMA"; then
    sudo tee /etc/systemd/system/numeralia-actualizar.service >/dev/null <<UNIDAD
[Unit]
Description=Numeralia: baja los cambios de $RAMA y recompila
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
User=$DUENO
WorkingDirectory=$REPO
Environment=GIT_TERMINAL_PROMPT=0
Environment=RAMA=$RAMA
ExecStart=/usr/bin/env bash $REPO/scripts/actualizar.sh
UNIDAD
    sudo tee /etc/systemd/system/numeralia-actualizar.timer >/dev/null <<UNIDAD
[Unit]
Description=Numeralia: revisa $RAMA cada 3 minutos

[Timer]
OnBootSec=2min
OnUnitActiveSec=3min
RandomizedDelaySec=30s

[Install]
WantedBy=timers.target
UNIDAD
    sudo systemctl daemon-reload
    sudo systemctl enable --now numeralia-actualizar.timer
    sudo systemctl restart numeralia-actualizar.timer
    echo "Activa: cada 3 minutos revisa $RAMA. Bitácora: journalctl -u numeralia-actualizar"
  else
    aviso "No pude bajar de GitHub sin contraseña, así que no activé la actualización automática."
    aviso "Guarda la credencial (git config --global credential.helper store y un git pull)"
    aviso "o agrega una llave de despliegue al repositorio, y vuelve a correr este script."
  fi
fi

paso "Listo"
echo "Abre $URL"
