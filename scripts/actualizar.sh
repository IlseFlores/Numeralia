#!/usr/bin/env bash
# Numeralia: actualiza el servidor desde GitHub cuando hay cambios en la rama (main por
# omision; la fija RAMA en numeralia-actualizar.service).
#
# Lo corre cada 3 minutos numeralia-actualizar.timer, que instala
# scripts/servidor-ubuntu.sh. A mano tambien:  bash scripts/actualizar.sh
#
# Sin commits nuevos no hace nada. Con commits nuevos: git pull, compila,
# levanta y espera a que quede sano. Si falla, regresa al commit anterior y
# apunta el fallido en .git/numeralia-fallido para no reintentarlo cada 3 minutos.
#
# Bitacora: journalctl -u numeralia-actualizar

set -euo pipefail
trap 'echo "!! Fallo la linea $LINENO: $BASH_COMMAND" >&2' ERR

# Entre llaves: bash lee el bloque completo antes de ejecutarlo, asi el git pull
# puede cambiar este mismo archivo sin romper la corrida.
{

cd "$(dirname "$0")/.."
RAMA=${RAMA:-main}
FALLIDO=.git/numeralia-fallido

exec 9>/tmp/numeralia-actualizar.lock
flock -n 9 || exit 0

GIT_TERMINAL_PROMPT=0 git fetch -q origin "$RAMA"
ANTES=$(git rev-parse HEAD)
NUEVO=$(git rev-parse "origin/$RAMA")
[ "$ANTES" = "$NUEVO" ] && exit 0
if [ -f "$FALLIDO" ] && [ "$(cat "$FALLIDO")" = "$NUEVO" ]; then
  exit 0
fi

echo "Actualizando ${ANTES:0:7} -> ${NUEVO:0:7}:"
git log --oneline "$ANTES..$NUEVO"

if ! git merge --ff-only -q "origin/$RAMA"; then
  echo "La copia del servidor tiene cambios propios y no se puede actualizar sola." >&2
  echo "Revisa con: git status" >&2
  echo "$NUEVO" > "$FALLIDO"
  exit 1
fi

compilar() { docker compose build numeralia; }
levantar() { docker compose up -d --remove-orphans; }
sana() {
  local estado="" id
  for _ in $(seq 1 300); do
    id=$(docker compose ps -q numeralia 2>/dev/null || true)
    estado=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo ninguno)
    [ "$estado" = healthy ] && return 0
    sleep 3
  done
  echo "El tablero quedo en: $estado" >&2
  return 1
}

if compilar && levantar && sana; then
  rm -f "$FALLIDO"
  echo "Listo: ${NUEVO:0:7} en marcha."
  exit 0
fi

echo "La version ${NUEVO:0:7} no quedo sana; regreso a ${ANTES:0:7}." >&2
docker compose logs --tail 40 numeralia >&2 || true
echo "$NUEVO" > "$FALLIDO"
git reset -q --hard "$ANTES"
if compilar && levantar && sana; then
  echo "De vuelta en ${ANTES:0:7}." >&2
else
  echo "Tampoco levanto ${ANTES:0:7}: hay que revisarlo a mano." >&2
fi
exit 1
}
