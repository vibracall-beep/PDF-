#!/usr/bin/env python3
"""Verified, journaled local app updates. No network, privilege or preference changes."""
from __future__ import annotations
import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager, ExitStack
from bundle_lease import exclusive, open_resource, check_descriptor, validate_inherited
from install_files import identity, move_new

LIMIT = 12 * 1024 ** 3
MANIFEST_LIMIT = 32 * 1024 ** 2
BUNDLE_ID = 'local.pdf.desktop'


def regular_bytes(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('Arquivo regular excede o limite permitido.')
        data = stream.read(limit + 1)
        if len(data) != info.st_size:
            raise ValueError('Arquivo mudou durante a leitura.')
        return data


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_journal(parent, data):
    target = parent / '.pdf-update.json'
    temporary = parent / ('.pdf-journal.' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write((json.dumps(data, sort_keys=True) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        sync_directory(parent)
    finally:
        temporary.unlink(missing_ok=True)


def contained_link(path, target, root):
    if not target or os.path.isabs(target):
        raise ValueError('Link absoluto ou vazio recusado: ' + str(path))
    resolved = (path.parent / target).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('Link sai do pacote: ' + str(path))


def verify_manifest(distribution):
    distribution = Path(distribution).resolve(strict=True)
    manifest = json.loads(regular_bytes(distribution / 'manifest.json', MANIFEST_LIMIT))
    if (manifest.get('schemaVersion') != 1 or manifest.get('architecture') != 'arm64'
            or not re.fullmatch('[0-9a-f]{40}', manifest.get('commit', ''))):
        raise ValueError('Manifesto de distribuição inválido.')
    expected = manifest.get('files')
    if not isinstance(expected, dict) or not expected or len(expected) > 200000:
        raise ValueError('Lista de arquivos inválida.')
    actual = {}
    folded = set()
    total = 0
    for parent, directories, files in os.walk(distribution, followlinks=False):
        for name in list(directories) + files:
            path = Path(parent) / name
            relative = path.relative_to(distribution).as_posix()
            if relative == 'manifest.json':
                continue
            if any(ord(c) < 32 for c in relative) or relative.casefold() in folded:
                raise ValueError('Nome de arquivo inválido ou ambíguo.')
            folded.add(relative.casefold())
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                contained_link(path, target, distribution)
                actual[relative] = {'type': 'symlink', 'target': target}
                if name in directories:
                    directories.remove(name)
            elif stat.S_ISDIR(info.st_mode):
                continue
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > LIMIT:
                    raise ValueError('Pacote excede 12 GiB.')
                digest = hashlib.sha256()
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError('Arquivo mudou durante a validação.')
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                    os.fsync(stream.fileno())
                actual[relative] = {'type': 'file', 'sha256': digest.hexdigest(),
                                    'size': info.st_size, 'mode': stat.S_IMODE(info.st_mode)}
            else:
                raise ValueError('Arquivo especial recusado: ' + relative)
    if actual != expected:
        raise ValueError('O manifesto não corresponde exatamente ao pacote extraído.')
    app = distribution / 'PDF.app'
    verify_bundle_identity(app)
    return manifest


def verify_copied_bundle(app, manifest):
    expected = {name.removeprefix('PDF.app/'): value for name, value in manifest['files'].items()
                if name.startswith('PDF.app/')}
    actual = {}
    directories = []
    for parent, children, files in os.walk(app, followlinks=False):
        directories.append(Path(parent))
        for name in list(children) + files:
            path = Path(parent) / name
            relative = path.relative_to(app).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                contained_link(path, os.readlink(path), app)
                actual[relative] = {'type': 'symlink', 'target': os.readlink(path)}
                if name in children:
                    children.remove(name)
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                    os.fsync(stream.fileno())
                actual[relative] = {'type': 'file', 'sha256': digest.hexdigest(),
                                    'size': info.st_size, 'mode': stat.S_IMODE(info.st_mode)}
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError('Arquivo especial na cópia de instalação.')
    if actual != expected:
        raise ValueError('Cópia de instalação difere do manifesto verificado.')
    for directory in reversed(directories):
        sync_directory(directory)


def verify_bundle_identity(app):
    identity(app)
    info = plistlib.loads(regular_bytes(app / 'Contents/Info.plist', 1024 * 1024))
    if info.get('CFBundleIdentifier') != BUNDLE_ID:
        raise ValueError('O destino não pertence ao aplicativo PDF.')


@contextmanager
def installation_lock(parent):
    path = parent / '.pdf-update.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('Bloqueio de instalação inválido.')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Keep one stable lock inode. Kernel releases its lock even after SIGKILL.
        yield
    finally:
        os.close(fd)


def journal_paths(parent, journal):
    if journal.get('schemaVersion') != 1 or not re.fullmatch('[0-9a-f]{32}', journal.get('transaction', '')):
        raise ValueError('Diário de recuperação inválido; arquivos preservados.')
    token = journal['transaction']
    if journal.get('state') not in ('prepared', 'backed-up', 'activated', 'committed'):
        raise ValueError('Estado de recuperação inválido.')
    for key in ('newIdentity', 'oldIdentity'):
        if journal.get(key) is not None and not re.fullmatch(r'\d+:\d+', journal[key]):
            raise ValueError('Identidade de recuperação inválida.')
    if journal.get('newIdentity') is None:
        raise ValueError('Falta identidade do novo bundle.')
    # No path supplied by the journal is used. Every path is derived locally.
    return (parent / 'PDF.app', parent / ('.pdf-incoming.' + token + '.app'),
            parent / ('PDF.previous.' + token + '.app'), parent / ('PDF.failed.' + token + '.app'))


def same(path, expected):
    if not os.path.lexists(path):
        return False
    return identity(path) == expected


def recover(parent, held_descriptors=()):
    path = parent / '.pdf-update.json'
    if not os.path.lexists(path):
        return None
    journal = json.loads(regular_bytes(path, 32768))
    destination, incoming, backup, failed = journal_paths(parent, journal)
    # A restarted installer must not rename a candidate that a user opened
    # after the interrupted process lost its locks. Refuse and keep the journal.
    with ExitStack() as recovery_leases:
        for candidate, expected in ((destination, journal['newIdentity']),
                                    (destination, journal['oldIdentity']),
                                    (incoming, journal['newIdentity']),
                                    (backup, journal['oldIdentity'])):
            if expected is None or not same(candidate, expected):
                continue
            resource = open_resource(candidate)
            try:
                key = check_descriptor(resource)
            finally:
                os.close(resource)
            retained = next((fd for fd in held_descriptors if check_descriptor(fd) == key), None)
            if retained is None:
                recovery_leases.enter_context(exclusive(candidate))
            else:
                validate_inherited(candidate, retained)
        return recover_locked(parent, journal, destination, incoming, backup, failed)


def recover_locked(parent, journal, destination, incoming, backup, failed):
    path = parent / '.pdf-update.json'
    if journal['state'] != 'committed':
        if same(destination, journal['newIdentity']):
            move_new(destination, failed, journal['newIdentity'])
            sync_directory(parent)
        elif os.path.lexists(destination) and not same(destination, journal['oldIdentity']):
            raise ValueError('Destino foi alterado por outro processo; recuperação preservou todos os arquivos.')
        if journal['oldIdentity'] is not None:
            if same(backup, journal['oldIdentity']):
                if os.path.lexists(destination):
                    raise ValueError('Destino ocupado; a versão anterior permanece no backup.')
                move_new(backup, destination, journal['oldIdentity'])
                sync_directory(parent)
            elif not same(destination, journal['oldIdentity']):
                raise ValueError('A versão anterior não está no local esperado; recuperação requer inspeção.')
    else:
        if not same(destination, journal['newIdentity']):
            raise ValueError('Instalação concluída mudou de identidade; diário preservado.')
    path.unlink()
    sync_directory(parent)
    return journal['state']


def validate_product(app, descriptor):
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    environment = dict(os.environ, PDF_INSTALLATION_LOCK_FD=str(descriptor), PDF_INSTALLATION_LOCK_BUNDLE=str(app))
    python = app / 'Contents/Resources/runtime/bin/python3'
    verifier = app / 'Contents/Resources/distribution/check_runtime.py'
    deadline = app / 'Contents/Resources/distribution/run-with-timeout.py'
    subprocess.run([str(python), str(deadline), '--seconds', '600', '--', str(python), str(verifier), str(app)], check=True, env=environment, pass_fds=(descriptor,))
    subprocess.run([str(python), str(deadline), '--seconds', '300', '--',
                    str(app / 'Contents/MacOS/PDF'), '--smoke-test'], check=True, env=environment, pass_fds=(descriptor,))


def copy_regular_file(source, destination):
    # APFS clones avoid allocating another complete runtime during an update.
    # HFS+/other volumes use an ordinary copy; ENOSPC remains a real failure.
    if sys.platform == 'darwin':
        library = ctypes.CDLL(None, use_errno=True)
        clone = library.clonefile
        clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        clone.restype = ctypes.c_int
        if clone(os.fsencode(source), os.fsencode(destination), 0) == 0:
            return destination
        failure = ctypes.get_errno()
        if failure not in (errno.EXDEV, errno.ENOTSUP, errno.EINVAL, errno.ENOSYS):
            raise OSError(failure, os.strerror(failure), str(destination))
    return shutil.copy2(source, destination)


def install(distribution, parent, *, validate=None, checkpoint=lambda _: None):
    """Callables are used by the failure harness, never selected by environment/CLI."""
    distribution, parent = Path(distribution).resolve(strict=True), Path(parent).resolve(strict=True)
    manifest = verify_manifest(distribution)
    with installation_lock(parent), ExitStack() as leases:
        recover(parent)
        destination = parent / 'PDF.app'
        old_id = None
        held_descriptors = []
        if os.path.lexists(destination):
            verify_bundle_identity(destination)
            old_id = identity(destination)
            held_descriptors.append(leases.enter_context(exclusive(destination)))
        token = uuid.uuid4().hex
        incoming = parent / ('.pdf-incoming.' + token + '.app')
        # Capture our directory before copying so failure can remove only this
        # attempt's unpublished bytes, including partial copies after ENOSPC.
        incoming.mkdir(mode=0o700)
        incoming_id = identity(incoming)
        try:
            shutil.copytree(distribution / 'PDF.app', incoming, symlinks=True,
                            copy_function=copy_regular_file, dirs_exist_ok=True)
            verify_copied_bundle(incoming, manifest)
            descriptor = leases.enter_context(exclusive(incoming))
            held_descriptors.append(descriptor)
            if validate is None:
                validate_product(incoming, descriptor)
            else:
                validate(incoming)
            checkpoint('validated-staging')
            journal = {'schemaVersion': 1, 'transaction': token, 'state': 'prepared',
                       'oldIdentity': old_id, 'newIdentity': incoming_id}
            write_journal(parent, journal)
            checkpoint('prepared')
            if old_id:
                move_new(destination, parent / ('PDF.previous.' + token + '.app'), old_id)
                sync_directory(parent)
            checkpoint('backup-renamed')
            journal['state'] = 'backed-up'
            write_journal(parent, journal)
            move_new(incoming, destination, journal['newIdentity'])
            sync_directory(parent)
            checkpoint('activation-renamed')
            journal['state'] = 'activated'
            write_journal(parent, journal)
            if validate is None:
                validate_product(destination, descriptor)
            else:
                validate(destination)
            checkpoint('validated-destination')
            if not same(destination, journal['newIdentity']):
                raise ValueError('Bundle mudou durante a verificação final.')
            journal['state'] = 'committed'
            write_journal(parent, journal)
            checkpoint('committed')
            recover(parent, held_descriptors)
        except BaseException:
            # ENOSPC may prevent writing, but rollback itself only renames and
            # removes the old journal. If that also fails, the next run retries.
            recover(parent, held_descriptors)
            # Recovery succeeded (or publication never began). Do not leave a
            # multi-GB failed copy on each ordinary retry. An interrupted or
            # foreign directory is never identified by its filename alone.
            if same(incoming, incoming_id):
                shutil.rmtree(incoming)
                sync_directory(parent)
            raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('install', 'recover', 'verify'))
    parser.add_argument('--distribution', type=Path)
    parser.add_argument('--destination', type=Path, default=Path.home() / 'Applications')
    args = parser.parse_args()
    try:
        if args.operation == 'verify':
            verify_manifest(args.distribution)
        elif args.operation == 'recover':
            parent = args.destination.expanduser().resolve(strict=True)
            with installation_lock(parent):
                print('Recuperação:', recover(parent) or 'nenhuma transação pendente')
        else:
            if sys.platform != 'darwin':
                raise ValueError('O pacote binário requer macOS Apple Silicon.')
            print('Instalado e validado:', install(args.distribution, args.destination))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print('Instalação recusada: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
