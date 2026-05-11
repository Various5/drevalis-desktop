# Drevalis License Server

Minimal FastAPI service that issues + validates license JWTs for self-hosted Drevalis Creator Studio installs. Billing runs through Stripe; emails go out via Resend.

The service is a single container (~50 MB image, ~50 MB RAM at idle) with a SQLite database on a mounted volume. It runs comfortably on any small VPS, or on Fly.io's free tier as an alternate.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/checkout` | Start a Stripe Checkout session for tier+interval |
| POST | `/webhook/stripe` | Stripe webhook (signature-verified) |
| POST | `/activate` | Validate license key + machine, return a signed JWT |
| POST | `/heartbeat` | Renewal heartbeat — called every 24h by the client |
| POST | `/deactivate` | Release a seat for this machine |
| GET  | `/updates/manifest` | Latest release info (gated by active license) |
| GET  | `/admin/licenses` | List licenses (Bearer `ADMIN_TOKEN`) |
| GET  | `/admin/licenses/{id}` | License details + active machines |
| POST | `/admin/licenses/{id}/revoke` | Manually revoke |
| POST | `/admin/licenses/issue` | Create a license without Stripe (comps / bootstrap) |
| POST | `/admin/licenses/preview-jwt` | Mint a JWT for an existing license (manual delivery) |
| POST | `/admin/updates/publish` | Publish a new release manifest |

## One-time setup

1. **Generate the signing keypair** (done once — the public half lives in the client).

   ```bash
   python - <<'PY'
   from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
   from cryptography.hazmat.primitives import serialization
   k = Ed25519PrivateKey.generate()
   print(k.private_bytes(
       serialization.Encoding.PEM,
       serialization.PrivateFormat.PKCS8,
       serialization.NoEncryption(),
   ).decode())
   print(k.public_key().public_bytes(
       serialization.Encoding.PEM,
       serialization.PublicFormat.SubjectPublicKeyInfo,
   ).decode())
   PY
   ```

   - Private PEM → `LICENSE_PRIVATE_KEY_PEM` secret.
   - Public PEM → `src/drevalis/core/license/keys.py` in the client repo.

2. **Create Stripe products and prices.** One product per tier (Solo / Pro / Studio), two prices per product (monthly + yearly). Copy the six `price_...` IDs into the env vars.

3. **Register a Resend domain.** Optional in dev — emails no-op with structured logs when `RESEND_API_KEY` is unset.

## Deployment: self-hosted Docker + reverse proxy (recommended)

This is the default path. The compose file in this repo assumes you already have a reverse proxy on a Docker network called `proxy` — Nginx Proxy Manager, Caddy, Traefik, anything that terminates TLS and forwards HTTP.

### Prerequisites on the server

- Docker Engine + Compose plugin
- A reverse proxy running on the external network `proxy`
- DNS: `license.<yourdomain>` → server IP
- Ports 80/443 reachable from the public internet (for Let's Encrypt)

### Deploy

```bash
# On the server, as your deploy user (not root):
sudo mkdir -p /srv/drevalis-license
sudo chown -R $USER:$USER /srv/drevalis-license

# Copy this directory up from your dev machine:
#   scp -r license-server/* user@server:/srv/drevalis-license/
#   scp license-server/.env.example license-server/.gitignore user@server:/srv/drevalis-license/

cd /srv/drevalis-license
cp .env.example .env
# edit .env — paste every secret, then:
chmod 600 .env

# Ensure the shared proxy network exists (one-time):
docker network ls | grep -q '\bproxy\b' || docker network create proxy

docker compose up -d --build
docker compose logs -f license-server
# look for "license_server_startup_complete"
```

### Reverse-proxy configuration (Nginx Proxy Manager)

Admin UI → Hosts → Proxy Hosts → Add:

- Domain: `license.<yourdomain>`
- Scheme: `http`
- Forward Hostname: `drevalis-license-server`  (the container name on the `proxy` network)
- Forward Port: `8080`
- SSL tab: request a new Let's Encrypt cert, force SSL on

### Verify

```bash
curl -s https://license.<yourdomain>/health
# → {"status":"ok"}

curl -s -H "Authorization: Bearer <ADMIN_TOKEN>" \
     https://license.<yourdomain>/admin/licenses
# → []
```

### Updating

```bash
cd /srv/drevalis-license
git pull   # or scp a fresh copy up
docker compose up -d --build
```

SQLite at `./data/licenses.db` and `./data/manifest.json` are preserved across rebuilds.

### Backup

The entire state is in `/srv/drevalis-license/data`. A nightly cron is enough:

```bash
# /etc/cron.daily/drevalis-backup
#!/bin/sh
tar czf /root/backups/drevalis-$(date +%F).tgz -C /srv/drevalis-license data
find /root/backups -name 'drevalis-*.tgz' -mtime +14 -delete
```

Rsync that backup off-box to anywhere you trust.

## Deployment: Fly.io (alternate)

If you'd rather not run a VPS:

```bash
fly launch --copy-config --name drevalis-license --no-deploy
fly volumes create data --size 1 --region fra
fly secrets set LICENSE_PRIVATE_KEY_PEM="$(cat dev_private.pem)" \
                STRIPE_SECRET_KEY=sk_live_... \
                STRIPE_WEBHOOK_SECRET=whsec_... \
                ADMIN_TOKEN=$(openssl rand -hex 32) \
                RESEND_API_KEY=re_... \
                STRIPE_PRICE_SOLO_MONTHLY=price_... # ... all six prices
fly deploy
```

Point Stripe webhook at `https://drevalis-license.fly.dev/webhook/stripe`. The HTTP health check and SQLite volume are already configured in `fly.toml`.

## Local development

```bash
cd license-server
python -m venv .venv && source .venv/bin/activate   # or .\.venv\Scripts\Activate.ps1 on Windows
pip install -e .[dev]
cp .env.example .env
# edit .env: paste your dev private PEM, use Stripe test keys,
# set ADMIN_TOKEN=$(openssl rand -hex 32), leave RESEND_API_KEY empty.
# For local dev, override DATABASE_PATH=./licenses.db (not /data).

uvicorn app.main:app --reload --port 9000
```

Issue a license manually (no Stripe):

```bash
TOKEN=<your ADMIN_TOKEN>
PERIOD_END=$(date -d '+30 days' +%s)
curl -s -X POST http://localhost:9000/admin/licenses/issue \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"tier\":\"pro\",\"interval\":\"monthly\",\"email\":\"buyer@example.com\",\"period_end_unix\":${PERIOD_END}}"
```

Exchange a key for a JWT the client can use:

```bash
curl -s -X POST http://localhost:9000/activate \
  -H "Content-Type: application/json" \
  -d '{"license_key":"<id from issue response>","machine_id":"abc12345"}'
```

## Stripe webhook (local)

Forward real Stripe events to your local server via the Stripe CLI:

```bash
stripe listen --forward-to localhost:9000/webhook/stripe
# copy the whsec_... it prints into STRIPE_WEBHOOK_SECRET
stripe trigger checkout.session.completed
```

## Data model

Three tables, all SQLite:

- `licenses` — one row per purchased subscription (id = license key).
- `activations` — per-machine rows for seat enforcement + heartbeat timestamps.
- `webhook_events` — Stripe event IDs we've already processed (idempotency).

Plus one JSON file alongside the DB:

- `manifest.json` — current release manifest served by `GET /updates/manifest`.

Schema is created on startup; migrations aren't needed until the tables outgrow this shape.
