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



def publish_staging_record(parent, temporary, destination, expected_identity):
    """Atomically publish a regular marker without replacing another file.

    A hard-link would leave nlink=2 if killed before unlinking the temporary;
    use the same exclusive rename primitive as directory publication instead.
    """
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.stat(temporary.name, dir_fd=descriptor, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077
                or (info.st_dev, info.st_ino) != expected_identity):
            raise ValueError('O registro temporário mudou antes da publicação.')
        library = ctypes.CDLL(None, use_errno=True)
        if sys.platform == 'darwin':
            rename, flags = library.renameatx_np, 0x00000004  # RENAME_EXCL
        elif sys.platform.startswith('linux'):
            rename, flags = library.renameat2, 1  # RENAME_NOREPLACE
        else:
            raise OSError(errno.ENOTSUP, 'Publicação exclusiva indisponível.')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(descriptor, os.fsencode(temporary.name), descriptor, os.fsencode(destination.name), flags):
            failure = ctypes.get_errno()
            raise OSError(failure, os.strerror(failure), str(destination))
    finally:
        os.close(descriptor)


def register_staging(parent, token, incoming, checkpoint=lambda _: None):
    """Bind unpublished bytes to their inode before any multi-GB copy starts.

    Filename resemblance never authorizes cleanup. The private record must
    match this exact parent, directory and read-only runtime lease, and a new
    process must acquire both the installation and runtime locks first.
    """
    resource = incoming / 'Contents/Resources/installation.lock'
    resource.parent.mkdir(parents=True)
    fd = os.open(resource, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    os.fchmod(fd, 0o444)
    os.close(fd)
    descriptor = open_resource(incoming)
    try:
        lease_identity = ':'.join(map(str, check_descriptor(descriptor)))
    finally:
        os.close(descriptor)
    path = parent / ('.pdf-staging.' + token + '.json')
    record = {'schemaVersion': 1, 'transaction': token, 'parentIdentity': identity(parent),
              'incomingIdentity': identity(incoming), 'leaseIdentity': lease_identity}
    # Incomplete markers are never visible under the committed .json name.
    # Before publication a crash can leave only a tiny unregistered directory
    # and marker, which are preserved without blocking later installations.
    temporary = parent / ('.pdf-staging.' + token + '.pending')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    temporary_identity = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
    try:
        with os.fdopen(fd, 'wb', buffering=0) as stream:
            checkpoint('staging-marker-empty')
            data = (json.dumps(record, sort_keys=True) + '\n').encode()
            boundary = len(data) // 2
            def write_all(block):
                view = memoryview(block)
                while view:
                    written = stream.write(view)
                    if not written:
                        raise OSError(errno.EIO, 'Gravação incompleta do registro temporário.')
                    view = view[written:]
            write_all(data[:boundary])
            checkpoint('staging-marker-partial')
            write_all(data[boundary:])
            os.fsync(stream.fileno())
        sync_directory(resource.parent)
        sync_directory(incoming / 'Contents')
        sync_directory(incoming)
        publish_staging_record(parent, temporary, path, temporary_identity)
        sync_directory(parent)
    finally:
        if os.path.lexists(temporary):
            info = temporary.lstat()
            if (info.st_dev, info.st_ino) == temporary_identity:
                temporary.unlink()
    return path


def cleanup_staging(parent, held_descriptors=()):
    """Only under installation_lock; malformed/unregistered/changed items stay."""
    removed = 0
    for path in sorted(parent.glob('.pdf-staging.*.json')):
        token = path.name.removeprefix('.pdf-staging.').removesuffix('.json')
        info = path.lstat()
        if (not re.fullmatch('[0-9a-f]{32}', token) or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError('Registro da cópia temporária inseguro; todos os arquivos foram preservados.')
        record = json.loads(regular_bytes(path, 32768))
        if (record.get('schemaVersion') != 1 or record.get('transaction') != token
                or record.get('parentIdentity') != identity(parent)
                or not re.fullmatch(r'\d+:\d+', record.get('incomingIdentity', ''))
                or not re.fullmatch(r'\d+:\d+', record.get('leaseIdentity', ''))):
            raise ValueError('Registro da cópia temporária inválido; arquivos foram preservados.')
        incoming = parent / ('.pdf-incoming.' + token + '.app')
        if os.path.lexists(incoming):
            if not same(incoming, record['incomingIdentity']):
                raise ValueError('A cópia temporária mudou de identidade; arquivos foram preservados.')
            with ExitStack() as leases:
                descriptor = open_resource(incoming)
                try:
                    key = check_descriptor(descriptor)
                finally:
                    os.close(descriptor)
                if ':'.join(map(str, key)) != record['leaseIdentity']:
                    raise ValueError('O bloqueio da cópia temporária mudou; arquivos foram preservados.')
                retained = next((fd for fd in held_descriptors if check_descriptor(fd) == key), None)
                if retained is None:
                    leases.enter_context(exclusive(incoming))
                else:
                    validate_inherited(incoming, retained)
                # Check again after acquiring the lifetime lease. rmtree does
                # not follow bundle symlinks. Replacements and active apps are
                # never selected merely by a name, age or process ID.
                if not same(incoming, record['incomingIdentity']):
                    raise ValueError('A cópia temporária mudou durante a limpeza; arquivos preservados.')
                shutil.rmtree(incoming)
                sync_directory(parent)
                removed += 1
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError('O registro da cópia temporária mudou durante a limpeza.')
        path.unlink()
        sync_directory(parent)
    return removed

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
    storage = {'schemaVersion': 1, 'distributionBytes': 0, 'bundleBytes': 0,
               'distributionEntries': 1, 'bundleEntries': 0}
    for parent, directories, files in os.walk(distribution, followlinks=False):
        for name in list(directories) + files:
            path = Path(parent) / name
            relative = path.relative_to(distribution).as_posix()
            if relative == 'manifest.json':
                continue
            storage['distributionEntries'] += 1
            bundled = relative == 'PDF.app' or relative.startswith('PDF.app/')
            if bundled:
                storage['bundleEntries'] += 1
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
                storage['distributionBytes'] += info.st_size
                if bundled:
                    storage['bundleBytes'] += info.st_size
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
    # Optional only for previously delivered schema-1 packages. New packages
    # bind the pre-extraction estimate to the actual files/directories too.
    if 'storageRequirements' in manifest:
        declared = manifest['storageRequirements']
        if (not isinstance(declared, dict) or any(type(value) is not int for value in declared.values())
                or declared != storage):
            raise ValueError('A estimativa de espaço não corresponde exatamente ao pacote extraído.')
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
        cleanup_staging(parent, held_descriptors)
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
        result = recover_locked(parent, journal, destination, incoming, backup, failed)
    cleanup_staging(parent, held_descriptors)
    return result


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
            register_staging(parent, token, incoming, checkpoint=checkpoint)
            descriptor = leases.enter_context(exclusive(incoming))
            held_descriptors.append(descriptor)
            checkpoint('registered-staging')
            lease_path = incoming / 'Contents/Resources/installation.lock'
            def copy_file(source, target):
                if Path(target) == lease_path:
                    # Never replace/chmod the inode locked before copying.
                    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    try:
                        check_descriptor(source_fd)
                    finally:
                        os.close(source_fd)
                    return target
                result = copy_regular_file(source, target)
                checkpoint('copied-file')
                return result
            shutil.copytree(distribution / 'PDF.app', incoming, symlinks=True,
                            copy_function=copy_file, dirs_exist_ok=True)
            validate_inherited(incoming, descriptor)
            verify_copied_bundle(incoming, manifest)
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
        except BaseException as failure:
            # ENOSPC may prevent writing, but rollback itself only renames and
            # removes the old journal. If that also fails, the next run retries.
            try:
                recover(parent, held_descriptors)
            except Exception as recovery_error:
                failure.add_note('A recuperação também foi recusada; arquivos preservados: ' + str(recovery_error))
                raise failure
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
