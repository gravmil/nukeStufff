#!/usr/bin/env bash
# Builds a single-file, dependency-free normal2height binary using PyInstaller.
#
# Build on the same OS/architecture you intend to run the result on -
# PyInstaller bundles native libraries, it does not cross-compile.
#
# Usage: ./scripts/build_executable.sh
# Output: dist/normal2height

set -euo pipefail
cd "$(dirname "$0")/.."

VENV_DIR=".venv-build"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

pip install --upgrade pip -q
pip install -e ".[exr]" -q
pip install pyinstaller -q

pyinstaller \
    --onefile \
    --name normal2height \
    --paths src \
    --collect-all OpenEXR \
    --collect-all imageio \
    --collect-submodules tifffile \
    scripts/pyinstaller_entry.py

echo
echo "Built: dist/normal2height"
echo "Run it directly, no Python install required: ./dist/normal2height --help"
