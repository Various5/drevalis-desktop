# Releasing a new version

Drevalis Creator Studio is distributed as Docker images on GHCR
(`ghcr.io/<org>/creator-studio-*`). Customer installs reference these
images and update via the in-app "Update now" button, which pulls the
newest tag matching what the license server's `/updates/manifest`
advertises.

## Release pipeline at a glance

```
Tag v1.2.3 on main
     │
     ▼
.github/workflows/release.yml fires
     │
     ├── Build + push 3 images to GHCR
     │     ghcr.io/<org>/creator-studio-app:1.2.3       (and :stable)
     │     ghcr.io/<org>/creator-studio-frontend:1.2.3  (and :stable)
     │     ghcr.io/<org>/creator-studio-updater:1.2.3   (and :stable)
     │
     └── POST the manifest to https://license.drevalis.com/admin/updates/publish
           with the new version number + image tags + changelog URL

Every licensed install's Settings → Updates tab flips to "Update available"
within 6 hours (the client-side cache TTL).
```

## One-time setup

### GitHub repository secrets

Settings → Secrets and variables → Actions:

| Name | Value | Where it comes from |
|------|-------|---------------------|
| `LICENSE_SERVER_ADMIN_TOKEN` | the `ADMIN_TOKEN` from your `/srv/drevalis-license/.env` | password manager |

### GitHub repository variables

Same page, Variables tab:

| Name | Value |
|------|-------|
| `LICENSE_SERVER_URL` | `https://license.drevalis.com` |

### GHCR package visibility

After the first run, GHCR creates the packages as **Private** by default.
Make them public so anonymous customers can pull:

- github.com/\<org\>?tab=packages → each `creator-studio-*` package → Package settings → **Change visibility → Public**

Otherwise `docker compose pull` in the installer fails with `unauthorized`.

## Cutting a release

```bash
# Make sure main is clean and the version bumps in pyproject.toml / frontend/package.json are committed
git checkout main
git pull

# Tag
git tag v1.2.3
git push origin v1.2.3
```

The Actions workflow picks up the tag, builds, pushes, and tells the
license server. Watch it in the Actions tab. Total time: ~5–8 min.

## Manual publish (no git tag)

Actions → Release workflow → **Run workflow** → type version → Run.

## Verifying the release

```bash
# Images visible on GHCR
docker pull ghcr.io/<org>/creator-studio-app:1.2.3
docker pull ghcr.io/<org>/creator-studio-app:stable

# License server has the new manifest
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     https://license.drevalis.com/admin/updates/current

# Customer install sees the update (do this on one of your own test boxes)
curl -s http://localhost:8000/api/v1/updates/status?force=true | jq .
```

## Rolling back

If a release breaks something:

1. Re-publish the previous manifest (roll the `current_stable`):
   ```bash
   curl -fsSL -X POST "https://license.drevalis.com/admin/updates/publish" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "current_stable": "1.2.2",
       "image_tags": {
         "app":      "ghcr.io/<org>/creator-studio-app:1.2.2",
         "worker":   "ghcr.io/<org>/creator-studio-app:1.2.2",
         "frontend": "ghcr.io/<org>/creator-studio-frontend:1.2.2",
         "updater":  "ghcr.io/<org>/creator-studio-updater:1.2.2"
       }
     }'
   ```
2. Clients already updated to 1.2.3 will NOT auto-downgrade — they need to
   manually edit their `docker-compose.yml` to pin `:1.2.2` and `docker compose up -d`.
3. Clients still on 1.2.2 stay there (they no longer see "update available").

Because GHCR doesn't delete images, `:1.2.2` always stays pullable.

## Semver conventions

- **Patch** (1.2.3 → 1.2.4): bug fixes only, always safe
- **Minor** (1.2.3 → 1.3.0): new features, no breaking changes, DB
  migrations allowed (Alembic runs on container start)
- **Major** (1.2.3 → 2.0.0): breaking changes. Publish with
  `"mandatory_security_update": false` unless it's a security fix. Consider
  writing a migration notes page before tagging.

## Changelog

Every release should ship with a GitHub Release (auto-created by the tag).
The release body becomes the "View changelog" link in the in-app update
banner.
