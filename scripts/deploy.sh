#!/usr/bin/env bash
# Deploy the stack on an Ubuntu 24.04 EC2 host (docs/04_Deployment_Guide.md).
#
# Usage (from the repository root on the server):
#   bash scripts/deploy.sh install      # one time: Docker Engine + compose plugin, 2 GB swap
#   bash scripts/deploy.sh env          # one time: write .env (asks for the RDS endpoint, DB password, Gemini key)
#   bash scripts/deploy.sh up [--seed]  # build, start, migrate; --seed loads the demo data
#   bash scripts/deploy.sh update       # git pull, then up
#   bash scripts/deploy.sh reset-data   # drop all tables, migrate, seed again (fresh demo data)
#   bash scripts/deploy.sh status | logs [service] | down
#
# Secrets stay in .env (chmod 600, never committed). Nothing secret is printed.

set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f docker-compose.prod.yml)
REQUIRED=(DATABASE_URL JWT_SECRET GEMINI_API_KEY)

log() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

install_docker() {
  [ -r /etc/os-release ] && . /etc/os-release
  [ "${ID:-}" = "ubuntu" ] || die "install supports Ubuntu only (found ${ID:-unknown})"

  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    log "Docker is already installed: $(docker --version)"
  else
    log "Installing Docker Engine from Docker's apt repository"
    sudo apt-get update -y
    sudo apt-get install -y ca-certificates curl git
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
      | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable --now docker
  fi
  sudo usermod -aG docker "$USER"

  # A 2 GB instance can run out of memory while building the web bundle and five images.
  if ! swapon --show | grep -q /swapfile; then
    log "Adding a 2 GB swap file"
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
    sudo swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  fi

  log "Done. Log out and back in (or run: newgrp docker) so docker works without sudo."
}

write_env() {
  if [ -f .env ]; then
    read -r -p ".env already exists. Overwrite it? [y/N] " answer
    [ "${answer:-}" = "y" ] || die "kept the existing .env"
  fi
  read -r -p "RDS endpoint (e.g. tuition-db.xxxx.eu-central-1.rds.amazonaws.com): " db_host
  read -r -p "RDS master username [tuition]: " db_user
  read -r -p "RDS database name [tuition]: " db_name
  read -r -s -p "RDS master password (hidden): " db_pass; echo
  read -r -s -p "Gemini API key (hidden): " gemini_key; echo
  read -r -p "Public domain for HTTPS, e.g. tuition.example.dev (empty = serve by IP over HTTP): " public_domain
  db_user="${db_user:-tuition}"
  db_name="${db_name:-tuition}"
  [ -n "$db_host" ] && [ -n "$db_pass" ] && [ -n "$gemini_key" ] || die "endpoint, password and Gemini key are required"

  # Percent-encode the password so characters like '#' or '%' cannot break the URL.
  db_pass_enc="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$db_pass")"
  # Kong's entrypoint accepts only URL-safe base64 characters in the secret.
  jwt_secret="$(openssl rand -base64 48 | tr '+/' '-_' | tr -d '=\n')"

  umask 077
  cat > .env <<EOF
# Written by scripts/deploy.sh env. Never commit this file.
DATABASE_URL=postgresql+psycopg://${db_user}:${db_pass_enc}@${db_host}:5432/${db_name}?sslmode=require
JWT_SECRET=${jwt_secret}
JWT_EXPIRES_MIN=60
GEMINI_API_KEY=${gemini_key}
GEMINI_MODEL=gemini-flash-latest
GEMINI_FALLBACK_MODEL=gemini-flash-lite-latest,gemini-2.5-flash-lite
PUBLIC_DOMAIN=${public_domain}
EOF
  chmod 600 .env
  log "Wrote .env (mode 600). Next: bash scripts/deploy.sh up --seed"
}

check_env() {
  [ -f .env ] || die ".env is missing. Run: bash scripts/deploy.sh env"
  local name value
  for name in "${REQUIRED[@]}"; do
    value="$(grep -E "^${name}=" .env | tail -1 | cut -d= -f2- || true)"
    [ -n "$value" ] || die "$name is empty in .env"
    case "$value" in *change-me*) die "$name still has the placeholder value" ;; esac
  done
  grep -E '^DATABASE_URL=' .env | grep -q '@postgres:' && die "DATABASE_URL points at the local postgres service; use the RDS endpoint"
  return 0
}

migrate() {
  log "Applying database migrations"
  "${COMPOSE[@]}" run --rm --no-deps tuition-api alembic upgrade head
}

seed() {
  log "Loading demo data (existing rows are kept)"
  "${COMPOSE[@]}" run --rm --no-deps tuition-api python -m seed.seed
}

wait_healthy() {
  log "Waiting for the gateway"
  local i
  for i in $(seq 1 60); do
    if curl -fsS --max-time 3 http://localhost/api/v1/health >/dev/null 2>&1; then
      "${COMPOSE[@]}" ps
      local ip domain
      ip="$(curl -fsS --max-time 2 https://checkip.amazonaws.com 2>/dev/null || echo '<elastic-ip>')"
      domain="$(grep -E '^PUBLIC_DOMAIN=' .env | tail -1 | cut -d= -f2- || true)"
      [ -n "$domain" ] && log "Up: https://${domain}/  (smoke test: bash scripts/smoke.sh https://${domain})"
      log "Up: http://${ip}/  (by IP, plain HTTP)"
      return 0
    fi
    sleep 5
  done
  "${COMPOSE[@]}" ps
  die "the gateway did not answer within 5 minutes; check: bash scripts/deploy.sh logs"
}

up() {
  check_env
  log "Building images (the first build takes a few minutes)"
  "${COMPOSE[@]}" build
  migrate
  if [ "${1:-}" = "--seed" ]; then seed; fi
  log "Starting the stack"
  "${COMPOSE[@]}" up -d --remove-orphans
  wait_healthy
}

reset_data() {
  check_env
  read -r -p "This deletes every student, tuition and payment row in RDS. Type 'reset' to continue: " answer
  [ "${answer:-}" = "reset" ] || die "cancelled"
  "${COMPOSE[@]}" run --rm --no-deps tuition-api alembic downgrade base
  migrate
  seed
  log "Demo data restored"
}

case "${1:-}" in
  install)    install_docker ;;
  env)        write_env ;;
  up)         up "${2:-}" ;;
  update)     git pull --ff-only && up "${2:-}" ;;
  reset-data) reset_data ;;
  status)     "${COMPOSE[@]}" ps ;;
  logs)       "${COMPOSE[@]}" logs --tail 200 -f ${2:+"$2"} ;;
  down)       "${COMPOSE[@]}" down ;;
  *)          sed -n '2,12p' "$0"; exit 1 ;;
esac
