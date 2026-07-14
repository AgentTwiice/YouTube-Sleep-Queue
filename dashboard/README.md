# YouTube Sleep Queue dashboard

This vanilla HTML/CSS/JavaScript dashboard shows the generated sleep queue, edits validated configuration, manages channel filters, and starts asynchronous local refresh jobs.

Use the packaged backend rather than opening the files directly:

```powershell
uv sync --extra dashboard --dev
uv run python -m dashboard.backend.run
```

Then open `http://127.0.0.1:5001`. When no generated data exists, the API returns an explicitly empty, stale `source: none` response. `playlist.example.json` is used only when the user deliberately loads demonstration data; it is never presented as a successful live playlist.

The frontend uses local scripts only, creates untrusted channel/video content with DOM APIs and `textContent`, and contains no inline handlers or remote runtime dependencies.
