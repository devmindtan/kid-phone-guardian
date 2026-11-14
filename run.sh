#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

if ! python -c "import fastapi, uvicorn, httpx" >/dev/null 2>&1; then
  pip install -r requirements.txt
fi

exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}"
