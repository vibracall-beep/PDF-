"""Real CLI cancellation must unwind before private child groups are forgotten."""
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from owned_process import ProcessInterrupted, cooperative_signals


class CooperativeCLITests(unittest.TestCase):
    def test_imports_do_not_replace_callers_signal_handlers(self):
        source = '''import signal,sys
sys.path[:0]=[sys.argv[1]+'/engine',sys.argv[1]+'/diagnostics']
previous={number:signal.getsignal(number) for number in (signal.SIGINT,signal.SIGTERM)}
import owned_process,run_pdfkit_diagnostics,portable_office_diagnostics
assert all(signal.getsignal(number)==handler for number,handler in previous.items())
print('unchanged')
'''
        result=subprocess.run([sys.executable,'-I','-c',source,str(ROOT)],capture_output=True,timeout=5)
        self.assertEqual((result.returncode,result.stdout),(0,b'unchanged\n'),result.stderr)

    def test_first_signal_unwinds_and_repeated_signals_do_not_interrupt_cleanup(self):
        previous={number:signal.getsignal(number) for number in (signal.SIGINT,signal.SIGTERM)}
        for requested in (signal.SIGINT,signal.SIGTERM):
            with self.subTest(signal=requested):
                with self.assertRaises(ProcessInterrupted) as caught:
                    with cooperative_signals():
                        try: os.kill(os.getpid(),requested)
                        finally:
                            for number in previous:
                                self.assertEqual(signal.getsignal(number),signal.SIG_IGN)
                                os.kill(os.getpid(),number)
                self.assertEqual(caught.exception.number,requested)
                self.assertEqual({number:signal.getsignal(number) for number in previous},previous)
        with self.assertRaisesRegex(ValueError,'normal failure'):
            with cooperative_signals(): raise ValueError('normal failure')
        self.assertEqual({number:signal.getsignal(number) for number in previous},previous)

    def test_pdfkit_and_office_cli_cancel_real_groups_and_release_descendant_locks(self):
        with tempfile.TemporaryDirectory(prefix='PDF CLI cancellation ') as temporary:
            root=Path(temporary)
            runtime=root/'Library/Application Support/PDF';runtime.mkdir(parents=True)
            interpreter=runtime/'python3';interpreter.symlink_to(sys.executable)
            for kind in ('pdfkit','office'):
                for requested in (signal.SIGINT,signal.SIGTERM):
                    with self.subTest(driver=kind,signal=requested):
                        case=root/f'{kind}-{requested}';case.mkdir()
                        marker=case/'ready.json';lock=case/'child.lock';child=case/'synthetic-engine'
                        child_script=case/'synthetic engine.py'
                        child_script.write_text('''import fcntl,json,os,signal,time
from pathlib import Path
signal.signal(signal.SIGINT,signal.SIG_IGN)
signal.signal(signal.SIGTERM,signal.SIG_IGN)
read,write=os.pipe();descendant=os.fork()
if descendant==0:
 os.close(read)
 descriptor=os.open(__LOCK_PATH__,os.O_CREAT|os.O_RDWR,0o600)
 fcntl.flock(descriptor,fcntl.LOCK_EX)
 os.write(write,b'ready');os.close(write)
 time.sleep(15);os._exit(0)
os.close(write);assert os.read(read,5)==b'ready';os.close(read)
Path(__MARKER_PATH__).write_text(json.dumps(dict(pid=os.getpid(),descendant=descendant)))
time.sleep(15)
'''.replace('__LOCK_PATH__',repr(str(lock))).replace('__MARKER_PATH__',repr(str(marker))))
                        # Kernels do not interpret a quoted interpreter path in
                        # a shebang. Exercise the installed venv's space-bearing
                        # path using an actual shell exec with two quoted argv.
                        child.write_text('#!/bin/sh\nexec '+shlex.quote(str(interpreter))+' '
                                         +shlex.quote(str(child_script))+' "$@"\n')
                        child.chmod(0o700)
                        output=case/'output'
                        if kind=='pdfkit':
                            # The actual CLI runs this as its first qpdf invocation.
                            command=[sys.executable,str(ROOT/'diagnostics/run_pdfkit_diagnostics.py'),
                                     '--executable',str(child),'--qpdf',str(child),'--output',str(output)]
                        else:
                            # Only the macOS-only workload is replaced. The real
                            # entrypoint, owner, signal policy and cleanup execute.
                            source='''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/diagnostics')
import portable_office_diagnostics as office
office.main=lambda:office.measure([sys.argv[2]],Path(sys.argv[3]),seconds=20)
raise SystemExit(office.run_main())
'''
                            command=[sys.executable,'-c',source,str(ROOT),str(child),str(output)]
                        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                        try:
                            deadline=time.monotonic()+5
                            while not marker.exists() and process.poll() is None and time.monotonic()<deadline:
                                time.sleep(.01)
                            if not marker.exists():
                                startup_error=b'Process still running; stderr was not read before collection.'
                                if process.poll() is not None:
                                    _,startup_error=process.communicate(timeout=1)
                                self.fail('The actual descendant must hold its lock before cancellation; '
                                          +'bootstrap exit='+str(process.returncode)+'; stderr='
                                          +startup_error.decode(errors='replace')[:8192])
                            identities=json.loads(marker.read_text())
                            self.assertNotEqual(identities['pid'],identities['descendant'])
                            process.send_signal(requested)
                            time.sleep(.1)
                            process.send_signal(signal.SIGTERM if requested==signal.SIGINT else signal.SIGINT)
                            stdout,stderr=process.communicate(timeout=8)
                            self.assertEqual(process.returncode,128+requested,stderr)
                            with lock.open('rb') as stream:
                                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                            if kind=='pdfkit':
                                report=json.loads((output/'PDFKit-diagnostics.json').read_text())
                                self.assertIs(report['measurementComplete'],False)
                                self.assertIn('ProcessInterrupted',report['measurementError'])
                        finally:
                            if process.poll() is None: process.kill()
                            process.communicate(timeout=5)
