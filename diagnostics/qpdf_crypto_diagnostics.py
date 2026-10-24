#!/usr/bin/env python3
"""Measure OpenSSL-provider discovery using only known synthetic PDFKit inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
sys.path.insert(0, str(ROOT / 'scripts'))
from owned_process import OwnedProcess, cooperative_signals
from portable_isolation import candidate_profile
from process_ownership_diagnostics import production_profile
from private_ipc_diagnostics import manifest_identity
from assemble_qpdf_runtime import assemble
from package_binary import macho

# These credentials protect generated diagnostic inputs only. They never enter
# argv, environment, retained job files, stdout or an unredacted stderr log.
READER = 'qpdf-synthetic-reader-123'
OWNER = 'qpdf-synthetic-owner-456'
WRONG = 'qpdf-synthetic-incorrect'
CREDENTIALS = (READER, OWNER, WRONG)


def redact(data):
    text = data.decode('utf-8', errors='replace')
    for credential in sorted(CREDENTIALS, key=len, reverse=True):
        text = text.replace(credential, '[redacted synthetic credential]')
    return text


def completed(record, codes):
    return (type(record.get('exit')) is int and record['exit'] in codes
            and record.get('errorType') is None and record.get('cleanupConfirmed') is True)


def legacy_failure(record):
    return completed(record, (2,)) and 'unable to load openssl legacy provider' in record.get('stderr', '').lower()


def encryption_summary(data):
    root = json.loads(data)
    if type(root.get('version')) is not int or root['version'] != 2 or not isinstance(root.get('encrypt'), dict):
        raise ValueError('The qpdf encryption receipt has no supported schema.')
    encrypted = root['encrypt']; parameters = encrypted.get('parameters')
    if not isinstance(parameters, dict): raise ValueError('The encryption parameters are absent.')
    result = {}
    for key in ('encrypted', 'userpasswordmatched', 'ownerpasswordmatched'):
        if type(encrypted.get(key)) is not bool: raise ValueError('The encryption flags have invalid types.')
        result[key] = encrypted[key]
    result['parameters'] = {}
    for key in ('bits', 'V', 'R', 'P'):
        if type(parameters.get(key)) is not int: raise ValueError('The encryption integers have invalid types.')
        result['parameters'][key] = parameters[key]
    for key in ('method', 'streammethod', 'stringmethod', 'filemethod'):
        if parameters.get(key) not in ('none', 'RC4', 'AES', 'AESv2', 'AESv3', 'mixed'):
            raise ValueError('The cipher name is not in the diagnostic allowlist.')
        result['parameters'][key] = parameters[key]
    # In particular, never retain recovered passwords or unrestricted qpdf JSON.
    return result


def aes256_expected(summary):
    parameters = summary.get('parameters', {})
    return (summary.get('encrypted') is True and summary.get('userpasswordmatched') is True
            and summary.get('ownerpasswordmatched') is False
            and parameters.get('bits') == 256 and parameters.get('V') == 5 and parameters.get('R') == 6
            and all(parameters.get(key) == 'AESv3' for key in ('method', 'streammethod', 'stringmethod', 'filemethod')))


class Measurement:
    def __init__(self, output):
        self.output = output
        self.children = []

    def run(self, name, arguments, *, payload=b'', environment=None, profile=None, seconds=30):
        prefix = [] if profile is None else ['/usr/bin/sandbox-exec', '-p', profile]
        record = {'exit': None, 'errorType': None, 'cleanupConfirmed': False, 'sandboxed': profile is not None}
        self.children.append(record)
        process = None
        primary = None
        stdout = b''
        try:
            # A private anonymous regular file matches the app's job transport
            # and cannot leave credentials in the retained artifact directory.
            with tempfile.TemporaryFile(mode='w+b') as stdin:
                stdin.write(payload); stdin.flush(); stdin.seek(0)
                process = OwnedProcess([*prefix, *map(str, arguments)], stdin=stdin,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, grace_seconds=10)
                record['pid'] = process.pid
                stdout, stderr = process.communicate(seconds, output_limit=65536)
                record.update(exit=process.returncode, stdoutBytes=len(stdout), stderr=redact(stderr))
        except BaseException as error:
            primary = error
            record['errorType'] = type(error).__name__
            raise
        finally:
            try:
                if process is not None:
                    try: process.close()
                    except BaseException as error:
                        record['cleanupErrorType'] = type(error).__name__
                        if primary is None: raise
                        primary.add_note('Diagnostic child cleanup failed: ' + type(error).__name__)
                    finally: record['cleanupConfirmed'] = process.cleanup_confirmed
            finally:
                (self.output / (name + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        return record, stdout

    def job(self, name, executable, job, environment, profile=None):
        record, stdout = self.run(name, [executable, '--job-json-file=/dev/stdin'],
            payload=json.dumps(job, sort_keys=True).encode(), environment=environment, profile=profile)
        record['executableSHA256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
        record['inputSHA256'] = hashlib.sha256(Path(job['inputFile']).read_bytes()).hexdigest()
        return record, stdout


def diagnose(args):
    if sys.platform != 'darwin': raise ValueError('The real Apple SDK and sandbox are required.')
    os.umask(0o077)
    output = args.output.absolute(); output.mkdir(mode=0o700)
    measurement = Measurement(output)
    report = {'schemaVersion': 1, 'kind': 'synthetic-qpdf-crypto-diagnosis', 'productApproved': False,
              'commit': os.environ.get('GITHUB_SHA'), 'complete': False, 'causalProofPassed': False,
              'cases': {}, 'limitations': ['A raw PDFKit warning remains a warning and never approves a product output.',
                                          'Only qpdf and its actual dependency closure are assembled.']}
    workspace = Path(tempfile.mkdtemp(prefix='pdf-qcrypto-', dir='/tmp')).resolve(strict=True)
    report['workspace'] = str(workspace)
    try:
        fixture = args.fixture.resolve(strict=True)
        generated, _ = measurement.run('generate-fixtures', [fixture, output / 'fixtures'], payload=(READER + '\n').encode())
        if not completed(generated, (0,)): raise RuntimeError('The independent PDFKit fixture failed.')
        report['fixture'] = json.loads((output / 'fixtures/fixture.json').read_text())
        plain, protected = output / 'fixtures/plain.pdf', output / 'fixtures/protected.pdf'
        assembly = assemble(workspace / 'build')
        original = assembly['root']; moved = workspace / 'moved runtime'
        original.rename(moved)
        paths = {key: moved / assembly[key].relative_to(original) for key in ('qpdf', 'wrapper', 'crypto', 'modules')}
        shutil.copyfile(moved / 'manifest.json', output / 'runtime-manifest.json')
        shutil.copyfile(moved / 'provenance.json', output / 'runtime-provenance.json')
        before = manifest_identity(moved)
        report['runtime'] = {'moved': True, 'sourceAbsent': not original.exists(), 'manifestSHA256Before': before,
            'crypto': str(paths['crypto'].relative_to(moved)), 'modules': str(paths['modules'].relative_to(moved)),
            'cryptoSHA256': hashlib.sha256(paths['crypto'].read_bytes()).hexdigest(),
            'legacySHA256': hashlib.sha256((paths['modules'] / 'legacy.dylib').read_bytes()).hexdigest()}
        ipc = workspace / 'ipc'; ipc.mkdir(mode=0o700)
        home = ipc / 'home'; home.mkdir(mode=0o700)
        cache = ipc / 'cache'; cache.mkdir(mode=0o700)
        empty_modules = workspace / 'empty-modules'; empty_modules.mkdir(mode=0o700)
        profile = candidate_profile(production_profile(), ipc, Path.home())
        (output / 'sandbox.sb').write_text(profile)
        report['sandboxSHA256'] = hashlib.sha256(profile.encode()).hexdigest()
        environment = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(home), 'LC_ALL': 'C',
                       'TMPDIR': str(ipc) + '/', 'MAC_CHROMIUM_TMPDIR': str(ipc),
                       'OSL_SOCKET_PATH': str(ipc), 'XDG_CACHE_HOME': str(cache)}
        candidate = dict(environment, OPENSSL_MODULES=str(paths['modules']))
        missing = dict(environment, OPENSSL_MODULES=str(empty_modules))
        source_status = {}
        for name, source, password in [('plain', plain, ''), ('protected', protected, READER)]:
            job = {'inputFile': str(source), 'password': password, 'check': ''}
            result, _ = measurement.job('source-' + name, assembly['sourceQPDF'], job, environment)
            report['cases']['source-' + name] = result
            if not completed(result, (0, 3)): raise RuntimeError('Original qpdf cannot read the synthetic reference.')
            source_status[name] = result['exit']
        report['rawPDFKitReferenceStatuses'] = source_status
        for transport in ('qpdf', 'wrapper'):
            executable = paths[transport]
            plain_job = {'inputFile': str(plain), 'check': ''}
            protected_job = {'inputFile': str(protected), 'password': READER, 'check': ''}
            scenarios = [('plain-isolated', plain_job, environment, profile),
                         ('protected-outside', protected_job, environment, None),
                         ('protected-baseline', protected_job, environment, profile),
                         ('protected-modules', protected_job, candidate, profile),
                         ('protected-empty-modules', protected_job, missing, profile),
                         ('protected-restored', protected_job, candidate, profile),
                         ('protected-unset-after', protected_job, environment, profile),
                         ('wrong-password', dict(protected_job, password=WRONG), candidate, profile)]
            report['cases'][transport] = {}
            for label, job, env, policy in scenarios:
                result, _ = measurement.job(transport + '-' + label, executable, job, env, policy)
                report['cases'][transport][label] = result
            result, data = measurement.job(transport + '-encryption', executable,
                {'inputFile': str(protected), 'password': READER, 'json': '2', 'jsonKey': ['encrypt']}, candidate, profile)
            if completed(result, (0, 3)): result['encryption'] = encryption_summary(data)
            report['cases'][transport]['encryption'] = result
        # Produce clean synthetic bytes before the strict AES-256 control. A
        # warning on raw PDFKit input is reported; the rewritten output must0.
        normalized = output / 'normalized-plain.pdf'
        normalize, _ = measurement.job('normalize-plain', paths['wrapper'],
            {'inputFile': str(plain), 'outputFile': str(normalized)}, candidate, profile)
        report['normalization'] = normalize
        clean, _ = measurement.job('normalized-check', paths['wrapper'], {'inputFile': str(normalized), 'check': ''}, candidate, profile)
        report['normalizedCheck'] = clean
        if not completed(normalize, (0, 3)) or not completed(clean, (0,)):
            raise RuntimeError('The independent AES control requires a structurally valid plain input.')
        aes = output / 'aes256.pdf'
        encrypted, _ = measurement.job('aes256-create', paths['wrapper'], {'inputFile': str(normalized), 'outputFile': str(aes),
            'encrypt': {'userPassword': READER, 'ownerPassword': OWNER, '256bit': {}}}, candidate, profile)
        report['aes256'] = {'create': encrypted}
        for label, password, env in [('baseline', READER, environment), ('candidate', READER, candidate), ('wrong-password', WRONG, candidate)]:
            checked, _ = measurement.job('aes256-' + label, paths['wrapper'], {'inputFile': str(aes), 'password': password, 'check': ''}, env, profile)
            report['aes256'][label] = checked
        queried, data = measurement.job('aes256-encryption', paths['wrapper'],
            {'inputFile': str(aes), 'password': READER, 'json': '2', 'jsonKey': ['encrypt']}, candidate, profile)
        if completed(queried, (0,)): queried['encryption'] = encryption_summary(data)
        report['aes256']['encryption'] = queried
        inspected, _ = measurement.run('aes256-pdfkit-inspect', [fixture, '--inspect', aes, output / 'aes256-inspection.json'],
                                        payload=(READER + '\n').encode())
        report['aes256']['independentInspection'] = inspected
        if completed(inspected, (0,)):
            report['aes256']['pdfkit'] = json.loads((output / 'aes256-inspection.json').read_text())
        after = manifest_identity(moved)
        report['runtime']['manifestSHA256After'] = after
        report['runtime']['bytesUnchanged'] = before == after
        for index, binary in enumerate(path for path in moved.rglob('*') if macho(path)):
            signed, _ = measurement.run('signature-after-' + str(index), ['/usr/bin/codesign', '--verify', '--strict', binary])
            if not completed(signed, (0,)): raise RuntimeError('The diagnostic runtime signature changed.')
        report['runtime']['signaturesAfterVerified'] = True
        proof = True
        for transport in ('qpdf', 'wrapper'):
            cases = report['cases'][transport]
            compared = [cases[key] for key in ('protected-baseline', 'protected-modules', 'protected-empty-modules', 'protected-restored', 'protected-unset-after')]
            proof = (proof and completed(cases['plain-isolated'], (source_status['plain'],))
                and all(legacy_failure(cases[key]) for key in ('protected-baseline', 'protected-empty-modules', 'protected-unset-after'))
                and all(completed(cases[key], (source_status['protected'],)) for key in ('protected-modules', 'protected-restored'))
                and completed(cases['wrong-password'], (2,)) and 'invalid password' in cases['wrong-password']['stderr'].lower()
                and len({case['executableSHA256'] for case in compared}) == 1
                and len({case['inputSHA256'] for case in compared}) == 1)
        aes_report = report['aes256']
        report['causalProofPassed'] = bool(proof and before == after
            and all(completed(aes_report[key], (0,)) for key in ('create', 'baseline', 'candidate', 'encryption', 'independentInspection'))
            and completed(aes_report['wrong-password'], (2,))
            and 'invalid password' in aes_report['wrong-password']['stderr'].lower()
            and aes256_expected(aes_report['encryption'].get('encryption', {})))
        report['complete'] = True
    except BaseException as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        report['allChildCleanupConfirmed'] = all(child['cleanupConfirmed'] for child in measurement.children)
        if report['complete'] and report['allChildCleanupConfirmed']:
            shutil.rmtree(workspace); report['workspaceRemoved'] = True
        else:
            report['workspacePreserved'] = True
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print('FINAL QPDF CRYPTO DIAGNOSTIC REPORT', json.dumps(report, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with cooperative_signals(): diagnose(args)


if __name__ == '__main__': main()
