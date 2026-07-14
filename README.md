# YouTube Sleep Queue

Automatically discovers recent videos from your YouTube subscriptions, ranks them locally for sleep suitability with Ollama, and adds the best candidates to a private or unlisted YouTube playlist.

This project is an MIT-licensed fork of Keith Baker's [`keif/playlist-from-subs`](https://github.com/keif/playlist-from-subs). The original copyright notice and licence are retained in [LICENSE](LICENSE); fork details are documented in [UPSTREAM.md](UPSTREAM.md).

## How it works

1. YouTube OAuth grants access to read subscriptions and manage one playlist.
2. Existing quota-efficient discovery and deterministic filters remove unsuitable durations, dates, channels, keywords, and live content.
3. Candidate metadata without a matching model/prompt/content cache entry is sent to the configured Ollama endpoint (local by default), which returns a score from 0 to 100 and a short rationale.
4. Candidates above `SLEEP_MINIMUM_SCORE` are sorted by score and capped by `SLEEP_QUEUE_SIZE`.
5. The latest candidate state and run summaries are stored locally in SQLite; selected videos are added to the configured YouTube playlist.

## Architecture

The fork keeps the upstream OAuth, YouTube API client, deterministic filters, cache, reporting, dashboard, and deployment assets. `PlaylistManager` now limits filtered candidates using `MAX_VIDEOS_TO_FETCH`, reuses unchanged rankings for the same Ollama model and prompt version, asks `SleepRanker` to score only cache misses through Ollama's structured-output API, persists rankings in one SQLite transaction, and sends only the highest-ranked eligible videos to the existing playlist insertion path.

Ollama failures are explicit: the run exits without adding a ranked queue when the endpoint is unavailable or the model returns invalid data. SQLite uses a versioned migration rather than ad-hoc table creation.

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- A Google Cloud project with YouTube Data API v3 enabled
- OAuth 2.0 desktop-app credentials

## Setup

```powershell
git clone https://github.com/AgentTwiice/YouTube-Sleep-Queue.git
cd YouTube-Sleep-Queue
uv sync
Copy-Item .env.example .env
ollama pull llama3.2:3b
ollama serve
```

Download the OAuth desktop client JSON from Google Cloud Console and save it as `client_secrets.json` in the project root. Then authenticate:

```powershell
uv run python -m yt_sub_playlist.auth.oauth
```

The OAuth flow creates a standard Google authorized-user `token.json`. Legacy pickle tokens are deliberately rejected because loading pickle from disk can execute code; delete an old token and authenticate again. Both credential files, `.env`, SQLite databases, reports, and local YouTube data are ignored by Git. Never commit or share them.

## Configure

Edit `.env`:

```dotenv
PLAYLIST_ID=
PLAYLIST_NAME=YouTube Sleep Queue
PLAYLIST_VISIBILITY=unlisted
VIDEO_MIN_DURATION_SECONDS=120
LOOKBACK_HOURS=168
MAX_VIDEOS_TO_FETCH=50
SKIP_LIVE_CONTENT=true

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_TIMEOUT_SECONDS=30
SLEEP_MINIMUM_SCORE=70
SLEEP_QUEUE_SIZE=10
```

If `PLAYLIST_ID` is empty, a playlist is created on the first live run. Use `private` or `unlisted` unless you intentionally want a public playlist.

## Run

Preview without creating a playlist or adding videos:

```powershell
uv run python -m yt_sub_playlist --dry-run --verbose
```

Run live:

```powershell
uv run python -m yt_sub_playlist
```

Generate a local report:

```powershell
uv run python -m yt_sub_playlist --report reports/sleep-queue.csv
```

Runtime state defaults to `yt_sub_playlist/data/`. Set `YT_SUB_PLAYLIST_DATA_DIR` to store it elsewhere. The SQLite database is created at `<data-dir>/sleep_queue.sqlite3` and migrated automatically using SQLite's `user_version`; migration 1 creates `queue_runs` and `video_candidates`, and migration 2 adds explicit run outcomes, insertion counts, ranking cache identity, scoring timestamps, and durable add history.

`queue_runs` records active, completed, and failed states plus candidate, selection, insertion, and insertion-failure counts. `video_candidates` stores the latest score, rationale, signals, cache identity, status, add history, and non-secret YouTube metadata for each discovered video. A failed sync is marked failed rather than appearing completed, while partial playlist insertion is recorded accurately. Future schema changes must increment `SCHEMA_VERSION` and add a forward migration; databases newer than the running application are rejected.

For Docker, Ollama must be reachable from the container. On Docker Desktop, set `OLLAMA_BASE_URL=http://host.docker.internal:11434`; Linux hosts may need an equivalent host-gateway or network configuration.

## Testing

```powershell
uv run python -m unittest discover -s tests -v
npm test
```

The repository CI also verifies JavaScript syntax, the frozen dependency lock, package builds, and tracked/unignored files for credential filenames and common secret patterns.

## Security and privacy

- The default Ollama endpoint is local. Video metadata is sent to whatever `OLLAMA_BASE_URL` you configure, so only use an endpoint you trust.
- OAuth credentials and tokens stay on the machine and are excluded from version control.
- SQLite contains personal viewing candidates and must remain private.
- The dashboard API is same-origin only for mutations, requires a per-process CSRF token, and renders video metadata through safe DOM properties instead of HTML interpolation. It is still intended for trusted local access and has no user login.
- The ranking prompt prohibits sensitive-trait inference and evaluates only supplied video metadata.
- Treat AI rankings as recommendations, not safety guarantees. Titles and metadata can be misleading.
- Review OAuth grants in your Google Account and revoke access when the application is no longer used.

## Known limitations

- Ollama must be running and the configured model must be installed; ranking fails explicitly if it is unavailable or returns invalid JSON.
- Ranking uses YouTube metadata, not audio or frame analysis.
- YouTube API quota and subscription visibility limits still apply.
- Playlist insertion is not transactional; a quota or network failure can result in a partially updated playlist.
- The inherited dashboard does not yet show sleep scores or SQLite run state, and it should not be exposed directly to the public internet because it has no authentication layer.

## Licence

MIT. See [LICENSE](LICENSE). Copyright (c) 2025 Keith Baker remains intact.
