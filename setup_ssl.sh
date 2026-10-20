#!/bin/bash
# =============================================================================
# IncuBrix Long-Tail Distribution - Automated SSL & Nginx HTTPS Setup
# Configures Let's Encrypt SSL certificate and Nginx reverse proxy
# Usage: sudo ./setup_ssl.sh <YOUR_DOMAIN_NAME>
# Example: sudo ./setup_ssl.sh incubrix-longtail.eastasia.cloudapp.azure.com
# =============================================================================

set -euo pipefail

DOMAIN="${1:-}"

if [ -z "$DOMAIN" ]; then
    echo "================================================================="
    echo "Error: Domain name required."
    echo "Usage: sudo ./setup_ssl.sh <YOUR_DOMAIN_NAME>"
    echo "Example: sudo ./setup_ssl.sh incubrix-longtail.eastasia.cloudapp.azure.com"
    echo "================================================================="
    exit 1
fi

echo "================================================================="
echo "  Setting up HTTPS and SSL for: ${DOMAIN}"
echo "================================================================="

# 1. Install Nginx and Certbot
echo "[1/4] Installing Nginx and Certbot..."
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx

# 2. Configure initial HTTP Nginx reverse proxy
echo "[2/4] Setting up Nginx reverse proxy for port 80 -> port 8000..."
sudo tee /etc/nginx/sites-available/incubrix > /dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

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
sudo nginx -t
sudo systemctl restart nginx

# 3. Request Let's Encrypt SSL Certificate
echo "[3/4] Requesting free Let's Encrypt SSL Certificate..."
sudo certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "admin@${DOMAIN}" --redirect

# 4. Verify SSL Auto-Renewal
echo "[4/4] Verifying certificate renewal timer..."
sudo systemctl status certbot.timer --no-pager || true

echo ""
echo "================================================================="
echo "  SUCCESS! Your IncuBrix site is now SECURE with HTTPS!"
echo "================================================================="
echo "Secure URL: https://${DOMAIN}/dashboard"
echo "API Docs:   https://${DOMAIN}/docs"
echo "================================================================="
