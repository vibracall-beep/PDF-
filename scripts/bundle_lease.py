#!/usr/bin/env python3
"""Cooperative bundle lifetime lease; close descriptors, never unlock a shared description."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat

RESOURCE = 'Contents/Resources/installation.lock'


def check_descriptor(descriptor):
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_size != 0 or info.st_nlink != 1
            or info.st_uid not in (0, os.getuid()) or stat.S_IMODE(info.st_mode) & 0o222):
        raise ValueError('O recurso de bloqueio deve ser regular, vazio e somente leitura.')
    return info.st_dev, info.st_ino


def open_resource(app):
    try:
        descriptor = os.open(Path(app) / RESOURCE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError as error:
        raise ValueError('Esta versão anterior não possui o protocolo de atualização segura. '
                         'Instale em um diretório novo; o aplicativo anterior e suas preferências serão preservados.') from error
    try:
        check_descriptor(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def validate_inherited(app, descriptor):
    if descriptor < 3 or descriptor > 4096:
        raise ValueError('Descritor de bloqueio inválido.')
    expected = open_resource(app)
    try:
        if check_descriptor(descriptor) != check_descriptor(expected):
            raise ValueError('O bloqueio herdado não pertence a este bundle.')
        # The same open-file description remains locked across exec. Never
        # LOCK_UN here: that would release the installer's lease as well.
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('O PDF está em execução. Feche o aplicativo antes de atualizar; nenhuma sessão foi encerrada.') from error
        return descriptor
    finally:
        os.close(expected)


@contextmanager
def exclusive(app):
    descriptor = open_resource(app)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('O PDF está em execução. Feche o aplicativo antes de atualizar; nenhuma sessão foi encerrada.') from error
        yield descriptor
    finally:
        os.close(descriptor)


def inherited_from_environment():
    value = os.environ.get('PDF_INSTALLATION_LOCK_FD')
    app = os.environ.get('PDF_INSTALLATION_LOCK_BUNDLE')
    if value is None and app is None:
        return ()
    if not value or not value.isdecimal() or not app:
        raise ValueError('Ambiente de bloqueio herdado incompleto.')
    return (validate_inherited(app, int(value)),)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True)
    parser.add_argument('--fd', type=int, required=True)
    args = parser.parse_args()
    try:
        validate_inherited(args.app, args.fd)
        return 0
    except (OSError, ValueError) as error:
        parser.exit(1, 'Atualização recusada: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
