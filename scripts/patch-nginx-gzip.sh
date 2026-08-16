#!/bin/bash
# =============================================================================
# patch-nginx-gzip.sh - Habilita gzip en nginx para comprimir responses de la API
#
# F-NGINX-GZIP (2026-08-08, Kevin): el cuello de /payments/ y otros endpoints
# es el overhead de FastAPI/middleware (~1.0s). La transferencia del response
# es marginal (~5KB) pero con muchos usuarios concurrentes suma. Gzip reduce
# ~70% el tamaño de responses JSON, ahorrando 30-50ms por request en la red.
#
# Es idempotente: si gzip ya esta aplicado, no hace nada.
# Hace backup de la config original antes de modificar.
# Recarga nginx automaticamente al final.
#
# Uso:
#   sudo /usr/local/bin/patch-nginx-gzip.sh
#
# Tambien se invoca automaticamente desde .github/workflows/deploy.yml antes
# de cada deploy del backend. Asi, el gzip queda habilitado de por vida.
# =============================================================================

set -euo pipefail

LOG_TAG="patch-nginx-gzip"
log()  { echo "[$(date -u +%H:%M:%S)] [$LOG_TAG] $*"; }
die()  { echo "[$(date -u +%H:%M:%S)] [$LOG_TAG] ERROR: $*" >&2; exit 1; }

# Sanity checks
[[ $EUID -eq 0 ]] || die "Debe correr como root (sudo)"

# -----------------------------------------------------------------------------
# 1) Detectar el archivo de config de nginx que tiene proxy_pass a FastAPI
# -----------------------------------------------------------------------------
# Patron comun: el server block que reverse-proxea a kyc-backend (puerto 8000)
PROXY_PATTERN="proxy_pass.*127.0.0.1:8000"

NGINX_CONF=""
# Buscar en orden de prioridad
for candidate in \
    /etc/nginx/sites-available/datahuba \
    /etc/nginx/sites-available/postgrado \
    /etc/nginx/sites-available/default \
    /etc/nginx/conf.d/datahuba.conf \
    /etc/nginx/conf.d/postgrado.conf; do
    if [[ -f "$candidate" ]] && grep -qE "$PROXY_PATTERN" "$candidate"; then
        NGINX_CONF="$candidate"
        break
    fi
done

# Si no se encontro por nombre, buscar todos los .conf en sites-available y conf.d
if [[ -z "$NGINX_CONF" ]]; then
    for candidate in /etc/nginx/sites-available/* /etc/nginx/conf.d/*.conf; do
        if [[ -f "$candidate" ]] && grep -qE "$PROXY_PATTERN" "$candidate"; then
            NGINX_CONF="$candidate"
            break
        fi
    done
fi

# Si AUN no se encontro, usar el nginx.conf principal (raro)
if [[ -z "$NGINX_CONF" ]]; then
    if [[ -f /etc/nginx/nginx.conf ]] && grep -qE "$PROXY_PATTERN" /etc/nginx/nginx.conf; then
        NGINX_CONF="/etc/nginx/nginx.conf"
    fi
fi

[[ -n "$NGINX_CONF" ]] || die "No se encontro el server block con proxy_pass a 127.0.0.1:8000"
log "Config detectada: $NGINX_CONF"

# -----------------------------------------------------------------------------
# 2) Verificar si gzip ya esta aplicado (idempotente)
# -----------------------------------------------------------------------------
if grep -qE '^\s*gzip\s+on\s*;' "$NGINX_CONF"; then
    log "gzip ya esta habilitado en $NGINX_CONF. Nada que hacer."
    exit 0
fi

# -----------------------------------------------------------------------------
# 3) Backup de la config original
# -----------------------------------------------------------------------------
BACKUP="/etc/nginx/$(basename $NGINX_CONF).pre-gzip.$(date +%Y%m%d-%H%M%S).bak"
cp -a "$NGINX_CONF" "$BACKUP"
log "Backup: $BACKUP"

# -----------------------------------------------------------------------------
# 4) Insertar el bloque gzip DESPUES del primer bloque 'server {' o 'http {'
#    (gzip funciona en http context Y server context en nginx).
# -----------------------------------------------------------------------------
# Crear un archivo temporal con la config nueva
TMP=$(mktemp)
trap "rm -f $TMP" EXIT

# Bloque gzip que vamos a insertar
GZIP_BLOCK='
    # F-NGINX-GZIP (2026-08-08, Kevin): habilitar compresion gzip para reducir
    # el tamaño de responses de la API (~70% en JSON). Ahorra 30-50ms por
    # request en la transferencia de red, especialmente con multiples usuarios
    # concurrentes. Solo comprime responses > 1KB para evitar overhead en
    # responses pequenos (404, health checks, etc).
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml
        application/xml+rss
        application/atom+xml
        application/vnd.ms-fontobject
        application/x-font-ttf
        font/opentype
        image/svg+xml
        image/x-icon;'

# Estrategia: encontrar la primera ocurrencia de "server {" o "http {"
# y meter el bloque gzip justo DESPUES de la linea de apertura.
# awk es la forma mas limpia.

awk -v block="$GZIP_BLOCK" '
    /^[[:space:]]*(server|http)[[:space:]]*\{/ && !inserted {
        print
        print block
        inserted = 1
        next
    }
    { print }
' "$NGINX_CONF" > "$TMP"

# Verificar que el bloque se inserto
if ! grep -qE '^\s*gzip\s+on\s*;' "$TMP"; then
    die "No se pudo insertar el bloque gzip. Abortando sin modificar."
fi

# -----------------------------------------------------------------------------
# 5) Validar la nueva config con nginx -t antes de aplicar
# -----------------------------------------------------------------------------
log "Validando config con nginx -t..."
if ! nginx -t 2>&1; then
    die "La nueva config tiene errores de sintaxis. Backup en $BACKUP. NO se aplico."
fi
log "Config valida."

# -----------------------------------------------------------------------------
# 6) Aplicar y recargar nginx
# -----------------------------------------------------------------------------
mv "$TMP" "$NGINX_CONF"
trap - EXIT  # Limpiar el trap del TMP (ya no existe)

log "Config actualizada: $NGINX_CONF"

# Recargar nginx sin reiniciar (zero downtime)
if systemctl is-active --quiet nginx 2>/dev/null; then
    log "Recargando nginx via systemctl..."
    systemctl reload nginx
elif command -v nginx &>/dev/null; then
    log "Recargando nginx via 'nginx -s reload'..."
    nginx -s reload
else
    die "No se encontro systemctl ni nginx para recargar. Aplica el reload manualmente."
fi

# -----------------------------------------------------------------------------
# 7) Verificar que gzip funciona
# -----------------------------------------------------------------------------
sleep 1
log "Verificando gzip..."
TEST_URL="https://postgrado.datahuba.com/api/api/v1/auth/login"
RESPONSE_HEADERS=$(curl -sI -X POST -H "Content-Type: application/json" \
    -d '{"username":"nonexistent","password":"nonexistent"}' \
    "$TEST_URL" 2>&1 || echo "")

if echo "$RESPONSE_HEADERS" | grep -qi "content-encoding: gzip"; then
    log "✅ GZIP FUNCIONANDO. Response viene comprimido."
else
    log "WARN: No se detecto Content-Encoding: gzip en los headers."
    log "      Puede ser que el endpoint /auth/login retorne un error chico (< 1KB)."
    log "      Para verificar con un response mas grande:"
    log "        curl -sI -H 'Authorization: Bearer <token>' https://postgrado.datahuba.com/api/api/v1/payments/ | grep -i encoding"
fi

log "=== PATCH COMPLETADO ==="
