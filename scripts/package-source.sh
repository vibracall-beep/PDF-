#!/bin/bash
# Produce a deterministic source archive without dependencies, caches or secrets.
set -euo pipefail
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
import sys

root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).expanduser().absolute()
checksum = output.with_name(output.name + '.sha256')
if output.exists() or checksum.exists():
    raise SystemExit('O arquivo de destino ou seu checksum já existe. Escolha outro nome.')
allowed = ['README.md', 'Package.swift', '.gitignore', 'requirements.txt', 'requirements-optional.txt', 'Sources', 'engine', 'scripts', 'tests', 'docs', '.github']
excluded = {'.git', '.venv', '__pycache__', '.build', '.DS_Store', 'node_modules', '.env', 'id_rsa', 'id_ed25519', 'credentials', 'secrets'}
files = []
for name in allowed:
    candidate = root / name
    if candidate.is_symlink():
        raise SystemExit(f'Link simbólico não permitido no pacote: {name}')
    if candidate.is_file():
        files.append(candidate)
    elif candidate.is_dir():
        for directory, directories, names in os.walk(candidate):
            directories[:] = sorted(name for name in directories if name not in excluded)
            for entry in directories:
                if (Path(directory) / entry).is_symlink():
                    raise SystemExit(f'Link simbólico não permitido: {Path(directory) / entry}')
            for entry in sorted(names):
                if entry in excluded or entry.endswith(('.pyc', '.pyo', '.pem', '.key', '.p12', '.pfx', '.mobileprovision')) or entry.startswith('.env'):
                    continue
                path = Path(directory) / entry
                if path.is_symlink():
                    raise SystemExit(f'Link simbólico não permitido: {path}')
                files.append(path)
files.sort(key=lambda path: path.relative_to(root).as_posix())
contents = {path: path.read_bytes() for path in files}
try:
    commit_result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD^{commit}'], capture_output=True, text=True, check=True)
    status_result = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=normal'], capture_output=True, text=True, check=True)
    commit = commit_result.stdout.strip()
    dirty = bool(status_result.stdout.strip())
except (subprocess.CalledProcessError, FileNotFoundError):
    commit, dirty = None, None
build_info = (json.dumps({'source_archive_format': 1, 'commit': commit, 'working_tree_dirty': dirty}, sort_keys=True, indent=2) + '\n').encode()
manifest = (''.join(f'{hashlib.sha256(contents[path]).hexdigest()}  {path.relative_to(root).as_posix()}\n' for path in files) + f'{hashlib.sha256(build_info).hexdigest()}  BUILD-INFO.json\n').encode()
output.parent.mkdir(parents=True, exist_ok=True)
created = False
try:
    raw = output.open('xb')
    created = True
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
    if created and output.exists():
        output.unlink()
    raise
print(f'Pacote: {output}')
print(f'SHA-256: {digest}')
print(f'Arquivos: {len(files)}')
PY
