#!/bin/bash
# Run once on a fresh Ubuntu 22.04/24.04 VPS as root.
set -e

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq git nginx python3.12 python3.12-venv python3-pip \
  postgresql redis-server curl

echo "==> Installing Node.js 20"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

echo "==> Setting up PostgreSQL"
systemctl enable postgresql
systemctl start postgresql
# Create DB user and database (edit password as needed)
sudo -u postgres psql -c "CREATE USER trading WITH PASSWORD 'trading';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE trading OWNER trading;" 2>/dev/null || true

echo "==> Setting up Redis"
sed -i 's/^# maxmemory-policy.*/maxmemory-policy allkeys-lru/' /etc/redis/redis.conf
sed -i 's/^# maxmemory <bytes>/maxmemory 512mb/' /etc/redis/redis.conf
systemctl enable redis-server
systemctl restart redis-server

echo "==> Cloning repository"
mkdir -p /opt/stocksignal
# Replace with your actual GitHub repo URL
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git /opt/stocksignal
chown -R ubuntu:ubuntu /opt/stocksignal

echo "==> Python virtualenv"
cd /opt/stocksignal
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -q

echo "==> Copy .env (do this manually)"
echo "  scp .env ubuntu@YOUR_VPS_IP:/opt/stocksignal/.env"

echo "==> Frontend build"
cd /opt/stocksignal/frontend
npm ci
npm run build

echo "==> Configuring Nginx"
cp /opt/stocksignal/deploy/nginx.conf /etc/nginx/sites-available/stocksignal
ln -sf /etc/nginx/sites-available/stocksignal /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

echo "==> Installing systemd services"
cp /opt/stocksignal/deploy/stocksignal-backend.service /etc/systemd/system/
cp /opt/stocksignal/deploy/stocksignal-frontend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable stocksignal-backend stocksignal-frontend
systemctl start stocksignal-backend stocksignal-frontend

echo ""
echo "==> Setup complete. App running at http://$(curl -s ifconfig.me)"
echo ""
echo "Next: add GitHub deploy key and set these GitHub Secrets:"
echo "  VPS_HOST = $(curl -s ifconfig.me)"
echo "  VPS_USER = ubuntu"
echo "  VPS_SSH_KEY = (paste contents of ~/.ssh/id_rsa)"
