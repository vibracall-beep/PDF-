#!/bin/bash
# Produce a deterministic source archive without dependencies, caches or secrets.
set -euo pipefail
umask 077
PDF_SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDF_ARCHIVE="${1:-$PDF_SOURCE_ROOT/dist/PDF-source.tar.gz}"
python3 - "$PDF_SOURCE_ROOT" "$PDF_ARCHIVE" <<'PY'
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import subprocess
import stat
import sys

root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).expanduser().absolute()
checksum = output.with_name(output.name + '.sha256')
if any(ord(char) < 32 for char in output.name):
    raise SystemExit('Nome de arquivo de destino inválido.')
if output.exists() or checksum.exists() or output.is_symlink() or checksum.is_symlink():
    raise SystemExit('O arquivo de destino ou seu checksum já existe. Escolha outro nome.')
allowed = ['README.md', 'Package.swift', '.gitignore', 'requirements.txt', 'requirements-optional.txt', 'Sources', 'engine', 'scripts', 'tests', 'docs', '.github']
excluded = {'.git', '.venv', '__pycache__', '.build', '.ds_store', 'node_modules', '.env', 'id_rsa', 'id_ed25519', 'credentials', 'secrets'}
def excluded_name(name):
    lower = name.lower()
    return (lower in excluded or lower.startswith('.env')
            or lower.endswith(('.pyc', '.pyo', '.pem', '.key', '.p8', '.p12', '.pfx', '.mobileprovision', '.jks', '.keystore', '.kdbx'))
            or any(lower == prefix or lower.startswith(prefix + '.') for prefix in ('credentials', '.credentials', 'secrets', '.secrets', 'id_rsa', 'id_ed25519')))


def walk_error(error):
    raise error


def read_regular_file(path):
    relative = path.relative_to(root)
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        file_fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(file_fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 32 * 1024 ** 2:
                raise SystemExit('Tipo ou tamanho de arquivo não permitido no pacote: ' + str(relative))
            content = stream.read(32 * 1024 ** 2 + 1)
            after = os.fstat(stream.fileno())
            if (len(content) != before.st_size or after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns):
                raise SystemExit('O arquivo mudou durante o empacotamento: ' + str(relative))
            return content
    finally:
        os.close(directory_fd)


files = []
for name in allowed:
    candidate = root / name
    if candidate.is_symlink():
        raise SystemExit(f'Link simbólico não permitido no pacote: {name}')
    if candidate.is_file():
        files.append(candidate)
    elif candidate.is_dir():
        for directory, directories, names in os.walk(candidate, onerror=walk_error):
            directories[:] = sorted(name for name in directories if not excluded_name(name))
            for entry in directories:
                if (Path(directory) / entry).is_symlink():
                    raise SystemExit(f'Link simbólico não permitido: {Path(directory) / entry}')
            for entry in sorted(names):
                if excluded_name(entry):
                    continue
                if any(ord(char) < 32 for char in entry):
                    raise SystemExit('Nome de arquivo inválido no pacote.')
                path = Path(directory) / entry
                if path.is_symlink():
                    raise SystemExit(f'Link simbólico não permitido: {path}')
                files.append(path)
files.sort(key=lambda path: path.relative_to(root).as_posix())
if len(files) > 9998:
    raise SystemExit('Os fontes excedem os limites do pacote de instalação.')
contents = {}
total_bytes = 0
for path in files:
    content = read_regular_file(path)
    total_bytes += len(content)
    if total_bytes > 120 * 1024 ** 2:
        raise SystemExit('Os fontes excedem os limites do pacote de instalação.')
    contents[path] = content
try:
    top_level = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True)
    if Path(top_level.stdout.strip()).resolve() != root:
        raise FileNotFoundError('A pasta não é a raiz do checkout.')
    commit_result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD^{commit}'], capture_output=True, text=True, check=True)
    status_result = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=normal'], capture_output=True, text=True, check=True)
    commit = commit_result.stdout.strip()
    dirty = bool(status_result.stdout.strip())
except (subprocess.CalledProcessError, FileNotFoundError):
    commit, dirty = None, None
build_info = (json.dumps({'source_archive_format': 1, 'commit': commit, 'working_tree_dirty': dirty}, sort_keys=True, indent=2) + '\n').encode()
manifest = (''.join(f'{hashlib.sha256(contents[path]).hexdigest()}  {path.relative_to(root).as_posix()}\n' for path in files) + f'{hashlib.sha256(build_info).hexdigest()}  BUILD-INFO.json\n').encode()
output.parent.mkdir(parents=True, exist_ok=True)
created_identity = None
try:
    raw = output.open('xb')
    created_stat = os.fstat(raw.fileno())
    created_identity = (created_stat.st_dev, created_stat.st_ino)
    with raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for path in files:
                    info = tarfile.TarInfo('PDF/' + path.relative_to(root).as_posix())
                    content = contents[path]
                    info.size = len(content)
                    info.mode = 0o755 if path.suffix == '.sh' else 0o644
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(content))
                info = tarfile.TarInfo('PDF/BUILD-INFO.json')
                info.size = len(build_info)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(build_info))
                info = tarfile.TarInfo('PDF/SHA256SUMS')
                info.size = len(manifest)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(manifest))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    with checksum.open('x') as stream:
        stream.write(f'{digest}  {output.name}\n')
except BaseException:
    # Remove only this command's newly created archive if publication failed.
    if created_identity is not None:
        try:
            current = output.lstat()
            if (current.st_dev, current.st_ino) == created_identity:
                output.unlink()
        except FileNotFoundError:
            pass
    raise
print(f'Pacote: {output}')
print(f'SHA-256: {digest}')
print(f'Arquivos: {len(files)}')
PY
