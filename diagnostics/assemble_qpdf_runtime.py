"""Assemble the real qpdf dependency closure for an isolated diagnosis.

Production copy, link relocation, Mach-O rewriting, signature and manifest
helpers are reused. This is not an app package or a portable approval gate.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_binary import (command, contained_link, copy_tree, macho,
    otool_libraries, register_public_ca, relocate_links, remap_absolute,
    rewrite_macho, sign_if_needed, write_executable, write_manifest)


def _crypto_dependency(qpdf_root: Path, sources: dict[str, Path]) -> tuple[str, Path, Path]:
    """Read the source load commands before rewriting; never guess an ABI."""
    dependencies = set()
    for path in sorted(qpdf_root.rglob('*')):
        if not macho(path):
            continue
        for value in otool_libraries(command('/usr/bin/otool', '-m', '-L', path)):
            if re.fullmatch(r'libcrypto(?:\.[0-9]+)*\.dylib', Path(value).name):
                if not Path(value).is_absolute():
                    raise ValueError('The source qpdf crypto dependency is not an explicit load path.')
                dependencies.add(Path(value).resolve(strict=True))
    if len(dependencies) != 1:
        raise ValueError('The source qpdf must identify exactly one crypto library.')
    crypto = dependencies.pop()
    owners = [name for name, source in sources.items() if crypto.is_relative_to(source)]
    if len(owners) != 1 or not re.fullmatch(r'openssl(?:@[0-9]+)?', owners[0]):
        raise ValueError('The qpdf crypto library does not have a unique OpenSSL formula owner.')
    owner = owners[0]
    modules = sources[owner] / 'lib/ossl-modules'
    legacy = modules / 'legacy.dylib'
    if (not modules.is_dir() or not legacy.is_file()
            or not legacy.resolve(strict=True).is_relative_to(sources[owner]) or not macho(legacy)):
        raise ValueError('The qpdf crypto formula does not contain its own legacy provider.')
    return owner, crypto, modules


def assemble(destination: Path, commit: str | None = None) -> dict:
    if sys.platform != 'darwin' or command('/usr/bin/uname', '-m') != 'arm64':
        raise ValueError('The qpdf diagnostic runtime requires the real arm64 build Mac.')
    commit = commit or os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('An immutable source commit is required for the diagnostic manifest.')
    destination = destination.absolute()
    destination.mkdir(mode=0o700)
    # Canonicalize the newly created root, before recording relative load paths.
    destination = destination.resolve(strict=True)
    vendor = destination / 'vendor'
    vendor.mkdir()
    roots = ['qpdf', 'ca-certificates']
    formulas = sorted(set(roots + command('brew', 'deps', '--formula', '--installed', '--union', *roots).splitlines()))
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9@+_.-]*', name) for name in formulas):
        raise ValueError('A diagnostic dependency formula has an unsupported name.')
    formula_info = json.loads(command('brew', 'info', '--json=v2', '--formula', *formulas))
    sources = {name: Path(command('brew', '--prefix', name)).resolve(strict=True) for name in formulas}
    crypto_formula, source_crypto, source_modules = _crypto_dependency(sources['qpdf'], sources)
    source_qpdf = (sources['qpdf'] / 'bin/qpdf').resolve(strict=True)
    if not source_qpdf.is_relative_to(sources['qpdf']) or not macho(source_qpdf):
        raise ValueError('The source qpdf is not its formula-owned Mach-O executable.')
    maps = {}
    copies = []
    for name in formulas:
        copied = vendor / name
        maps[sources[name]] = copied
        maps[Path('/opt/homebrew/opt') / name] = copied
        copies.append((sources[name], copied))
    for original, copied in copies:
        copy_tree(original, copied)
    register_public_ca(destination, maps)
    for original, copied in copies:
        relocate_links(original, copied, maps)
    for path in destination.rglob('*'):
        if path.is_symlink():
            contained_link(path, os.readlink(path), destination)
        elif path.is_dir() and path.suffix in ('.app', '.framework', '.xpc'):
            raise ValueError('Unexpected nested code bundle in the small qpdf dependency closure.')
    qpdf = remap_absolute(source_qpdf, maps)
    crypto = remap_absolute(source_crypto, maps)
    modules = remap_absolute(source_modules, maps)
    # Keep the production shell transport and default module discovery intact.
    # The driver controls OPENSSL_MODULES per invocation to test the hypothesis.
    # Python/font/browser variables are irrelevant to this small qpdf closure.
    (destination / 'environment.sh').write_text('''#!/bin/bash
# Diagnostic subset of the production relocatable runtime environment.
PDF_RUNTIME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
export PATH="$PDF_RUNTIME/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
export SSL_CERT_FILE="$PDF_RUNTIME/vendor/ca-certificates/share/ca-certificates/cacert.pem"
export SSL_CERT_DIR="$PDF_RUNTIME/vendor/ca-certificates/share/ca-certificates"
''')
    (destination / 'bin').mkdir()
    wrapper = destination / 'bin/qpdf'
    relative_qpdf = qpdf.relative_to(destination).as_posix()
    if any(value in relative_qpdf for value in ('"', '`', '$', '\n')):
        raise ValueError('The diagnostic qpdf wrapper path cannot be represented safely.')
    write_executable(wrapper, '#!/bin/bash\nset -euo pipefail\nsource "$(dirname "$0")/../environment.sh"\n'
                     'exec "$PDF_RUNTIME/' + relative_qpdf + '" "$@"\n')
    native_files = [path for path in destination.rglob('*') if macho(path)]
    if qpdf not in native_files or crypto not in native_files or modules / 'legacy.dylib' not in native_files:
        raise ValueError('The copied qpdf/crypto/provider payload is incomplete.')
    for path in native_files:
        subprocess.run(['/usr/bin/lipo', str(path), '-verify_arch', 'arm64'], check=True, timeout=30)
        rewrite_macho(path, maps, destination)
    for path in native_files:
        sign_if_needed(path)
    for path in native_files:
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(path)], check=True, timeout=30)
    metadata = {
        'schemaVersion': 1, 'kind': 'qpdf-crypto-diagnostic-runtime', 'productApproved': False,
        'architecture': 'arm64', 'nativeFiles': len(native_files), 'nativeSignaturesVerifiedStrict': True,
        'cryptoFormula': crypto_formula, 'sourceQPDF': str(source_qpdf), 'sourceCrypto': str(source_crypto),
        'qpdf': relative_qpdf, 'crypto': crypto.relative_to(destination).as_posix(),
        'modules': modules.relative_to(destination).as_posix(), 'homebrew': formula_info,
        'environmentScope': 'qpdf transport and CA paths only; no module override installed',
    }
    (destination / 'provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
    write_manifest(destination, commit)
    return {'root': destination, 'qpdf': qpdf, 'wrapper': wrapper, 'crypto': crypto,
            'modules': modules, 'sourceQPDF': source_qpdf, 'formulaInfo': formula_info}
