#!/usr/bin/env python3
"""Measure owned zombies/live descendants without changing application policy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
# Only the existing HEAD API is required. Product changes need not be included
# in the diagnostic commit; this driver is not an application approval gate.
from owned_process import OwnedProcess

LIMIT = 1024 * 1024


def write_json(path, value):
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write('\n')


def production_profile():
    lines = [line for line in (ROOT / 'scripts/check-portable.sh').read_text().splitlines()
             if line.startswith('PDF_PROFILE=')]
    if len(lines) != 1 or not lines[0].startswith('PDF_PROFILE="(version 1)(allow default)'):
        raise ValueError('The exact production sandbox assignment is unavailable.')
    return subprocess.check_output(['/bin/bash', '-eu', '-c', lines[0] + '\nprintf "%s" "$PDF_PROFILE"\n'],
        text=True, timeout=10,
        env={'PATH': '/usr/bin:/bin', 'PDF_HOME_QUOTED': json.dumps(str(Path.home() / 'Library/Application Support/PDF/runtimes'))})


def external_ps(group):
    result = {'requestedPGID': group}
    try:
        process = subprocess.run(['/bin/ps', '-axo', 'pid=,pgid=,stat='],
            capture_output=True, text=True, timeout=5, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        if len(process.stdout.encode()) > LIMIT: raise ValueError('External ps output exceeded its bound.')
        result.update(exit=process.returncode, stdoutBytes=len(process.stdout.encode()), members=[])
        for line in process.stdout.splitlines():
            values = line.split()
            if len(values) != 3: raise ValueError('External ps returned an incomplete record.')
            pid, pgid = int(values[0]), int(values[1])
            if pgid == group: result['members'].append(dict(pid=pid, pgid=pgid, status=values[2]))
        result['complete'] = process.returncode == 0
    except Exception as error:
        result.update(complete=False, errorType=type(error).__name__, errno=getattr(error, 'errno', None))
    return result


def case(probe, mode, profile, destination):
    prefix = [] if profile is None else ['/usr/bin/sandbox-exec', '-p', profile]
    owner = OwnedProcess([*prefix, str(probe), mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, grace_seconds=10)
    result = {'mode': mode, 'sandboxed': profile is not None, 'probePID': owner.pid, 'records': []}
    initial = bytearray(); partial = bytearray(); errors = bytearray()
    primary = None
    try:
        pipes = {owner.process.stdout.fileno(): 'stdout', owner.process.stderr.fileno(): 'stderr'}
        for descriptor in pipes: os.set_blocking(descriptor, False)
        deadline = time.monotonic() + 20
        ready = None
        while ready is None:
            if owner.exited(): raise RuntimeError('The probe exited before publishing its unreaped leader.')
            if time.monotonic() >= deadline: raise TimeoutError('The probe did not publish its ready record.')
            descriptors, _, _ = select.select(list(pipes), [], [], .05)
            for descriptor in descriptors:
                data = os.read(descriptor, 65536)
                if not data:
                    del pipes[descriptor]
                    continue
                if descriptor == owner.process.stderr.fileno():
                    errors.extend(data)
                    if len(errors) > LIMIT: raise ValueError('Probe stderr exceeded its bound.')
                    continue
                initial.extend(data); partial.extend(data)
                if len(initial) > LIMIT: raise ValueError('Probe stdout exceeded its bound.')
                while b'\n' in partial:
                    line, _, tail = partial.partition(b'\n'); partial[:] = tail
                    record = json.loads(line)
                    if record.get('event') != 'ready' or ready is not None:
                        raise ValueError('Unexpected pre-acknowledgement event.')
                    ready = record
            if not pipes and ready is None: raise RuntimeError('The probe closed its output without evidence.')
        if (ready.get('owned') is not True or ready.get('exitObservedWithoutReap') is not True
                or ready.get('probePID') != owner.pid or type(ready.get('leaderPID')) is not int
                or ready['leaderPID'] <= 0 or ready.get('leaderPGID') != ready['leaderPID']):
            raise ValueError('The probe did not demonstrate ownership and exit without collection.')
        result['records'] = [ready]
        result['externalBeforeSignals'] = external_ps(ready['leaderPID'])
        # Only now permit the probe to signal its own group and collect it.
        out, err = owner.communicate(20, input_bytes=b'g', output_limit=LIMIT)
        stdout, stderr = bytes(initial) + out, bytes(errors) + err
        result['records'] = [json.loads(line) for line in stdout.splitlines()]
        result.update(exit=owner.returncode, stdoutSHA256=hashlib.sha256(stdout).hexdigest(),
                      stderrSHA256=hashlib.sha256(stderr).hexdigest(), stderrBytes=len(stderr))
        with destination.with_suffix('.stdout.jsonl').open('xb') as stream: stream.write(stdout)
        with destination.with_suffix('.stderr.txt').open('xb') as stream: stream.write(stderr)
        events = [record.get('event') for record in result['records']]
        result['measurementComplete'] = (owner.returncode == 0 and events == ['ready', 'after-term', 'after-kill', 'reaped']
            and result['records'][-1].get('pid') == ready['leaderPID']
            and result['records'][-1].get('exitCode') == 7
            and result['records'][-2].get('livenessPipeClosed') is True)
        # These are observations, not a fallback policy or product acceptance.
        snapshot = ready['snapshot']
        result['observedAllZombies'] = {name: snapshot[name].get('allZombies') for name in ('libproc','sysctl')}
        result['expectedCandidateAllZombies'] = mode == 'solo'
        result['candidateControlMatched'] = all(value is (mode == 'solo') for value in result['observedAllZombies'].values())
    except BaseException as error:
        primary = error
        result.update(measurementComplete=False, errorType=type(error).__name__, errno=getattr(error, 'errno', None))
        raise
    finally:
        try: owner.close()
        except BaseException as error:
            result['cleanupErrorType'] = type(error).__name__
            result['measurementComplete'] = False
            if primary is None: raise
            primary.add_note('Diagnostic controller cleanup failed: ' + type(error).__name__)
        finally:
            write_json(destination, result)
            print('PROCESS OWNERSHIP CASE', destination.name, json.dumps(result, sort_keys=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin': parser.error('The real macOS kernel and SDK probe are required.')
    probe = args.probe.resolve(strict=True)
    if not probe.is_file() or not os.access(probe, os.X_OK): parser.error('An executable native probe is required.')
    os.umask(0o077); output = args.output.absolute(); output.mkdir(mode=0o700)
    profile = production_profile()
    with (output/'production.sb').open('x') as stream: stream.write(profile+'\n')
    metadata = os.stat('/bin/ps')
    report = {'schemaVersion': 1, 'kind': 'synthetic-process-ownership-diagnosis', 'productApproved': False,
              'commit': os.environ.get('GITHUB_SHA'), 'probeSHA256': hashlib.sha256(probe.read_bytes()).hexdigest(),
              'policySHA256': hashlib.sha256(profile.encode()).hexdigest(),
              'psMetadata': {'mode': stat.S_IMODE(metadata.st_mode), 'uid': metadata.st_uid, 'gid': metadata.st_gid,
                             'setuid': bool(metadata.st_mode & stat.S_ISUID), 'setgid': bool(metadata.st_mode & stat.S_ISGID)},
              'cases': {}, 'measurementComplete': False,
              'limitations': ['No Java or application validation is executed by these synthetic controls.',
                              'An inaccessible, empty, partial or live group never counts as proof that all members are zombies.',
                              'Candidate APIs are measured, not installed as a production fallback.']}
    try:
        for label, sandbox in [('unrestricted',None),('production-sandbox',profile)]:
            for mode in ('solo','live'):
                name=label+'-'+mode
                report['cases'][name] = case(probe,mode,sandbox,output/(name+'.json'))
        report['measurementComplete'] = all(item.get('measurementComplete') is True for item in report['cases'].values())
    finally:
        write_json(output/'report.json',report)
    print('PROCESS OWNERSHIP SUMMARY',json.dumps(report,sort_keys=True),flush=True)
    if not report['measurementComplete']: raise RuntimeError('The synthetic measurement did not complete.')


if __name__ == '__main__':
    # Standalone diagnostic policy only; no dependency on the uncommitted shared
    # CLI context. Imports do not change handlers and cleanup still owns its PGID.
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT,signal.SIGTERM)}
    def interrupted(number, _frame):
        for signum in previous: signal.signal(signum,signal.SIG_IGN)
        raise KeyboardInterrupt('Diagnostic interrupted by signal '+str(number))
    try:
        for number in previous: signal.signal(number,interrupted)
        main()
    finally:
        for number, handler in previous.items(): signal.signal(number,handler)
