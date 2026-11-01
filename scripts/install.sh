#!/usr/bin/env bash
# =============================================================================
# LocalDeploy — Linux one-command installer
#
#   curl -fsSL <your-host>/install.sh | bash
#   # or: ./scripts/install.sh
#
# Installs Docker Engine (if missing), prepares the environment and starts the
# full LocalDeploy stack with Docker Compose.
# =============================================================================
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[localdeploy]${NC} $*"; }
warn()  { echo -e "${YELLOW}[localdeploy]${NC} $*"; }
fail()  { echo -e "${RED}[localdeploy]${NC} $*" >&2; exit 1; }

info "LocalDeploy installer"

# --- 1. Root check -----------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  warn "Not running as root. Docker installation may require sudo."
  SUDO="sudo"
else
  SUDO=""
fi

# --- 2. Ensure Docker Engine --------------------------------------------------
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  info "Docker Engine detected: $(docker --version)"
else
  info "Installing Docker Engine…"
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y
    $SUDO apt-get install -y ca-certificates curl gnupg
    $SUDO install -m 0755 -d /etc/apt/keyrings
    $SUDO curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    $SUDO chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null
    $SUDO apt-get update -y
    $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf -y install dnf-plugins-core
    $SUDO dnf-3 config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo 2>/dev/null || \
      $SUDO dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
    $SUDO dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    fail "Unsupported package manager. Install Docker Engine manually: https://docs.docker.com/engine/install/"
  fi
  $SUDO systemctl enable --now docker
  info "Docker installed: $(docker --version)"
fi

command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 || \
  fail "docker compose plugin missing. Install docker-compose-plugin."

# --- 3. Clone or use current directory ----------------------------------------
INSTALL_DIR="${LOCALDEPLOY_DIR:-$HOME/localdeploy}"
if [[ -f ./docker-compose.yml && -f apps/api/app/main.py ]]; then
  INSTALL_DIR="$PWD"
  info "Using current repository: $INSTALL_DIR"
elif [[ ! -d "$INSTALL_DIR/.git" ]]; then
  info "Cloning LocalDeploy into $INSTALL_DIR…"
  git clone "${LOCALDEPLOY_REPO:-https://github.com/your-org/localdeploy.git}" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# --- 4. Environment ------------------------------------------------------------
if [[ ! -f .env ]]; then
  info "Creating .env from .env.example"
  cp .env.example .env
  SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || openssl rand -hex 32)
  sed -i "s|^LOCALDEPLOY_SECRET_KEY=.*|LOCALDEPLOY_SECRET_KEY=$SECRET|" .env
  sed -i "s|^LOCALDEPLOY_ENVIRONMENT=.*|LOCALDEPLOY_ENVIRONMENT=production|" .env
  # Postgres password
  PG_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null || openssl rand -base64 24)
  sed -i "s|CHANGE_ME_STRONG_PASSWORD|$PG_PASSWORD|g" .env
  warn "Generated credentials into .env — review it now: POSTGRES password, admin user, ACME_EMAIL."
  echo "  Default dashboard login: admin / localdeploy123  (CHANGE IT AFTER FIRST LOGIN)"
fi

# --- 5. Start the stack --------------------------------------------------------
info "Building and starting LocalDeploy…"
$SUDO docker compose up -d --build

info "Waiting for the API to become healthy…"
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 || \
     $SUDO docker compose exec -T api curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo
info "──────────────────────────────────────────────────────"
info " LocalDeploy is running!"
info "   Dashboard : http://${LOCALDEPLOY_HOSTNAME:-localdeploy.local} (add to /etc/hosts or DNS)"
info "   API       : /api  (OpenAPI at /api/docs)"
info "   Config    : $INSTALL_DIR/.env"
info " Next steps:"
info "   1. Point ${LOCALDEPLOY_HOSTNAME:-localdeploy.local} (DNS) at this server"
info "   2. Set ACME_EMAIL in .env for Let's Encrypt and run: docker compose up -d"
info "   3. Log in and change the admin password"
info "──────────────────────────────────────────────────────"
