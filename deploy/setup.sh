#!/usr/bin/env bash
# One-time VPS setup: Caddy (auto HTTPS) + systemd service + firewall.
# Run this yourself (it needs your sudo password once):
#   cd ~/dev/idea/shanai-faq-ai && bash deploy/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"

echo "== 1/5: Installing Caddy (if not already installed) =="
if ! command -v caddy >/dev/null 2>&1; then
  sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update
  sudo apt-get install -y caddy
else
  echo "  already installed: $(caddy version)"
fi

echo "== 2/5: Installing Caddyfile =="
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl enable caddy >/dev/null

echo "== 3/5: Installing systemd service for the app =="
sudo cp deploy/shanai-faq-ai.service /etc/systemd/system/shanai-faq-ai.service
sudo systemctl daemon-reload
sudo systemctl enable --now shanai-faq-ai

echo "== 4/5: Opening firewall (80, 443) =="
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
else
  echo "  ufw not found — open 80/443 manually if you use another firewall"
fi

echo "== 5/5: Starting Caddy (requests HTTPS cert on first real request) =="
sudo systemctl restart caddy

echo
echo "Done. Once DNS for app.shanaiai.com points at this server's IP,"
echo "https://app.shanaiai.com will come up automatically (Let's Encrypt)."
echo
echo "Check status any time:"
echo "  sudo systemctl status shanai-faq-ai"
echo "  sudo systemctl status caddy"
echo "  sudo journalctl -u caddy -f      # watch cert issuance"
