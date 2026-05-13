# Glitchtip self-host

Sentry-protocol-compatible error tracker for Drevalis Creator Studio.
Lives behind nginx-proxy-manager at https://errors.drevalis.com.

## Why Glitchtip, not Sentry

Sentry's self-host requires Kafka, ClickHouse, ZooKeeper, multiple
Snuba services — ~6 GB RAM minimum. Glitchtip implements the same
wire protocol with just Postgres + Redis + Celery, runs in ~700 MB,
and the desktop alpha doesn't need the analytics that justify
Sentry's footprint.

## Deploy

```bash
# 1. Copy this directory to /srv/glitchtip on the VPS.
scp -r infra/glitchtip drevalis@138.199.204.240:/srv/

# 2. SSH in and generate secrets.
ssh drevalis@138.199.204.240
cd /srv/glitchtip
cp .env.example .env
sed -i "s|REPLACE_WITH_openssl_rand_-base64_48|$(openssl rand -base64 48)|" .env
sed -i "s|REPLACE_WITH_openssl_rand_-base64_24|$(openssl rand -base64 24)|" .env

# 3. Bring the stack up. First boot takes ~30s while Postgres
#    initialises and Glitchtip runs migrations.
docker compose up -d

# 4. Tail logs until ``web`` reports it's listening.
docker compose logs -f web

# 5. Once healthy, create the superuser interactively.
docker compose exec web ./manage.py createsuperuser

# 6. Connect NPM to the proxy network so it can resolve glitchtip-web
#    by name. (Run on the host, not inside containers.)
docker network connect glitchtip-proxy nginx-proxy-manager

# 7. Open NPM UI (http://138.199.204.240:81). Add Proxy Host:
#      Domain Names:         errors.drevalis.com
#      Scheme:               http
#      Forward Hostname:     glitchtip-web
#      Forward Port:         8000
#      Cache Assets:         off
#      Block Common Exploits: on
#      Websockets Support:   ON  (required for the live UI)
#    SSL tab:
#      SSL Certificate:      Request a new SSL Certificate
#      Force SSL:            on
#      HTTP/2 Support:       on
#      HSTS Enabled:         on
#      Email:                varous555@gmail.com
#      Terms of Service:     accept
#    Save. NPM provisions the Let's Encrypt cert via HTTP-01;
#    propagation usually completes inside 30s.

# 8. Browse https://errors.drevalis.com and log in as the superuser
#    you created in step 5. Create an organisation, then create a
#    project named "drevalis-creator-studio". Copy its DSN — looks
#    like:
#      https://<key>@errors.drevalis.com/<project_id>

# 9. Paste the DSN as a GitHub repo secret:
#      gh secret set GLITCHTIP_DSN --body "<paste DSN here>"
#    Next alpha build (release.yml) bakes it into the binary via
#    ``DREVALIS_TELEMETRY_DSN`` at compile time and exposes it to the
#    backend via the same env var. Frontend reads from the backend's
#    ``/api/v1/telemetry/bootstrap`` so no rebuild is needed when the
#    DSN changes — flip the env var on the bundled backend and the
#    SPA picks it up on next page load.
```

## Operations

### Backups

The Postgres volume is named ``glitchtip-postgres-data``. To dump:

```bash
docker compose exec postgres pg_dump -U glitchtip glitchtip > /srv/glitchtip-backup-$(date +%Y%m%d).sql
```

### Upgrades

```bash
cd /srv/glitchtip
# Pin a new tag in docker-compose.yml, then:
docker compose pull web worker
docker compose up -d
# Migrations run automatically on web startup.
```

### Retention

By default Glitchtip keeps events forever — fine for an alpha-scale
project but worth pruning later. Add ``GLITCHTIP_MAX_EVENT_LIFE_DAYS=90``
to ``.env`` (and bounce the worker) when event volume justifies it.

## Wire format

The Drevalis SDK side is already wired (see
``src/drevalis/core/telemetry.py``, ``frontend/src/lib/telemetry.ts``,
``tauri/src-tauri/src/main.rs::init_telemetry``). All three speak the
Sentry HTTP envelope protocol, which Glitchtip implements. Once the
DSN env var is set the events flow with no code changes.
