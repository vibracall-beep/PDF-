#!/usr/bin/env python3
"""Measure synthetic LibreOffice conversion before/after packaging and isolation.

This is diagnostic evidence, never an approval of the PDF application. It does
not change the production sandbox, use user documents, or contact a service.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_binary import copy_tree, macho, rewrite_macho, sign_if_needed

LOG_LIMIT = 2 * 1024 * 1024


def production_profile(home):
    # Evaluate the actual checked-in assignment, without sourcing/running the
    # rest of the verification script. This keeps the diagnostic policy exact.
    lines = [line for line in (ROOT / 'scripts/check-portable.sh').read_text().splitlines()
             if line.startswith('PDF_PROFILE=')]
    if len(lines) != 1 or not lines[0].startswith('PDF_PROFILE="(version 1)(allow default)'):
        raise ValueError('The production sandbox profile could not be identified.')
    return subprocess.check_output(
        ['/bin/bash', '-eu', '-c', lines[0] + '\nprintf "%s" "$PDF_PROFILE"\n'],
        text=True, timeout=10,
        env={'PATH': '/usr/bin:/bin', 'PDF_HOME_QUOTED': json.dumps(str(home / 'Library/Application Support/PDF/runtimes'))})


def office_socket(user_installation, uid):
    # LibreOffice tag libreoffice-26.8.1.1:
    # desktop/source/deployment/misc/dp_misc.cxx getOfficePipeId hashes the
    # normalized UserInstallation file URL's UTF-16 code units with MD5, then
    # appends each byte in hexadecimal WITHOUT two-digit padding. MD5 is only
    # its IPC naming protocol, never an integrity/security digest here.
    directory = user_installation.resolve(strict=True)
    if user_installation.is_symlink() or not directory.is_dir() or type(uid) is not int or uid < 0:
        raise ValueError('Invalid private Office profile.')
    uri = directory.as_uri().rstrip('/')
    digest = hashlib.md5(uri.encode('utf-16-le' if sys.byteorder == 'little' else 'utf-16-be')).digest()
    name = 'OSL_PIPE_' + str(uid) + '_SingleOfficeIPC_' + ''.join(format(byte, 'x') for byte in digest)
    # sal/osl/unx/pipe.cxx prefers writable /tmp over /var/tmp and ignores
    # TMPDIR. The unchanged production profile permits writing /tmp.
    return Path('/tmp').resolve(strict=True) / name


def exact_office_profile(base, socket_path):
    if not socket_path.is_absolute() or socket_path.parent != Path('/tmp').resolve(strict=True):
        raise ValueError('The diagnostic exception must name one temporary Unix socket.')
    if re.fullmatch('OSL_PIPE_' + str(os.getuid()) + r'_SingleOfficeIPC_[0-9a-f]{16,32}', socket_path.name) is None:
        raise ValueError('The diagnostic exception does not belong to this Office profile.')
    return base + '\n(allow network-bind network-inbound network-outbound (literal ' + json.dumps(str(socket_path)) + '))\n'


def prepare_office_fixture(directory):
    from docx import Document
    directory.mkdir(mode=0o700)
    source = directory / 'office.docx'
    document = Document(); document.add_paragraph('PDF portable Office verification'); document.save(source)
    user_installation = directory / 'profile'; user_installation.mkdir(mode=0o700)
    converted = directory / 'converted'; converted.mkdir(mode=0o700)
    return source, user_installation, converted


def probe_expectation(result, data, allowed):
    stages = ('socketCreated', 'bound', 'listening', 'connected', 'exchanged')
    errors = ('socketErrno', 'bindErrno', 'listenErrno', 'connectErrno', 'exchangeErrno')
    if (result.get('exit') != 0 or result.get('stoppedBecause') is not None
            or not isinstance(data, dict) or set(data) != set(stages + errors)
            or any(type(data[key]) is not bool for key in stages)
            or any(type(data[key]) is not int or data[key] < 0 for key in errors)):
        return False
    if allowed:
        return all(data[key] for key in stages) and all(data[key] == 0 for key in errors)
    # A refused/absent listener (ECONNREFUSED) proves nothing about policy.
    # Require an actual denied bind on a newly created socket, and no traffic.
    return (data['socketCreated'] and data['socketErrno'] == 0 and not data['bound']
            and data['bindErrno'] == errno.EPERM
            and not any(data[key] for key in ('listening', 'connected', 'exchanged'))
            and all(data[key] == 0 for key in ('listenErrno', 'connectErrno', 'exchangeErrno')))


def causal_denial(result):
    # Match the observed LibreOffice failure, not a timeout, signal, malformed
    # invocation or any other failure that happened to produce no readable PDF.
    return (type(result.get('exit')) is int and result['exit'] == 1
            and result.get('stoppedBecause') is None and result.get('pdfExists') is False
            and result.get('conversionPassed') is False)


class ExitObservation:
    """Observe the owned child without releasing its PID/process-group identity."""
    @staticmethod
    def supported():
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise RuntimeError('A custom SIGCHLD handler could reap the diagnostic child.')
        if all(hasattr(os, name) for name in ('waitid', 'WNOWAIT', 'P_PID', 'WEXITED', 'WNOHANG')):
            return 'waitid'
        # CPython deliberately omits os.waitid on macOS. kqueue NOTE_EXIT also
        # observes exit without collecting the zombie; wait() remains ours.
        if sys.platform == 'darwin' and all(hasattr(select, name) for name in
                ('kqueue', 'kevent', 'KQ_FILTER_PROC', 'KQ_NOTE_EXIT', 'KQ_EV_ADD', 'KQ_EV_ONESHOT')):
            return 'kqueue'
        raise RuntimeError('Non-reaping child exit observation is unavailable.')

    def __init__(self, pid):
        backend = self.supported()
        self.pid = pid
        self.queue = None
        self.observed = False
        if backend == 'kqueue':
            self.queue = select.kqueue()
            event = select.kevent(pid, filter=select.KQ_FILTER_PROC,
                                 flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)
            try:
                self.queue.control([event], 0, 0)
            except OSError as error:
                if error.errno != errno.ESRCH:
                    self.queue.close(); self.queue = None; raise
                # The child may already be a zombie when NOTE_EXIT is added.
                # SIGCHLD is default and no poll/wait has reaped our Popen, so
                # its PID is still reserved even if kqueue cannot register it.
                self.observed = True

    def exited(self):
        if self.observed:
            return True
        if self.queue is None:
            result = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            self.observed = result is not None and result.si_pid == self.pid
        else:
            self.observed = bool(self.queue.control([], 1, 0))
        return self.observed

    def close(self):
        if self.queue is not None:
            self.queue.close(); self.queue = None


def group_has_only_zombies(leader):
    """Read a process-table snapshot while our unreaped leader pins the PGID."""
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,pgid=,stat='],
                            capture_output=True, text=True, check=True, timeout=5,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if len(result.stdout) > 1024 * 1024:
        raise RuntimeError('The process-group snapshot exceeds its diagnostic limit.')
    group = {}
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) != 3:
            raise RuntimeError('The process-group snapshot is incomplete.')
        pid, pgid = int(columns[0]), int(columns[1])
        if pgid == leader:
            if pid in group:
                raise RuntimeError('The process-group snapshot contains duplicate members.')
            group[pid] = columns[2]
    # Require positive evidence of the still-owned zombie leader, not merely
    # an empty/missing group. No live member may remain in this snapshot.
    return leader in group and all(state.startswith('Z') for state in group.values())


def signal_owned_group(process, observation, signum):
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        # XNU killpg1 filters SZOMB out of pgrp_iterate and returns EPERM when
        # no signallable members remain (bsd/kern/kern_sig.c). Accept this
        # Darwin-specific case only after proving exit without reap AND a
        # complete group snapshot containing only zombies. Real permission
        # failures in a live or uninspectable group remain fatal.
        if sys.platform == 'darwin' and error.errno == errno.EPERM and observation is not None:
            try:
                if observation.exited() and group_has_only_zombies(process.pid):
                    return
            except Exception as proof_error:
                error.add_note('Could not prove the diagnostic group is dead: ' + type(proof_error).__name__)
        raise


def stop(process, observation):
    if process.returncode is not None:
        raise RuntimeError('Diagnostic leader was already reaped; do not signal a reused group.')
    failure = None
    try:
        signal_owned_group(process, observation, signal.SIGTERM)
        deadline = time.monotonic() + 3
        while observation is not None and not observation.exited() and time.monotonic() < deadline:
            time.sleep(0.05)
    except BaseException as error:
        failure = error
    finally:
        # Kill any remaining owned descendants while the unreaped leader still
        # reserves its PID/PGID. Only then may wait() release that identity.
        try:
            signal_owned_group(process, observation, signal.SIGKILL)
        except BaseException as error:
            if failure is None: failure = error
            else: failure.add_note('Group kill also failed: ' + type(error).__name__)
        finally:
            try:
                process.wait(timeout=5)
            except BaseException as error:
                if failure is None: failure = error
                else: failure.add_note('Leader collection also failed: ' + type(error).__name__)
    if failure is not None:
        raise failure


def measure(command, directory, environment=None, seconds=90, observe=None):
    ExitObservation.supported()
    directory.mkdir(mode=0o700)
    stdout = directory / 'stdout.txt'; stderr = directory / 'stderr.txt'
    began = time.monotonic()
    reason = None
    with stdout.open('xb') as out, stderr.open('xb') as err:
        process = subprocess.Popen([str(value) for value in command], stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err, env=environment, start_new_session=True)
        observation = None
        try:
            observation = ExitObservation(process.pid)
            while not observation.exited():
                if observe is not None: observe()
                if time.monotonic() - began > seconds:
                    reason = 'deadline'; break
                if max(stdout.stat().st_size, stderr.stat().st_size) > LOG_LIMIT:
                    reason = 'log-limit'; break
                time.sleep(0.05)
        finally:
            # Reap the entire owned group, including a descendant whose leader
            # exited early. Nothing outside this diagnostic group is signalled.
            try: stop(process, observation)
            finally:
                if observation is not None: observation.close()
    sizes = {}
    for path in (stdout, stderr):
        sizes[path.name] = path.stat().st_size
        if path.stat().st_size > LOG_LIMIT:
            if reason is None: reason = 'log-limit'
            with path.open('r+b') as stream: stream.truncate(LOG_LIMIT)
    result = {'pid': process.pid, 'exit': process.returncode, 'seconds': round(time.monotonic() - began, 3),
              'stoppedBecause': reason, 'originalLogBytes': sizes,
              'stdout': stdout.name, 'stderr': stderr.name}
    print('MEASUREMENT', directory.name, json.dumps(result, sort_keys=True), flush=True)
    for label, path in [('stdout', stdout), ('stderr', stderr)]:
        data = path.read_bytes()[:32000].decode('utf-8', errors='replace')
        if data: print(label + ':\n' + data, flush=True)
    return result


def conversion(executable, directory, profile=None, fixture=None):
    import fitz
    directory.mkdir(mode=0o700)
    source, user_installation, converted = fixture or prepare_office_fixture(directory / 'fixture')
    generated = converted / 'office.pdf'
    if os.path.lexists(generated):
        raise FileExistsError('The synthetic conversion output must be absent before every attempt.')
    socket_path = office_socket(user_installation, os.getuid())
    if os.path.lexists(socket_path):
        raise FileExistsError('The synthetic Office socket already exists; do not connect to or remove it.')
    socket_observed = False
    socket_metadata = None
    def observe():
        nonlocal socket_observed, socket_metadata
        try: info = socket_path.lstat()
        except FileNotFoundError: return
        if stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid():
            socket_observed = True
            socket_metadata = {'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode), 'device': info.st_dev, 'inode': info.st_ino}
    environment = dict(os.environ)
    environment['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
    # This affects logging only; no bootstrap/profile/IPC workaround is added.
    environment['SAL_LOG'] = '+WARN+INFO'
    command = [str(executable), '-env:UserInstallation=' + user_installation.resolve(strict=True).as_uri(),
               '--headless', '--convert-to', 'pdf', '--outdir', str(converted), str(source)]
    office_arguments = command[:]
    if profile is not None: command = ['/usr/bin/sandbox-exec', '-p', profile, *command]
    result = measure(command, directory / 'process', environment, observe=observe)
    result['predictedSocket'] = str(socket_path)
    result['predictedSocketObserved'] = socket_observed
    result['socketMetadataWhileRunning'] = socket_metadata
    result['inputSHA256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    result['officeArguments'] = office_arguments
    result['executableSHA256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
    output = directory / 'office.pdf'
    if os.path.lexists(generated):
        if not stat.S_ISREG(generated.lstat().st_mode):
            raise ValueError('The synthetic converter did not create a regular PDF.')
        # Retain each attempt separately, then free the shared output pathname
        # so deny/allow/deny use identical arguments without overwriting a PDF.
        os.link(generated, output, follow_symlinks=False)
        if not output.samefile(generated): raise RuntimeError('Synthetic PDF identity changed.')
        generated.unlink()
    result['pdfExists'] = output.is_file()
    result['pdfContainsFixture'] = False
    if output.is_file():
        result['pdfSHA256'] = hashlib.sha256(output.read_bytes()).hexdigest()
        try:
            with fitz.open(output) as pdf:
                result['pages'] = len(pdf)
                result['pdfContainsFixture'] = bool(len(pdf)) and 'PDF portable Office verification' in ''.join(page.get_text() for page in pdf)
        except Exception as error:
            result['pdfReadError'] = type(error).__name__ + ': ' + str(error)
    result['conversionPassed'] = result['exit'] == 0 and result['stoppedBecause'] is None and result['pdfContainsFixture']
    print('CONVERSION', directory.name, json.dumps(result, sort_keys=True), flush=True)
    return result


SOCKET_PROBE = r'''#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
int main(int argc,char **argv) {
    struct sockaddr_un address={0}; struct stat before;
    if(argc!=2 || strlen(argv[1])>=sizeof(address.sun_path)) return 2;
    if(lstat(argv[1],&before)==0 || errno!=ENOENT) return 3;
    int fd=socket(AF_UNIX,SOCK_STREAM,0), socketError=fd<0?errno:0;
    int bound=-1, bindError=0;
    if(fd>=0) {
        address.sun_len=sizeof(address); address.sun_family=AF_UNIX; strcpy(address.sun_path,argv[1]);
        bound=bind(fd,(struct sockaddr *)&address,sizeof(address));
        if(bound<0) bindError=errno;
        close(fd); if(bound==0) unlink(argv[1]);
    }
    printf("{\"socketCreated\":%s,\"socketErrno\":%d,\"bound\":%s,\"bindErrno\":%d}\n",
           fd>=0?"true":"false",socketError,bound==0?"true":"false",bindError);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin': raise ValueError('This diagnosis requires macOS.')
    os.umask(0o077)
    output = args.output.absolute(); output.mkdir(mode=0o700)
    source = Path('/Applications/LibreOffice.app')
    info = plistlib.loads((source / 'Contents/Info.plist').read_bytes())
    profile = production_profile(Path.home())
    (output / 'production-sandbox.sb').write_text(profile)
    report = {'schemaVersion': 1, 'kind': 'synthetic-portable-office-diagnosis', 'productApproved': False,
              'commit': os.environ.get('GITHUB_SHA'), 'libreOfficeVersion': info.get('CFBundleShortVersionString'),
              'sandboxSHA256': hashlib.sha256(profile.encode()).hexdigest(), 'cases': {}, 'complete': False,
              'officePipeProtocolSource': 'https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/desktop/source/deployment/misc/dp_misc.cxx',
              'limitations': ['Only LibreOffice is copied; the full PDF runtime and its fontconfig environment are not assembled.',
                              'Unisolated cases are diagnostic controls using synthetic input, not a production fallback.',
                              'No result from this workflow approves the complete PDF application.']}
    def publish():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    publish()
    try:
        report['metadata'] = measure(['/usr/bin/codesign', '-d', '--verbose=4', '--entitlements', ':-',
                                      str(source / 'Contents/MacOS/soffice')], output / 'source-signature')
        report['version'] = measure([str(source / 'Contents/MacOS/soffice'), '--version'], output / 'source-version')
        report['cases']['original'] = conversion(source / 'Contents/MacOS/soffice', output / 'original')
        publish()
        with tempfile.TemporaryDirectory(prefix='PDF private Office ') as directory:
            root = Path(directory)
            copied = root / 'runtime/LibreOffice.app'; copied.parent.mkdir()
            copy_tree(source, copied)
            report['cases']['private-before-rewrite'] = conversion(copied / 'Contents/MacOS/soffice', output / 'private-before-rewrite')
            publish()
            natives = [path for path in copied.rglob('*') if macho(path)]
            report['nativeFileCount'] = len(natives)
            for path in natives:
                subprocess.run(['/usr/bin/lipo', str(path), '-verify_arch', 'arm64'], check=True, stdout=subprocess.DEVNULL, timeout=30)
                rewrite_macho(path, {source: copied}, copied)
            for path in natives: sign_if_needed(path)
            nested = [path for path in copied.rglob('*') if path.is_dir() and not path.is_symlink()
                      and path.suffix in ('.app', '.framework', '.xpc')]
            for path in sorted(nested, key=lambda item: len(item.parts), reverse=True) + [copied]:
                sign_if_needed(path, deep=True)
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(copied)], check=True, timeout=90)
            report['privateSignatureVerified'] = True
            relocated = root / 'relocated runtime'; copied.parent.rename(relocated)
            executable = relocated / 'LibreOffice.app/Contents/MacOS/soffice'
            report['privateSignature'] = measure(['/usr/bin/codesign', '-d', '--verbose=4', '--entitlements', ':-', str(executable)], output / 'private-signature')
            report['cases']['private-signed'] = conversion(executable, output / 'private-signed')
            publish()
            report['cases']['private-isolated'] = conversion(executable, output / 'private-isolated', profile)
            publish()
            # Two attempts use the same signed executable, DOCX bytes and
            # canonical profile directory. Only the exact socket allow rule
            # differs; no IP-network or dependency rule is removed.
            fixture = prepare_office_fixture(output / 'causal-fixture')
            socket_path = office_socket(fixture[1], os.getuid())
            limited = exact_office_profile(profile, socket_path)
            (output / 'exact-socket-sandbox.sb').write_text(limited)
            report['exactSocket'] = str(socket_path)
            report['exactSocketSandboxSHA256'] = hashlib.sha256(limited.encode()).hexdigest()
            report['cases']['causal-denied'] = conversion(executable, output / 'causal-denied', profile, fixture)
            publish()
            report['cases']['causal-exact-socket'] = conversion(executable, output / 'causal-exact-socket', limited, fixture)
            publish()
            report['cases']['causal-denied-after'] = conversion(executable, output / 'causal-denied-after', profile, fixture)
            publish()
        with tempfile.TemporaryDirectory(prefix='pdf-lo-ipc-', dir='/tmp') as directory:
            root = Path(directory); probe = root / 'probe'
            subprocess.run(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-x', 'c', '-', '-o', str(probe)],
                           input=SOCKET_PROBE, text=True, capture_output=True, check=True, timeout=60)
            report['socketProbe'] = {}
            for name, prefix in [('plain', []), ('isolated', ['/usr/bin/sandbox-exec', '-p', profile])]:
                report['socketProbe'][name] = measure([*prefix, str(probe), str(root / 'ipc')], output / ('socket-' + name), seconds=10)
                result = output / ('socket-' + name) / 'stdout.txt'
                report['socketProbe'][name]['result'] = json.loads(result.read_text())
        # A separate native probe validates byte exchange and the boundaries of
        # the candidate rule. Only loopback and synthetic Unix endpoints are
        # attempted; there is no external network destination.
        with tempfile.TemporaryDirectory(prefix='pdf-lo-boundaries-', dir='/tmp') as directory:
            root = Path(directory); probe = root / 'probe'
            subprocess.run(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'diagnostics/PortableIPCProbe.c'), '-o', str(probe)],
                           capture_output=True, check=True, timeout=60)
            report['exactSocketControls'] = {}
            cases = [('allowed-unix', ['unix-office', str(socket_path)]),
                     ('outside-unix', ['unix', str(root.resolve() / 'outside')]),
                     ('denied-tcp', ['tcp']), ('denied-udp', ['udp'])]
            for name, arguments in cases:
                result = measure(['/usr/bin/sandbox-exec', '-p', limited, str(probe), *arguments], output / name, seconds=10)
                data = json.loads((output / name / 'stdout.txt').read_text())
                result['result'] = data
                result['expectationPassed'] = probe_expectation(result, data, name == 'allowed-unix')
                report['exactSocketControls'][name] = result
                publish()
        controls = report['exactSocketControls']
        denied, allowed, denied_after = (report['cases'][name] for name in ('causal-denied', 'causal-exact-socket', 'causal-denied-after'))
        report['causalProofPassed'] = (causal_denial(denied) and causal_denial(denied_after) and allowed['conversionPassed']
            and allowed['predictedSocketObserved'] and denied['inputSHA256'] == allowed['inputSHA256'] == denied_after['inputSHA256']
            and denied['officeArguments'] == allowed['officeArguments'] == denied_after['officeArguments']
            and denied['executableSHA256'] == allowed['executableSHA256'] == denied_after['executableSHA256']
            and all(item['expectationPassed'] for item in controls.values()))
        report['networkControlInterpretation'] = 'Negative controls require bind() EPERM on fresh endpoints; connection refusal or a missing listener never counts as network isolation.'
        report['complete'] = True
    finally:
        publish()
    print('FINAL DIAGNOSTIC REPORT', json.dumps(report, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
