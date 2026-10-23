#!/usr/bin/env python3
"""Install one verified official veraPDF CLI JAR, without executing installers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.request

VERSION='1.30.3'
SHA256='4c8acbaeb16405456c8d6d76deac8cf40d94618cb4e33aedf44e51ee1b68be91'
URL=f'https://repo.maven.apache.org/maven2/org/verapdf/apps/cli/{VERSION}/cli-{VERSION}.jar'


def install(directory):
    directory=Path(directory).expanduser()
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if directory.is_symlink(): raise ValueError('O diretório do validador não pode ser um link simbólico.')
    destination=directory/f'cli-{VERSION}.jar'
    if os.path.lexists(destination):
        if destination.is_symlink() or not destination.is_file(): raise ValueError('Destino do validador não é um arquivo regular.')
        with destination.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest != SHA256: raise ValueError('O validador existente tem checksum incorreto; nenhum arquivo foi sobrescrito.')
        return destination.resolve()
    # HTTPS certificate validation stays enabled. Only the pinned bytes execute.
    descriptor, temporary=tempfile.mkstemp(prefix='.verapdf-',dir=directory)
    try:
        digest=hashlib.sha256(); total=0
        with os.fdopen(descriptor,'wb') as output, urllib.request.urlopen(URL,timeout=45) as source:
            if not source.url.startswith('https://'): raise ValueError('Redirecionamento inseguro no download do validador.')
            while chunk:=source.read(64*1024):
                total+=len(chunk)
                if total>32*1024*1024: raise ValueError('O download do validador excede 32 MB.')
                digest.update(chunk); output.write(chunk)
            output.flush(); os.fsync(output.fileno())
        if digest.hexdigest()!=SHA256: raise ValueError('Checksum SHA-256 do veraPDF incorreto. O download não será executado.')
        os.link(temporary,destination)  # atomic no-clobber, including concurrent links
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination.resolve()


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--directory',required=True)
    args=parser.parse_args()
    try: print(install(args.directory))
    except Exception as exc: parser.exit(1,f'veraPDF: {exc}\n')
