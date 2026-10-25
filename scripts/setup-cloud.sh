#!/bin/bash
set -euo pipefail
PDF_SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PDF_SOURCE_ROOT"
python3 -m venv .venv
export PATH="$PDF_SOURCE_ROOT/.venv/bin:$PATH"
.venv/bin/python -m pip install -r requirements.txt -r requirements-optional.txt
command -v java >/dev/null || { printf '%s\n' 'Instale Java 21 para a validação independente de PDF/A e PDF/UA.' >&2; exit 1; }
.venv/bin/python scripts/install-verapdf.py --directory .venv/share/verapdf
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s scripts -p 'test_*.py' -v
