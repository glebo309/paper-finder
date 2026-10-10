#!/bin/bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$project_dir"
if [[ -x "$project_dir/.venv/bin/python" ]]; then
  python_bin="$project_dir/.venv/bin/python"
else
  python_bin="python3"
fi
exec "$python_bin" -m streamlit run "$project_dir/streamlit_app.py" \
  --server.address "${PAPER_FINDER_HOST:-127.0.0.1}" \
  --server.port "${PAPER_FINDER_PORT:-8501}"
