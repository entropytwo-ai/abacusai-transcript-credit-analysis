#!/usr/bin/env bash
# Install (first run) and start the credit dashboard.
#   ./run.sh              install deps into .venv, verify, start on $PORT (default 3000)
#   ./run.sh --check      install + verify only
#   ./run.sh --sync       install + run one sync in the foreground
# Environment: ABACUS_API_KEY (required for syncing), PORT, HOST, CREDIT_DASH_DATA (data dir).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null || { echo "error: python3 not found" >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "error: Python 3.9+ required" >&2; exit 1; }

if [[ ! -x .venv/bin/python ]]; then
    echo "==> creating virtualenv"
    "$PY" -m venv .venv || { echo "error: python3 -m venv failed (Debian/Ubuntu: apt install python3-venv)" >&2; exit 1; }
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, jinja2, itsdangerous, multipart, abacusai' 2>/dev/null \
   || [[ requirements.txt -nt .venv/.installed ]]; then
    echo "==> installing requirements"
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -r requirements.txt
    touch .venv/.installed
fi

echo "==> verifying install"
.venv/bin/python -m app.cli check

case "${1:-}" in
    --check) exit 0 ;;
    --sync)  exec .venv/bin/python -m app.cli sync ;;
esac

link=$(.venv/bin/python -m app.cli setup-link)
if [[ -n $link ]]; then
    echo
    echo "==> No owner account yet. Open this one-time link (on this site's address) to create it:"
    echo "    $link"
    echo
fi
echo "==> starting on ${HOST:-0.0.0.0}:${PORT:-3000}"
exec .venv/bin/uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-3000}" --proxy-headers --forwarded-allow-ips='*'
