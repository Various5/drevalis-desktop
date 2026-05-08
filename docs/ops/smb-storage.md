# Storage on an SMB/CIFS share

Drevalis reads and writes its media library at `/app/storage` inside
the container. Out of the box that's a local bind mount
(`./storage:/app/storage`), which is fast and zero-config. When you'd
rather have the media live on a NAS, a Windows share, or a homelab
TrueNAS box — so multiple machines can share the same library, or you
can keep the content off your dev laptop — point that same path at an
SMB share instead.

This guide walks through the minimal config. App code stays unchanged;
the redirect happens at the Docker volume layer.

## 1. Prepare the share

On your NAS / file server:

1. Create a share named e.g. `drevalis-storage`.
2. Create a dedicated user (e.g. `drevalis`) with **read + write** on
   that share. Don't reuse an admin account.
3. Note the host's IP or hostname as seen from the machine running
   Drevalis. `ping nas.lan` from that machine must succeed.
4. If your NAS restricts SMB protocol versions, make sure at least
   **SMBv2.1 or SMBv3** is enabled. Drevalis defaults to 3.0.

## 2. Tell Docker where the share is

Copy `.env.example` to `.env` if you haven't already, then append:

```bash
SMB_HOST=nas.lan                 # or 192.168.1.42
SMB_SHARE=drevalis-storage
SMB_USER=drevalis
SMB_PASS=correct-horse-battery-staple
SMB_DOMAIN=WORKGROUP             # optional; keep as WORKGROUP if unsure
SMB_VERS=3.0                     # lower only if your NAS refuses 3.0
# Linux permissions seen inside the container. Match your container
# user (``nginx`` in frontend = 101, the default uvicorn app = root/0
# on Dockerfile images; tune to match). 1000/1000 works for most.
SMB_UID=1000
SMB_GID=1000
SMB_FILE_MODE=0664
SMB_DIR_MODE=0775
```

Keep this `.env` out of git.

## 3. Launch the stack with the SMB override

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.smb.override.yml \
  up -d
```

What this does:

* Adds a new Docker volume called `storage_smb` driven by the Linux
  kernel `cifs` module.
* Repoints both the `app` and `worker` services so their
  `/app/storage` path is backed by that SMB volume instead of the
  local `./storage` bind mount.
* Everything else (Postgres, Redis, the frontend nginx, the updater
  sidecar) stays local.

If the first `up -d` hangs or fails with `mount error(13): Permission
denied` or `(2): No such file or directory`, check:

| Symptom | Fix |
|---|---|
| `mount error(13)` | Username / password / domain wrong. Double-check. |
| `mount error(2)` | Share name typo. `smbclient -L //nas.lan -U drevalis` lists shares. |
| `mount error(112)` | SMB protocol version mismatch. Try `SMB_VERS=2.1`. |
| Permission denied when writing | Wrong `SMB_UID`/`SMB_GID`. Run `id` inside the container (`docker compose exec app id`) and set SMB_UID/SMB_GID to those values. |
| Slow scene generation | Use a Gigabit link; 100 Mb/s is a hard ceiling. |

## 4. Move existing media onto the share

One-time copy of your local `./storage/` onto the NAS (before switching
the compose override on):

```bash
# Linux / macOS
rsync -avP ./storage/ /mnt/nas/drevalis-storage/

# Windows (PowerShell)
robocopy .\storage \\nas.lan\drevalis-storage /MIR /R:3 /W:5
```

After the copy finishes, bring the stack up with the override (step 3).
If your `media_assets.file_path` values look wrong on the new mount
— for instance the UUID directories differ — click **Settings → Backup
→ Repair now** once. The repair relinks rows to the actual files on
the share.

## 5. Verify

Once the stack is up:

```bash
# Should print ``cifs`` if mounted correctly
docker compose exec app sh -c "stat -f -c %T /app/storage"

# A sample write the app user owns
docker compose exec app sh -c "touch /app/storage/smoke && ls -l /app/storage/smoke && rm /app/storage/smoke"
```

If the write fails with `Read-only file system`, the kernel mounted
the share read-only — usually because SMBv1 fell through. Bump
`SMB_VERS` to 3.0 and redeploy.

## Caveats

* **Don't put Postgres on SMB.** Its WAL needs POSIX file locking
  that SMB doesn't guarantee. The override only touches the media
  volume.
* **Don't expose the share to the public internet.** Firewall SMB
  at the LAN boundary; it's not an authenticated HTTP API.
* **Backups still work.** The backup service writes to the
  `BACKUP_DIRECTORY` env var — that can live on the share too (the
  override can be extended with a second volume) or stay local.
* **Latency matters for long-form video.** Scene generation + ffmpeg
  assembly stream GB-scale files; a flaky NAS will bottleneck the
  entire pipeline. Budget Gigabit at minimum.
