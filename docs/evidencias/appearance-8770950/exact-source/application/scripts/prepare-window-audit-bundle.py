#!/usr/bin/env python3
"""Build a diagnostic-only app around the compiled executable, without engines.

The production Info.plist is copied byte-for-byte. This small ad-hoc bundle is
only for the real WindowGroup lifecycle check; it is not an installed product,
an approved distribution or a substitute for installed/portable validation.
"""
import argparse
import os
from pathlib import Path
import platform
import plistlib
import shutil
import stat
import subprocess
import sys


PRODUCTION_PLIST = Path(__file__).with_name('PDF-Info.plist')


def copy_regular(source, destination, limit, mode):
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as reader:
        before = os.fstat(reader.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError('The diagnostic bundle requires a bounded regular input file.')
        count = 0
        with destination.open('xb') as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b''):
                count += len(block)
                if count > limit:
                    raise ValueError('The diagnostic bundle input grew beyond its limit.')
                writer.write(block)
        after = os.fstat(reader.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (count, after.st_mtime_ns, after.st_ctime_ns) or count != after.st_size:
            raise ValueError('The diagnostic bundle input changed during copying.')
    destination.chmod(mode)


def assemble(binary, destination):
    """Assemble only; signing and macOS execution remain separate operations."""
    binary = Path(binary).absolute(); destination = Path(destination).absolute()
    if destination.suffix != '.app':
        raise ValueError('The diagnostic destination must be a new .app directory.')
    metadata = plistlib.loads(PRODUCTION_PLIST.read_bytes())
    if metadata.get('CFBundleIdentifier') != 'local.pdf.desktop' or metadata.get('CFBundleExecutable') != 'PDF':
        raise ValueError('The shared production app identity is invalid.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)  # Refuse existing files, directories and links.
    identity = destination.stat()
    try:
        contents = destination / 'Contents'
        (contents / 'MacOS').mkdir(parents=True)
        (contents / 'Resources').mkdir()
        copy_regular(binary, contents / 'MacOS/PDF', 256 * 1024**2, 0o755)
        copy_regular(PRODUCTION_PLIST, contents / 'Info.plist', 65536, 0o644)
        with (contents / 'Resources/installation.lock').open('xb'):
            pass
        (contents / 'Resources/installation.lock').chmod(0o444)
    except BaseException:
        current = destination.lstat()
        if stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
            shutil.rmtree(destination)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    arguments = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        parser.error('Ad-hoc signing of this diagnostic bundle requires native Apple Silicon macOS.')
    app = assemble(arguments.binary, arguments.destination)
    subprocess.run(['/usr/bin/plutil', '-lint', str(app / 'Contents/Info.plist')], check=True, timeout=15)
    for target in (app / 'Contents/MacOS/PDF', app):
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(target)], check=True, timeout=30)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True, timeout=30)
    print('Diagnostic-only minimal bundle, with exact production Info.plist and installation lease:', app)
    print('No Python runtime, engine, icon or App Intents metadata was installed; this is not distribution approval.')


if __name__ == '__main__':
    main()
