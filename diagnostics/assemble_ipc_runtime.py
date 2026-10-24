"""Build a small, real relocated Python/Chromium runtime for IPC diagnosis.

Uses the production relocation/signature checks; it is not a distribution or a
replacement for the complete app's isolated installation tests.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_binary import (command, complete_python_frameworks, contained_link,
    copy_tree, isolate_python_startups, macho, register_public_ca, relocate_links,
    rewrite_macho, sign_if_needed, write_executable, write_manifest)


def assemble(source_venv, source_browsers, destination, commit):
    if sys.platform != 'darwin' or command('/usr/bin/uname', '-m') != 'arm64':
        raise ValueError('The diagnostic runtime requires the real arm64 build Mac.')
    source_venv, source_browsers = source_venv.resolve(strict=True), source_browsers.resolve(strict=True)
    python = source_venv / 'bin/python3'
    version = command(python, '-c', 'import sys;print("%d.%d"%sys.version_info[:2])')
    if version != '3.12': raise ValueError('The diagnostic Python must match the production 3.12 ABI.')
    playwright_version = command(python, '-c', 'import importlib.metadata;print(importlib.metadata.version("playwright"))')
    if playwright_version != '1.56.0': raise ValueError('The diagnostic requires the exact pinned Playwright release.')
    site = Path(command(python, '-c', 'import sysconfig;print(sysconfig.get_path("purelib"))')).resolve(strict=True)
    if not site.is_relative_to(source_venv): raise ValueError('Source packages escaped their pinned fixture environment.')
    destination.mkdir(mode=0o700)
    # Match the production signing unit: dependency apps such as IDLE have
    # relative links into a sibling framework in this enclosing app. Verifying
    # IDLE as a standalone root falsely rejects those contained links. Keep the
    # entire payload, sign inner code first, and strictly verify the whole app.
    # Apple TN2206, "Gatekeeper Changes in macOS 10.11": apply --strict to the
    # topmost bundle; nested bundles may link into that enclosing bundle.
    app = destination / 'PDFIPCDiagnostic.app'
    contents = app / 'Contents'; executable_directory = contents / 'MacOS'
    executable_directory.mkdir(parents=True)
    runtime = contents / 'Resources/runtime'; runtime.mkdir(parents=True)
    stub = executable_directory / 'PDFIPCDiagnostic'
    subprocess.run(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-mmacosx-version-min=26.0',
                    '-Wall', '-Wextra', '-Werror', '-x', 'c', '-', '-o', str(stub)],
                   input='int main(void) { return 0; }\n', text=True, check=True, timeout=60)
    info = {'CFBundleIdentifier': 'org.vibracall.pdf.ipc-diagnostic', 'CFBundleName': 'PDF IPC Diagnostic',
            'CFBundleExecutable': stub.name, 'CFBundlePackageType': 'APPL',
            'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0', 'LSMinimumSystemVersion': '26.0'}
    with (contents / 'Info.plist').open('xb') as stream: plistlib.dump(info, stream)
    vendor = runtime / 'vendor'; vendor.mkdir()
    roots = ['python@3.12', 'ca-certificates']
    formulas = sorted(set(roots + command('brew', 'deps', '--formula', '--installed', '--union', *roots).splitlines()))
    maps, copies = {}, []
    for formula in formulas:
        original = Path(command('brew', '--prefix', formula)).resolve(strict=True)
        copied = vendor / formula
        maps[original] = copied; maps[Path('/opt/homebrew/opt') / formula] = copied
        copies.append((original, copied)); copy_tree(original, copied)
    register_public_ca(runtime, maps)
    isolated = isolate_python_startups(runtime, formulas)
    for original, copied in copies: relocate_links(original, copied, maps)
    restored = complete_python_frameworks(runtime, formulas)
    python_root = vendor / 'python@3.12/Frameworks/Python.framework/Versions/3.12'
    private_site = python_root / 'lib/python3.12/site-packages'
    if private_site.exists(): shutil.rmtree(private_site)
    copy_tree(site, private_site)
    browsers = runtime / 'browsers'; copy_tree(source_browsers, browsers)
    shutil.rmtree(browsers / '.links', ignore_errors=True)
    maps[source_browsers] = browsers
    for path in destination.rglob('*'):
        if path.is_symlink(): contained_link(path, os.readlink(path), destination)
    browser_paths = {
        'chromium': browsers / 'chromium-1194/chrome-mac/Chromium.app/Contents/MacOS/Chromium',
        'headless-shell': browsers / 'chromium_headless_shell-1194/chrome-mac/headless_shell',
    }
    for path in browser_paths.values():
        if not path.is_file(): raise ValueError('Pinned Playwright1.56 browser revision1194 is missing.')
    (runtime / 'bin').mkdir()
    write_executable(runtime / 'bin/python3', '''#!/bin/bash
set -euo pipefail
PDF_IPC_DIAGNOSTIC_RUNTIME="$(cd "$(dirname "$0")/.." && pwd -P)"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export PLAYWRIGHT_BROWSERS_PATH="$PDF_IPC_DIAGNOSTIC_RUNTIME/browsers"
export SSL_CERT_FILE="$PDF_IPC_DIAGNOSTIC_RUNTIME/vendor/ca-certificates/share/ca-certificates/cacert.pem"
export SSL_CERT_DIR="$PDF_IPC_DIAGNOSTIC_RUNTIME/vendor/ca-certificates/share/ca-certificates"
exec "$PDF_IPC_DIAGNOSTIC_RUNTIME/vendor/python@3.12/Frameworks/Python.framework/Versions/3.12/bin/python3.12" -I -B "$@"
''')
    native_files = [path for path in app.rglob('*') if macho(path)]
    print('IPC diagnostic Mach-O files:', len(native_files), flush=True)
    for path in native_files:
        subprocess.run(['/usr/bin/lipo', str(path), '-verify_arch', 'arm64'], check=True, timeout=30)
        rewrite_macho(path, maps, app)
    for path in native_files: sign_if_needed(path)
    nested = [path for path in app.rglob('*') if path.is_dir() and not path.is_symlink()
              and path.suffix in ('.app', '.framework', '.xpc')]
    for path in sorted(nested, key=lambda value: len(value.parts), reverse=True) + [app]:
        sign_if_needed(path, deep=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True, timeout=90)
    for path in native_files:
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(path)], check=True, timeout=30)
    metadata = {'schemaVersion': 1, 'kind': 'private-ipc-diagnostic-runtime', 'productApproved': False,
        'architecture': 'arm64', 'pythonABI': version, 'playwrightVersion': playwright_version, 'chromiumRevision': '1194',
        'signatureUnit': app.name, 'signatureVerifiedDeepStrict': True, 'syntheticExecutable': stub.relative_to(destination).as_posix(),
        'removedHostStartup': isolated, 'completedFrameworkLinks': restored, 'nativeFiles': len(native_files),
        'sourcePackages': json.loads(command(python, '-m', 'pip', 'list', '--format=json')),
        'homebrew': json.loads(command('brew', 'info', '--json=v2', '--formula', *formulas))}
    (destination / 'provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
    write_manifest(destination, commit)
    return {'runtime': destination, 'app': app, 'python': runtime / 'bin/python3', 'browsers': browser_paths,
            'manifestSHA256': hashlib.sha256((destination / 'manifest.json').read_bytes()).hexdigest()}
