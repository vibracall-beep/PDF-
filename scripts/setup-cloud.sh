#!/bin/bash
set -euo pipefail
cd /workspace/PDF-
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
