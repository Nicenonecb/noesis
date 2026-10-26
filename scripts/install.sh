#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -x "$project_dir/.venv/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --offline --python 3.11 "$project_dir/.venv"
  else
    "${NOESIS_PYTHON:-python3.11}" -m venv "$project_dir/.venv"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --offline --python "$project_dir/.venv/bin/python" setuptools
  uv pip install --offline --no-build-isolation --python "$project_dir/.venv/bin/python" -e "$project_dir"
else
  "$project_dir/.venv/bin/python" -m pip install --no-index --no-build-isolation -e "$project_dir"
fi
exec "$project_dir/.venv/bin/python" -m noesis.install install --project "$project_dir" "$@"
