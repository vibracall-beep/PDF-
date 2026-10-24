#!/usr/bin/env python3
"""Bind original cross-OS GUI artifacts to an unchanged installed binary.

This verifies capture completeness and own-window AX structure, not human visual
review or VoiceOver interaction. Capture runs outside the dependency sandbox;
the portable runtime has its own preceding isolation gate. No app is rebuilt.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import portable_compatibility as portable

ROOT = Path(__file__).resolve().parent.parent
require = portable.require
STATES = ('', 'leitor', 'abas', 'lado-a-lado', 'anotacoes', 'recuperacao',
          'personalizar', 'ferramentas', 'navegacao', 'opcoes-leitura', 'arquivos',
          'escuro', 'lista', 'configuracao-ferramenta', 'fluxo-lote',
          'assinatura-digital', 'verificar-assinaturas', 'validar-pdfa', 'auditar-pdfua',
          'atalhos', 'perfis', 'paleta', 'editor-conteudo', 'revisao-ocr', 'biblioteca',
          'corrigir-acessibilidade', 'solicitar-assinaturas', 'automacao',
          'producao-print-preflight', 'producao-bates', 'producao-measure', 'producao-pdfx')
PNG_NAMES = tuple('PDF-preview' + ('.' + state if state else '') + '.png' for state in STATES)
AX_NAMES = tuple('PDF-preview' + ('.' + state if state else '') + '.accessibility.json'
                 for state in ('', 'leitor', 'lado-a-lado', 'anotacoes', 'biblioteca', 'corrigir-acessibilidade'))
OCR_PDF = 'PDF-preview.revisao-ocr.source.pdf'
OCR_JSON = 'PDF-preview.revisao-ocr.analysis.json'
ORIGINALS = dict.fromkeys(PNG_NAMES, 64 * 1024 ** 2) | dict.fromkeys(AX_NAMES, 16 * 1024 ** 2) | {
    OCR_PDF: 64 * 1024 ** 2, OCR_JSON: 32 * 1024 ** 2}
BEFORE = 'PDF-cross-gui-before.json'
RECEIPT = 'PDF-cross-gui.json'
CAPTURE_LOG = 'PDF-cross-gui-capture.log'
VALIDATION_LOG = 'PDF-cross-gui-validation.log'
GUI_CONTENTS = dict(ORIGINALS, **{BEFORE: 32768, RECEIPT: 32768,
                                CAPTURE_LOG: 64 * 1024 ** 2, VALIDATION_LOG: 16 * 1024 ** 2})
BASE_CONTENTS = {'PDF-cross-origin.json', 'PDF-cross-verified.json', 'PDF-cross-isolation.log'}
SCRIPT_NAMES = ('run-with-timeout.py', 'check_preview_artifacts.py', 'check_accessibility_report.py', 'binary_update.py')
IDENTITY_KEYS = ('repository', 'sourceRunID', 'sourceCommit', 'sourceArtifactID', 'archiveSHA256', 'archiveBytes', 'manifestSHA256')
BINARY_KEYS = ('PDF.app/Contents/MacOS/PDF', 'PDF.app/Contents/Info.plist')
MAX_TOTAL = 512 * 1024 ** 2


def hashed_file(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit, 'Expected a nonempty bounded regular evidence file.')
        digest = hashlib.sha256()
        count = 0
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            count += len(block)
            require(count <= limit, 'Evidence grew beyond its bound.')
            digest.update(block)
        after = os.fstat(fd)
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (count, after.st_mtime_ns, after.st_ctime_ns) and count == after.st_size,
                'Evidence changed during hashing.')
    return {'bytes': count, 'sha256': digest.hexdigest()}


def exact_names(directory, expected):
    require(not directory.is_symlink() and directory.is_dir(), 'Evidence directory must be real.')
    require({entry.name for entry in directory.iterdir()} == set(expected),
            'Cross GUI evidence is missing files or contains unexpected files.')


def script_module(source, name):
    # Only the authenticated checkout (during capture) or this controller's
    # checked-in validators (during delivery) is imported, never artifact code.
    scripts = source / 'scripts'
    old = sys.path[:]
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location('_cross_' + name, scripts / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = old


def source_identity(source, commit):
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True, timeout=15).strip()
    require(actual == commit, 'GUI scripts are not from the authenticated source commit.')
    subprocess.run(['git', '-C', str(source), 'diff', '--quiet', 'HEAD', '--'], check=True, timeout=15)
    return {name: hashed_file(source / 'scripts' / name, 1024 ** 2) for name in SCRIPT_NAMES}


def bundle_identity(app, manifest, source):
    require(not app.is_symlink() and app.is_dir(), 'Installed app must be a real bundle.')
    updater = script_module(source, 'binary_update')
    updater.verify_bundle_identity(app)
    updater.verify_copied_bundle(app, manifest)
    result = {}
    for key in BINARY_KEYS:
        entry = manifest['files'].get(key, {})
        require(entry.get('type') == 'file', 'Installed binary identity is absent from the source manifest.')
        measured = hashed_file(app / key.removeprefix('PDF.app/'), portable.MAX_ARCHIVE)
        require(measured == {'bytes': entry.get('size'), 'sha256': entry.get('sha256')},
                'Installed GUI differs from the exact approved archive.')
        result[key] = measured
    return result


def capture_binding(source, app, archive, manifest, verified):
    require(manifest.get('commit') == verified['sourceCommit']
            and portable.manifest_digest(manifest) == verified['manifestSHA256'],
            'GUI manifest differs from the authenticated complete archive manifest.')
    scripts = source_identity(source, verified['sourceCommit'])
    measured = hashed_file(archive, portable.MAX_ARCHIVE)
    require(measured == {'bytes': verified['archiveBytes'], 'sha256': verified['archiveSHA256']},
            'The source tar changed before or after GUI capture.')
    return dict(schemaVersion=1, **{key: verified[key] for key in IDENTITY_KEYS},
                sourceScripts=scripts, installedBinary=bundle_identity(app, manifest, source),
                captureDeadlineSeconds=300, captureAttempts=1, guiOutsideDependencySandbox=True,
                dependencyIsolationSeparate=True, rebuiltOnDestination=False)


def prepare(directory, source, app, archive, manifest, verified):
    # A fresh inventory and exclusive marker prevent reusing a previous capture.
    exact_names(directory, BASE_CONTENTS)
    binding = capture_binding(source, app, archive, manifest, verified)
    portable.write_json(directory / BEFORE, binding)
    return binding


def original_records(directory):
    records = {name: hashed_file(directory / name, limit) for name, limit in ORIGINALS.items()}
    require(sum(record['bytes'] for record in records.values()) <= MAX_TOTAL, 'GUI originals exceed the aggregate bound.')
    return records


def validate_ocr(analysis, source_sha):
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)
    require(type(analysis.get('version')) is int and analysis['version'] == 1
            and analysis.get('source_sha256') == source_sha and analysis.get('backend') == 'tesseract'
            and type(analysis.get('page_count')) is int and 0 < analysis['page_count'] <= 100000
            and analysis.get('review_required') is True, 'Invalid original OCR provenance/schema.')
    language = analysis.get('language')
    settings = analysis.get('settings')
    require(isinstance(language, str) and re.fullmatch(r'[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*', language)
            and isinstance(settings, dict) and settings.get('language') == language
            and type(settings.get('ocr_dpi')) is int and 120 <= settings['ocr_dpi'] <= 400
            and type(settings.get('ocr_psm')) is int and 3 <= settings['ocr_psm'] <= 13
            and finite(settings.get('min_confidence')) and 0 <= settings['min_confidence'] <= 100
            and ('ocr_deskew' not in settings or type(settings['ocr_deskew']) is bool), 'Invalid original OCR settings.')
    pages = analysis.get('pages'); words = analysis.get('words')
    require(isinstance(pages, list) and 0 < len(pages) <= analysis['page_count']
            and isinstance(words, list) and 0 < len(words) <= 50000, 'Invalid original OCR observations.')
    bounds = {}
    for page in pages:
        require(isinstance(page, dict) and type(page.get('page')) is int
                and 1 <= page['page'] <= analysis['page_count'] and page['page'] not in bounds
                and finite(page.get('width')) and page['width'] > 0
                and finite(page.get('height')) and page['height'] > 0, 'Invalid original OCR page geometry.')
        bounds[page['page']] = (page['width'], page['height'])
    identifiers = set(); text_bytes = 0
    for word in words:
        require(isinstance(word, dict) and isinstance(word.get('id'), str)
                and re.fullmatch('[0-9a-f]{64}', word['id']) and word['id'] not in identifiers
                and type(word.get('page')) is int and word['page'] in bounds
                and isinstance(word.get('text'), str) and bool(word['text'])
                and finite(word.get('confidence')) and 0 <= word['confidence'] <= 1,
                'Invalid original OCR word identity/text/confidence.')
        rect = word.get('rect'); width, height = bounds[word['page']]
        require(isinstance(rect, list) and len(rect) == 4 and all(finite(value) for value in rect)
                and 0 <= rect[0] < rect[2] <= width and 0 <= rect[1] < rect[3] <= height,
                'Original OCR word is outside its page.')
        identifiers.add(word['id']); text_bytes += len(word['text'].encode('utf-8'))
    require(text_bytes <= 8 * 1024 ** 2, 'Original OCR text exceeds its bound.')
    content = {key: value for key, value in analysis.items() if key != 'review_sha256'}
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    require(analysis.get('review_sha256') == digest, 'Original OCR canonical report hash mismatch.')


def validate_originals(directory, source=ROOT):
    records = original_records(directory)
    checker = script_module(source, 'check_preview_artifacts')
    require(tuple(checker.PREVIEW_STATES) == STATES and set(checker.REQUIRED_AX) == set(AX_NAMES),
            'The authenticated preview validator has a different capture contract.')
    # Reports may contain arbitrary strings. Do not echo them in delivery logs.
    with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
        require(checker.check_directory(directory), 'PNG or own-window AX structure failed validation.')
    pdf = portable.regular_bytes(directory / OCR_PDF, ORIGINALS[OCR_PDF])
    analysis = portable.regular_json(directory / OCR_JSON, ORIGINALS[OCR_JSON])
    require(pdf.startswith(b'%PDF-'), 'Original OCR source is not a PDF.')
    validate_ocr(analysis, records[OCR_PDF]['sha256'])
    require(original_records(directory) == records, 'Original GUI evidence changed during validation.')
    return records


def finish(directory, source, app, archive, manifest, verified):
    exact_names(directory, BASE_CONTENTS | {BEFORE, CAPTURE_LOG, VALIDATION_LOG} | set(ORIGINALS))
    before = portable.regular_json(directory / BEFORE, 32768)
    require(before == capture_binding(source, app, archive, manifest, verified),
            'Source scripts, installed app or archive changed during GUI capture.')
    records = validate_originals(directory, source)
    logs = {name: hashed_file(directory / name, GUI_CONTENTS[name]) for name in (CAPTURE_LOG, VALIDATION_LOG)}
    result = dict(before, installedBundleManifestMatchedBeforeAndAfter=True, archiveUnchanged=True,
                  guiCapturePassed=True, pngCount=32, ownWindowAXCount=6, originalOCRFileCount=2,
                  humanVisualReview=False, humanVoiceOverTested=False, originals=records, logs=logs,
                  beforeSHA256=hashed_file(directory / BEFORE, 32768)['sha256'])
    portable.write_json(directory / RECEIPT, result)
    return result


def verify_receipt(directory, verified, manifest=None):
    expected = BASE_CONTENTS | set(GUI_CONTENTS)
    if (directory / 'PDF-cross-platform.json').exists(): expected.add('PDF-cross-platform.json')
    exact_names(directory, expected)
    receipt = portable.regular_json(directory / RECEIPT, 32768)
    before = portable.regular_json(directory / BEFORE, 32768)
    require(set(before) == set(IDENTITY_KEYS) | {'schemaVersion', 'sourceScripts', 'installedBinary',
                'captureDeadlineSeconds', 'captureAttempts', 'guiOutsideDependencySandbox',
                'dependencyIsolationSeparate', 'rebuiltOnDestination'}
            and all(receipt.get(key) == value for key, value in before.items())
            and receipt.get('beforeSHA256') == hashed_file(directory / BEFORE, 32768)['sha256'],
            'GUI before/after evidence disagrees.')
    require(all(receipt.get(key) == verified[key] for key in IDENTITY_KEYS), 'GUI evidence belongs to a different source binary.')
    for key in ('installedBundleManifestMatchedBeforeAndAfter', 'archiveUnchanged', 'guiCapturePassed',
                'guiOutsideDependencySandbox', 'dependencyIsolationSeparate'):
        require(receipt.get(key) is True, 'Missing mandatory GUI check: ' + key)
    for key, value in (('schemaVersion', 1), ('captureDeadlineSeconds', 300), ('captureAttempts', 1),
                       ('pngCount', 32), ('ownWindowAXCount', 6), ('originalOCRFileCount', 2)):
        require(type(receipt.get(key)) is int and receipt[key] == value, 'Invalid GUI capture contract: ' + key)
    for key in ('rebuiltOnDestination', 'humanVisualReview', 'humanVoiceOverTested'):
        require(receipt.get(key) is False, 'Unsupported GUI claim: ' + key)
    scripts = receipt.get('sourceScripts')
    binary = receipt.get('installedBinary')
    require(isinstance(scripts, dict) and set(scripts) == set(SCRIPT_NAMES)
            and isinstance(binary, dict) and set(binary) == set(BINARY_KEYS), 'Incomplete GUI source/binary identity.')
    for record in list(scripts.values()) + list(binary.values()):
        require(isinstance(record, dict) and set(record) == {'bytes', 'sha256'}
                and type(record['bytes']) is int and 0 < record['bytes'] <= portable.MAX_ARCHIVE
                and isinstance(record['sha256'], str) and re.fullmatch('[0-9a-f]{64}', record['sha256']),
                'Invalid GUI source/binary fingerprint.')
    if manifest is not None:
        require(portable.manifest_digest(manifest) == receipt['manifestSHA256'],
                'GUI receipt differs from the authenticated complete tar manifest.')
        for key in BINARY_KEYS:
            entry = manifest.get('files', {}).get(key, {})
            require(entry.get('type') == 'file' and binary[key] == {'bytes': entry.get('size'), 'sha256': entry.get('sha256')},
                    'GUI executable/plist differs from the authenticated tar manifest.')
    require(receipt.get('originals') == validate_originals(directory), 'Captured GUI originals differ from their receipt.')
    require(receipt.get('logs') == {name: hashed_file(directory / name, GUI_CONTENTS[name])
                                   for name in (CAPTURE_LOG, VALIDATION_LOG)}, 'GUI capture/validation log changed.')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'finish'))
    for name in ('directory', 'source', 'app', 'archive', 'manifest', 'verified'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        operation = prepare if args.operation == 'prepare' else finish
        operation(args.directory, args.source.resolve(strict=True), args.app, args.archive,
                  portable.regular_json(args.manifest), portable.regular_json(args.verified, 32768))
        print('Cross-OS GUI ' + args.operation + ' verified; original artifacts retained, no human review claimed.')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Cross GUI evidence rejected: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
