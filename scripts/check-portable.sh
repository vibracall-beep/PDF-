#!/bin/bash
# Execute a relocated package while macOS denies all build-host dependency roots.
set -euo pipefail
umask 077
PDF_APP="$(cd "$1" && pwd -P)"
PDF_BUNDLE_PYTHON="$PDF_APP/Contents/Resources/runtime/bin/python3"
PDF_SCRIPTS="$PDF_APP/Contents/Resources/distribution"
[[ -x /usr/bin/sandbox-exec ]] || { echo 'Sandbox de isolamento indisponível; pacote não pode ser aprovado como independente.' >&2; exit 1; }
# Deny both reads and writes; no host installation is renamed or modified.
PDF_HOME_QUOTED="$("$PDF_BUNDLE_PYTHON" -c 'import json,pathlib; print(json.dumps(str(pathlib.Path.home()/"Library/Application Support/PDF/runtimes")))')"
PDF_PROFILE="(version 1)(allow default)(deny network*)(deny file-read* file-write* (subpath \"/opt/homebrew\") (subpath \"/usr/local\") (subpath \"/Applications/LibreOffice.app\") (regex \"^/Applications/Xcode[^/]*[.]app(/|$)\") (subpath \"/Library/Developer\") (subpath $PDF_HOME_QUOTED))"
# The signed helper owns a short private Unix namespace. It first proves the
# local-only exception and blocked IP/escape boundaries, then runs these same
# runtime/native checks and verifies the bundle remains byte-for-byte intact.
exec "$PDF_BUNDLE_PYTHON" -I "$PDF_SCRIPTS/portable_isolation.py" --app "$PDF_APP" --base-profile "$PDF_PROFILE"
