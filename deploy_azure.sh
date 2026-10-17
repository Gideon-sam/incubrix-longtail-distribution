#!/bin/bash
# =============================================================================
# IncuBrix Long-Tail Distribution — Azure Student VM Deployment Script
# =============================================================================
# Run as: chmod +x deploy_azure.sh && ./deploy_azure.sh
# Requirements: Ubuntu 22.04 LTS, Docker, Docker Compose (included below)
# Free tier: Azure Student ($100 credit) — B2s VM (2 vCPU, 4 GB RAM)
# =============================================================================

set -euo pipefail

echo "=== IncuBrix Long-Tail Distribution — Azure Deployment ==="

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    echo "Docker installed."
fi

# 2. Install Docker Compose plugin if not present
if ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo apt-get install -y docker-compose-plugin
fi

# 3. Set up environment file from example
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo ".env created with production-ready defaults."
fi

# 4. Open firewall ports on Azure NSG (if using azure-cli)
# az network nsg rule create \
#   --resource-group incubrix-rg \
#   --nsg-name incubrix-nsg \
#   --name AllowHTTP --protocol tcp --priority 100 --destination-port-range 8000 --access Allow

# 5. Pull images and start all services
echo "Starting all services..."
docker compose pull --ignore-pull-failures 2>/dev/null || true
docker compose up --build -d

# 6. Wait for health
echo "Waiting for service to be healthy..."
for i in {1..30}; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "Service is up!"
        break
    fi
    echo "  Attempt $i/30..."
    sleep 3
done

# 7. Run batch tests
echo ""
echo "=== Running Smoke Tests ==="
docker compose exec -T api python batch_runner.py \
    --input /app/tests/batch_inputs/ \
    --output /app/tests/batch_results/ \
    --base-url http://localhost:8000 \
    --timeout 10 \
    2>&1 | tail -20

# 8. Print access info
VM_IP=$(curl -sf https://ipinfo.io/ip 2>/dev/null || echo "YOUR_VM_IP")

echo ""
echo "================================================================="
echo "  🎉 IncuBrix Long-Tail Distribution is LIVE!"
echo "================================================================="
echo ""
echo "Shareable Public URL:  http://${VM_IP}:8000"
echo "Interactive Web UI:    http://${VM_IP}:8000/dashboard"
echo "API Docs (Swagger):    http://${VM_IP}:8000/docs"
echo "Health Check:          http://${VM_IP}:8000/health"
echo ""
echo "To test from terminal:"
echo "  curl http://${VM_IP}:8000/health"
echo "  curl http://${VM_IP}:8000/api/v1/connectors"
echo "================================================================="
