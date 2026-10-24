"""Diagnostic-only private Unix IPC experiment; never changes product policy."""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

from assemble_ipc_runtime import assemble
from portable_office_diagnostics import (ROOT, causal_denial, conversion, measure,
    office_socket, prepare_office_fixture, probe_expectation)
from package_binary import contained_link


def private_profile(base, root):
    root = Path(root)
    info = root.lstat()
    if (root != root.resolve(strict=True) or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700
            or len(os.fsencode(root)) > 50):
        raise ValueError('The IPC exception requires a short, canonical private directory.')
    # LO 26.8.1.1 sal/osl/unx/pipe.cxx tests W_OK on these roots before using
    # OSL_SOCKET_PATH, which is a raw system path, not a file URL. Whether
    # Seatbelt's literal denial produces that behavior is measured, not assumed.
    roots = sorted({str(Path(path).resolve(strict=True)) for path in ('/tmp', '/var/tmp')})
    return (base + '\n(deny file-write* ' + ' '.join('(literal ' + json.dumps(path) + ')' for path in roots)
            + ')\n(allow network-bind network-inbound network-outbound (subpath '
            + json.dumps(str(root)) + '))\n')


def access_expectation(result, data, writable):
    return (type(result.get('exit')) is int and result['exit'] == 0 and result.get('stoppedBecause') is None
            and isinstance(data, dict) and set(data) == {'writable', 'accessErrno'}
            and type(data['writable']) is bool and type(data['accessErrno']) is int
            and data['writable'] is writable
            and (data['accessErrno'] == 0 if writable else data['accessErrno'] in (errno.EACCES, errno.EPERM)))


def manifest_identity(runtime):
    """Check the exact original manifest without rewriting it during the test."""
    manifest_bytes = (runtime / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    actual = {}
    for path in sorted(runtime.rglob('*')):
        name = path.relative_to(runtime).as_posix()
        if name == 'manifest.json': continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path); contained_link(path, target, runtime)
            actual[name] = {'type': 'symlink', 'target': target}
        elif stat.S_ISREG(info.st_mode):
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
            actual[name] = {'type': 'file', 'size': info.st_size, 'mode': stat.S_IMODE(info.st_mode), 'sha256': digest.hexdigest()}
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Special file appeared inside the diagnostic runtime.')
    if manifest['files'] != actual:
        raise ValueError('The runtime bytes differ from the original signed-build manifest.')
    return hashlib.sha256(manifest_bytes).hexdigest()


def worker_expectation(result, data, mode):
    if (mode not in ('multiprocessing', 'browser') or type(result.get('exit')) is not int
            or result['exit'] != 0 or result.get('stoppedBecause') is not None
            or not isinstance(data, dict) or type(data.get('schemaVersion')) is not int
            or data['schemaVersion'] != 1 or data.get('passed') is not True or data.get('mode') != mode):
        return False
    if mode == 'multiprocessing':
        pids = [data.get(key) for key in ('parentPID', 'managerPID', 'childPID')]
        return (all(type(pid) is int and pid > 0 for pid in pids) and len(set(pids)) == 3
                and type(data.get('value')) is int and data['value'] == 42
                and type(data.get('childExitCode')) is int and data['childExitCode'] == 0
                and type(data.get('managerExitCode')) is int and data['managerExitCode'] == 0
                and data.get('managerShutdown') is True and data.get('socketRemoved') is True)
    return (type(data.get('pageCount')) is int and data['pageCount'] == 1 and data.get('recognizedTextMatched') is True
            and data.get('browserClosed') is True and type(data.get('browserPDFBytes')) is int
            and 128 <= data['browserPDFBytes'] <= 2 * 1024 * 1024
            and isinstance(data.get('browserPDFSHA256'), str)
            and re.fullmatch('[0-9a-f]{64}', data['browserPDFSHA256']) is not None)


def browser_receipt_matches(path, data):
    """Require the received PDF's actual bytes, not just a worker success flag."""
    if not isinstance(data, dict): return False
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 128 <= info.st_size <= 2 * 1024 * 1024: return False
            content = stream.read(2 * 1024 * 1024 + 1)
        return (content.startswith(b'%PDF-') and len(content) == info.st_size == data.get('browserPDFBytes')
                and hashlib.sha256(content).hexdigest() == data.get('browserPDFSHA256'))
    except OSError:
        return False


def run_private_ipc(executable, base, ipc_probe, output, source_venv, source_browsers, commit):
    output.mkdir(mode=0o700)
    report = {'schemaVersion': 1, 'productionPromoted': False, 'passed': False,
              'officeFallbackProtocolSource': 'https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sal/osl/unx/pipe.cxx',
              'limitations': ['Synthetic IPC diagnosis, not the complete PDF distribution.',
                             'No hardware GPU acceleration or complete Office font fidelity is inferred.']}
    def publish():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    publish()
    try:
        with tempfile.TemporaryDirectory(prefix='pdi-', dir='/tmp') as temporary:
            workspace = Path(temporary).resolve(strict=True)
            ipc = workspace / 'ipc'; ipc.mkdir(mode=0o700)
            outside = workspace / 'outside'; outside.mkdir(mode=0o700)
            escape = ipc / 'escape'; escape.symlink_to(outside, target_is_directory=True)
            assembled = assemble(source_venv, source_browsers, workspace / 'build', commit)
            original = assembled['runtime']; runtime = workspace / 'moved runtime'
            original.rename(runtime)
            app = runtime / assembled['app'].relative_to(original)
            python = runtime / assembled['python'].relative_to(original)
            browsers = {name: runtime / path.relative_to(original) for name, path in assembled['browsers'].items()}
            shutil.copyfile(runtime / 'manifest.json', output / 'runtime-manifest.json')
            shutil.copyfile(runtime / 'provenance.json', output / 'runtime-provenance.json')
            before = manifest_identity(runtime)
            if before != assembled['manifestSHA256']: raise ValueError('Relocation changed the runtime manifest.')
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True, timeout=90)
            report['runtime'] = {'moved': True, 'manifestSHA256Before': before, 'sourceLocationAbsent': not original.exists(),
                                 'signatureUnit': str(app), 'signatureAfterMoveVerified': True,
                                 'pythonSHA256': hashlib.sha256(python.read_bytes()).hexdigest()}
            # Deny the fixture's source packages/browsers as well as the base's
            # Homebrew/Office/Xcode roots. Cache roots cannot silently use host
            # browser data; all workload HOME/cache/temp directories are private.
            denied_roots = [source_venv.resolve(strict=True), source_browsers.resolve(strict=True), original,
                            Path.home() / 'Library/Caches', Path.home() / '.cache',
                            Path.home() / 'Library/Application Support/Chromium']
            baseline = base + '\n(deny file-read* file-write* ' + ' '.join('(subpath ' + json.dumps(str(path)) + ')' for path in denied_roots) + ')\n'
            candidate = private_profile(baseline, ipc)
            (output / 'baseline.sb').write_text(baseline); (output / 'candidate.sb').write_text(candidate)
            report['baselineSHA256'] = hashlib.sha256(baseline.encode()).hexdigest()
            report['candidateSHA256'] = hashlib.sha256(candidate.encode()).hexdigest()
            report['ipcRoot'] = str(ipc)
            environment = dict(os.environ, PATH='/usr/bin:/bin:/usr/sbin:/sbin', TMPDIR=str(ipc) + '/',
                               MAC_CHROMIUM_TMPDIR=str(ipc), OSL_SOCKET_PATH=str(ipc))
            for key in ('PYTHONPATH', 'PYTHONHOME', '__PYVENV_LAUNCHER__'): environment.pop(key, None)
            home = ipc / 'home'; home.mkdir(mode=0o700)
            cache = ipc / 'cache'; cache.mkdir(mode=0o700)
            environment.update(HOME=str(home), XDG_CACHE_HOME=str(cache))
            report['access'] = {}
            for name, path, expected in [('tmp', Path('/tmp'), False), ('var-tmp', Path('/var/tmp'), False), ('private', ipc, True)]:
                result = measure(['/usr/bin/sandbox-exec', '-p', candidate, ipc_probe, 'access', path], output / ('access-' + name), environment, seconds=10)
                data = json.loads((output / ('access-' + name) / 'stdout.txt').read_text())
                result.update(result=data, expectationPassed=access_expectation(result, data, expected))
                report['access'][name] = result; publish()
            report['boundaries'] = {}
            for name, arguments, allowed in [('private-unix', ['unix', str(ipc / 'probe')], True),
                    ('outside-unix', ['unix', str(outside / 'probe')], False),
                    ('symlink-escape', ['unix-lexical', str(escape / 'probe')], False),
                    ('tcp', ['tcp'], False), ('udp', ['udp'], False)]:
                result = measure(['/usr/bin/sandbox-exec', '-p', candidate, ipc_probe, *arguments], output / ('boundary-' + name), environment, seconds=10)
                data = json.loads((output / ('boundary-' + name) / 'stdout.txt').read_text())
                result.update(result=data, expectationPassed=probe_expectation(result, data, allowed))
                report['boundaries'][name] = result; publish()
            fixture = prepare_office_fixture(output / 'office-fixture')
            private_socket = ipc / office_socket(fixture[1], os.getuid()).name
            report['officeFallback'] = {}
            for name, policy, predicted in [('denied-before', baseline, None), ('private', candidate, private_socket), ('denied-after', baseline, None)]:
                result = conversion(executable, output / ('office-' + name), policy, fixture,
                                    environment_override=environment, predicted_socket=predicted)
                report['officeFallback'][name] = result; publish()
            worker = ROOT / 'scripts/private_ipc_worker.py'
            report['workerSHA256'] = hashlib.sha256(worker.read_bytes()).hexdigest()
            report['workers'] = {}
            for name, browser in [('multiprocessing', None), *browsers.items()]:
                mode = 'multiprocessing' if browser is None else 'browser'
                report['workers'][name] = {}
                for label, policy in [('baseline', baseline), ('candidate', candidate)]:
                    case = output / (name + '-' + label); case.mkdir(mode=0o700)
                    private = ipc / (name + '-' + label); private.mkdir(mode=0o700)
                    result_path = case / 'worker.json'
                    command = [python, worker, '--mode', mode, '--ipc', private, '--output', result_path]
                    if browser is not None: command.extend(['--browser-executable', browser])
                    result = measure(['/usr/bin/sandbox-exec', '-p', policy, *command], case / 'process',
                                     dict(environment, TMPDIR=str(private) + '/', MAC_CHROMIUM_TMPDIR=str(private)), seconds=90)
                    data = None
                    if result_path.is_file() and result_path.stat().st_size <= 16384: data = json.loads(result_path.read_text())
                    expectation = worker_expectation(result, data, mode)
                    if expectation:
                        expectation = data.get('parentPID') == result['pid']
                    if mode == 'multiprocessing' and expectation:
                        expectation = data.get('managerAddress') == str(private / 'manager.sock')
                    generated = private / 'browser.pdf'
                    if mode == 'browser' and expectation:
                        expectation = browser_receipt_matches(generated, data)
                    result.update(report=data, expectationPassed=expectation,
                                  executableSHA256=hashlib.sha256((browser or python).read_bytes()).hexdigest())
                    report['workers'][name][label] = result
                    if browser_receipt_matches(generated, data): shutil.copyfile(generated, case / 'browser.pdf')
                    publish()
            after = manifest_identity(runtime)
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True, timeout=90)
            report['runtime']['signatureAfterWorkloadsVerified'] = True
            report['runtime']['manifestSHA256After'] = after
            report['runtime']['bytesUnchanged'] = before == after
            denied, allowed, denied_after = (report['officeFallback'][key] for key in ('denied-before', 'private', 'denied-after'))
            report['passed'] = (causal_denial(denied) and causal_denial(denied_after) and allowed['conversionPassed']
                and allowed['predictedSocketObserved']
                and denied['officeArguments'] == allowed['officeArguments'] == denied_after['officeArguments']
                and denied['inputSHA256'] == allowed['inputSHA256'] == denied_after['inputSHA256']
                and denied['executableSHA256'] == allowed['executableSHA256'] == denied_after['executableSHA256']
                and all(case['expectationPassed'] for case in report['access'].values())
                and all(case['expectationPassed'] for case in report['boundaries'].values())
                and all(cases['candidate']['expectationPassed'] for cases in report['workers'].values())
                and before == after)
    finally:
        publish()
    print('PRIVATE IPC DIAGNOSTIC REPORT', json.dumps(report, sort_keys=True), flush=True)
    return report
