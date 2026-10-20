#!/bin/bash
# =============================================================================
# IncuBrix Long-Tail Distribution — Azure VM Deployment Script
# Target: Ubuntu 22.04 LTS, B2s (2 vCPU, 4 GB RAM)
# Run as: chmod +x deploy_azure.sh && ./deploy_azure.sh
# =============================================================================

set -euo pipefail

echo "================================================================="
echo "  IncuBrix Long-Tail Distribution — Azure Deployment"
echo "================================================================="

# 1. Set up 2 GB swapfile to ensure memory stability on 4 GB VM
if [ ! -f /swapfile ]; then
    echo "[INFO] Creating 2 GB swapfile for memory stability..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
    echo "[INFO] Swapfile configured."
else
    echo "[INFO] Swapfile already exists."
fi

# 2. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "[INFO] Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker "$USER"
    rm -f get-docker.sh
    echo "[INFO] Docker installed."
fi

DOCKER_CMD="docker"
if ! docker ps >/dev/null 2>&1; then
    DOCKER_CMD="sudo docker"
fi

# 3. Install Docker Compose plugin if not present
if ! $DOCKER_CMD compose version &> /dev/null; then
    echo "[INFO] Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# 4. Prepare directories
mkdir -p outputs/mrss
mkdir -p tests/batch_results

# 5. Set up environment file and generate cryptographic secrets
if [ ! -f .env ]; then
    echo "[INFO] Copying .env.example to .env..."
    cp .env.example .env
fi

generate_secret() {
    if command -v openssl &>/dev/null; then
        openssl rand -hex 24
    else
        python3 -c "import secrets; print(secrets.token_hex(24))"
    fi
}

echo "[INFO] Checking and generating required production secrets..."
replace_secret() {
    local key="$1"
    local current_val
    current_val=$(grep "^${key}=" .env | cut -d'=' -f2- || true)
    if [ -z "$current_val" ] || [ "$current_val" = "CHANGE_ME" ]; then
        local new_val
        new_val=$(generate_secret)
        sed -i "s|^${key}=.*|${key}=${new_val}|" .env
        echo "[INFO] Generated random secret for ${key}"
    fi
}

replace_secret "POSTGRES_PASSWORD"
replace_secret "MINIO_ROOT_PASSWORD"
replace_secret "MINIO_SECRET_KEY"
replace_secret "ACCESS_TOKEN"
replace_secret "CALLBACK_SECRET"
replace_secret "LEMMY_PASSWORD"
replace_secret "HMAC_WEBHOOK_SECRET"

# Read generated ACCESS_TOKEN for display
TOKEN=$(grep "^ACCESS_TOKEN=" .env | cut -d'=' -f2- || echo "")

# 6. Bring up docker compose stack
echo "[INFO] Building and starting all services..."
$DOCKER_CMD compose down --remove-orphans 2>/dev/null || true
$DOCKER_CMD compose pull --ignore-pull-failures 2>/dev/null || true
$DOCKER_CMD compose up --build -d

# 7. Wait up to 5 minutes (300 seconds) for /ready endpoint
echo "[INFO] Waiting for service readiness (/ready check)..."
READY=0
for i in {1..60}; do
    if curl -sf http://localhost:8000/ready > /dev/null 2>&1; then
        echo "[INFO] Service /ready check passed! (attempt $i/60)"
        READY=1
        break
    fi
    echo "  Readiness check attempt $i/60... sleeping 5s"
    sleep 5
done

if [ "$READY" -ne 1 ]; then
    echo "[ERROR] Service failed to become ready within 5 minutes."
    $DOCKER_CMD compose ps
    $DOCKER_CMD compose logs --tail=50 api
    exit 1
fi

# 8. Run batch smoke tests
echo ""
echo "=== Running Batch Smoke Tests ==="
$DOCKER_CMD compose exec -T api python batch_runner.py \
    --input /app/tests/batch_inputs/ \
    --output /app/tests/batch_results/ \
    --base-url http://localhost:8000 \
    --timeout 15 \
    2>&1 | tail -25 || true

# 9. Configure 24/7 Persistence (systemd unit for automatic reboot recovery)
echo "[INFO] Configuring systemd persistence service for 24/7 uptime..."
CURRENT_DIR=$(pwd)
CURRENT_USER=$(whoami)

sudo tee /etc/systemd/system/incubrix.service > /dev/null <<EOF
[Unit]
Description=IncuBrix Long-Tail Distribution Stack
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${CURRENT_DIR}
User=${CURRENT_USER}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable incubrix.service
echo "[INFO] systemd incubrix.service enabled: stack will auto-restart on VM boot."

# 10. Optional Nginx Reverse Proxy for Port 80
if command -v nginx &>/dev/null || sudo apt-get install -y nginx 2>/dev/null; then
    echo "[INFO] Configuring Nginx reverse proxy on port 80..."
    sudo tee /etc/nginx/sites-available/incubrix > /dev/null <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo ln -sf /etc/nginx/sites-available/incubrix /etc/nginx/sites-enabled/
    sudo systemctl restart nginx 2>/dev/null || true
    echo "[INFO] Nginx configured on port 80."
fi

# 11. Print access details
VM_IP=$(curl -sf https://ipinfo.io/ip 2>/dev/null || echo "YOUR_VM_IP")

echo ""
echo "================================================================="
echo "  IncuBrix Long-Tail Distribution is LIVE (24/7 Persistence)"
echo "================================================================="
echo "Public Web URL (Port 80):   http://${VM_IP}/dashboard"
echo "Public Direct (Port 8000):  http://${VM_IP}:8000/dashboard"
echo "API Documentation:          http://${VM_IP}/docs"
echo "Readiness Endpoint:         http://${VM_IP}/ready"
echo "Liveness Endpoint:          http://${VM_IP}/health"
echo "Generated ACCESS_TOKEN:     ${TOKEN}"
echo ""
echo "Test command:"
echo "  curl -H 'X-Access-Token: ${TOKEN}' http://${VM_IP}/api/v1/destinations"
echo "================================================================="
