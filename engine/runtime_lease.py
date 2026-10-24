"""Keep a bundle lease across Python exec and explicitly owned converter children.

Only lock identity and mode travel in the environment. Options and credentials
remain on stdin. Third-party descendants that close inherited descriptors are
not covered by this cooperative protocol.
"""
from __future__ import annotations
import fcntl
import os
from pathlib import Path
import stat
import sys

FD_KEY = 'PDF_RUNTIME_LEASE_FD'
BUNDLE_KEY = 'PDF_RUNTIME_LEASE_BUNDLE'
MODE_KEY = 'PDF_RUNTIME_LEASE_MODE'
CARRIER_KEY = 'PDF_RUNTIME_LEASE_STDERR'


def _identity(descriptor):
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_size != 0 or info.st_nlink != 1
            or info.st_uid not in (0, os.getuid()) or stat.S_IMODE(info.st_mode) & 0o222):
        raise ValueError('O bloqueio do runtime não é um recurso regular vazio e somente leitura.')
    return info.st_dev, info.st_ino


def _validate(bundle, descriptor, mode):
    if mode not in ('shared', 'exclusive'):
        raise ValueError('Modo de bloqueio do runtime inválido.')
    resource = Path(bundle) / 'Contents/Resources/installation.lock'
    expected = os.open(resource, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if _identity(expected) != _identity(descriptor):
            raise ValueError('O descritor do runtime não pertence a este bundle.')
        # A fresh shared probe distinguishes an existing exclusive lease. Never
        # downgrade the installer's EX description because of an incorrect mode.
        try:
            fcntl.flock(expected, fcntl.LOCK_SH | fcntl.LOCK_NB)
            exclusive = False
        except BlockingIOError:
            exclusive = True
        if exclusive != (mode == 'exclusive'):
            raise ValueError('O modo declarado não corresponde ao bloqueio real do runtime.')
        fcntl.flock(descriptor, (fcntl.LOCK_EX if mode == 'exclusive' else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    finally:
        os.close(expected)  # Never LOCK_UN on the inherited description.


def inherited_fds():
    values = [os.environ.get(key) for key in (FD_KEY, BUNDLE_KEY, MODE_KEY)]
    if all(value is None for value in values) and CARRIER_KEY not in os.environ:
        return ()
    descriptor, bundle, mode = values
    if (CARRIER_KEY in os.environ or not descriptor or not descriptor.isdecimal()
            or str(int(descriptor)) != descriptor or not 3 <= int(descriptor) <= 4096 or not bundle or not mode):
        raise ValueError('Ambiente de bloqueio do runtime incompleto.')
    _validate(bundle, int(descriptor), mode)
    return (int(descriptor),)


def bootstrap(arguments):
    if len(arguments) < 2 or arguments[0] not in ('--bootstrap', '--qpdf'):
        raise ValueError('A inicialização do runtime exige um componente local válido.')
    operation = arguments[0]
    own = Path(__file__).resolve(strict=True)
    bundle = own.parents[3]
    executable = Path(arguments[1]).resolve(strict=True)
    declared_bundle = os.environ.get(BUNDLE_KEY)
    mode = os.environ.get(CARRIER_KEY)
    if (own.parent.name != 'engine' or own.parent.parent.name != 'Resources'
            or own.parents[2].name != 'Contents' or bundle.suffix.lower() != '.app'
            or not declared_bundle or Path(declared_bundle).resolve(strict=True) != bundle
            or FD_KEY in os.environ or MODE_KEY in os.environ):
        raise ValueError('O inicializador não pertence ao motor deste aplicativo.')
    if operation == '--bootstrap':
        allowed = own.with_name('pdf_engine.py').resolve(strict=True)
    else:
        if arguments[2:] != ['--job-json-file=/dev/stdin']:
            raise ValueError('O verificador PDF exige suas opções pelo canal stdin privado.')
        runtime = bundle / 'Contents/Resources/runtime'
        allowed = (runtime / 'bin/qpdf' if (runtime / 'portable.json').exists()
                   else Path('/opt/homebrew/bin/qpdf')).resolve(strict=True)
    if executable != allowed or not executable.is_file():
        raise ValueError('O componente solicitado não pertence a esta instalação.')
    _validate(bundle, 2, mode)
    descriptor = fcntl.fcntl(2, fcntl.F_DUPFD, 3)
    try:
        os.set_inheritable(descriptor, True)
        # Workspace already combines logs; OCR uses /dev/null for both.
        # qpdf stdout can contain bounded structured output, so its diagnostic
        # channel remains /dev/null instead of contaminating that output.
        if operation == '--bootstrap':
            os.dup2(1, 2)
        else:
            diagnostics = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(diagnostics, 2)
            finally:
                os.close(diagnostics)
        environment = dict(os.environ)
        environment.pop(CARRIER_KEY, None)
        environment[FD_KEY] = str(descriptor)
        environment[MODE_KEY] = mode
        environment[BUNDLE_KEY] = str(bundle)
        for key in ('PDF_INSTALLATION_LOCK_FD', 'PDF_INSTALLATION_LOCK_BUNDLE', 'PDF_RUNTIME_LEASE_STDIN'):
            environment.pop(key, None)
        if operation == '--bootstrap':
            os.execve(sys.executable, [sys.executable, '-E', '-s', '-B', str(executable), *arguments[2:]], environment)
        else:
            os.execve(executable, [str(executable), *arguments[2:]], environment)
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    try:
        bootstrap(sys.argv[1:])
    except (OSError, ValueError, IndexError):
        # stderr may still be the read-only carrier. No input path, payload or
        # credential is printed when validation fails before stderr restoration.
        print('O runtime não pôde manter o bloqueio seguro do aplicativo.', flush=True)
        raise SystemExit(2)
