#!/bin/bash
# Execute a relocated package while macOS denies all build-host dependency roots.
set -euo pipefail
umask 077
PDF_APP="$(cd "$1" && pwd -P)"
PDF_BUNDLE_PYTHON="$PDF_APP/Contents/Resources/runtime/bin/python3"
PDF_SCRIPTS="$PDF_APP/Contents/Resources/distribution"
[[ -x /usr/bin/sandbox-exec ]] || { echo 'Sandbox de isolamento indisponível; pacote não pode ser aprovado como independente.' >&2; exit 1; }
# This only denies reads, without modifying Homebrew, Xcode or another app.
PDF_HOME_QUOTED="$("$PDF_BUNDLE_PYTHON" -c 'import json,pathlib; print(json.dumps(str(pathlib.Path.home()/"Library/Application Support/PDF/runtimes")))')"
PDF_PROFILE="(version 1)(allow default)(deny network*)(deny file-read* (subpath \"/opt/homebrew\") (subpath \"/usr/local\") (subpath \"/Applications/LibreOffice.app\") (regex \"^/Applications/Xcode[^/]*[.]app(/|$)\") (subpath \"/Library/Developer\") (subpath $PDF_HOME_QUOTED))"
/usr/bin/codesign --verify --deep --strict "$PDF_APP"
/usr/bin/sandbox-exec -p "$PDF_PROFILE" "$PDF_BUNDLE_PYTHON" "$PDF_SCRIPTS/run-with-timeout.py" --seconds 600 -- "$PDF_BUNDLE_PYTHON" -I "$PDF_SCRIPTS/check_runtime.py" "$PDF_APP"
/usr/bin/sandbox-exec -p "$PDF_PROFILE" "$PDF_BUNDLE_PYTHON" "$PDF_SCRIPTS/run-with-timeout.py" --seconds 300 -- "$PDF_APP/Contents/MacOS/PDF" --smoke-test
printf '%s\n' 'Bundle portátil validado com acesso negado ao Homebrew, LibreOffice externo e ferramentas de compilação.'
