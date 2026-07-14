#!/bin/sh
# Hydrate base64-encoded secrets from env vars to /data so the Python app can
# read them. If a file already exists on disk (bind-mounted or persisted-volume
# case), leave it alone so refreshed tokens survive restarts.
#
# Both OAuth files are JSON. They remain base64 encoded in environment variables
# so multiline values survive CI and hosting-provider secret transports intact.
#
# Encode files on the user's laptop with: base64 -w0 < token.json
# (macOS: `base64 < token.json | tr -d '\n'`)

set -eu

DATA_DIR="${YT_SUB_PLAYLIST_DATA_DIR:-/data}"

write_secret() {
    var_value="$1"
    file_name="$2"
    file_path="$DATA_DIR/$file_name"

    if [ -z "$var_value" ]; then
        return 0
    fi

    if [ -f "$file_path" ]; then
        return 0
    fi

    temporary_path="$(mktemp "$DATA_DIR/.${file_name}.XXXXXX")"
    if ! printf '%s' "$var_value" | base64 -d > "$temporary_path"; then
        rm -f "$temporary_path"
        echo "Failed to decode $file_name" >&2
        return 1
    fi
    chmod 600 "$temporary_path"
    mv "$temporary_path" "$file_path"
}

mkdir -p "$DATA_DIR"
umask 077
write_secret "${CLIENT_SECRETS_B64:-}" client_secrets.json
write_secret "${TOKEN_B64:-}" token.json

# The app reads client_secrets.json / token.json as relative paths. The image's
# WORKDIR is /data, but platforms like GitHub Actions (`uses: docker://...`)
# override the container's working directory to the runner's checkout. Force
# cwd to the secrets directory so the CLI's relative reads find the hydrated
# files regardless of how the container was invoked.
cd "$DATA_DIR"

# Point the app's runtime state (playlist_cache/, processed_videos.json,
# api_call_log.json) at /data directly rather than the historical
# yt_sub_playlist/data/ subdirectory that resolves under cwd for local dev.
# See yt_sub_playlist/core/playlist_manager.py::resolve_data_dir and issue #26.
export YT_SUB_PLAYLIST_DATA_DIR="$DATA_DIR"

exec "$@"
