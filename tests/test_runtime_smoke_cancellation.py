"""A real imported engine conversion must unwind on the smoke supervisor's TERM."""
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from portable_isolation import private_namespace, run_owned


class RuntimeSmokeCancellationTests(unittest.TestCase):
    def test_timeout_unwinds_imported_engine_new_session_before_namespace_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='runtime smoke cancellation ') as temporary:
            fixture = Path(temporary).resolve(); binaries = fixture / 'bin'; binaries.mkdir()
            lock = fixture / 'converter.lock'; ready = fixture / 'converter.json'
            converter = fixture / 'converter.py'
            converter.write_text('import fcntl,json,os,signal,sys,time\nfrom pathlib import Path\n'
                'fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\n'
                'fcntl.flock(fd,fcntl.LOCK_EX)\n'
                'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                'Path(sys.argv[2]).write_text(json.dumps({"pid":os.getpid(),"group":os.getpgrp()}))\n'
                'time.sleep(30)\n')
            soffice = binaries / 'soffice'
            soffice.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(converter))
                + ' ' + shlex.quote(str(lock)) + ' ' + shlex.quote(str(ready)) + ' "$@"\n')
            soffice.chmod(0o755)
            source = fixture / 'input.docx'; source.write_bytes(b'synthetic converter cancellation fixture')
            caller = fixture / 'imported engine caller.py'
            caller.write_text('import os,sys\nfrom pathlib import Path\n'
                'sys.path[:0]=[' + repr(str(ROOT / 'scripts')) + ',' + repr(str(ROOT / 'engine')) + ']\n'
                'import check_runtime\nfrom pdf_engine import run\n'
                'def conversion():\n'
                '    Path(sys.argv[3]).write_text(str(os.getpgrp()))\n'
                '    run("office",[sys.argv[1]],sys.argv[2],{})\n'
                'check_runtime.main=conversion\ncheck_runtime.run_main()\n')
            environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ.get('PATH', ''))
            target = fixture / 'output.pdf'; caller_group = fixture / 'caller-group'
            with self.assertRaises(subprocess.TimeoutExpired):
                with private_namespace() as (namespace, ipc, outside, state):
                    state['workloadsStarted'] = True
                    run_owned([sys.executable, caller, source, target, caller_group], seconds=2,
                              environment=environment, capture=True)
            self.assertTrue(ready.is_file(), 'The term-ignoring converter must actually start.')
            child = json.loads(ready.read_text())
            self.assertNotEqual(child['group'], int(caller_group.read_text()), 'The converter must own a different session.')
            with lock.open('rb') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(state['children'][0]['cleanupConfirmed'])
            # A timeout is conservatively unverified transitively, even though
            # this fixture can independently prove its converter released the
            # lock. Only this test removes its own root after that proof.
            self.assertTrue(state['preserved']); self.assertTrue(state['transitiveCleanupUnverified'])
            self.assertFalse(state['removed']); self.assertTrue(namespace.exists())
            self.assertFalse(target.exists()); self.assertFalse(list(fixture.glob('.pdf-output-*')))
            shutil.rmtree(namespace)


if __name__ == '__main__': unittest.main()
