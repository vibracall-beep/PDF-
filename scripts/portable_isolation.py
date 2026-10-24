#!/usr/bin/env python3
"""Validate a portable bundle with private Unix IPC and no host/IP fallback."""
from __future__ import annotations

import argparse
import contextlib
import contextvars
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HELPERS = Path(__file__).resolve().parent
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(HELPERS.parent / 'engine'))
from bundle_lease import inherited_from_environment
from owned_process import OwnedProcess, ProcessInterrupted as ValidationInterrupted, cooperative_signals


ACTIVE_NAMESPACE = contextvars.ContextVar('pdf_portable_validation_namespace', default=None)


def run_owned(arguments, *, seconds, environment=None, capture=False, identity=None):
    options = {'stdin': subprocess.DEVNULL, 'env': environment,
               'pass_fds': inherited_from_environment(), 'grace_seconds': 10}
    if capture: options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    namespace = ACTIVE_NAMESPACE.get()
    receipt = {'pid': None, 'cleanupConfirmed': False}
    if namespace is not None: namespace['children'].append(receipt)
    process = failure = None
    try:
        process = OwnedProcess([str(value) for value in arguments], **options)
        receipt['pid'] = process.pid
        if identity is not None: identity['pid'] = process.pid
        if capture:
            stdout, stderr = process.communicate(seconds, output_limit=2 * 1024 * 1024)
            if process.returncode != 0:
                print(stderr[:8192].decode('utf-8', errors='replace'), file=sys.stderr, flush=True)
            return process.returncode, stdout
        return process.wait(seconds), None
    except BaseException as error:
        failure = error
        raise
    finally:
        if process is not None:
            try: process.close()
            except BaseException as error:
                if failure is None: raise
                failure.add_note('Portable child cleanup failed: ' + type(error).__name__)
            finally:
                receipt['cleanupConfirmed'] = process.cleanup_confirmed
        if not receipt['cleanupConfirmed'] and failure is None:
            raise RuntimeError('Child cleanup was not confirmed; private namespace must be preserved.')


@contextlib.contextmanager
def private_namespace():
    # The short canonical name is required by sockaddr_un, including the
    # suffixes Chromium and multiprocessing append themselves.
    root = Path(tempfile.mkdtemp(prefix='pdf-ipc-', dir='/tmp')).resolve(strict=True)
    info = root.lstat()
    state = {'path': str(root), 'children': [], 'removed': False, 'preserved': False,
             'cleanupScope': 'direct-process-groups', 'workloadsStarted': False,
             'transitiveCleanupUnverified': False}
    token = ACTIVE_NAMESPACE.set(state)
    failure = None
    try:
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Private isolation namespace must be caller-owned with mode 0700.')
        ipc = root / 'ipc'; ipc.mkdir(mode=0o700)
        outside = root / 'outside'; outside.mkdir(mode=0o700)
        (ipc / 'escape').symlink_to(outside, target_is_directory=True)
        # Every child is synchronously collected by run_owned before this
        # context may remove the namespace. SIGKILL cannot execute cleanup.
        yield root, ipc, outside, state
    except BaseException as error:
        failure = error
        raise
    finally:
        ACTIVE_NAMESPACE.reset(token)
        try:
            if failure is not None and state['workloadsStarted']:
                state['transitiveCleanupUnverified'] = True
                state['preservationReason'] = 'Validation failed after workloads started; transitive cleanup is unverified.'
            current = root.lstat()
            if ((current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
                    or not stat.S_ISDIR(current.st_mode)):
                state['preserved'] = True
                raise RuntimeError('Private namespace identity changed; replacement was preserved.')
            if any(not child['cleanupConfirmed'] for child in state['children']):
                state['preserved'] = True
                raise RuntimeError('Child cleanup was not confirmed; private namespace preserved at ' + str(root))
            if failure is not None and state['workloadsStarted']:
                # A checker can fail to collect a converter in another session
                # and then exit. Collection of the checker group alone is not
                # proof that every transitive descendant has released this root.
                state['preserved'] = True
                raise RuntimeError(state['preservationReason'] + ' Namespace: ' + str(root))
            shutil.rmtree(root)
            state['removed'] = True
        except BaseException as error:
            state['preserved'] = True
            if failure is None: raise
            failure.add_note('Private namespace cleanup: ' + str(error))


def candidate_profile(base, ipc, home):
    info = ipc.lstat()
    if (ipc != ipc.resolve(strict=True) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700 or len(os.fsencode(ipc)) > 50):
        raise ValueError('IPC policy requires a short, canonical private directory.')
    # The original deny-all-IP and dependency-root rules remain byte-for-byte.
    # Additional cache denials and private HOME match the approved diagnosis.
    caches = [home / 'Library/Caches', home / '.cache', home / 'Library/Application Support/Chromium']
    policy = base + '\n(deny file-read* file-write* ' + ' '.join('(subpath ' + json.dumps(str(path)) + ')' for path in caches) + ')\n'
    temporary_roots = sorted({str(Path(path).resolve(strict=True)) for path in ('/tmp', '/var/tmp')})
    # LibreOffice 26.8.1.1 uses OSL_SOCKET_PATH only when W_OK fails for both
    # global temp roots. Deny these literal directories, not their descendants.
    policy += '(deny file-write* ' + ' '.join('(literal ' + json.dumps(path) + ')' for path in temporary_roots) + ')\n'
    policy += '(allow network-bind network-inbound network-outbound (subpath ' + json.dumps(str(ipc)) + '))\n'
    return policy


def probe_expected(code, data, allowed):
    stages = ('socketCreated', 'bound', 'listening', 'connected', 'exchanged')
    errors = ('socketErrno', 'bindErrno', 'listenErrno', 'connectErrno', 'exchangeErrno')
    if (type(code) is not int or code != 0 or not isinstance(data, dict) or set(data) != set(stages + errors)
            or any(type(data[key]) is not bool for key in stages)
            or any(type(data[key]) is not int or data[key] < 0 for key in errors)): return False
    if allowed: return all(data[key] for key in stages) and all(data[key] == 0 for key in errors)
    return (data['socketCreated'] and data['socketErrno'] == 0 and not data['bound'] and data['bindErrno'] == errno.EPERM
            and not any(data[key] for key in ('listening', 'connected', 'exchanged'))
            and all(data[key] == 0 for key in ('listenErrno', 'connectErrno', 'exchangeErrno')))


def access_expected(code, data, writable):
    return (type(code) is int and code == 0 and isinstance(data, dict) and set(data) == {'writable', 'accessErrno'}
            and type(data['writable']) is bool and type(data['accessErrno']) is int and data['writable'] is writable
            and (data['accessErrno'] == 0 if writable else data['accessErrno'] in (errno.EACCES, errno.EPERM)))


def snapshot(app):
    """Hash every file/link and its mode without writing to the signed bundle."""
    digest = hashlib.sha256(); total = count = 0
    for path in sorted(app.rglob('*')):
        name = path.relative_to(app).as_posix(); info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            if Path(target).is_absolute() or not path.resolve(strict=True).is_relative_to(app):
                raise ValueError('Bundle link escaped its signed root.')
            entry = {'name': name, 'target': target}
        elif stat.S_ISREG(info.st_mode):
            total += info.st_size
            if total > 12 * 1024 ** 3: raise ValueError('Bundle exceeds its verification limit.')
            file_hash = hashlib.sha256()
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as stream:
                before = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino): raise ValueError('Bundle file changed before reading.')
                for block in iter(lambda: stream.read(1024 * 1024), b''): file_hash.update(block)
                after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns): raise ValueError('Bundle file changed during reading.')
            entry = {'name': name, 'size': info.st_size, 'mode': stat.S_IMODE(info.st_mode), 'sha256': file_hash.hexdigest()}
        elif stat.S_ISDIR(info.st_mode): continue
        else: raise ValueError('Special file is not allowed in the bundle.')
        count += 1
        if count > 200000: raise ValueError('Bundle file count exceeds its verification limit.')
        digest.update(json.dumps(entry, sort_keys=True, separators=(',', ':')).encode() + b'\n')
    return {'sha256': digest.hexdigest(), 'files': count, 'bytes': total}


def worker_expected(code, report, mode, ipc, parent_pid):
    if (type(code) is not int or code != 0 or not isinstance(report, dict) or type(report.get('schemaVersion')) is not int
            or report['schemaVersion'] != 1 or report.get('passed') is not True or report.get('mode') != mode
            or type(report.get('parentPID')) is not int or report['parentPID'] != parent_pid): return False
    if mode == 'multiprocessing':
        pids = [report.get(key) for key in ('parentPID', 'managerPID', 'childPID')]
        return (all(type(pid) is int and pid > 0 for pid in pids) and len(set(pids)) == 3
                and type(report.get('value')) is int and report['value'] == 42
                and type(report.get('childExitCode')) is int and report['childExitCode'] == 0
                and type(report.get('managerExitCode')) is int and report['managerExitCode'] == 0
                and report.get('managerShutdown') is True and report.get('socketRemoved') is True
                and report.get('managerAddress') == str(ipc / 'manager.sock') and not os.path.lexists(ipc / 'manager.sock'))
    if (mode != 'browser' or type(report.get('pageCount')) is not int or report['pageCount'] != 1
            or report.get('recognizedTextMatched') is not True or report.get('browserClosed') is not True
            or type(report.get('browserPDFBytes')) is not int or not 128 <= report['browserPDFBytes'] <= 2 * 1024 ** 2
            or not isinstance(report.get('browserPDFSHA256'), str) or re.fullmatch('[0-9a-f]{64}', report['browserPDFSHA256']) is None): return False
    descriptor = os.open(ipc / 'browser.pdf', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != report['browserPDFBytes']: return False
        content = stream.read(2 * 1024 ** 2 + 1)
    return content.startswith(b'%PDF-') and len(content) == info.st_size and hashlib.sha256(content).hexdigest() == report['browserPDFSHA256']


def validate(app, base, report):
    runtime = app / 'Contents/Resources/runtime'
    python = runtime / 'bin/python3'; probe = runtime / 'bin/pdf-ipc-probe'
    for path in (python, probe):
        if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK): raise ValueError('Required private verifier is unavailable.')
    def signature():
        code, _ = run_owned(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], seconds=90, capture=True)
        if code: raise RuntimeError('The portable bundle signature is invalid.')
    signature(); before = snapshot(app)
    report['snapshotBefore'] = before
    home = Path.home()
    with private_namespace() as (root, ipc, outside, namespace_state):
        report['namespaceState'] = namespace_state
        policy = candidate_profile(base, ipc, home)
        report['policySHA256'] = hashlib.sha256(policy.encode()).hexdigest()
        report['probeSHA256'] = hashlib.sha256(probe.read_bytes()).hexdigest()
        report['namespace'] = str(root)
        private_home = ipc / 'home'; private_home.mkdir(mode=0o700)
        cache = ipc / 'cache'; cache.mkdir(mode=0o700)
        environment = dict(os.environ, TMPDIR=str(ipc) + '/', MAC_CHROMIUM_TMPDIR=str(ipc),
                           OSL_SOCKET_PATH=str(ipc), HOME=str(private_home), XDG_CACHE_HOME=str(cache))
        for name in ('PYTHONHOME', 'PYTHONPATH', '__PYVENV_LAUNCHER__'): environment.pop(name, None)
        prefix = ['/usr/bin/sandbox-exec', '-p', policy]
        report['controls'] = {}
        for name, arguments, expected, kind in [
                ('tmp-not-writable', ['access', '/tmp'], False, 'access'),
                ('var-tmp-not-writable', ['access', '/var/tmp'], False, 'access'),
                ('private-writable', ['access', str(ipc)], True, 'access'),
                ('private-unix', ['unix', str(ipc / 'probe')], True, 'network'),
                ('outside-unix', ['unix', str(outside / 'probe')], False, 'network'),
                ('symlink-escape', ['unix-lexical', str(ipc / 'escape/probe')], False, 'network'),
                ('tcp-denied', ['tcp'], False, 'network'), ('udp-denied', ['udp'], False, 'network')]:
            code, stdout = run_owned([*prefix, probe, *arguments], seconds=10, environment=environment, capture=True)
            data = json.loads(stdout)
            passed = access_expected(code, data, expected) if kind == 'access' else probe_expected(code, data, expected)
            report['controls'][name] = {'exit': code, 'result': data, 'passed': passed}
            if not passed: raise RuntimeError('Portable isolation boundary failed: ' + name)
        report['workers'] = {}
        namespace_state['workloadsStarted'] = True
        browsers = [('chromium', runtime / 'browsers/chromium-1194/chrome-mac/Chromium.app/Contents/MacOS/Chromium'),
                    ('headless-shell', runtime / 'browsers/chromium_headless_shell-1194/chrome-mac/headless_shell')]
        for name, browser in [('multiprocessing', None), *browsers]:
            directory = ipc / name; directory.mkdir(mode=0o700)
            result_path = directory / 'worker.json'
            mode = 'multiprocessing' if browser is None else 'browser'
            arguments = [python, '-I', '-B', HELPERS / 'private_ipc_worker.py', '--mode', mode,
                         '--ipc', directory, '--output', result_path]
            if browser is not None: arguments.extend(['--browser-executable', browser])
            identity = {}
            code, _ = run_owned([*prefix, *arguments], seconds=90,
                environment=dict(environment, TMPDIR=str(directory) + '/', MAC_CHROMIUM_TMPDIR=str(directory)), capture=True, identity=identity)
            descriptor = os.open(result_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 16384: raise ValueError('Invalid private worker receipt.')
                data = json.loads(stream.read(16385))
            passed = worker_expected(code, data, mode, directory, identity['pid'])
            report['workers'][name] = {'exit': code, 'report': data, 'passed': passed}
            if not passed: raise RuntimeError('Private runtime worker failed: ' + name)
        # Keep the existing complete engine and native tests and their budgets.
        for name, seconds, arguments in [
                ('runtime', 600, [python, '-I', HELPERS / 'check_runtime.py', app]),
                ('native', 300, [app / 'Contents/MacOS/PDF', '--smoke-test'])]:
            code, _ = run_owned([*prefix, *arguments], seconds=seconds, environment=environment)
            report[name] = {'exit': code, 'passed': code == 0}
            if code: raise RuntimeError('Portable validation failed: ' + name)
        signature(); after = snapshot(app)
        report['snapshotAfter'] = after
        if after != before: raise RuntimeError('Portable execution changed the signed bundle.')
        report['signatureAfterVerified'] = True
    report['namespaceRemoved'] = not root.exists()
    if not report['namespaceRemoved']: raise RuntimeError('Private IPC namespace cleanup did not complete.')
    report['passed'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--base-profile', required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin': parser.error('Real macOS isolation is required.')
    os.umask(0o077)
    report = {'schemaVersion': 1, 'passed': False, 'kind': 'portable-private-ipc-validation',
              'basis': {'run': 40125812418, 'commit': 'c2ecff71c160461962e3a1a7676c6cf2238b46e9'},
              'headlessBaselineAlreadyPassed': True}
    result = 1
    try:
        with cooperative_signals(): validate(args.app.resolve(strict=True), args.base_profile, report)
        result = 0
    except ValidationInterrupted as error:
        result = 128 + error.number; report['error'] = 'interrupted'
    except subprocess.TimeoutExpired:
        result = 124; report['error'] = 'deadline'
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        print('PORTABLE ISOLATION REPORT', json.dumps(report, sort_keys=True), flush=True)
    return result


if __name__ == '__main__': raise SystemExit(main())
