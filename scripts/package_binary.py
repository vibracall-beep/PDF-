#!/usr/bin/env python3
"""Build a genuinely relocatable macOS app from an already validated source install.

Runs only on the build Mac. Every native dependency is copied and its Mach-O
load commands are rewritten; the destination Mac needs no development tools.
The resulting package is a candidate until check_portable.sh passes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
from binary_update import contained_link

SCRIPTS = Path(__file__).resolve().parent
MAGICS = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
SYSTEM = ('/System/Library/', '/usr/lib/')


def command(*args):
    return subprocess.check_output([str(value) for value in args], text=True).strip()


def macho(path):
    if not path.is_file() or path.is_symlink():
        return False
    with path.open('rb') as stream:
        return stream.read(4) in MAGICS


def copy_tree(source, destination):
    shutil.copytree(source, destination, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))


def remap_absolute(value, maps):
    value = Path(value)
    for original, replacement in sorted(maps.items(), key=lambda item: len(str(item[0])), reverse=True):
        if value == original or value.is_relative_to(original):
            return replacement / value.relative_to(original)
    # /opt/homebrew/lib and other public links may point into a known keg.
    resolved = value.resolve(strict=True)
    if resolved != value:
        return remap_absolute(resolved, maps)
    raise ValueError('Dependência externa não empacotada: ' + str(value))


def relocate_links(original, copied, maps):
    for parent, dirs, files in os.walk(copied, followlinks=False):
        for name in list(dirs) + files:
            path = Path(parent) / name
            if not path.is_symlink():
                continue
            old = original / path.relative_to(copied)
            # Homebrew exposes global site-packages outside the Python keg.
            # Do not copy host-global packages: the pinned app venv is merged
            # into this newly private directory below.
            if name == 'site-packages' and 'python' in str(old):
                path.unlink()
                path.mkdir()
                if name in dirs:
                    dirs.remove(name)
                continue
            target = old.resolve(strict=True)
            mapped = remap_absolute(target, maps)
            relative = os.path.relpath(mapped, path.parent)
            path.unlink()
            path.symlink_to(relative, target_is_directory=target.is_dir())
            if name in dirs:
                dirs.remove(name)


def rewrite_macho(path, maps, root):
    # Native frameworks already use @rpath/@loader_path. Rewrite every external
    # absolute load reference; fail closed for unexpected non-system libraries.
    changes = []
    output = command('/usr/bin/otool', '-l', path).splitlines()
    identifiers = set()
    rpaths = set()
    for index, line in enumerate(output):
        if line.strip() == 'cmd LC_ID_DYLIB':
            identifiers.add(output[index + 2].strip().removeprefix('name ').split(' (offset', 1)[0])
        if line.strip() == 'cmd LC_RPATH':
            rpaths.add(output[index + 2].strip().removeprefix('path ').split(' (offset', 1)[0])
    if identifiers:
        changes += ['-id', '@rpath/' + path.name]
    deps = {line.strip().split(' (', 1)[0] for line in command('/usr/bin/otool', '-L', path).splitlines()
            if line.startswith(('\t', ' ')) and ' (' in line}
    for value in sorted(deps - identifiers):
        if value.startswith('/') and not value.startswith(SYSTEM):
            mapped = remap_absolute(value, maps)
            if not mapped.exists():
                raise ValueError('Biblioteca ausente no pacote: ' + str(mapped))
            changes += ['-change', value, '@loader_path/' + os.path.relpath(mapped, path.parent)]
    for value in sorted(rpaths):
        if value.startswith('/') and not value.startswith(SYSTEM):
            try:
                mapped = remap_absolute(value, maps)
                changes += ['-rpath', value, '@loader_path/' + os.path.relpath(mapped, path.parent)]
            except (OSError, ValueError):
                # Discard build-tool search paths, never add a host fallback.
                changes += ['-delete_rpath', value]

    if changes:
        subprocess.run(['/usr/bin/install_name_tool', *changes, str(path)], check=True)
    # Reject a surviving absolute load path; textual debug/build strings do not
    # count as a load command and are retained for license/provenance integrity.
    for line in command('/usr/bin/otool', '-L', path).splitlines():
        if not line.startswith(('\t', ' ')) or ' (' not in line:
            continue
        value = line.strip().split(' (', 1)[0]
        if value.startswith('/') and not value.startswith(SYSTEM):
            raise ValueError('Carga Mach-O externa após relocalização: ' + value)


def write_executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


def build(installed, output, commit):
    if sys.platform != 'darwin' or command('/usr/bin/uname', '-m') != 'arm64':
        raise ValueError('Empacotamento requer o Mac arm64 de compilação.')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Commit imutável obrigatório.')
    output.mkdir(mode=0o700)
    app = output / 'PDF.app'
    copy_tree(installed, app)
    resources = app / 'Contents/Resources'
    old_runtime = Path((resources / 'runtime-location.txt').read_text().strip()).resolve(strict=True)
    (resources / 'runtime-location.txt').unlink()
    runtime = resources / 'runtime'
    shutil.rmtree(runtime)
    (runtime / 'vendor').mkdir(parents=True)
    roots = ['python@3.12', 'qpdf', 'tesseract', 'tesseract-lang', 'ghostscript', 'openjdk@21', 'ocrmypdf']
    formulas = sorted(set(roots + command('brew', 'deps', '--formula', '--installed', '--union', *roots).splitlines()))
    maps = {}
    copies = []
    for formula in formulas:
        source = Path(command('brew', '--prefix', formula)).resolve(strict=True)
        target = runtime / 'vendor' / formula
        maps[source] = target
        maps[Path('/opt/homebrew/opt') / formula] = target
        copies.append((source, target))
    for source, target in copies:
        copy_tree(source, target)
    # All dependencies are known before remapping cross-formula symlinks.
    for source, target in copies:
        relocate_links(source, target, maps)
    python_root = runtime / 'vendor/python@3.12/Frameworks/Python.framework/Versions/3.12'
    python = python_root / 'bin/python3.12'
    if not python.is_file():
        raise ValueError('Layout Python framework não reconhecido.')
    site = python_root / 'lib/python3.12/site-packages'
    if site.exists():
        shutil.rmtree(site)
    site.mkdir()
    # The source venv owns the pinned engine libraries. Copy regular contents;
    # no venv shebang or pyvenv.cfg may refer to the build host.
    source_site = old_runtime / 'lib/python3.12/site-packages'
    for item in source_site.iterdir():
        if item.name in ('__pycache__',) or item.suffix == '.pyc':
            continue
        destination = site / item.name
        if os.path.lexists(destination):
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if item.is_symlink():
            raise ValueError('Site-package com link não suportado: ' + item.name)
        if item.is_dir():
            copy_tree(item, destination)
        else:
            shutil.copy2(item, destination)
    copy_tree(old_runtime / 'share/verapdf', runtime / 'share/verapdf')
    copy_tree(old_runtime / 'browsers', runtime / 'browsers')
    shutil.rmtree(runtime / 'browsers/.links', ignore_errors=True)
    office_source = Path('/Applications/LibreOffice.app')
    copy_tree(office_source, runtime / 'LibreOffice.app')
    maps[office_source] = runtime / 'LibreOffice.app'
    # Browser symlinks are internal; copy preserves the official framework layout.
    for path in runtime.rglob('*'):
        if path.is_symlink():
            contained_link(path, os.readlink(path), runtime)
    bin_dir = runtime / 'bin'; bin_dir.mkdir()
    java = runtime / 'vendor/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java'
    jar = next((runtime / 'share/verapdf').glob('*.jar'))
    gs_resource = next((runtime / 'vendor/ghostscript/share/ghostscript').glob('*/Resource'))
    tessdata = runtime / 'vendor/tesseract/share/tessdata'
    # Homebrew's tesseract-lang is a separate keg; merge only missing language
    # files, retaining licenses and all original kegs in vendor.
    extra_languages = runtime / 'vendor/tesseract-lang/share/tessdata'
    for item in extra_languages.glob('*.traineddata'):
        if not (tessdata / item.name).exists():
            shutil.copy2(item, tessdata / item.name)
    def rel(path):
        return path.relative_to(runtime).as_posix()
    environment = '''#!/bin/bash
# Relocatable runtime: no Homebrew or user-site fallback.
PDF_RUNTIME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
export PATH="$PDF_RUNTIME/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
'''
    for key, value in {'PDF_JAVA': rel(java), 'PDF_VERAPDF_JAR': rel(jar),
                       'PLAYWRIGHT_BROWSERS_PATH': 'browsers', 'TESSDATA_PREFIX': rel(tessdata),
                       'GS_LIB': rel(gs_resource / 'Init') + ':$PDF_RUNTIME/' + rel(gs_resource / 'Font') + ':$PDF_RUNTIME/' + rel(gs_resource.parent / 'lib')}.items():
        # These build-generated relative paths contain no shell input.
        if '"' in value or '`' in value or '$(' in value:
            raise ValueError('Caminho de runtime inválido.')
        environment += f'export {key}="$PDF_RUNTIME/{value}"\n'
    (runtime / 'environment.sh').write_text(environment)
    programs = {'python3': rel(python), 'qpdf': 'vendor/qpdf/bin/qpdf',
                'tesseract': 'vendor/tesseract/bin/tesseract', 'gs': 'vendor/ghostscript/bin/gs',
                'java': rel(java), 'soffice': 'LibreOffice.app/Contents/MacOS/soffice'}
    for name, relative in programs.items():
        write_executable(bin_dir / name, '#!/bin/bash\nset -euo pipefail\nsource "$(dirname "$0")/../environment.sh"\nexec "$PDF_RUNTIME/' + relative + '" "$@"\n')
    ocr_env = runtime / 'vendor/ocrmypdf/libexec'
    ocr_site = next((ocr_env / 'lib').glob('python*/site-packages'))
    version = ocr_site.parent.name.removeprefix('python')
    ocr_python = runtime / f'vendor/python@{version}/Frameworks/Python.framework/Versions/{version}/bin/python{version}'
    if not ocr_python.exists():
        # Current formula may use the same 3.12 already bundled.
        raise ValueError('Python do OCRmyPDF não encontrado na árvore de dependências.')
    (runtime / 'dispatch_ocr.py').write_text('import runpy,sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).parent/' + repr(rel(ocr_site)) + '))\nsys.argv[0]="ocrmypdf"\nrunpy.run_module("ocrmypdf",run_name="__main__")\n')
    write_executable(bin_dir / 'ocrmypdf', '#!/bin/bash\nset -euo pipefail\nsource "$(dirname "$0")/../environment.sh"\nexec "$PDF_RUNTIME/' + rel(ocr_python) + '" -I "$PDF_RUNTIME/dispatch_ocr.py" "$@"\n')
    portable = {'schemaVersion': 1, 'commit': commit, 'architecture': 'arm64', 'minimumMacOS': '26.0',
                'dependencyFormulae': formulas, 'hostDependenciesAllowed': False}
    (runtime / 'portable.json').write_text(json.dumps(portable, indent=2) + '\n')
    distribution = resources / 'distribution'; distribution.mkdir()
    for filename in ('binary_update.py', 'install_files.py', 'run-with-timeout.py', 'check_runtime.py'):
        shutil.copy2(SCRIPTS / filename, distribution / filename)
    shutil.copy2(SCRIPTS / 'install-binary.sh', output / 'install-binary.sh')
    info = json.loads(command('brew', 'info', '--json=v2', '--formula', *formulas))
    (runtime / 'THIRD-PARTY.json').write_text(json.dumps(info, indent=2) + '\n')
    (runtime / 'THIRD-PARTY.txt').write_text('Components are redistributed as separate programs and libraries.\n'
        'Original license files remain in vendor, LibreOffice.app and browsers.\n'
        'THIRD-PARTY.json records exact versions, licenses, upstream source URLs and checksums from Homebrew.\n'
        'LibreOffice source and license: https://www.libreoffice.org/download/\n'
        'Chromium source and license: https://chromium.googlesource.com/chromium/src/\n'
        'Python wheels retain their dist-info license metadata.\n')
    native_files = [path for path in app.rglob('*') if macho(path)]
    print('Relocating Mach-O files:', len(native_files), flush=True)
    for path in native_files:
        subprocess.run(['/usr/bin/lipo', str(path), '-verify_arch', 'arm64'], check=True, stdout=subprocess.DEVNULL)
        rewrite_macho(path, maps, app)
    for path in native_files:
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(path)], check=True, stdout=subprocess.DEVNULL)
    nested = [path for path in app.rglob('*') if path.is_dir() and not path.is_symlink() and path.suffix in ('.app', '.framework', '.xpc')]
    for path in sorted(nested, key=lambda item: len(item.parts), reverse=True) + [app]:
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(path)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    write_manifest(output, commit)
    return output


def write_manifest(root, commit):
    files = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            contained_link(path, os.readlink(path), root)
            files[relative] = {'type': 'symlink', 'target': os.readlink(path)}
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            files[relative] = {'type': 'file', 'size': path.stat().st_size,
                               'mode': stat.S_IMODE(path.stat().st_mode), 'sha256': digest.hexdigest()}
    (root / 'manifest.json').write_text(json.dumps({'schemaVersion': 1, 'architecture': 'arm64',
        'commit': commit, 'files': files}, sort_keys=True, separators=(',', ':')) + '\n')


def archive(root, output):
    with output.open('xb') as raw:
        with tarfile.open(fileobj=raw, mode='w:gz', dereference=False) as tar:
            tar.add(root, arcname='PDF-distribution', recursive=True)
    digest = hashlib.sha256()
    with output.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    output.with_suffix(output.suffix + '.sha256').write_text(digest.hexdigest() + '  ' + output.name + '\n')
    print('Binary package SHA-256:', digest.hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    build(args.installed.resolve(strict=True), args.output.absolute(), args.commit)
    if args.archive:
        archive(args.output, args.archive)


if __name__ == '__main__':
    main()
