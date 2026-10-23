#!/bin/bash
# Compatibility entrypoint: the complete installer now includes every engine.
set -euo pipefail
PDF_SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
printf '%s\n' 'OCR, LibreOffice e Chromium fazem parte da instalação completa. Verificando a instalação atual…'
PDF_APP="${PDF_INSTALL_DIR:-$HOME/Applications}/PDF.app"
if [[ -d "$PDF_APP" ]]; then
  if bash "$PDF_SOURCE_ROOT/scripts/check-mac.sh" "$PDF_APP"; then exit 0; fi
  printf '%s\n' 'A instalação precisa ser atualizada. Executando instalação completa com preservação da versão anterior…'
fi
exec bash "$PDF_SOURCE_ROOT/scripts/install-mac.sh"
