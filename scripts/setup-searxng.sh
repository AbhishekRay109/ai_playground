#!/usr/bin/env bash
# Install SearXNG from source into .local/searxng (no Docker). Linux and macOS; on Windows use WSL2.
# SearXNG is AGPL-3.0 and runs as a separate local service; this app only calls its HTTP API.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/.local/searxng"
PYTHON="${PYTHON:-python3}"

mkdir -p "$ROOT/.local"
if [ ! -d "$DEST/src/.git" ]; then
  git clone --depth 1 https://github.com/searxng/searxng.git "$DEST/src"
else
  git -C "$DEST/src" pull --ff-only
fi

"$PYTHON" -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install -U pip setuptools wheel pyyaml
"$DEST/venv/bin/pip" install -r "$DEST/src/requirements.txt"
"$DEST/venv/bin/pip" install --use-pep517 --no-build-isolation -e "$DEST/src"

echo "SearXNG installed in $DEST. Start it with: scripts/run-searxng.sh"
