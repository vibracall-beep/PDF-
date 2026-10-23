#!/bin/bash
set -euo pipefail
PDF_SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PDF_SOURCE_ROOT"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-optional.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s scripts -p 'test_*.py' -v
