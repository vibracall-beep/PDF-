#!/bin/bash
# Automated installed-bundle readiness checks. Does not open a GUI window.
set -euo pipefail
PDF_SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { printf '%s\n' 'A verificação nativa requer macOS Apple Silicon.' >&2; exit 1; }
PDF_APP="${1:-${PDF_INSTALL_DIR:-$HOME/Applications}/PDF.app}"
[[ -d "$PDF_APP" ]] || { printf 'Bundle inexistente: %s\n' "$PDF_APP" >&2; exit 1; }
PDF_APP="$(cd "$PDF_APP" && pwd -P)"
PDF_EXECUTABLE="$PDF_APP/Contents/MacOS/PDF"
PDF_INTERPRETER="$PDF_APP/Contents/Resources/runtime/bin/python3"
PDF_ENGINE_DIRECTORY="$PDF_APP/Contents/Resources/engine"
[[ -x "$PDF_EXECUTABLE" && -x "$PDF_INTERPRETER" ]] || { printf '%s\n' 'Executável ou runtime ausente.' >&2; exit 1; }
plutil -lint "$PDF_APP/Contents/Info.plist"
lipo "$PDF_EXECUTABLE" -verify_arch arm64
codesign --verify --deep --strict "$PDF_APP"
export PATH="/opt/homebrew/bin:$PATH"
command -v ocrmypdf >/dev/null
command -v tesseract >/dev/null
command -v gs >/dev/null
if ! command -v soffice >/dev/null 2>&1; then
  [[ -x /Applications/LibreOffice.app/Contents/MacOS/soffice ]] || { printf '%s\n' 'LibreOffice ausente.' >&2; exit 1; }
fi
PDF_LANGUAGES="$(tesseract --list-langs 2>/dev/null)"
printf '%s\n' "$PDF_LANGUAGES" | grep -qx por
printf '%s\n' "$PDF_LANGUAGES" | grep -qx eng
"$PDF_INTERPRETER" - "$PDF_ENGINE_DIRECTORY" <<'PY'
import pathlib
import sys
import tempfile
import fitz
from playwright.sync_api import sync_playwright
sys.path.insert(0, sys.argv[1])
from pdf_engine import run
from pdf_standards import validator_paths
import pyhanko.sign.signers
with tempfile.TemporaryDirectory(prefix='pdf-install-check-') as directory:
    root = pathlib.Path(directory)
    source = root / 'source.pdf'
    output = root / 'processed.pdf'
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), 'PDF installation verification')
        document.save(source)
    validator_paths()  # Hash-check the installed independent validator.
    run('validate-pdfua', [str(source)], str(root / 'ua-report.json'), {})
    import json
    report = json.loads((root / 'ua-report.json').read_text())
    assert report['compliant'] is False and report['counts']['failedRules'] > 0
    run('verify-signatures', [str(source)], str(root / 'signature-report.json'), {})
    signature_report = json.loads((root / 'signature-report.json').read_text())
    assert signature_report['signature_count'] == 0 and signature_report['all_integrity_ok'] is False
    run('rotate', [str(source)], str(output), {'degrees': 90})
    with fitz.open(output) as document:
        assert document.page_count == 1 and document[0].rotation == 90
        assert 'installation verification' in document[0].get_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content('<h1>PDF browser verification</h1>')
        page.pdf(path=str(root / 'browser.pdf'))
        browser.close()
    with fitz.open(root / 'browser.pdf') as document:
        assert 'PDF browser verification' in document[0].get_text()
print('Runtime, motor PDF, assinaturas, veraPDF independente e Chromium: OK')
PY
# The product must recover real text through its local OCR pipeline. A failed
# Apple-only capability audit is reported separately by CI, never substituted
# for this mandatory product smoke check or for the installer's rollback.
"$PDF_INTERPRETER" "$PDF_SOURCE_ROOT/scripts/run-with-timeout.py" --seconds 180 -- "$PDF_EXECUTABLE" --smoke-test
printf '%s\n' 'Bundle arm64, assinatura local, dependências, OCR local e verificações do aplicativo: OK'
