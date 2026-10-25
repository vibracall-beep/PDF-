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
# PDF_SPACE_FUNCTIONS_BEGIN
pdf_available_kib() {
  local PDF_DF PDF_FREE
  PDF_DF="$(LC_ALL=C /bin/df -Pk "$PDF_PARENT")" || fail 'Não foi possível consultar o espaço livre do destino.'
  PDF_FREE="$(printf '%s\n' "$PDF_DF" | /usr/bin/awk 'NR == 2 && NF >= 6 { print $4; found = 1 } END { if (!found) exit 1 }')" || fail 'Resposta inválida ao consultar o espaço livre.'
  [[ "$PDF_FREE" =~ ^(0|[1-9][0-9]{0,14})$ ]] || fail 'O espaço livre informado pelo sistema é inválido.'
  printf '%s\n' "$PDF_FREE"
}
pdf_require_space() {
  local PDF_REQUIRED_BYTES="$1" PDF_PHASE="$2" PDF_FREE_KIB PDF_REQUIRED_KIB
  PDF_FREE_KIB="$(pdf_available_kib)"
  PDF_REQUIRED_KIB=$(( (PDF_REQUIRED_BYTES + 1023) / 1024 ))
  if [[ "$PDF_FREE_KIB" -lt "$PDF_REQUIRED_KIB" ]]; then
    fail "Espaço insuficiente para $PDF_PHASE: são necessários $(( (PDF_REQUIRED_KIB + 1023) / 1024 )) MiB livres e há $(( PDF_FREE_KIB / 1024 )) MiB. Libere espaço e execute novamente; a instalação existente foi preservada."
  fi
}
pdf_archive_bytes() {
  local PDF_VALUE
  # Match cp's existing non-recursive behavior for a user-selected symlink:
  # measure its target, not the handful of bytes in the link itself.
  PDF_VALUE="$(/usr/bin/stat -L -f '%z' "$1")" || fail 'Não foi possível medir o arquivo do pacote.'
  [[ "$PDF_VALUE" =~ ^[1-9][0-9]{0,10}$ && "$PDF_VALUE" -le 12884901888 ]] || fail 'O arquivo deve ter no máximo 12 GiB.'
  printf '%s\n' "$PDF_VALUE"
}
pdf_storage_integer() {
  local PDF_KEY="$1" PDF_MAXIMUM="$2" PDF_VALUE
  PDF_VALUE="$(/usr/bin/plutil -extract "storageRequirements.$PDF_KEY" raw -expect integer -o - "$PDF_MANIFEST" 2>/dev/null)" || fail 'O manifesto contém uma estimativa de espaço inválida.'
  [[ "$PDF_VALUE" =~ ^(0|[1-9][0-9]{0,11})$ && "$PDF_VALUE" -le "$PDF_MAXIMUM" ]] || fail 'A estimativa de espaço excede o limite permitido.'
  printf '%s\n' "$PDF_VALUE"
}
# PDF_SPACE_FUNCTIONS_END
PDF_ARCHIVE="$PDF_EXTRACT/package.tar.gz"
if [[ "$PDF_PACKAGE_SOURCE" == https://* ]]; then
  /usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --max-time 1800 --max-filesize 12884901888 --output "$PDF_ARCHIVE" "$PDF_PACKAGE_SOURCE"
else
  [[ "$PDF_PACKAGE_SOURCE" != *://* && -f "$PDF_PACKAGE_SOURCE" ]] || fail 'Use um arquivo regular local ou uma URL HTTPS.'
  PDF_ARCHIVE_BYTES="$(pdf_archive_bytes "$PDF_PACKAGE_SOURCE")"
  # Reserve an ordinary copy, even when APFS may later clone it cheaply.
  pdf_require_space "$(( PDF_ARCHIVE_BYTES + 67108864 ))" 'copiar o pacote'
  /bin/cp -c "$PDF_PACKAGE_SOURCE" "$PDF_ARCHIVE" || /bin/cp "$PDF_PACKAGE_SOURCE" "$PDF_ARCHIVE"
fi
PDF_ACTUAL_SHA="$(/usr/bin/shasum -a 256 "$PDF_ARCHIVE")"
PDF_ACTUAL_SHA="${PDF_ACTUAL_SHA%% *}"
[[ "$PDF_ACTUAL_SHA" == "$PDF_EXPECTED_SHA" ]] || fail 'Checksum não corresponde: nada foi instalado.'
# Only the authenticated archive is inspected/extracted. bsdtar's default
# traversal/symlink protections are retained; no -P or unsafe extraction flags.
/usr/bin/tar -tzf "$PDF_ARCHIVE" > "$PDF_EXTRACT/members.txt"
PDF_MANIFEST_MEMBERS=0
while IFS= read -r PDF_MEMBER; do
  [[ "$PDF_MEMBER" == PDF-distribution || "$PDF_MEMBER" == PDF-distribution/* ]] || fail 'Estrutura do pacote inválida.'
  [[ "/$PDF_MEMBER/" != */../* && "/$PDF_MEMBER/" != */./* ]] || fail 'Caminho inseguro no pacote.'
  if [[ "$PDF_MEMBER" == PDF-distribution/manifest.json ]]; then PDF_MANIFEST_MEMBERS=$(( PDF_MANIFEST_MEMBERS + 1 )); fi
done < "$PDF_EXTRACT/members.txt"
[[ "$PDF_MANIFEST_MEMBERS" == 1 ]] || fail 'O pacote precisa conter um único manifesto regular.'
# PDF_STORAGE_CHECK_BEGIN
# The archive has already passed SHA-256 authentication. Read only metadata
# before expanding the app. New archives place it first; --fast-read is bsdtar.
PDF_MANIFEST_JSON="$PDF_EXTRACT/storage-manifest.json"
/usr/bin/tar -xOzf "$PDF_ARCHIVE" --fast-read PDF-distribution/manifest.json > "$PDF_MANIFEST_JSON"
PDF_MANIFEST_BYTES="$(/usr/bin/stat -f '%z' "$PDF_MANIFEST_JSON")"
[[ "$PDF_MANIFEST_BYTES" =~ ^[1-9][0-9]{0,7}$ && "$PDF_MANIFEST_BYTES" -le 33554432 ]] || fail 'O manifesto excede o limite de 32 MiB.'
# plutil's lint/type/extract operations read property lists, not JSON. Its
# explicit converter accepts JSON and preserves integer/real/boolean types.
# Keep the authenticated JSON untouched; all queries use the same private plist.
PDF_MANIFEST="$PDF_EXTRACT/storage-manifest.plist"
/usr/bin/plutil -convert xml1 -o "$PDF_MANIFEST" -- "$PDF_MANIFEST_JSON" >/dev/null || fail 'O manifesto JSON é inválido.'
/usr/bin/plutil -lint "$PDF_MANIFEST" >/dev/null || fail 'A representação do manifesto é inválida.'
PDF_MANIFEST_SCHEMA="$(/usr/bin/plutil -extract schemaVersion raw -expect integer -o - "$PDF_MANIFEST" 2>/dev/null)" || fail 'A versão do manifesto é inválida.'
[[ "$PDF_MANIFEST_SCHEMA" == 1 ]] || fail 'A versão do manifesto não é suportada.'
if PDF_STORAGE_TYPE="$(/usr/bin/plutil -type storageRequirements "$PDF_MANIFEST" 2>/dev/null)"; then
  [[ "$PDF_STORAGE_TYPE" == dictionary ]] || fail 'A estimativa autenticada de espaço não é um objeto válido.'
  PDF_STORAGE_SCHEMA="$(pdf_storage_integer schemaVersion 1)"
  [[ "$PDF_STORAGE_SCHEMA" == 1 ]] || fail 'A versão da estimativa de espaço não é suportada.'
  PDF_DISTRIBUTION_BYTES="$(pdf_storage_integer distributionBytes 12884901888)"
  PDF_BUNDLE_BYTES="$(pdf_storage_integer bundleBytes 12884901888)"
  PDF_DISTRIBUTION_ENTRIES="$(pdf_storage_integer distributionEntries 1000000)"
  PDF_BUNDLE_ENTRIES="$(pdf_storage_integer bundleEntries 1000000)"
  [[ "$PDF_DISTRIBUTION_BYTES" -gt 0 && "$PDF_BUNDLE_BYTES" -gt 0 && "$PDF_BUNDLE_BYTES" -le "$PDF_DISTRIBUTION_BYTES" && "$PDF_BUNDLE_ENTRIES" -gt 0 && "$PDF_BUNDLE_ENTRIES" -le "$PDF_DISTRIBUTION_ENTRIES" ]] || fail 'A estimativa de espaço do pacote é inconsistente.'
  # Available space already excludes the downloaded archive, current app and
  # existing backups. Rollback renames the current app; it does not copy it.
  # Allow full extraction + full staging copy (no clone assumption), 16 KiB
  # per entry for allocation/metadata, the manifest, and a 1 GiB working margin.
  PDF_REQUIRED_BYTES=$(( PDF_DISTRIBUTION_BYTES + PDF_BUNDLE_BYTES + PDF_MANIFEST_BYTES + 16384 * (PDF_DISTRIBUTION_ENTRIES + PDF_BUNDLE_ENTRIES) + 1073741824 ))
  pdf_require_space "$PDF_REQUIRED_BYTES" 'extrair, validar e instalar o aplicativo'
  printf 'Espaço verificado: estimativa conservadora de %s MiB além do pacote já copiado; a verificação não reserva blocos no disco.\n' "$(( (PDF_REQUIRED_BYTES + 1048575) / 1048576 ))"
else
  # Schema-1 packages delivered before this additive field remain compatible.
  # No gzip ISIZE (32-bit wrap), untrusted Content-Length or guessed JSON sum.
  printf '%s\n' 'Pacote anterior sem estimativa autenticada de espaço. O controle transacional continua ativo; não foi feita uma estimativa de extração.'
fi
# PDF_STORAGE_CHECK_END
# The private extraction directory remains 0700. Preserve authenticated file
# modes inside it: applying umask 077 to 0644/0755 would invalidate the exact
# manifest and executable permissions. Do not restore the build user's owner.
/usr/bin/tar -xzpf "$PDF_ARCHIVE" --no-same-owner -C "$PDF_EXTRACT"
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
