#!/bin/bash
# Download reviewed, immutable sources; then compile and install on this Mac.
# This script never executes an unverified download or follows a mutable branch.
set -euo pipefail
umask 077
usage() {
  cat <<'USAGE'
Uso:
  bash scripts/install-from-github.sh --commit <SHA completo de 40 caracteres>
  bash scripts/install-from-github.sh --archive <URL HTTPS> --sha256 <SHA-256 esperado>

Opções:
  --repository <dono/repositorio>  Padrão: vibracall-beep/PDF-
  --source-dir <diretorio>        Diretório novo para preservar os fontes baixados.
  --help                         Exibe esta ajuda.

A primeira forma usa Git HTTPS e verifica o commit exato. A segunda exige o
SHA-256 do pacote PDF-source.tar.gz e também verifica seu manifesto interno.
Obtenha o commit/checksum de uma execução revisada do GitHub Actions. Nenhuma
forma executa automaticamente uma branch mutável. Git usa a autenticação já
configurada no Mac. Requisitos: macOS 26+, Apple Silicon, Xcode 26+, Homebrew.
USAGE
}
fail() { printf '%s\n' "$*" >&2; exit 1; }
PDF_REPOSITORY='vibracall-beep/PDF-'
PDF_COMMIT=''
PDF_ARCHIVE_URL=''
PDF_EXPECTED_SHA=''
PDF_SOURCE_DEST=''
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --commit|--archive|--sha256|--source-dir|--repository)
      [[ "$#" -ge 2 && -n "$2" ]] || fail "Valor ausente para $1"
      case "$1" in
        --commit) PDF_COMMIT="$2" ;;
        --archive) PDF_ARCHIVE_URL="$2" ;;
        --sha256) PDF_EXPECTED_SHA="$2" ;;
        --source-dir) PDF_SOURCE_DEST="$2" ;;
        --repository) PDF_REPOSITORY="$2" ;;
      esac
      shift 2 ;;
    *) fail "Opção desconhecida: $1" ;;
  esac
done
if [[ -n "$PDF_COMMIT" ]]; then
  [[ -z "$PDF_ARCHIVE_URL" && -z "$PDF_EXPECTED_SHA" ]] || fail 'Escolha --commit OU --archive com --sha256.'
  [[ "$PDF_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]] || fail 'Informe o SHA completo e imutável de 40 caracteres; branches e tags não são aceitas.'
  PDF_COMMIT="$(printf '%s' "$PDF_COMMIT" | tr '[:upper:]' '[:lower:]')"
  PDF_SOURCE_KEY="$PDF_COMMIT"
else
  [[ "$PDF_ARCHIVE_URL" == https://* && "$PDF_EXPECTED_SHA" =~ ^[0-9a-fA-F]{64}$ ]] || fail 'Use --commit ou informe --archive HTTPS junto com --sha256 de 64 caracteres.'
  PDF_EXPECTED_SHA="$(printf '%s' "$PDF_EXPECTED_SHA" | tr '[:upper:]' '[:lower:]')"
  PDF_SOURCE_KEY="$PDF_EXPECTED_SHA"
fi
[[ "$PDF_REPOSITORY" =~ ^[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*$ ]] || fail 'Repositório inválido; use dono/repositorio.'
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail 'Requer macOS Apple Silicon executado sem Rosetta.'
if [[ -z "$PDF_SOURCE_DEST" ]]; then
  PDF_SOURCE_DEST="$HOME/Library/Application Support/PDF/sources/$PDF_SOURCE_KEY"
fi
[[ ! -e "$PDF_SOURCE_DEST" && ! -L "$PDF_SOURCE_DEST" ]] || fail 'O diretório de fontes já existe. Use outra pasta com --source-dir; o conteúdo existente será preservado.'
mkdir -p "$(dirname "$PDF_SOURCE_DEST")"
PDF_SOURCE_PARENT="$(cd "$(dirname "$PDF_SOURCE_DEST")" && pwd -P)"
PDF_SOURCE_DEST="$PDF_SOURCE_PARENT/$(basename "$PDF_SOURCE_DEST")"
PDF_DOWNLOAD_STAGE="$(mktemp -d "$PDF_SOURCE_PARENT/.pdf-download.XXXXXXXX")"
cleanup() { rm -rf -- "$PDF_DOWNLOAD_STAGE"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ -n "$PDF_COMMIT" ]]; then
  command -v git >/dev/null 2>&1 || fail 'Git não foi encontrado. Instale e selecione o Xcode.'
  git init --quiet "$PDF_DOWNLOAD_STAGE/source"
  git -C "$PDF_DOWNLOAD_STAGE/source" fetch --quiet --no-tags --depth 1 "https://github.com/$PDF_REPOSITORY.git" "$PDF_COMMIT"
  git -C "$PDF_DOWNLOAD_STAGE/source" -c advice.detachedHead=false checkout --quiet --detach FETCH_HEAD
  PDF_ACTUAL_COMMIT="$(git -C "$PDF_DOWNLOAD_STAGE/source" rev-parse --verify 'HEAD^{commit}')"
  [[ "$PDF_ACTUAL_COMMIT" == "$PDF_COMMIT" ]] || fail 'O commit recebido não corresponde ao commit solicitado.'
  git -C "$PDF_DOWNLOAD_STAGE/source" fsck --no-reflogs --no-dangling >/dev/null
  [[ -z "$(find "$PDF_DOWNLOAD_STAGE/source" -type l -print -quit)" ]] || fail 'Os fontes contêm links simbólicos e não serão executados.'
else
  command -v python3 >/dev/null 2>&1 || fail 'Python 3 é necessário para verificar o pacote. Instale Xcode ou Python pelo Homebrew.'
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 --fail --location --retry 2 --connect-timeout 20 --max-time 300 --max-filesize 134217728 \
    --output "$PDF_DOWNLOAD_STAGE/source.tar.gz" "$PDF_ARCHIVE_URL"
  PDF_ACTUAL_SHA="$(shasum -a 256 "$PDF_DOWNLOAD_STAGE/source.tar.gz" | awk '{print $1}')"
  [[ "$PDF_ACTUAL_SHA" == "$PDF_EXPECTED_SHA" ]] || fail 'Checksum divergente. O pacote não foi extraído nem executado.'
  python3 - "$PDF_DOWNLOAD_STAGE/source.tar.gz" "$PDF_DOWNLOAD_STAGE/source" <<'PY'
import gzip
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import unicodedata
archive_path, destination = Path(sys.argv[1]), Path(sys.argv[2])
class BoundedReader:
    def __init__(self, stream):
        self.stream = stream
        self.remaining = 160 * 1024 ** 2
    def read(self, size=-1):
        amount = self.remaining + 1 if size < 0 else min(size, self.remaining + 1)
        data = self.stream.read(amount)
        self.remaining -= len(data)
        if self.remaining < 0:
            raise SystemExit('O pacote descompactado excede o limite permitido.')
        return data

with gzip.open(archive_path, 'rb') as compressed, tarfile.open(fileobj=BoundedReader(compressed), mode='r|') as archive:
    files = {}
    canonical_names = {}
    file_names = set()
    directory_names = set()
    total_size = 0
    member_count = 0
    for member in archive:
        member_count += 1
        total_size += member.size
        if member_count > 10000 or member.size < 0 or member.size > 32 * 1024 ** 2 or total_size > 128 * 1024 ** 2:
            raise SystemExit('Pacote excede os limites de tamanho esperados.')
        path = PurePosixPath(member.name)
        if (path.is_absolute() or '..' in path.parts or len(path.parts) < 2 or path.parts[0] != 'PDF'
                or str(path) != member.name.rstrip('/') or any(ord(char) < 32 for char in member.name)):
            raise SystemExit('Caminho inválido no pacote.')
        # APFS/HFS installations commonly ignore case and normalize Unicode.
        # Reject aliases and file/directory collisions before creating files.
        for length in range(1, len(path.parts) + 1):
            prefix = '/'.join(path.parts[:length])
            canonical = unicodedata.normalize('NFD', prefix).casefold()
            if canonical in canonical_names and canonical_names[canonical] != prefix:
                raise SystemExit('Nomes de arquivos incompatíveis com o sistema de arquivos do Mac.')
            canonical_names[canonical] = prefix
            if length < len(path.parts):
                if canonical in file_names:
                    raise SystemExit('Um arquivo foi usado como diretório no pacote.')
                directory_names.add(canonical)
        canonical = unicodedata.normalize('NFD', str(path)).casefold()
        if member.isdir():
            if canonical in file_names:
                raise SystemExit('Conflito entre arquivo e diretório no pacote.')
            directory_names.add(canonical)
            continue
        if not member.isfile() or canonical in file_names or canonical in directory_names:
            raise SystemExit('Pacote contém link, tipo especial, nome duplicado ou conflito de diretórios.')
        file_names.add(canonical)
        stream = archive.extractfile(member)
        if stream is None:
            raise SystemExit('Arquivo inacessível no pacote.')
        content = stream.read()
        if len(content) != member.size:
            raise SystemExit('Arquivo truncado no pacote.')
        files[str(path)] = content
    manifest = files.get('PDF/SHA256SUMS')
    if manifest is None:
        raise SystemExit('Manifesto SHA256SUMS ausente.')
    expected = {}
    for line in manifest.decode('utf-8').splitlines():
        if '  ' not in line:
            raise SystemExit('Manifesto inválido.')
        digest, name = line.split('  ', 1)
        key = 'PDF/' + name
        if key in expected or re.fullmatch('[0-9a-f]{64}', digest) is None:
            raise SystemExit('Manifesto inválido.')
        expected[key] = digest
    if set(expected) != set(files) - {'PDF/SHA256SUMS'}:
        raise SystemExit('O manifesto não corresponde a todos os arquivos do pacote.')
    for name, digest in expected.items():
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise SystemExit('Checksum interno divergente: ' + name)
    if not {'PDF/Package.swift', 'PDF/scripts/install-mac.sh'}.issubset(files):
        raise SystemExit('O pacote não contém o instalador do PDF.')
    destination.mkdir(mode=0o700)
    for name, content in files.items():
        path = destination.joinpath(*PurePosixPath(name).parts[1:])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(content)
        path.chmod(0o755 if path.suffix == '.sh' else 0o644)
PY
fi
[[ -f "$PDF_DOWNLOAD_STAGE/source/scripts/install-mac.sh" && -f "$PDF_DOWNLOAD_STAGE/source/Package.swift" ]] || fail 'Os fontes não contêm um projeto PDF válido.'
# Atomically reserve a new destination. Existing directories are never merged.
mkdir "$PDF_SOURCE_DEST" || fail 'O destino foi criado por outro processo; arquivos existentes foram preservados.'
if ! cp -R "$PDF_DOWNLOAD_STAGE/source/." "$PDF_SOURCE_DEST/"; then
  fail "Não foi possível copiar os fontes. A pasta parcial foi preservada para diagnóstico: $PDF_SOURCE_DEST"
fi
printf 'Fontes verificados e preservados em: %s\n' "$PDF_SOURCE_DEST"
bash "$PDF_SOURCE_DEST/scripts/install-mac.sh"
