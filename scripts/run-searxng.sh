#!/usr/bin/env bash
# Run the locally installed SearXNG (see setup-searxng.sh) with this project's settings on 127.0.0.1:8080.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/.local/searxng"
if [ ! -x "$DEST/venv/bin/searxng-run" ]; then
  echo "SearXNG is not installed. Run scripts/setup-searxng.sh first." >&2
  exit 1
fi

# Use SEARXNG_SECRET from the environment or .env; otherwise generate one for this run.
if [ -z "${SEARXNG_SECRET:-}" ] && [ -f "$ROOT/.env" ]; then
  SEARXNG_SECRET="$(grep -E '^SEARXNG_SECRET=' "$ROOT/.env" | tail -1 | cut -d= -f2- || true)"
fi
if [ -z "${SEARXNG_SECRET:-}" ] || [ "$SEARXNG_SECRET" = "change-me-to-a-random-string" ]; then
  SEARXNG_SECRET="$("$DEST/venv/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
fi

export SEARXNG_SECRET
export SEARXNG_SETTINGS_PATH="$ROOT/searxng/settings.yml"
export SEARXNG_BIND_ADDRESS="${SEARXNG_BIND_ADDRESS:-127.0.0.1}"
export SEARXNG_PORT="${SEARXNG_PORT:-8080}"
exec "$DEST/venv/bin/searxng-run"
