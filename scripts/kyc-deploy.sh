#!/bin/bash
# =============================================================================
# kyc-deploy.sh — Wrapper unificado para deploy del backend KYC.
#
# UBICACIÓN EN VPS: /usr/local/bin/kyc-deploy
# PERMISOS: 0755, root:root
#
# Usado por:
#   - GitHub Actions workflow (.github/workflows/deploy.yml)
#   - Deploys manuales SSH (cuando necesitas forzar un rebuild rápido)
#
# Características:
#   - Lock file con flock + timeout (15 min) → GitHub Actions no se cuelga
#     esperando un deploy manual infinito
#   - Marker file /tmp/deploy-in-progress con timestamp + PID + user
#     → cualquier admin puede ver "quien está desplegando ahora mismo"
#   - Log persistente en /tmp/deploy-backend.log (append) para auditoría
#   - trap para cleanup automático del marker (incluso en Ctrl+C o error)
#   - set -euo pipefail para fallar rápido en cualquier error
#   - Health check al final: espera 30s a que kyc-backend responda 200
#
# Uso:
#   sudo /usr/local/bin/kyc-deploy                # deploy normal
#   sudo /usr/local/bin/kyc-deploy --skip-build   # solo restart sin rebuild
#   sudo FLOCK_TIMEOUT=60 /usr/local/bin/kyc-deploy   # timeout custom
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
LOCK="/tmp/deploy-backend.lock"
MARKER="/tmp/deploy-in-progress"
LOG="/tmp/deploy-backend.log"
HEALTHCHECK_URL="http://127.0.0.1:8000/docs"
HEALTHCHECK_TIMEOUT=60   # segundos maximos de espera post-deploy
FLOCK_TIMEOUT="${FLOCK_TIMEOUT:-900}"   # 15 min default
BACKEND_DIR="/root/postgrado/backend"
COMPOSE_DIR="/root/postgrado"
SKIP_BUILD=0

# Parse args
for arg in "$@"; do
  case $arg in
    --skip-build) SKIP_BUILD=1 ;;
    --help|-h)
      echo "Uso: $0 [--skip-build]"
      echo "Variables de entorno:"
      echo "  FLOCK_TIMEOUT=segundos   (default 900 = 15 min)"
      exit 0
      ;;
    *) echo "Argumento desconocido: $arg"; exit 1 ;;
  esac
done

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
log()  { echo "[$(date -u +%H:%M:%S)] $*"; }
die()  { echo "[$(date -u +%H:%M:%S)] ERROR: $*" >&2; exit 1; }

# Pre-check: si hay un marker "fresco" (deploy en curso ahora mismo),
# fallar rápido con mensaje claro. No esperamos 15 min.
if [[ -f "$MARKER" ]]; then
  MARKER_AGE=$(( $(date +%s) - $(stat -c %Y "$MARKER") ))
  if (( MARKER_AGE < FLOCK_TIMEOUT )); then
    MARKER_INFO=$(cat "$MARKER" 2>/dev/null || echo "(ilegible)")
    die "Otro deploy esta en curso (marker creado hace ${MARKER_AGE}s):
$MARKER_INFO
Si crees que es un marker fantasma: sudo rm -f $MARKER"
  else
    log "Marker stale (${MARKER_AGE}s) — ignorando y continuando"
    rm -f "$MARKER"
  fi
fi

# -----------------------------------------------------------------------------
# Lock con flock
# -----------------------------------------------------------------------------
exec 200>"$LOCK"
if ! flock -w "$FLOCK_TIMEOUT" 200; then
  die "No se pudo obtener el lock en ${FLOCK_TIMEOUT}s. Hay otro deploy en curso.
Para forzar: sudo rm -f $LOCK (asegurarse primero de que no hay nada corriendo)"
fi

# -----------------------------------------------------------------------------
# Marker con trap para cleanup automático
# -----------------------------------------------------------------------------
{
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "user=$(whoami)"
  echo "pid=$$"
  echo "skip_build=$SKIP_BUILD"
  echo "flock_timeout=${FLOCK_TIMEOUT}"
} > "$MARKER"
trap 'rm -f "$MARKER"' EXIT
trap 'die "Deploy interrumpido (señal recibida)"' INT TERM

# Redirigir TODO el output al log (mantenemos también en stdout via tee)
exec > >(tee -a "$LOG") 2>&1

# -----------------------------------------------------------------------------
# Deploy propiamente
# -----------------------------------------------------------------------------
log "=== KYC BACKEND DEPLOY $(date -u) ==="
log "lock=$LOCK marker=$MARKER log=$LOG"
log "user=$(whoami) pid=$$ skip_build=$SKIP_BUILD"

cd "$BACKEND_DIR"
log "[1/6] git fetch + reset --hard origin/develop_kevin"
git fetch origin +refs/heads/develop_kevin:refs/remotes/origin/develop_kevin
SHA=$(git rev-parse origin/develop_kevin)
log "      remote SHA: $SHA"
git reset --hard origin/develop_kevin
git clean -fd
LOCAL_SHA=$(git rev-parse HEAD)
log "      local  SHA: $LOCAL_SHA"
if [[ "$LOCAL_SHA" != "$SHA" ]]; then
  die "SHA local ($LOCAL_SHA) != remote ($SHA) despues de reset"
fi

cd "$COMPOSE_DIR"
log "[2/6] detener contenedor kyc-backend"
docker update --restart=no kyc-backend 2>/dev/null || true
docker compose stop backend 2>/dev/null || true
docker kill kyc-backend 2>/dev/null || true
docker rm -f kyc-backend 2>/dev/null || true
sleep 1
if docker ps -a --format '{{.Names}}' | grep -q '^kyc-backend$'; then
  die "kyc-backend sigue vivo despues de kill+rm. Abortando."
fi

log "[3/6] borrar imagen vieja"
docker rmi -f $(docker images -q postgrado-backend) 2>/dev/null || true

if (( SKIP_BUILD )); then
  log "[4/6] SKIP_BUILD=1 — no rebuild"
else
  log "[4/6] docker compose build --no-cache --pull backend"
  docker compose build --no-cache --pull backend
fi

log "[5/6] reiniciar kyc-backend"
# F-ACTIONS-DEPLOY-FIX-3 (2026-07-30): hacer rm -f JUSTO ANTES del up.
# El build tarda ~30s, tiempo suficiente para que algo (otro deploy,
# un restart policy, etc) cree un container "kyc-backend" fantasma.
# Si intentamos up con un container del mismo nombre ya existente,
# docker compose falla con "Conflict. The container name is already
# in use". Hacer rm -f aqui garantiza que el slot esta libre.
# Usamos '|| true' para que un fallo en cleanup NO mate el script
# (set -e ya esta activo). El cleanup es best-effort; el verdadero
# validacion es el health check al final.
docker compose down backend 2>/dev/null || true
docker rm -f kyc-backend 2>/dev/null || true
sleep 1
# Verificar que el slot esta realmente libre antes de up
if docker ps -a --format '{{.Names}}' | grep -q '^kyc-backend$'; then
  log "WARN: todavia hay un container kyc-backend despues de cleanup, forzando rm"
  docker rm -f kyc-backend 2>/dev/null || true
  sleep 1
fi
docker compose up -d --no-deps --force-recreate backend
sleep 3
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}' | grep -E 'kyc-backend|postgrado-backend' || log "WARN: kyc-backend no encontrado en docker ps"

log "[6/6] health check (espera hasta ${HEALTHCHECK_TIMEOUT}s)"
HEALTH_OK=0
for i in $(seq 1 "$HEALTHCHECK_TIMEOUT"); do
  if curl -sf -o /dev/null --max-time 2 "$HEALTHCHECK_URL" 2>/dev/null; then
    HEALTH_OK=1
    log "      health check OK en ${i}s"
    break
  fi
  sleep 1
done
if (( !HEALTH_OK )); then
  log "WARN: health check NO respondio en ${HEALTHCHECK_TIMEOUT}s"
  log "      (el deploy puede haber sido exitoso pero el backend tarda en arrancar)"
  log "      Ultimos logs (best effort, no falla el script si container no existe):"
  # Usamos || true para que un container desaparecido NO mate el script.
  # El deploy puede haber sido exitoso aunque el container se cayo despues.
  docker logs kyc-backend --tail 20 2>&1 | sed 's/^/        /' || log "      (no se pudieron leer logs: container no existe o ya esta muerto)"
  log "      Verificacion final:"
  docker ps -a --format 'table {{.Names}}\t{{.Status}}' | grep kyc-backend || log "      (kyc-backend no aparece en docker ps -a)"
fi

docker image prune -f > /dev/null 2>&1 || true

log "=== DEPLOY COMPLETADO $(date -u) ==="
log "SHA deployed: $LOCAL_SHA"
log "Uptime:"
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep kyc-backend || true
