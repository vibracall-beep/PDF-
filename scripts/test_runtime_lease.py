#!/usr/bin/env python3
"""Real exec/stdio and orphaned-direct-child coverage for the Python runtime."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent


class RuntimeLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'PDF.app'
        self.engine = self.bundle / 'Contents/Resources/engine'
        self.engine.mkdir(parents=True)
        shutil.copy2(ROOT / 'engine/runtime_lease.py', self.engine / 'runtime_lease.py')
        self.resource = self.bundle / 'Contents/Resources/installation.lock'
        self.resource.touch(); self.resource.chmod(0o444)
        self.payload = b'{"fixture":"stdin remains private and intact"}'

    def tearDown(self):
        self.temporary.cleanup()

    def start(self, code, mode='shared', actual=None, bundle=None):
        (self.engine / 'pdf_engine.py').write_text(code)
        descriptor = os.open(self.resource, os.O_RDONLY)
        fcntl.flock(descriptor, fcntl.LOCK_EX if (actual or mode) == 'exclusive' else fcntl.LOCK_SH)
        environment = dict(os.environ, PDF_RUNTIME_LEASE_STDERR=mode,
                           PDF_RUNTIME_LEASE_BUNDLE=str(bundle or self.bundle))
        for key in ('PDF_RUNTIME_LEASE_FD','PDF_RUNTIME_LEASE_MODE'):
            environment.pop(key, None)
        try:
            process = subprocess.Popen([sys.executable, '-E', '-s', '-B', str(self.engine / 'runtime_lease.py'),
                                        '--bootstrap', str(self.engine / 'pdf_engine.py')],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=descriptor,
                                       env=environment, start_new_session=True)
        finally:
            os.close(descriptor)
        return process

    def stop(self, process):
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        process.communicate(timeout=5)

    def exclusive_blocked(self):
        descriptor = os.open(self.resource, os.O_RDONLY)
        try:
            try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: return True
            return False
        finally:
            os.close(descriptor)

    def test_exec_preserves_private_stdin_and_restores_combined_stderr(self):
        code = 'import hashlib,json,sys\nfrom runtime_lease import inherited_fds\nprint(json.dumps({"hash":hashlib.sha256(sys.stdin.buffer.read()).hexdigest(),"fd":len(inherited_fds())}),flush=True)\nprint("stderr restored",file=sys.stderr,flush=True)\n'
        for mode in ('shared', 'exclusive'):
            with self.subTest(mode=mode):
                process = self.start(code, mode)
                output, _ = process.communicate(self.payload, timeout=5)
                self.assertEqual(process.returncode, 0, output)
                lines = output.decode().splitlines()
                self.assertEqual(json.loads(lines[0]), {'hash': hashlib.sha256(self.payload).hexdigest(), 'fd': 1})
                self.assertEqual(lines[1], 'stderr restored')
                self.assertFalse(self.exclusive_blocked())

    def test_exclusive_parent_cannot_be_silently_downgraded(self):
        process = self.start('raise AssertionError("must not execute")', mode='shared', actual='exclusive')
        output, _ = process.communicate(self.payload, timeout=5)
        self.assertEqual(process.returncode, 2)
        self.assertNotIn(self.payload, output)
        self.assertNotIn(b'AssertionError', output)

    def test_wrong_bundle_identity_is_rejected_without_echoing_payload(self):
        wrong = self.root / 'Other.app'; (wrong / 'Contents/Resources').mkdir(parents=True)
        other_resource = wrong / 'Contents/Resources/installation.lock'; other_resource.touch(); other_resource.chmod(0o444)
        process = self.start('raise AssertionError("must not execute")', bundle=wrong)
        output, _ = process.communicate(self.payload, timeout=5)
        self.assertEqual(process.returncode, 2)
        self.assertNotIn(self.payload, output)
        self.assertNotIn(str(wrong).encode(), output)

    def test_qpdf_carrier_preserves_stdin_and_does_not_pollute_json_stdout(self):
        runtime = self.bundle / 'Contents/Resources/runtime'
        (runtime / 'bin').mkdir(parents=True)
        (runtime / 'portable.json').write_text('{}')
        qpdf = runtime / 'bin/qpdf'
        fixture_script = runtime / 'qpdf fixture.py'
        interpreter = self.root / 'python interpreter'
        interpreter.symlink_to(sys.executable)
        fixture_script.write_text('import hashlib,json,os,sys\n'
                        'fd=int(os.environ["PDF_RUNTIME_LEASE_FD"])\n'
                        'print(json.dumps({"hash":hashlib.sha256(sys.stdin.buffer.read()).hexdigest(),"size":os.fstat(fd).st_size}),flush=True)\n'
                        'print("diagnostic must be discarded",file=sys.stderr)\n')
        qpdf.write_text('#!/bin/sh\nexec ' + shlex.quote(str(interpreter)) + ' ' + shlex.quote(str(fixture_script)) + ' "$@"\n')
        qpdf.chmod(0o755)
        for mode in ('shared', 'exclusive'):
            descriptor = os.open(self.resource, os.O_RDONLY)
            fcntl.flock(descriptor, fcntl.LOCK_EX if mode == 'exclusive' else fcntl.LOCK_SH)
            try:
                environment = dict(os.environ, PDF_RUNTIME_LEASE_STDERR=mode, PDF_RUNTIME_LEASE_BUNDLE=str(self.bundle))
                process = subprocess.Popen([sys.executable, str(self.engine / 'runtime_lease.py'), '--qpdf', str(qpdf),
                                            '--job-json-file=/dev/stdin'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=descriptor, env=environment)
            finally:
                os.close(descriptor)
            output, _ = process.communicate(self.payload, timeout=5)
            self.assertEqual(process.returncode, 0, output)
            self.assertEqual(json.loads(output), {'hash':hashlib.sha256(self.payload).hexdigest(), 'size':0})
            self.assertNotIn(b'diagnostic', output)

    def test_qpdf_carrier_rejects_other_programs_and_command_line_credentials(self):
        runtime = self.bundle / 'Contents/Resources/runtime'
        (runtime / 'bin').mkdir(parents=True)
        (runtime / 'portable.json').write_text('{}')
        qpdf = runtime / 'bin/qpdf'; qpdf.write_text('#!/bin/sh\nexit 99\n'); qpdf.chmod(0o755)
        for executable, arguments in ((Path('/bin/echo'), ['--job-json-file=/dev/stdin']),
                                      (qpdf, ['--password=private-fixture'])):
            descriptor = os.open(self.resource, os.O_RDONLY); fcntl.flock(descriptor, fcntl.LOCK_SH)
            try:
                environment = dict(os.environ, PDF_RUNTIME_LEASE_STDERR='shared', PDF_RUNTIME_LEASE_BUNDLE=str(self.bundle))
                process = subprocess.Popen([sys.executable, str(self.engine / 'runtime_lease.py'), '--qpdf', str(executable), *arguments],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=descriptor, env=environment)
            finally:
                os.close(descriptor)
            output, _ = process.communicate(self.payload, timeout=5)
            self.assertEqual(process.returncode, 2)
            self.assertNotIn(b'private-fixture', output)
            self.assertNotIn(self.payload, output)

    def test_direct_converter_retains_lease_after_engine_sigkill(self):
        # Execute the production _external with a direct child that publishes a
        # private ready receipt and stays alive. Killing only the engine cannot
        # make the bundle available for replacement while that child remains.
        ready = self.root / 'converter-ready.json'
        child = 'import json,os,time;from pathlib import Path;Path(' + repr(str(ready)) + ').write_text(json.dumps({"pid":os.getpid()}));time.sleep(30)'
        # Execute the actual production function AST, without importing optional
        # PDF dependencies before CI installs its venv. The function body is not
        # copied into the test or replaced by a stand-in.
        code = ('import ast,os,signal,subprocess,sys\nfrom pathlib import Path\n'
                'tree=ast.parse(Path(' + repr(str(ROOT / 'engine/pdf_engine.py')) + ').read_text())\n'
                'function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=="_external")\n'
                'exec(compile(ast.Module(body=[function],type_ignores=[]),"production_external","exec"))\n'
                '_external([sys.executable,"-c",' + repr(child) + '],timeout=30)\n')
        for mode in ('shared', 'exclusive'):
            with self.subTest(mode=mode):
                ready.unlink(missing_ok=True)
                process = self.start(code, mode)
                try:
                    process.stdin.write(self.payload); process.stdin.close(); process.stdin = None
                    deadline = time.monotonic() + 5
                    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists(), 'production converter did not reach its ready receipt')
                    child_id = json.loads(ready.read_text())['pid']
                    self.assertTrue(self.exclusive_blocked())
                    process.kill(); process.wait(timeout=5)
                    self.assertEqual(process.returncode, -signal.SIGKILL)
                    self.assertTrue(self.exclusive_blocked(), 'engine crash released a live direct converter lease')
                    os.kill(child_id, signal.SIGKILL)
                    deadline = time.monotonic() + 5
                    while self.exclusive_blocked() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertFalse(self.exclusive_blocked())
                finally:
                    if ready.exists():
                        try: os.kill(json.loads(ready.read_text())['pid'], signal.SIGKILL)
                        except ProcessLookupError: pass
                    self.stop(process)


if __name__ == '__main__':
    unittest.main()
