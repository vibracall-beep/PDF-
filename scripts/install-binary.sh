#!/bin/bash
# Installs an already built package; no Xcode, Git, Homebrew or host Python.
# SHA-256 must be obtained from the trusted publisher independently of the download.
set -euo pipefail
umask 077
fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail 'Requer macOS Apple Silicon, sem Rosetta.'
[[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ]] || fail 'Requer macOS 26 ou posterior.'
[[ $# -ge 2 && $# -le 3 ]] || fail 'Uso: bash install-binary.sh ARQUIVO-ou-URL-HTTPS SHA256 [PASTA-DESTINO]'
PDF_PACKAGE_SOURCE="$1"
PDF_EXPECTED_SHA="$2"
[[ "$PDF_EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]] || fail 'Informe o SHA-256 completo publicado para esta versão.'
PDF_PARENT="${3:-$HOME/Applications}"
mkdir -p "$PDF_PARENT"
PDF_PARENT="$(cd "$PDF_PARENT" && pwd -P)"
PDF_EXTRACT="$(mktemp -d "$PDF_PARENT/.pdf-download.XXXXXXXX")"
PDF_EXTRACT_ID="$(stat -f '%d:%i' "$PDF_EXTRACT")"
cleanup() {
  PDF_STATUS=$?
  trap - EXIT
  if [[ -d "$PDF_EXTRACT" && ! -L "$PDF_EXTRACT" && "$(stat -f '%d:%i' "$PDF_EXTRACT")" == "$PDF_EXTRACT_ID" ]]; then
    rm -rf -- "$PDF_EXTRACT"
  fi
  exit "$PDF_STATUS"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
PDF_ARCHIVE="$PDF_EXTRACT/package.tar.gz"
if [[ "$PDF_PACKAGE_SOURCE" == https://* ]]; then
  /usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --max-time 1800 --max-filesize 12884901888 --output "$PDF_ARCHIVE" "$PDF_PACKAGE_SOURCE"
else
  [[ "$PDF_PACKAGE_SOURCE" != *://* && -f "$PDF_PACKAGE_SOURCE" ]] || fail 'Use um arquivo regular local ou uma URL HTTPS.'
  /bin/cp -c "$PDF_PACKAGE_SOURCE" "$PDF_ARCHIVE" || /bin/cp "$PDF_PACKAGE_SOURCE" "$PDF_ARCHIVE"
fi
PDF_ACTUAL_SHA="$(/usr/bin/shasum -a 256 "$PDF_ARCHIVE")"
PDF_ACTUAL_SHA="${PDF_ACTUAL_SHA%% *}"
[[ "$PDF_ACTUAL_SHA" == "$PDF_EXPECTED_SHA" ]] || fail 'Checksum não corresponde: nada foi instalado.'
# Only the authenticated archive is inspected/extracted. bsdtar's default
# traversal/symlink protections are retained; no -P or unsafe extraction flags.
/usr/bin/tar -tzf "$PDF_ARCHIVE" > "$PDF_EXTRACT/members.txt"
while IFS= read -r PDF_MEMBER; do
  [[ "$PDF_MEMBER" == PDF-distribution || "$PDF_MEMBER" == PDF-distribution/* ]] || fail 'Estrutura do pacote inválida.'
  [[ "/$PDF_MEMBER/" != */../* && "/$PDF_MEMBER/" != */./* ]] || fail 'Caminho inseguro no pacote.'
done < "$PDF_EXTRACT/members.txt"
/usr/bin/tar -xzf "$PDF_ARCHIVE" -C "$PDF_EXTRACT"
PDF_DISTRIBUTION="$PDF_EXTRACT/PDF-distribution"
PDF_APP="$PDF_DISTRIBUTION/PDF.app"
/usr/bin/codesign --verify --deep --strict "$PDF_APP"
# This interpreter and updater are authenticated by the archive checksum and
# bundle seal before first execution. No destination-side build or pip install.
"$PDF_APP/Contents/Resources/runtime/bin/python3" \
  "$PDF_APP/Contents/Resources/distribution/binary_update.py" install \
  --distribution "$PDF_DISTRIBUTION" --destination "$PDF_PARENT"
printf 'Abra com: open %q\n' "$PDF_PARENT/PDF.app"
printf '%s\n' 'Assinatura ad hoc, sem notarização Apple. As políticas do Gatekeeper permanecem ativas.'
