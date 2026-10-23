#!/usr/bin/env python3
"""Filesystem operations used by the installer; destinations are never replaced."""
import argparse
import ctypes
import errno
import os
from pathlib import Path
import stat
import sys


def identity(path):
    value = os.lstat(path)
    if not stat.S_ISDIR(value.st_mode):
        raise ValueError('O caminho não é um diretório regular: ' + str(path))
    return f'{value.st_dev}:{value.st_ino}'


def move_new(source, destination, expected):
    """Rename a known directory without replacing a file, directory or symlink."""
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if source.name in ('', '.', '..') or destination.name in ('', '.', '..'):
        raise ValueError('Caminho de publicação inválido.')
    flags = os.O_RDONLY | os.O_DIRECTORY
    flags |= getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
    source_fd = os.open(source.parent, flags)
    try:
        destination_fd = os.open(destination.parent, flags)
        try:
            info = os.stat(source.name, dir_fd=source_fd, follow_symlinks=False)
            actual = f'{info.st_dev}:{info.st_ino}'
            if not stat.S_ISDIR(info.st_mode) or actual != expected:
                raise ValueError('O diretório mudou durante a instalação; ele foi preservado.')
            library = ctypes.CDLL(None, use_errno=True)
            if sys.platform == 'darwin':
                rename = library.renameatx_np
                rename_flags = 0x00000004  # RENAME_EXCL, documented by renameatx_np(2).
            elif sys.platform.startswith('linux'):
                rename = library.renameat2
                rename_flags = 1  # RENAME_NOREPLACE.
            else:
                raise OSError(errno.ENOTSUP, 'Publicação exclusiva não suportada nesta plataforma.')
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            if rename(source_fd, os.fsencode(source.name), destination_fd, os.fsencode(destination.name), rename_flags):
                value = ctypes.get_errno()
                raise OSError(value, os.strerror(value), str(destination))
            return actual
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='operation', required=True)
    inspect = subparsers.add_parser('identity')
    inspect.add_argument('path')
    move = subparsers.add_parser('move')
    move.add_argument('source')
    move.add_argument('destination')
    move.add_argument('--expected', required=True)
    args = parser.parse_args()
    try:
        if args.operation == 'identity':
            print(identity(args.path))
        else:
            print(move_new(args.source, args.destination, args.expected))
    except (OSError, ValueError, AttributeError) as error:
        print('Falha na operação de instalação: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
