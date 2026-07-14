# Local dashboard backend

The dashboard is a packaged Flask application intended only for the local user. Install and start it from the repository root:

```powershell
uv sync --extra dashboard --dev
uv run python -m dashboard.backend.run
```

Open `http://127.0.0.1:5001`. The server accepts only explicit loopback hosts. Mutation requests require a loopback `Origin` and the request-protection token returned by `GET /api/csrf-token`; this is cross-site request protection, not user authentication.

Important endpoints:

- `GET /api/playlist` returns videos plus `source`, `stale`, and `last_updated`.
- `POST /api/refresh` returns HTTP 202 and a job ID.
- `GET /api/refresh/<job-id>` returns queued, running, completed, failed, timed-out, or abandoned state.
- `GET /api/channels` and `/api/channels/search?q=` return normalized subscription channel data.
- `/api/config` validates and atomically persists the shared configuration.
- `/api/stats/quota` consumes the CLI's versioned quota event log.

Only one refresh runs at a time. Configuration and channel mutations are locked while it runs. Full CLI output stays in server logs; browser-visible errors are sanitized and capped.
