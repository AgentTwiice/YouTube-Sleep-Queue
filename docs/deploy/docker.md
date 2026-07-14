# Raw Docker / VPS Runbook

Self-host YouTube Sleep Queue on any Linux VPS (or local machine) with Docker installed. The sync job runs as a one-shot container triggered by host cron or a systemd timer. No daemon, no restart policy.

---

## Prerequisites

- **Docker 24+** (ships Compose v2 as `docker compose`). Check: `docker compose version`.
- `make` — optional shortcut layer; not required.
- A **full checkout** of this repo on the server when building locally. The Dockerfile builds from the whole tree (`pyproject.toml`, `uv.lock`, `LICENSE`, `README.md`, `yt_sub_playlist/`), so grabbing just `docker-compose.yml` and `Dockerfile` will fail at build time. If a release image is available, you can skip this and pull instead — see [Build vs. pull](#build-vs-pull) below.
  ```bash
  git clone https://github.com/AgentTwiice/YouTube-Sleep-Queue.git /srv/youtube-sleep-queue
  cd /srv/youtube-sleep-queue
  ```

**OAuth credentials** — complete the one-time bootstrap on your laptop first:  
→ [docs/deploy/oauth-bootstrap.md](./oauth-bootstrap.md)

That process produces `client_secrets.json` and `token.json`. You will copy both to the server in the Setup section below.

---

## Setup

### Directory layout

All credentials and runtime state live in `./data/`. The compose file mounts it as `./data:/data`. The container writes state files (playlist cache, API log) here on every run, and rewrites `token.json` whenever the OAuth library refreshes it, so this directory must be writable by the container's UID.

```
/srv/youtube-sleep-queue/
├── docker-compose.yml
├── Dockerfile
└── data/                             ← bind-mounted at /data inside the container
    ├── client_secrets.json           (credentials, you provide)
    ├── token.json                    (credentials, you provide; refreshed in place)
    ├── config.json                   (optional)
    ├── .env                          (optional)
    ├── processed_videos.json          (runtime state)
    ├── playlist_cache/                (runtime state)
    └── api_call_log.json              (runtime state)
```

The container's entrypoint sets `YT_SUB_PLAYLIST_DATA_DIR=/data` so runtime
state files sit at the root of the bind-mounted directory alongside your
credentials. Local development that runs `python -m yt_sub_playlist` from a
repo checkout still writes into `yt_sub_playlist/data/` by default (backwards
compatible), so nothing changes for laptop use.

### Drop credentials into ./data/

Copy credentials AS THE HOST USER first — otherwise the chown+chmod steps
below lock the current user out of writing into `./data/`.

```bash
mkdir -p ./data

# From your laptop:
scp /path/to/client_secrets.json user@your-server:/srv/youtube-sleep-queue/data/
scp /path/to/token.json          user@your-server:/srv/youtube-sleep-queue/data/
```

### Lock down the data directory

```bash
# Linux hosts: the container runs as UID 1000. Give that UID write access.
# macOS Docker Desktop / OrbStack: UID translation is handled automatically —
# skip these two commands on macOS.
sudo chown -R 1000:1000 ./data

# Restrict access — this directory holds a live OAuth refresh token.
sudo chmod 700 ./data
```

### Optional: app configuration

The entrypoint forces the container's working directory to `/data`, so the
app reads `config.json` and `.env` from that directory automatically. Drop
them in if you want to override defaults (playlist name, duration filters,
lookback window, etc.). **Do this BEFORE the "Lock down the data directory"
step above** — otherwise the same `chown 1000:1000` + `chmod 700` will lock
the host user out of writing into `./data/`. If you missed it, either
`sudo cp` the files as root or temporarily chown back to your user, drop
them in, then re-run the lockdown.

```bash
scp /path/to/config.json user@your-server:/srv/youtube-sleep-queue/data/   # optional
scp /path/to/.env        user@your-server:/srv/youtube-sleep-queue/data/   # optional
```

See the [README](../../README.md) for the full list of supported env vars and config keys.

---

## Build vs. pull

### Build locally

Build the image from source when no release image has been published yet:

```bash
docker compose build
```

### Pull a published release from ghcr.io

Once the repository's container workflow has published a release tag, swap the compose file's `build: .` for an image pin and pull instead of building:

1. In `docker-compose.yml`, replace:
   ```yaml
   services:
     sync:
       build: .
       image: youtube-sleep-queue:local
   ```
   with:
   ```yaml
   services:
     sync:
       image: ghcr.io/agenttwiice/youtube-sleep-queue:<version>
   ```
2. Pull the published image:
   ```bash
   docker compose pull
   ```

Pin to a specific version tag rather than `:latest` so you opt in to upgrades explicitly.

---

## Verification: first run

Do a dry run before scheduling anything:

```bash
docker compose run --rm sync --dry-run
```

Expected: the sync logic runs, no videos are added to the playlist, no errors. If you see `ModuleNotFoundError` or a credentials failure, check that both JSON files landed in `./data/` with correct permissions.

> **--dry-run is strictly no-mutation.** With `PLAYLIST_ID` unset, dry-run
> skips the playlist-create call entirely and logs what would have been
> created. With `PLAYLIST_ID` set, dry-run verifies the playlist exists
> (read-only) then reports what would be added. Either way, nothing on
> your YouTube account changes.

---

## Scheduling

The `sync` service is intentionally one-shot — no `restart` policy. Pick whichever scheduler fits your server.

### Option A: host cron

```bash
crontab -e
```

Add a line (runs daily at 06:00):

```cron
0 6 * * *  cd /srv/youtube-sleep-queue && /usr/bin/docker compose run --rm sync >> ${HOME}/youtube-sleep-queue.log 2>&1
```

Log to a user-writable path (`${HOME}/youtube-sleep-queue.log`) rather than
`/var/log/`, which requires root. If you install the cron entry as root
(via `sudo crontab -e`) then `/var/log/youtube-sleep-queue.log` is fine.

Use the full path to `docker` (`which docker`) if your cron environment doesn't include it.

### Option B: systemd timer

Create two unit files. Replace `/srv/youtube-sleep-queue` with your actual checkout path.

**/etc/systemd/system/youtube-sleep-queue-sync.service**

```ini
[Unit]
Description=YouTube Sleep Queue sync
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=/srv/youtube-sleep-queue
ExecStart=/usr/bin/docker compose run --rm sync
StandardOutput=journal
StandardError=journal
```

**/etc/systemd/system/youtube-sleep-queue-sync.timer**

```ini
[Unit]
Description=Run YouTube Sleep Queue sync daily at 06:00

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now youtube-sleep-queue-sync.timer

# Verify the timer is active:
systemctl list-timers youtube-sleep-queue-sync.timer

# Trigger a manual run immediately (bypasses the timer schedule):
sudo systemctl start youtube-sleep-queue-sync.service
```

**Note:** cron *inside* the container is out of scope. The container exits after each sync; scheduling is the host's job.

---

## Logs

- **Host cron path:** logs land in whatever file you redirect to (the example above uses `${HOME}/youtube-sleep-queue.log`, or `/var/log/youtube-sleep-queue.log` for the root-cron variant). Rotate with `logrotate` if needed.
- **systemd timer path:** logs go to the journal. Read them with:
  ```bash
  journalctl -u youtube-sleep-queue-sync.service
  journalctl -u youtube-sleep-queue-sync.service --since "1 hour ago"
  ```

After a real run (not `--dry-run`), the primary verification is the log
output — look for `Processing complete: N/M videos added successfully`
and no `RefreshError` / `401` warnings.

Token file mtime is a WEAKER signal: the app only rewrites `token.json`
when the credentials it loaded were expired or otherwise invalid. On a
successful run with a still-valid access token the file is untouched, so
an unchanged mtime does NOT mean the refresh cycle is broken. The mtime
only proves activity when it DOES advance — an updated mtime means a
refresh happened and the round-trip works.

```bash
# Linux with the lockdown applied: sudo, because ./data is chmod 700 owned by 1000
sudo ls -la ./data/token.json
```

---

## Dashboard

The dashboard is **out of scope for v1** on raw Docker. It is intentionally
commented out of `docker-compose.yml`. The dashboard backend's data-source
path is currently hard-coded, so it does not yet honour the same
`YT_SUB_PLAYLIST_DATA_DIR` env var the CLI uses (the CLI got that in
issue #26; extending it to the dashboard is a future change).

For now, treat "look at the server's state" as an admin-shell task:
`ssh user@your-server 'ls -la /srv/youtube-sleep-queue/data/'`.

A future spec will cover dashboard deploy with a proper auth layer and
teach the dashboard to point at a mounted or remote directory.

---

## Re-authentication

Google refresh tokens can expire after roughly **6 months of disuse** or if the OAuth client's policy changes. When the sync starts failing with a `401` / `invalid_grant` error, you need to re-run the OAuth bootstrap.

1. On your laptop, re-run the bootstrap to produce a fresh `token.json`:
   ```bash
   uv run python -m yt_sub_playlist.auth.oauth
   ```
   See [docs/deploy/oauth-bootstrap.md](./oauth-bootstrap.md) for the full flow.

2. Copy the new token to the server. `./data/` is chmod 700 owned by UID
   1000 after the initial lockdown, so a plain `scp` as the deploy user
   will fail on Linux hosts where the deploy user is not UID 1000. Use
   one of these patterns:

   ```bash
   # Option A: scp to a staging path, then move as root
   scp /path/to/token.json user@your-server:/tmp/token.json
   ssh user@your-server 'sudo install -m 600 -o 1000 -g 1000 /tmp/token.json /srv/youtube-sleep-queue/data/token.json && rm /tmp/token.json'

   # Option B: rsync with --rsync-path=sudo (requires passwordless sudo)
   rsync -av --rsync-path='sudo rsync' --chown=1000:1000 /path/to/token.json user@your-server:/srv/youtube-sleep-queue/data/

   # macOS Docker Desktop / OrbStack hosts (no UID lockdown): plain scp works.
   scp /path/to/token.json user@your-server:/srv/youtube-sleep-queue/data/
   ```

3. If a sync container is currently running, stop it:
   ```bash
   docker stop youtube-sleep-queue-sync
   ```
   The next scheduled run will pick up the new token automatically.

Re-auth is also required if you rotate your GCP OAuth client credentials — in that case replace both `client_secrets.json` and `token.json`.
