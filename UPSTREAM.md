# Upstream

- Original project: `keif/playlist-from-subs`
- Upstream repository: https://github.com/keif/playlist-from-subs
- Original licence: MIT
- Upstream commit used: `8b68dbd93f34ae7cb84a15e90996efc51126982f`

The upstream code provides YouTube OAuth, quota-efficient subscription discovery, deterministic filtering, playlist management, CLI/dashboard surfaces, and deployment support.

This fork adds local Ollama-based sleep-suitability scoring, score-based queue selection, SQLite run summaries and latest candidate state with versioned migrations, sleep-specific configuration, tests, documentation, and privacy protections. The original MIT licence and copyright notice are unchanged.

## Pulling future upstream changes

```powershell
git fetch upstream
git switch main
git switch -c maintenance/upstream-sync
git merge upstream/main
git push -u origin maintenance/upstream-sync
```

Open a pull request from `maintenance/upstream-sync` into `main`. Never force-push shared branches. Re-run the complete test suite after resolving conflicts, especially around configuration, playlist orchestration, persistence, and OAuth.
